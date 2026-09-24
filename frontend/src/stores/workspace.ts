import { ref, computed } from "vue";
import { defineStore } from "pinia";
import { getProject, listProjects, type ProjectInfo } from "../api";
import { useChapterStore } from "./chapter";
import { useVolumeStore } from "./volume";

export const useWorkspaceStore = defineStore("workspace", () => {
  const chapterStore = useChapterStore();
  const volumeStore = useVolumeStore();

  const projectId = ref<number | null>(null);
  const project = ref<ProjectInfo | null>(null);

  const chapters = computed(() => chapterStore.chapters);
  const selectedChapterId = computed(() => chapterStore.selectedChapterId);
  const selectedChapter = computed(
    () =>
      chapterStore.chapters.find((c) => c.id === chapterStore.selectedChapterId) ??
      null,
  );
  const volumes = computed(() => volumeStore.volumes);

  const loadWorkspace = async (idOrName: string) => {
    let info: ProjectInfo | null = null;
    const asId = Number(idOrName);
    if (Number.isInteger(asId) && asId > 0) {
      try {
        info = await getProject(asId);
      } catch {
        info = null;
      }
    }
    if (!info) {
      try {
        const list = await listProjects();
        info = list.find((p) => p.name === idOrName) ?? null;
      } catch {
        info = null;
      }
    }
    if (!info || info.id == null) {
      projectId.value = null;
      project.value = null;
      return;
    }
    const pid = info.id;
    projectId.value = pid;
    project.value = info;
    chapterStore.reset();
    volumeStore.reset();
    await Promise.all([
      volumeStore.loadProjectVolumes(pid),
      chapterStore.loadChapters(pid),
    ]);
  };

  const chatFocusSeq = ref(0);
  const requestChatFocus = () => { chatFocusSeq.value++; };

  const refreshStructure = async () => {
    if (projectId.value == null) return;
    await Promise.all([
      chapterStore.loadChapters(projectId.value),
      volumeStore.refreshVolumes(projectId.value),
    ]);
  };

  const loadChapters = () =>
    projectId.value == null
      ? Promise.resolve()
      : chapterStore.loadChapters(projectId.value);

  const selectChapter = (id: number | null) => chapterStore.selectChapter(id);

  const saveChapter = (chapterId: number, data: { title: string; content: string }) =>
    chapterStore.saveChapter(chapterId, data);

  const createChapterInVolume = async (
    volumeId: number,
    title: string = "新章节",
  ) => {
    if (projectId.value == null) return;
    await chapterStore.createChapterInVolume(projectId.value, volumeId, title);
    await volumeStore.refreshVolumes(projectId.value);
  };

  const insertChapter = async (
    targetChapterId: number,
    position: "before" | "after",
    title: string = "新章节",
  ) => {
    if (projectId.value == null) return;
    await chapterStore.insertChapter(projectId.value, targetChapterId, position, title);
    await volumeStore.refreshVolumes(projectId.value);
  };

  const removeChapter = async (chapterId: number) => {
    if (projectId.value == null) return;
    await chapterStore.removeChapter(chapterId);
    await refreshStructure();
  };

  const moveChapter = (
    dragId: number,
    targetChapterId: number,
    position: "before" | "after",
    targetVolumeId?: number,
  ) => {
    if (projectId.value == null) return;
    const pid = projectId.value;
    const srcVol = volumeStore.volumes.find((v) => v.chapters?.some((c) => c.id === dragId));
    const crossVolume = srcVol != null && targetVolumeId != null && srcVol.id !== targetVolumeId;
    const optimistic = chapterStore.moveChapter(pid, dragId, targetChapterId, position, {
      onCommitted: crossVolume ? () => volumeStore.refreshVolumes(pid) : undefined,
      onRollback: () => volumeStore.refreshVolumes(pid),
    }, crossVolume);
    if (optimistic && targetVolumeId != null) {
      volumeStore.applyLocalReorder(dragId, targetVolumeId, optimistic);
    }
  };

  const cancelPendingReorder = () => chapterStore.cancelPendingReorder();

  const createVolume = async (name: string) => {
    if (projectId.value == null) return null;
    return volumeStore.createVolume(projectId.value, name);
  };

  const expandVolume = async (volumeId: number) => {
    if (projectId.value == null) return;
    await volumeStore.toggleExpand(volumeId, projectId.value);
  };

  const loadVolumeChapters = (volumeId: number, page: number = 1) =>
    projectId.value == null
      ? Promise.resolve()
      : volumeStore.loadVolumeChapters(volumeId, projectId.value, page);

  const loadMoreChapters = (volumeId: number) =>
    projectId.value == null
      ? Promise.resolve()
      : volumeStore.loadMoreChapters(volumeId, projectId.value);

  return {
    projectId,
    project,
    loadWorkspace,

    chatFocusSeq,
    requestChatFocus,

    refreshStructure,

    chapters,
    selectedChapterId,
    selectedChapter,
    loadChapters,
    selectChapter,
    saveChapter,
    createChapterInVolume,
    insertChapter,
    removeChapter,
    moveChapter,
    cancelPendingReorder,

    volumes,
    createVolume,
    expandVolume,
    loadVolumeChapters,
    loadMoreChapters,
  };
});
