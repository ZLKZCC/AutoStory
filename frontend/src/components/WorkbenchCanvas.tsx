import {
  defineComponent,
  ref,
  computed,
  watch,
  onMounted,
  type PropType,
} from "vue";
import {
  getProjectConcept,
  saveProjectConcept,
  getProjectWorldline,
  saveProjectWorldline,
  getProjectVolumes,
  type VolumeInfo,
  type OutlineData,
  type WorldlineData,
  type Worldline,
} from "../api";
import { useWorkspaceStore } from "../stores/workspace";
import type { PendingChange } from "../stores/chat";
import WorldlineOverlay from "./WorldlineOverlay";
import RichTextEditor from "./RichTextEditor";
import AudioBookHub from "./AudioBookHub";
import CharactersView from "./CharactersView";
import { entityLabel } from "./DataChangeBubble";
import { Button } from ".";
import {
  PhArticle,
  PhListBullets,
  PhGitBranch,
  PhUser,
  PhHeadphones,
  PhPencilSimple,
  PhCheck,
  PhX,
  PhEye,
  PhCode,
  PhSparkle,
} from "@phosphor-icons/vue";
import gsap from "gsap";

type ViewKey = "text" | "outline" | "worldlines" | "characters" | "audiobook";

interface WlNode {
  id: string;
  title: string;
  description: string;
  color: string;
  textColor: string;
  fontSize: number;
  fontWeight: string;
  fontStyle: string;
  x: number;
  y: number;
}

interface EdgeRelation {
  id: string;
  from: string;
  to: string;
  label: string;
  arrowType:
    | "undirected"
    | "bidirectional"
    | "unidirectional-left"
    | "unidirectional-right";
  sourceHandle?: string;
  targetHandle?: string;
}

export default defineComponent({
  name: "WorkbenchCanvas",
  props: {
    projectName: { type: String, required: true },
    refreshSignal: { type: Number, default: 0 },
    pendingChanges: {
      type: Array as PropType<PendingChange[]>,
      default: () => [],
    },
    onResolveChange: {
      type: Function as PropType<
        (messageId: string, confirmed: boolean) => void
      >,
      default: undefined,
    },
    onAskAboutSelection: {
      type: Function as PropType<(text: string) => void>,
      default: undefined,
    },
  },
  setup(props) {
    const view = ref<ViewKey>("text");
    const contentEl = ref<HTMLDivElement | null>(null);
    const ws = useWorkspaceStore();
    const projectId = computed(() => ws.projectId);
    const chapter = computed(() => ws.selectedChapter);

    const chapterTitle = ref("");
    const chapterDraft = ref("");
    const chapterDirty = ref(false);
    const chapterEditing = ref(false);
    const savingChapter = ref(false);

    const outline = ref<OutlineData>({ sections: [], global_notes: "" });
    const outlineDraft = ref("");
    const outlineEditing = ref(false);
    const outlineDirty = ref(false);
    const volumes = ref<VolumeInfo[]>([]);
    const savingOutline = ref(false);

    const worldlineData = ref<WorldlineData>({ worldlines: [], active: null });
    const wlNodeMap = ref<Record<string, WlNode[]>>({});
    const edgeRelations = ref<EdgeRelation[]>([]);
    const wlVisualOpen = ref(false);
    const wlJsonOpen = ref(false);

    watch(
      () => [chapter.value?.id, chapter.value?.content],
      (val, old) => {
        const idChanged = !old || old[0] !== val[0];
        if (!idChanged && (chapterDirty.value || chapter.value?.content === undefined)) return;
        chapterTitle.value = chapter.value?.title || "";
        chapterDraft.value = chapter.value?.content || "";
        chapterDirty.value = false;
        chapterEditing.value = false;
      },
      { immediate: true },
    );

    const loadOutline = () => {
      if (projectId.value == null) return;
      getProjectConcept(projectId.value)
        .then((res) => {
          if (res) {
            outline.value = res;
            if (res.outline_html) {
              outlineDraft.value = res.outline_html;
            } else {
              const parts: string[] = [];
              if (res.global_notes) {
                parts.push(
                  `<p>${res.global_notes.replace(/\n/g, "</p><p>")}</p>`,
                );
              }
              for (const s of res.sections) {
                parts.push(`<h2>${s.title || "未命名段落"}</h2>`);
                if (s.content) {
                  parts.push(
                    s.content.trim().startsWith("<")
                      ? s.content
                      : `<p>${s.content.replace(/\n/g, "</p><p>")}</p>`,
                  );
                }
              }
              outlineDraft.value = parts.join("");
            }
          } else {
            outline.value = { sections: [], global_notes: "" };
            outlineDraft.value = "";
          }
          outlineDirty.value = false;
        })
        .catch(() => {});
    };

    const loadVolumes = () => {
      if (projectId.value == null) return;
      getProjectVolumes(projectId.value)
        .then((res) => { volumes.value = res.data ?? []; })
        .catch(() => {});
    };

    const loadWorldlines = () => {
      if (projectId.value == null) return;
      getProjectWorldline(projectId.value)
        .then((res) => {
          if (!res || res.worldlines.length === 0) {
            res = {
              worldlines: [
                {
                  id: "wl_main",
                  name: "主线",
                  description: "",
                  parent_branch: null,
                  branch_point_chapter: null,
                  chapters: [],
                  created_at: new Date().toISOString(),
                  updated_at: new Date().toISOString(),
                  nodes: [],
                  edges: [],
                },
              ],
              active: "wl_main",
            };
          }
          worldlineData.value = res;
          const nodeMap: Record<string, WlNode[]> = {};
          const edges: EdgeRelation[] = [];
          for (const wl of res.worldlines) {
            nodeMap[wl.id] = (wl.nodes || []).map((n: any) => ({
              id: n.id,
              title: n.title || "",
              description: n.description || "",
              color: n.color || "#f59e0b",
              textColor: n.textColor || "#3d2e24",
              fontSize: n.fontSize || 14,
              fontWeight: n.fontWeight || "600",
              fontStyle: n.fontStyle || "normal",
              x: n.x ?? 0,
              y: n.y ?? 0,
            }));
            for (const e of wl.edges || []) {
              edges.push({
                id: e.id || `edge-${Math.random().toString(36).slice(2, 9)}`,
                from: e.from || "",
                to: e.to || "",
                label: e.label || "",
                arrowType: (e.arrowType as any) || "unidirectional-right",
                sourceHandle: e.sourceHandle || undefined,
                targetHandle: e.targetHandle || undefined,
              });
            }
          }
          wlNodeMap.value = nodeMap;
          edgeRelations.value = edges;
        })
        .catch(() => {});
    };

    onMounted(() => {
      loadOutline();
      loadWorldlines();
    });

    watch(
      () => props.refreshSignal,
      (sig) => {
        if (!sig) return;
        loadOutline();
        loadWorldlines();
        loadVolumes();
      },
    );

    watch(
      () => ws.projectId,
      (pid) => {
        if (pid == null) return;
        loadOutline();
        loadWorldlines();
        loadVolumes();
      },
    );

    const switchView = (key: ViewKey) => {
      if (key === view.value) return;
      if (key === "text" && ws.selectedChapterId != null) ws.selectChapter(ws.selectedChapterId);
      if (key === "outline") { loadOutline(); loadVolumes(); }
      if (key === "worldlines") loadWorldlines();
      if (key === "audiobook") ws.loadChapters();
      const el = contentEl.value;
      if (el) {
        gsap.to(el, {
          opacity: 0,
          y: 8,
          duration: 0.12,
          ease: "power2.in",
          onComplete: () => {
            view.value = key;
            gsap.fromTo(
              el,
              { opacity: 0, y: -8 },
              { opacity: 1, y: 0, duration: 0.28, ease: "power3.out" },
            );
          },
        });
      } else {
        view.value = key;
      }
    };

    const persistChapter = async () => {
      const target = chapter.value;
      if (!target) return;
      savingChapter.value = true;
      try {
        await ws.saveChapter(target.id, {
          title: chapterTitle.value,
          content: chapterDraft.value,
        });
        chapterDirty.value = false;
        chapterEditing.value = false;
      } catch {
      } finally {
        savingChapter.value = false;
      }
    };

    const handleSaveChapter = () => persistChapter();

    const cancelEditChapter = () => {
      chapterTitle.value = chapter.value?.title || "";
      chapterDraft.value = chapter.value?.content || "";
      chapterDirty.value = false;
      chapterEditing.value = false;
    };

    const renderPending = (entity: string) => {
      const items = props.pendingChanges.filter(
        (p) => p.dataChange.entity === entity,
      );
      if (items.length === 0) return null;
      return (
        <div class="canvas-pending">
          {items.map((i) => (
            <div class="canvas-pending-item" key={i.messageId}>
              <PhSparkle size={12} weight="fill" />
              <span class="canvas-pending-summary">
                {i.dataChange.summary || `${i.dataChange.action} · ${entityLabel(entity)}`}
              </span>
              <button
                class="canvas-pending-btn accept"
                onClick={() => props.onResolveChange?.(i.messageId, true)}
              >
                <PhCheck size={11} /> 确认
              </button>
              <button
                class="canvas-pending-btn reject"
                onClick={() => props.onResolveChange?.(i.messageId, false)}
              >
                <PhX size={11} /> 放弃
              </button>
            </div>
          ))}
        </div>
      );
    };

    const handleSaveOutline = async () => {
      if (projectId.value == null) return;
      savingOutline.value = true;
      try {
        await saveProjectConcept(projectId.value, {
          global_notes: outline.value.global_notes,
          sections: outline.value.sections,
          outline_html: outlineDraft.value,
        });
        outlineDirty.value = false;
        outlineEditing.value = false;
      } catch {
      } finally {
        savingOutline.value = false;
      }
    };

    const currentWl = computed<Worldline | null>(() =>
      worldlineData.value.worldlines.length > 0
        ? worldlineData.value.worldlines.find(
            (w) => w.id === worldlineData.value.active,
          ) || worldlineData.value.worldlines[0]
        : null,
    );
    const wlNodes = computed(() =>
      currentWl.value ? wlNodeMap.value[currentWl.value.id] || [] : [],
    );

    const persistWorldlines = async () => {
      if (projectId.value == null) return;
      const data: WorldlineData = {
        worldlines: worldlineData.value.worldlines.map((wl) => {
          const nodes = wlNodeMap.value[wl.id] || [];
          const nodeIds = new Set(nodes.map((n) => n.id));
          return {
            ...wl,
            nodes,
            edges: edgeRelations.value.filter(
              (e) => nodeIds.has(e.from) && nodeIds.has(e.to),
            ),
            updated_at: new Date().toISOString(),
          };
        }),
        active: worldlineData.value.active,
      };
      await saveProjectWorldline(projectId.value, data);
    };

    const renameWorldline = async (wlId: string, name: string) => {
      const wl = worldlineData.value.worldlines.find((w) => w.id === wlId);
      if (!wl) return;
      wl.name = name;
      await persistWorldlines();
    };

    const views: { key: ViewKey; label: string; icon: any }[] = [
      { key: "text", label: "正文", icon: PhArticle },
      { key: "outline", label: "大纲", icon: PhListBullets },
      { key: "worldlines", label: "世界线", icon: PhGitBranch },
      { key: "characters", label: "角色", icon: PhUser },
      { key: "audiobook", label: "有声书", icon: PhHeadphones },
    ];

    return () => (
      <div class="workbench-canvas">
        <div class="canvas-toolbar">
          <div class="canvas-seg">
            {views.map((v) => {
              const Icon = v.icon;
              return (
                <button
                  key={v.key}
                  class={`canvas-seg-btn ${view.value === v.key ? "active" : ""}`}
                  onClick={() => switchView(v.key)}
                  title={v.label}
                >
                  <Icon size={14} weight="light" />
                  <span>{v.label}</span>
                </button>
              );
            })}
          </div>
        </div>

        <div class="canvas-body" ref={contentEl}>
          {view.value === "text" &&
            (chapter.value ? (
              <div class="canvas-text">
                {renderPending("chapters")}
                <div class="canvas-text-head">
                  {chapterEditing.value ? (
                    <input
                      class="canvas-title-input"
                      value={chapterTitle.value}
                      onInput={(e) => {
                        chapterTitle.value = (
                          e.target as HTMLInputElement
                        ).value;
                        chapterDirty.value = true;
                      }}
                      placeholder="章节标题"
                    />
                  ) : (
                    <h3 class="canvas-title-view">
                      {chapterTitle.value || "未命名章节"}
                    </h3>
                  )}
                  <div class="canvas-text-actions">
                    {chapterEditing.value ? (
                      <>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={cancelEditChapter}
                        >
                          <PhX size={12} /> <span class="btn-label">取消</span>
                        </Button>
                        <Button
                          size="sm"
                          onClick={handleSaveChapter}
                          disabled={!chapterDirty.value}
                          loading={savingChapter.value}
                        >
                          {!savingChapter.value && <PhCheck size={12} />}
                          <span class="btn-label">保存</span>
                        </Button>
                      </>
                    ) : (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => (chapterEditing.value = true)}
                      >
                        <PhPencilSimple size={12} /> 编辑
                      </Button>
                    )}
                  </div>
                </div>
                <div class="canvas-prose">
                  <RichTextEditor
                    content={chapterDraft.value}
                    onChange={(v: string) => {
                      chapterDraft.value = v;
                      chapterDirty.value = true;
                    }}
                    placeholder="开始写作……"
                    readOnly={!chapterEditing.value}
                    className="canvas-rte"
                    minRows={16}
                    onAskAboutSelection={props.onAskAboutSelection}
                  />
                </div>
              </div>
            ) : (
              <div class="canvas-empty-wrap">
                {renderPending("chapters")}
                <div class="canvas-empty">
                  <PhArticle size={28} weight="light" />
                  <p>在左侧选择一个章节开始创作</p>
                </div>
              </div>
            ))}

          {view.value === "outline" && (
            <div class="canvas-outline">
              {renderPending("outline")}
              <div class="canvas-outline-head">
                <span class="canvas-section-label">大纲</span>
                <div class="canvas-outline-actions">
                  {outlineEditing.value ? (
                    <>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          outlineEditing.value = false;
                          loadOutline();
                        }}
                      >
                        <PhX size={12} /> <span class="btn-label">取消</span>
                      </Button>
                      <Button
                        size="sm"
                        onClick={handleSaveOutline}
                        disabled={!outlineDirty.value}
                        loading={savingOutline.value}
                      >
                        {!savingOutline.value && <PhCheck size={12} />}
                        <span class="btn-label">保存</span>
                      </Button>
                    </>
                  ) : (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => (outlineEditing.value = true)}
                    >
                      <PhPencilSimple size={12} /> 编辑
                    </Button>
                  )}
                </div>
              </div>
              {volumes.value.length > 0 && (
                <div class="canvas-volumes">
                  <div class="cv-head">
                    <span class="cv-head-label">卷</span>
                    <span class="cv-head-count">{volumes.value.length} 卷</span>
                  </div>
                  <div class="cv-spine">
                    {volumes.value.map((v: { volume_index: number; name: string; chapter_start: number; chapter_end: number; summary: string }, i: number) => (
                      <article
                        class="cv-card"
                        style={{ animationDelay: `${i * 45}ms` }}
                        title={v.summary || `${v.name || `第${v.volume_index + 1}卷`} · 第${v.chapter_start + 1}–${v.chapter_end + 1}章`}
                      >
                        <span class="cv-seal">{String(v.volume_index + 1).padStart(2, "0")}</span>
                        <div class="cv-body">
                          <h4 class="cv-name">{v.name || `第${v.volume_index + 1}卷`}</h4>
                          <span class="cv-range">第 {v.chapter_start + 1}–{v.chapter_end + 1} 章</span>
                        </div>
                      </article>
                    ))}
                  </div>
                </div>
              )}
              <div class="canvas-outline-paper">
                <RichTextEditor
                  content={outlineDraft.value}
                  onChange={(v: string) => {
                    outlineDraft.value = v;
                    outlineDirty.value = true;
                  }}
                  placeholder="暂无大纲内容，点击编辑开始编写"
                  readOnly={!outlineEditing.value}
                  className="canvas-outline-rte"
                  minRows={12}
                  onAskAboutSelection={props.onAskAboutSelection}
                />
              </div>
            </div>
          )}

          {view.value === "worldlines" && (
            <div class="canvas-worldlines">
              {renderPending("worldlines")}
              <button
                class="canvas-wl-btn"
                onClick={() => (wlVisualOpen.value = true)}
              >
                <div class="canvas-wl-icon">
                  <PhEye size={20} weight="light" />
                </div>
                <span class="canvas-wl-label">可视化</span>
                <span class="canvas-wl-desc">图结构查看世界线发展</span>
              </button>
              <button
                class="canvas-wl-btn"
                onClick={() => (wlJsonOpen.value = true)}
              >
                <div class="canvas-wl-icon">
                  <PhCode size={20} weight="light" />
                </div>
                <span class="canvas-wl-label">JSON</span>
                <span class="canvas-wl-desc">查看和导出世界线数据</span>
              </button>
            </div>
          )}

          {view.value === "characters" && (
            <CharactersView
              projectName={props.projectName}
              chapters={ws.chapters}
              refreshSignal={props.refreshSignal}
              pendingChanges={props.pendingChanges}
              onResolveChange={props.onResolveChange}
            />
          )}

          {/* ══════ 有声书（唯一入口 Hub：新建向导 / 我的草稿 两档）
              项目 id / 章节列表均从 workspace store 直取 ══════ */}
          {view.value === "audiobook" && (
            <AudioBookHub refreshSignal={props.refreshSignal} />
          )}
        </div>

        <WorldlineOverlay
          projectName={props.projectName}
          wlVisualOpen={wlVisualOpen.value}
          wlJsonOpen={wlJsonOpen.value}
          onCloseVisual={() => (wlVisualOpen.value = false)}
          onCloseJson={() => (wlJsonOpen.value = false)}
          currentWl={currentWl.value}
          wlNodes={wlNodes.value}
          edgeRelations={edgeRelations.value}
          wlNodeMap={wlNodeMap.value}
          setWlNodeMap={(v: Record<string, WlNode[]>) => (wlNodeMap.value = v)}
          setEdgeRelations={(v: EdgeRelation[]) => (edgeRelations.value = v)}
          loadWorldlines={loadWorldlines}
          onPersistWorldlines={persistWorldlines}
          onRenameWorldline={renameWorldline}
        />
      </div>
    );
  },
});
