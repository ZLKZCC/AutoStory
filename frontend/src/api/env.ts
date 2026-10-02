import { http, createWsChannel, type WsChannel } from "./client";
import { shell } from "../shell";
import type { PrepareItem, CheckModelItem } from "./types";

export const prepareEnvironment = (): Promise<{ items: PrepareItem[] }> =>
  shell.prepareEnvironment();

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
