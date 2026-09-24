import { defineComponent, ref, watch, onBeforeUnmount } from "vue";
import { PhCheckCircle, PhInfo, PhWarning, PhXCircle, PhX } from "@phosphor-icons/vue";
import { useToastStore, type ToastConfig, type ToastType } from "../stores/toast";
import "./Toast.css";

export type { ToastConfig, ToastType };
export { useToast } from "../stores/toast";

const ICON_MAP: Record<ToastType, ReturnType<typeof defineComponent>> = {
  success: PhCheckCircle,
  info: PhInfo,
  error: PhXCircle,
  warning: PhWarning,
};

const ToastItem = defineComponent({
  name: "ToastItem",
  props: {
    config: { type: Object as () => ToastConfig, required: true },
  },
  emits: ["remove"],
  setup(props, { emit }) {
    const exiting = ref(false);
    let timer: ReturnType<typeof setTimeout> | undefined;

    const handleClose = () => {
      exiting.value = true;
      setTimeout(() => emit("remove", props.config.id), 150);
    };

    watch(
      () => props.config.duration,
      (duration) => {
        if (timer) clearTimeout(timer);
        if (duration && duration > 0) {
          timer = setTimeout(handleClose, duration);
        }
      },
      { immediate: true },
    );

    onBeforeUnmount(() => {
      if (timer) clearTimeout(timer);
    });

    return () => {
      const config = props.config;
      const Icon = ICON_MAP[config.type];
      return (
        <div class={`toast-item toast-${config.type} ${exiting.value ? "toast-exit" : "toast-enter"}`}>
          <span class="toast-icon">
            <Icon size={18} weight="fill" />
          </span>
          <div class="toast-content">
            <div class="toast-title">{config.title}</div>
            {config.message && <div class="toast-message">{config.message}</div>}
          </div>
          <button class="toast-close" onClick={handleClose}>
            <PhX size={14} weight="light" />
          </button>
          {config.progress !== undefined && (
            <div class="toast-progress">
              <div
                class="toast-progress-fill"
                style={{ width: `${Math.min(100, Math.max(0, config.progress))}%` }}
              />
            </div>
          )}
        </div>
      );
    };
  },
});

export const ToastProvider = defineComponent({
  name: "ToastProvider",
  setup(_, { slots }) {
    const store = useToastStore();
    return () => (
      <>
        {slots.default?.()}
        <div class="toast-container">
          {store.toasts.map((t) => (
            <ToastItem key={t.id} config={t} onRemove={(id: string) => store.removeToast(id)} />
          ))}
        </div>
      </>
    );
  },
});
