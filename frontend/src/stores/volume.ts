import { ref } from "vue";
import { defineStore } from "pinia";
import {
  getProjectVolumes,
  getVolumeChapters,
  createVolume as createVolumeApi,
  type ChapterInfo,
  type VolumeWithChapters,
} from "../api";

export const useVolumeStore = defineStore("volume", () => {
  const volumes = ref<VolumeWithChapters[]>([]);
  const loading = ref(false);

  const loadProjectVolumes = async (projectId: number) => {
    if (projectId == null) return;
    loading.value = true;
    try {
      const res = await getProjectVolumes(projectId, true);
      volumes.value = (res.data || []).map((v) => ({
        ...v,
        expanded: false,
        chapters: undefined,
        currentPage: 1,
        hasMore: false,
        loading: false,
      }));
    } catch (e) {
      console.error("Failed to load volumes:", e);
    } finally {
      loading.value = false;
    }
  };

  const refreshVolumes = async (projectId: number) => {
    if (projectId == null) return;
    const expandedIds = new Set(
      volumes.value.filter((v) => v.expanded).map((v) => v.id),
    );
    try {
      const res = await getProjectVolumes(projectId, true);
      volumes.value = (res.data || []).map((v) => ({
        ...v,
        expanded: expandedIds.has(v.id),
        chapters: undefined,
        currentPage: 1,
        hasMore: false,
        loading: false,
      }));
    } catch (e) {
      console.error("Failed to refresh volumes:", e);
      return;
    }
    for (const v of volumes.value) {
      if (v.expanded) loadVolumeChapters(v.id, projectId, 1);
    }
  };

  const loadVolumeChapters = async (
    volumeId: number,
    projectId: number,
    page: number = 1,
  ) => {
    const vol = volumes.value.find((v) => v.id === volumeId);
    if (!vol || vol.loading) return;
    vol.loading = true;
    try {
      const res = await getVolumeChapters(volumeId, page, 50);
      const list = res.data.List || [];
      if (page === 1) vol.chapters = [...list];
      else vol.chapters = [...(vol.chapters || []), ...list];
      vol.currentPage = page;
      vol.hasMore = res.data.More ?? false;
      if (vol.total_word_count == null) {
        vol.total_word_count = (vol.chapters || []).reduce(
          (sum, c) => sum + (c.word_count || 0),
          0,
        );
      }
    } catch (e) {
      console.error("Failed to load volume chapters:", e);
    } finally {
      vol.loading = false;
    }
  };

  const loadMoreChapters = async (volumeId: number, projectId: number) => {
    const vol = volumes.value.find((v) => v.id === volumeId);
    if (!vol || vol.loading || !vol.hasMore) return;
    await loadVolumeChapters(volumeId, projectId, (vol.currentPage || 1) + 1);
  };

  const toggleExpand = async (volumeId: number, projectId: number) => {
    const vol = volumes.value.find((v) => v.id === volumeId);
    if (!vol) return;
    vol.expanded = !vol.expanded;
    if (vol.expanded && !vol.chapters && !vol.loading) {
      await loadVolumeChapters(volumeId, projectId, 1);
    }
  };

  const applyLocalReorder = (
    dragId: number,
    targetVolumeId: number,
    globalChapters: ChapterInfo[],
  ) => {
    const dragged = globalChapters.find((c) => c.id === dragId);
    if (!dragged) return;
    for (const vol of volumes.value) {
      if (!vol.chapters) continue;
      const hasDrag = vol.chapters.some((c) => c.id === dragId);
      const isTarget = vol.id === targetVolumeId;
      if (hasDrag && isTarget) {
        const ids = new Set(vol.chapters.map((c) => c.id));
        vol.chapters = globalChapters.filter((c) => ids.has(c.id));
      } else if (hasDrag) {
        vol.chapters = vol.chapters.filter((c) => c.id !== dragId);
        vol.chapter_count = Math.max(0, (vol.chapter_count ?? 0) - 1);
        vol.total_word_count = Math.max(0, (vol.total_word_count ?? 0) - (dragged.word_count || 0));
      } else if (isTarget) {
        const ids = new Set(vol.chapters.map((c) => c.id));
        ids.add(dragId);
        vol.chapters = globalChapters.filter((c) => ids.has(c.id));
        vol.chapter_count = (vol.chapter_count ?? 0) + 1;
        vol.total_word_count = (vol.total_word_count ?? 0) + (dragged.word_count || 0);
      }
    }
  };

  const createVolume = async (projectId: number, name: string) => {
    const res = await createVolumeApi({
      project_id: projectId,
      name,
      volume_index: volumes.value.length, // 占位，后端重算
      chapter_start: -1,
      chapter_end: -1,
    });
    const vol: VolumeWithChapters = { ...res.data, expanded: true };
    volumes.value = [...volumes.value, vol];
    return vol;
  };

  const reset = () => {
    volumes.value = [];
    loading.value = false;
  };

  return {
    volumes,
    loading,
    loadProjectVolumes,
    refreshVolumes,
    loadVolumeChapters,
    loadMoreChapters,
    toggleExpand,
    applyLocalReorder,
    createVolume,
    reset,
  };
});
