import { ref } from "vue";
import { defineStore, acceptHMRUpdate } from "pinia";
import {
  checkModels,
  prepareModels,
  retryFailedModels,
  type CheckModelItem,
  type PrepareItem,
  type WsChannel,
} from "../api";

export const useModelSyncStore = defineStore("modelSync", () => {
  const localModels = ref<CheckModelItem[]>([]);
  const downloading = ref<Record<string, PrepareItem>>({});
  const downloadedIds = ref<Set<string>>(new Set());
  const syncing = ref(false);
  const checking = ref(false);

  let syncWs: WsChannel | null = null;

  const refreshLocalModels = () => {
    if (checking.value) return;
    checking.value = true;
    checkModels()
      .then((d) => {
        localModels.value = d.items || [];
      })
      .catch(() => {})
      .finally(() => {
        checking.value = false;
      });
  };

  const startSync = async () => {
    if (syncWs || syncing.value) return;
    syncing.value = true;
    // 用户显式同步：先复活本会话报错的模型再连 WS（复活失败静默，继续拉新状态）
    try {
      await retryFailedModels();
    } catch {}
    syncWs = prepareModels(
      (list) => {
        syncing.value = false;
        list.forEach((item) => {
          const m = localModels.value.find((x) => x.name === item.name);
          if (m) downloading.value = { ...downloading.value, [m.id]: item };
        });
        if (list.every((it) => it.status === "done" || it.status === "error")) {
          syncWs?.close();
          syncWs = null;
          const doneIds = new Set(downloadedIds.value);
          const rest: Record<string, PrepareItem> = {};
          list.forEach((item) => {
            const m = localModels.value.find((x) => x.name === item.name);
            if (!m) return;
            if (item.status === "done") doneIds.add(m.id);
            else if (item.status === "error") rest[m.id] = item;
          });
          downloadedIds.value = doneIds;
          downloading.value = rest;
          refreshLocalModels();
        }
      },
      {
        onClose: () => {
          syncing.value = false;
          syncWs = null;
        },
      },
    );
  };

  return { localModels, downloading, downloadedIds, syncing, checking, refreshLocalModels, startSync };
});

if (import.meta.hot) {
  import.meta.hot.accept(acceptHMRUpdate(useModelSyncStore, import.meta.hot));
}
