import { defineComponent, ref, reactive, computed, onMounted } from "vue";
import {
  createMaterial,
  deleteMaterial,
  deleteMaterialKnowledge,
  searchMaterial,
  importMaterialFiles,
  getImportProgress,
  getUserPreference,
  updateUserPreference,
  type MaterialInfo,
  type MaterialKnowledge,
  type KnowledgeSearchResult,
} from "../api";
import { useKnowledgeStore } from "../stores/knowledge";
import { Button, Tag, Modal, PageLoader } from "../components";
import VirtualList from "../components/VirtualList";
import { useToast } from "../components/Toast";
import {
  PhBookBookmark,
  PhPlus,
  PhTrash,
  PhMagnifyingGlass,
  PhUploadSimple,
  PhGearSix,
  PhFileText,
  PhCaretRight,
  PhCaretDown,
  PhBook,
  PhFolder,
  PhSortAscending,
  PhClockCounterClockwise,
} from "@phosphor-icons/vue";

export default defineComponent({
  name: "KnowledgeBasePage",
  setup() {
    const kbStore = useKnowledgeStore();
    const materials = computed(() => kbStore.materials);
    const selectedMaterial = computed(() => kbStore.selectedMaterial);
    const knowledges = computed(() => kbStore.knowledges);
    const loading = computed(() => kbStore.loading);
    const knowledgeChunks = computed(() => kbStore.chunks);
    const kbSearch = computed({
      get: () => kbStore.search,
      set: (v: string) => (kbStore.search = v),
    });
    const kbSort = computed({
      get: () => kbStore.sort,
      set: (v: "updated" | "created" | "name") => (kbStore.sort = v),
    });
    const loadMaterials = kbStore.loadMaterials;

    const pageLoading = ref(true);

    const searchQuery = ref("");
    const searchResults = ref<KnowledgeSearchResult[] | null>(null);

    const showCreate = ref(false);
    const newKBName = ref("");
    const newKBDescription = ref("");

    const fileInputEl = ref<HTMLInputElement | null>(null);
    const importing = ref(false);
    const pendingFiles = ref<File[]>([]);
    const importTitles = ref<string[]>([]);

    const expandedKnowledges = ref<Set<string>>(new Set());

    const showSettings = ref(false);
    const knowledgeConfig = reactive({
      chunk_model: true,
      chunk_size: 400,
      overlap_size: 200,
    });

    const confirmDelete = ref<{
      type: "material" | "knowledge";
      materialId: number;
      knowledgeName?: string;
      name: string;
    } | null>(null);
    const { addToast, updateToast } = useToast();

    onMounted(() => {
      Promise.all([
        loadMaterials(),
        getUserPreference()
          .then((pref) => {
            knowledgeConfig.chunk_model = pref.chunk_model;
            knowledgeConfig.chunk_size = pref.chunk_size;
            knowledgeConfig.overlap_size = pref.overlap_size;
          })
          .catch(() => {}),
      ]).finally(() => (pageLoading.value = false));
    });

    const handleSearch = async () => {
      if (!selectedMaterial.value || !searchQuery.value.trim()) return;
      const toastId = addToast({
        type: "info",
        title: "正在搜索",
        message: `搜索「${searchQuery.value.slice(0, 20)}${searchQuery.value.length > 20 ? "..." : ""}」`,
        duration: 0,
      });
      try {
        const result = await searchMaterial(selectedMaterial.value.id, searchQuery.value);
        searchResults.value = result.entries || [];
        updateToast(toastId, {
          type: "success",
          title: "搜索完成",
          message: `找到 ${(result.entries || []).length} 条结果`,
          duration: 3000,
        });
      } catch {
        searchResults.value = [];
        updateToast(toastId, {
          type: "error",
          title: "搜索失败",
          message: "请稍后重试",
          duration: 3000,
        });
      }
    };

    const handleCreate = async () => {
      if (!newKBName.value.trim()) return;
      await createMaterial(newKBName.value, newKBDescription.value);
      showCreate.value = false;
      newKBName.value = "";
      newKBDescription.value = "";
      loadMaterials();
    };

    const handleDeleteMaterial = async (id: number) => {
      try {
        await deleteMaterial(id);
        kbStore.removeMaterialLocal(id);
        addToast({
          type: "success",
          title: "已删除",
          message: "素材库已删除",
          duration: 3000,
        });
      } catch {
        addToast({
          type: "error",
          title: "删除失败",
          message: "请稍后重试",
          duration: 3000,
        });
      }
    };

    const handleDeleteKnowledge = async (materialId: number, knowledgeName: string) => {
      try {
        await deleteMaterialKnowledge(materialId, knowledgeName);
        const knowledgeId = `${materialId}_${knowledgeName}`;
        const nextExpanded = new Set(expandedKnowledges.value);
        nextExpanded.delete(knowledgeId);
        expandedKnowledges.value = nextExpanded;
        kbStore.dropChunks(knowledgeId);
        kbStore.reloadKnowledges(materialId);
        addToast({
          type: "success",
          title: "已删除",
          message: "素材已删除",
          duration: 3000,
        });
      } catch {
        addToast({
          type: "error",
          title: "删除失败",
          message: "请稍后重试",
          duration: 3000,
        });
      }
    };

    const handleImport = async () => {
      if (!selectedMaterial.value || pendingFiles.value.length === 0) return;
      const material = selectedMaterial.value;
      const fileArr = pendingFiles.value;
      const titles = importTitles.value;
      const toastId = addToast({
        type: "info",
        title: "正在导入",
        message: `共 ${fileArr.length} 个文件，准备中...`,
        progress: 0,
        duration: 0,
      });
      pendingFiles.value = [];
      importTitles.value = [];
      importing.value = true;
      try {
        const res = await importMaterialFiles(material.id, fileArr, titles);
        const taskId = res.data.TaskId;
        const poll = setInterval(async () => {
          try {
            const p = await getImportProgress(taskId);
            updateToast(toastId, {
              progress: p.progress,
              message: p.current_file
                ? `${p.processed_files}/${p.total_files} — ${p.current_file}`
                : `${p.processed_files}/${p.total_files}`,
            });
            if (p.status === "completed") {
              clearInterval(poll);
              importing.value = false;
              updateToast(toastId, {
                type: "success",
                title: "导入完成",
                message: `成功入库 ${p.imported} 个切片`,
                progress: 100,
                duration: 3000,
              });
              await kbStore.reloadKnowledges(material.id);
              loadMaterials();
            }
            if (p.error) {
              clearInterval(poll);
              importing.value = false;
              updateToast(toastId, {
                type: "warning",
                title: "部分导入失败",
                message: p.error,
                progress: undefined,
                duration: 5000,
              });
            }
          } catch {
            clearInterval(poll);
            importing.value = false;
            updateToast(toastId, {
              type: "error",
              title: "获取进度失败",
              message: "轮询中断，请刷新页面查看结果",
              progress: undefined,
              duration: 5000,
            });
          }
        }, 1000);
      } catch {
        importing.value = false;
        updateToast(toastId, {
          type: "error",
          title: "导入失败",
          message: "请稍后重试",
          progress: undefined,
          duration: 3000,
        });
      }
    };

    const handleSaveConfig = async () => {
      await updateUserPreference({ ...knowledgeConfig });
      showSettings.value = false;
    };

    const toggleKnowledgeExpand = async (knowledge: MaterialKnowledge) => {
      const next = new Set(expandedKnowledges.value);
      if (next.has(knowledge.id)) next.delete(knowledge.id);
      else next.add(knowledge.id);
      expandedKnowledges.value = next;
      if (selectedMaterial.value) {
        await kbStore.loadChunks(
          selectedMaterial.value.id,
          knowledge.knowledge_name,
        );
      }
    };

    const toggleSearchGroup = (key: string) => {
      const next = new Set(expandedKnowledges.value);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      expandedKnowledges.value = next;
    };

    const formatDate = (ts: number) => {
      const d = new Date(ts * 1000);
      return d.toLocaleDateString("zh-CN", { month: "short", day: "numeric" });
    };

    const searchGroups = computed(() => {
      if (!searchResults.value) return null;
      const groups: Record<string, KnowledgeSearchResult[]> = {};
      for (const r of searchResults.value) {
        const title = r.knowledge_name || "未知素材";
        if (!groups[title]) groups[title] = [];
        groups[title].push(r);
      }
      return groups;
    });

    return () => (
      <PageLoader loading={pageLoading.value} text="加载素材库...">
        <div
          class="page-container"
          style={{ display: "flex", flexDirection: "column", height: "100%" }}
        >
          <div class="page-header">
            <h1 class="page-title">素材库</h1>
            <div style={{ display: "flex", gap: "8px" }}>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => (showSettings.value = true)}
              >
                <PhGearSix size={14} /> 设置
              </Button>
              <Button
                size="sm"
                variant="primary"
                onClick={() => (showCreate.value = true)}
              >
                <PhPlus size={14} /> 新建素材库
              </Button>
            </div>
          </div>

          <div class="kb-layout">
            <div class="kb-list">
              <div
                style={{
                  padding: "8px 8px 4px",
                  display: "flex",
                  gap: "4px",
                  alignItems: "center",
                  borderBottom: "1px solid var(--color-border-light)",
                }}
              >
                <PhMagnifyingGlass
                  size={12}
                  style={{
                    color: "var(--color-text-muted)",
                    flexShrink: 0,
                  }}
                />
                <input
                  class="input-field"
                  style={{
                    flex: 1,
                    fontSize: "11px",
                    padding: "4px 8px",
                    border: "none",
                    background: "transparent",
                  }}
                  placeholder="搜索素材库..."
                  value={kbSearch.value}
                  onInput={(e) => (kbSearch.value = (e.target as HTMLInputElement).value)}
                />
                <button
                  class="icon-btn"
                  style={{ padding: "2px" }}
                  title={
                    kbSort.value === "updated"
                      ? "按更新时间"
                      : kbSort.value === "created"
                        ? "按创建时间"
                        : "按名称"
                  }
                  onClick={() => {
                    const next =
                      kbSort.value === "updated"
                        ? "created"
                        : kbSort.value === "created"
                          ? "name"
                          : "updated";
                    kbSort.value = next;
                  }}
                >
                  {kbSort.value === "name" ? (
                    <PhSortAscending size={12} />
                  ) : (
                    <PhClockCounterClockwise size={12} />
                  )}
                </button>
              </div>

              <div style={{ flex: 1, minHeight: 0 }}>
                <VirtualList
                  data={materials.value}
                  itemKey={(m: MaterialInfo) => m.id}
                  totalCount={materials.value.length}
                  emptyContent={
                    <span style={{ fontSize: "12px" }}>
                      {kbSearch.value ? "无匹配结果" : "暂无素材库"}
                    </span>
                  }
                  renderItem={(m: MaterialInfo) => (
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "8px",
                        padding: "8px 12px",
                        cursor: "pointer",
                        background:
                          selectedMaterial.value?.id === m.id
                            ? "var(--color-accent-light, rgba(59,130,246,0.08))"
                            : "transparent",
                        borderLeft:
                          selectedMaterial.value?.id === m.id
                            ? "2px solid var(--color-accent)"
                            : "2px solid transparent",
                        transition:
                          "background var(--duration-fast), border-color var(--duration-fast)",
                      }}
                      onClick={() => {
                        if (selectedMaterial.value?.id === m.id) return;
                        searchResults.value = null;
                        searchQuery.value = "";
                        kbStore.clearChunks();
                        expandedKnowledges.value = new Set();
                        kbStore.selectMaterial(m);
                      }}
                      onMouseenter={(e: MouseEvent) => {
                        if (selectedMaterial.value?.id !== m.id)
                          (e.currentTarget as HTMLElement).style.background =
                            "var(--color-bg-tertiary)";
                      }}
                      onMouseleave={(e: MouseEvent) => {
                        if (selectedMaterial.value?.id !== m.id)
                          (e.currentTarget as HTMLElement).style.background =
                            "transparent";
                      }}
                    >
                      <PhFolder
                        size={16}
                        weight={selectedMaterial.value?.id === m.id ? "fill" : "regular"}
                        style={{
                          color:
                            selectedMaterial.value?.id === m.id
                              ? "var(--color-accent)"
                              : "var(--color-text-muted)",
                          flexShrink: 0,
                        }}
                      />
                      <div
                        style={{
                          flex: 1,
                          minWidth: 0,
                          display: "flex",
                          flexDirection: "column",
                          gap: "1px",
                        }}
                      >
                        <div
                          style={{
                            fontSize: "12px",
                            fontWeight: 500,
                            whiteSpace: "nowrap",
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            color:
                              selectedMaterial.value?.id === m.id
                                ? "var(--color-accent)"
                                : "var(--color-text)",
                          }}
                        >
                          {m.name}
                        </div>
                        <div
                          style={{
                            fontSize: "10px",
                            color: "var(--color-text-muted)",
                            display: "flex",
                            gap: "6px",
                          }}
                        >
                          <span>{m.knowledge_count ?? 0} 篇</span>
                          <span>·</span>
                          <span>{m.chunk_count ?? 0} 段</span>
                          <span>·</span>
                          <span>{formatDate(m.updated_at)}</span>
                        </div>
                      </div>
                      <span
                        class="icon-btn"
                        style={{ padding: "2px", opacity: 0.4 }}
                        onClick={(e: MouseEvent) => {
                          e.stopPropagation();
                          confirmDelete.value = {
                            type: "material",
                            materialId: m.id,
                            name: m.name,
                          };
                        }}
                      >
                        <PhTrash size={10} />
                      </span>
                    </div>
                  )}
                />
              </div>
            </div>

            <div class="kb-detail">
              {!selectedMaterial.value ? (
                <div
                  class="panel-empty"
                  style={{
                    flex: 1,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  <PhBookBookmark
                    size={32}
                    weight="light"
                    style={{ opacity: 0.2, marginBottom: "8px" }}
                  />
                  选择一个素材库查看内容
                </div>
              ) : (
                <>
                  <div
                    style={{
                      padding: "10px 16px",
                      borderBottom: "1px solid var(--color-border-light)",
                      display: "flex",
                      alignItems: "center",
                      gap: "8px",
                    }}
                  >
                    <PhFolder
                      size={16}
                      weight="fill"
                      style={{ color: "var(--color-accent)" }}
                    />
                    <span style={{ fontSize: "13px", fontWeight: 600 }}>
                      {selectedMaterial.value.name}
                    </span>
                    {selectedMaterial.value.description && (
                      <span
                        style={{
                          fontSize: "11px",
                          color: "var(--color-text-muted)",
                          marginLeft: "4px",
                        }}
                      >
                        {selectedMaterial.value.description}
                      </span>
                    )}
                    <div style={{ marginLeft: "auto", display: "flex", gap: "6px" }}>
                      <Button
                        size="sm"
                        variant="primary"
                        onClick={() => fileInputEl.value?.click()}
                        disabled={importing.value}
                      >
                        <PhUploadSimple size={12} />{" "}
                        {importing.value ? "导入中..." : "导入小说"}
                      </Button>
                    </div>
                  </div>

                  <div
                    style={{
                      display: "flex",
                      gap: "8px",
                      padding: "8px 16px",
                      alignItems: "center",
                      borderBottom: "1px solid var(--color-border-light)",
                    }}
                  >
                    <input
                      class="input-field"
                      style={{ flex: 1, fontSize: "12px" }}
                      placeholder="搜索小说内容..."
                      value={searchQuery.value}
                      onInput={(e) =>
                        (searchQuery.value = (e.target as HTMLInputElement).value)
                      }
                      onKeydown={(e: KeyboardEvent) =>
                        e.key === "Enter" && handleSearch()
                      }
                    />
                    <Button size="sm" variant="ghost" onClick={handleSearch}>
                      <PhMagnifyingGlass size={12} />
                    </Button>
                    {searchResults.value !== null && (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          searchResults.value = null;
                          searchQuery.value = "";
                        }}
                      >
                        清除
                      </Button>
                    )}
                    <input
                      ref={fileInputEl}
                      type="file"
                      multiple
                      accept=".txt,.md"
                      style={{ display: "none" }}
                      onChange={(e) => {
                        const target = e.target as HTMLInputElement;
                        if (target.files && target.files.length > 0) {
                          const files = Array.from(target.files);
                          pendingFiles.value = files;
                          importTitles.value = files.map((f) =>
                            f.name.replace(/\.[^.]+$/, ""),
                          );
                        }
                        target.value = "";
                      }}
                    />
                  </div>

                  <div
                    style={{
                      flex: 1,
                      minHeight: 0,
                      overflow: "auto",
                      padding: "8px 16px",
                    }}
                  >
                    {searchResults.value !== null ? (
                      searchResults.value.length === 0 ? (
                        <div class="panel-empty">
                          <PhMagnifyingGlass
                            size={24}
                            weight="light"
                            style={{ opacity: 0.3, marginBottom: "8px" }}
                          />
                          无搜索结果
                        </div>
                      ) : (
                        <div
                          style={{
                            display: "flex",
                            flexDirection: "column",
                            gap: "8px",
                          }}
                        >
                          {Object.entries(searchGroups.value || {}).map(
                            ([knowledgeName, results]) => {
                              const isExpanded = expandedKnowledges.value.has(
                                `search_${knowledgeName}`,
                              );
                              return (
                                <div
                                  key={knowledgeName}
                                  style={{
                                    background: "var(--color-bg-tertiary)",
                                    borderRadius: "8px",
                                    overflow: "hidden",
                                  }}
                                >
                                  <div
                                    style={{
                                      display: "flex",
                                      alignItems: "center",
                                      gap: "6px",
                                      padding: "8px 12px",
                                      cursor: "pointer",
                                      borderBottom: isExpanded
                                        ? "1px solid var(--color-border-light)"
                                        : "none",
                                    }}
                                    onClick={() =>
                                      toggleSearchGroup(`search_${knowledgeName}`)
                                    }
                                  >
                                    {isExpanded ? (
                                      <PhCaretDown size={10} />
                                    ) : (
                                      <PhCaretRight size={10} />
                                    )}
                                    <PhFileText size={13} weight="light" />
                                    <span style={{ fontSize: "12px", fontWeight: 500 }}>
                                      {knowledgeName}
                                    </span>
                                    <Tag size="sm" variant="default">
                                      {results.length} 段
                                    </Tag>
                                    <Tag size="sm" variant="info">
                                      相关度 {Math.round(results[0].score * 100)}%
                                    </Tag>
                                  </div>
                                  {isExpanded && (
                                    <div style={{ padding: "4px 12px 8px" }}>
                                      {results.map((r) => (
                                        <div
                                          key={r.id}
                                          style={{
                                            padding: "6px 8px",
                                            fontSize: "11px",
                                            lineHeight: 1.6,
                                            color: "var(--color-text-secondary)",
                                            borderBottom:
                                              "1px solid var(--color-border-lighter, rgba(128,128,128,0.1))",
                                          }}
                                        >
                                          {r.content}
                                        </div>
                                      ))}
                                    </div>
                                  )}
                                </div>
                              );
                            },
                          )}
                        </div>
                      )
                    ) : loading.value ? (
                      <div
                        style={{
                          fontSize: "12px",
                          color: "var(--color-text-muted)",
                          padding: "16px",
                        }}
                      >
                        加载中...
                      </div>
                    ) : knowledges.value.length === 0 ? (
                      <div class="panel-empty">
                        <PhBook
                          size={24}
                          weight="light"
                          style={{ opacity: 0.3, marginBottom: "8px" }}
                        />
                        暂无素材，点击「导入小说」添加参考素材
                      </div>
                    ) : (
                      <div
                        style={{
                          display: "flex",
                          flexDirection: "column",
                          gap: "8px",
                        }}
                      >
                        {knowledges.value.map((knowledge) => {
                          const isExpanded = expandedKnowledges.value.has(
                            knowledge.id,
                          );
                          const chunks = knowledgeChunks.value[knowledge.id] || [];
                          return (
                            <div
                              key={knowledge.id}
                              style={{
                                background: "var(--color-bg-tertiary)",
                                borderRadius: "8px",
                                overflow: "hidden",
                              }}
                            >
                              <div
                                style={{
                                  display: "flex",
                                  alignItems: "center",
                                  gap: "6px",
                                  padding: "8px 12px",
                                  cursor: "pointer",
                                  borderBottom: isExpanded
                                    ? "1px solid var(--color-border-light)"
                                    : "none",
                                }}
                                onClick={() => toggleKnowledgeExpand(knowledge)}
                              >
                                {isExpanded ? (
                                  <PhCaretDown size={10} />
                                ) : (
                                  <PhCaretRight size={10} />
                                )}
                                <PhFileText size={13} weight="light" />
                                <span style={{ fontSize: "12px", fontWeight: 500 }}>
                                  {knowledge.knowledge_name}
                                </span>
                                <Tag size="sm" variant="default">
                                  {knowledge.chunk_count} 段
                                </Tag>
                                <Tag size="sm" variant="info">
                                  {knowledge.word_count.toLocaleString()} 字
                                </Tag>
                                <span
                                  class="icon-btn"
                                  style={{ marginLeft: "auto", padding: 0 }}
                                  onClick={(e: MouseEvent) => {
                                    e.stopPropagation();
                                    confirmDelete.value = {
                                      type: "knowledge",
                                      materialId: selectedMaterial.value!.id,
                                      knowledgeName: knowledge.knowledge_name,
                                      name: knowledge.knowledge_name,
                                    };
                                  }}
                                >
                                  <PhTrash size={10} />
                                </span>
                              </div>
                              {isExpanded && (
                                <div style={{ padding: "4px 12px 8px" }}>
                                  {chunks.length === 0 ? (
                                    <div
                                      style={{
                                        fontSize: "11px",
                                        color: "var(--color-text-muted)",
                                        padding: "4px 8px",
                                      }}
                                    >
                                      加载切片中...
                                    </div>
                                  ) : (
                                    chunks.map((chunk) => (
                                      <div
                                        key={chunk.id}
                                        style={{
                                          padding: "6px 8px",
                                          fontSize: "11px",
                                          lineHeight: 1.6,
                                          color: "var(--color-text-secondary)",
                                          borderBottom:
                                            "1px solid var(--color-border-lighter, rgba(128,128,128,0.1))",
                                        }}
                                      >
                                        <span
                                          style={{
                                            color: "var(--color-text-muted)",
                                            marginRight: "6px",
                                          }}
                                        >
                                          [{chunk.chunk_id}]
                                        </span>
                                        {chunk.content}
                                      </div>
                                    ))
                                  )}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                </>
              )}
            </div>
          </div>

          <Modal
            open={showCreate.value}
            onClose={() => (showCreate.value = false)}
            title="新建素材库"
          >
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: "var(--space-md)",
              }}
            >
              <input
                class="input-field"
                placeholder="素材库名称（如：玄幻参考、同人素材）"
                value={newKBName.value}
                onInput={(e) => (newKBName.value = (e.target as HTMLInputElement).value)}
              />
              <input
                class="input-field"
                placeholder="描述（可选）"
                value={newKBDescription.value}
                onInput={(e) =>
                  (newKBDescription.value = (e.target as HTMLInputElement).value)
                }
              />
              <div
                style={{
                  display: "flex",
                  gap: "8px",
                  justifyContent: "flex-end",
                }}
              >
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => (showCreate.value = false)}
                >
                  取消
                </Button>
                <Button size="sm" variant="primary" onClick={handleCreate}>
                  创建
                </Button>
              </div>
            </div>
          </Modal>

          <Modal
            open={showSettings.value}
            onClose={() => (showSettings.value = false)}
            title="素材库设置"
          >
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: "var(--space-md)",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <label
                  style={{
                    fontSize: "12px",
                    minWidth: "100px",
                    color: "var(--color-text-secondary)",
                  }}
                >
                  切片模式
                </label>
                <label
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "6px",
                    fontSize: "12px",
                    cursor: "pointer",
                  }}
                >
                  <input
                    type="checkbox"
                    checked={knowledgeConfig.chunk_model}
                    onChange={(e) =>
                      (knowledgeConfig.chunk_model = (e.target as HTMLInputElement).checked)
                    }
                    style={{ accentColor: "var(--color-accent)" }}
                  />
                  {knowledgeConfig.chunk_model ? "开启" : "关闭"}
                </label>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <label
                  style={{
                    fontSize: "12px",
                    minWidth: "100px",
                    color: "var(--color-text-secondary)",
                  }}
                >
                  切片大小
                </label>
                <input
                  type="number"
                  class="input-field"
                  style={{ width: "80px" }}
                  disabled={!knowledgeConfig.chunk_model}
                  value={knowledgeConfig.chunk_size}
                  onInput={(e) =>
                    (knowledgeConfig.chunk_size = Number((e.target as HTMLInputElement).value))
                  }
                />
                <span style={{ fontSize: "11px", color: "var(--color-text-muted)" }}>
                  字
                </span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <label
                  style={{
                    fontSize: "12px",
                    minWidth: "100px",
                    color: "var(--color-text-secondary)",
                  }}
                >
                  重合大小
                </label>
                <input
                  type="number"
                  class="input-field"
                  style={{ width: "80px" }}
                  disabled={!knowledgeConfig.chunk_model}
                  value={knowledgeConfig.overlap_size}
                  onInput={(e) =>
                    (knowledgeConfig.overlap_size = Number((e.target as HTMLInputElement).value))
                  }
                />
                <span style={{ fontSize: "11px", color: "var(--color-text-muted)" }}>
                  字
                </span>
              </div>
              <div
                style={{
                  fontSize: "11px",
                  color: "var(--color-text-muted)",
                  lineHeight: 1.5,
                }}
              >
                切片模式开启后，导入素材按切片大小切分入库，重合大小决定相邻切片的重叠字数。较大的切片提供更多上下文，较小的切片提高检索精度。
              </div>
              <div
                style={{
                  display: "flex",
                  gap: "8px",
                  justifyContent: "flex-end",
                }}
              >
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => (showSettings.value = false)}
                >
                  取消
                </Button>
                <Button size="sm" variant="primary" onClick={handleSaveConfig}>
                  保存配置
                </Button>
              </div>
            </div>
          </Modal>

          <Modal
            open={confirmDelete.value !== null}
            onClose={() => (confirmDelete.value = null)}
            title="确认删除"
          >
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: "var(--space-md)",
              }}
            >
              <div style={{ fontSize: "13px", color: "var(--color-text-secondary)" }}>
                确定要删除「{confirmDelete.value?.name}」吗？
                {confirmDelete.value?.type === "material" && (
                  <span style={{ color: "var(--color-error)", marginLeft: "4px" }}>
                    此操作将删除库内所有素材和切片，不可恢复。
                  </span>
                )}
                {confirmDelete.value?.type === "knowledge" && (
                  <span style={{ color: "var(--color-error)", marginLeft: "4px" }}>
                    将删除该素材的全部切片，不可恢复。
                  </span>
                )}
              </div>
              <div style={{ display: "flex", gap: "8px", justifyContent: "flex-end" }}>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => (confirmDelete.value = null)}
                >
                  取消
                </Button>
                <Button
                  size="sm"
                  variant="danger"
                  onClick={() => {
                    if (!confirmDelete.value) return;
                    if (confirmDelete.value.type === "material") {
                      handleDeleteMaterial(confirmDelete.value.materialId);
                    } else {
                      handleDeleteKnowledge(
                        confirmDelete.value.materialId,
                        confirmDelete.value.knowledgeName!,
                      );
                    }
                    confirmDelete.value = null;
                  }}
                >
                  确认删除
                </Button>
              </div>
            </div>
          </Modal>

          <Modal
            open={pendingFiles.value.length > 0}
            onClose={() => {
              pendingFiles.value = [];
              importTitles.value = [];
            }}
            title="导入小说"
          >
            <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
              {pendingFiles.value.map((f, idx) => (
                <div
                  key={idx}
                  style={{ display: "flex", flexDirection: "column", gap: "4px" }}
                >
                  <label style={{ fontSize: "11px", color: "var(--color-text-muted)" }}>
                    {f.name}
                  </label>
                  <input
                    class="input-field"
                    style={{ fontSize: "12px" }}
                    value={importTitles.value[idx] || ""}
                    onInput={(e) => {
                      const next = [...importTitles.value];
                      next[idx] = (e.target as HTMLInputElement).value;
                      importTitles.value = next;
                    }}
                    placeholder="输入标题（留空使用文件名）"
                  />
                </div>
              ))}
              <div
                style={{
                  display: "flex",
                  gap: "8px",
                  justifyContent: "flex-end",
                  marginTop: "4px",
                }}
              >
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    pendingFiles.value = [];
                    importTitles.value = [];
                  }}
                >
                  取消
                </Button>
                <Button size="sm" variant="primary" onClick={handleImport}>
                  开始导入
                </Button>
              </div>
            </div>
          </Modal>
        </div>
      </PageLoader>
    );
  },
});
