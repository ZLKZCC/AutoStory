import os
import sys
from pathlib import Path

_root_env = os.environ.get("AUTOSTORY_ROOT")
if _root_env:
    _site = Path(_root_env) / "runtime" / "python" / "Lib" / "site-packages"
    if _site.is_dir():
        sys.path.insert(0, str(_site))
        _torch_lib = _site / "torch" / "lib"
        if _torch_lib.is_dir():
            os.add_dll_directory(str(_torch_lib))

import uvicorn
from fastapi import FastAPI
from warnings import filterwarnings
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from config.db_conf import init_database, init_vector
from middlewares.security import LoopbackOnlyMiddleware, AppTokenMiddleware
from routers import project, provider, chapter, character, resource, chat, enviroment, chatrecord, characterstage, userpreference, audiobookscript, material, volume, gpu

filterwarnings("ignore")

@asynccontextmanager
async def lifespan(app):
    await init_database()
    await init_vector()
    yield

Version = "0.1.0"
app = FastAPI(title="AutoStory", version=Version, lifespan=lifespan)

app.add_middleware(LoopbackOnlyMiddleware)
app.add_middleware(AppTokenMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "tauri://localhost",
        "https://tauri.localhost",
        "http://tauri.localhost",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(project.router)
app.include_router(provider.router)
app.include_router(chapter.router)
app.include_router(character.router)
app.include_router(characterstage.router)
app.include_router(resource.router)
app.include_router(enviroment.router)
app.include_router(chat.router)
app.include_router(chatrecord.router)
app.include_router(userpreference.router)
app.include_router(audiobookscript.router)
app.include_router(material.router)
app.include_router(volume.router)
app.include_router(gpu.router)


@app.get("/")
async def root():
    return {"Product": "AutoStory", "Version": Version}


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": Version}


if __name__ == "__main__":
    port_env = os.environ.get("AUTOSTORY_PORT")
    print(f"当前进程 PID: {os.getpid()}")
    if port_env:
        uvicorn.run(app, host="127.0.0.1", port=int(port_env))
    else:
        uvicorn.run("main:app", host="127.0.0.1", port=8080, reload=True)
