import { defineComponent, ref, watch, onMounted, computed } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter, RouterView } from "vue-router";
import BootScreen from "./components/BootScreen";
import { ToastProvider } from "./components/Toast";
import ConfirmDialog, { useConfirm } from "./components/ConfirmDialog";
import StarDialog from "./components/StarDialog";
import { useProjectStore } from "./stores/projects";
import {
  PhBookOpen,
  PhGearSix,
  PhCaretRight,
  PhMusicNote,
  PhTrash,
  PhCheck,
  PhX,
  PhPencilSimple,
  PhCheckSquare,
  PhSquare,
  PhArrowLeft,
  PhBookBookmark,
} from "@phosphor-icons/vue";

export function useProjectList() {
  const store = useProjectStore();
  const { projects } = storeToRefs(store);
  return {
    projects,
    refreshProjects: store.refreshProjects,
    addProject: store.addProject,
    removeProject: store.removeProject,
    removeProjects: store.removeProjects,
  };
}

const Sidebar = defineComponent({
  name: "AppSidebar",
  setup() {
    const route = useRoute();
    const nav = useRouter();
    const projectStore = useProjectStore();
    const { projects } = storeToRefs(projectStore);
    const { removeProject, removeProjects } = projectStore;

    const path = computed(() => route.path);
    const isHome = computed(() => path.value === "/");
    const isSettings = computed(() => path.value === "/settings");
    const isResources = computed(() => path.value === "/resources");
    const isKnowledgeBase = computed(() => path.value === "/knowledge-base");
    const currentProjectId = computed(() => {
      if (!path.value.startsWith("/project/")) return null;
      const raw = decodeURIComponent(path.value.split("/project/")[1]);
      const asId = Number(raw);
      return Number.isInteger(asId) && asId > 0 ? asId : null;
    });

    const expanded = ref(true);
    const { confirm } = useConfirm();

    const selectMode = ref(false);
    const selectedIds = ref<Set<number>>(new Set());

    const toggleSelect = (id: number) => {
      const next = new Set(selectedIds.value);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      selectedIds.value = next;
    };

    const selectAll = () => {
      selectedIds.value = new Set(projects.value.map((p) => p.id!));
    };

    const deselectAll = () => {
      selectedIds.value = new Set();
    };

    const exitSelectMode = () => {
      selectMode.value = false;
      selectedIds.value = new Set();
    };

    const handleBatchDelete = async () => {
      if (selectedIds.value.size === 0) return;
      const count = selectedIds.value.size;
      const ok = await confirm({
        title: "批量删除作品",
        message: `确定要删除选中的 ${count} 个作品吗？所有项目下的章节、角色、音频与数据将一并删除，不可恢复。`,
        danger: true,
        confirmText: "确认删除",
      });
      if (!ok) return;
      const ids = Array.from(selectedIds.value);
      await removeProjects(ids);
      if (currentProjectId.value && selectedIds.value.has(currentProjectId.value)) {
        nav.push("/");
      }
      exitSelectMode();
    };

    const handleDelete = async (e: MouseEvent, id: number, displayName: string) => {
      e.stopPropagation();
      const ok = await confirm({
        title: "删除作品",
        message: `确定要删除作品「${displayName}」吗？该项目下全部章节、角色、音频与数据将一并删除，不可恢复。`,
        danger: true,
        confirmText: "确认删除",
      });
      if (!ok) return;
      await removeProject(id);
      if (currentProjectId.value === id) nav.push("/");
    };

    return () => (
      <aside class="sidebar">
        <div class="sidebar-brand">
          <img src="/logo.png" alt="" class="sidebar-brand-logo" />
          <div class="sidebar-brand-name">
            <span class="auto">Auto</span>
            <span class="story">Story{"\u200B"}</span>
          </div>
        </div>

        <nav class="sidebar-nav">
          <div class="sidebar-section-label">工作区</div>

          <div class="sidebar-group">
            <button
              class={`sidebar-item ${isHome.value && !currentProjectId.value ? "active" : ""}`}
              onClick={() => {
                if (selectMode.value) {
                  exitSelectMode();
                  return;
                }
                if (!expanded.value && projects.value.length > 0) expanded.value = true;
                nav.push("/");
              }}
            >
              <span class="sidebar-item-icon">
                <PhBookOpen size={18} weight="light" />
              </span>
              <span class="sidebar-item-label">
                {selectMode.value ? `已选 ${selectedIds.value.size} 项` : "作品"}
              </span>
              {selectMode.value ? (
                <span
                  class="sidebar-expand-icon"
                  onClick={(e) => {
                    e.stopPropagation();
                    exitSelectMode();
                  }}
                  title="退出选择"
                >
                  <PhArrowLeft size={12} weight="bold" />
                </span>
              ) : (
                <>
                  {projects.value.length > 0 && (
                    <>
                      <span
                        class="sidebar-edit-icon"
                        onClick={(e) => {
                          e.stopPropagation();
                          selectMode.value = true;
                        }}
                        title="批量管理"
                      >
                        <PhPencilSimple size={12} weight="light" />
                      </span>
                      <span
                        class="sidebar-expand-icon"
                        onClick={(e) => {
                          e.stopPropagation();
                          expanded.value = !expanded.value;
                        }}
                      >
                        <PhCaretRight
                          size={12}
                          weight="bold"
                          style={{
                            transition: "transform 0.2s ease",
                            transform: expanded.value
                              ? "rotate(90deg)"
                              : "rotate(0deg)",
                          }}
                        />
                      </span>
                    </>
                  )}
                </>
              )}
            </button>

            {selectMode.value && expanded.value && projects.value.length > 0 && (
              <div class="sidebar-batch-bar">
                <div class="sidebar-batch-row">
                  <button
                    class="sidebar-batch-btn"
                    onClick={selectAll}
                    title="全选"
                  >
                    <PhCheckSquare size={13} weight="light" />
                    <span>全选</span>
                  </button>
                  <button
                    class="sidebar-batch-btn"
                    onClick={deselectAll}
                    title="取消全选"
                  >
                    <PhSquare size={13} weight="light" />
                    <span>取消</span>
                  </button>
                </div>
                <button
                  class="sidebar-batch-btn sidebar-batch-delete"
                  onClick={handleBatchDelete}
                  disabled={selectedIds.value.size === 0}
                  title={`删除 ${selectedIds.value.size} 个作品`}
                >
                  <PhTrash size={13} weight="light" />
                  <span>删除({selectedIds.value.size})</span>
                </button>
              </div>
            )}

            {expanded.value && projects.value.length > 0 && (
              <div class="sidebar-sub-list">
                {projects.value.map((p) => {
                  const isSelected = selectedIds.value.has(p.id!);

                  return (
                    <button
                      key={p.id}
                      class={`sidebar-item sidebar-subitem ${currentProjectId.value === p.id ? "active" : ""} ${selectMode.value && isSelected ? "sidebar-subitem-selected" : ""}`}
                      onClick={() => {
                        if (selectMode.value) {
                          toggleSelect(p.id!);
                        } else {
                          nav.push(`/project/${p.id}`);
                        }
                      }}
                      onContextmenu={(e) => {
                        e.preventDefault();
                        if (!selectMode.value) {
                          selectMode.value = true;
                          selectedIds.value = new Set([p.id!]);
                        }
                      }}
                    >
                      {selectMode.value && (
                        <span class="sidebar-checkbox">
                          {isSelected ? (
                            <PhCheckSquare
                              size={14}
                              weight="fill"
                              style={{ color: "var(--color-accent)" }}
                            />
                          ) : (
                            <PhSquare size={14} weight="light" />
                          )}
                        </span>
                      )}
                      <span class="sidebar-item-label">{p.name}</span>
                      {!selectMode.value && (
                        <span
                          class="sidebar-delete-btn"
                          onClick={(e) => handleDelete(e, p.id!, p.name)}
                          title="删除作品"
                        >
                          <PhTrash size={12} weight="light" />
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          <button
            class={`sidebar-item ${isResources.value ? "active" : ""}`}
            onClick={() => nav.push("/resources")}
          >
            <span class="sidebar-item-icon">
              <PhMusicNote size={18} weight="light" />
            </span>
            <span class="sidebar-item-label">音频库</span>
          </button>

          <button
            class={`sidebar-item ${isKnowledgeBase.value ? "active" : ""}`}
            onClick={() => nav.push("/knowledge-base")}
          >
            <span class="sidebar-item-icon">
              <PhBookBookmark size={18} weight="light" />
            </span>
            <span class="sidebar-item-label">素材库</span>
          </button>

          <div class="sidebar-section-label" style={{ marginTop: "8px" }}>
            系统
          </div>

          <button
            class={`sidebar-item ${isSettings.value ? "active" : ""}`}
            onClick={() => nav.push("/settings")}
          >
            <span class="sidebar-item-icon">
              <PhGearSix size={18} weight="light" />
            </span>
            <span class="sidebar-item-label">模型设置</span>
          </button>
        </nav>
      </aside>
    );
  },
});

const MainContent = defineComponent({
  name: "MainContent",
  setup() {
    const route = useRoute();
    return () => (
      <main class="main-content" key={route.fullPath}>
        <RouterView />
      </main>
    );
  },
});

export default defineComponent({
  name: "App",
  setup() {
    const booted = ref(false);
    const route = useRoute();
    const projectStore = useProjectStore();

    onMounted(() => projectStore.refreshProjects());

    watch(() => route.path, () => projectStore.refreshProjects());

    return () =>
      !booted.value ? (
        <BootScreen onComplete={() => (booted.value = true)} />
      ) : (
        <ToastProvider>
          <ConfirmDialog>
            <StarDialog />
            <div class="app-shell">
              <Sidebar />
              <MainContent />
            </div>
          </ConfirmDialog>
        </ToastProvider>
      );
  },
});
