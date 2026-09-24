import os
from pathlib import Path

def ensure_dir(dir_path: Path):
    path = Path(dir_path)
    path.mkdir(parents=True, exist_ok=True)

def ensure_file(file_path: Path):
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)

class ConfigStore:
    _instance = None
    def __init__(self):
        if hasattr(self,"init"):
            return
        self.init=True
        root_env = os.environ.get("AUTOSTORY_ROOT")
        self.ROOT_DIR = Path(root_env).resolve() if root_env else Path(__file__).resolve().parent.parent.parent
        self.DATA_DIR = self.ROOT_DIR / "data"
        self.KEY_FILE_PATH = self.DATA_DIR / ".sys_data"
        self.CHROMA_DIR = self.DATA_DIR / "chroma"
        self.SCRIPT_DIR = self.DATA_DIR / "chapters"
        self.CHARACTER_DIR = self.DATA_DIR / "characters"
        self.RESOURCE_DIR = self.DATA_DIR / "resources"
        databasefile = self.DATA_DIR / "autostory.db"
        ensure_file(databasefile)
        self.ASYNC_DATABASE_URL = f"sqlite+aiosqlite:///{databasefile}"
        self.AGENT_URL = self.DATA_DIR / "agent_checkpoints.db"
        self.CHROMA_DB_URL = self.CHROMA_DIR / "autostory.db"
        self.CHROMA_COLLECTION = ["chapters","knowledges","experience"]
        self.CHROMA_KB_DB_URL = self.CHROMA_DIR / "kb.db"
        self.CHROMA_KB_COLLECTION = ["writing_kb", "analysis_kb", "summary_kb"]
        self.MODEL_DIR = self.DATA_DIR / "models"
        self.VECTOR_MODEL_DIR = self.MODEL_DIR / "bge-m3"
        self.Voice_Base_MODEL_DIR = self.MODEL_DIR / "Qwen3-TTS-12Hz-1.7B-Base"
        self.Voice_CustomVoice_MODEL_DIR = self.MODEL_DIR / "Qwen3-TTS-12Hz-1.7B-CustomVoice"
        self.Voice_VoiceDesign_MODEL_DIR = self.MODEL_DIR / "Qwen3-TTS-12Hz-1.7B-VoiceDesign"
        self.Voice_Tokenizer_MODEL_DIR = self.MODEL_DIR / "Qwen3-TTS-Tokenizer-12Hz"
        bundled_ffmpeg = self.ROOT_DIR / "runtime" / "ffmpeg" / "bin" / "ffmpeg.exe"
        self.FFMPEG_PATH = str(bundled_ffmpeg) if bundled_ffmpeg.exists() else "ffmpeg"
        if bundled_ffmpeg.exists():
            from pydub import AudioSegment
            AudioSegment.converter = str(bundled_ffmpeg)
        ensure_dir(self.CHROMA_DIR)
        ensure_dir(self.CHROMA_DB_URL)
        ensure_dir(self.CHROMA_KB_DB_URL)
        ensure_dir(self.SCRIPT_DIR)
        ensure_dir(self.CHARACTER_DIR)
        ensure_dir(self.RESOURCE_DIR)
        ensure_dir(self.MODEL_DIR)

    def __new__(cls,*args,**kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

conf = ConfigStore()

MODEL_REGISTRY = [
    {
        "id": "Qwen3-TTS-12Hz-1.7B-Base",
        "name": "Qwen3-TTS Base",
        "description": "基础语音合成模型，支持多语言文本转语音",
        "category": "tts",
        "repo": "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
    },
    {
        "id": "Qwen3-TTS-12Hz-1.7B-CustomVoice",
        "name": "Qwen3-TTS CustomVoice",
        "description": "自定义音色模型，支持音色克隆和风格控制",
        "category": "tts",
        "repo": "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
    },
    {
        "id": "Qwen3-TTS-12Hz-1.7B-VoiceDesign",
        "name": "Qwen3-TTS VoiceDesign",
        "description": "音色设计模型，支持从文本描述生成音色",
        "category": "tts",
        "repo": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
    },
    {
        "id": "Qwen3-TTS-Tokenizer-12Hz",
        "name": "Qwen3-TTS Tokenizer",
        "description": "TTS 语音分词器，Base/CustomVoice/VoiceDesign 共用",
        "category": "tts",
        "repo": "Qwen/Qwen3-TTS-Tokenizer-12Hz",
    },
    {
        "id": "bge-m3",
        "name": "BGE-M3",
        "description": "多语言通用向量模型，支持中文，1024维",
        "category": "vector",
        "required_files": ["config.json"],
        "repo": "BAAI/bge-m3",
        "dimensions": 1024,
    },
]

MODEL_DIR_MAP = {
    "bge-m3": "VECTOR_MODEL_DIR",
    "Qwen3-TTS-12Hz-1.7B-Base": "Voice_Base_MODEL_DIR",
    "Qwen3-TTS-12Hz-1.7B-CustomVoice": "Voice_CustomVoice_MODEL_DIR",
    "Qwen3-TTS-12Hz-1.7B-VoiceDesign": "Voice_VoiceDesign_MODEL_DIR",
    "Qwen3-TTS-Tokenizer-12Hz": "Voice_Tokenizer_MODEL_DIR",
}

MODELSCOPE_REPO_MAP = {
    "bge-m3": "Xorbits/bge-m3",
    "Qwen3-TTS-12Hz-1.7B-Base": "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
    "Qwen3-TTS-12Hz-1.7B-CustomVoice": "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
    "Qwen3-TTS-12Hz-1.7B-VoiceDesign": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
    "Qwen3-TTS-Tokenizer-12Hz": "Qwen/Qwen3-TTS-Tokenizer-12Hz",
}

DOWNLOAD_SOURCES = {
    "huggingface_global": {
        "name": "HuggingFace Global",
        "base_url": "https://huggingface.co",
        "type": "huggingface"
    },
    "huggingface_cn": {
        "name": "HuggingFace CN",
        "base_url": "https://hf-mirror.com",
        "type": "huggingface"
    },
    "modelscope": {
        "name": "ModelScope",
        "base_url": "https://modelscope.cn",
        "type": "modelscope"
    }
}

MODEL_PROFILE_REGISTRY = {

    "gpt-3.5-turbo": 16385,
    "gpt-3.5-turbo-0125": 16385,

    "gpt-4": 8192,
    "gpt-4-0314": 8192,
    "gpt-4-0613": 8192,

    "gpt-4-32k": 32768,
    "gpt-4-32k-0613": 32768,

    "gpt-4-turbo": 128000,
    "gpt-4-turbo-preview": 128000,

    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,

    "gpt-4.1": 1048576,
    "gpt-4.1-mini": 1048576,
    "gpt-4.1-nano": 1048576,

    "o1": 200000,
    "o1-mini": 128000,

    "o3": 200000,
    "o3-mini": 200000,

    "o4-mini": 200000,

    "gpt-5": 272000,
    "gpt-5.1": 272000,
    "gpt-5.2": 272000,

    "gpt-5.4": 1050000,
    "gpt-5.5": 1050000,
    "gpt-5.6": 1050000,

    "claude-2": 100000,
    "claude-2.1": 200000,

    "claude-instant-1": 100000,

    "claude-3-haiku": 200000,
    "claude-3-sonnet": 200000,
    "claude-3-opus": 200000,

    "claude-3-5-sonnet": 200000,
    "claude-3-5-haiku": 200000,

    "claude-3-7-sonnet": 200000,

    "claude-sonnet-4": 200000,
    "claude-opus-4": 200000,

    "claude-sonnet-4.5": 200000,
    "claude-haiku-4.5": 200000,
    "claude-opus-4.5": 200000,

    "claude-opus-4.6": 1000000,
    "claude-sonnet-4.6": 1000000,

    "deepseek-chat": 131072,
    "deepseek-coder": 16000,

    "deepseek-v2": 128000,
    "deepseek-v2-chat": 128000,

    "deepseek-v3": 64000,

    "deepseek-reasoner": 131072,

    "deepseek-v3.2": 131072,

    "deepseek-v4": 1048576,

    "deepseek-v4-flash": 1048576,
    "deepseek-v4-flash-vision-exp": 1048576,

    "deepseek-v4.1-flash": 1048576,

    "deepseek-flash": 1048576,

    "deepseek-v4-pro": 1048576,

    "qwen-turbo": 131072,

    "qwen-plus": 1048576,
    "qwen-flash": 1048576,

    "qwen-max": 32768,
    "qwen-max-longcontext": 1000000,
    "qwen-long": 10000000,

    "qwen2-7b": 32768,
    "qwen2-72b": 131072,

    "qwen2.5-7b": 32768,
    "qwen2.5-14b": 131072,
    "qwen2.5-32b": 131072,
    "qwen2.5-72b": 131072,

    "qwen3-8b": 131072,
    "qwen3-14b": 131072,
    "qwen3-32b": 131072,
    "qwen3-235b": 262144,

    "qwen3-max": 262144,

    "qwen3.7-plus": 1048576,

    "qwen3.8-max": 1048576,
    "qwen3.8-flash": 1048576,

    "gemini-1.0-pro": 32768,

    "gemini-1.5-pro": 2000000,
    "gemini-1.5-flash": 1000000,

    "gemini-2.0-flash": 1048576,

    "gemini-2.5-pro": 1048576,
    "gemini-2.5-flash": 1048576,

    "gemini-3-pro": 1048576,
    "gemini-3-flash": 1048576,

    "gemini-3.1-pro": 1048576,

    "llama-2-7b": 4096,
    "llama-2-13b": 4096,
    "llama-2-70b": 4096,

    "llama-3-8b": 8192,
    "llama-3-70b": 8192,

    "llama-3.1-8b": 131072,
    "llama-3.1-70b": 131072,
    "llama-3.1-405b": 131072,

    "llama-3.2-1b": 131072,
    "llama-3.2-3b": 131072,
    "llama-3.2-11b": 131072,
    "llama-3.2-90b": 131072,

    "llama-3.3-70b": 131072,

    "llama-4-scout": 10000000,

    "llama-4-maverick": 1048576,

    "mistral-7b": 8192,

    "mixtral-8x7b": 32768,
    "mixtral-8x22b": 65536,

    "mistral-large": 128000,
    "mistral-small": 32000,

    "mistral-large-2": 131072,

    "mistral-medium-3.5": 262144,

    "mistral-large-3": 262144,
    "mistral-small-4": 262144,

    "mistral-medium-3.1": 131072,

    "codestral": 128000,

    "devstral-2": 262144,

    "magistral-medium-1.2": 128000,

    "ministral-3-3b": 262144,
    "ministral-3-8b": 262144,
    "ministral-3-14b": 262144,

    "mistral-nemo": 128000,

    "yi-large": 32768,
    "yi-medium": 16384,

    "glm-4": 128000,
    "glm-4-air": 128000,

    "chatglm3-6b": 8192,

    "glm-4.5-air": 98304,
    "glm-4.6": 202752,
    "glm-4.7": 202752,

    "glm-5": 202752,
    "glm-5.1": 202752,

    "glm-5.2": 1048576,
    "glm-5.3": 1048576,

    "baichuan2-13b": 4096,

    "internlm2-20b": 32768,
    "internlm2.5-20b": 32768,

    "kimi-k2": 131072,

    "kimi-k2.5": 262144,
    "kimi-k2.6": 262144,
    "kimi-k2.7": 262144,

    "kimi-k3": 1048576,

    "kimi-for-coding": 262144,

    "minimax-m2": 204800,
    "minimax-m2.5": 196608,
    "minimax-m3": 700000,

    "doubao-seed": 262144,

    "grok-4": 262144,
    "grok-4.5": 524288,
    "grok-4.6": 524288,

    "llama3": 8192,
    "llama3.1": 131072,

    "qwen2": 32768,
    "qwen2.5": 131072,
    "qwen3": 131072,

    "deepseek-r1": 65536,
    "deepseek-r1-distill-qwen-32b": 131072,
}

DEFAULT_CONTEXT_WINDOW = 131072

def get_model_context_window(model_id: str) -> int:
    mid = (model_id or "").strip().lower()
    if mid in MODEL_PROFILE_REGISTRY:
        return MODEL_PROFILE_REGISTRY[mid]
    best = ""
    for key in MODEL_PROFILE_REGISTRY:
        if mid.startswith(key) and len(key) > len(best):
            best = key
    return MODEL_PROFILE_REGISTRY[best] if best else DEFAULT_CONTEXT_WINDOW
