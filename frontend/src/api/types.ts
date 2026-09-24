export interface ProjectInfo {
  id?: number;
  name: string;
  description: string;
  path: string;
  chapter_count: number;
  character_count: number;
  summary?: string;
  concept?: Record<string, unknown> | null;
  worldline?: Record<string, unknown> | null;
}

export interface ChapterInfo {
  id: number;
  title: string;
  chapter_index: number;
  word_count: number;
  content?: string;
  content_updated_at?: string;
}

export interface OutlineSection {
  id: string;
  title: string;
  content: string;
  chapter_index: number | null;
  created_at: string;
  updated_at: string;
}

export interface OutlineData {
  sections: OutlineSection[];
  global_notes: string;
  outline_html?: string;
}

export interface Worldline {
  id: string;
  name: string;
  description: string;
  parent_branch: string | null;
  branch_point_chapter: number | null;
  chapters: string[];
  created_at: string;
  updated_at: string;
  nodes?: {
    id: string;
    title: string;
    description: string;
    color: string;
    textColor: string;
    fontSize: number;
    fontWeight: string;
    fontStyle: string;
    x: number;
    y: number;
  }[];
  edges?: {
    id: string;
    from: string;
    to: string;
    label: string;
    arrowType: string;
    sourceHandle?: string;
    targetHandle?: string;
  }[];
  text?: string;
}

export interface WorldlineData {
  worldlines: Worldline[];
  active: string | null;
}

export interface CharacterInfo {
  id: number;
  character_name: string;
  gender: string;
  role: string;
}

export interface CharacterStageInfo {
  id: number;
  stage_name: string;
  alias_name: string;
  gender: string;
  chapter_index: number;
  age_Description: string;
  appearance_description: string;
  profile: string;
  voice_description: string;
  voice_path: string;
}

export interface ProviderInfo {
  id: number;
  provider_name: string;
  kind: string;
  model_id: string;
  context_length: number;
  active: boolean;
  api_url: string;
  api_key: string;
}

export interface ResourceItem {
  id: number;
  Audio_name: string;
  audiotype: string;
  description: string;
  path: string;
}

export interface AudioScriptItem {
  id: number;
  name: string;
  project_id: number;
  chapter_id: number;
  script_path: string;
  audio_path: string;
  mapping: string;
  narrator_desc: string;
  stage_payload: string;
}

export interface NarratorConfig {
  voice_desc: string;
  sample_text: string;
}

export interface PrepareItem {
  name: string; // "pytorch" | "ffmpeg" | 模型名
  progress: number; // 0-100
  speed: string; // "12.5 MB/s"，不适用时为 ""（如 ffmpeg 秒装完）
  status: "pending" | "running" | "done" | "error";
  error?: string; // status 为 error 时给用户看的话
}

export interface CheckModelItem {
  id: string; // 模型标识（触发下载用）
  name: string; // 显示名
  description: string;
  category: "tts" | "vector"; // 所属引擎分组
  size: string; // 显示用大小，如 "1.8 GB"
  exists: boolean; // 模型文件已就绪
}

export interface MaterialInfo {
  id: number;
  name: string;
  description: string;
  created_at: number;
  updated_at: number;
  knowledge_count?: number;
  chunk_count?: number;
}

export interface MaterialKnowledge {
  id: string;
  material_id: number;
  knowledge_name: string;
  chunk_count: number;
  word_count: number;
}

export interface KnowledgeChunk {
  id: string;
  material_id: number;
  knowledge_name: string;
  chunk_id: number;
  content: string;
}

export interface KnowledgeSearchResult {
  id: string;
  material_id: number;
  material_name: string;
  knowledge_name: string;
  chunk_id: number;
  content: string;
  score: number;
}

export interface UserPreferenceInfo {
  id: number;
  chunk_model: boolean;
  chunk_size: number;
  overlap_size: number;
}

export interface ImportProgress {
  status: "processing" | "completed" | "error";
  total_files: number;
  processed_files: number;
  current_file: string;
  progress: number;
  imported: number;
  error: string | null;
}

export interface ProjectKnowledgeRef {
  id: number;
  content: string;
}
