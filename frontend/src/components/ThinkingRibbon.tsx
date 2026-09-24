import {
  defineComponent,
  ref,
  watch,
  onBeforeUnmount,
  type PropType,
} from "vue";
import gsap from "gsap";
import type { ChatMessage } from "../stores/chat";
import { useChatStore } from "../stores/chat";
import { PhSparkle, PhStop } from "@phosphor-icons/vue";

export default defineComponent({
  name: "ThinkingRibbon",
  props: {
    messages: {
      type: Array as PropType<ChatMessage[]>,
      default: () => [],
    },
  },
  setup(props) {
    const ribbonEl = ref<HTMLDivElement | null>(null);
    const chat = useChatStore();

    const isThinking = () => {
      const ms = props.messages;
      for (let i = ms.length - 1; i >= 0; i--) {
        const m = ms[i];
        if (m.role === "agent") {
          return m.status === "thinking" || m.status === "streaming";
        }
        if (m.role === "user") return false;
      }
      return false;
    };

    const currentText = (): string => {
      const ms = props.messages;
      for (let i = ms.length - 1; i >= 0; i--) {
        const m = ms[i];
        if (m.role === "agent") {
          return m.statusText || (m.status === "streaming" ? "正在回复" : "正在思考");
        }
        if (m.role === "user") return "";
      }
      return "";
    };

    let active = false;

    const enter = () => {
      const el = ribbonEl.value;
      if (!el) return;
      el.style.display = "";
      gsap.fromTo(
        el,
        { height: 0, opacity: 0 },
        {
          height: "auto",
          opacity: 1,
          duration: 0.28,
          ease: "power3.out",
        },
      );
    };

    const leave = () => {
      const el = ribbonEl.value;
      if (!el) return;
      gsap.to(el, {
        height: 0,
        opacity: 0,
        duration: 0.2,
        ease: "power2.in",
        onComplete: () => {
          if (ribbonEl.value) ribbonEl.value.style.display = "none";
        },
      });
    };

    watch(
      () => props.messages,
      () => {
        const next = isThinking();
        if (next && !active) {
          active = true;
          enter();
        } else if (!next && active) {
          active = false;
          leave();
        }
      },
      { deep: true, immediate: true },
    );

    onBeforeUnmount(() => {
      gsap.killTweensOf(ribbonEl.value || {});
    });

    return () => (
      <div
        ref={ribbonEl}
        class="thinking-ribbon"
        style={{ display: "none", height: "0", overflow: "hidden" }}
        aria-live="polite"
      >
        <div class="thinking-ribbon-inner">
          <span class="thinking-ribbon-dot">
            <PhSparkle size={12} weight="fill" />
          </span>
          <span class="thinking-ribbon-text">{currentText() || "正在思考"}</span>
          <button
            class="thinking-ribbon-stop"
            onClick={() => chat.cancel()}
            title="停止本轮生成"
          >
            <PhStop size={11} weight="fill" />
            停止
          </button>
        </div>
      </div>
    );
  },
});
