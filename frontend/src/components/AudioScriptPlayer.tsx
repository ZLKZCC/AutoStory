import {
  defineComponent,
  ref,
  computed,
  watch,
  onBeforeUnmount,
  type PropType,
} from "vue";
import { PhPlay, PhPause, PhWaveform, PhDownloadSimple } from "@phosphor-icons/vue";
import { downloadUrl } from "../api";
import { useToast } from "../stores/toast";

const fmt = (seconds: number) => {
  if (!isFinite(seconds) || seconds < 0) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
};

export default defineComponent({
  name: "AudioScriptPlayer",
  props: {
    src: { type: String, default: "" },
    downloadName: {
      type: String,
      default: "有声书.mp3",
    },
    title: { type: String, default: "" },
    onPlay: { type: Function as PropType<() => void> },
  },
  setup(props) {
    const audioEl = ref<HTMLAudioElement | null>(null);
    const trackEl = ref<HTMLDivElement | null>(null);
    const playing = ref(false);
    const currentTime = ref(0);
    const duration = ref(0);
    const dragging = ref(false);
    const dragPercent = ref(0);
    let animFrame: number | null = null;

    const percent = computed(() =>
      dragging.value
        ? dragPercent.value
        : duration.value > 0
          ? (currentTime.value / duration.value) * 100
          : 0,
    );

    const startTick = () => {
      const tick = () => {
        if (audioEl.value && !audioEl.value.paused) {
          currentTime.value = audioEl.value.currentTime;
          animFrame = requestAnimationFrame(tick);
        }
      };
      animFrame = requestAnimationFrame(tick);
    };
    const stopTick = () => {
      if (animFrame != null) {
        cancelAnimationFrame(animFrame);
        animFrame = null;
      }
    };

    const toggle = () => {
      const a = audioEl.value;
      if (!a || !props.src) return;
      if (a.paused) {
        a.play().then(() => {
          playing.value = true;
          startTick();
        }).catch(() => {});
      } else {
        a.pause();
        playing.value = false;
        stopTick();
      }
    };

    watch(
      () => props.src,
      () => {
        playing.value = false;
        currentTime.value = 0;
        duration.value = 0;
        stopTick();
      },
    );

    const calcPercent = (clientX: number): number => {
      if (!trackEl.value) return 0;
      const rect = trackEl.value.getBoundingClientRect();
      const x = clientX - rect.left;
      return Math.max(0, Math.min(100, (x / rect.width) * 100));
    };

    const applyPercent = (p: number) => {
      const a = audioEl.value;
      if (!a || !duration.value) return;
      a.currentTime = (p / 100) * duration.value;
      currentTime.value = a.currentTime;
    };

    const beginDrag = (clientX: number) => {
      if (!props.src) return;
      dragPercent.value = calcPercent(clientX);
      dragging.value = true;
    };
    watch(dragging, (d, _old, onCleanup) => {
      if (!d) return;
      const onMove = (e: MouseEvent) => {
        dragPercent.value = calcPercent(e.clientX);
      };
      const onTouchMove = (e: TouchEvent) => {
        dragPercent.value = calcPercent(e.touches[0].clientX);
      };
      const onEnd = (e: MouseEvent) => {
        dragging.value = false;
        applyPercent(calcPercent(e.clientX));
      };
      const onTouchEnd = (e: TouchEvent) => {
        dragging.value = false;
        applyPercent(calcPercent(e.changedTouches[0].clientX));
      };
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onEnd);
      window.addEventListener("touchmove", onTouchMove);
      window.addEventListener("touchend", onTouchEnd);
      onCleanup(() => {
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onEnd);
        window.removeEventListener("touchmove", onTouchMove);
        window.removeEventListener("touchend", onTouchEnd);
      });
    });

    const handleClick = (e: MouseEvent) => {
      if (!props.src || dragging.value) return;
      applyPercent(calcPercent(e.clientX));
    };

    onBeforeUnmount(() => {
      stopTick();
      dragging.value = false;
    });

    const downloadHref = computed(() => props.src || "#");
    const downloadFile = computed(() => {
      const base = props.title?.trim();
      return base ? `${base}.mp3` : props.downloadName;
    });

    const { addToast } = useToast();
    const downloading = ref(false);
    // 音频直链是后端跨源地址：<a download> 在跨源下会被忽略、Tauri 还会拦导航，
    // 必须先 fetch 成 blob（同源 objectURL）再程序化触发下载
    const onDownload = async (e: MouseEvent) => {
      e.preventDefault();
      if (!props.src || downloading.value) return;
      downloading.value = true;
      try {
        await downloadUrl(props.src, downloadFile.value);
      } catch {
        addToast({ type: "error", title: "音频下载失败，请重试", duration: 3000 });
      } finally {
        downloading.value = false;
      }
    };

    return () => (
      <div class="audio-player-bar abw-player">
        <audio
          ref={audioEl}
          src={props.src || undefined}
          preload="metadata"
          style={{ display: "none" }}
          onLoadedmetadata={(e) => {
            const d = (e.target as HTMLAudioElement).duration;
            if (d && isFinite(d)) duration.value = d;
          }}
          onDurationchange={(e) => {
            const d = (e.target as HTMLAudioElement).duration;
            if (d && isFinite(d)) duration.value = d;
          }}
          onEnded={() => {
            playing.value = false;
            stopTick();
            currentTime.value = 0;
          }}
          onPause={() => stopTick()}
        />

        <button
          class={`audio-play-btn ${!props.src ? "audio-play-btn-disabled" : ""}`}
          onClick={toggle}
          disabled={!props.src}
          title={playing.value ? "暂停" : "播放"}
        >
          {playing.value ? (
            <PhPause size={14} weight="fill" />
          ) : (
            <PhPlay size={14} weight="fill" />
          )}
        </button>

        <span class="audio-time audio-time-current">
          {fmt(currentTime.value)}
        </span>

        <div
          ref={trackEl}
          class={`audio-progress-track ${!props.src ? "audio-progress-disabled" : ""} ${dragging.value ? "audio-progress-dragging" : ""}`}
          onMousedown={(e) => {
            e.preventDefault();
            beginDrag(e.clientX);
          }}
          onTouchstart={(e) => beginDrag(e.touches[0].clientX)}
          onClick={handleClick}
        >
          <div
            class="audio-progress-fill"
            style={{
              width: `${percent.value}%`,
              transition: playing.value || dragging.value ? "none" : "width 0.2s ease-out",
            }}
          />
          <div
            class={`audio-progress-thumb ${dragging.value ? "audio-progress-thumb-active" : ""}`}
            style={{
              left: `${percent.value}%`,
              transition:
                playing.value || dragging.value
                  ? "transform 0.15s cubic-bezier(0.16, 1, 0.3, 1)"
                  : "left 0.2s ease-out, transform 0.15s cubic-bezier(0.16, 1, 0.3, 1)",
            }}
          />
        </div>

        <span class="audio-time audio-time-duration">
          {duration.value > 0 ? fmt(duration.value) : "--:--"}
        </span>

        {playing.value && (
          <div class="audio-waveform">
            <PhWaveform size={14} weight="light" />
          </div>
        )}

        <a
          class={`abw-player-download ${downloading.value ? "abw-player-download-busy" : ""}`}
          href={downloadHref.value}
          download={downloadFile.value}
          title={downloading.value ? "正在下载…" : "下载音频"}
          onClick={onDownload}
        >
          <PhDownloadSimple size={14} weight="light" />
        </a>
      </div>
    );
  },
});
