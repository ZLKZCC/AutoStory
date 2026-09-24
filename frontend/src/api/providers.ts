import { http } from "./client";
import type { ProviderInfo } from "./types";

export const listProviders = (page: number, pagesize: number) =>
  http.get<{ data: { List: ProviderInfo[]; Total: number; More: boolean } }>(
    "/autostory/provider/providers",
    { query: { page, pagesize } },
  );

export const addProvider = (data: {
  provider_name: string;
  kind: string;
  model_id: string;
  context_length: number;
  active: boolean;
  api_url: string;
  api_key: string;
}) =>
  http.post<{ data: { Provider: ProviderInfo; Resp: string } }>(
    "/autostory/provider/create_provider",
    data,
  );

export const updateProvider = (providerId: number, data: Partial<ProviderInfo>) =>
  http.put<{ data: { Provider: ProviderInfo; Resp: string } }>(
    `/autostory/provider/${providerId}`,
    data,
  );

export const deleteProvider = (providerId: number) =>
  http.delete<{ data: { Resp: string } }>(`/autostory/provider/${providerId}`);

export const batchDeleteProviders = (providerIds: number[]) =>
  http.post<{ data: { Deleted: number; Resp: string } }>(
    "/autostory/provider/batch-delete",
    providerIds,
  );

export const testProvider = (apiUrl: string, apiKey: string, provider?: string) =>
  http.post<{ data: { success: boolean; error?: string; models?: string[] } }>(
    "/autostory/provider/test",
    { api_url: apiUrl, api_key: apiKey, provider },
  );

export const testConnection = (baseUrl: string, apiKey: string, provider?: string) =>
  http.post<{ data: { success: boolean; error?: string; models?: string[] } }>(
    "/autostory/provider/test-connection",
    { api_url: baseUrl, api_key: apiKey, provider },
  );

export const activateProvider = (providerId: number) =>
  http.get<{ data: { Provider: ProviderInfo; Resp: string } }>(
    `/autostory/provider/activate/${providerId}`,
  );
