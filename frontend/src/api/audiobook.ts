import { http, sse, resolveUrl } from "./client";
import type { AudioScriptItem } from "./types";

type Resp = { data: { Resp: string } };
type ScriptListResp = { data: { List: AudioScriptItem[]; Total: number; More: boolean } };

export interface ExtractedChar {
  name: string;
  aliases: string[];
  evidence: string;
  scene_hint: string;
  voice_hint: string;
}
export interface Extraction { characters: ExtractedChar[] }

export interface StageDraft {
  stage_name: string;
  alias_name?: string;
  gender?: string;
  chapter_index: number;
  age_Description?: string;
  appearance_description?: string;
  profile?: string;
  voice_description?: string;
}
export interface NewCharDraft {
  character_name: string;
  gender?: string;
  role?: string;
  reason?: string;
  stages: StageDraft[];
}
export interface VoiceSupplement {
  stage_id: number;
  character_name?: string;
  stage_name?: string;
  voice_description: string;
}
export interface Proposal {
  new_characters: NewCharDraft[];
  voice_supplements?: VoiceSupplement[];
}

export interface CatalogItem {
  character_id: number;
  character_name: string;
  stage_id: number;
  stage_name: string;
  chapter_index: number;
  profile: string;
  voice_description?: string;
}

export interface MappingEntry {
  extracted_name: string;
  character_id: number;
  stage_id: number;
  confidence?: number;
  reason?: string;
}
export interface Mapping { entries: MappingEntry[] }

export interface PanelState {
  script_id: number;
  project_id: number;
  chapter_id: number;
  chapter_index: number;
  chapter_title: string;
  name: string;
  step: number;
  stage: string;
  done: boolean;
  mapping: Mapping | null;
  mapping_preview: Mapping | null;
  audio_ids: number[];
  narrator_desc: string;
  narrator_text: string;
  script_path: string;
  audio_path: string;
  extraction: Extraction | null;
  proposal: Proposal | null;
  warnings: string[];
}

export interface ScriptOverview {
  segments: number;
  speakers: string[];
  bgm: number;
  sfx: number;
  warnings: string[];
}

export interface PanelAudioResource {
  id: number;
  name: string;
  type: string;
  description: string;
  path: string;
}

export const NARRATOR_SAMPLE_DEFAULT = "夜色渐深，风穿过山谷，故事从这里开始。";

export const panelCreate = (projectId: number, chapterId: number) =>
  http.post<{ data: PanelState & { resumed: boolean } }>(
    "/autostory/audiobookscript/panel/create",
    { project_id: projectId, chapter_id: chapterId },
  );

export const panelGetState = (scriptId: number) =>
  http.get<{ data: PanelState }>(`/autostory/audiobookscript/panel/${scriptId}/state`);

export const panelSetName = (scriptId: number, name: string) =>
  http.put<{ data: { Resp: string; name: string } }>(
    `/autostory/audiobookscript/panel/${scriptId}/name`,
    { name },
  );

export const panelExtract = (scriptId: number, refresh = false) =>
  http.post<{ data: { characters: ExtractedChar[]; cached: boolean } }>(
    `/autostory/audiobookscript/panel/${scriptId}/extract?refresh=${refresh}`,
  );

export const panelProposal = (scriptId: number, refresh = false) =>
  http.post<{ data: { proposal: Proposal; cached: boolean } }>(
    `/autostory/audiobookscript/panel/${scriptId}/proposal?refresh=${refresh}`,
  );

export const panelProposalConfirm = (scriptId: number, proposal: Proposal) =>
  http.post<{ data: { created: unknown[]; supplemented: number } }>(
    `/autostory/audiobookscript/panel/${scriptId}/proposal/confirm`,
    { proposal },
  );

export const panelGetCatalog = (scriptId: number) =>
  http.get<{ data: { catalog: CatalogItem[] } }>(
    `/autostory/audiobookscript/panel/${scriptId}/catalog`,
  );

export const panelMappingSuggest = (scriptId: number, refresh = false) =>
  http.post<{ data: { mapping: Mapping; catalog?: CatalogItem[]; cached: boolean } }>(
    `/autostory/audiobookscript/panel/${scriptId}/mapping/suggest?refresh=${refresh}`,
  );

export const panelMappingConfirm = (scriptId: number, entries: MappingEntry[]) =>
  http.put<Resp>(`/autostory/audiobookscript/panel/${scriptId}/mapping`, { entries });

export const panelGetAudios = (scriptId: number) =>
  http.get<{ data: { audio_ids: number[]; resources: PanelAudioResource[] } }>(
    `/autostory/audiobookscript/panel/${scriptId}/audios`,
  );

export const panelSetAudios = (scriptId: number, audioIds: number[]) =>
  http.put<{ data: { audio_ids: number[] } }>(
    `/autostory/audiobookscript/panel/${scriptId}/audios`,
    { audio_ids: audioIds },
  );

export const panelSetNarrator = (scriptId: number, narratorDesc: string, narratorText: string) =>
  http.put<Resp>(`/autostory/audiobookscript/panel/${scriptId}/narrator`, {
    narrator_desc: narratorDesc,
    narrator_text: narratorText,
  });

export const previewNarrator = (voiceDesc: string, sampleText: string) =>
  http.post<Blob>(
    "/autostory/audiobookscript/narrator_preview",
    { voice_desc: voiceDesc, sample_text: sampleText },
    { responseType: "blob" },
  );

export const fetchNarratorPreview = (scriptId: number) =>
  http.post<Blob>(
    "/autostory/audiobookscript/get_narrator_preview",
    { script_id: scriptId },
    { responseType: "blob" },
  );

export const panelGenScript = (scriptId: number) =>
  http.post<{ data: { script_path: string; overview: ScriptOverview } }>(
    `/autostory/audiobookscript/panel/${scriptId}/script`,
  );

export interface SynthProgress {
  phase: "resolve" | "plain" | "emotional" | "mix";
  done: number;
  total: number;
}
export interface SynthStreamHandlers {
  onQueued?: () => void;
  onProgress?: (p: SynthProgress) => void;
  onDone: (d: { audio_path: string; warnings: string[] }) => void;
  onError: (detail: string) => void;
}
export const panelSynthesizeStream = (scriptId: number, handlers: SynthStreamHandlers): AbortController =>
  sse(`/autostory/audiobookscript/panel/${scriptId}/synthesize/stream`, {
    onMessage: (raw) => {
      let ev: { type?: string; detail?: string };
      try {
        ev = JSON.parse(raw);
      } catch {
        return;
      }
      if (ev.type === "queued") handlers.onQueued?.();
      else if (ev.type === "progress") handlers.onProgress?.(ev as SynthProgress);
      else if (ev.type === "done") handlers.onDone?.(ev as { audio_path: string; warnings: string[] });
      else if (ev.type === "error") handlers.onError?.(ev.detail ?? "合成失败");
    },
    onError: () => {
      handlers.onError("合成连接中断；已启动的任务会继续完成，可稍后回来重试");
      return false;
    },
  });

export const getAudioScripts = (chapterId: number, page = 1, pagesize = 50) =>
  http.get<ScriptListResp>("/autostory/audiobookscript/scripts", {
    query: { chapter_id: chapterId, page, pagesize },
  });

export const getProjectAudioScripts = (projectId: number, page = 1, pagesize = 100) =>
  http.get<ScriptListResp>("/autostory/audiobookscript/project_scripts", {
    query: { project_id: projectId, page, pagesize },
  });

export const updateAudioScript = (
  scriptId: number,
  payload: { name: string; script_content: Record<string, any> },
) =>
  http.put<Resp>(`/autostory/audiobookscript/script/${scriptId}`, payload);

export const copyAudioScript = (scriptId: number) =>
  http.post<Resp>(`/autostory/audiobookscript/copy/${scriptId}`);

export const deleteAudioScriptAudio = (scriptId: number) =>
  http.delete<Resp>(`/autostory/audiobookscript/audio/${scriptId}`);

export const deleteAudioScript = (scriptId: number) =>
  http.delete<Resp>(`/autostory/audiobookscript/script/${scriptId}`);

export const batchDeleteAudioScripts = (scriptIds: number[]) =>
  http.delete<Resp>(
    `/autostory/audiobookscript/scripts?${scriptIds.map((id) => `scripts_ids=${id}`).join("&")}`,
  );

export const getAudioScriptContent = async (scriptId: number): Promise<Record<string, any>> => {
  const res = await http.get<{ data: { Content: Record<string, any> } }>(
    `/autostory/audiobookscript/script/${scriptId}/content`,
  );
  return res.data?.Content ?? {};
};

export const getAudioScriptAudioUrl = (scriptId: number) =>
  resolveUrl(`/autostory/audiobookscript/audio/${scriptId}`);
