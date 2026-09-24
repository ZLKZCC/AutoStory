import { http } from "./client";
import type { ChapterInfo } from "./types";

export interface VolumeInfo {
  id: number;
  project_id: number;
  volume_index: number;
  name: string;
  summary: string;
  chapter_start: number;
  chapter_end: number;
  summary_generated_at?: string;
}

export interface VolumeDetail extends VolumeInfo {
  chapter_count?: number;
  total_word_count?: number;
}

export interface CreateVolumeRequest {
  project_id: number;
  name: string;
  volume_index: number;
  chapter_start: number;
  chapter_end: number;
  summary?: string;
}

export interface UpdateVolumeRequest {
  name?: string;
  summary?: string;
}

export interface VolumeWithChapters extends VolumeDetail {
  chapters?: ChapterInfo[];     // 已加载的章节列表
  expanded?: boolean;            // UI 状态：是否展开
  loading?: boolean;             // 是否正在加载
  currentPage?: number;          // 当前页码
  hasMore?: boolean;             // 是否还有更多
}

export function getProjectVolumes(
  projectId: number,
  includeStats: boolean = false
): Promise<{ data: VolumeDetail[] }> {
  return http.get<{ data: VolumeDetail[] }>(
    `/autostory/volume/project/${projectId}${includeStats ? '?include_stats=true' : ''}`
  );
}

export function getVolumeById(volumeId: number): Promise<{ data: VolumeDetail }> {
  return http.get<{ data: VolumeDetail }>(`/autostory/volume/${volumeId}`);
}

export function createVolume(payload: CreateVolumeRequest): Promise<{ data: VolumeDetail }> {
  return http.post<{ data: VolumeDetail }>("/autostory/volume", payload);
}

export function updateVolume(
  volumeId: number,
  payload: UpdateVolumeRequest
): Promise<{ data: VolumeDetail }> {
  return http.put<{ data: VolumeDetail }>(`/autostory/volume/${volumeId}`, payload);
}

export function deleteVolume(volumeId: number): Promise<{ data: { Resp: string } }> {
  return http.delete<{ data: { Resp: string } }>(`/autostory/volume/${volumeId}`);
}

export function getVolumeChapters(
  volumeId: number,
  page: number = 1,
  pagesize: number = 50
): Promise<{ data: { List: ChapterInfo[], Total: number, More: boolean } }> {
  return http.get<{ data: { List: ChapterInfo[], Total: number, More: boolean } }>(
    `/autostory/volume/${volumeId}/chapters?page=${page}&pagesize=${pagesize}`
  );
}
