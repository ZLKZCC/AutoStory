import { defineComponent, ref, reactive, computed, watch, onMounted, onBeforeUnmount, h, type Component } from "vue";
import { storeToRefs } from "pinia";
import {
  panelCreate,
  panelGetState,
  panelSetName,
  panelExtract,
  panelProposal,
  panelProposalConfirm,
  panelGetCatalog,
  panelMappingSuggest,
  panelMappingConfirm,
  panelSetAudios,
  panelSetNarrator,
  previewNarrator,
  fetchNarratorPreview,
  panelGenScript,
  updateAudioScript,
  getGpuStatus,
  getAudioScriptContent,
  getAudioScriptAudioUrl,
  NARRATOR_SAMPLE_DEFAULT,
  ApiError,
  type PanelState,
  type Proposal,
  type CatalogItem,
  type ExtractedChar,
  type MappingEntry,
  type ScriptOverview,
  type SynthProgress,
} from "../api";
import type { ChapterInfo, ResourceItem } from "../api/types";
import { useWorkspaceStore } from "../stores/workspace";
import { useAudiobookStore, type StepKey } from "../stores/audiobook";
import { useProviderStore } from "../stores/providers";
import { useResourceStore } from "../stores/resources";
import { Button, AudioScriptPlayer, MiniAudioPlayer, MappingCanvas, type LinkPair } from ".";
import { useToast } from "../stores/toast";
import {
  PhCheck,
  PhSpeakerHigh,
  PhMusicNote,
  PhPlaylist,
  PhFileAudio,
  PhUsers,
  PhLink,
  PhFileText,
  PhArrowClockwise,
  PhSparkle,
  PhX,
  PhBookOpen,
} from "@phosphor-icons/vue";
import "./AudioBookWizard.css";
import "./audiobook/shared.css";

const STEPS: { n: StepKey; label: string; icon: Component }[] = [
  { n: 1, label: "选章节", icon: PhPlaylist },
  { n: 2, label: "命名", icon: PhBookOpen },
  { n: 3, label: "提取", icon: PhUsers },
  { n: 4, label: "提案", icon: PhSparkle },
  { n: 5, label: "配对", icon: PhLink },
  { n: 6, label: "音频", icon: PhMusicNote },
  { n: 7, label: "旁白", icon: PhSpeakerHigh },
  { n: 8, label: "脚本", icon: PhFileText },
  { n: 9, label: "合成", icon: PhFileAudio },
];

export default defineComponent({
  name: "AudioBookWizard",
  setup(_props, { expose }) {
    const ws = useWorkspaceStore();
    const { addToast } = useToast();
    const resStore = useResourceStore();
    const providerStore = useProviderStore();

    const abStore = useAudiobookStore();
    const { step, maxStep, scriptId, anyBusy } = storeToRefs(abStore);
    const busy = abStore.busy;
    const state = ref<PanelState | null>(null);

    const toastErr = (e: unknown, fallback: string) =>
      addToast({ type: "error", title: e instanceof ApiError ? e.message : fallback, duration: 3500 });

    const selectedChapterId = ref<number | null>(null);
    watch(
      () => [ws.selectedChapterId, ws.chapters.length],
      () => {
        if (
          selectedChapterId.value == null ||
          !ws.chapters.some((c) => c.id === selectedChapterId.value)
        ) {
          selectedChapterId.value = ws.selectedChapterId ?? ws.chapters[0]?.id ?? null;
        }
      },
      { immediate: true },
    );
    const selectedChapter = computed(
      () => ws.chapters.find((c) => c.id === selectedChapterId.value) || null,
    );

    const volumeGroups = computed(() => {
      const groups: { key: string; name: string; chapters: ChapterInfo[] }[] = [];
      const used = new Set<number>();
      for (const v of ws.volumes) {
        const chs = ws.chapters.filter(
          (c) => c.chapter_index >= v.chapter_start && c.chapter_index <= v.chapter_end,
        );
        chs.forEach((c) => used.add(c.id));
        groups.push({ key: `vol-${v.id}`, name: v.name || `第 ${v.volume_index + 1} 卷`, chapters: chs });
      }
      const loose = ws.chapters.filter((c) => !used.has(c.id));
      if (loose.length > 0) groups.push({ key: "loose", name: "未入卷", chapters: loose });
      return groups;
    });

    watch(selectedChapterId, () => {
      if (scriptId.value != null) {
        scriptId.value = null;
        state.value = null;
        maxStep.value = 1;
      }
    });

    const nameDraft = ref("");
    const confirmName = async () => {
      const name = nameDraft.value.trim();
      const ch = selectedChapter.value;
      if (ws.projectId == null || !name || !ch || !(ch.word_count > 0) || busy.create) return;
      await providerStore.ensureLoaded();
      if (!providerStore.llmAvailable) {
        addToast({
          type: "warning",
          title: "接下来的步骤需要模型生成内容，还没配置模型；先到设置里添加一个再继续",
          duration: 4000,
        });
        return;
      }
      busy.create = true;
      try {
        const pid = ws.projectId;
        const d = await panelCreate(pid, ch.id);
        if (ws.projectId !== pid) {
          abStore.shardOf(pid).scriptId = d.data.script_id;
          await panelSetName(d.data.script_id, name);
          return;
        }
        scriptId.value = d.data.script_id;
        state.value = d.data;
        maxStep.value = Math.max(1, d.data.step) as StepKey;
        await panelSetName(scriptId.value, name);
        if (state.value) state.value.name = name;
        if (d.data.resumed) {
          addToast({ type: "info", title: "已接上这一章之前的进度", duration: 2500 });
        }
        advance(3);
      } catch (e) {
        toastErr(e, "创建失败");
      } finally {
        busy.create = false;
      }
    };

    const characters = ref<ExtractedChar[]>([]);
    const extractCached = ref(false);

    const runExtract = async (refresh = false) => {
      if (scriptId.value == null || busy.extracting) return;
      busy.extracting = true;
      try {
        const d = await panelExtract(scriptId.value, refresh);
        characters.value = d.data.characters || [];
        extractCached.value = d.data.cached;
      } catch (e) {
        toastErr(e, "角色提取失败");
      } finally {
        busy.extracting = false;
      }
    };

    const propDraft = reactive<Proposal>({ new_characters: [], voice_supplements: [] });

    const runProposal = async (refresh = false) => {
      if (scriptId.value == null || busy.proposing) return;
      busy.proposing = true;
      try {
        const d = await panelProposal(scriptId.value, refresh);
        propDraft.new_characters = d.data.proposal?.new_characters || [];
        propDraft.voice_supplements = d.data.proposal?.voice_supplements || [];
      } catch (e) {
        toastErr(e, "提案生成失败");
      } finally {
        busy.proposing = false;
      }
    };

    const removePropChar = (i: number) => {
      propDraft.new_characters.splice(i, 1);
    };

    const confirmProposal = async () => {
      if (scriptId.value == null || busy.confirmingProposal) return;
      busy.confirmingProposal = true;
      try {
        await panelProposalConfirm(scriptId.value, {
          new_characters: propDraft.new_characters,
          voice_supplements: propDraft.voice_supplements,
        });
        await refreshState();     // 新建角色会进角色库，刷新 catalog 数据
        advance(5);
      } catch (e) {
        toastErr(e, "提案确认失败");
      } finally {
        busy.confirmingProposal = false;
      }
    };

    const catalog = ref<CatalogItem[]>([]);
    const linkPairs = ref<LinkPair[]>([]);
    const mappingCanConfirm = ref(false);

    const enterMapping = async (refreshSuggest = false) => {
      if (scriptId.value == null) return;
      if (catalog.value.length === 0) {
        busy.cataloging = true;
        try {
          const d = await panelGetCatalog(scriptId.value);
          catalog.value = d.data?.catalog || [];
        } catch (e) {
          toastErr(e, "角色清单加载失败");
        } finally {
          busy.cataloging = false;
        }
      }
      const known = state.value?.mapping || state.value?.mapping_preview;
      if (known?.entries && !refreshSuggest) {
        linkPairs.value = known.entries.map((e) => ({
          extracted_name: e.extracted_name,
          character_id: e.character_id,
          stage_id: e.stage_id,
        }));
        return;
      }
      if (busy.suggesting) return;
      busy.suggesting = true;
      try {
        const d = await panelMappingSuggest(scriptId.value, refreshSuggest);
        if (d.data?.catalog) catalog.value = d.data.catalog;   // suggest 顺带最新 catalog
        linkPairs.value = (d.data.mapping?.entries || []).map((e: MappingEntry) => ({
          extracted_name: e.extracted_name,
          character_id: e.character_id,
          stage_id: e.stage_id,
        }));
      } catch (e) {
        toastErr(e, "映射预填失败");
      } finally {
        busy.suggesting = false;
      }
    };

    const confirmMapping = async () => {
      if (scriptId.value == null || !mappingCanConfirm.value || busy.confirmingMapping) return;
      busy.confirmingMapping = true;
      try {
        await panelMappingConfirm(scriptId.value, linkPairs.value as MappingEntry[]);
        await refreshState();
        advance(6);
      } catch (e) {
        toastErr(e, "配对确认失败");
      } finally {
        busy.confirmingMapping = false;
      }
    };

    const resources = computed(() => resStore.allResources);
    const audioSelected = ref<Set<number>>(new Set());

    const bgmResources = computed(() => resources.value.filter((r) => r.audiotype === "bgm"));
    const sfxResources = computed(() => resources.value.filter((r) => r.audiotype === "sfx"));

    const toggleAudio = (id: number) => {
      const next = new Set(audioSelected.value);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      audioSelected.value = next;
    };

    const saveAudios = async () => {
      if (scriptId.value == null || busy.savingAudios) return;
      busy.savingAudios = true;
      try {
        await panelSetAudios(scriptId.value, [...audioSelected.value]);
        await refreshState();
        advance(7);
      } catch (e) {
        toastErr(e, "音频映射保存失败");
      } finally {
        busy.savingAudios = false;
      }
    };

    const narratorDesc = ref("");
    const narratorText = ref(NARRATOR_SAMPLE_DEFAULT);
    const previewUrl = ref("");
    const previewLoading = ref(false);
    let previewDisposed = false;
    const releasePreview = () => {
      if (previewUrl.value) {
        URL.revokeObjectURL(previewUrl.value);
        previewUrl.value = "";
      }
    };
    watch(narratorDesc, releasePreview);
    watch(narratorText, releasePreview);

    const gpuWaiting = ref(0);
    let gpuTimer: ReturnType<typeof setInterval> | null = null;
    const stopGpuPoll = () => {
      if (gpuTimer) clearInterval(gpuTimer);
      gpuTimer = null;
      gpuWaiting.value = 0;
    };
    const startGpuPoll = () => {
      if (gpuTimer) return;
      const tick = async () => {
        try {
          const d = await getGpuStatus();
          gpuWaiting.value = d.data?.waiting ?? 0;
        } catch {
          gpuWaiting.value = 0; // 查询失败不打扰试听本身
        }
      };
      void tick();
      gpuTimer = setInterval(tick, 2000);
    };

    const handlePreview = async () => {
      const desc = narratorDesc.value.trim();
      const text = narratorText.value.trim() || NARRATOR_SAMPLE_DEFAULT;
      if (!desc || previewLoading.value) return;
      previewLoading.value = true;
      startGpuPoll();
      try {
        const blob = await previewNarrator(desc, text);
        const url = URL.createObjectURL(blob);
        if (previewDisposed) {
          URL.revokeObjectURL(url);
          return;
        }
        releasePreview();
        previewUrl.value = url;
      } catch (e) {
        toastErr(e, "试听生成失败");
      } finally {
        previewLoading.value = false;
        stopGpuPoll();
      }
    };

    const tryCachedPreview = async () => {
      if (scriptId.value == null || !state.value?.narrator_desc) return;
      try {
        const blob = await fetchNarratorPreview(scriptId.value);
        const url = URL.createObjectURL(blob);
        if (previewDisposed) {
          URL.revokeObjectURL(url);
          return;
        }
        releasePreview();
        previewUrl.value = url;
      } catch {
      }
    };

    const confirmNarrator = async () => {
      const desc = narratorDesc.value.trim();
      if (scriptId.value == null || !desc || busy.confirmingNarrator) return;
      busy.confirmingNarrator = true;
      try {
        const text = narratorText.value.trim() || NARRATOR_SAMPLE_DEFAULT;
        await panelSetNarrator(scriptId.value, desc, text);
        await refreshState();
        advance(8);
      } catch (e) {
        toastErr(e, "旁白确认失败");
      } finally {
        busy.confirmingNarrator = false;
      }
    };

    const scriptOverview = ref<ScriptOverview | null>(null);
    const scriptJson = ref("");
    const scriptDirty = ref(false);
    const scriptError = ref("");

    const loadScriptContent = async () => {
      if (scriptId.value == null) return;
      try {
        const content = await getAudioScriptContent(scriptId.value);
        scriptJson.value = JSON.stringify(content, null, 2);
        scriptDirty.value = false;
        const segs = (content.segments as unknown[] | undefined) || [];
        scriptOverview.value = {
          segments: segs.length,
          speakers: [
            ...new Set(
              (segs as { speaker?: string }[]).map((s) => s.speaker || "").filter(Boolean),
            ),
          ].sort(),
          bgm: ((content.bgm_tracks as unknown[] | undefined) || []).length,
          sfx: ((content.sfx_tracks as unknown[] | undefined) || []).length,
          warnings: (content.metadata?.warnings as string[] | undefined) || [],
        };
      } catch {
        scriptJson.value = "";
      }
    };

    const genScript = async () => {
      if (scriptId.value == null || busy.generatingScript) return;
      busy.generatingScript = true;
      scriptError.value = "";
      try {
        const d = await panelGenScript(scriptId.value);
        scriptOverview.value = d.data.overview;
        await loadScriptContent();
        await refreshState();
      } catch (e) {
        toastErr(e, "脚本生成失败");
        const detail = e instanceof ApiError ? e.message : "脚本生成失败";
        scriptError.value = `${detail}。长章节生成脚本耗时较久，请点击重新生成多等一会儿；` +
          `若反复失败，多为模型服务超时，请到「设置 → 模型设置」检查或更换供应商。`;
      } finally {
        busy.generatingScript = false;
      }
    };

    const saveScriptEdits = async () => {
      if (scriptId.value == null || busy.savingScript) return;
      let parsed: Record<string, unknown>;
      try {
        parsed = JSON.parse(scriptJson.value);
      } catch {
        addToast({ type: "warning", title: "JSON 格式有误，改好再存", duration: 2500 });
        return;
      }
      busy.savingScript = true;
      try {
        await updateAudioScript(scriptId.value, {
          name: state.value?.name || "",
          script_content: parsed,
        });
        scriptDirty.value = false;
        addToast({ type: "success", title: "脚本修改已保存", duration: 2000 });
      } catch (e) {
        toastErr(e, "脚本保存失败");
      } finally {
        busy.savingScript = false;
      }
    };

    const synthWarnings = ref<string[]>([]);
    const synthDone = computed(() => !!(state.value?.audio_path));

    const SYNTH_PHASE_TEXT: Record<SynthProgress["phase"], string> = {
      resolve: "解析音色",
      plain: "合成无情绪段",
      emotional: "合成带情绪段",
      mix: "混音导出",
    };

    const synthTrack = computed(() => abStore.synthOf(scriptId.value));
    const synthActive = computed(() => synthTrack.value?.running === true);

    const stepNavLocked = computed(() => anyBusy.value || synthActive.value);

    const synthesize = () => {
      if (scriptId.value == null) return;
      abStore.startSynth(scriptId.value);
    };

    watch(synthActive, async (now, was) => {
      if (!was || now || scriptId.value == null) return;
      await refreshState();
      synthWarnings.value = state.value?.warnings || [];
    });

    const refreshState = async () => {
      if (scriptId.value == null) return;
      try {
        const d = await panelGetState(scriptId.value);
        state.value = d.data;
        maxStep.value = Math.max(maxStep.value, d.data.step) as StepKey;
      } catch {
      }
    };

    const advance = (next: StepKey) => {
      maxStep.value = Math.max(maxStep.value, next) as StepKey;
      step.value = next;
    };

    const goStep = (n: number) => {
      if (n < 1 || n > 9 || n === step.value) return;
      if (n > maxStep.value) return;
      if (stepNavLocked.value) return;
      step.value = n as StepKey;
    };

    const loadScript = async (id: number) => {
      const pid = ws.projectId;
      if (pid == null) return;
      try {
        const d = await panelGetState(id);
        if (ws.projectId !== pid) {
          abStore.shardOf(pid).scriptId = id;
          return;
        }
        scriptId.value = d.data.script_id;
        state.value = d.data;
        maxStep.value = Math.max(2, d.data.step) as StepKey;
        const prev = step.value;
        step.value = maxStep.value;
        if (step.value === prev) onStepChange(step.value);
      } catch (e) {
        toastErr(e, "载入失败");
      }
    };

    const onStepChange = (s: StepKey) => {
      if (state.value == null) return;
      const exChars = state.value?.extraction?.characters;
      if (exChars) {
        characters.value = exChars;
        extractCached.value = true;
      }
      const pr = state.value?.proposal;
      if (pr) {
        propDraft.new_characters = pr.new_characters || [];
        propDraft.voice_supplements = pr.voice_supplements || [];
      }
      if (s === 2) {
        nameDraft.value = state.value?.name || "";
      } else if (s === 3) {
        if (!exChars) runExtract();
      } else if (s === 4) {
        if (!pr) runProposal();
      } else if (s === 5) {
        enterMapping();
      } else if (s === 6) {
        audioSelected.value = new Set(state.value?.audio_ids || []);
        if (resources.value.length === 0) resStore.loadAll();
      } else if (s === 7) {
        narratorDesc.value = state.value?.narrator_desc || "";
        narratorText.value = state.value?.narrator_text || NARRATOR_SAMPLE_DEFAULT;
        tryCachedPreview();
      } else if (s === 8) {
        if (state.value?.script_path) loadScriptContent();
        else genScript();
      } else if (s === 9) {
        synthWarnings.value = state.value?.warnings || [];
      }
    };
    watch(step, onStepChange);

    const clearLocal = () => {
      state.value = null;
      characters.value = [];
      propDraft.new_characters = [];
      propDraft.voice_supplements = [];
      catalog.value = [];
      linkPairs.value = [];
      audioSelected.value = new Set();
      scriptOverview.value = null;
      scriptJson.value = "";
      synthWarnings.value = [];
      releasePreview();
    };

    const exitToHome = () => {
      if (anyBusy.value) return;
      step.value = 1;
      maxStep.value = 1;
      scriptId.value = null;
      clearLocal();
    };

    watch(
      () => ws.projectId,
      () => {
        clearLocal();
        if (scriptId.value != null) loadScript(scriptId.value);
      },
    );

    onBeforeUnmount(() => {
      previewDisposed = true;
      releasePreview();
      stopGpuPoll(); // 试听排队轮询随组件停；合成流在 store，不随卸载断
    });

    onMounted(() => {
      if (abStore.scriptId != null) loadScript(abStore.scriptId);
    });

    expose({ loadScript, step });

    const footerSummary = computed(() => {
      const parts: string[] = [];
      const ch = selectedChapter.value;
      if (ch) parts.push(`第 ${ch.chapter_index + 1} 章「${ch.title || "未命名"}」`);
      if (state.value?.name) parts.push(`「${state.value.name}」`);
      return parts.length > 0 ? parts.join(" · ") : "选一章开始制作";
    });

    const renderResGroup = (label: string, list: ResourceItem[]) => (
      <div class="abw-res-group" key={label}>
        <div class="abw-res-group-label">{label}</div>
        {list.length === 0 ? (
          <div class="abw-empty">
            <PhMusicNote size={22} weight="light" />
            <span>音频库里还没有这类资源</span>
          </div>
        ) : (
          <div class="abw-res-list">
            {list.map((r) => {
              const selected = audioSelected.value.has(r.id);
              return (
                <button
                  key={r.id}
                  class={`abw-res-item${selected ? " selected" : ""}`}
                  onClick={() => toggleAudio(r.id)}
                >
                  <span class="abw-res-check">
                    {selected && <PhCheck size={11} weight="bold" />}
                  </span>
                  <span class="abw-res-info">
                    <span class="abw-res-name">{r.Audio_name}</span>
                    <div class="abw-res-desc">{r.description || "—"}</div>
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>
    );

    const renderSteps = () => (
      <div class="abw-steps-zone">
        {step.value >= 3 && (
          <button
            class="abw-exit-btn"
            onClick={exitToHome}
            disabled={anyBusy.value}
            title={
              anyBusy.value
                ? "有任务进行中，稍等一下再退出"
                : "退出向导回到主菜单；进度已保存，可随时从草稿继续"
            }
          >
            返回
          </button>
        )}
        <div class="abw-steps">
          {STEPS.map((s, i) => {
            const stateCls = i + 1 < step.value ? "done" : i + 1 === step.value ? "current" : "";
            const reachable = i + 1 <= maxStep.value;
            return [
              <button
                key={`step-${s.n}`}
                class={`abw-step ${stateCls}`}
                onClick={() => goStep(s.n)}
                disabled={!reachable || stepNavLocked.value}
                title={stepNavLocked.value ? "当前步骤任务进行中，完成后再切换" : undefined}
              >
                <span class="abw-step-dot">
                  {i + 1 < step.value
                    ? h(PhCheck, { size: 12, weight: "bold" })
                    : h(s.icon, { size: 12, weight: "light" })}
                </span>
                <span class="abw-step-label">{s.label}</span>
              </button>,
              ...(i < STEPS.length - 1
                ? [
                    <span
                      key={`conn-${s.n}`}
                      class={`abw-step-connector${i + 1 < step.value ? " done" : ""}`}
                    />,
                  ]
                : []),
            ];
          })}
        </div>
      </div>
    );

    return () => (
      <div class="abw">
        {renderSteps()}

        <div class="abw-card" key={step.value}>
          {step.value === 1 && (
            <>
              <div class="abw-card-title">选章节</div>
              <div class="abw-card-desc">想给哪一章配音？一次做一章。</div>
              {ws.chapters.length === 0 ? (
                <div class="abw-empty">
                  <PhPlaylist size={22} weight="light" />
                  <span>还没有章节</span>
                </div>
              ) : (
                <div class="abw-chapter-list">
                  {volumeGroups.value.map((g) => (
                    <div class="abw-vol-group" key={g.key}>
                      <div class="abw-vol-head">
                        <span class="abw-vol-title">{g.name}</span>
                        <span class="abw-vol-meta">
                          {g.chapters.length > 0
                            ? `${g.chapters.length} 章 · ${g.chapters
                                .reduce((sum, c) => sum + (c.word_count || 0), 0)
                                .toLocaleString()} 字`
                            : "还没有章节"}
                        </span>
                      </div>
                      {g.chapters.map((c) => {
                        const selected = c.id === selectedChapterId.value;
                        const empty = !(c.word_count > 0);
                        return (
                          <button
                            key={c.id}
                            class={`abw-chapter-item${selected ? " selected" : ""}${empty ? " empty" : ""}`}
                            disabled={empty}
                            title={empty ? "这一章还没有正文" : undefined}
                            onClick={() => (selectedChapterId.value = c.id)}
                          >
                            <span class="abw-chapter-radio" />
                            <span class="abw-chapter-index">第 {c.chapter_index + 1} 章</span>
                            <span class="abw-chapter-name">{c.title || "未命名"}</span>
                            <span class="abw-chapter-meta">
                              {empty ? "无正文" : `${(c.word_count || 0).toLocaleString()} 字`}
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  ))}
                </div>
              )}
            </>
          )}

          {step.value === 2 && (
            <>
              <div class="abw-card-title">命名</div>
              <div class="abw-card-desc">
                给这次的有声书起个名字，方便在草稿列表里认出它。
              </div>
              <div class="abw-field">
                <label class="abw-field-label">名称</label>
                <input
                  class="abw-input"
                  value={nameDraft.value}
                  onInput={(e) => (nameDraft.value = (e.target as HTMLInputElement).value)}
                  placeholder="例：暖阳咖啡·第一章"
                  maxlength={60}
                />
              </div>
            </>
          )}

          {step.value === 3 && (
            <>
              <div class="abw-card-title">
                提取出场人物
                {busy.extracting && <span class="abw-state-badge busy">⏳</span>}
                {extractCached.value && characters.value.length > 0 && (
                  <span class="abw-cached-tag">已缓存</span>
                )}
              </div>
              <div class="abw-card-desc">AI 通读全章，找出所有说话角色（旁白不算）。</div>
              {busy.extracting ? (
                <div class="abw-empty">
                  <PhSparkle size={22} weight="light" />
                  <span>AI 正在通读章节提取角色…</span>
                </div>
              ) : characters.value.length === 0 ? (
                <div class="abw-empty">没有提取到角色，可重试</div>
              ) : (
                <div class="abw-extract-list">
                  {characters.value.map((c) => (
                    <div class="abw-extract-item" key={c.name}>
                      <div class="abw-extract-name">
                        {c.name}
                        {c.aliases.length > 0 && (
                          <span class="abw-extract-alias">（{c.aliases.join("、")}）</span>
                        )}
                      </div>
                      {c.voice_hint && <div class="abw-extract-hint">{c.voice_hint}</div>}
                      {c.evidence && <div class="abw-extract-evidence">{c.evidence}</div>}
                    </div>
                  ))}
                </div>
              )}
            </>
          )}

          {step.value === 4 && (
            <>
              <div class="abw-card-title">
                新建提案
                {busy.proposing && <span class="abw-state-badge busy">⏳</span>}
              </div>
              <div class="abw-card-desc">
                角色库里配不上的会提议新建，可编辑可移除，确认后写入角色库。
              </div>
              {busy.proposing ? (
                <div class="abw-empty">
                  <PhSparkle size={22} weight="light" />
                  <span>AI 正在比对角色库…</span>
                </div>
              ) : (
                <>
                  {propDraft.new_characters.length === 0 &&
                    (propDraft.voice_supplements || []).length === 0 && (
                      <div class="abw-hint-row">
                        <PhCheck size={13} weight="bold" />
                        <span>已有角色够用，无需新建，直接下一步。</span>
                      </div>
                    )}

                  {propDraft.new_characters.length > 0 && (
                    <>
                      <div class="abw-section-title">
                        <PhSparkle size={13} weight="light" /> 要新建的角色（可编辑）
                      </div>
                      <div class="abw-proposal-list">
                        {propDraft.new_characters.map((nc, i) => (
                          <div class="abw-proposal-item" key={i}>
                            <div class="abw-prop-grid">
                              <label class="abw-prop-cell">
                                <span class="abw-prop-label">角色名</span>
                                <input
                                  class="abw-prop-input"
                                  value={nc.character_name}
                                  onInput={(e) =>
                                    (nc.character_name = (e.target as HTMLInputElement).value)
                                  }
                                />
                              </label>
                              <label class="abw-prop-cell">
                                <span class="abw-prop-label">性别</span>
                                <input
                                  class="abw-prop-input"
                                  value={nc.gender || ""}
                                  onInput={(e) => (nc.gender = (e.target as HTMLInputElement).value)}
                                />
                              </label>
                              <label class="abw-prop-cell">
                                <span class="abw-prop-label">定位</span>
                                <input
                                  class="abw-prop-input"
                                  value={nc.role || ""}
                                  onInput={(e) => (nc.role = (e.target as HTMLInputElement).value)}
                                />
                              </label>
                              <button
                                class="abw-prop-remove"
                                title="移除这个角色（不新建）"
                                onClick={() => removePropChar(i)}
                              >
                                <PhX size={13} weight="bold" />
                              </button>
                            </div>
                            {nc.reason && <div class="abw-proposal-reason">{nc.reason}</div>}
                            <div class="abw-proposal-stages">
                              {(nc.stages || []).map((s, si) => (
                                <span class="abw-proposal-stage" key={si}>
                                  {s.stage_name}（第 {s.chapter_index + 1} 章起）
                                </span>
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                    </>
                  )}

                  {(propDraft.voice_supplements || []).length > 0 && (
                    <>
                      <div class="abw-section-title">
                        <PhSpeakerHigh size={13} weight="light" /> 为已有角色补音色描述
                      </div>
                      <div class="abw-proposal-list">
                        {propDraft.voice_supplements!.map((vs, i) => (
                          <div class="abw-proposal-item" key={i}>
                            <div class="abw-prop-sup-head">
                              {vs.character_name} · {vs.stage_name}
                            </div>
                            <textarea
                              class="abw-textarea"
                              rows={2}
                              value={vs.voice_description}
                              onInput={(e) =>
                                (vs.voice_description = (e.target as HTMLTextAreaElement).value)
                              }
                            />
                          </div>
                        ))}
                      </div>
                    </>
                  )}
                </>
              )}
            </>
          )}

          {step.value === 5 && (
            <>
              <div class="abw-card-title">
                人物配对
                {(busy.cataloging || busy.suggesting) && (
                  <span class="abw-state-badge busy">⏳</span>
                )}
              </div>
              <div class="abw-card-desc">
                先在右侧选中提取的角色，再点左侧对应的阶段卡片连线；每个角色都连过才能确认。
              </div>
              {busy.suggesting ? (
                <div class="abw-empty">
                  <PhSparkle size={22} weight="light" />
                  <span>AI 正在尝试连线…</span>
                </div>
              ) : (
                <MappingCanvas
                  catalog={catalog.value}
                  extracted={characters.value}
                  modelValue={linkPairs.value}
                  onUpdate:modelValue={(v: LinkPair[]) => (linkPairs.value = v)}
                  onConfirmEnable={(ok: boolean) => (mappingCanConfirm.value = ok)}
                />
              )}
            </>
          )}

          {step.value === 6 && (
            <>
              <div class="abw-card-title">配乐音效</div>
              <div class="abw-card-desc">
                勾选这章要用的背景音乐和音效，可跳过。
              </div>
              {resStore.allLoading ? (
                <div class="abw-empty">加载中...</div>
              ) : (
                <>
                  {renderResGroup("背景音乐", bgmResources.value)}
                  {renderResGroup("音效", sfxResources.value)}
                </>
              )}
            </>
          )}

          {step.value === 7 && (
            <>
              <div class="abw-card-title">旁白音色</div>
              <div class="abw-card-desc">
                旁白是贯穿全章的声音，描述你想要的感觉。
              </div>
              <div class="abw-field">
                <label class="abw-field-label">声音描述</label>
                <textarea
                  class="abw-textarea"
                  rows={3}
                  placeholder="例：温和沉稳的女声，语速偏慢"
                  value={narratorDesc.value}
                  onInput={(e) =>
                    (narratorDesc.value = (e.target as HTMLTextAreaElement).value)
                  }
                />
              </div>
              <div class="abw-field">
                <label class="abw-field-label">试听文本（留空用默认句）</label>
                <textarea
                  class="abw-textarea"
                  rows={2}
                  placeholder={NARRATOR_SAMPLE_DEFAULT}
                  value={narratorText.value}
                  onInput={(e) =>
                    (narratorText.value = (e.target as HTMLTextAreaElement).value)
                  }
                />
              </div>
              <div class="abw-preview-row">
                <Button
                  size="sm"
                  onClick={handlePreview}
                  loading={previewLoading.value}
                  disabled={!narratorDesc.value.trim()}
                >
                  {!previewLoading.value && <PhSpeakerHigh size={12} weight="fill" />}
                  {previewLoading.value ? "合成中…" : "试听一下"}
                </Button>
                {previewLoading.value && gpuWaiting.value > 0 && (
                  <span class="abw-queue-hint">
                    GPU 忙，排队等待中
                    {gpuWaiting.value > 1 ? `（前方 ${gpuWaiting.value - 1} 个）` : ""}
                  </span>
                )}
                {previewUrl.value && (
                  <div class="abw-preview-player">
                    <MiniAudioPlayer src={previewUrl.value} />
                  </div>
                )}
              </div>
            </>
          )}

          {step.value === 8 && (
            <>
              <div class="abw-card-title">
                生成脚本
                {busy.generatingScript && <span class="abw-state-badge busy">⏳</span>}
              </div>
              <div class="abw-card-desc">
                AI 按配对结果与音频清单排配音脚本，可手工微调后保存。
              </div>
              {!busy.generatingScript && scriptError.value && (
                <div class="abw-error-box">{scriptError.value}</div>
              )}
              {busy.generatingScript ? (
                <div class="abw-empty">
                  <PhSparkle size={22} weight="light" />
                  <span>AI 正在编排配音脚本…</span>
                </div>
              ) : (
                <>
                  {scriptOverview.value && (
                    <div class="abw-ov-chips">
                      <span class="abw-ov-chip">{scriptOverview.value.segments} 段</span>
                      {scriptOverview.value.speakers.length > 0 && (
                        <span class="abw-ov-chip">
                          {scriptOverview.value.speakers.length} 位说话人
                        </span>
                      )}
                      <span class="abw-ov-chip">{scriptOverview.value.bgm} BGM</span>
                      <span class="abw-ov-chip">{scriptOverview.value.sfx} 音效</span>
                    </div>
                  )}
                  {scriptJson.value && (
                    <textarea
                      class="abw-json"
                      value={scriptJson.value}
                      onInput={(e) => {
                        scriptJson.value = (e.target as HTMLTextAreaElement).value;
                        scriptDirty.value = true;
                      }}
                      spellcheck={false}
                    />
                  )}
                  {scriptOverview.value?.warnings.length ? (
                    <div class="abw-warnings">
                      <div class="abw-warnings-title">
                        <PhArrowClockwise size={13} weight="light" /> 生成警告
                      </div>
                      <ul>
                        {scriptOverview.value.warnings.map((w, i) => (
                          <li key={i}>{w}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </>
              )}
            </>
          )}

          {step.value === 9 && (
            <>
              <div class="abw-card-title">
                合成成品
                {synthActive.value && <span class="abw-state-badge busy">⏳</span>}
              </div>
              <div class="abw-card-desc">
                {synthDone.value
                  ? "成品已就绪，可试听；改了前面步骤可重新合成。"
                  : "把脚本合成为成品音频，大概需要几分钟。"}
              </div>
              {synthActive.value ? (
                <div class="abw-empty">
                  <PhFileAudio size={22} weight="light" />
                  <span>
                    {synthTrack.value?.queued
                      ? "GPU 正忙，排队等待中…"
                      : synthTrack.value?.progress
                        ? `正在合成 · ${SYNTH_PHASE_TEXT[synthTrack.value.progress.phase]} ${synthTrack.value.progress.done}/${synthTrack.value.progress.total} 段`
                        : "正在准备合成…"}
                  </span>
                </div>
              ) : (
                synthDone.value &&
                scriptId.value != null && (
                  <div class="abw-audio-done">
                    <div class="abw-audio-done-head">
                      <PhFileAudio size={13} weight="fill" />
                      {state.value?.name || "成品音频"}
                    </div>
                    <AudioScriptPlayer
                      src={getAudioScriptAudioUrl(scriptId.value)}
                      title={state.value?.name || "成品音频"}
                    />
                  </div>
                )
              )}
              {synthWarnings.value.length > 0 && (
                <div class="abw-warnings">
                  <div class="abw-warnings-title">
                    <PhArrowClockwise size={13} weight="light" /> 合成警告
                  </div>
                  <ul>
                    {synthWarnings.value.map((w, i) => (
                      <li key={i}>{w}</li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </div>

        <div class="abw-footer">
          <span class="abw-footer-summary">{footerSummary.value}</span>
          <div class="abw-footer-actions">
            {step.value > 1 && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => goStep(step.value - 1)}
                disabled={stepNavLocked.value}
              >
                上一步
              </Button>
            )}

            {step.value === 1 && (
              <Button
                size="sm"
                onClick={() => advance(2)}
                disabled={!(selectedChapter.value && selectedChapter.value.word_count > 0)}
              >
                下一步
              </Button>
            )}

            {step.value === 2 && (
              <Button
                size="sm"
                onClick={confirmName}
                loading={busy.create}
                disabled={!nameDraft.value.trim()}
              >
                确认命名
              </Button>
            )}

            {step.value === 3 && (
              <>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => runExtract(true)}
                  loading={busy.extracting}
                >
                  <PhArrowClockwise size={12} /> 重新提取
                </Button>
                <Button
                  size="sm"
                  onClick={() => advance(4)}
                  disabled={busy.extracting || characters.value.length === 0}
                >
                  下一步
                </Button>
              </>
            )}

            {step.value === 4 && (
              <>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => runProposal(true)}
                  loading={busy.proposing}
                >
                  <PhArrowClockwise size={12} /> 重新生成
                </Button>
                <Button
                  size="sm"
                  onClick={confirmProposal}
                  loading={busy.confirmingProposal}
                  disabled={busy.proposing}
                >
                  确认提案
                </Button>
              </>
            )}

            {step.value === 5 && (
              <>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => enterMapping(true)}
                  loading={busy.suggesting}
                >
                  <PhArrowClockwise size={12} /> 重新预填
                </Button>
                <Button
                  size="sm"
                  onClick={confirmMapping}
                  loading={busy.confirmingMapping}
                  disabled={!mappingCanConfirm.value || busy.suggesting}
                >
                  确认配对
                </Button>
              </>
            )}

            {step.value === 6 && (
              <Button size="sm" onClick={saveAudios} loading={busy.savingAudios}>
                保存并继续
              </Button>
            )}

            {step.value === 7 && (
              <Button
                size="sm"
                onClick={confirmNarrator}
                loading={busy.confirmingNarrator}
                disabled={!narratorDesc.value.trim()}
              >
                确认旁白
              </Button>
            )}

            {step.value === 8 && (
              <>
                {scriptDirty.value && (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={saveScriptEdits}
                    loading={busy.savingScript}
                  >
                    保存修改
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={genScript}
                  loading={busy.generatingScript}
                >
                  <PhArrowClockwise size={12} /> 重新生成
                </Button>
                <Button
                  size="sm"
                  onClick={() => advance(9)}
                  disabled={busy.generatingScript || !scriptJson.value}
                >
                  去合成
                </Button>
              </>
            )}

            {step.value === 9 && (
              <Button
                size="sm"
                onClick={synthesize}
                loading={synthActive.value}
                disabled={!scriptJson.value && !state.value?.script_path}
              >
                <PhFileAudio size={12} /> {synthDone.value ? "重新合成" : "开始合成"}
              </Button>
            )}
          </div>
        </div>
      </div>
    );
  },
});
