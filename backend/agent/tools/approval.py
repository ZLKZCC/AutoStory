from langgraph.types import interrupt


def request_approval(payload: dict, call_id: str = "") -> dict:
    """统一中断点：发提案 → 收用户裁决。

    call_id 并入 payload，让前端把 resume 后回来的 tool_result 按 call_id 绑回这张人审卡，
    据此得知本次确认的真实成败，而不是乐观假设成功。
    """
    if call_id:
        payload = {**payload, "call_id": call_id}
    answer = interrupt(payload)
    if not isinstance(answer, dict):
        return {"approved": False, "reason": "未识别的响应"}
    return answer
