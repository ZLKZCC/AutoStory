import { ref, watch } from "vue";
import { defineStore, acceptHMRUpdate } from "pinia";
import {
  listMaterials,
  listMaterialKnowledges,
  listKnowledgeChunks,
  type MaterialInfo,
  type MaterialKnowledge,
  type KnowledgeChunk,
} from "../api";

export const useKnowledgeStore = defineStore("knowledge", () => {
  const materials = ref<MaterialInfo[]>([]);
  const search = ref("");
  const sort = ref<"updated" | "created" | "name">("updated");
  const pageLoading = ref(true);

  const loadMaterials = async () => {
    try {
      const res = await listMaterials(search.value || undefined, sort.value);
      materials.value = res.materials || [];
    } catch {
      materials.value = [];
    }
  };

  watch([search, sort], () => loadMaterials());

  const selectedMaterial = ref<MaterialInfo | null>(null);
  const knowledges = ref<MaterialKnowledge[]>([]);
  const loading = ref(false);

  watch(selectedMaterial, (material) => {
    if (!material) return;
    loading.value = true;
    listMaterialKnowledges(material.id)
      .then((res) => (knowledges.value = res.knowledges || []))
      .catch(() => (knowledges.value = []))
      .finally(() => (loading.value = false));
  });

  const selectMaterial = (m: MaterialInfo | null) => {
    if (!m) {
      selectedMaterial.value = null;
      knowledges.value = [];
      return;
    }
    selectedMaterial.value = m;
  };

  const removeMaterialLocal = (id: number) => {
    materials.value = materials.value.filter((m) => m.id !== id);
    if (selectedMaterial.value?.id === id) selectedMaterial.value = null;
  };

  const reloadKnowledges = async (materialId: number) => {
    try {
      const res = await listMaterialKnowledges(materialId);
      knowledges.value = res.knowledges || [];
    } catch {
    }
  };

  const chunks = ref<Record<string, KnowledgeChunk[]>>({});

  const loadChunks = async (
    materialId: number,
    knowledgeName: string,
  ): Promise<KnowledgeChunk[] | null> => {
    const key = `${materialId}_${knowledgeName}`;
    if (chunks.value[key]) return chunks.value[key];
    try {
      const res = await listKnowledgeChunks(materialId, knowledgeName);
      const list = res.chunks || [];
      chunks.value = { ...chunks.value, [key]: list };
      return list;
    } catch {
      chunks.value = { ...chunks.value, [key]: [] };
      return [];
    }
  };

  const dropChunks = (key: string) => {
    if (!(key in chunks.value)) return;
    const next = { ...chunks.value };
    delete next[key];
    chunks.value = next;
  };

  const clearChunks = () => {
    chunks.value = {};
  };

  return {
    materials,
    search,
    sort,
    pageLoading,
    selectedMaterial,
    knowledges,
    loading,
    chunks,
    loadMaterials,
    selectMaterial,
    removeMaterialLocal,
    reloadKnowledges,
    loadChunks,
    dropChunks,
    clearChunks,
  };
});

if (import.meta.hot) {
  import.meta.hot.accept(acceptHMRUpdate(useKnowledgeStore, import.meta.hot));
}
