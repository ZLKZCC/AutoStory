import { http } from "./client";
import type { ProjectInfo, OutlineData, WorldlineData } from "./types";

interface ProjectDetailDTO {
  id: number;
  project_name: string;
  description: string;
  Project_summary: string;
  concept: Record<string, unknown> | null;
  worldline: Record<string, unknown> | null;
  activetime: string;
}

interface ProjectListResp {
  data: {
    List: ProjectDetailDTO[];
    Chaptercount: Record<string, number>;
    Charactercount: Record<string, number>;
    More: boolean;
  };
}

export const listProjects = async (): Promise<ProjectInfo[]> => {
  const res = await http.get<ProjectListResp>("/autostory/project/projects", {
    query: { page: 1, pagesize: 1000 },
  });
  const { List = [], Chaptercount = {}, Charactercount = {} } = res.data || {};
  return List.map((p) => ({
    id: p.id,
    name: p.project_name,
    description: p.description || "",
    path: "",
    chapter_count: Chaptercount[String(p.id)] ?? 0,
    character_count: Charactercount[String(p.id)] ?? 0,
  }));
};

export const createProject = async (
  name: string,
  description: string = "",
): Promise<ProjectInfo> => {
  const res = await http.post<{ data: { Project: ProjectDetailDTO; Resp: string } }>(
    "/autostory/project/create_project",
    { project_name: name, description },
  );
  const p = res.data.Project;
  return {
    id: p.id,
    name: p.project_name,
    description: p.description || "",
    path: "",
    chapter_count: 0,
    character_count: 0,
  };
};

export const getProject = async (
  projectId: number,
): Promise<ProjectInfo> => {
  const res = await http.get<{ data: { Project: ProjectDetailDTO } }>(
    `/autostory/project/${projectId}`,
  );
  const p = res.data.Project;
  return {
    id: p.id,
    name: p.project_name,
    description: p.description || "",
    path: "",
    chapter_count: 0,
    character_count: 0,
    summary: p.Project_summary || "",
    concept: p.concept ?? null,
    worldline: p.worldline ?? null,
  };
};

export const deleteProject = (projectId: number) =>
  http.delete<{ data: { Resp: string } }>(`/autostory/project/${projectId}`);

export const batchDeleteProjects = (projectIds: number[]) =>
  http.delete<{ data: { Resp: string } }>(
    `/autostory/project/projects?${projectIds.map((id) => `project_ids=${id}`).join("&")}`,
  );

export const getProjectConcept = (projectId: number) =>
  http
    .get<{ data: { Concept: OutlineData | null } }>(
      `/autostory/project/${projectId}/concept`,
    )
    .then((res) => res.data.Concept);

export const saveProjectConcept = (projectId: number, concept: OutlineData) =>
  http.put<{ data: { Concept: OutlineData; Resp: string } }>(
    `/autostory/project/${projectId}/concept`,
    concept,
  );

export const getProjectWorldline = (projectId: number) =>
  http
    .get<{ data: { Worldline: WorldlineData | null } }>(
      `/autostory/project/${projectId}/worldline`,
    )
    .then((res) => res.data.Worldline);

export const saveProjectWorldline = (
  projectId: number,
  worldline: WorldlineData,
) =>
  http.put<{ data: { Worldline: WorldlineData; Resp: string } }>(
    `/autostory/project/${projectId}/worldline`,
    worldline,
  );

export const parseFiles = async (files: File[]): Promise<string> => {
  const formData = new FormData();
  files.forEach((f) => formData.append("files", f));
  const res = await http.post<{ data: { Content: string } }>(
    "/autostory/project/parse_files",
    formData,
  );
  return res.data.Content || "";
};
