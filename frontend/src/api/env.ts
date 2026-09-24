import { invoke } from "@tauri-apps/api/core";
import { ok } from "./mock";
import { http, createWsChannel, type WsChannel } from "./client";
import type { PrepareItem, CheckModelItem } from "./types";

export const prepareEnvironment = async (): Promise<{ items: PrepareItem[] }> => {
  if ("__TAURI_INTERNALS__" in window) {
    return invoke<{ items: PrepareItem[] }>("prepare_environment");
  }
  return ok<{ items: PrepareItem[] }>({
    items: [
      { name: "pytorch", progress: 100, speed: "", status: "done" },
      { name: "ffmpeg", progress: 100, speed: "", status: "done" },
    ],
  });
};

export const prepareModels = (
  onUpdate: (items: PrepareItem[]) => void,
  opts: { onClose?: (ev: CloseEvent) => void } = {},
): WsChannel => {
  const ws = createWsChannel("/autostory/environment/sync_model", {
    reconnectInterval: 3000,
    maxRetries: 100,
    ...opts,
  });
  ws.on((data) => {
    const list = (data as { data?: unknown })?.data;
    if (Array.isArray(list)) onUpdate(list as PrepareItem[]);
  });
  return ws;
};

export const checkModels = () =>
  http.get<{ items: CheckModelItem[] }>("/autostory/environment/check_models");

export const retryFailedModels = () =>
  http.post<{ retried: string[] }>("/autostory/environment/retry_failed");
