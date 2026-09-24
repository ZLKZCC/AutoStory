import { defineComponent, ref, watch, onMounted, type PropType } from "vue";
import {
  searchKnowledgeGlobal,
  getProjectKnowledges,
  addProjectKnowledge,
  deleteProjectKnowledge,
  type KnowledgeSearchResult,
  type ProjectKnowledgeRef,
} from "../api";
import Button from "./Button";
import { useToast } from "../stores/toast";
import { useConfirm } from "./ConfirmDialog";
import {
  PhGlobe,
  PhMagnifyingGlass,
  PhPlus,
  PhTrash,
  PhX,
  PhArrowClockwise,
} from "@phosphor-icons/vue";

const MAX_CHUNK_REFS = 20;

export default defineComponent({
  name: "KnowledgePanel",
  props: {
    projectId: { type: Number as PropType<number | null>, default: null },
    refreshSignal: { type: Number, default: 0 },
  },
  setup(props) {
    const refs = ref<ProjectKnowledgeRef[]>([]);
    const loading = ref(false);
    const searchQuery = ref("");
    const searchResults = ref<KnowledgeSearchResult[]>([]);
    const searching = ref(false);
    const showSearch = ref(false);
    const titleMap = ref<Record<string, string>>({});
    const { addToast, updateToast } = useToast();
    const { confirm } = useConfirm();

    const refContents = () => new Set(refs.value.map((r) => r.content));

    const refTitle = (r: ProjectKnowledgeRef) =>
      titleMap.value[r.content] ||
      (r.content.length > 30 ? r.content.slice(0, 30) + "..." : r.content);

    const loadRefs = () => {
      if (props.projectId == null) return;
      loading.value = true;
      getProjectKnowledges(props.projectId)
        .then((d) => (refs.value = d.knowledges || []))
        .catch(() => (refs.value = []))
        .finally(() => (loading.value = false));
    };

    onMounted(loadRefs);

    watch(() => props.projectId, loadRefs);

    watch(
      () => props.refreshSignal,
      (sig) => {
        if (sig === undefined || sig === 0) return;
        loadRefs();
      },
    );

    const handleSearch = async () => {
      if (!searchQuery.value.trim()) return;
      searching.value = true;
      const toastId = addToast({
        type: "info",
        title: "正在搜索素材",
        duration: 0,
      });
      try {
        const result = await searchKnowledgeGlobal(searchQuery.value, 20);
        searchResults.value = result.entries || [];
        updateToast(toastId, {
          type: "success",
          title: `找到 ${(result.entries || []).length} 条素材`,
          duration: 2000,
        });
      } catch {
        updateToast(toastId, {
          type: "error",
          title: "搜索失败",
          duration: 3000,
        });
      } finally {
        searching.value = false;
      }
    };

    const handleAddChunk = async (chunk: KnowledgeSearchResult) => {
      if (refContents().has(chunk.content)) {
        addToast({ type: "warning", title: "该素材已引用", duration: 2000 });
        return;
      }
      if (refs.value.length >= MAX_CHUNK_REFS) {
        addToast({
          type: "warning",
          title: `素材引用上限为 ${MAX_CHUNK_REFS} 条`,
          duration: 3000,
        });
        return;
      }
      try {
        const added = await addProjectKnowledge(props.projectId!, chunk.content);
        titleMap.value = {
          ...titleMap.value,
          [chunk.content]: `${chunk.knowledge_name} #${chunk.chunk_id}`,
        };
        refs.value = [...refs.value, { id: added.id, content: chunk.content }];
      } catch {
        addToast({ type: "error", title: "添加失败", duration: 2000 });
      }
    };

    const handleRemoveChunk = async (refId: number, content: string) => {
      const ok = await confirm({
        title: "移除素材引用",
        message: `确定要从本项目移除「${(titleMap.value[content] || content).slice(0, 40)}${content.length > 40 ? "..." : ""}」吗？仅取消引用，不影响素材库中的原文件。`,
        danger: true,
        confirmText: "确认移除",
      });
      if (!ok) return;
      try {
        await deleteProjectKnowledge(props.projectId!, content);
        refs.value = refs.value.filter((r) => r.id !== refId);
        delete titleMap.value[content];
      } catch {
        addToast({ type: "error", title: "移除失败", duration: 2000 });
      }
    };

    return () => {
      const contents = refContents();

      return (
        <div class="knowledge-panel">
          <div class="knowledge-panel-header">
            <span class="knowledge-panel-title">
              素材库引用
              <span class="knowledge-panel-count">
                {refs.value.length}/{MAX_CHUNK_REFS}
              </span>
            </span>
            <div style={{ display: "flex", gap: "4px" }}>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => (showSearch.value = !showSearch.value)}
              >
                <PhPlus size={12} />
              </Button>
              <Button size="sm" variant="ghost" onClick={loadRefs}>
                <PhArrowClockwise size={12} />
              </Button>
            </div>
          </div>

          {showSearch.value && (
            <div class="kb-search-area">
              <div class="kb-search-bar">
                <PhMagnifyingGlass size={14} weight="light" />
                <input
                  class="kb-search-input"
                  type="text"
                  placeholder="搜索素材内容..."
                  value={searchQuery.value}
                  onInput={(e) => (searchQuery.value = (e.target as HTMLInputElement).value)}
                  onKeydown={(e) => e.key === "Enter" && handleSearch()}
                />
                <Button size="sm" onClick={handleSearch} disabled={searching.value}>
                  搜索
                </Button>
                <button class="icon-btn" onClick={() => (showSearch.value = false)}>
                  <PhX size={14} />
                </button>
              </div>
              {searchResults.value.length > 0 && (
                <div class="kb-search-results">
                  {searchResults.value.map((r) => {
                    const added = contents.has(r.content);
                    return (
                      <div key={r.id} class="kb-search-result-item">
                        <div class="kb-search-result-header">
                          <span class="kb-search-result-title">
                            {r.knowledge_name} #{r.chunk_id}
                          </span>
                          <span class="kb-search-result-score">
                            {(r.score * 100).toFixed(0)}%
                          </span>
                        </div>
                        <div class="kb-search-result-content">
                          {r.content.slice(0, 120)}
                          {r.content.length > 120 ? "..." : ""}
                        </div>
                        <Button
                          size="sm"
                          variant={added ? "ghost" : "primary"}
                          disabled={added}
                          onClick={() => handleAddChunk(r)}
                        >
                          {added ? "已引用" : "引用"}
                        </Button>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {loading.value ? (
            <div class="panel-empty">加载中...</div>
          ) : refs.value.length === 0 ? (
            <div class="panel-empty">
              <PhGlobe
                size={20}
                weight="light"
                style={{ opacity: 0.3, marginBottom: "4px" }}
              />
              暂无引用素材
              <div
                style={{
                  fontSize: "11px",
                  color: "var(--color-text-muted)",
                  marginTop: "4px",
                }}
              >
                点击 + 搜索并添加素材引用
              </div>
            </div>
          ) : (
            <div class="kb-ref-list">
              {refs.value.map((r) => (
                <div key={r.id} class="kb-ref-item">
                  <div class="kb-ref-header">
                    <span class="kb-ref-title">{refTitle(r)}</span>
                    <button
                      class="icon-btn"
                      style={{ color: "var(--color-error)" }}
                      onClick={() => handleRemoveChunk(r.id, r.content)}
                    >
                      <PhTrash size={10} />
                    </button>
                  </div>
                  <div class="kb-ref-content">
                    {r.content.slice(0, 100)}
                    {r.content.length > 100 ? "..." : ""}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      );
    };
  },
});
