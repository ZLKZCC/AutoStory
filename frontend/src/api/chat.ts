import { http, sse } from "./client";

const CHAT_PREFIX = "/autostory/chat";

export interface ChatMessageData {
  id: number;
  role: string;          // "user" | "assistant"（旧库行可能还有 "Human"）
  content: string;       // tool_call 行 = JSON 字符串
  timestamp: string;     // ISO datetime
  type: string;          // message | tool_call | interrupt | audiobook（user/ai 由 role 区分）
  extra?: string;        // 行协议外层：绑定的 call_id（tool_call/audiobook 行）
}

export interface ChatEnvelope {
  type: "token" | "tool_call" | "tool_result" | "done" | "error" | "awaiting_input"
    | "audiobook_progress";  // custom 通道透传（目前仅有声书进度）
  seq: number;
  data: Record<string, unknown>;
}

type EnvelopeHandler = (env: ChatEnvelope) => void;

export function sendMessageStream(
  projectId: number,
  content: string,
  onEnvelope: EnvelopeHandler,
  onError?: (err: unknown) => void,
): AbortController {
  return sse(`${CHAT_PREFIX}/sendmessage`, {
    method: "POST",
    body: { project_id: projectId, content },
    onMessage: (data) => {
      if (!data || !data.trim()) return;
      try { onEnvelope(JSON.parse(data) as ChatEnvelope); } catch (e) { console.error("[chat] SSE 解析失败:", e, "raw:", data); }
    },
    onError: (err) => { onError?.(err); return false; }, // 不自动重试，断连即取消
  });
}

export function resumeStream(
  projectId: number,
  resumeValue: unknown,
  onEnvelope: EnvelopeHandler,
  onError?: (err: unknown) => void,
  identity?: { callId?: string; action?: string },
): AbortController {
  return sse(`${CHAT_PREFIX}/resume`, {
    method: "POST",
    body: {
      project_id: projectId,
      resume_value: resumeValue,
      ...(identity?.callId ? { call_id: identity.callId } : {}),
      ...(identity?.action ? { action: identity.action } : {}),
    },
    onMessage: (data) => {
      if (!data || !data.trim()) return;
      try { onEnvelope(JSON.parse(data) as ChatEnvelope); } catch (e) { console.error("[chat] SSE 解析失败:", e, "raw:", data); }
    },
    onError: (err) => { onError?.(err); return false; },
  });
}

export const cancelChat = (projectId: number) =>
  http.post<{ status: string }>(`${CHAT_PREFIX}/cancel`, { project_id: projectId });

export const getContextSize = (projectId: number, draft = "") =>
  http.get<{ tokens_used: number; context_window: number }>(
    `${CHAT_PREFIX}/context_size`,
    { query: { project_id: projectId, draft } },
  );

export const CHAT_PAGE_SIZE = 50;

export async function getChatHistoryPage(
  projectId: number,
  page: number,
): Promise<{
  messages: ChatMessageData[];
  total: number;
  more: boolean;
  tokens_used?: number;
  context_window?: number;
}> {
  const data = await http.get<{
    data: {
      List: ChatMessageData[];
      Total: number;
      More: boolean;
      tokens_used?: number;
      context_window?: number;
    };
  }>(
    "/autostory/chatrecord/chatrecords",
    { query: { project_id: projectId, page, pagesize: CHAT_PAGE_SIZE } },
  );
  return {
    messages: data.data?.List || [],
    total: data.data?.Total || 0,
    more: data.data?.More || false,
    tokens_used: data.data?.tokens_used,
    context_window: data.data?.context_window,
  };
}
