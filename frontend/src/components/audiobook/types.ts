import type {
  CatalogItem,
  Mapping,
  MappingEntry,
  NewCharDraft,
  Proposal,
  ScriptOverview,
  VoiceSupplement,
} from "../../api/audiobook";

export type {
  CatalogItem,
  Mapping,
  MappingEntry,
  NewCharDraft,
  Proposal,
  ScriptOverview,
  VoiceSupplement,
};

export interface AudiobookAnswer {
  approved: boolean;
  edited?: {
    name?: string;
    proposal?: {
      new_characters?: NewCharDraft[];
      voice_supplements?: VoiceSupplement[];
    };
    entries?: MappingEntry[];
    narrator_desc?: string;
  };
  feedback?: string;
}

export type AudiobookSubtype = "naming" | "proposal" | "mapping" | "narrator" | "script";

export interface NarratorPreset {
  label: string;
  desc: string;
}

interface PanelBase {
  summary: string;
  script_id?: number;
}

export interface NamingPayload extends PanelBase {
  current: string;
}

export interface ProposalPayload extends PanelBase {
  proposal: Proposal;
  stage_catalog: CatalogItem[];
}

export interface MappingPayload extends PanelBase {
  mapping: Mapping;
  stage_catalog: CatalogItem[];
}

export interface NarratorPayload extends PanelBase {
  presets: NarratorPreset[];
  narrator_desc: string;
}

export interface ScriptPayload extends PanelBase {
  script_overview: ScriptOverview;
  preview?: Array<{ i: number; speaker: string; text: string }>;
  script_id: number;
}

export type AudiobookPayload =
  | NamingPayload
  | ProposalPayload
  | MappingPayload
  | NarratorPayload
  | ScriptPayload;

export type AudiobookFinal = "confirmed" | "reverted" | "failed" | "terminated";

export interface AudiobookRecordRow {
  subtype: AudiobookSubtype | "done";
  final?: AudiobookFinal;
  summary?: string;
  script_id?: number;
  payload?: Partial<AudiobookPayload>;
  warnings?: string[];
  _thread_id?: string;
}

export interface AudiobookCardInfo {
  status:
    | "running" | "awaiting"
    | "done" | "cancelled"
    | "confirmed" | "reverted" | "failed" | "terminated";
  phase: string;
  phaseDetail: string;
  subtype?: AudiobookSubtype;
  payload?: AudiobookPayload;
  warnings?: string[];
  callId?: string;
  scriptId?: number;
}

export const RAIL_PHASES = [
  { key: "naming",    label: "命名" },
  { key: "extract",   label: "提取" },
  { key: "proposal",  label: "提案" },
  { key: "mapping",   label: "配对" },
  { key: "audio",     label: "音频" },
  { key: "narrator",  label: "旁白" },
  { key: "script",    label: "脚本" },
  { key: "synthesize", label: "合成" },
  { key: "done",      label: "完成" },
] as const;

export const REVIEW_TO_PHASE: Record<AudiobookSubtype, string> = {
  naming: "naming",
  proposal: "proposal",
  mapping: "mapping",
  narrator: "narrator",
  script: "script",
};
