import { defineComponent, ref, onBeforeUnmount } from "vue";
import { PhPlay, PhPause, PhWaveform } from "@phosphor-icons/vue";

const formatTimeShort = (seconds: number): string => {
  if (!seconds || !isFinite(seconds)) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
};

export default defineComponent({
  name: "MiniAudioPlayer",
  props: {
    src: { type: String, required: true },
    playerId: { type: String, default: "" },
  },
  setup(props) {
    let audio: HTMLAudioElement | null = null;
    let animRef: number | null = null;
    const trackEl = ref<HTMLDivElement | null>(null);
    const playing = ref(false);
    const currentTime = ref(0);
    const duration = ref(0);

    const startTick = () => {
      const tick = () => {
        if (audio && !audio.paused) {
          currentTime.value = audio.currentTime;
          animRef = requestAnimationFrame(tick);
        }
      };
      animRef = requestAnimationFrame(tick);
    };

    const stopTick = () => {
      if (animRef != null) {
        cancelAnimationFrame(animRef);
        animRef = null;
      }
    };

    onBeforeUnmount(() => {
      stopTick();
      if (audio) audio.pause();
    });

    const togglePlay = () => {
      if (!audio) {
        const a = new Audio();
        a.preload = "metadata";
        a.addEventListener("loadedmetadata", () => {
          if (isFinite(a.duration)) duration.value = a.duration;
        });
        a.addEventListener("durationchange", () => {
          if (isFinite(a.duration)) duration.value = a.duration;
        });
        a.addEventListener("ended", () => {
          stopTick();
          currentTime.value = a.duration || 0;
          playing.value = false;
          setTimeout(() => (currentTime.value = 0), 300);
        });
        a.src = props.src;
        audio = a;
        a.play()
          .then(() => {
            playing.value = true;
            startTick();
          })
          .catch(() => {});
        return;
      }
      if (!audio.paused) {
        audio.pause();
        stopTick();
        playing.value = false;
      } else {
        audio.currentTime = 0;
        audio
          .play()
          .then(() => {
            playing.value = true;
            startTick();
          })
          .catch(() => {});
      }
    };

    const handleSeek = (e: MouseEvent) => {
      if (!trackEl.value || !audio) return;
      const rect = trackEl.value.getBoundingClientRect();
      const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
      audio.currentTime = pct * duration.value;
      currentTime.value = audio.currentTime;
    };

    return () => {
      const pct = duration.value > 0 ? (currentTime.value / duration.value) * 100 : 0;

      return (
        <div class="mini-audio-player">
          <button class="mini-audio-play-btn" onClick={togglePlay}>
            {playing.value ? (
              <PhPause size={12} weight="fill" />
            ) : (
              <PhPlay size={12} weight="fill" />
            )}
          </button>
          <span class="mini-audio-time">{formatTimeShort(currentTime.value)}</span>
          <div ref={trackEl} class="mini-audio-track" onClick={handleSeek}>
            <div class="mini-audio-fill" style={{ width: `${pct}%` }} />
          </div>
          <span class="mini-audio-time">{formatTimeShort(duration.value)}</span>
          {playing.value && (
            <PhWaveform size={10} weight="light" class="mini-audio-wave" />
          )}
        </div>
      );
    };
  },
});
