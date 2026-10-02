// preload：向渲染层注入
// 1) 启动参数（autostoryBoot）：后端端口与访问令牌
// 2) autostoryBridge —— 前端 shell 层（frontend/src/shell）调用的窗口与环境能力
const { contextBridge, ipcRenderer } = require("electron");

const readArg = (name) => {
  const prefix = `--${name}=`;
  const hit = process.argv.find((a) => a.startsWith(prefix));
  return hit ? hit.slice(prefix.length) : undefined;
};

const port = Number(readArg("autostory-port") ?? 8080);
const token = readArg("autostory-token") ?? "";

// contextIsolation 下 preload 的普通 window 赋值不会进入主世界，
// 启动参数必须经由 contextBridge 同步暴露（client.ts 读取）
contextBridge.exposeInMainWorld("autostoryBoot", {
  port: Number.isFinite(port) ? port : 8080,
  token,
});

const resizedHandlers = new Set();
ipcRenderer.on("win:resized", () => {
  resizedHandlers.forEach((h) => {
    try {
      h();
    } catch {
      /* 单个回调异常不影响其他 */
    }
  });
});

contextBridge.exposeInMainWorld("autostoryBridge", {
  envSnapshot: () => ipcRenderer.invoke("env:snapshot"),
  openExternal: (url) => ipcRenderer.invoke("shell:open-external", url),
  minimize: () => ipcRenderer.invoke("win:minimize"),
  toggleMaximize: () => ipcRenderer.invoke("win:toggle-maximize"),
  isMaximized: () => ipcRenderer.invoke("win:is-maximized"),
  hideToTray: () => ipcRenderer.invoke("win:hide"),
  exitApp: () => ipcRenderer.invoke("win:exit"),
  onResized: (cb) => {
    resizedHandlers.add(cb);
    return () => resizedHandlers.delete(cb);
  },
});
