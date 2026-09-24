import { defineComponent, ref, computed, watch, onMounted } from "vue";
import { useRoute, useRouter } from "vue-router";
import { parseFilesToPrefix } from "../api/parseFile";
import { useWorkspaceStore } from "../stores/workspace";
import { useProviderStore } from "../stores/providers";
import { useChatStore, type PendingChange } from "../stores/chat";
import PageLoader from "../components/PageLoader";
import VolumeTree from "../components/VolumeTree";
import WorkbenchCanvas from "../components/WorkbenchCanvas";
import Inspector from "../components/Inspector";
import ThinkingRibbon from "../components/ThinkingRibbon";
import PanelResizer from "../components/PanelResizer";
import Modal from "../components/Modal";
import { Button } from "../components";
import { useConfirm } from "../components/ConfirmDialog";
import { useToast } from "../stores/toast";
import { PhBookOpen, PhPlus } from "@phosphor-icons/vue";

const WB_RIGHT_MIN = 240;
const WB_RIGHT_MAX = 560;
const WB_RIGHT_DEFAULT = 340;
const WB_RIGHT_KEY = "autostory.wb-right-width";

export default defineComponent({
  name: "ProjectPage",
  setup() {
    const route = useRoute();
    const nav = useRouter();
    const routeKey = computed(() => (route.params.id as string) || "");
    const ws = useWorkspaceStore();
    const providerStore = useProviderStore();
    const { confirm } = useConfirm();
    const toast = useToast();

    const chat = useChatStore();

    const refreshSignal = ref(0);

    watch(() => chat.dataVersion, () => {
      ws.refreshStructure().catch(() => {});
      refreshSignal.value++;
    });

    const clampRightWidth = (w: number) =>
      Math.round(Math.min(WB_RIGHT_MAX, Math.max(WB_RIGHT_MIN, w)));

    const rightWidth = ref(WB_RIGHT_DEFAULT);
    try {
      const saved = Number(localStorage.getItem(WB_RIGHT_KEY));
      if (Number.isFinite(saved) && saved > 0) {
        rightWidth.value = clampRightWidth(saved);
      }
    } catch {
    }

    let dragStartWidth = WB_RIGHT_DEFAULT;
    const handleDragStart = () => {
      dragStartWidth = rightWidth.value;
    };
    const handleDragMove = (delta: number) => {
      rightWidth.value = clampRightWidth(dragStartWidth + delta);
    };
    const handleDragEnd = () => {
      try {
        localStorage.setItem(WB_RIGHT_KEY, String(rightWidth.value));
      } catch {
      }
    };
    const handleResetWidth = () => {
      rightWidth.value = clampRightWidth(WB_RIGHT_DEFAULT);
      try {
        localStorage.removeItem(WB_RIGHT_KEY);
      } catch {
      }
    };

    const pendingSelection = ref("");
    const handleAskAboutSelection = (text: string) => {
      if (!text.trim()) return;
      pendingSelection.value = text;
    };
    const clearSelection = () => {
      pendingSelection.value = "";
    };

    const handleDeleteChapter = async (id: number) => {
      const ch = ws.chapters.find((c) => c.id === id);
      const ok = await confirm({
        title: "删除章节",
        message: `确定要删除「${ch?.title || "该章节"}」吗？章节正文，连同这一章的配音方案和已合成的音频，都会一并删除、不可恢复。`,
        danger: true,
        confirmText: "确认删除",
      });
      if (!ok) return;
      ws.removeChapter(id).catch(() => {});
    };

    const volumeModalOpen = ref(false);
    const volumeNameDraft = ref("");
    const creatingVolume = ref(false);

    const openVolumeModal = () => {
      volumeNameDraft.value = "";
      volumeModalOpen.value = true;
    };

    const handleCreateVolume = async () => {
      const name = volumeNameDraft.value.trim();
      if (!name || creatingVolume.value) return;
      creatingVolume.value = true;
      try {
        const vol = await ws.createVolume(name);
        volumeModalOpen.value = false;
        if (vol) {
          toast.addToast({ type: "success", title: "新卷已创建", message: `「${vol.name}」` });
        }
      } catch (e) {
        toast.addToast({
          type: "error",
          title: "创建卷失败",
          message: e instanceof Error ? e.message : String(e),
        });
      } finally {
        creatingVolume.value = false;
      }
    };

    const pendingChanges = computed<PendingChange[]>(() =>
      chat.messages
        .filter(
          (m) =>
            m.role === "data_change" &&
            m.dataChange &&
            m.dataChange.status === "pending",
        )
        .map((m) => ({
          messageId: m.id,
          dataChange: m.dataChange!,
        })),
    );

    const resolveChange = (messageId: string, confirmed: boolean) => {
      chat.resolveChange(messageId, confirmed).catch((e) => {
        toast.addToast({
          type: "error",
          title: "提交裁决失败",
          message: e instanceof Error ? e.message : String(e),
        });
      });
    };

    const pageReady = ref(false);
    const historyLoaded = ref(false);

    let loadSeq = 0;

    const projectDisplayName = computed(() => ws.project?.name || "");

    const loadPage = async () => {
      if (!routeKey.value) return;
      const seq = ++loadSeq;
      pageReady.value = false;
      historyLoaded.value = false;
      chat.bindProject(null);
      await ws.loadWorkspace(routeKey.value);
      if (seq !== loadSeq) return;   // 已被更新的导航取代，丢弃本次结果
      if (ws.projectId == null) {
        pageReady.value = true;
        return;
      }
      if (routeKey.value !== String(ws.projectId)) {
        nav.replace(`/project/${ws.projectId}`);
      }
      chat.bindProject(ws.projectId);
      Promise.all([
        providerStore.ensureLoaded(),
        chat.ensureHistoryLoaded(ws.projectId)
          .finally(() => {
            if (seq === loadSeq) historyLoaded.value = true;
          }),
      ]).finally(() => {
        if (seq === loadSeq) pageReady.value = true;
      });
    };

    onMounted(loadPage);
    watch(routeKey, loadPage);

    const loading = computed(() => !pageReady.value || !historyLoaded.value);

    const llmAvailable = computed(() => providerStore.llmAvailable);

    const handleAssistantSend = async (text: string, files: File[]) => {
      if (!providerStore.llmAvailable) return;

      const userMsg = text.trim();
      if (!userMsg && files.length === 0) return;

      let prefix = "";
      if (files.length > 0) {
        const { prefix: p } = await parseFilesToPrefix(files);
        prefix = p;
      }

      const displayContent = `${prefix}${userMsg}`;

      await chat.send(displayContent);
    };

    return () => (
      <PageLoader loading={loading.value} text="加载作品空间...">
        <div class="workbench">
          <ThinkingRibbon messages={chat.messages} />

          {/* ── 三栏主体（项目名融入左栏顶部，不再单独占一条顶栏） ──
              右栏宽度经局部 CSS 变量下发，不污染 :root，也不与折叠态规则打架 */}
          <div
            class="workbench-body"
            style={{ "--wb-right": `${rightWidth.value}px` } as any}
          >
            <div class="workbench-left">
              <div class="workspace-title">
                <PhBookOpen size={17} weight="light" class="workspace-title-icon" />
                <h2>{projectDisplayName.value}</h2>
                <button
                  class="workspace-add-volume"
                  title="新建卷"
                  onClick={openVolumeModal}
                >
                  <PhPlus size={14} weight="light" />
                </button>
              </div>
              {!llmAvailable.value && !loading.value && (
                <div class="workspace-model-row">
                  <button
                    class="workbench-model-hint"
                    onClick={() => nav.push("/settings")}
                  >
                    未配置模型
                  </button>
                </div>
              )}
              <div class="workspace-tree">
                <VolumeTree
                  projectName={projectDisplayName.value}
                  volumes={ws.volumes}
                  selectedId={ws.selectedChapterId}
                  onSelectChapter={(id) => ws.selectChapter(id)}
                  onToggleExpand={(volumeId) => ws.expandVolume(volumeId)}
                  onCreateChapterInVolume={(volumeId, chapterId, position) => {
                    if (chapterId != null && position) {
                      ws.insertChapter(chapterId, position).catch(() => {});
                    } else {
                      ws.createChapterInVolume(volumeId).catch(() => {});
                    }
                  }}
                  onDeleteChapter={handleDeleteChapter}
                  onMoveChapter={(dragId, targetId, position, targetVolumeId) =>
                    ws.moveChapter(dragId, targetId, position, targetVolumeId)
                  }
                  onLoadMore={(volumeId) => ws.loadMoreChapters(volumeId)}
                />
              </div>
            </div>

            <div class="workbench-center">
              <WorkbenchCanvas
                projectName={projectDisplayName.value}
                refreshSignal={refreshSignal.value}
                pendingChanges={pendingChanges.value}
                onResolveChange={resolveChange}
                onAskAboutSelection={handleAskAboutSelection}
              />
            </div>

            <div class="workbench-right">
              <PanelResizer
                side="left"
                onDragstart={handleDragStart}
                onDragmove={handleDragMove}
                onDragend={handleDragEnd}
                onReset={handleResetWidth}
              />
              <Inspector
                projectName={projectDisplayName.value}
                projectId={ws.projectId ?? undefined}
                refreshSignal={refreshSignal.value}
                pendingChanges={pendingChanges.value}
                onResolveChange={resolveChange}
                modelAvailable={llmAvailable.value}
                onSend={handleAssistantSend}
                pendingSelection={pendingSelection.value}
                onClearSelection={clearSelection}
              />
            </div>
          </div>

          <Modal
            open={volumeModalOpen.value}
            title="新建卷"
            width={420}
            onClose={() => (volumeModalOpen.value = false)}
          >
            <div class="volume-create-form">
              <label class="volume-create-label">卷名</label>
              <input
                class="volume-create-input"
                value={volumeNameDraft.value}
                onInput={(e) => (volumeNameDraft.value = (e.target as HTMLInputElement).value)}
                onKeydown={(e) => {
                  if (e.key === "Enter") handleCreateVolume();
                }}
                placeholder="如：第一卷 · 风起"
                autofocus
              />
              <p class="volume-create-hint">
                卷序号将自动分配；起始/结束章节默认为空（-1），卷内添加章节后自动归属。
              </p>
              <div class="volume-create-actions">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => (volumeModalOpen.value = false)}
                >
                  取消
                </Button>
                <Button
                  size="sm"
                  onClick={handleCreateVolume}
                  disabled={!volumeNameDraft.value.trim()}
                  loading={creatingVolume.value}
                >
                  {!creatingVolume.value && <PhPlus size={12} />}
                  <span class="btn-label">创建</span>
                </Button>
              </div>
            </div>
          </Modal>
        </div>
      </PageLoader>
    );
  },
});
