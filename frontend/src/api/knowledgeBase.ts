import { http } from "./client";
import type {
  MaterialInfo,
  MaterialKnowledge,
  KnowledgeChunk,
  KnowledgeSearchResult,
  ImportProgress,
  ProjectKnowledgeRef,
} from "./types";

export const listMaterials = (search?: string, sort?: string) =>
  http
    .get<{ data: { List: MaterialInfo[]; Total: number } }>(
      "/autostory/material/materials",
      { query: { search, sort, page: 1, pagesize: 1000 } },
    )
    .then((res) => ({ materials: res.data.List }));

export const createMaterial = (name: string, description: string = "") =>
  http.post<{ data: { Material: MaterialInfo; Resp: string } }>(
    "/autostory/material/create_material",
    { material_name: name, description },
  );

export const getMaterial = (materialId: number) =>
  http.get<{ data: { Material: MaterialInfo } }>(
    `/autostory/material/${materialId}`,
  );

export const updateMaterial = (
  materialId: number,
  data: { material_name?: string; description?: string },
) =>
  http.put<{ data: { Material: MaterialInfo; Resp: string } }>(
    `/autostory/material/${materialId}`,
    data,
  );

export const deleteMaterial = (materialId: number) =>
  http.delete<{ data: { Resp: string } }>(
    `/autostory/material/delete_material/${materialId}`,
  );

export const batchDeleteMaterials = (materialIds: number[]) =>
  http.post<{ data: { Resp: string } }>(
    "/autostory/material/batch_delete_materials",
    materialIds,
  );

export const listMaterialKnowledges = (materialId: number) =>
  http
    .get<{ data: { List: MaterialKnowledge[]; Total: number } }>(
      `/autostory/material/${materialId}/knowledges`,
    )
    .then((res) => ({ knowledges: res.data.List }));

export const deleteMaterialKnowledge = (materialId: number, knowledgeName: string) =>
  http.delete<{ data: { Resp: string } }>(
    `/autostory/material/${materialId}/knowledges`,
    { query: { knowledge_name: knowledgeName } },
  );

export const listKnowledgeChunks = (materialId: number, knowledgeName: string) =>
  http
    .get<{ data: { List: KnowledgeChunk[]; Total: number } }>(
      `/autostory/material/${materialId}/chunks`,
      { query: { knowledge_name: knowledgeName, page: 1, pagesize: 1000 } },
    )
    .then((res) => ({ chunks: res.data.List }));

export const searchMaterial = (materialId: number, query: string, limit: number = 20) =>
  http
    .post<{ data: { List: KnowledgeSearchResult[]; Total: number } }>(
      `/autostory/material/${materialId}/search`,
      { query, top_k: limit },
    )
    .then((res) => ({ entries: res.data.List }));

export const searchKnowledgeGlobal = (query: string, limit: number = 20) =>
  http
    .post<{ data: { List: KnowledgeSearchResult[]; Total: number } }>(
      "/autostory/material/search",
      { query, top_k: limit },
    )
    .then((res) => ({ entries: res.data.List }));

export const importMaterialFiles = (materialId: number, files: File[], titles?: string[]) => {
  const form = new FormData();
  files.forEach((f) => form.append("files", f));
  titles?.forEach((t) => form.append("knowledge_names", t));
  return http.post<{ data: { TaskId: string; Total: number; Resp: string } }>(
    `/autostory/material/${materialId}/import`,
    form,
  );
};

export const getImportProgress = (taskId: string) =>
  http
    .get<{ data: { Progress: ImportProgress } }>(
      `/autostory/material/import-progress/${taskId}`,
    )
    .then((res) => res.data.Progress);

export const getProjectKnowledges = (projectId: number) =>
  http
    .get<{ data: { List: ProjectKnowledgeRef[]; Total: number } }>(
      `/autostory/project/klproject/${projectId}`,
    )
    .then((res) => ({ knowledges: res.data.List }));

export const addProjectKnowledge = (
  projectId: number,
  content: string,
) =>
  http
    .post<{ data: { Knowledge: ProjectKnowledgeRef; Resp: string } }>(
      `/autostory/project/klproject/${projectId}`,
      content,
    )
    .then((res) => res.data.Knowledge);

export const deleteProjectKnowledge = (
  projectId: number,
  content: string,
) =>
  http.delete<{ data: { Resp: string } }>(
    `/autostory/project/klproject/${projectId}`,
    { body: content },
  );
