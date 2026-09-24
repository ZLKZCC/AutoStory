import { ref } from "vue";
import { defineStore, acceptHMRUpdate } from "pinia";

export type ToastType = "success" | "info" | "error" | "warning";

export interface ToastConfig {
  id: string;
  type: ToastType;
  title: string;
  message?: string;
  duration?: number; // ms, 0 = manual close only
  progress?: number; // 0-100, show progress bar when set
}

let _toastId = 0;

export const useToastStore = defineStore("toast", () => {
  const toasts = ref<ToastConfig[]>([]);

  const addToast = (config: Omit<ToastConfig, "id">): string => {
    const id = `toast-${++_toastId}`;
    toasts.value.push({ ...config, id });
    return id;
  };

  const removeToast = (id: string) => {
    toasts.value = toasts.value.filter((t) => t.id !== id);
  };

  const updateToast = (id: string, patch: Partial<ToastConfig>) => {
    toasts.value = toasts.value.map((t) => (t.id === id ? { ...t, ...patch } : t));
  };

  return { toasts, addToast, removeToast, updateToast };
});

export const useToast = () => {
  const store = useToastStore();
  return {
    addToast: store.addToast,
    removeToast: store.removeToast,
    updateToast: store.updateToast,
  };
};

if (import.meta.hot) {
  import.meta.hot.accept(acceptHMRUpdate(useToastStore, import.meta.hot));
}
