import {
  defineComponent,
  ref,
  reactive,
  computed,
  watch,
  onMounted,
  onBeforeUnmount,
  type PropType,
} from "vue";
import {
  Button,
  Tag,
  Input,
  Modal,
  CustomDropdown,
  VirtualList,
  PageLoader,
} from "../components";
import { useToast } from "../components/Toast";
import { useConfirm } from "../components/ConfirmDialog";
import { useResourceStore } from "../stores/resources";
import {
  uploadResource,
  deleteResource,
  batchDeleteResources,
  updateResource,
  getResourceFileUrl,
  type ResourceItem,
} from "../api";
import gsap from "gsap";
import {
  PhMusicNote,
  PhSpeakerHigh,
  PhPlus,
  PhTrash,
  PhUploadSimple,
  PhPlay,
  PhPause,
  PhWaveform,
  PhPencilSimple,
  PhCheckSquare,
  PhSquare,
} from "@phosphor-icons/vue";

function useAudioPlayer() {
  let audioEl: HTMLAudioElement | null = null;
  let animFrame: number | null = null;
  const playingId = ref<number | null>(null);
  const currentTime = ref<Record<number, number>>({});
  const duration = ref<Record<number, number>>({});
  const seeking = ref(false);
  const loadedId = ref<number | null>(null);

  const startTick = (id: number) => {
    const tick = () => {
      if (audioEl && !audioEl.paused) {
        currentTime.value = { ...currentTime.value, [id]: audioEl.currentTime };
        animFrame = requestAnimationFrame(tick);
      }
    };
    animFrame = requestAnimationFrame(tick);
  };

  const stopTick = () => {
    if (animFrame != null) {
      cancelAnimationFrame(animFrame);
      animFrame = null;
    }
  };

  const play = (id: number, filePath?: string) => {
    if (!filePath) return;

    if (playingId.value === id && audioEl && !audioEl.paused) {
      audioEl.pause();
      stopTick();
      playingId.value = null;
      return;
    }

    if (audioEl) {
      audioEl.pause();
      stopTick();
    }

    const audio = new Audio();
    audio.preload = "metadata";
    audioEl = audio;
    loadedId.value = id;

    audio.addEventListener("loadedmetadata", () => {
      const dur = audio.duration;
      if (dur && isFinite(dur)) {
        duration.value = { ...duration.value, [id]: dur };
      }
    });

    audio.addEventListener("durationchange", () => {
      const dur = audio.duration;
      if (dur && isFinite(dur)) {
        duration.value = { ...duration.value, [id]: dur };
      }
    });

    audio.addEventListener("ended", () => {
      stopTick();
      playingId.value = null;
      currentTime.value = { ...currentTime.value, [id]: 0 };
    });

    audio.addEventListener("pause", () => {
      stopTick();
    });

    audio.src = filePath;
    audio
      .play()
      .then(() => {
        playingId.value = id;
        startTick(id);
      })
      .catch(() => {});
  };

  const stop = () => {
    if (audioEl) {
      audioEl.pause();
      audioEl.currentTime = 0;
    }
    stopTick();
    playingId.value = null;
    currentTime.value = {};
  };

  const seekToTime = (id: number, timeSeconds: number) => {
    if (!audioEl || loadedId.value !== id) return;
    audioEl.currentTime = timeSeconds;
    currentTime.value = { ...currentTime.value, [id]: timeSeconds };
  };

  const seekToPercent = (id: number, percent: number) => {
    const dur = duration.value[id];
    if (!dur || !isFinite(dur)) return;
    seekToTime(id, (percent / 100) * dur);
  };

  const onSeekStart = () => {
    seeking.value = true;
    stopTick();
  };

  const onSeekEnd = (id: number, percent: number) => {
    seeking.value = false;
    seekToPercent(id, percent);
    if (audioEl && playingId.value === id) {
      audioEl
        .play()
        .then(() => startTick(id))
        .catch(() => {});
    } else if (audioEl && loadedId.value === id) {
      currentTime.value = { ...currentTime.value, [id]: audioEl.currentTime };
    }
  };

  onBeforeUnmount(() => {
    stopTick();
    if (audioEl) audioEl.pause();
  });

  return {
    playingId,
    currentTime,
    duration,
    seeking,
    play,
    stop,
    seekToPercent,
    seekToTime,
    onSeekStart,
    onSeekEnd,
  };
}

function formatTime(seconds: number): string {
  if (!seconds || !isFinite(seconds)) return "0:00.000";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  const ms = Math.floor((seconds % 1) * 1000);
  return `${m}:${s.toString().padStart(2, "0")}.${ms.toString().padStart(3, "0")}`;
}

function formatTimeShort(seconds: number): string {
  if (!seconds || !isFinite(seconds)) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

const AudioPlayerBar = defineComponent({
  name: "AudioPlayerBar",
  props: {
    resourceId: { type: Number, required: true },
    isPlaying: { type: Boolean, default: false },
    hasAudio: { type: Boolean, default: false },
    audioUrl: { type: String, default: undefined },
    currentTime: { type: Number, default: 0 },
    duration: { type: Number, default: 0 },
    seeking: { type: Boolean, default: false },
    onPlay: { type: Function as PropType<() => void>, required: true },
    onSeekStart: { type: Function as PropType<() => void>, required: true },
    onSeekEnd: {
      type: Function as PropType<(id: number, percent: number) => void>,
      required: true,
    },
    seekToPercent: {
      type: Function as PropType<(id: number, percent: number) => void>,
      required: true,
    },
  },
  setup(props) {
    const trackEl = ref<HTMLDivElement | null>(null);
    const dragging = ref(false);
    const dragPercent = ref(0);

    const percent = computed(() =>
      dragging.value || props.seeking
        ? dragPercent.value
        : props.duration > 0
          ? (props.currentTime / props.duration) * 100
          : 0,
    );

    const isPlayingOrDragging = computed(
      () => props.isPlaying || dragging.value || props.seeking,
    );

    const calcPercent = (clientX: number): number => {
      if (!trackEl.value) return 0;
      const rect = trackEl.value.getBoundingClientRect();
      const x = clientX - rect.left;
      return Math.max(0, Math.min(100, (x / rect.width) * 100));
    };

    const handleMousedown = (e: MouseEvent) => {
      if (!props.hasAudio) return;
      e.preventDefault();
      dragPercent.value = calcPercent(e.clientX);
      dragging.value = true;
      props.onSeekStart();
    };

    const handleTouchstart = (e: TouchEvent) => {
      if (!props.hasAudio) return;
      const touch = e.touches[0];
      dragPercent.value = calcPercent(touch.clientX);
      dragging.value = true;
      props.onSeekStart();
    };

    watch(dragging, (d, _old, onCleanup) => {
      if (!d) return;

      const handleMouseMove = (e: MouseEvent) => {
        dragPercent.value = calcPercent(e.clientX);
      };
      const handleMouseUp = (e: MouseEvent) => {
        dragging.value = false;
        props.onSeekEnd(props.resourceId, calcPercent(e.clientX));
      };
      const handleTouchMove = (e: TouchEvent) => {
        const touch = e.touches[0];
        dragPercent.value = calcPercent(touch.clientX);
      };
      const handleTouchEnd = (e: TouchEvent) => {
        const touch = e.changedTouches[0];
        dragging.value = false;
        props.onSeekEnd(props.resourceId, calcPercent(touch.clientX));
      };

      window.addEventListener("mousemove", handleMouseMove);
      window.addEventListener("mouseup", handleMouseUp);
      window.addEventListener("touchmove", handleTouchMove);
      window.addEventListener("touchend", handleTouchEnd);
      onCleanup(() => {
        window.removeEventListener("mousemove", handleMouseMove);
        window.removeEventListener("mouseup", handleMouseUp);
        window.removeEventListener("touchmove", handleTouchMove);
        window.removeEventListener("touchend", handleTouchEnd);
      });
    });

    const handleClick = (e: MouseEvent) => {
      if (!props.hasAudio || dragging.value) return;
      props.seekToPercent(props.resourceId, calcPercent(e.clientX));
    };

    return () => (
      <div
        class="audio-player-bar"
        style={{
          display: "flex",
          alignItems: "center",
          gap: "var(--space-sm)",
          marginTop: "10px",
          paddingTop: "10px",
          borderTop: "1px solid var(--color-border-light)",
        }}
      >
        <button
          class={`audio-play-btn ${!props.hasAudio ? "audio-play-btn-disabled" : ""}`}
          onClick={props.onPlay}
          disabled={!props.hasAudio}
          title={!props.hasAudio ? "未上传音频文件" : props.isPlaying ? "暂停" : "播放"}
        >
          {props.isPlaying ? (
            <PhPause size={14} weight="fill" />
          ) : (
            <PhPlay size={14} weight="fill" />
          )}
        </button>

        <span class="audio-time audio-time-current">
          {props.hasAudio ? formatTimeShort(props.currentTime) : "0:00"}
        </span>

        <div
          ref={trackEl}
          class={`audio-progress-track ${!props.hasAudio ? "audio-progress-disabled" : ""} ${dragging.value ? "audio-progress-dragging" : ""}`}
          onMousedown={handleMousedown}
          onTouchstart={handleTouchstart}
          onClick={handleClick}
        >
          <div
            class="audio-progress-fill"
            style={{
              width: `${percent.value}%`,
              transition: isPlayingOrDragging.value ? "none" : "width 0.2s ease-out",
            }}
          />
          <div
            class={`audio-progress-thumb ${dragging.value ? "audio-progress-thumb-active" : ""}`}
            style={{
              left: `${percent.value}%`,
              transition: isPlayingOrDragging.value
                ? "transform 0.15s cubic-bezier(0.16, 1, 0.3, 1)"
                : "left 0.2s ease-out, transform 0.15s cubic-bezier(0.16, 1, 0.3, 1)",
            }}
          />
        </div>

        <span class="audio-time audio-time-duration">
          {props.hasAudio && props.duration > 0 ? formatTimeShort(props.duration) : "--:--"}
        </span>

        {props.isPlaying && (
          <div class="audio-waveform">
            <PhWaveform size={14} weight="light" />
          </div>
        )}
      </div>
    );
  },
});

export default defineComponent({
  name: "ResourcesPage",
  setup() {
    const { confirm } = useConfirm();
    const resStore = useResourceStore();
    const resources = computed(() => resStore.resources);
    const filter = computed(() => resStore.filter);
    const total = computed(() => resStore.total);
    const loadingMore = computed(() => resStore.loadingMore);
    const showAdd = ref(false);
    const newItem = reactive({
      name: "",
      type: "bgm" as "sfx" | "bgm",
      description: "",
    });
    const uploadFile = ref<File | null>(null);
    const editingId = ref<number | null>(null);
    const editData = reactive({ audio_name: "", description: "" });
    const loading = computed(() => resStore.loading);
    const selectMode = ref(false);
    const selectedIds = ref<Set<number>>(new Set());
    const fileInputEl = ref<HTMLInputElement | null>(null);
    const tabEls: (HTMLButtonElement | null)[] = [];
    const tabIndicatorEl = ref<HTMLDivElement | null>(null);
    const { addToast, updateToast } = useToast();
    const {
      playingId,
      currentTime,
      duration,
      seeking,
      play,
      stop,
      seekToPercent,
      onSeekStart,
      onSeekEnd,
    } = useAudioPlayer();

    const loadResources = () => resStore.loadResources();
    const setFilter = resStore.setFilter;

    const loadMore = () => {
      if (loadingMore.value || resources.value.length >= total.value) return;
      resStore.loadResources(true);
    };

    onMounted(() => {
      loadResources();
      moveIndicator();
    });

    const moveIndicator = () => {
      const idx = ["all", "bgm", "sfx"].indexOf(filter.value);
      const btn = tabEls[idx];
      const indicator = tabIndicatorEl.value;
      if (btn && indicator) {
        gsap.to(indicator, {
          x: btn.offsetLeft,
          width: btn.offsetWidth,
          duration: 0.3,
          ease: "power2.out",
        });
      }
    };

    watch(filter, moveIndicator, { flush: "post" });

    const filtered = computed(() => resources.value);

    const resetAddForm = () => {
      newItem.name = "";
      newItem.type = "bgm";
      newItem.description = "";
      uploadFile.value = null;
    };

    const handleAdd = async () => {
      if (!newItem.name.trim()) {
        addToast({ type: "warning", title: "请输入音频名称", duration: 3000 });
        return;
      }
      if (!newItem.description.trim()) {
        addToast({ type: "warning", title: "请输入音频描述", duration: 3000 });
        return;
      }
      if (!uploadFile.value) {
        addToast({ type: "warning", title: "请上传音频文件", duration: 3000 });
        return;
      }

      const toastId = addToast({
        type: "info",
        title: "正在上传",
        message: uploadFile.value.name,
        duration: 0,
        progress: 0,
      });

      try {
        const newResource = await uploadResource(
          { audio_name: newItem.name, audiotype: newItem.type, description: newItem.description },
          uploadFile.value,
          (pct) => updateToast(toastId, { progress: pct }),
        );

        updateToast(toastId, {
          type: "success",
          title: "上传成功",
          message: newItem.name,
          progress: 100,
          duration: 3000,
        });

        resetAddForm();
        showAdd.value = false;
        if (newResource) {
          resStore.addLocal(newResource);
        } else {
          loadResources();
        }
      } catch (e: any) {
        updateToast(toastId, {
          type: "error",
          title: "上传失败",
          message: e.message || "添加失败",
          progress: undefined,
          duration: 5000,
        });
      }
    };

    const handleDelete = async (id: number) => {
      const resource = resources.value.find((r) => r.id === id);
      const ok = await confirm({
        title: "删除音频",
        message: `确定要删除音频「${resource?.Audio_name || String(id)}」吗？音频文件将一并删除，不可恢复。`,
        danger: true,
        confirmText: "确认删除",
      });
      if (!ok) return;
      if (playingId.value === id) stop();
      try {
        await deleteResource(id);
        resStore.removeLocal([id]);
        addToast({
          type: "success",
          title: "已删除",
          message: resource?.Audio_name || String(id),
          duration: 3000,
        });
      } catch (e: any) {
        addToast({
          type: "error",
          title: "删除失败",
          message: e.message,
          duration: 4000,
        });
      }
    };

    const handleEdit = (r: ResourceItem) => {
      editingId.value = r.id;
      editData.audio_name = r.Audio_name;
      editData.description = r.description;
    };

    const handleSaveEdit = async (id: number) => {
      try {
        const result = await updateResource(id, { ...editData });
        editingId.value = null;
        if (result.data.Resource) {
          resStore.replaceLocal(result.data.Resource);
        }
        addToast({ type: "success", title: "保存成功", duration: 3000 });
      } catch (e: any) {
        addToast({
          type: "error",
          title: "保存失败",
          message: e.message,
          duration: 4000,
        });
      }
    };

    const getAudioUrl = (r: ResourceItem) => getResourceFileUrl(r.id);

    const toggleSelect = (id: number) => {
      const next = new Set(selectedIds.value);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      selectedIds.value = next;
    };

    const selectAll = () => {
      selectedIds.value = new Set(filtered.value.map((r) => r.id));
    };

    const deselectAll = () => {
      selectedIds.value = new Set();
    };

    const exitSelectMode = () => {
      selectMode.value = false;
      selectedIds.value = new Set();
    };

    const handleBatchDelete = async () => {
      if (selectedIds.value.size === 0) return;
      const count = selectedIds.value.size;
      const ok = await confirm({
        title: "批量删除音频",
        message: `确定要删除选中的 ${count} 项音频吗？音频文件将一并删除，不可恢复。`,
        danger: true,
        confirmText: "确认删除",
      });
      if (!ok) return;
      const ids = [...selectedIds.value];
      if (playingId.value !== null && selectedIds.value.has(playingId.value)) stop();
      const toastId = addToast({
        type: "info",
        title: `正在删除 ${count} 项音频`,
        duration: 0,
        progress: 0,
      });
      try {
        await batchDeleteResources(ids);
        resStore.removeLocal(ids);
        updateToast(toastId, {
          type: "success",
          title: `已删除 ${count} 项音频`,
          progress: 100,
          duration: 3000,
        });
      } catch (e: any) {
        updateToast(toastId, {
          type: "error",
          title: "批量删除失败",
          message: e.message,
          progress: 100,
          duration: 4000,
        });
      }
      exitSelectMode();
    };

    return () => (
      <PageLoader loading={loading.value} text="加载音频库...">
        <div
          class="page-container"
          style={{ display: "flex", flexDirection: "column", overflow: "hidden" }}
        >
          <div class="page-header">
            <h1 class="page-title">音频库</h1>
            <div
              style={{
                display: "flex",
                gap: "var(--space-sm)",
                alignItems: "center",
              }}
            >
              {selectMode.value ? (
                <>
                  <button class="provider-batch-btn" onClick={selectAll}>
                    <PhCheckSquare size={13} weight="light" /> 全选
                  </button>
                  <button class="provider-batch-btn" onClick={deselectAll}>
                    <PhSquare size={13} weight="light" /> 取消
                  </button>
                  <button
                    class="provider-batch-btn provider-batch-delete"
                    onClick={handleBatchDelete}
                    disabled={selectedIds.value.size === 0}
                  >
                    <PhTrash size={13} weight="light" /> 删除({selectedIds.value.size})
                  </button>
                  <button class="provider-batch-btn" onClick={exitSelectMode}>
                    取消选择
                  </button>
                </>
              ) : (
                <>
                  <div style={{ display: "flex", gap: 0, position: "relative" }}>
                    {(["all", "bgm", "sfx"] as const).map((f, i) => (
                      <button
                        key={f}
                        ref={(el) => {
                          tabEls[i] = el as HTMLButtonElement | null;
                        }}
                        class={`tab-item ${filter.value === f ? "active" : ""}`}
                        style={{
                          borderBottom: "none",
                          padding: "5px 12px",
                          fontSize: "12px",
                        }}
                        onClick={() => setFilter(f)}
                      >
                        {f === "all" ? "全部" : f === "bgm" ? "BGM" : "音效"}
                      </button>
                    ))}
                    <div
                      ref={tabIndicatorEl}
                      style={{
                        position: "absolute",
                        bottom: 0,
                        height: "2px",
                        background: "var(--color-accent)",
                        borderRadius: "1px",
                      }}
                    />
                  </div>
                  {filtered.value.length > 0 && (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => (selectMode.value = true)}
                    >
                      批量管理
                    </Button>
                  )}
                  <Button
                    size="sm"
                    onClick={() => (showAdd.value = true)}
                    variant="secondary"
                  >
                    <PhPlus size={14} weight="bold" />
                    添加音频
                  </Button>
                </>
              )}
            </div>
          </div>

          <Modal
            open={showAdd.value}
            onClose={() => {
              showAdd.value = false;
              resetAddForm();
            }}
            title="添加新音频"
          >
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: "var(--space-md)",
              }}
            >
              <Input
                label="名称"
                placeholder="如：森林晨曦"
                value={newItem.name}
                onUpdate:value={(v: string) => (newItem.name = v)}
              />
              <div class="input-wrapper">
                <label class="input-label">类型</label>
                <CustomDropdown
                  value={newItem.type}
                  onUpdate:value={(v: string) => (newItem.type = v as "sfx" | "bgm")}
                  options={[
                    { value: "bgm", label: "BGM 背景音乐" },
                    { value: "sfx", label: "SFX 音效" },
                  ]}
                  placeholder="选择类型"
                />
              </div>
              <div class="input-wrapper" style={{ gridColumn: "1 / -1" }}>
                <label class="input-label">描述</label>
                <textarea
                  class="input-field input-textarea"
                  style={{
                    height: "80px",
                    minHeight: "80px",
                    maxHeight: "80px",
                    resize: "none",
                    overflowY: "auto",
                  }}
                  maxlength={500}
                  placeholder="用文字描述这段音频的氛围、场景、乐器等特征，供 Agent 选择使用..."
                  value={newItem.description}
                  onInput={(e) =>
                    (newItem.description = (e.target as HTMLTextAreaElement).value)
                  }
                />
              </div>
              <div class="input-wrapper">
                <label class="input-label">
                  音频文件 <span style={{ color: "var(--color-error)" }}>*</span>
                </label>
                <input
                  ref={fileInputEl}
                  type="file"
                  accept=".wav,.mp3,.ogg,.flac,.m4a,.aac"
                  style={{ display: "none" }}
                  onChange={(e) =>
                    (uploadFile.value =
                      (e.target as HTMLInputElement).files?.[0] || null)
                  }
                />
                <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => fileInputEl.value?.click()}
                  >
                    <PhUploadSimple size={14} weight="light" />
                    {uploadFile.value ? uploadFile.value.name : "选择文件"}
                  </Button>
                </div>
              </div>
              <div
                style={{
                  display: "flex",
                  alignItems: "flex-end",
                  gap: "var(--space-sm)",
                  gridColumn: "1 / -1",
                  justifyContent: "flex-end",
                }}
              >
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    showAdd.value = false;
                    resetAddForm();
                  }}
                >
                  取消
                </Button>
                <Button
                  size="sm"
                  onClick={handleAdd}
                  disabled={
                    !uploadFile.value ||
                    !newItem.name.trim() ||
                    !newItem.description.trim()
                  }
                >
                  保存
                </Button>
              </div>
            </div>
          </Modal>

          <div style={{ flex: 1, minHeight: 0 }}>
            {loading.value ? (
              <div class="empty-state">加载中...</div>
            ) : filtered.value.length === 0 ? (
              <div class="empty-state">
                <PhMusicNote size={32} weight="light" style={{ opacity: 0.3 }} />
                <div style={{ fontWeight: 500, marginBottom: "4px" }}>暂无音频</div>
              </div>
            ) : (
              <VirtualList
                data={filtered.value}
                hasMore={resources.value.length < total.value}
                loadingMore={loadingMore.value}
                onLoadMore={loadMore}
                totalCount={total.value}
                itemKey={(item: ResourceItem) => item.id}
                renderItem={(r: ResourceItem) => {
                  const isPlaying = playingId.value === r.id;
                  const audioUrl = getAudioUrl(r);
                  const hasAudio = !!audioUrl;
                  const isEditing = editingId.value === r.id;
                  const isSelected = selectedIds.value.has(r.id);

                  return (
                    <div style={{ padding: "2px 0" }}>
                      <div
                        class={`project-card resource-card ${selectMode.value && isSelected ? "resource-card-selected" : ""}`}
                        onClick={() => selectMode.value && toggleSelect(r.id)}
                        style={selectMode.value ? { cursor: "pointer" } : undefined}
                      >
                        <div
                          class="project-card-inner"
                          style={{
                            flexDirection: "column",
                            alignItems: "stretch",
                            gap: 0,
                          }}
                        >
                          <div
                            style={{
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "space-between",
                            }}
                          >
                            <div
                              style={{
                                display: "flex",
                                alignItems: "center",
                                gap: "var(--space-md)",
                                minWidth: 0,
                                flex: 1,
                              }}
                            >
                              {selectMode.value && (
                                <span style={{ flexShrink: 0 }}>
                                  {isSelected ? (
                                    <PhCheckSquare
                                      size={16}
                                      weight="fill"
                                      style={{ color: "var(--color-accent)" }}
                                    />
                                  ) : (
                                    <PhSquare size={16} weight="light" />
                                  )}
                                </span>
                              )}
                              <div
                                class="project-card-icon"
                                style={{
                                  background:
                                    r.audiotype === "bgm"
                                      ? "linear-gradient(135deg, rgba(217, 104, 48, 0.1), rgba(255, 170, 120, 0.12))"
                                      : "linear-gradient(135deg, rgba(68, 120, 168, 0.1), rgba(120, 170, 220, 0.12))",
                                  color:
                                    r.audiotype === "bgm"
                                      ? "var(--color-accent)"
                                      : "var(--color-info)",
                                }}
                              >
                                {r.audiotype === "bgm" ? (
                                  <PhMusicNote size={18} weight="light" />
                                ) : (
                                  <PhSpeakerHigh size={18} weight="light" />
                                )}
                              </div>
                              <div style={{ minWidth: 0, flex: 1 }}>
                                {isEditing ? (
                                  <div class="edit-form">
                                    <label class="edit-field">
                                      <span class="edit-field-label">名称</span>
                                      <input
                                        class="edit-input"
                                        value={editData.audio_name}
                                        onInput={(e) =>
                                          (editData.audio_name = (e.target as HTMLInputElement).value)
                                        }
                                        onKeydown={(e) => {
                                          if (e.key === "Enter") handleSaveEdit(r.id);
                                          else if (e.key === "Escape") editingId.value = null;
                                        }}
                                      />
                                    </label>
                                    <label class="edit-field">
                                      <span class="edit-field-label">描述</span>
                                      <textarea
                                        class="edit-input"
                                        rows={2}
                                        value={editData.description}
                                        onInput={(e) =>
                                          (editData.description = (
                                            e.target as HTMLTextAreaElement
                                          ).value)
                                        }
                                        onKeydown={(e) => {
                                          if (e.key === "Escape") editingId.value = null;
                                        }}
                                      />
                                    </label>
                                    <div class="edit-actions">
                                      <span class="edit-kbd-hint">Esc 取消</span>
                                      <Button
                                        size="sm"
                                        variant="ghost"
                                        onClick={(e: MouseEvent) => {
                                          e.stopPropagation();
                                          editingId.value = null;
                                        }}
                                      >
                                        取消
                                      </Button>
                                      <Button
                                        size="sm"
                                        onClick={(e: MouseEvent) => {
                                          e.stopPropagation();
                                          handleSaveEdit(r.id);
                                        }}
                                      >
                                        保存
                                      </Button>
                                    </div>
                                  </div>
                                ) : (
                                  <>
                                    <div
                                      style={{
                                        fontWeight: 500,
                                        fontSize: "13px",
                                        whiteSpace: "nowrap",
                                        overflow: "hidden",
                                        textOverflow: "ellipsis",
                                      }}
                                    >
                                      {r.Audio_name}
                                    </div>
                                    <div
                                      style={{
                                        fontSize: "12px",
                                        color: "var(--color-text-secondary)",
                                        marginTop: "2px",
                                        lineHeight: 1.5,
                                        display: "-webkit-box",
                                        WebkitLineClamp: 2,
                                        WebkitBoxOrient: "vertical",
                                        overflow: "hidden",
                                      }}
                                    >
                                      {r.description}
                                    </div>
                                    <div
                                      style={{
                                        display: "flex",
                                        gap: "4px",
                                        marginTop: "4px",
                                        flexWrap: "wrap",
                                      }}
                                    >
                                      <Tag
                                        size="sm"
                                        variant={r.audiotype === "bgm" ? "default" : "info"}
                                      >
                                        {r.audiotype === "bgm" ? "BGM" : "SFX"}
                                      </Tag>
                                    </div>
                                  </>
                                )}
                              </div>
                            </div>
                            <div
                              style={{
                                display: "flex",
                                alignItems: "center",
                                gap: "4px",
                                flexShrink: 0,
                              }}
                            >
                              {!isEditing && (
                                <>
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    onClick={(e: MouseEvent) => {
                                      e.stopPropagation();
                                      handleEdit(r);
                                    }}
                                  >
                                    <PhPencilSimple size={14} weight="light" />
                                  </Button>
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    onClick={(e: MouseEvent) => {
                                      e.stopPropagation();
                                      handleDelete(r.id);
                                    }}
                                  >
                                    <PhTrash size={14} weight="light" />
                                  </Button>
                                </>
                              )}
                            </div>
                          </div>
                          <AudioPlayerBar
                            resourceId={r.id}
                            isPlaying={isPlaying}
                            hasAudio={hasAudio}
                            audioUrl={audioUrl}
                            currentTime={currentTime.value[r.id] || 0}
                            duration={duration.value[r.id] || 0}
                            seeking={seeking.value}
                            onPlay={() => play(r.id, audioUrl)}
                            onSeekStart={onSeekStart}
                            onSeekEnd={onSeekEnd}
                            seekToPercent={seekToPercent}
                          />
                        </div>
                      </div>
                    </div>
                  );
                }}
              />
            )}
          </div>
        </div>
      </PageLoader>
    );
  },
});
