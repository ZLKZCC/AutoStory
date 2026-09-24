from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []

for _pkg in [
    "chromadb",
    "transformers",
    "langchain",
    "langchain_community",
    "langchain_core",
    "langgraph",
    "langgraph.checkpoint.sqlite",
    "modelscope",
    "zai",
    "qwen_tts",
    "sentence_transformers",
    "sse_starlette",
    "pydub",
    "docx",
    "soundfile",
    "psutil",
    "cryptography",
]:
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["torch", "torchaudio", "torchvision", "tkinter"],
    noarchive=False,
)

a.binaries = [b for b in a.binaries if not b[0].startswith("torch")]
a.datas = [d for d in a.datas if not d[0].startswith("torch")]
a.pure = [m for m in a.pure if not m[0].startswith("torch")]
a.hiddenimports = [h for h in a.hiddenimports if not h.startswith("torch")]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="autostory-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="autostory-backend",
)
