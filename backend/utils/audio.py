from typing import List, Union, Tuple
import numpy as np
from pydub import AudioSegment


def _to_numpy(x):
    """把 TTS 返回的音频统一成 numpy float 数组。

    qwen_tts 的 generate 可能返回 torch.Tensor（而非 numpy）；torch 张量没有 .astype，
    下面 (wav*32767).astype(np.int16) 会抛 AttributeError → 每段合成都失败 → 全静音。
    这里先 detach/cpu/numpy 兜住两种类型。
    """
    if hasattr(x, "detach"):          # torch.Tensor
        x = x.detach().cpu().numpy()
    return np.asarray(x)


def convert_audio(
        audio_source: Union[np.ndarray, List[np.ndarray]],
        sr: int,
        output_type: str = "numpy"
):
    if isinstance(audio_source, (list, tuple)):
        arrs = [_to_numpy(a) for a in audio_source]
        arrs = [a for a in arrs if a.size > 0]
        wav = np.concatenate(arrs) if arrs else np.array([])
    else:
        wav = _to_numpy(audio_source)

    if wav.size == 0:
        if output_type == "pydub":
            return AudioSegment.empty()
        return wav, sr

    if output_type == "pydub":
        audio_int16 = (wav * 32767).astype(np.int16)
        return AudioSegment(
            data=audio_int16.tobytes(),
            sample_width=audio_int16.dtype.itemsize,
            frame_rate=sr,
            channels=1
        )
    return wav, sr
