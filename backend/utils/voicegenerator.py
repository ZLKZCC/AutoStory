import os
import gc
import time
import torch
import psutil
import subprocess
from pathlib import Path
from config.store import conf
from typing import List, Optional
from qwen_tts import Qwen3TTSModel
from utils.audio import convert_audio

DEFAULT_REF_TEXT = "你好，这是一段测试音频"

VOICE_QUALITY_SUFFIX = "语气自然，吐字清晰"
_VOICE_QUALITY_KEYS = ("自然", "清晰")


def ensure_voice_quality(desc: str) -> str:
    """提示词质量保底：desc 不含任何质量关键词时补一句通用约束。
    已含（用户/LLM 描述里写过自然、清晰之类）则原样返回，不覆盖已有意图、不堆词。"""
    if not desc:
        return desc
    if any(k in desc for k in _VOICE_QUALITY_KEYS):
        return desc
    return f"{desc.rstrip('。')}。{VOICE_QUALITY_SUFFIX}。"


def _model_path(model_type: str) -> str:
    """模型类型 → 本地模型目录（conf 单点注册）"""
    path_map = {
        "base": conf.Voice_Base_MODEL_DIR,
        "voice_design": conf.Voice_VoiceDesign_MODEL_DIR,
        "custom_voice": conf.Voice_CustomVoice_MODEL_DIR,
    }
    model_path = path_map.get(model_type)
    if not model_path:
        raise ValueError(f"未知模型类型: {model_type}")
    return str(model_path)


def estimate_model_memory(model_type: str) -> int:
    """估算模型加载所需显存/内存（字节）

    实测（RTX 4060 Laptop 8GB，VoiceDesign）：bf16 权重 1:1 驻留 GPU，
    短文本推理开销 ≈ 0（峰值 4.2GB ≈ 权重 4.31GB）。
    故按 权重 + 0.5GB 固定余量 估算（长文本激活略增，余量覆盖）。
    """
    size = sum(
        f.stat().st_size for f in Path(_model_path(model_type)).rglob("*") if f.is_file()
    )
    if size <= 0:
        raise ValueError(f"模型目录为空: {model_type}")
    return size + 500 * 1024 * 1024


def _smi_free_bytes() -> Optional[int]:
    """nvidia-smi 驱动级空闲显存（字节）；不可用时返回 None

    Windows WDDM 下 torch.cuda.mem_get_info 不反映其他进程的显存占用，
    需以 nvidia-smi 读数为准做交叉校验。
    """
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.free",
             "--format=csv,noheader,nounits"],
            text=True, timeout=5,
        ).strip().splitlines()
        return int(out[0]) * 1024 * 1024
    except Exception:
        return None


def probe_device(
    model_type: str,
    retries: int = 3,
    wait_seconds: float = 5.0,
) -> str:
    """
    实例化前资源探测（同步，供 executor 线程调用；重试等待会阻塞，勿在事件循环直接调）。
    GPU 优先，CPU 是重试穷尽后的降级，而非并行备选：
    - 无 CUDA → CPU 空闲内存够即 cpu（等待无意义，GPU 不存在）
    - GPU 空闲显存足够（torch 与 nvidia-smi 双口径，取小）→ cuda:0
    - GPU 可用但空闲不足（典型：前任务刚 release、WDDM 驱动级读数回收有延迟，
      smi 仍显示被占）→ 按 wait_seconds × retries 等待重试，显存回收即返回 GPU；
      穷尽后 CPU 空闲内存够 → 降级 cpu（日志明示，推理会明显变慢）
    - GPU/CPU 上限均低于需求 → 硬件性不足，直接抛错（等待也不可能满足）
    - 上限够但重试穷尽仍不足 → 抛错提醒用户关闭占用程序
    """
    need = estimate_model_memory(model_type)
    have_cuda = torch.cuda.is_available()
    if not have_cuda:
        print("[Resource] torch.cuda 不可用（CUDA 未安装/驱动异常/进程初始化失败），跳过 GPU")

    # 上限判定放在循环外：硬件性不足等待无意义，直接抛
    gpu_cap = have_cuda and torch.cuda.get_device_properties(0).total_memory >= need
    cpu_cap = psutil.virtual_memory().total >= need
    if not (gpu_cap or cpu_cap):
        raise ValueError(
            f"GPU 显存与 CPU 内存均低于模型所需（约 {need / 1024**3:.1f}GB），无法实例化"
        )

    for attempt in range(retries + 1):
        # ── GPU 优先：双口径空闲显存（WDDM 下 torch 不反映其他进程，smi 是驱动级
        #    读数、刚 release 完的显存回收有延迟 → 此处必须等待重试，不能立即降级）
        if have_cuda:
            torch_free, _ = torch.cuda.mem_get_info()
            smi_free = _smi_free_bytes()
            gpu_free = min(torch_free, smi_free) if smi_free is not None else torch_free
            if gpu_free >= need:
                print(f"[Resource] {model_type} -> cuda:0 (need {need / 1024**3:.1f}GB)")
                return "cuda:0"
            print(
                f"[Resource] GPU 空闲不足: torch={torch_free / 1024**3:.1f}GB"
                + (f" nvidia-smi={smi_free / 1024**3:.1f}GB" if smi_free is not None else "")
                + f" need={need / 1024**3:.1f}GB"
                + (f"，{wait_seconds}s 后重试 ({attempt + 1}/{retries})" if attempt < retries else "，重试已穷尽")
            )
        elif psutil.virtual_memory().available >= need:
            print(f"[Resource] {model_type} -> cpu (need {need / 1024**3:.1f}GB)")
            return "cpu"

        if attempt < retries:
            time.sleep(wait_seconds)

    # ── 重试穷尽：GPU 仍不足 → CPU 内存够则降级（明示变慢），否则抛错
    if psutil.virtual_memory().available >= need:
        print(f"[Resource] GPU 重试 {retries} 次仍不足，{model_type} 降级 -> cpu "
              f"(need {need / 1024**3:.1f}GB；CPU 推理会明显变慢)")
        return "cpu"
    raise RuntimeError(
        f"等待重试 {retries} 次后资源仍不足（需约 {need / 1024**3:.1f}GB），"
        "请关闭占用 GPU/内存的程序后重试"
    )


class VoiceGenerator:
    """语音生成器 (Qwen3-TTS)：独立实例，用完必须 release() 释放"""

    def __init__(self, device: Optional[str] = None, dtype=None, attn_implementation: str = "sdpa"):
        # device 由 probe_device 探测结果指定；缺省时自动选择
        self.device = (
            torch.device(device)
            if device
            else torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        )
        self.dtype = dtype or torch.bfloat16
        print(self.device)
        self.attn_impl = attn_implementation
        self._models: dict = {}
        self._prompts: dict = {}

    def release(self):
        """释放实例持有的模型与音色资源（用完必须调用，避免实例间互相干扰）

        关键点：
        - 显式 del 每个模型对象（触发 __del__，释放 GPU 张量引用）
        - 把模型先移到 CPU（让 GPU 张量从 device_map 持有转为 CPU 张量，
          GPU 引用计数降为 0，empty_cache 才能真正回收显存）
        - torch.cuda.synchronize() 等所有 CUDA 异步操作完成
        - 两轮 GC（处理模型内部循环引用）+ 两轮 empty_cache
          （GC 后张量被回收，cache 才能再次清理出空间）

        若仅 _models.clear() + 一次 empty_cache，模型张量不会真正释放，
        GPU 显存残留约 1-2GB，下次 design 兜底再分配 4.7GB 时总显存不够。
        """
        for model_type, model in list(self._models.items()):
            try:
                # 先移到 CPU：device_map 持有的 GPU 张量转 CPU，释放 GPU 引用
                if hasattr(model, "cpu"):
                    model.cpu()
                # 显式 del，触发 __del__，引用计数降一
                del model
            except Exception as e:
                print(f"[System] release model {model_type} failed: {e}")
        self._models.clear()
        self._prompts.clear()

        if torch.cuda.is_available():
            # 等所有 CUDA 异步操作完成（避免张量还在用）
            torch.cuda.synchronize()
            torch.cuda.empty_cache()

        # 两轮 GC（循环引用可能要两轮）+ 两轮 empty_cache（GC 后张量释放再清 cache）
        gc.collect()
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        print("[System] VoiceGenerator resources released")

    def unload(self, model_type: str):
        """只卸载单个模型（保留已注册的音色指纹 _prompts），并真正回收显存。

        两趟合成用：base 提完指纹 / 念完无情绪段后先卸掉，给 custom_voice 腾出 8GB 单卡空间，
        保证 base 与 custom_voice 永不同时驻留（否则 4.2+4.2>8GB 必 OOM）。
        """
        model = self._models.pop(model_type, None)
        if model is None:
            return
        try:
            if hasattr(model, "cpu"):
                model.cpu()      # 先把 GPU 张量转 CPU，GPU 引用计数归零，empty_cache 才收得回
            del model
        except Exception as e:
            print(f"[System] unload {model_type} failed: {e}")
        if torch.cuda.is_available():
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
        gc.collect()
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        print(f"[System] VoiceGenerator unloaded {model_type}")

    # ── 模型管理 ──────────────────────────────────────────

    def _load_model(self, model_type: str = "base") -> Qwen3TTSModel:
        """懒加载模型"""
        if model_type in self._models:
            return self._models[model_type]

        model_path_str = _model_path(model_type)

        print(f"[System] Loading {model_type} model...")
        t0 = time.time()

        try:
            model = Qwen3TTSModel.from_pretrained(
                model_path_str,
                local_files_only=True,
                device_map=self.device,
                dtype=self.dtype,
                attn_implementation=self.attn_impl,
            )
        except Exception as e:
            # CUDA 显存不足回退到 CPU
            if self.device != "cpu":
                print(f"[System] CUDA load failed ({e}), fallback to CPU")
                torch.cuda.empty_cache()
                model = Qwen3TTSModel.from_pretrained(
                    model_path_str,
                    local_files_only=True,
                    device_map="cpu",
                    dtype=self.dtype,
                    attn_implementation=self.attn_impl,
                )
                self.device = "cpu"
            else:
                raise

        print(f"[System] {model_type} loaded ({time.time() - t0:.1f}s)")
        self._models[model_type] = model
        return model

    # ── 核心功能 ───────────────────────────────────────────

    def design_voice(self, voice_desc: str, sample_text: str, output_path: Optional[str] = None):
        """根据描述生成参考音色。
        instruct 过 ensure_voice_quality 保底：缺质量关键词的描述补一句通用约束
        （角色音色生成 / 合成 design 兜底 / 旁白试听三入口都走这里，一处收口）。"""
        model = self._load_model("voice_design")
        wavs, sr = model.generate_voice_design(
            text=sample_text,
            instruct=ensure_voice_quality(voice_desc),
        )
        if output_path and wavs:
            import soundfile as sf
            sf.write(output_path, wavs[0], sr)
        return wavs, sr

    def register(self, voice_id: str, ref_audio_path: str, ref_text: str):
        """注册音色"""
        if voice_id in self._prompts:
            return
        print(f"[Register] {voice_id}")
        model = self._load_model("base")
        # create_voice_clone_prompt 返回 List[VoiceClonePromptItem]（批量接口，单个参考音也是列表），
        # 原样存列表；下游 generate / _generate_emotional 按「扁平 item 列表」消费，勿再包一层
        prompt = model.create_voice_clone_prompt(
            ref_audio=ref_audio_path,
            ref_text=ref_text
        )
        self._prompts[voice_id] = prompt

    def generate(
        self,
        voice_id: str,
        text: str,
        emotion: Optional[str] = None,
        language: str = "Chinese",
        output_path: Optional[str] = None,
        return_type: str = "pydub",
        **kwargs
    ):
        """生成语音"""
        if voice_id not in self._prompts:
            raise KeyError(f"音色 '{voice_id}' 未注册")
        if not text or not text.strip():
            raise ValueError("text 不能为空")

        t0 = time.time()

        if emotion:
            wavs, sr = self._generate_emotional(voice_id, text, emotion, language, **kwargs)
        else:
            model = self._load_model("base")
            prompt = self._prompts[voice_id]

            # _prompts 里存的就是 create_voice_clone_prompt 的返回值（扁平 item 列表），
            # generate_voice_clone 直接收这种列表；再包一层 [prompt] 会变嵌套列表，
            # 库内 it.ref_code 直接 AttributeError（正式合成被吞成静音占位，整本即无声）
            wavs, sr = model.generate_voice_clone(
                text=text,
                language=language,
                voice_clone_prompt=prompt,
                **kwargs,
            )

        dur = len(wavs[0]) / sr if wavs else 0
        print(f"[Generate] {voice_id} -> {dur:.2f}s ({time.time()-t0:.1f}s)")

        if output_path and wavs:
            import soundfile as sf
            sf.write(output_path, wavs[0], sr)

        return convert_audio(wavs, sr, return_type)

    def _generate_emotional(
        self,
        voice_id: str,
        text: str,
        emotion: str,
        language: str = "Chinese",
        **kwargs
    ):
        """情感语音生成 (CustomVoice 模型)

        只需 custom_voice 一个模型：base 与 custom_voice 各 ~4.2GB，8GB 单卡装不下两个。
        原先这里 `_load_model("base")` 仅为调 `_prompt_items_to_voice_clone_prompt`——
        而它是纯 dict 重组（只用 register 时 base 已提取好的 ref_spk_embedding），不碰模型/GPU。
        故直接手拼 vcp，**不加载 base**，让 base 与 custom_voice 永不共存（两趟合成的前提）。
        """
        cv_model = self._load_model("custom_voice")
        # _prompts 存的是 item 列表（register 单个参考音 → 长度恒为 1），取首个用
        item = self._prompts[voice_id][0]

        # 等价于 base_model._prompt_items_to_voice_clone_prompt([item]) 再覆盖三个字段：
        # x_vector_only_mode=True / icl_mode=False / ref_code=None（只保留说话人指纹）
        vcp = {
            "ref_code": [None],
            "ref_spk_embedding": [item.ref_spk_embedding],
            "x_vector_only_mode": [True],
            "icl_mode": [False],
        }

        input_texts = [cv_model._build_assistant_text(text)]
        input_ids = cv_model._tokenize_texts(input_texts)

        # 情绪 instruct 同样过质量保底（emotion 只有"开心/愤怒"这类词时永远缺关键词），
        # 防带情绪段也念得干瘪；desc 已含质量词时原样返回不重复堆
        instruct_text = cv_model._build_instruct_text(ensure_voice_quality(emotion))
        instruct_ids = [cv_model._tokenize_texts([instruct_text])[0]]

        gen_kwargs = cv_model._merge_generate_kwargs(**kwargs)

        # 底层 model.generate 的 voice_clone_prompt 按 dict 消费
        # （库源码 generate_speaker_prompt 里 voice_clone_prompt["ref_spk_embedding"] 下标访问；
        # 其类型标注 list[dict] 有误导性），传 [vcp] 会 TypeError
        talker_codes_list, _ = cv_model.model.generate(
            input_ids=input_ids,
            instruct_ids=instruct_ids,
            voice_clone_prompt=vcp,
            languages=[language],
            non_streaming_mode=True,
            **gen_kwargs,
        )

        wavs, sr = cv_model.model.speech_tokenizer.decode(
            [{"audio_codes": c} for c in talker_codes_list]
        )

        return wavs, sr

    def generate_batch(
        self,
        voice_id: str,
        texts: List[str],
        output_dir: Optional[str] = None,
        **kwargs
    ) -> list:
        """批量生成"""
        results = []
        for idx, t in enumerate(texts):
            out_path = os.path.join(output_dir, f"{idx:04d}.wav") if output_dir else None
            results.append(self.generate(voice_id, t, output_path=out_path, **kwargs))
        return results
