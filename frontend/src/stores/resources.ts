import { ref } from "vue";
import { defineStore, acceptHMRUpdate } from "pinia";
import {
  listResources,
  type ResourceItem,
} from "../api";

const BATCH_SIZE = 30;

export const useResourceStore = defineStore("resources", () => {
  const resources = ref<ResourceItem[]>([]);
  const filter = ref<"all" | "sfx" | "bgm">("all");
  const total = ref(0);
  const loading = ref(true);
  const loadingMore = ref(false);

  const loadResources = async (append = false) => {
    try {
      if (append) loadingMore.value = true;
      else loading.value = true;
      const typeFilter = filter.value === "all" ? undefined : filter.value;
      const page = append
        ? Math.floor(resources.value.length / BATCH_SIZE) + 1
        : 1;
      const result = await listResources(typeFilter, page, BATCH_SIZE);
      const { List, Total } = result.data;
      resources.value = append ? [...resources.value, ...List] : List;
      total.value = Total;
    } catch {
    } finally {
      loading.value = false;
      loadingMore.value = false;
    }
  };

  const setFilter = (f: "all" | "sfx" | "bgm") => {
    if (filter.value === f) return;
    filter.value = f;
    resources.value = [];
    loadResources();
  };

  const allResources = ref<ResourceItem[]>([]);
  const allLoading = ref(false);

  const loadAll = async (force = false) => {
    if (allLoading.value) return;
    if (!force && allResources.value.length > 0) return;
    allLoading.value = true;
    try {
      const all: ResourceItem[] = [];
      let page = 1;
      for (;;) {
        const d = await listResources(undefined, page, 100);
        all.push(...(d.data?.List || []));
        if (all.length >= (d.data?.Total ?? 0)) break;
        page += 1;
      }
      allResources.value = all;
    } catch {
    } finally {
      allLoading.value = false;
    }
  };

  const addLocal = (item: ResourceItem) => {
    resources.value = [item, ...resources.value];
    allResources.value = [item, ...allResources.value];
    total.value += 1;
  };

  const removeLocal = (ids: number[]) => {
    const idSet = new Set(ids);
    resources.value = resources.value.filter((r) => !idSet.has(r.id));
    allResources.value = allResources.value.filter((r) => !idSet.has(r.id));
    total.value = Math.max(0, total.value - ids.length);
  };

  const replaceLocal = (item: ResourceItem) => {
    const idx = resources.value.findIndex((r) => r.id === item.id);
    if (idx !== -1) resources.value.splice(idx, 1, item);
    const aidx = allResources.value.findIndex((r) => r.id === item.id);
    if (aidx !== -1) allResources.value.splice(aidx, 1, item);
  };

  return {
    resources,
    filter,
    total,
    loading,
    loadingMore,
    allResources,
    allLoading,
    loadResources,
    setFilter,
    loadAll,
    addLocal,
    removeLocal,
    replaceLocal,
  };
});

if (import.meta.hot) {
  import.meta.hot.accept(acceptHMRUpdate(useResourceStore, import.meta.hot));
}
