import { ref, computed } from "vue";
import { defineStore, acceptHMRUpdate } from "pinia";
import {
  listProviders,
  addProvider,
  deleteProvider,
  batchDeleteProviders,
  activateProvider,
  updateProvider,
  type ProviderInfo,
} from "../api";

type NewProvider = {
  provider_name: string;
  kind: string;
  model_id: string;
  context_length: number;
  active: boolean;
  api_url: string;
  api_key: string;
};

const PROVIDER_PAGESIZE = 10;

export const useProviderStore = defineStore("providers", () => {
  const providers = ref<ProviderInfo[]>([]);
  const page = ref(0);
  const hasMore = ref(false);
  const total = ref(0);
  const loading = ref(false);
  const loaded = ref(false);

  const llmAvailable = computed(() => providers.value.length > 0);

  const loadProviders = (reset: boolean): Promise<void> => {
    if (loading.value) return Promise.resolve();
    if (!reset && !hasMore.value) return Promise.resolve();
    loading.value = true;
    const target = reset ? 1 : page.value + 1;
    return listProviders(target, PROVIDER_PAGESIZE)
      .then((d) => {
        const { List = [], Total = 0, More = false } = d.data ?? {};
        providers.value = reset ? List : [...providers.value, ...List];
        page.value = target;
        hasMore.value = More;
        total.value = Total;
        loaded.value = true;
      })
      .catch((e) => {
        console.error(e);
      })
      .finally(() => (loading.value = false));
  };

  const ensureLoaded = () =>
    loaded.value ? Promise.resolve() : loadProviders(true);

  const create = async (data: NewProvider) => {
    await addProvider(data);
    await loadProviders(true);
  };

  const remove = async (id: number) => {
    await deleteProvider(id);
    await loadProviders(true);
  };

  const batchRemove = async (ids: number[]) => {
    await batchDeleteProviders(ids);
    await loadProviders(true);
  };

  const activate = async (id: number) => {
    await activateProvider(id);
    await loadProviders(true);
  };

  const update = async (id: number, data: Partial<NewProvider>) => {
    await updateProvider(id, data);
    await loadProviders(true);
  };

  return {
    providers,
    page,
    hasMore,
    total,
    loading,
    llmAvailable,
    loadProviders,
    ensureLoaded,
    create,
    remove,
    batchRemove,
    activate,
    update,
  };
});

if (import.meta.hot) {
  import.meta.hot.accept(acceptHMRUpdate(useProviderStore, import.meta.hot));
}
