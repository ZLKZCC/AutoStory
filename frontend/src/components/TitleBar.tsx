import { defineComponent, ref, onMounted, onBeforeUnmount } from "vue";
import {
  PhMinus,
  PhSquare,
  PhCopy,
  PhX,
  PhTray,
  PhPower,
} from "@phosphor-icons/vue";
import { shell } from "../shell";
import "./TitleBar.css";

const isDesktop = shell.isDesktop;

const CLOSE_ACTION_KEY = "autostory.closeAction";
type CloseAction = "tray" | "exit";

export default defineComponent({
  name: "TitleBar",
  props: {
    // 启动页上方时背景透明、按钮浅色，与深色启动画面融合
    overlay: { type: Boolean, default: false },
  },
  setup(props) {
    const maximized = ref(false);
    const closeMenuOpen = ref(false);
    const rememberChoice = ref(false);
    let unlisten: (() => void) | null = null;
    let debounce: ReturnType<typeof setTimeout> | undefined;

    onMounted(() => {
      if (!isDesktop) return;
      void shell.isMaximized().then((v) => (maximized.value = v));
      // 拖拽缩放会连续触发，只在停下后取一次状态
      unlisten = shell.onWindowResized(() => {
        clearTimeout(debounce);
        debounce = setTimeout(() => {
          void shell.isMaximized().then((v) => (maximized.value = v));
        }, 150);
      });
    });

    onBeforeUnmount(() => {
      unlisten?.();
      clearTimeout(debounce);
    });

    const applyCloseAction = async (action: CloseAction) => {
      closeMenuOpen.value = false;
      if (!isDesktop) return;
      if (action === "exit") {
        // exitApp 绕过壳侧"关闭即隐藏"的拦截，真正退出并结束后端
        await shell.exitApp();
      } else {
        await shell.hideToTray();
      }
    };

    const handleCloseClick = () => {
      if (!isDesktop) return;
      const saved = localStorage.getItem(CLOSE_ACTION_KEY);
      if (saved === "tray" || saved === "exit") {
        void applyCloseAction(saved);
        return;
      }
      closeMenuOpen.value = !closeMenuOpen.value;
    };

    const chooseClose = (action: CloseAction) => {
      if (rememberChoice.value) {
        try {
          localStorage.setItem(CLOSE_ACTION_KEY, action);
        } catch {
          /* 忽略存储失败，仅本次生效 */
        }
      }
      void applyCloseAction(action);
    };

    const controls = () => {
      if (!isDesktop) return null;
      return (
        <div class="titlebar-controls">
          <button
            class="titlebar-btn"
            title="最小化"
            onClick={() => void shell.minimize()}
          >
            <PhMinus size={15} weight="light" />
          </button>
          <button
            class="titlebar-btn"
            title={maximized.value ? "还原" : "最大化"}
            onClick={() => void shell.toggleMaximize()}
          >
            {maximized.value ? (
              <PhCopy size={12} weight="light" />
            ) : (
              <PhSquare size={12} weight="light" />
            )}
          </button>
          <button
            class="titlebar-btn titlebar-btn-close"
            title="关闭"
            onClick={handleCloseClick}
          >
            <PhX size={15} weight="light" />
          </button>
        </div>
      );
    };

    const closeMenu = () => {
      if (!closeMenuOpen.value) return null;
      return (
        <>
          <div
            class="titlebar-close-backdrop"
            onClick={() => (closeMenuOpen.value = false)}
          />
          <div class="titlebar-close-menu">
            <div class="titlebar-close-menu-title">关闭窗口时</div>
            <button
              class="titlebar-close-option"
              onClick={() => chooseClose("tray")}
            >
              <span class="titlebar-close-option-icon">
                <PhTray size={16} weight="light" />
              </span>
              <span class="titlebar-close-option-text">
                最小化到系统托盘
                <em>窗口隐藏，从托盘图标随时恢复</em>
              </span>
            </button>
            <button
              class="titlebar-close-option titlebar-close-option-danger"
              onClick={() => chooseClose("exit")}
            >
              <span class="titlebar-close-option-icon">
                <PhPower size={16} weight="light" />
              </span>
              <span class="titlebar-close-option-text">
                退出程序
                <em>结束后端进程并完全退出</em>
              </span>
            </button>
            <label class="titlebar-close-remember">
              <input
                type="checkbox"
                checked={rememberChoice.value}
                onChange={(e) =>
                  (rememberChoice.value = (e.target as HTMLInputElement).checked)
                }
              />
              记住我的选择
            </label>
          </div>
        </>
      );
    };

    return () => (
      <header class={`titlebar ${props.overlay ? "titlebar-overlay" : ""}`}>
        <div class="titlebar-brand">
          <img src="/logo.png" alt="" class="titlebar-logo" draggable={false} />
          <span class="titlebar-name">
            <span class="auto">Auto</span>
            <span class="story">Story{"\u200B"}</span>
          </span>
        </div>
        {controls()}
        {closeMenu()}
      </header>
    );
  },
});
