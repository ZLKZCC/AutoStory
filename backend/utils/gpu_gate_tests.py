import asyncio
import sys
from contextlib import suppress

from utils.gpu_gate import (
    _GpuGate, VRAM_TTS, VRAM_EMBED, MAX_CONCURRENT, SAFETY_FRACTION, _GB,
)


def make_gate(total_gb: float | None = None, unlimited: bool = False) -> _GpuGate:
    """造一把闸并注入预算（绕过 torch 真机探测）：total_gb=显卡总显存，unlimited=CPU。"""
    g = _GpuGate()
    if unlimited:
        g._unlimited = True
    elif total_gb is not None:
        g._budget = int(total_gb * _GB * SAFETY_FRACTION)   # 与 _ensure_budget 同口径
    else:
        g._unlimited = True
    return g


async def measure_max_concurrent(g: _GpuGate, need: int, n_tasks: int, hold: float = 0.05) -> int:
    """并发跑 n_tasks 个 reserve(need)，返回同时在闸内的最大数量。"""
    live = 0
    maxlive = 0

    async def one():
        nonlocal live, maxlive
        async with g.reserve(need):
            live += 1
            maxlive = max(maxlive, live)
            await asyncio.sleep(hold)
            live -= 1

    await asyncio.gather(*[one() for _ in range(n_tasks)])
    return maxlive


# ── 1 VRAM 限流缩放 ──────────────────────────────────────────
async def test_vram_scaling():
    # (总显存GB, 期望最大并发合成路数)：bge-m3 常驻 VRAM_EMBED 先扣，余量按 VRAM_TTS 分
    cases = [(8, 1), (12, 1), (16, 2), (24, 4), (48, MAX_CONCURRENT)]
    for total_gb, expected in cases:
        g = make_gate(total_gb)
        await g.reserve_permanent(VRAM_EMBED)
        got = await measure_max_concurrent(g, VRAM_TTS, n_tasks=8)
        assert got == expected, f"{total_gb}GB 卡：期望最大并发 {expected}，实测 {got}"


# ── 2 并发硬封顶 ────────────────────────────────────────────
async def test_max_concurrent_cap():
    g = make_gate(200)          # 显存极大，预算远超需要
    await g.reserve_permanent(VRAM_EMBED)
    got = await measure_max_concurrent(g, VRAM_TTS, n_tasks=12)
    assert got == MAX_CONCURRENT, f"显存再大也应封顶 {MAX_CONCURRENT}，实测 {got}"


# ── 3 CPU/无 CUDA ───────────────────────────────────────────
async def test_cpu_unlimited_capped():
    g = make_gate(unlimited=True)
    await g.reserve_permanent(VRAM_EMBED)
    got = await measure_max_concurrent(g, VRAM_TTS, n_tasks=10)
    assert got == MAX_CONCURRENT, f"CPU 不限显存但应受并发上限 {MAX_CONCURRENT}，实测 {got}"


# ── 4 安全阀防饿死 ──────────────────────────────────────────
async def test_safety_valve_no_starvation():
    g = make_gate(3)            # 预算 ~2.85GB < 单个 VRAM_TTS(4.5GB)
    await g.reserve_permanent(VRAM_EMBED)
    assert g._budget < VRAM_TTS, "本用例要求预算小于单任务占用"
    done = 0

    async def one():
        nonlocal done
        async with g.reserve(VRAM_TTS):
            await asyncio.sleep(0.02)
            done += 1

    # 关键：全部任务都应在合理时间内完成（安全阀放行一个、跑完释放、下一个再进），不死锁
    await asyncio.wait_for(asyncio.gather(*[one() for _ in range(5)]), timeout=5)
    assert done == 5, f"安全阀应保证不饿死，5 个任务应全完成，实际 {done}"
    assert g._transient == 0


# ── 5 异常释放锁 ────────────────────────────────────────────
async def test_exception_releases():
    g = make_gate(24)
    await g.reserve_permanent(VRAM_EMBED)
    base = g._committed
    with suppress(RuntimeError):
        async with g.reserve(VRAM_TTS):
            assert g._transient == 1
            raise RuntimeError("boom")
    assert g._transient == 0 and g._committed == base, "reserve 内异常后未释放锁"
    # 后续仍能正常申请
    async with g.reserve(VRAM_TTS):
        assert g._transient == 1
    assert g._transient == 0 and g._committed == base


# ── 6 取消释放锁（持有中）────────────────────────────────────
async def test_cancel_while_holding():
    g = make_gate(24)
    await g.reserve_permanent(VRAM_EMBED)
    base = g._committed
    entered = asyncio.Event()

    async def holder():
        async with g.reserve(VRAM_TTS):
            entered.set()
            await asyncio.sleep(30)      # 会被 cancel

    t = asyncio.create_task(holder())
    await asyncio.wait_for(entered.wait(), timeout=2)
    assert g._transient == 1 and g._committed == base + VRAM_TTS
    t.cancel()
    with suppress(asyncio.CancelledError):
        await t
    assert g._transient == 0 and g._committed == base, "取消持有者后未释放锁"


# ── 7 取消释放锁（排队中）────────────────────────────────────
async def test_cancel_while_waiting():
    g = make_gate(8)            # 8GB：常驻扣掉后一次只容一路合成
    await g.reserve_permanent(VRAM_EMBED)
    holder_in = asyncio.Event()
    release = asyncio.Event()

    async def holder():
        async with g.reserve(VRAM_TTS):
            holder_in.set()
            await release.wait()

    async def waiter():
        async with g.reserve(VRAM_TTS):
            pass

    h = asyncio.create_task(holder())
    await asyncio.wait_for(holder_in.wait(), timeout=2)
    w = asyncio.create_task(waiter())
    await asyncio.sleep(0.08)   # 让 waiter 进入排队
    assert g._transient == 1, "排队中的 waiter 不应计入 transient"
    w.cancel()
    with suppress(asyncio.CancelledError):
        await w
    assert g._transient == 1, "取消排队者后 holder 仍应持有"
    release.set()
    await h
    assert g._transient == 0 and g._committed == VRAM_EMBED, "holder 结束后应回到常驻基线"


# ── 8 常驻预留 ──────────────────────────────────────────────
async def test_permanent_reservation():
    g = make_gate(24)
    await g.reserve_permanent(VRAM_EMBED)
    assert g._transient == 0, "常驻占用不应计入瞬态并发名额"
    assert g._committed == VRAM_EMBED, "常驻占用应计入 committed（扣预算）"
    # 常驻不占并发名额：24GB 下瞬态仍可并行到封顶
    got = await measure_max_concurrent(g, VRAM_TTS, n_tasks=8)
    assert got == MAX_CONCURRENT, f"常驻不应挤占瞬态名额，期望 {MAX_CONCURRENT}，实测 {got}"
    assert g._committed == VRAM_EMBED, "瞬态全部释放后应只剩常驻占用"


# ── 9 would_wait ────────────────────────────────────────────
async def test_would_wait():
    g = make_gate(8)
    await g.reserve_permanent(VRAM_EMBED)
    assert g.would_wait(VRAM_TTS) is False, "空闸（仅常驻）应能放行，不排队"
    holder_in = asyncio.Event()
    release = asyncio.Event()

    async def holder():
        async with g.reserve(VRAM_TTS):
            holder_in.set()
            await release.wait()

    h = asyncio.create_task(holder())
    await asyncio.wait_for(holder_in.wait(), timeout=2)
    assert g.would_wait(VRAM_TTS) is True, "8GB 已被一路合成占满，再来应排队"
    release.set()
    await h
    assert g.would_wait(VRAM_TTS) is False, "释放后应不再排队"


# ── 10 释放后恢复容量 ───────────────────────────────────────
async def test_release_restores_capacity():
    g = make_gate(8)            # 一次一路
    await g.reserve_permanent(VRAM_EMBED)
    done = 0

    async def one():
        nonlocal done
        async with g.reserve(VRAM_TTS):
            await asyncio.sleep(0.02)
            done += 1

    await asyncio.wait_for(asyncio.gather(*[one() for _ in range(4)]), timeout=5)
    assert done == 4, f"串行 4 个应全完成，实际 {done}"
    assert g._transient == 0 and g._committed == VRAM_EMBED


TESTS = [
    ("VRAM 限流缩放", test_vram_scaling),
    ("并发硬封顶", test_max_concurrent_cap),
    ("CPU 不限显存但封顶", test_cpu_unlimited_capped),
    ("安全阀防饿死", test_safety_valve_no_starvation),
    ("异常释放锁", test_exception_releases),
    ("取消释放锁(持有中)", test_cancel_while_holding),
    ("取消释放锁(排队中)", test_cancel_while_waiting),
    ("常驻预留不占并发名额", test_permanent_reservation),
    ("would_wait 预判", test_would_wait),
    ("释放后恢复容量", test_release_restores_capacity),
]


async def _run_all() -> int:
    print(f"gpu_gate 模拟测试 | VRAM_TTS={VRAM_TTS/_GB:.1f}GB VRAM_EMBED={VRAM_EMBED/_GB:.1f}GB "
          f"SAFETY_FRACTION={SAFETY_FRACTION} MAX_CONCURRENT={MAX_CONCURRENT}")
    print("-" * 60)
    passed = failed = 0
    for name, fn in TESTS:
        try:
            await fn()
            print(f"  PASS  {name}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {name}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR {name}: {type(e).__name__}: {e}")
            failed += 1
    print("-" * 60)
    print(f"{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_run_all()))
