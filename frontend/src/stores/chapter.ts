import { ref } from "vue";
import { defineStore } from "pinia";
import {
  createChapterInVolume as createChapterInVolumeApi,
  insertChapter as insertChapterApi,
  deleteChapter as deleteChapterApi,
  updateChapter as updateChapterApi,
  getChapters,
  getChapter,
  reorderChapters as reorderChaptersApi,
  type ChapterInfo,
} from "../api";

export const useChapterStore = defineStore("chapter", () => {
  const chapters = ref<ChapterInfo[]>([]);
  const selectedChapterId = ref<number | null>(null);
  const loading = ref(false);

  const loadChapters = async (projectId: number) => {
    if (projectId == null) return;
    loading.value = true;
    try {
      chapters.value = await getChapters(projectId);
      if (
        selectedChapterId.value != null &&
        !chapters.value.some((c) => c.id === selectedChapterId.value)
      ) {
        selectedChapterId.value = null;
      }
      if (selectedChapterId.value === null && chapters.value.length > 0) {
        await selectChapter(chapters.value[0].id);
      } else if (selectedChapterId.value != null) {
        await selectChapter(selectedChapterId.value);
      }
    } catch (e) {
      console.error("Failed to load chapters:", e);
    } finally {
      loading.value = false;
    }
  };

  const selectChapter = async (id: number | null) => {
    selectedChapterId.value = id;
    if (id == null) return;
    const ch = chapters.value.find((c) => c.id === id);
    if (ch && ch.content === undefined) {
      try {
        const full = await getChapter(id);
        Object.assign(ch, full);
      } catch {
      }
    }
  };

  const createChapterInVolume = async (
    projectId: number,
    volumeId: number,
    title: string = "新章节",
  ) => {
    const res = await createChapterInVolumeApi(projectId, volumeId, title);
    await loadChapters(projectId);
    return res;
  };

  const insertChapter = async (
    projectId: number,
    targetChapterId: number,
    position: "before" | "after",
    title: string = "新章节",
  ) => {
    const res = await insertChapterApi(projectId, targetChapterId, position, title);
    await loadChapters(projectId);
    return res;
  };

  const saveChapter = async (
    chapterId: number,
    data: { title: string; content: string },
  ) => {
    await updateChapterApi(chapterId, data);
    const ch = chapters.value.find((c) => c.id === chapterId);
    if (ch) {
      ch.title = data.title;
      ch.content = data.content;
      ch.word_count = data.content.length;
    }
  };

  const removeChapter = async (chapterId: number) => {
    await deleteChapterApi(chapterId);
    if (selectedChapterId.value === chapterId) {
      selectedChapterId.value = null;
    }
  };

  let reorderTimer: ReturnType<typeof setTimeout> | null = null;

  const moveChapter = (
    projectId: number,
    dragId: number,
    targetChapterId: number,
    position: "before" | "after",
    hooks?: { onCommitted?: () => void; onRollback?: () => void },
    crossVolume = false,
  ): ChapterInfo[] | undefined => {
    const list = chapters.value;
    const from = list.findIndex((c) => c.id === dragId);
    const anchor = list.findIndex((c) => c.id === targetChapterId);
    if (from < 0 || anchor < 0 || from === anchor) return;
    if (!crossVolume) {
      if (position === "before" && from === anchor - 1) return;
      if (position === "after" && from === anchor + 1) return;
    }

    const next = [...list];
    const [moved] = next.splice(from, 1);
    const anchorAfter = next.findIndex((c) => c.id === targetChapterId);
    next.splice(position === "before" ? anchorAfter : anchorAfter + 1, 0, moved);
    next.forEach((c, i) => { c.chapter_index = i; });
    chapters.value = next;

    if (reorderTimer !== null) clearTimeout(reorderTimer);
    const orderedIds = next.map((c) => c.id);
    reorderTimer = setTimeout(async () => {
      reorderTimer = null;
      try {
        await reorderChaptersApi(projectId, orderedIds, dragId);
        hooks?.onCommitted?.();
      } catch (e) {
        console.error("Failed to reorder chapters:", e);
        await loadChapters(projectId);
        hooks?.onRollback?.();
      }
    }, 400);
    return next;
  };

  const cancelPendingReorder = () => {
    if (reorderTimer !== null) {
      clearTimeout(reorderTimer);
      reorderTimer = null;
    }
  };

  const reset = () => {
    chapters.value = [];
    selectedChapterId.value = null;
    loading.value = false;
    cancelPendingReorder();
  };

  return {
    chapters,
    selectedChapterId,
    loading,
    loadChapters,
    selectChapter,
    createChapterInVolume,
    insertChapter,
    saveChapter,
    removeChapter,
    moveChapter,
    cancelPendingReorder,
    reset,
  };
});
