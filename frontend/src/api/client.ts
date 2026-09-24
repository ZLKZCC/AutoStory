import ReconnectingWebSocket from "reconnecting-websocket";
import { fetchEventSource } from "@microsoft/fetch-event-source";

const runtime = window as unknown as {
  __AUTOSTORY_PORT__?: number;
  __AUTOSTORY_TOKEN__?: string;
};

const backendPort = () => runtime.__AUTOSTORY_PORT__ ?? 8080;
const appToken = () => runtime.__AUTOSTORY_TOKEN__ ?? "";

const apiOrigin = () =>
  `http${location.protocol === "https:" ? "s" : ""}://127.0.0.1:${backendPort()}`;
const wsOrigin = () =>
  `ws${location.protocol === "https:" ? "s" : ""}://127.0.0.1:${backendPort()}`;

const withOrigin = (origin: string, path: string) =>
  /^[a-z]+:\/\//.test(path) ? path : `${origin}${path.startsWith("/") ? path : `/${path}`}`;

const withQuery = (path: string, query?: Record<string, unknown>) => {
  if (!query) return path;
  const qs = Object.entries(query)
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join("&");
  return qs ? `${path}${path.includes("?") ? "&" : "?"}${qs}` : path;
};

const authHeaders = (): Record<string, string> =>
  appToken() ? { "X-App-Token": appToken() } : {};
const withToken = (path: string) => withQuery(path, appToken() ? { token: appToken() } : undefined);

export const resolveUrl = (path: string) => withToken(withOrigin(apiOrigin(), path));

// 跨源直链的 <a download> 会被浏览器忽略 download 属性、Tauri 里还会拦截导航；
// 统一走 fetch → blob（同源 objectURL）→ 程序化触发下载
export const downloadUrl = async (url: string, filename: string) => {
  const res = await fetch(url);
  if (!res.ok) throw new ApiError(res.status, `下载失败(${res.status})`, null);
  const blob = await res.blob();
  const objUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objUrl;
  a.download = filename.replace(/[\\/:*?"<>|]/g, "_");
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(objUrl);
};

export class ApiError extends Error {
  readonly status: number;
  readonly payload: unknown;
  constructor(status: number, message: string, payload: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

export interface HttpOptions {
  query?: Record<string, unknown>;
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  responseType?: "json" | "blob" | "text";
}

const request = async <T>(method: string, path: string, opts: HttpOptions = {}): Promise<T> => {
  const isForm = opts.body instanceof FormData;
  const res = await fetch(withQuery(withOrigin(apiOrigin(), path), opts.query), {
    method,
    headers: {
      ...authHeaders(),
      ...(opts.body !== undefined && !isForm ? { "Content-Type": "application/json" } : {}),
      ...opts.headers,
    },
    body:
      opts.body === undefined
        ? undefined
        : isForm
          ? (opts.body as FormData)
          : JSON.stringify(opts.body),
    signal: opts.signal,
  });
  if (!res.ok) {
    let payload: unknown = null;
    try {
      payload = await res.json();
    } catch {
    }
    const detail = (payload as { detail?: string } | null)?.detail;
    throw new ApiError(res.status, detail ?? `请求失败(${res.status})`, payload);
  }
  if (opts.responseType === "blob") return (await res.blob()) as T;
  if (opts.responseType === "text") return (await res.text()) as T;
  return res.status === 204 ? (undefined as T) : res.json();
};

export const http = {
  request,
  get: <T>(path: string, opts?: HttpOptions) => request<T>("GET", path, opts),
  post: <T>(path: string, body?: unknown, opts?: HttpOptions) =>
    request<T>("POST", path, { ...opts, body }),
  put: <T>(path: string, body?: unknown, opts?: HttpOptions) =>
    request<T>("PUT", path, { ...opts, body }),
  patch: <T>(path: string, body?: unknown, opts?: HttpOptions) =>
    request<T>("PATCH", path, { ...opts, body }),
  delete: <T>(path: string, opts?: HttpOptions) => request<T>("DELETE", path, opts),
};

export interface WsOptions {
  onOpen?: () => void;
  onClose?: (ev: CloseEvent) => void;
  onError?: (ev: Event) => void;
  reconnectInterval?: number;
  maxRetries?: number;
}

export interface WsChannel {
  send: (data: unknown) => void;
  on: (handler: (data: unknown) => void) => () => void;
  close: () => void;
}

const wsUrl = (path: string) => {
  if (/^wss?:\/\//.test(path)) return path;
  if (/^https?:\/\//.test(path)) return path.replace(/^http/, "ws");
  return withToken(withOrigin(wsOrigin(), path));
};

export const createWsChannel = (path: string, opts: WsOptions = {}): WsChannel => {
  const maxRetries = opts.maxRetries ?? 3;
  let failStreak = 0;
  let uptimeTimer: ReturnType<typeof setTimeout> | null = null;
  let closedByClient = false;
  const ws = new ReconnectingWebSocket(
    wsUrl(path),
    [],
    {
      ...(opts.reconnectInterval
        ? {
            minReconnectionDelay: opts.reconnectInterval,
            maxReconnectionDelay: opts.reconnectInterval,
          }
        : {}),
      maxRetries,
    },
  );
  ws.onopen = () => {
    if (uptimeTimer) clearTimeout(uptimeTimer);
    uptimeTimer = setTimeout(() => (failStreak = 0), 5000);
    opts.onOpen?.();
  };
  ws.onclose = (ev) => {
    if (uptimeTimer) {
      clearTimeout(uptimeTimer);
      uptimeTimer = null;
    }
    if (!closedByClient && ++failStreak > maxRetries)
      opts.onClose?.(ev as unknown as CloseEvent);
  };
  ws.onerror = (ev) => opts.onError?.(ev as unknown as Event);
  const handlers = new Set<(data: unknown) => void>();
  ws.onmessage = (ev: MessageEvent) => {
    let data: unknown = ev.data;
    if (typeof data === "string") {
      try {
        data = JSON.parse(data);
      } catch {
      }
    }
    handlers.forEach((h) => h(data));
  };
  return {
    send: (data) => ws.send(typeof data === "string" ? data : JSON.stringify(data)),
    on: (handler) => {
      handlers.add(handler);
      return () => handlers.delete(handler);
    },
    close: () => {
      closedByClient = true;
      if (uptimeTimer) clearTimeout(uptimeTimer);
      ws.close();
    },
  };
};

export interface SseOptions {
  method?: "GET" | "POST";
  body?: unknown;
  query?: Record<string, unknown>;
  headers?: Record<string, string>;
  onMessage: (data: string, meta: { event: string; id?: string }) => void;
  onOpen?: () => void;
  onError?: (err: unknown) => boolean;
}

export const sse = (path: string, opts: SseOptions): AbortController => {
  const ctrl = new AbortController();
  fetchEventSource(withQuery(withOrigin(apiOrigin(), path), opts.query), {
    openWhenHidden: true,
    method: opts.method ?? "GET",
    headers: {
      ...authHeaders(),
      ...(opts.body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...opts.headers,
    },
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    signal: ctrl.signal,
    onopen: async (res) => {
      if (res.ok) {
        opts.onOpen?.();
        return;
      }
      throw new ApiError(res.status, `SSE 连接失败(${res.status})`, null);
    },
    onmessage: (ev) => opts.onMessage(ev.data, { event: ev.event, id: ev.id }),
    onerror: (err) => {
      if (opts.onError?.(err)) return; // 返回 true：交给库继续重试
      ctrl.abort(); // 默认中断，不自动重试
      throw err;
    },
  }).catch(() => {
  });
  return ctrl;
};
