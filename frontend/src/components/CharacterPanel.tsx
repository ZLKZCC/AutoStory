import {
  defineComponent,
  reactive,
  ref,
  watch,
  onMounted,
  type PropType,
  type VNode,
} from "vue";
import {
  updateCharacter,
  deleteCharacter,
  listCharacterStages,
  createCharacterStage,
  updateCharacterStage,
  deleteCharacterStage,
  generateVoiceReference,
  getVoiceGeneratingStatus,
  deleteStageVoiceReference,
  getStageVoiceAudioUrl,
  type CharacterInfo,
  type CharacterStageInfo,
  type ChapterInfo,
} from "../api";
import { useToast } from "./Toast";
import { useConfirm } from "./ConfirmDialog";
import Button from "./Button";
import Tag from "./Tag";
import MiniAudioPlayer from "./MiniAudioPlayer";
import {
  PhUser,
  PhPencilSimple,
  PhSpeakerHigh,
  PhSparkle,
  PhTrash,
  PhCaretDown,
  PhCaretUp,
  PhPlus,
  PhCheck,
  PhX,
} from "@phosphor-icons/vue";

const ROLE_LABELS: Record<
  string,
  {
    label: string;
    variant: "default" | "success" | "warning" | "error" | "info";
  }
> = {
  protagonist: { label: "主角", variant: "success" },
  antagonist: { label: "反派", variant: "error" },
  supporting: { label: "配角", variant: "info" },
  extra: { label: "龙套", variant: "default" },
};

const StageVoiceGenButton = defineComponent({
  name: "StageVoiceGenButton",
  props: {
    stageId: { type: Number, required: true },
    voiceDescription: { type: String, required: true },
    isGenerating: { type: Boolean, default: false },
    onStarted: { type: Function as PropType<(stageId: number) => void>, default: undefined },
  },
  setup(props) {
    const { addToast, updateToast } = useToast();

    const handleClick = async () => {
      const toastId = addToast({
        type: "info",
        title: "已开始生成参考音色",
        duration: 2500,
      });
      try {
        await generateVoiceReference(props.stageId, props.voiceDescription);
        props.onStarted?.(props.stageId);
      } catch (err: any) {
        const detail = err?.detail || err?.message || "";
        if (err?.status === 409 || detail.includes("已有音声生成任务")) {
          updateToast(toastId, {
            type: "warning",
            title: "已有音声生成任务进行中",
            message: "请等待当前任务完成后再试",
            duration: 4000,
          });
        } else {
          updateToast(toastId, {
            type: "error",
            title: "音色生成失败",
            message: detail || undefined,
            duration: 3000,
          });
        }
      }
    };

    return () => (
      <Button
        size="sm"
        variant="secondary"
        disabled={props.isGenerating}
        onClick={handleClick}
      >
        <PhSparkle size={10} />
        {props.isGenerating ? "生成中..." : "生成参考音色音频"}
      </Button>
    );
  },
});

const StageEditCard = defineComponent({
  name: "StageEditCard",
  props: {
    stage: { type: Object as PropType<CharacterStageInfo>, default: undefined },
    characterId: { type: Number, required: true },
    chapters: {
      type: Array as PropType<ChapterInfo[]>,
      default: () => [],
    },
    onSave: { type: Function as PropType<() => void>, required: true },
    onCancel: { type: Function as PropType<() => void>, required: true },
  },
  setup(props) {
    const form = reactive({
      stage_name: props.stage?.stage_name || "",
      alias_name: props.stage?.alias_name || "",
      gender: props.stage?.gender || "",
      chapter_index:
        props.stage?.chapter_index != null ? props.stage.chapter_index : -1,
      age_Description: props.stage?.age_Description || "",
      appearance_description: props.stage?.appearance_description || "",
      profile: props.stage?.profile || "",
      voice_description: props.stage?.voice_description || "",
    });
    const { addToast } = useToast();

    const handleSave = async () => {
      if (!form.stage_name.trim()) {
        addToast({ type: "warning", title: "请输入阶段名称", duration: 2000 });
        return;
      }
      try {
        if (props.stage) {
          await updateCharacterStage(props.stage.id, { ...form });
        } else {
          await createCharacterStage(props.characterId, { ...form });
        }
        addToast({ type: "success", title: "阶段已保存", duration: 2000 });
        props.onSave();
      } catch {
        addToast({ type: "error", title: "保存失败", duration: 3000 });
      }
    };

    const input = (
      key: keyof typeof form,
      placeholder: string,
    ) => (
      <input
        class="edit-input"
        value={form[key] as string}
        onInput={(e) => (form[key] = (e.target as HTMLInputElement).value as never)}
        placeholder={placeholder}
      />
    );

    const textarea = (key: keyof typeof form, placeholder: string) => (
      <textarea
        class="edit-input"
        value={form[key] as string}
        onInput={(e) => (form[key] = (e.target as HTMLTextAreaElement).value as never)}
        placeholder={placeholder}
        rows={2}
      />
    );

    const field = (label: string, control: VNode) => (
      <label class="edit-field">
        <span class="edit-field-label">{label}</span>
        {control}
      </label>
    );

    const onFormKeydown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        props.onCancel();
      } else if (
        e.key === "Enter" &&
        (e.target as HTMLElement).tagName !== "TEXTAREA"
      ) {
        e.preventDefault();
        handleSave();
      }
    };

    return () => (
      <div class="char-stage-edit" onKeydown={onFormKeydown}>
        <div class="edit-form">
          <div class="edit-group">
            <span class="edit-group-title">基本信息</span>
            <div class="edit-grid edit-grid-2">
              {field("阶段名称", input("stage_name", "如：初登场 / 黑化后"))}
              {field("别名 / 昵称", input("alias_name", "此阶段的称呼"))}
            </div>
            <div class="edit-grid edit-grid-2">
              {field("性别", input("gender", "如：女"))}
              {field(
                "登场章节",
                <select
                  class="edit-input"
                  value={form.chapter_index}
                  onChange={(e) =>
                    (form.chapter_index = Number(
                      (e.target as HTMLSelectElement).value,
                    ))
                  }
                >
                  <option value={-1}>未指定章节</option>
                  {props.chapters.map((ch) => (
                    <option key={ch.id} value={ch.chapter_index + 1}>
                      第{ch.chapter_index + 1}章
                      {ch.title ? ` · ${ch.title}` : ""}
                    </option>
                  ))}
                </select>,
              )}
            </div>
          </div>
          <div class="edit-group">
            <span class="edit-group-title">人物设定</span>
            {field("年龄", input("age_Description", "如：十八岁 / 二十出头"))}
            {field("侧写", textarea("profile", "职业 / 身份 / 背景梗概"))}
            {field("外观", textarea("appearance_description", "容貌 / 服饰 / 身形"))}
          </div>
          <div class="edit-group">
            <span class="edit-group-title">声音</span>
            {field(
              "声音描述",
              textarea("voice_description", "音色 / 语速 / 情绪基调，用于生成参考音色"),
            )}
          </div>
        </div>
        <div class="edit-actions">
          <span class="edit-kbd-hint">Esc 取消</span>
          <Button size="sm" variant="ghost" onClick={props.onCancel}>
            取消
          </Button>
          <Button size="sm" onClick={handleSave}>
            <PhCheck size={12} /> 保存
          </Button>
        </div>
      </div>
    );
  },
});

export default defineComponent({
  name: "CharacterPanel",
  props: {
    character: { type: Object as PropType<CharacterInfo>, required: true },
    chapters: {
      type: Array as PropType<ChapterInfo[]>,
      default: () => [],
    },
    onRefresh: { type: Function as PropType<() => void>, required: true },
  },
  setup(props) {
    const editing = ref(false);
    const stages = ref<CharacterStageInfo[]>([]);
    const stagesOpen = ref(true);
    const editingStageId = ref<number | null>(null);
    const newStageOpen = ref(false);
    const generatingStageId = ref<number | null>(null);
    const genStatus = ref<"queued" | "processing" | null>(null);
    const genQueueWaiting = ref(0);
    const { addToast, updateToast } = useToast();
    const { confirm } = useConfirm();
    const editData = reactive({
      character_name: props.character.character_name,
      gender: props.character.gender || "",
      role: props.character.role || "",
    });

    const loadStages = () => {
      listCharacterStages(props.character.id)
        .then((data) => (stages.value = data))
        .catch(() => {});
    };

    onMounted(() => {
      loadStages();
      getVoiceGeneratingStatus()
        .then((res) => {
          genStatus.value = res.data?.Status ?? null;
          genQueueWaiting.value = res.data?.Queue?.waiting ?? 0;
          if (res.data?.Generating && res.data.StageId != null) {
            generatingStageId.value = res.data.StageId;
          }
        })
        .catch(() => {});
    });
    watch(
      () => props.character.id,
      () => loadStages(),
    );

    watch(generatingStageId, (id, _old, onCleanup) => {
      if (!id) return;
      let cancelled = false;
      const poll = async () => {
        try {
          const res = await getVoiceGeneratingStatus();
          if (cancelled) return;
          if (!res.data?.Generating) {
            generatingStageId.value = null;
            genStatus.value = null;
            genQueueWaiting.value = 0;
            if (res.data?.Error) {
              addToast({
                type: "error",
                title: "音色生成失败",
                message: res.data.Error,
                duration: 3000,
              });
            } else {
              addToast({
                type: "success",
                title: "参考音色已生成",
                duration: 3000,
              });
            }
            loadStages();
          } else {
            genStatus.value = res.data.Status ?? null;
            genQueueWaiting.value = res.data.Queue?.waiting ?? 0;
          }
        } catch {}
      };
      const interval = setInterval(poll, 1500);
      onCleanup(() => {
        cancelled = true;
        clearInterval(interval);
      });
    });

    const handleSave = async () => {
      try {
        await updateCharacter(props.character.id, {
          character_name: editData.character_name,
          gender: editData.gender,
          role: editData.role,
        });
        editing.value = false;
        addToast({ type: "success", title: "角色已保存", duration: 2000 });
        props.onRefresh();
      } catch {
        addToast({ type: "error", title: "保存失败", duration: 3000 });
      }
    };

    const handleDelete = async () => {
      const ok = await confirm({
        title: "删除角色",
        message: `确定要删除角色「${props.character.character_name}」吗？其全部阶段与参考音频将一并删除，不可恢复。`,
        danger: true,
        confirmText: "确认删除",
      });
      if (!ok) return;
      try {
        await deleteCharacter(props.character.id);
        addToast({
          type: "success",
          title: `已删除角色「${props.character.character_name}」`,
          duration: 2000,
        });
        props.onRefresh();
      } catch {
        addToast({ type: "error", title: "删除失败", duration: 3000 });
      }
    };

    const handleRegenVoice = async (stage: CharacterStageInfo) => {
      try {
        const res = await getVoiceGeneratingStatus();
        if (res.data?.Generating) {
          addToast({
            type: "warning",
            title: "已有音声生成任务进行中",
            message: "请等待当前任务完成后再试",
            duration: 4000,
          });
          return;
        }
      } catch {}

      generatingStageId.value = stage.id;
      const toastId = addToast({
        type: "info",
        title: "已开始重新生成参考音色",
        duration: 2500,
      });
      if (stage.voice_path) {
        try {
          await deleteStageVoiceReference(stage.id);
        } catch {
          updateToast(toastId, {
            type: "error",
            title: "删除旧音频失败",
            duration: 3000,
          });
          generatingStageId.value = null;
          return;
        }
      }
      generateVoiceReference(stage.id, stage.voice_description)
        .catch((err: any) => {
          const detail = err?.detail || err?.message || "";
          updateToast(toastId, {
            type: "error",
            title: "重新生成失败",
            message: detail || undefined,
            duration: 3000,
          });
          generatingStageId.value = null;
        });
    };

    const handleDeleteVoice = async (stageId: number) => {
      const ok = await confirm({
        title: "删除参考音频",
        message: "确定要删除该阶段的参考音频吗？删除后可重新生成。",
        danger: true,
        confirmText: "确认删除",
      });
      if (!ok) return;
      try {
        await deleteStageVoiceReference(stageId);
        addToast({ type: "success", title: "参考音频已删除", duration: 2000 });
        loadStages();
      } catch {
        addToast({ type: "error", title: "删除失败", duration: 3000 });
      }
    };

    const handleDeleteStage = async (stageId: number) => {
      const ok = await confirm({
        title: "删除阶段",
        message: "确定要删除该角色阶段吗？阶段资料与参考音频将一并删除，不可恢复。",
        danger: true,
        confirmText: "确认删除",
      });
      if (!ok) return;
      try {
        await deleteCharacterStage(stageId);
        addToast({ type: "success", title: "阶段已删除", duration: 2000 });
        loadStages();
      } catch {
        addToast({ type: "error", title: "删除失败", duration: 3000 });
      }
    };

    return () => {
      const c = props.character;
      const roleInfo = ROLE_LABELS[c.role] || null;

      if (editing.value) {
        return (
          <div class="character-panel character-panel-editing">
            <div class="character-info">
              <div
                class="edit-form"
                onKeydown={(e) => {
                  if (e.key === "Escape") {
                    e.stopPropagation();
                    editing.value = false;
                  } else if (
                    e.key === "Enter" &&
                    (e.target as HTMLElement).tagName !== "TEXTAREA"
                  ) {
                    e.preventDefault();
                    handleSave();
                  }
                }}
              >
                <div class="edit-grid edit-grid-3">
                  <label class="edit-field">
                    <span class="edit-field-label">角色名</span>
                    <input
                      class="edit-input"
                      value={editData.character_name}
                      onInput={(e) =>
                        (editData.character_name = (e.target as HTMLInputElement).value)
                      }
                      placeholder="角色姓名"
                    />
                  </label>
                  <label class="edit-field">
                    <span class="edit-field-label">性别</span>
                    <input
                      class="edit-input"
                      value={editData.gender}
                      onInput={(e) =>
                        (editData.gender = (e.target as HTMLInputElement).value)
                      }
                      placeholder="如：女"
                    />
                  </label>
                  <label class="edit-field">
                    <span class="edit-field-label">角色定位</span>
                    <select
                      class="edit-input"
                      value={editData.role}
                      onChange={(e) =>
                        (editData.role = (e.target as HTMLSelectElement).value)
                      }
                    >
                      <option value="">未设定</option>
                      <option value="protagonist">主角</option>
                      <option value="antagonist">反派</option>
                      <option value="supporting">配角</option>
                      <option value="extra">龙套</option>
                    </select>
                  </label>
                </div>
              </div>
              <div class="edit-actions">
                <span class="edit-kbd-hint">Esc 取消</span>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => (editing.value = false)}
                >
                  取消
                </Button>
                <Button size="sm" onClick={handleSave}>
                  <PhCheck size={12} /> 保存
                </Button>
              </div>
            </div>
          </div>
        );
      }

      const initialStage =
        stages.value.find((s) => s.stage_name === "初登场") || stages.value[0];

      return (
        <div class="character-panel">
          <div class="character-info">
            <div class="character-name">
              <PhUser size={14} /> {c.character_name}
              {initialStage?.alias_name && (
                <span class="char-alias">({initialStage.alias_name})</span>
              )}
              {roleInfo && (
                <Tag variant={roleInfo.variant} size="sm">
                  {roleInfo.label}
                </Tag>
              )}
              <button
                class="icon-btn"
                disabled={generatingStageId.value !== null}
                onClick={() => {
                  editing.value = true;
                  editData.character_name = c.character_name;
                  editData.gender = c.gender || "";
                  editData.role = c.role || "";
                }}
              >
                <PhPencilSimple size={12} />
              </button>
              <button
                class="icon-btn"
                style={{ color: "var(--color-error)" }}
                disabled={generatingStageId.value !== null}
                title="删除角色"
                onClick={handleDelete}
              >
                <PhTrash size={12} />
              </button>
            </div>
            {initialStage && (
              <>
                <div class="char-meta-row">
                  {initialStage.gender && (
                    <span class="char-meta-item">{initialStage.gender}</span>
                  )}
                  {initialStage.age_Description && (
                    <span class="char-meta-item">
                      {initialStage.age_Description}
                    </span>
                  )}
                </div>
                {initialStage.profile && (
                  <div class="character-desc">{initialStage.profile}</div>
                )}
                {initialStage.appearance_description && (
                  <div class="char-field">
                    <b>外观：</b>
                    {initialStage.appearance_description}
                  </div>
                )}
                {initialStage.voice_description && (
                  <div class="character-voice-desc">
                    <PhSpeakerHigh size={10} /> {initialStage.voice_description}
                  </div>
                )}
              </>
            )}

            <div class="char-stages-section">
              <button
                class="char-stages-toggle"
                onClick={() => {
                  if (!stagesOpen.value && !generatingStageId.value) loadStages();
                  stagesOpen.value = !stagesOpen.value;
                }}
              >
                {stagesOpen.value ? (
                  <PhCaretUp size={12} />
                ) : (
                  <PhCaretDown size={12} />
                )}
                角色阶段 ({stages.value.length})
              </button>
              {stagesOpen.value && (
                <div class="char-stages-list">
                  {stages.value.map((s) =>
                    editingStageId.value === s.id ? (
                      <StageEditCard
                        key={s.id}
                        stage={s}
                        characterId={props.character.id}
                        chapters={props.chapters}
                        onSave={() => {
                          editingStageId.value = null;
                          loadStages();
                        }}
                        onCancel={() => (editingStageId.value = null)}
                      />
                    ) : (
                      <div key={s.id} class="char-stage-item">
                        <div class="char-stage-header">
                          <span class="char-stage-label">{s.stage_name}</span>
                          {s.chapter_index >= 1 && (
                            <span class="char-stage-trigger">
                              第 {s.chapter_index} 章登场
                            </span>
                          )}
                          <button
                            class="icon-btn"
                            disabled={generatingStageId.value !== null}
                            onClick={() => (editingStageId.value = s.id)}
                          >
                            <PhPencilSimple size={10} />
                          </button>
                          <button
                            class="icon-btn"
                            style={{ color: "var(--color-error)" }}
                            disabled={generatingStageId.value !== null}
                            onClick={() => handleDeleteStage(s.id)}
                          >
                            <PhX size={10} />
                          </button>
                        </div>
                        <div class="char-meta-row">
                          {s.alias_name && (
                            <span class="char-meta-item">
                              <b>别名：</b>
                              {s.alias_name}
                            </span>
                          )}
                          {s.gender && (
                            <span class="char-meta-item">{s.gender}</span>
                          )}
                          {s.age_Description && (
                            <span class="char-meta-item">{s.age_Description}</span>
                          )}
                        </div>
                        {s.profile && (
                          <div class="char-stage-desc">{s.profile}</div>
                        )}
                        <div class="char-stage-fields">
                          {s.appearance_description && (
                            <span>
                              <b>外观：</b>
                              {s.appearance_description}
                            </span>
                          )}
                          {s.voice_description && (
                            <span>
                              <b>声音：</b>
                              {s.voice_description}
                            </span>
                          )}
                        </div>
                        <div class="char-stage-voice">
                          {s.voice_description && (
                            <span class="char-stage-voice-desc">
                              <PhSpeakerHigh size={10} /> {s.voice_description}
                            </span>
                          )}
                          {s.voice_path && generatingStageId.value !== s.id ? (
                            <div class="char-stage-audio-row">
                              <MiniAudioPlayer
                                src={getStageVoiceAudioUrl(s.id)}
                                playerId={String(s.id)}
                              />
                              <button
                                class="icon-btn"
                                title="重新生成"
                                disabled={generatingStageId.value !== null}
                                onClick={() => handleRegenVoice(s)}
                              >
                                <PhSparkle size={10} />
                              </button>
                              <button
                                class="icon-btn"
                                style={{ color: "var(--color-error)" }}
                                title="删除音频"
                                disabled={generatingStageId.value !== null}
                                onClick={() => handleDeleteVoice(s.id)}
                              >
                                <PhTrash size={10} />
                              </button>
                            </div>
                          ) : generatingStageId.value === s.id ? (
                            <div class="char-stage-generating">
                              <span class="generating-pulse-dot" />
                              <span class="generating-text">
                                {genStatus.value === "queued"
                                  ? `GPU 忙，排队等待中${genQueueWaiting.value > 1 ? `（前方 ${genQueueWaiting.value - 1} 个）` : ""}`
                                  : "正在生成音色..."}
                              </span>
                              <div class="generating-bar-track">
                                <div class="generating-bar-fill" />
                              </div>
                            </div>
                          ) : s.voice_description ? (
                            <StageVoiceGenButton
                              stageId={s.id}
                              voiceDescription={s.voice_description}
                              isGenerating={generatingStageId.value === s.id}
                              onStarted={(id) => (generatingStageId.value = id)}
                            />
                          ) : null}
                        </div>
                      </div>
                    ),
                  )}
                  {newStageOpen.value ? (
                    <StageEditCard
                      characterId={props.character.id}
                      chapters={props.chapters}
                      onSave={() => {
                        newStageOpen.value = false;
                        loadStages();
                      }}
                      onCancel={() => (newStageOpen.value = false)}
                    />
                  ) : (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => (newStageOpen.value = true)}
                    >
                      <PhPlus size={10} /> 新增阶段
                    </Button>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      );
    };
  },
});
