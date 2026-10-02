// AutoStory Electron 主进程。
// 无边框自绘标题栏 / 后端进程托管 / 环境准备管线 / 托盘 / 下载另存为 / app:// 前端服务。
const {
  app,
  BrowserWindow,
  Tray,
  Menu,
  dialog,
  ipcMain,
  shell,
  protocol,
  nativeImage,
  session,
} = require("electron");
const path = require("node:path");
const fs = require("node:fs");

const { runtimeConfig } = require("./lib/runtime-config");
const { envState } = require("./lib/env-state");
const { spawnAndWaitHealthy, killBackend } = require("./lib/backend");
const { startPipeline } = require("./lib/pipeline");

const isDev = !app.isPackaged;

// 注册 app:// 自定义协议（须在 ready 之前）。
// file:// 会被后端 CORS 白名单拒绝，自定义协议以 app://localhost 为来源。
protocol.registerSchemesAsPrivileged([
  {
    scheme: "app",
    privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true },
  },
]);

app.setAppUserModelId("com.autostory.app");

// 资源根目录：backend/、data/、runtime/、logs/
const appRoot = isDev
  ? path.resolve(app.getAppPath(), "..")
  : process.resourcesPath;
const frontendDist = isDev
  ? path.resolve(app.getAppPath(), "..", "frontend", "dist")
  : path.join(process.resourcesPath, "frontend");
const iconPath = path.join(__dirname, "build", "icon.ico");

const rc = { port: 8080, token: "" }; // whenReady 里按 dev/release 重新生成

let mainWindow = null;
let tray = null;
let quitting = false;

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".ttf": "font/ttf",
  ".mp3": "audio/mpeg",
  ".wasm": "application/wasm",
};

function serveFrontend(requestPath) {
  let rel = decodeURIComponent(requestPath.split("?")[0]);
  if (rel === "/" || rel === "") rel = "/index.html";
  const file = path.resolve(frontendDist, "." + rel.replace(/\\/g, "/"));
  // 防目录穿越
  if (!file.startsWith(frontendDist + path.sep) && file !== frontendDist) {
    return new Response("forbidden", { status: 403 });
  }
  try {
    const buf = fs.readFileSync(file);
    return new Response(buf, {
      headers: { "content-type": MIME[path.extname(file).toLowerCase()] ?? "application/octet-stream" },
    });
  } catch {
    // vue-router history 模式：非资源路径一律回退 index.html
    if (path.extname(file) === "") {
      const index = fs.readFileSync(path.join(frontendDist, "index.html"));
      return new Response(index, { headers: { "content-type": MIME[".html"] } });
    }
    return new Response("not found", { status: 404 });
  }
}

function restoreWindow() {
  if (!mainWindow) return;
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
}

function buildTray() {
  const icon = nativeImage.createFromPath(iconPath);
  tray = new Tray(icon);
  tray.setToolTip("AutoStory");
  const menu = Menu.buildFromTemplate([
    { label: "显示主界面", click: () => restoreWindow() },
    { label: "退出 AutoStory", click: () => { quitting = true; app.quit(); } },
  ]);
  tray.setContextMenu(menu);
  tray.on("click", () => restoreWindow());
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 960,
    minHeight: 600,
    center: true,
    title: "AutoStory",
    show: false,
    frame: false, // 无边框，标题栏由前端自绘（CSS -webkit-app-region 拖拽）
    icon: iconPath,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      // preload 需读取 additionalArguments 里的启动参数（sandbox 下的 process 是阉割版）
      sandbox: false,
      additionalArguments: [
        `--autostory-port=${rc.port}`,
        `--autostory-token=${rc.token}`,
      ],
    },
  });

  win.once("ready-to-show", () => win.show());

  // 关闭 = 隐藏到托盘；完全退出走 win:exit / 托盘菜单
  win.on("close", (e) => {
    if (!quitting) {
      e.preventDefault();
      win.hide();
    }
  });

  // 窗口尺寸变化（节流）：通知渲染层刷新最大化图标
  let resizeDebounce = null;
  win.on("resize", () => {
    clearTimeout(resizeDebounce);
    resizeDebounce = setTimeout(() => {
      if (!win.isDestroyed()) win.webContents.send("win:resized");
    }, 150);
  });

  // 禁用 WebView 默认右键菜单（对应 SetAreDefaultContextMenusEnabled(false)）
  win.webContents.on("context-menu", (e) => e.preventDefault());

  // 外部页面一律交给系统浏览器（对应 open_url 仅 https 的规则）
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("https://")) void shell.openExternal(url);
    return { action: "deny" };
  });
  win.webContents.on("will-navigate", (e, url) => {
    const allowed = isDev
      ? (process.env.AUTOSTORY_DEV_URL ?? "http://localhost:5173")
      : "app://localhost";
    if (!url.startsWith(allowed)) e.preventDefault();
  });

  // release 关闭 DevTools 快捷键（对应 SetAreDevToolsEnabled(false)）
  if (!isDev) {
    win.webContents.on("before-input-event", (e, input) => {
      const devtools =
        input.key === "F12" ||
        (input.control && input.shift && input.key.toLowerCase() === "i");
      if (devtools) e.preventDefault();
    });
  }

  if (isDev) {
    const devUrl = process.env.AUTOSTORY_DEV_URL ?? "http://localhost:5173";
    win.loadURL(devUrl).catch(() => {
      // vite 未就绪时等待重试
      setTimeout(() => win.loadURL(devUrl).catch(() => {}), 2000);
    });
  } else {
    win.loadURL("app://localhost/index.html");
  }

  return win;
}

function registerIpc() {
  ipcMain.handle("env:snapshot", () => ({ items: envState.snapshot() }));
  ipcMain.handle("shell:open-external", (_e, url) => {
    if (typeof url === "string" && url.startsWith("https://")) {
      return shell.openExternal(url);
    }
    return undefined;
  });
  ipcMain.handle("win:minimize", () => mainWindow?.minimize());
  ipcMain.handle("win:toggle-maximize", () => {
    if (!mainWindow) return;
    if (mainWindow.isMaximized()) mainWindow.unmaximize();
    else mainWindow.maximize();
  });
  ipcMain.handle("win:is-maximized", () => !!mainWindow?.isMaximized());
  ipcMain.handle("win:hide", () => mainWindow?.hide());
  ipcMain.handle("win:exit", () => {
    quitting = true;
    app.quit();
  });
}

function registerDownloadInterceptor() {
  // 下载接管：弹系统"另存为"，取消则中止下载
  session.defaultSession.on("will-download", (_e, item) => {
    _e.preventDefault();
    const win = mainWindow && !mainWindow.isDestroyed() ? mainWindow : undefined;
    dialog
      .showSaveDialog(win, {
        title: "保存文件",
        defaultPath: item.getFilename(),
        filters: [{ name: "MP3 音频", extensions: ["mp3"] }],
      })
      .then((picked) => {
        if (picked.canceled || !picked.filePath) {
          item.cancel();
          return;
        }
        item.setSavePath(picked.filePath);
        item.once("done", (_ev, state) => {
          if (state === "interrupted") {
            dialog.showErrorBox("下载失败", "文件下载被中断，请重试。");
          }
        });
      });
  });
}

app.whenReady().then(async () => {
  Object.assign(rc, await runtimeConfig(isDev));
  protocol.handle("app", (req) => serveFrontend(new URL(req.url).pathname));
  registerIpc();
  registerDownloadInterceptor();
  mainWindow = createWindow();
  buildTray();

  if (isDev) {
    // 开发模式：跳过环境管线，后端请手动启动（cd backend && python main.py）
    envState.markAllDone();
    console.log("[dev] 请手动启动后端：cd backend && python main.py");
  } else {
    startPipeline(envState, appRoot, rc).catch((msg) => {
      // 与 Rust cascade_error 一致：把错误落到所有未完成项上，由启动页展示
      envState.cascadeError(String(msg?.message ?? msg));
    });
  }

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) mainWindow = createWindow();
    else restoreWindow();
  });
});

app.on("before-quit", () => {
  quitting = true;
});

// 应用退出时结束后端进程
app.on("will-quit", () => {
  killBackend();
});

app.on("window-all-closed", () => {
  app.quit();
});
