import { http, resolveUrl } from "./client";
import type { ResourceItem } from "./types";

export const listResources = (audiotype?: string, page?: number, pagesize?: number) =>
  http.get<{ data: { List: ResourceItem[]; Total: number } }>(
    "/autostory/resource/resources",
    { query: { audiotype, page, pagesize } },
  );

export function uploadResource(
  data: { audio_name: string; audiotype: string; description: string },
  file: File,
  onProgress?: (pct: number) => void,
): Promise<ResourceItem | null> {
  const formData = new FormData();
  formData.append("audio_name", data.audio_name);
  formData.append("audiotype", data.audiotype);
  formData.append("description", data.description);
  formData.append("file", file);

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable) onProgress?.(Math.round((e.loaded / e.total) * 100));
    });
    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const resp = JSON.parse(xhr.responseText);
          resolve(resp?.data?.Resource ?? null);
        } catch {
          reject(new Error("响应解析失败"));
        }
      } else reject(new Error(`上传失败 (${xhr.status})`));
    });
    xhr.addEventListener("error", () => reject(new Error("网络错误")));
    xhr.addEventListener("abort", () => reject(new Error("上传已取消")));
    xhr.open("POST", resolveUrl("/autostory/resource/add_resource"));
    xhr.send(formData);
  });
}

export const updateResource = (
  audioId: number,
  data: { audio_name?: string; description?: string },
) => {
  const formData = new FormData();
  if (data.audio_name !== undefined) formData.append("audio_name", data.audio_name);
  if (data.description !== undefined) formData.append("description", data.description);
  return http.put<{ data: { Resource: ResourceItem; Resp: string } }>(
    `/autostory/resource/update_resource/${audioId}`,
    formData,
  );
};

export const deleteResource = (audioId: number) =>
  http.delete<{ data: { Resp: string } }>(`/autostory/resource/delete_resource/${audioId}`);

export const batchDeleteResources = (audioIds: number[]) =>
  http.post<{ data: { Resp: string } }>("/autostory/resource/batch_delete_resources",
    audioIds,
  );

export const getResourceFileUrl = (audioId: number) =>
  resolveUrl(`/autostory/resource/file/${audioId}`);

export const getProjectAudioResources = (projectId: number) =>
  http.get<{ data: { List: ResourceItem[] } }>(`/autostory/resource/project/${projectId}`);

export const addProjectAudioResource = (projectId: number, audioId: number) =>
  http.post<{ data: { Resp: string } }>("/autostory/resource/add_mapping", {
    project_id: projectId,
    audio_id: audioId,
  });

export const removeProjectAudioResource = (projectId: number, audioId: number) =>
  http.delete<{ data: { Resp: string } }>("/autostory/resource/remove_mapping", {
    query: { project_id: projectId, audio_id: audioId },
  });
