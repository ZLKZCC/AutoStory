<div align="center">
  <img src="logo.png" alt="AutoStory" width="140" height="140" />

<h1>AutoStory</h1>

<p>小说创作桌面应用</p>
</div>

<p align="center">
  <img alt="version" src="https://img.shields.io/badge/version-0.1.0-3d8a4a" />
  <a href="https://github.com/ZLKZCC/AutoStory">
    <img alt="GitHub repo" src="https://img.shields.io/badge/GitHub-ZLKZCC%2FAutoStory-181717?logo=github" />
  </a>
  <img alt="license" src="https://img.shields.io/badge/license-AGPL--3.0-a87020" />
  <img alt="platform" src="https://img.shields.io/badge/platform-Windows-1f6feb" />
  <img alt="status" src="https://img.shields.io/badge/status-WIP-d96830" />
</p>

---

## 项目背景

AutoStory 是一个用于写作的AI桌面应用，主要面向长篇小说创作。你可以同时创建多个作品，每个作品里除了其具体正文外，还包含了用于管理分卷、章节、大纲、世界线、角色设定，以及写作过程中积累的素材的工作台。

写的时候可以让 AI 帮忙起草或修改这些内容；本应用还接入了 Qwen3-TTS，所以章节创作完成之后，还可以将指定的章节转换为有声音频。

项目目前还处于初期，很多地方还待打磨。

## 技术架构

| 层                 | 技术栈                                                 | 主要用途                            |
| ----------------- | --------------------------------------------------- | ------------------------------- |
| 桌面壳 `src-tauri/`  | Tauri 2 · Rust                                      | 窗口、前端加载、后端进程生命周期管理              |
| 前端 `frontend/`    | Vue 3（TSX 风格）· Vite 6 · Pinia · vue-router          | 页面和交互、SSE 对话流、有声书向导、可视化工作台      |
| 后端 `backend/`     | FastAPI · LangGraph · SQLAlchemy (async) · ChromaDB | 作品、卷、章节、角色等资源管理 + Agent 编排、向量检索 |
| 模型 `data/models/` | bge-m3 · Qwen3-TTS                                  | 本地向量化、语音合成                      |

后端一部分是常规的业务接口，负责作品、卷、章节、角色这些数据的增删改查；另一部分是 LangGraph 编排的 Agent。两边共用同一套数据库。

Agent结构：

```text
context ─▶ think ─┬─▶ act（工具调用）────────────┐
                  │                              │
                  ├─▶ audiobook 子图（三处人审）──┤
                  │                              ▼
                  └────────────────────────▶ compress（上下文压缩）
```

## 快速开始

### 环境要求

- Node.js 22+ 与 pnpm
- Python 3.12+
- Rust 工具链（构建桌面版时需要）
- `data/models/` 下的模型文件夹：
  - `bge-m3`
  - `Qwen3-TTS-12Hz-1.7B-Base`
  - `Qwen3-TTS-12Hz-1.7B-CustomVoice`
  - `Qwen3-TTS-12Hz-1.7B-VoiceDesign`
  - `Qwen3-TTS-Tokenizer-12Hz`

缺少模型时，应用将在启动时自动下载。

后端依赖在 `backend/requirements.txt`。

PyTorch 不放在 requirements 里，需要根据本机显卡情况，从 [PyTorch 官网](https://pytorch.org/get-started/locally/) 安装对应的 CUDA / CPU 版本。

桌面应用的打包版本会在第一次启动时自动处理这些依赖，包括自动安装pytorch。

### 启动后端

```bash
cd backend
python main.py
```

默认监听：

```text
http://127.0.0.1:8080
```

### 启动前端

```bash
cd frontend
pnpm install
pnpm dev
```

默认监听：

```text
http://localhost:5173
```

### 启动桌面壳（可选）

从项目根目录运行：

```bash
frontend\node_modules\.bin\tauri.cmd dev
```

Tauri CLI 安装在 `frontend` 的 `devDependencies` 里。

开发模式下后端端口固定为 `8080`，所以需要先手动启动后端。

## 构建

Windows 桌面版目前分两步构建：

1. 用 PyInstaller 打包后端。
2. 用 Tauri 生成 NSIS 安装包。

```bash
cd backend
python -m PyInstaller autostory.spec --noconfirm

cd ..
frontend\node_modules\.bin\tauri.cmd build
```

### 应用目录

```text
应用目录/
├── AutoStory.exe         # 桌面壳，Tauri 生成
├── backend/              # 后端，PyInstaller 产物
│   ├── autostory-backend.exe
│   └── _internal/        # 后端运行环境，不含 PyTorch
├── data/
│   ├── chroma/kb.db/     # 知识库种子（写作相关的一些知识）
│   ├── models/           # 模型文件夹（首次启动自动下载）
│   └── autostory.db 等   # 业务库与生成产物（运行时自生成）
├── runtime/              # 首次启动自动下载安装
│   ├── python/           # Python 运行时（PyTorch 宿主）
│   ├── ffmpeg/
│   └── manifest.json     # 已安装项清单（含 torch 变体）
└── logs/                 # 运行日志（运行时生成）
```

安装包只带桌面壳、后端产物和知识库种子，其余在第一次启动时自动下载：

- Python 运行时
- PyTorch（按显卡自动选 CUDA / CPU 版）
- ffmpeg
- `data/models/` 下的模型文件夹

## 项目结构

```text
AutoStory/
├── src-tauri/            # Tauri 2 桌面壳
│   ├── src/main.rs
│   ├── tauri.conf.json
│   └── icons/
├── frontend/             # Vue 3 + Vite 前端
│   └── src/
│       ├── pages/        # Home / Project / Settings / Resources / KnowledgeBase
│       ├── components/   # 对话气泡、有声书卡片、可视化工作台等
│       ├── api/          # 按业务域拆分的接口封装
│       └── stores/       # Pinia 状态（chat=对话运行态，每项目一份分片）
├── backend/              # FastAPI + LangGraph 后端
│   ├── main.py           # 应用入口
│   ├── autostory.spec    # PyInstaller 打包配置
│   ├── agent/            # 主图、节点、工具、子 Agent、模型适配
│   ├── routers/          # HTTP 路由
│   ├── models/           # ORM 模型
│   ├── schemas/          # 请求 / 响应模型
│   ├── crud/             # 数据访问层
│   ├── utils/            # 上下文构建、运行管理、有声书管线
│   └── config/           # 路径与数据库配置
├── data/                 # 运行时数据（模型、向量库、生成产物）
└── logo.png
```

## 贡献

欢迎提交 Issue 和 Pull Request。

项目还在持续调整中，提交 PR 前建议先确认：

- 后端可以通过编译检查
- 前端可以通过类型检查

GitHub：

https://github.com/ZLKZCC/AutoStory

## 许可证

本项目基于 [GNU Affero General Public License v3.0](https://www.gnu.org/licenses/agpl-3.0.html)（2007 年 11 月 19 日版）发布。
