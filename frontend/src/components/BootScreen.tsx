import { defineComponent, ref, onMounted, onBeforeUnmount } from "vue";
import {
  prepareEnvironment,
  prepareModels,
  retryFailedModels,
  type PrepareItem,
  type WsChannel,
} from "../api";
import "./BootScreen.css";

const POLL_INTERVAL = 1000;
const STALL_TIMEOUT = 5 * 60 * 1000; // 模型阶段无任何进展超过该时长才给手动跳过出口（不自动跳）

const isSettled = (it: PrepareItem) => it.status === "done" || it.status === "error";

export default defineComponent({
  name: "BootScreen",
  emits: ["complete"],
  setup(_, { emit }) {
    const items = ref<PrepareItem[]>([]);
    const overallProgress = ref(0);
    const statusText = ref("正在检查运行环境...");
    const started = ref(false);
    const ready = ref(false);
    const failed = ref(false);
    const stalled = ref(false);
    let lastModelSig = "";
    let lastActiveAt = Date.now();

    let pollTimer: ReturnType<typeof setInterval> | null = null;
    let modelWs: WsChannel | null = null;
    let cancelled = false;

    const stopPoll = () => {
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    };

    const stop = () => {
      stopPoll();
      if (modelWs) {
        modelWs.close();
        modelWs = null;
      }
    };

    const finish = () => {
      stop();
      ready.value = true;
      overallProgress.value = 100;
      statusText.value = "环境就绪，正在启动...";
      setTimeout(() => {
        if (!cancelled) emit("complete");
      }, 800);
    };

    const phase = ref<"env" | "models">("env");
    let envItems: PrepareItem[] = [];
    let modelItems: PrepareItem[] | null = null;

    const avgProgress = (list: PrepareItem[]) =>
      list.length
        ? list.reduce((s, it) => s + (isSettled(it) ? 100 : it.progress), 0) /
          list.length
        : 0;

    const applyItems = () => {
      const list = [...envItems, ...(modelItems ?? [])];
      items.value = list;
      started.value = true;
      if (phase.value === "models" && modelItems != null) {
        // 有下载速度/进度变化即活跃；无任何变化超过 STALL_TIMEOUT 才算卡住，只给手动出口
        const sig = modelItems
          .map((it) => `${it.name}:${it.status}:${it.progress}:${it.speed}`)
          .join("|");
        if (sig !== lastModelSig) {
          lastModelSig = sig;
          lastActiveAt = Date.now();
          stalled.value = false;
        } else if (!ready.value && Date.now() - lastActiveAt > STALL_TIMEOUT) {
          stalled.value = true;
        }
      }
      if (!list.length) return;
      const modelPct =
        modelItems == null ? 0 : modelItems.length ? avgProgress(modelItems) : 100;
      overallProgress.value = Math.min(
        Math.round((avgProgress(envItems) + modelPct) / 2),
        100,
      );
      const busy = list.filter((it) => !isSettled(it));
      if (busy.length)
        statusText.value = `正在准备 ${busy.map((it) => it.name).join("、")}...`;
      // 只有全部 done 才自动进主页；有 error 停下来把错误展示给用户，由用户决定重试或跳过
      if (
        phase.value === "models" &&
        modelItems != null &&
        modelItems.every((it) => it.status === "done")
      )
        finish();
    };

    const connectModels = () => {
      modelWs = prepareModels(
        (list) => {
          if (cancelled) return;
          modelItems = list;
          applyItems();
        },
        {
          onClose: () => {
            if (cancelled || ready.value) return;
            stop();
            failed.value = true;
            const hasErr = (modelItems ?? []).some((it) => it.status === "error");
            statusText.value = hasErr
              ? "部分模型下载失败，可重试或跳过"
              : "无法连接模型服务，请确认后端已启动";
          },
        },
      );
    };

    const retryDownload = async () => {
      try {
        await retryFailedModels();
        failed.value = false;
        statusText.value = "正在重试下载...";
        connectModels();
      } catch {
        statusText.value = "重试请求失败，请确认后端已启动";
      }
    };

    const tick = async () => {
      if (phase.value !== "env") return;
      try {
        const env = await prepareEnvironment();
        if (cancelled || phase.value !== "env") return;
        envItems = env.items;
        applyItems();
        if (envItems.every(isSettled)) {
          phase.value = "models";
          stopPoll();
          statusText.value = "正在同步模型...";
          connectModels();
        }
      } catch (e) {
        if (cancelled) return;
        stop();
        failed.value = true;
        statusText.value = `环境准备失败: ${e instanceof Error ? e.message : String(e)}`;
      }
    };

    onMounted(() => {
      void tick();
      pollTimer = setInterval(() => void tick(), POLL_INTERVAL);
    });

    onBeforeUnmount(() => {
      cancelled = true;
      stop();
    });

    const activeSpeed = () => {
      const it = items.value.find((i) => i.status === "running" && i.speed);
      return it ? it.speed : "";
    };

    return () => (
      <div class="boot-screen">
        <div class="boot-particles" />

        <div class="boot-content">
          <div class="boot-logo" style={{ userSelect: "none" }}>
            <img
              src="/logo.png"
              alt="AutoStory"
              class="boot-logo-img"
              draggable={false}
            />
            <div class="boot-logo-text">
              <span class="boot-auto">Auto</span>
              <span class="boot-story">Story{"\u200B"}</span>
            </div>
          </div>

          <div class="boot-status">{statusText.value}</div>

          <div class="boot-progress-container">
            <div class="boot-progress-bar">
              {!started.value ? (
                <div class="boot-progress-indeterminate" />
              ) : (
                <div
                  class="boot-progress-fill"
                  style={{
                    width: `${ready.value ? 100 : overallProgress.value}%`,
                  }}
                />
              )}
            </div>
            {started.value && !ready.value && (
              <div class="boot-progress-text">
                {overallProgress.value}%
                {(() => {
                  const s = activeSpeed();
                  return s ? ` · ${s}` : "";
                })()}
              </div>
            )}
            {ready.value && (
              <div class="boot-progress-text boot-progress-ready">就绪</div>
            )}
          </div>

          {started.value && items.value.length > 0 && (
            <div class="boot-download-list">
              {items.value.map((it) => (
                <div key={it.name} class="boot-download-item">
                  <span class="boot-download-name">{it.name}</span>
                  <span class="boot-download-status">
                    {it.status === "running" &&
                      `${it.progress}%${it.speed ? ` ${it.speed}` : ""}`}
                    {it.status === "done" && "✓ 完成"}
                    {it.status === "error" &&
                      `✗ 失败: ${it.error || "未知错误"}`}
                    {it.status === "pending" && (it.error || "等待中...")}
                  </span>
                </div>
              ))}
            </div>
          )}

          {failed.value && (modelItems ?? []).some((it) => it.status === "error") && (
            <button class="boot-skip-btn" onClick={() => void retryDownload()}>
              重试下载失败项
            </button>
          )}
          {failed.value && (
            <button class="boot-skip-btn" onClick={() => emit("complete")}>
              跳过，使用降级模式启动
            </button>
          )}
          {phase.value === "models" && stalled.value && !ready.value && !failed.value && (
            <button class="boot-skip-btn" onClick={() => emit("complete")}>
              下载长时间无进展，先跳过（稍后可在设置中继续）
            </button>
          )}
        </div>
      </div>
    );
  },
});
