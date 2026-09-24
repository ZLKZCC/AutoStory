import { ref, reactive, computed, watch } from "vue";
import { defineStore } from "pinia";
import { useWorkspaceStore } from "./workspace";
import { useToast } from "./toast";
import { panelSynthesizeStream, type SynthProgress } from "../api/audiobook";

export type StepKey = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9;

export type BusyKey =
  | "create" | "naming" | "extracting" | "proposing" | "confirmingProposal"
  | "cataloging" | "suggesting" | "confirmingMapping" | "savingAudios"
  | "confirmingNarrator" | "previewing" | "generatingScript" | "savingScript";

type Shard = { step: StepKey; maxStep: StepKey; scriptId: number | null };

export type SynthTrack = {
  running: boolean;
  queued: boolean;
  progress: SynthProgress | null;
};

export const useAudiobookStore = defineStore("audiobook", () => {
  const ws = useWorkspaceStore();
  const { addToast } = useToast();

  const shards = reactive(new Map<number, Shard>());
  const emptyShard = Object.freeze({ step: 1, maxStep: 1, scriptId: null }) as Shard;
  const shardOf = (pid: number): Shard => {
    if (!shards.has(pid)) shards.set(pid, { step: 1, maxStep: 1, scriptId: null });
    return shards.get(pid)!;
  };

  const step = computed({
    get: () => (ws.projectId != null ? shardOf(ws.projectId).step : emptyShard.step),
    set: (v: StepKey) => { if (ws.projectId != null) shardOf(ws.projectId).step = v; },
  });
  const maxStep = computed({
    get: () => (ws.projectId != null ? shardOf(ws.projectId).maxStep : emptyShard.maxStep),
    set: (v: StepKey) => { if (ws.projectId != null) shardOf(ws.projectId).maxStep = v; },
  });
  const scriptId = computed({
    get: () => (ws.projectId != null ? shardOf(ws.projectId).scriptId : emptyShard.scriptId),
    set: (v: number | null) => { if (ws.projectId != null) shardOf(ws.projectId).scriptId = v; },
  });

  const busy = reactive<Record<BusyKey, boolean>>({
    create: false, naming: false, extracting: false, proposing: false,
    confirmingProposal: false, cataloging: false, suggesting: false,
    confirmingMapping: false, savingAudios: false, confirmingNarrator: false,
    previewing: false, generatingScript: false, savingScript: false,
  });
  const anyBusy = computed(() => Object.values(busy).some(Boolean));

  watch(() => ws.projectId, () => {
    for (const k of Object.keys(busy) as BusyKey[]) busy[k] = false;
  });

  const synthTracks = reactive(new Map<number, SynthTrack>());

  const startSynth = (scriptId: number) => {
    if (synthTracks.get(scriptId)?.running) return;
    synthTracks.set(scriptId, { running: true, queued: false, progress: null });
    panelSynthesizeStream(scriptId, {
      onQueued: () => {
        const t = synthTracks.get(scriptId);
        if (t) t.queued = true;
      },
      onProgress: (p) => {
        const t = synthTracks.get(scriptId);
        if (t) { t.queued = false; t.progress = p; }
      },
      onDone: () => {
        synthTracks.delete(scriptId);
        addToast({ type: "success", title: "合成完成，可以试听了", duration: 3000 });
      },
      onError: (detail) => {
        synthTracks.delete(scriptId);
        addToast({ type: "error", title: detail, duration: 3500 });
      },
    });
  };

  const synthOf = (scriptId: number | null): SynthTrack | null =>
    (scriptId != null && synthTracks.get(scriptId)) || null;

  return { step, maxStep, scriptId, busy, anyBusy, shardOf, synthOf, startSynth };
});
