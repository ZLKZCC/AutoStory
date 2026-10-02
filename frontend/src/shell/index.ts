// 桌面壳（Electron）与纯浏览器（vite dev 直开）统一的壳能力入口。
// Electron 端走 preload 注入的 window.autostoryBridge；浏览器端降级为 mock/无操作。
import { ok } from "../api/mock";
import type { PrepareItem } from "../api/types";

export type ShellKind = "electron" | "web";

const electronBridge = (): AutostoryBridge | null =>
  typeof window !== "undefined" && "autostoryBridge" in window
    ? (window as { autostoryBridge: AutostoryBridge }).autostoryBridge
    : null;

export const shellKind: ShellKind = electronBridge() ? "electron" : "web";

export const isDesktop = shellKind === "electron";

export const shell = {
  kind: shellKind,
  isDesktop,

  /** 启动期环境检查快照（python/pytorch/ffmpeg/服务）。 */
  async prepareEnvironment(): Promise<{ items: PrepareItem[] }> {
    if (isDesktop) {
      return electronBridge()!.envSnapshot();
    }
    return ok<{ items: PrepareItem[] }>({
      items: [
        { name: "python", progress: 100, speed: "", status: "done" },
        { name: "pytorch", progress: 100, speed: "", status: "done" },
        { name: "ffmpeg", progress: 100, speed: "", status: "done" },
        { name: "服务", progress: 100, speed: "", status: "done" },
      ],
    });
  },

  /** 外部链接，仅允许 https。 */
  async openUrl(url: string): Promise<void> {
    if (isDesktop) {
      await electronBridge()!.openExternal(url).catch(() => {});
      return;
    }
    window.open(url, "_blank", "noopener");
  },

  async minimize(): Promise<void> {
    if (isDesktop) await electronBridge()!.minimize();
  },

  async toggleMaximize(): Promise<void> {
    if (isDesktop) await electronBridge()!.toggleMaximize();
  },

  async isMaximized(): Promise<boolean> {
    if (isDesktop) return electronBridge()!.isMaximized();
    return false;
  },

  /** 关闭 = 隐藏到托盘。 */
  async hideToTray(): Promise<void> {
    if (isDesktop) await electronBridge()!.hideToTray();
  },

  /** 完全退出（绕过"关闭即隐藏"）。 */
  async exitApp(): Promise<void> {
    if (isDesktop) await electronBridge()!.exitApp();
  },

  /** 窗口尺寸变化（含最大化/还原），用于切换最大化图标。返回退订函数。 */
  onWindowResized(cb: () => void): () => void {
    if (isDesktop) {
      return electronBridge()!.onResized(cb);
    }
    return () => {};
  },
};

interface AutostoryBridge {
  envSnapshot(): Promise<{ items: PrepareItem[] }>;
  openExternal(url: string): Promise<void>;
  minimize(): Promise<void>;
  toggleMaximize(): Promise<void>;
  isMaximized(): Promise<boolean>;
  hideToTray(): Promise<void>;
  exitApp(): Promise<void>;
  onResized(cb: () => void): () => void;
}
