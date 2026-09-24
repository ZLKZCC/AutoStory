import { ref, computed, type Ref } from "vue";
import { defineStore, acceptHMRUpdate } from "pinia";
import {
  sendMessageStream,
  resumeStream,
  cancelChat,
  getContextSize,
  getChatHistoryPage,
  CHAT_PAGE_SIZE,
  type ChatMessageData,
  type ChatEnvelope,
} from "../api/chat";
import { ApiError } from "../api/client";
import { getProjectAudioScripts } from "../api/audiobook";
import type { AudiobookCardInfo, AudiobookAnswer } from "../components/audiobook/types";
import { REVIEW_TO_PHASE } from "../components/audiobook/types";

export interface ToolCallInfo {
  toolName: string;
  displayName?: string;
  status: "calling" | "success" | "error";
  arguments?: Record<string, unknown>;
  result?: unknown;
  error?: string;
  callId?: string;
}

export interface DataChangeInfo {
  entity: string;
  action: string;
  id?: string;
  summary?: string;
  callId?: string;
  decision?: boolean;
  status?: "pending" | "resolving" | "confirmed" | "failed" | "reverted" | "terminated";
}

export interface PendingChange {
  messageId: string;
  dataChange: DataChangeInfo;
}

export interface ChatMessage {
  id: string;
  role: "user" | "agent" | "system" | "tool_call" | "data_change" | "audiobook";
  content: string;
  timestamp: number;
  toolCall?: ToolCallInfo;
  dataChange?: DataChangeInfo;
  audiobook?: AudiobookCardInfo;  // 有声书卡片信息
  status?: "thinking" | "streaming" | "done";
  statusText?: string;
}

const liveAudiobookIdx = (msgs: ChatMessage[]): number => {
  for (let i = msgs.length - 1; i >= 0; i--) {
    const ab = msgs[i].audiobook;
    if (msgs[i].role === "audiobook" && ab && ab.status !== "done" && ab.status !== "cancelled" && ab.status !== "confirmed" && ab.status !== "reverted" && ab.status !== "failed")
      return i;
  }
  return -1;
};

const dbToMessage = (m: ChatMessageData): ChatMessage => {
  let role: ChatMessage["role"] = "agent";
  let content = m.content;
  let toolCall: ToolCallInfo | undefined;
  let dataChange: DataChangeInfo | undefined;
  let audiobook: AudiobookCardInfo | undefined;

  if (m.type === "message") {
    role = m.role === "user" || m.role === "Human" ? "user" : "agent";
  } else if (m.type === "tool_call") {
    role = "tool_call";
    try {
      const tc = JSON.parse(m.content);
      content = "";
      toolCall = {
        toolName: tc.tool || "",
        displayName: tc.display_name || tc.tool,
        status: tc.error ? "error" : "success",
        arguments: tc.arguments,
        result: tc.result,
        error: tc.error,
      };
    } catch {
    }
  } else if (m.type === "interrupt") {
    role = "data_change";
    try {
      const dc = JSON.parse(m.content);
      content = "";
      const status: DataChangeInfo["status"] = dc.resolved
        ? (dc.resolved_as === "approved"
            ? "confirmed"
            : dc.resolved_as === "terminated" ? "terminated" : "reverted")
        : "pending";
      dataChange = {
        entity: dc.entity || "",
        action: dc.action || "",
        summary: dc.summary || "",
        callId: dc.call_id || undefined,
        status,
      };
    } catch {
    }
  } else if (m.type === "audiobook") {
    role = "audiobook";
    try {
      const row = JSON.parse(m.content);
      content = "";
      const sub = String(row.subtype ?? "");
      const final = row.final as AudiobookCardInfo["status"] | undefined;
      const isDone = sub === "done";
      let status: AudiobookCardInfo["status"];
      if (isDone) {
        status = "done";       // done 行 = 完成卡（后端镜像带 final=confirmed，不影响完成态渲染）
      } else if (final) {
        status = final;        // 审核行终态：confirmed/reverted/failed/terminated 定格卡
      } else {
        status = "awaiting";   // 缺省 → 等待人审（可交互，后端按 _thread_id 恢复续跑）
      }
      audiobook = {
        status,
        phase: isDone ? "done" : (REVIEW_TO_PHASE[sub as keyof typeof REVIEW_TO_PHASE] ?? ""),
        phaseDetail: String(row.summary ?? ""),
        subtype: isDone || final ? undefined : (sub as AudiobookCardInfo["subtype"]),
        payload: isDone || final ? undefined : ({ summary: row.summary, script_id: row.script_id, ...(row.payload ?? {}) } as any),
        callId: (m as { extra?: string | number }).extra != null ? String((m as { extra?: string | number }).extra) : undefined,
        scriptId: row.script_id ?? undefined,
        warnings: isDone ? (row.warnings || undefined) : undefined,
      };
    } catch {
    }
  }

  return {
    id: String(m.id),
    role,
    content,
    timestamp: new Date(m.timestamp).getTime() || Date.now(),
    status: "done",
    toolCall,
    dataChange,
    audiobook,
  };
};

const extractAwaitingFromRecords = (records: ChatMessageData[]): unknown => {
  for (let i = records.length - 1; i >= 0; i--) {
    const r = records[i];
    if (r.type !== "interrupt" && r.type !== "audiobook") continue;
    try {
      const payload = JSON.parse(r.content);
      if (payload && !payload.resolved && !payload.final) return payload;
    } catch {
    }
  }
  return null;
};

const consolidateAudiobookCards = (msgs: ChatMessage[]): ChatMessage[] => {
  const lastIdxByCallId = new Map<string, number>();
  msgs.forEach((m, i) => {
    const cid = m.role === "audiobook" ? m.audiobook?.callId : undefined;
    if (cid) lastIdxByCallId.set(cid, i);
  });
  return msgs.filter((m, i) => {
    const cid = m.role === "audiobook" ? m.audiobook?.callId : undefined;
    if (!cid) return true;                       // 非有声书 / 无 callId：保留
    return lastIdxByCallId.get(cid) === i;       // 有声书：只留该 call_id 的最后一条
  });
};

interface ChatShard {
  messages: Ref<ChatMessage[]>;
  sending: Ref<boolean>;
  awaiting: Ref<unknown>;
  tokensUsed: Ref<number>;
  contextWindow: Ref<number>;
  dataVersion: Ref<number>;
  hasMoreMessages: Ref<boolean>;
  loadingMore: Ref<boolean>;
  loaded: Ref<boolean>;
  currentPage: number;
  ctrl: AbortController | null;
  thinkingTimer: ReturnType<typeof setInterval> | null;
  thinkingStart: number;
  historyPromise: Promise<void> | null;
  pendingWsRefresh: boolean;
  inputDraft: Ref<string>;
  narratorDrafts: Map<string, string>;
  ctxSizeTimer: ReturnType<typeof setTimeout> | null;
}

const createShard = (): ChatShard => ({
  messages: ref([]),
  sending: ref(false),
  awaiting: ref(null),
  tokensUsed: ref(0),
  contextWindow: ref(131072),
  dataVersion: ref(0),
  hasMoreMessages: ref(false),
  loadingMore: ref(false),
  loaded: ref(false),
  currentPage: 1,
  ctrl: null,
  thinkingTimer: null,
  thinkingStart: 0,
  historyPromise: null,
  pendingWsRefresh: false,
  inputDraft: ref(""),
  narratorDrafts: new Map(),
  ctxSizeTimer: null,
});

export const useChatStore = defineStore("chat", () => {
  let _msgSeq = 0;
  const nextMsgId = () => `${Date.now()}-${++_msgSeq}`;

  const shardMap = new Map<number, ChatShard>();
  const activeProjectId = ref<number | null>(null);

  const shardOf = (pid: number): ChatShard => {
    let s = shardMap.get(pid);
    if (!s) {
      s = createShard();
      shardMap.set(pid, s);
    }
    return s;
  };

  const bindProject = (pid: number | null) => {
    activeProjectId.value = pid;
    if (pid != null) shardOf(pid);
  };

  const dropShard = (pid: number) => {
    shardMap.delete(pid);
    if (activeProjectId.value === pid) activeProjectId.value = null;
  };

  const active = computed<ChatShard | null>(() =>
    activeProjectId.value == null
      ? null
      : shardMap.get(activeProjectId.value) ?? null,
  );
  const messages = computed(() => active.value?.messages.value ?? []);
  const sending = computed(() => active.value?.sending.value ?? false);
  const awaiting = computed(() => active.value?.awaiting.value ?? null);
  const tokensUsed = computed(() =>
    active.value && active.value.messages.value.length > 0
      ? active.value.tokensUsed.value
      : 0,
  );
  const contextWindow = computed(() => active.value?.contextWindow.value ?? 131072);
  const dataVersion = computed(() => active.value?.dataVersion.value ?? 0);
  const hasMoreMessages = computed(() => active.value?.hasMoreMessages.value ?? false);
  const loadingMore = computed(() => active.value?.loadingMore.value ?? false);
  const scheduleContextSizeRefresh = () => {
    const pid = activeProjectId.value;
    if (pid == null) return;
    const s = shardOf(pid);
    if (s.ctxSizeTimer) clearTimeout(s.ctxSizeTimer);
    s.ctxSizeTimer = setTimeout(() => {
      s.ctxSizeTimer = null;
      void refreshContextSize(pid);
    }, 600);
  };

  const inputDraft = computed<string>({
    get: () => active.value?.inputDraft.value ?? "",
    set: (v) => {
      if (!active.value) return;
      active.value.inputDraft.value = v;
      scheduleContextSizeRefresh();   // 草稿计入上下文 → 输入时圆环跟着动
    },
  });
  const getNarratorDraft = (callId: string): string =>
    active.value ? (active.value.narratorDrafts.get(callId) ?? "") : "";
  const setNarratorDraft = (callId: string, v: string) => {
    if (active.value) active.value.narratorDrafts.set(callId, v);
  };

  const stopThinkingTimer = (s: ChatShard) => {
    if (s.thinkingTimer) { clearInterval(s.thinkingTimer); s.thinkingTimer = null; }
  };
  const startThinkingTimer = (s: ChatShard, agentMsg: ChatMessage) => {
    stopThinkingTimer(s);
    s.thinkingStart = Date.now();
    s.thinkingTimer = setInterval(() => {
      if (agentMsg.status !== "thinking") { stopThinkingTimer(s); return; }
      const sec = Math.round((Date.now() - s.thinkingStart) / 1000);
      if (sec >= 3) {
        agentMsg.statusText = sec >= 15
          ? `思考较久，已等待 ${sec}s…`
          : `仍在思考 · ${sec}s`;
      }
    }, 3000);
  };

  const makeAgentMsg = (s: ChatShard): ChatMessage => {
    const msg: ChatMessage = {
      id: nextMsgId(),
      role: "agent",
      content: "",
      timestamp: Date.now(),
      status: "thinking",
      statusText: "正在思考...",
    };
    s.messages.value.push(msg);
    startThinkingTimer(s, msg);
    return s.messages.value[s.messages.value.length - 1];
  };

  const failLiveAudiobook = (s: ChatShard, reason: string) => {
    for (let i = 0; i < s.messages.value.length; i++) {
      const m = s.messages.value[i];
      const ab = m.audiobook;
      if (m.role === "audiobook" && ab && (ab.status === "running" || ab.status === "awaiting")) {
        s.messages.value[i] = {
          ...m,
          audiobook: { ...ab, status: "failed", phaseDetail: reason, subtype: undefined, payload: undefined },
        };
      }
    }
  };

  const failCallingToolCalls = (s: ChatShard, reason: string) => {
    for (const m of s.messages.value) {
      if (m.role === "tool_call" && m.toolCall && m.toolCall.status === "calling") {
        m.toolCall = { ...m.toolCall, status: "error", error: m.toolCall.error || reason };
      }
    }
  };

  const handleEnvelope = (
    s: ChatShard,
    env: ChatEnvelope,
    agentMsg: ChatMessage,
    pendingTools: Map<string, ChatMessage>,
  ) => {
    const { type: etype, data } = env;

    if (s.pendingWsRefresh) {
      s.pendingWsRefresh = false;
      s.dataVersion.value++;
    }

    if (etype === "token") {
      stopThinkingTimer(s);
      agentMsg.status = "streaming";
      agentMsg.statusText = undefined;
      agentMsg.content += data.text as string;
    } else if (etype === "tool_call") {
      agentMsg.status = "done";
      const tcMsg: ChatMessage = {
        id: nextMsgId(),
        role: "tool_call",
        content: "",
        timestamp: Date.now(),
        toolCall: {
          toolName: data.tool as string,
          displayName: data.display_name as string,
          status: "calling",
          arguments: data.arguments as Record<string, unknown>,
          callId: data.call_id as string,
        },
      };
      s.messages.value.push(tcMsg);
      pendingTools.set(data.call_id as string, s.messages.value[s.messages.value.length - 1]);
      return makeAgentMsg(s);
    } else if (etype === "tool_result") {
      const tc = pendingTools.get(data.call_id as string)
        ?? s.messages.value.find((m) => m.toolCall?.callId === (data.call_id as string));
      if (tc?.toolCall) {
        tc.toolCall.status = data.error ? "error" : "success";
        tc.toolCall.result = data.result;
        tc.toolCall.error = data.error as string;
      }
      const callId = data.call_id as string;
      const dc =
        s.messages.value.find(
          (m) => m.role === "data_change" && m.dataChange?.callId === callId,
        ) ??
        s.messages.value.find(
          (m) => m.role === "data_change" && m.dataChange?.status === "resolving",
        );
      if (
        dc?.dataChange &&
        (dc.dataChange.status === "resolving" || dc.dataChange.status === "pending")
      ) {
        dc.dataChange = {
          ...dc.dataChange,
          status: data.error
            ? "failed"
            : dc.dataChange.decision === false
              ? "reverted"
              : "confirmed",
        };
        s.dataVersion.value++;
      }
      const ab =
        s.messages.value.find(
          (m) => m.role === "audiobook" && m.audiobook?.callId === callId,
        ) ??
        s.messages.value.find(
          (m) => m.role === "audiobook" && m.audiobook?.status === "awaiting",
        );
      if (ab?.audiobook) {
        const live =
          ab.audiobook.status === "running" || ab.audiobook.status === "awaiting";
        if (data.error) {
          if (live) {
            ab.audiobook = {
              ...ab.audiobook,
              status: "failed",
              phaseDetail: String(data.error),
              subtype: undefined,
              payload: undefined,
            };
            s.dataVersion.value++;
          }
        } else if (live) {
          const resultText = String(data.result ?? "");
          if (resultText.includes("放弃")) {
            ab.audiobook = { ...ab.audiobook, status: "cancelled", subtype: undefined, payload: undefined };
            s.dataVersion.value++;
          }
        }
      }
    } else if (etype === "done") {
      agentMsg.status = "done";
      agentMsg.statusText = undefined;
      if (typeof data.tokens_used === "number") {
        s.tokensUsed.value = data.tokens_used;
      }
      if (typeof data.context_window === "number" && data.context_window > 0) {
        s.contextWindow.value = data.context_window;
      }
      s.sending.value = false;
      s.ctrl?.abort();
      s.ctrl = null;
    } else if (etype === "error") {
      agentMsg.status = "done";
      if (!agentMsg.content) {
        agentMsg.content = `出错了：${data.message}`;
      }
      for (const m of s.messages.value) {
        if (m.role === "data_change" && m.dataChange?.status === "resolving") {
          m.dataChange = { ...m.dataChange, status: "failed" };
        }
      }
      failLiveAudiobook(s, `出错了：${data.message}`);
      failCallingToolCalls(s, `出错了：${data.message}`);
      s.awaiting.value = null;
      s.sending.value = false;
      s.ctrl?.abort();   // 同 done：终态即掐断
      s.ctrl = null;
    } else if (etype === "audiobook_progress") {
      const cid = data.call_id as string | undefined;
      let i = cid
        ? s.messages.value.findIndex((m) => m.role === "audiobook" && m.audiobook?.callId === cid)
        : liveAudiobookIdx(s.messages.value);
      const isDone = data.phase === "done";
      const info: AudiobookCardInfo = {
        status: isDone ? "done" : "running",
        phase: String(data.phase ?? ""),
        phaseDetail: String(data.detail ?? ""),
        warnings: Array.isArray(data.warnings) ? (data.warnings as string[]) : undefined,
        callId: cid ?? (i >= 0 ? s.messages.value[i].audiobook?.callId : undefined),
        scriptId: isDone ? (data.script_id as number | undefined)
          : (i >= 0 ? s.messages.value[i].audiobook?.scriptId : undefined),
      };
      if (i >= 0) s.messages.value[i] = { ...s.messages.value[i], audiobook: info };
      else s.messages.value.push({
        id: nextMsgId(), role: "audiobook", content: "",
        timestamp: Date.now(), audiobook: info,
      });
      if (isDone) s.dataVersion.value++;
    } else if (etype === "awaiting_input") {
      const p = (data.payload ?? {}) as Record<string, any>;
      agentMsg.status = "done";
      s.awaiting.value = data.payload;   // resume 需要（无论是否 audiobook）
      s.sending.value = false;
      s.ctrl?.abort();   // 图暂停等人：主动断流（resume 走新请求）
      s.ctrl = null;
      if (p.entity === "audiobook") {
        const cid = p.call_id ? String(p.call_id) : undefined;
        let i = cid
          ? s.messages.value.findIndex((m) => m.role === "audiobook" && m.audiobook?.callId === cid)
          : liveAudiobookIdx(s.messages.value);
        if (i >= 0 && cid) {
          const st = s.messages.value[i].audiobook?.status;
          if (st === "done" || st === "cancelled" || st === "confirmed"
              || st === "reverted" || st === "failed") {
            console.warn("[audiobook] 丢弃终态卡的残留 awaiting_input", cid, st);
            s.awaiting.value = null;
            return agentMsg;
          }
        }
        const info: AudiobookCardInfo = {
          status: "awaiting",
          phase: REVIEW_TO_PHASE[p.subtype as keyof typeof REVIEW_TO_PHASE] ?? "",
          phaseDetail: String(p.summary ?? ""),
          subtype: p.subtype,
          payload: p as any,
          callId: cid ?? (i >= 0 ? s.messages.value[i].audiobook?.callId : undefined),
          scriptId: p.script_id ?? (i >= 0 ? s.messages.value[i].audiobook?.scriptId : undefined),
        };
        if (i >= 0) s.messages.value[i] = { ...s.messages.value[i], audiobook: info };
        else s.messages.value.push({
          id: nextMsgId(), role: "audiobook", content: "",
          timestamp: Date.now(), audiobook: info,
        });
      } else {
        const dcMsg: ChatMessage = {
          id: nextMsgId(),
          role: "data_change",
          content: "",
          timestamp: Date.now(),
          dataChange: {
            entity: String(p.entity ?? ""),
            action: String(p.action ?? ""),
            summary: String(p.summary ?? ""),
            callId: p.call_id ? String(p.call_id) : undefined,
            status: "pending",
          },
        };
        s.messages.value.push(dcMsg);
      }
    }
    return agentMsg;
  };

  const loadHistoryInto = async (s: ChatShard, pid: number) => {
    const first = await getChatHistoryPage(pid, 1);
    const totalPages = Math.ceil(first.total / CHAT_PAGE_SIZE) || 1;

    let records: ChatMessageData[];
    if (totalPages <= 1) {
      records = first.messages;
      s.currentPage = 1;
      s.hasMoreMessages.value = false;
    } else {
      const last = await getChatHistoryPage(pid, totalPages);
      records = last.messages;
      s.currentPage = totalPages;
      s.hasMoreMessages.value = s.currentPage > 1;
    }
    s.messages.value = consolidateAudiobookCards(records.map(dbToMessage));
    try {
      const scriptsRes = await getProjectAudioScripts(pid, 1, 200);
      const stageMap = new Map<number, Record<string, any>>();
      for (const it of (scriptsRes.data?.List ?? [])) {
        if (it.stage_payload) {
          try { stageMap.set(it.id, JSON.parse(it.stage_payload)); } catch { /* 损坏跳过 */ }
        }
      }
      for (const m of s.messages.value) {
        if (m.role !== "audiobook" || !m.audiobook?.scriptId || !m.audiobook.payload) continue;
        const sp = stageMap.get(m.audiobook.scriptId);
        if (!sp) continue;
        const sub = m.audiobook.subtype;
        const p = m.audiobook.payload as any;
        if (sub === "proposal" && sp.proposal) p.proposal = sp.proposal;
        if (sub === "mapping" && sp.mapping_preview) p.mapping = sp.mapping_preview;
      }
    } catch { /* 脚本列表拉取失败：保留 slim 卡（计数可见、可 resume），全量缺 */
    }
    s.awaiting.value = extractAwaitingFromRecords(records);
    s.loaded.value = true;
    if (!s.sending.value) {
      if (typeof first.tokens_used === "number" && first.tokens_used > 0) {
        s.tokensUsed.value = first.tokens_used;
      }
      if (typeof first.context_window === "number" && first.context_window > 0) {
        s.contextWindow.value = first.context_window;
      }
    }
    void refreshContextSize(pid);
  };

  async function refreshContextSize(pid: number): Promise<void> {
    const s = shardOf(pid);
    try {
      const sz = await getContextSize(pid, s.inputDraft.value);
      if (s.sending.value) return;
      if (typeof sz.tokens_used === "number") s.tokensUsed.value = sz.tokens_used;
      if (typeof sz.context_window === "number") s.contextWindow.value = sz.context_window;
    } catch { /* 取不到精确值就维持现状（不回落粗估，避免给出错误的偏小数） */ }
  }

  const ensureHistoryLoaded = (pid: number): Promise<void> => {
    const s = shardOf(pid);
    if (s.historyPromise) return s.historyPromise;
    if (s.sending.value || s.awaiting.value) return Promise.resolve();
    s.historyPromise = loadHistoryInto(s, pid)
      .catch(() => { /* 拉取失败保持现状：下次进入该项目重试 */ })
      .finally(() => { s.historyPromise = null; });
    return s.historyPromise;
  };

  const loadMoreHistory = async (): Promise<boolean> => {
    const pid = activeProjectId.value;
    if (pid == null) return false;
    const s = shardOf(pid);
    if (s.loadingMore.value || !s.hasMoreMessages.value) return false;
    s.loadingMore.value = true;
    try {
      const prevPage = s.currentPage - 1;
      if (prevPage < 1) {
        s.hasMoreMessages.value = false;
        return false;
      }
      const data = await getChatHistoryPage(pid, prevPage);
      const older = data.messages.map(dbToMessage);
      s.messages.value = consolidateAudiobookCards([...older, ...s.messages.value]);
      s.currentPage = prevPage;
      s.hasMoreMessages.value = s.currentPage > 1;
      void refreshContextSize(pid);
      return true; // 告知调用方已成功加载（用于滚动位置补偿）
    } catch (e) {
      console.error("[chat] 触顶续拉失败:", e);
      return false;
    } finally {
      s.loadingMore.value = false;
    }
  };

  const send = async (text: string) => {
    const pid = activeProjectId.value;
    if (pid == null) return;
    const s = shardOf(pid);
    if (!text.trim() || s.sending.value || s.awaiting.value) return;

    s.sending.value = true;
    s.awaiting.value = null;

    const userMsg: ChatMessage = {
      id: nextMsgId(),
      role: "user",
      content: text,
      timestamp: Date.now(),
    };
    s.messages.value.push(userMsg);

    let agentMsg = makeAgentMsg(s);
    const pendingTools = new Map<string, ChatMessage>();

    s.ctrl = sendMessageStream(
      pid,
      text,
      (env) => { agentMsg = handleEnvelope(s, env, agentMsg, pendingTools); },
      (err) => {
        agentMsg.status = "done";
        const isGate = err instanceof ApiError && err.status === 409;
        if (isGate) {
          agentMsg.content = "该项目有正在进行的对话，请先处理等待中的卡片";
        } else {
          const reason = `连接断开：${err instanceof Error ? err.message : String(err)}`;
          if (!agentMsg.content) agentMsg.content = reason;
          failLiveAudiobook(s, reason);
          failCallingToolCalls(s, reason);
        }
        s.awaiting.value = null;
        s.sending.value = false;
        s.ctrl = null;
      },
    );
  };

  const resume = async (resumeValue: unknown, identity?: { callId?: string; action?: string }) => {
    const pid = activeProjectId.value;
    console.warn(
      "[resume] 调用 pid=", pid,
      "callId=", identity?.callId, "action=", identity?.action,
      "sending=", pid != null ? shardOf(pid).sending.value : "n/a",
      "hasAwaiting=", pid != null ? !!shardOf(pid).awaiting.value : "n/a",
      "\nstack:", new Error("resume-trace").stack,
    );
    if (pid == null) return;
    const s = shardOf(pid);
    if (s.sending.value || !s.awaiting.value) return;
    s.sending.value = true;
    s.awaiting.value = null;

    let agentMsg = makeAgentMsg(s);
    const pendingTools = new Map<string, ChatMessage>();

    s.ctrl = resumeStream(
      pid,
      resumeValue,
      (env) => { agentMsg = handleEnvelope(s, env, agentMsg, pendingTools); },
      (err) => {
        agentMsg.status = "done";
        const isGate = err instanceof ApiError && err.status === 409;
        if (isGate) {
          agentMsg.content = "该流程正在后台进行，刷新可查看进度";
        } else {
          const reason = `恢复失败：${err instanceof Error ? err.message : String(err)}`;
          if (!agentMsg.content) agentMsg.content = reason;
          for (const m of s.messages.value) {
            if (m.role === "data_change" && m.dataChange?.status === "resolving") {
              m.dataChange = { ...m.dataChange, status: "failed" };
            }
          }
          failLiveAudiobook(s, reason);
          failCallingToolCalls(s, reason);
        }
        s.pendingWsRefresh = false;
        s.awaiting.value = null;
        s.sending.value = false;
        s.ctrl = null;
      },
      identity,
    );
  };

  const cancel = async () => {
    const pid = activeProjectId.value;
    if (pid == null) return;
    const s = shardOf(pid);
    stopThinkingTimer(s);
    if (s.ctrl) {
      s.ctrl.abort();
      s.ctrl = null;
    }
    for (let i = 0; i < s.messages.value.length; i++) {
      const m = s.messages.value[i];
      const ab = m.audiobook;
      if (m.role === "audiobook" && ab && (ab.status === "running" || ab.status === "awaiting")) {
        s.messages.value[i] = { ...m, audiobook: { ...ab, status: "cancelled", subtype: undefined, payload: undefined } };
      }
    }
    try {
      await cancelChat(pid);
    } catch { /* 闸可能已释放，忽略 */ }
    s.sending.value = false;
    s.awaiting.value = null;
    s.messages.value = s.messages.value.filter(
      (m) => !(m.role === "agent" && m.status === "thinking"),
    );
    s.loaded.value = false;
    await ensureHistoryLoaded(pid);
  };

  const resolveChange = async (messageId: string, approved: boolean) => {
    const s = active.value;
    if (!s) return;
    const msg = s.messages.value.find((m) => m.id === messageId);
    if (!msg?.dataChange) return;
    const prev = msg.dataChange;
    if (prev.status !== "pending") return;   // 已在处理/终态，忽略重复点击
    msg.dataChange = { ...prev, status: "resolving", decision: approved };
    try {
      await resume({ approved }, { callId: prev.callId, action: prev.action });
    } catch (e) {
      msg.dataChange = prev;   // 回滚，允许重试
      throw e;
    }
  };

  const reviewAudiobook = async (messageId: string, answer: AudiobookAnswer) => {
    const s = active.value;
    if (!s) return;
    const msg = s.messages.value.find((m) => m.id === messageId);
    if (!msg?.audiobook) return;
    const prev = msg.audiobook;
    if (prev.status !== "awaiting") return;   // 非等待态（已裁决/在跑/终态），忽略重复点击
    const identity = { callId: prev.callId, action: prev.subtype };
    const willWrite = !!(answer.approved || answer.feedback);
    msg.audiobook = willWrite
      ? { ...prev, status: "running", subtype: undefined, payload: undefined }
      : { ...prev, status: "cancelled", subtype: undefined, payload: undefined };
    if (willWrite) s.pendingWsRefresh = true;
    try {
      await resume(answer, identity);
    } catch (e) {
      msg.audiobook = prev;   // 回滚
      s.pendingWsRefresh = false;
      throw e;
    }
  };

  return {
    activeProjectId,
    messages,
    sending,
    awaiting,
    tokensUsed,
    contextWindow,
    dataVersion,
    hasMoreMessages,
    loadingMore,
    inputDraft,
    getNarratorDraft,
    setNarratorDraft,
    bindProject,
    ensureHistoryLoaded,
    dropShard,
    send,
    resume,
    cancel,
    resolveChange,
    reviewAudiobook,
    loadMoreHistory,
    refreshContextSize,
  };
});

if (import.meta.hot) {
  import.meta.hot.accept(acceptHMRUpdate(useChatStore, import.meta.hot));
}
