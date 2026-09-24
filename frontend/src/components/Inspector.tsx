import {
  defineComponent,
  ref,
  computed,
  watch,
  onMounted,
  onBeforeUnmount,
  nextTick,
  type PropType,
} from "vue";
import { useRouter } from "vue-router";
import gsap from "gsap";
import type { ChatMessage, PendingChange } from "../stores/chat";
import { useChatStore } from "../stores/chat";
import { useWorkspaceStore } from "../stores/workspace";
import { useToast } from "../stores/toast";
import type { AudiobookAnswer } from "./audiobook";
import Button from "./Button";
import Tag from "./Tag";
import KnowledgePanel from "./KnowledgePanel";
import ChatBubble from "./ChatBubble";
import { entityLabel } from "./DataChangeBubble";
import ContextRing from "./ContextRing";
import { parseFile } from "../api/parseFile";
import { useConfirm } from "./ConfirmDialog";
import {
  PhGlobe,
  PhSparkle,
  PhCheck,
  PhX,
  PhPaperPlaneTilt,
  PhStop,
  PhUploadSimple,
  PhFileText,
  PhCaretDown,
} from "@phosphor-icons/vue";

type InspectTab = "chat" | "knowledge";

interface InspectTabDef {
  key: InspectTab;
  label: string;
  icon: any;
}

const tabs: InspectTabDef[] = [
  { key: "chat", label: "对话", icon: PhSparkle },
  { key: "knowledge", label: "素材", icon: PhGlobe },
];

const ACCEPTED_FILE_TYPES = [".md", ".txt", ".docx"];

const MAX_ATTACHED_FILES = 5;
const SINGLE_TURN_MAX_CHARS = 8000;
const SINGLE_TURN_WARN_THRESHOLD = 0.8;
const COLLAPSE_THRESHOLD = 160;

interface ParsedFile {
  file: File;
  content: string;
  chars: number;
}

export default defineComponent({
  name: "Inspector",
  props: {
    projectName: { type: String, required: true },
    projectId: { type: Number, default: null },
    refreshSignal: { type: Number, default: 0 },
    pendingChanges: {
      type: Array as PropType<PendingChange[]>,
      default: () => [],
    },
    onResolveChange: {
      type: Function as PropType<(messageId: string, confirmed: boolean) => void>,
      default: undefined,
    },
    modelAvailable: { type: Boolean, default: false },
    onSend: {
      type: Function as PropType<(text: string, files: File[]) => void>,
      default: undefined,
    },
    pendingSelection: { type: String, default: "" },
    onClearSelection: {
      type: Function as PropType<() => void>,
      default: undefined,
    },
  },
  setup(props) {
    const nav = useRouter();
    const { confirm } = useConfirm();
    const chat = useChatStore();
    const { addToast } = useToast();
    const ws = useWorkspaceStore();
    const activeTab = ref<InspectTab>("chat");
    watch(() => ws.chatFocusSeq, () => { activeTab.value = "chat"; });

    const input = ref("");
    watch(() => chat.activeProjectId, () => { input.value = chat.inputDraft; }, { immediate: true });
    watch(input, (v) => { chat.inputDraft = v; });
    const attachedFiles = ref<ParsedFile[]>([]);
    const dragOver = ref(false);
    const showHint = ref(false);
    const fileInputEl = ref<HTMLInputElement | null>(null);
    const chatEndEl = ref<HTMLDivElement | null>(null);
    const msgScrollEl = ref<HTMLDivElement | null>(null);
    const userScrolledAway = ref(false);
    const scrollToBottom = (force = false) => {
      nextTick(() => {
        const el = msgScrollEl.value;
        if (!el) return;
        const doScroll = () => {
          if (force || !userScrolledAway.value) el.scrollTop = el.scrollHeight; // 不用 smooth：高频触发会卡顿
        };
        doScroll();
        requestAnimationFrame(doScroll);
      });
    };

    const handleMsgScroll = (e: Event) => {
      const el = e.target as HTMLElement;
      if (el.scrollTop <= 40 && chat.hasMoreMessages && !chat.loadingMore) {
        const prevHeight = el.scrollHeight;
        const prevTop = el.scrollTop;
        Promise.resolve(chat.loadMoreHistory()).then((ok) => {
          if (ok && msgScrollEl.value) {
            const added = msgScrollEl.value.scrollHeight - prevHeight;
            msgScrollEl.value.scrollTop = prevTop + added;
          }
        });
      }
      const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
      userScrolledAway.value = distFromBottom > 80;
    };
    const collapsed = ref(window.innerWidth <= 720);
    const collapsedMsgIds = ref<Set<string>>(new Set());

    const switchTab = (tab: InspectTab) => {
      activeTab.value = tab;
    };

    const renderPending = (entities: string[]) => {
      const items = props.pendingChanges.filter((p) =>
        entities.includes(p.dataChange.entity),
      );
      if (items.length === 0) return null;
      return (
        <div class="inspector-pending">
          {items.map((i) => (
            <div class="inspector-pending-item" key={i.messageId}>
              <PhSparkle size={12} weight="fill" />
              <span class="inspector-pending-summary">
                {i.dataChange.summary ||
                  `${i.dataChange.action} · ${entityLabel(i.dataChange.entity)}`}
              </span>
              <button
                class="inspector-pending-btn accept"
                onClick={() => props.onResolveChange?.(i.messageId, true)}
              >
                <PhCheck size={11} /> 确认
              </button>
              <button
                class="inspector-pending-btn reject"
                onClick={() => props.onResolveChange?.(i.messageId, false)}
              >
                <PhX size={11} /> 放弃
              </button>
            </div>
          ))}
        </div>
      );
    };

    const isAcceptedFile = (file: File) => {
      const ext = "." + (file.name.split(".").pop()?.toLowerCase() || "");
      return ACCEPTED_FILE_TYPES.includes(ext);
    };

    const handleDragOver = (e: DragEvent) => {
      e.preventDefault();
      dragOver.value = true;
    };
    const handleDragLeave = (e: DragEvent) => {
      e.preventDefault();
      dragOver.value = false;
    };
    const handleDrop = async (e: DragEvent) => {
      e.preventDefault();
      dragOver.value = false;
      const files = Array.from(e.dataTransfer?.files || []).filter(isAcceptedFile);
      if (files.length === 0) return;
      await ingestFiles(files);
    };
    const handleFileSelect = async (e: Event) => {
      const target = e.target as HTMLInputElement;
      const files = Array.from(target.files || []).filter(isAcceptedFile);
      target.value = "";
      if (files.length === 0) return;
      await ingestFiles(files);
    };

    const ingestFiles = async (files: File[]) => {
      const remaining = MAX_ATTACHED_FILES - attachedFiles.value.length;
      if (remaining <= 0) {
        await confirm({
          title: "附件数量已达上限",
          message: `最多上传 ${MAX_ATTACHED_FILES} 个文件，请先移除已有附件。`,
          confirmText: "知道了",
        });
        return;
      }

      const accepted: ParsedFile[] = [];
      for (const file of files.slice(0, remaining)) {
        const content = await parseFile(file);
        const chars = content.length;
        const existingChars = attachedFiles.value.reduce((s, f) => s + f.chars, 0)
          + accepted.reduce((s, f) => s + f.chars, 0);
        const projected = existingChars + chars + input.value.length;
        if (projected > SINGLE_TURN_MAX_CHARS) {
          await confirm({
            title: "文件超出单轮字数限制",
            message: `附件「${file.name}」解析后 ${chars.toLocaleString()} 字，加上已输入内容共 ${projected.toLocaleString()} 字，超过单轮上限 ${SINGLE_TURN_MAX_CHARS.toLocaleString()} 字。\n\n该附件未上传。请精简附件内容、或拆分多轮发送。`,
            danger: true,
            confirmText: "知道了",
          });
          continue; // 跳过此文件，继续处理后续
        }
        accepted.push({ file, content, chars });
      }
      if (accepted.length > 0) {
        attachedFiles.value = [...attachedFiles.value, ...accepted];
      }
    };

    const removeAttachedFile = (index: number) => {
      attachedFiles.value = attachedFiles.value.filter((_, i) => i !== index);
    };

    const inputChars = computed(() => input.value.length);
    const fileChars = computed(() =>
      attachedFiles.value.reduce((s, f) => s + f.chars, 0),
    );
    const totalInputChars = computed(() => inputChars.value + fileChars.value);
    const inputRatio = computed(() => totalInputChars.value / SINGLE_TURN_MAX_CHARS);
    const isOverLimit = computed(() => totalInputChars.value > SINGLE_TURN_MAX_CHARS);
    const isWarnLimit = computed(
      () => inputRatio.value >= SINGLE_TURN_WARN_THRESHOLD && !isOverLimit.value,
    );

    const handleSend = async () => {
      if (!input.value.trim() && attachedFiles.value.length === 0) return;
      if (chat.awaiting) return;
      if (!props.modelAvailable) {
        showHint.value = true;
        return;
      }
      if (isOverLimit.value) {
        await confirm({
          title: "超出单轮字数限制",
          message: `当前总字数 ${totalInputChars.value.toLocaleString()} 超过上限 ${SINGLE_TURN_MAX_CHARS.toLocaleString()}，请精简后重试。`,
          danger: true,
          confirmText: "知道了",
        });
        return;
      }
      let prefix = "";
      if (attachedFiles.value.length > 0) {
        const parts = attachedFiles.value.map((f, i) => {
          const body = f.content.trim()
            ? f.content
            : "（解析失败或内容为空）";
          return `附件${i + 1}内容：${f.file.name}\n${body}`;
        });
        prefix = parts.join("\n\n") + "\n\n";
      }
      const text = prefix + input.value.trim();
      input.value = "";
      attachedFiles.value = [];
      props.onSend?.(text, []);
    };

    watch(
      () => chat.messages.length,
      () => scrollToBottom(true), // 新消息出现 = 发送/收到新气泡 → 强滚到底
    );
    watch(
      () => chat.messages.map((m) => m.content).join("|"),
      () => scrollToBottom(false), // 内容变化但用户滚离时不抢回
    );

    watch(
      () => props.pendingSelection,
      (sel) => {
        if (!sel) return;
        collapsed.value = false;
        activeTab.value = "chat";
        const prefix = "「" + sel.replace(/\s+/g, " ").slice(0, 80) + "」\n";
        input.value = prefix + input.value;
        props.onClearSelection?.();
      },
    );

    watch(showHint, (v) => {
      if (v) setTimeout(() => (showHint.value = false), 5000);
    });

    const toggleCollapse = () => {
      collapsed.value = !collapsed.value;
    };

    const railIconEl = ref<HTMLButtonElement | null>(null);
    let railTween: gsap.core.Tween | null = null;
    const startRailGlow = () => {
      const svg = railIconEl.value?.querySelector("svg");
      if (railTween || !svg) return;
      railTween = gsap.to(svg, {
        filter: "hue-rotate(360deg)",
        duration: 2.4,
        repeat: -1,
        ease: "none",
      });
      gsap.to(svg, {
        scale: 1.18,
        duration: 0.55,
        yoyo: true,
        repeat: -1,
        ease: "sine.inOut",
      });
    };
    const stopRailGlow = () => {
      railTween?.kill();
      railTween = null;
      const svg = railIconEl.value?.querySelector("svg");
      if (svg) {
        gsap.killTweensOf(svg);
        gsap.set(svg, { clearProps: "filter,scale" });
      }
    };
    watch(
      collapsed,
      async (c) => {
        if (c) {
          await nextTick();
          startRailGlow();
        } else {
          stopRailGlow();
        }
      },
      { immediate: false },
    );
    onMounted(() => {
      if (collapsed.value) startRailGlow();
      scrollToBottom(true);
    });

    const toggleMsgExpand = (id: string) => {
      const set = new Set(collapsedMsgIds.value);
      if (set.has(id)) set.delete(id);
      else set.add(id);
      collapsedMsgIds.value = set;
    };

    const handleDataChangeConfirm = (msgId: string) =>
      props.onResolveChange?.(msgId, true);
    const handleDataChangeRevert = (msgId: string) =>
      props.onResolveChange?.(msgId, false);

    onBeforeUnmount(() => {
      stopRailGlow();
      input.value = "";
      attachedFiles.value = [];
    });

    const renderMsg = (msg: ChatMessage, idx: number, all: ChatMessage[]) => {
      const effectiveRole =
        msg.role === "tool_call" ||
        msg.role === "data_change"
          ? "agent"
          : msg.role;
      let prevVisibleMsg: ChatMessage | null = null;
      for (let i = idx - 1; i >= 0; i--) {
        const m = all[i];
        if (!(m.role === "agent" && m.status === "done" && !m.content)) {
          prevVisibleMsg = m;
          break;
        }
      }
      const prevEffectiveRole = prevVisibleMsg
        ? prevVisibleMsg.role === "tool_call" ||
          prevVisibleMsg.role === "data_change"
          ? "agent"
          : prevVisibleMsg.role
        : null;
      const showSender =
        msg.role !== "system" &&
        msg.role !== "data_change" &&
        (!prevVisibleMsg || prevEffectiveRole !== effectiveRole);

      const isLong =
        msg.role === "agent" &&
        msg.status === "done" &&
        (msg.content || "").length > COLLAPSE_THRESHOLD;
      const expanded = !collapsedMsgIds.value.has(msg.id);

      return (
        <div
          key={msg.id}
          class={`inspector-msg-wrap${isLong && !expanded ? " collapsed" : ""}`}
        >
          <ChatBubble
            message={msg}
            showSender={showSender}
            onDataChangeConfirm={handleDataChangeConfirm}
            onDataChangeRevert={handleDataChangeRevert}
            onAudiobookSubmit={(mid: string, ans: AudiobookAnswer) =>
              chat.reviewAudiobook(mid, ans).catch((e) => {
                addToast({
                  type: "error",
                  title: "提交裁决失败",
                  message: e instanceof Error ? e.message : String(e),
                });
              })
            }
          />
          {isLong && (
            <button
              class="inspector-msg-expand"
              onClick={() => toggleMsgExpand(msg.id)}
            >
              <PhCaretDown size={11} weight="bold" />
              {expanded ? "收起" : "展开"}
            </button>
          )}
        </div>
      );
    };

    const renderRail = () => (
      <div class="inspector-rail">
        <button
          ref={railIconEl}
          class="inspector-rail-expand"
          onClick={toggleCollapse}
          title="展开对话"
        >
          <PhSparkle size={16} weight="fill" />
        </button>
      </div>
    );

    return () => (
      <div class={`inspector ${collapsed.value ? "collapsed" : ""}`}>
        {collapsed.value ? (
          renderRail()
        ) : (
          <>
            <button
              class="inspector-collapse-handle"
              onClick={toggleCollapse}
              title="收起为细条（专注写作）"
            />

            <div class="inspector-tabs">
              {tabs.map((t) => {
                const Icon = t.icon;
                return (
                  <button
                    key={t.key}
                    class={`inspector-tab-btn ${activeTab.value === t.key ? "active" : ""}`}
                    onClick={() => switchTab(t.key)}
                  >
                    <Icon size={14} weight="light" />
                    <span>{t.label}</span>
                  </button>
                );
              })}
            </div>

            <div class="inspector-content">
              {activeTab.value === "chat" && (
                <div class="inspector-chat">
                  <div class="inspector-messages" ref={msgScrollEl} onScroll={handleMsgScroll}>
                    {chat.loadingMore && (
                      <div class="inspector-load-top">加载更早消息…</div>
                    )}
                    {chat.messages.length === 0 && !chat.loadingMore && (
                      <div class="inspector-chat-empty">
                        <PhSparkle size={22} weight="light" />
                        <p>告诉它你的意图，结果会直接落到正文 / 大纲里</p>
                      </div>
                    )}
                    {chat.messages.map((msg, idx, all) =>
                      renderMsg(msg, idx, all),
                    )}
                    <div ref={chatEndEl} />
                  </div>

                  <div
                    class={`inspector-input ${dragOver.value ? "drag-over" : ""}`}
                    onDragover={handleDragOver}
                    onDragleave={handleDragLeave}
                    onDrop={handleDrop}
                  >
                    {showHint.value && (
                      <div class="inspector-hint">
                        <span>尚未配置 LLM 供应商，请先前往设置。</span>
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => nav.push("/settings")}
                        >
                          前往设置
                        </Button>
                      </div>
                    )}
                    {attachedFiles.value.length > 0 && (
                      <div class="inspector-files">
                        {attachedFiles.value.map((f, i) => (
                          <Tag key={i} size="sm" variant="info">
                            <PhFileText size={10} /> {f.file.name}
                            <span class="tag-meta">{f.chars.toLocaleString()}字</span>
                            <button
                              class="tag-remove"
                              onClick={() => removeAttachedFile(i)}
                            >
                              <PhX size={10} />
                            </button>
                          </Tag>
                        ))}
                      </div>
                    )}
                    <div class="inspector-input-row">
                      <ContextRing
                        used={chat.tokensUsed}
                        total={chat.contextWindow}
                      />
                      <textarea
                        class={`inspector-textarea ${isWarnLimit.value ? "warn" : ""} ${isOverLimit.value ? "error" : ""}`}
                        placeholder="描述意图、修改建议，或提问…"
                        maxlength={SINGLE_TURN_MAX_CHARS}
                        value={input.value}
                        onInput={(e) =>
                          (input.value = (e.target as HTMLTextAreaElement).value)
                        }
                        onKeydown={(e) => {
                          if (e.key === "Enter" && !e.shiftKey) {
                            e.preventDefault();
                            handleSend();
                          }
                        }}
                        rows={2}
                      />
                      <div class="inspector-input-actions">
                        <input
                          ref={fileInputEl}
                          type="file"
                          accept={ACCEPTED_FILE_TYPES.join(",")}
                          multiple
                          style={{ display: "none" }}
                          onChange={handleFileSelect}
                        />
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => fileInputEl.value?.click()}
                          disabled={
                            attachedFiles.value.length >= MAX_ATTACHED_FILES ||
                            chat.sending
                          }
                          title={`上传文件 (${attachedFiles.value.length}/${MAX_ATTACHED_FILES})`}
                        >
                          <PhUploadSimple size={16} weight="light" />
                        </Button>
                        {chat.sending || chat.awaiting ? (
                          <Button
                            size="md"
                            variant="danger"
                            onClick={() => chat.cancel()}
                            title={chat.sending ? "停止本轮生成" : "终止等待中的流程"}
                          >
                            <PhStop size={16} weight="fill" />
                          </Button>
                        ) : (
                          <Button
                            size="md"
                            onClick={handleSend}
                            disabled={
                              (!input.value.trim() &&
                              attachedFiles.value.length === 0) ||
                              isOverLimit.value
                            }
                          >
                            <PhPaperPlaneTilt size={16} weight="fill" />
                          </Button>
                        )}
                      </div>
                    </div>
                    <div class={`inspector-input-meta ${isWarnLimit.value ? "warn" : ""} ${isOverLimit.value ? "error" : ""}`}>
                      <span>{totalInputChars.value.toLocaleString()} / {SINGLE_TURN_MAX_CHARS.toLocaleString()} 字</span>
                      {isWarnLimit.value && <span class="meta-hint">· 即将达上限</span>}
                      {isOverLimit.value && <span class="meta-hint">· 超出上限无法发送</span>}
                    </div>
                  </div>
                </div>
              )}

              {activeTab.value === "knowledge" && (
                <div class="inspector-knowledge">
                  {renderPending(["knowledge", "fragments"])}
                  <KnowledgePanel
                    projectId={props.projectId}
                    refreshSignal={props.refreshSignal}
                  />
                </div>
              )}

            </div>
          </>
        )}
      </div>
    );
  },
});
