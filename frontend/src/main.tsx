import { createApp } from "vue";
import { createPinia } from "pinia";
import App from "./App";
import { router } from "./router";
import { useToastStore } from "./stores/toast";
import "./styles/index.css";

const app = createApp(App).use(createPinia()).use(router);

let lastErrorToastAt = 0;
const notifyGlobalError = (message: string) => {
  const now = Date.now();
  if (now - lastErrorToastAt < 3000) return;
  lastErrorToastAt = now;
  try {
    useToastStore().addToast({
      type: "error",
      title: "界面出了点问题",
      message,
      duration: 6000,
    });
  } catch {
  }
};

app.config.errorHandler = (err, _instance, info) => {
  console.error("[app] 渲染错误:", err, "| 阶段:", info);
  notifyGlobalError(`${info}：${err instanceof Error ? err.message : String(err)}`);
};

window.addEventListener("unhandledrejection", (ev) => {
  console.error("[app] 未处理的异步错误:", ev.reason);
  notifyGlobalError(
    ev.reason instanceof Error ? ev.reason.message : String(ev.reason ?? "未知异步错误"),
  );
});

app.mount("#root");
