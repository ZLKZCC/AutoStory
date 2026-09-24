import type { AudioScriptItem } from "../../api/types";

export interface StatusMeta {
  label: string;
  cls: string;
}

export type PanelStageKey =
  | "done"          // 成品已有（audio_path）
  | "synthesize"    // 待合成（script_path，audio_path 空）
  | "script"        // 待生成脚本（narrator_desc）
  | "audio"         // 待选音频（mapping）
  | "early";        // 前期制作（步骤 1-5：选章/命名/提取/提案/配对）

export const STAGE_META: Record<PanelStageKey, StatusMeta> = {
  done:      { label: "已完成", cls: "st-done" },
  synthesize: { label: "待合成", cls: "st-wait" },
  script:    { label: "待脚本", cls: "st-wait" },
  audio:     { label: "待音频", cls: "st-wait" },
  early:     { label: "制作中", cls: "st-draft" },
};

export const deriveStage = (s: Pick<AudioScriptItem, "audio_path" | "script_path" | "narrator_desc" | "mapping">): PanelStageKey => {
  if (s.audio_path) return "done";
  if (s.script_path) return "synthesize";
  if (s.narrator_desc) return "script";
  if (s.mapping) return "audio";
  return "early";
};

export const stageMeta = (s: AudioScriptItem): StatusMeta => STAGE_META[deriveStage(s)];

export const derivedStep = (s: AudioScriptItem): number => {
  switch (deriveStage(s)) {
    case "done": return 9;
    case "synthesize": return 9;
    case "script": return 8;
    case "audio": return 6;
    default: return 1;
  }
};
