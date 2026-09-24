import { ref } from "vue";
import { defineStore, acceptHMRUpdate } from "pinia";
import { listProjects, deleteProject, batchDeleteProjects, type ProjectInfo } from "../api";
import { useChatStore } from "./chat";
import { useAudiobookStore } from "./audiobook";

export const useProjectStore = defineStore("projects", () => {
  const projects = ref<ProjectInfo[]>([]);

  const refreshProjects = async () => {
    try {
      projects.value = await listProjects();
    } catch {}
  };

  const addProject = (project: ProjectInfo) => {
    projects.value = [project, ...projects.value];
  };

  const findById = (id: number) => projects.value.find((p) => p.id === id) ?? null;
  const findByName = (name: string) => projects.value.find((p) => p.name === name) ?? null;

  const removeProject = async (id: number) => {
    const target = findById(id);
    if (!target) throw new Error("项目不存在");
    await deleteProject(id);
    projects.value = projects.value.filter((p) => p.id !== id);
    useChatStore().dropShard(id);
    useAudiobookStore().dropShard(id);
  };

  const removeProjects = async (ids: number[]) => {
    const unique = Array.from(new Set(ids));   // 去重（选择模式下理论上不会重复，兜底）
    if (unique.length === 0) return;
    await batchDeleteProjects(unique);
    const removedIds = new Set<number>(unique);
    projects.value = projects.value.filter((p) => !removedIds.has(p.id!));
    const chat = useChatStore();
    const audiobook = useAudiobookStore();
    for (const id of unique) {
      chat.dropShard(id);
      audiobook.dropShard(id);
    }
  };

  return {
    projects,
    refreshProjects,
    addProject,
    removeProject,
    removeProjects,
    findById,
    findByName,
  };
});

if (import.meta.hot) {
  import.meta.hot.accept(acceptHMRUpdate(useProjectStore, import.meta.hot));
}
