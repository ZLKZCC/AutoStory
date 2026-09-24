import { defineComponent, type PropType, ref, watch, onBeforeUnmount } from "vue";
import type { AudiobookAnswer, NarratorPayload } from "./types";
import MiniAudioPlayer from "../MiniAudioPlayer";
import { previewNarrator, NARRATOR_SAMPLE_DEFAULT } from "../../api/audiobook";
import { ApiError } from "../../api/client";
import { useChatStore } from "../../stores/chat";

export default defineComponent({
  name: "NarratorPanel",
  props: {
    payload: { type: Object as PropType<NarratorPayload>, required: true },
    callId: { type: String, default: "" },
    onSubmit: {
      type: Function as PropType<(answer: AudiobookAnswer) => void>,
      required: true,
    },
  },
  setup(props) {
    const chat = useChatStore();
    const callId = props.callId;
    const desc = ref(chat.getNarratorDraft(callId) || (props.payload.narrator_desc ?? "").trim());
    const activePreset = ref("");
    const previewUrl = ref("");
    const previewing = ref(false);
    const errorMsg = ref("");
    let disposed = false;

    const releasePreview = () => {
      if (previewUrl.value) {
        URL.revokeObjectURL(previewUrl.value);
        previewUrl.value = "";
      }
    };
    watch(desc, (v) => { releasePreview(); errorMsg.value = ""; chat.setNarratorDraft(callId, v); });
    onBeforeUnmount(() => { disposed = true; releasePreview(); });

    const pickPreset = (label: string, text: string) => {
      activePreset.value = label;
      desc.value = text;
    };

    const handlePreview = async () => {
      const text = desc.value.trim();
      if (!text || previewing.value) return;
      previewing.value = true;
      errorMsg.value = "";
      try {
        const blob = await previewNarrator(text, NARRATOR_SAMPLE_DEFAULT);
        const url = URL.createObjectURL(blob);
        if (disposed) { URL.revokeObjectURL(url); return; }
        releasePreview();
        previewUrl.value = url;
      } catch (e) {
        errorMsg.value = e instanceof ApiError ? e.message : "试听生成失败";
      } finally {
        previewing.value = false;
      }
    };

    const confirm = () => {
      const text = desc.value.trim();
      if (!text) return;
      props.onSubmit({ approved: true, edited: { narrator_desc: text } });
    };

    return () => (
      <div class="ab-panel">
        <p class="ab-panel-title">{props.payload.summary || "选择旁白音色"}</p>

        {(props.payload.presets?.length ?? 0) > 0 && (
          <div class="ab-narrator-presets">
            {props.payload.presets.map((p) => (
              <button
                type="button"
                class={["ab-preset", activePreset.value === p.label ? "is-active" : ""]}
                title={p.desc}
                onClick={() => pickPreset(p.label, p.desc)}
              >
                {p.label}
              </button>
            ))}
          </div>
        )}

        <textarea
          class="ab-narrator-input"
          rows={3}
          placeholder="点上面的预设，或直接描述你想要的旁白声音，例：温和沉稳的女声，语速偏慢"
          value={desc.value}
          onInput={(e: Event) => {
            activePreset.value = "";
            desc.value = (e.target as HTMLTextAreaElement).value;
          }}
        />

        <div class="ab-preview-row">
          <button class="ab-btn" onClick={handlePreview}
            disabled={!desc.value.trim() || previewing.value}>
            {previewing.value ? "合成中…" : "试听一下"}
          </button>
          {previewUrl.value && (
            <div class="ab-preview-player">
              <MiniAudioPlayer src={previewUrl.value} />
            </div>
          )}
        </div>

        {errorMsg.value && <p class="ab-narrator-error" title={errorMsg.value}>{errorMsg.value}</p>}

        <div class="ab-actions">
          <button class="ab-btn is-primary" onClick={confirm}
            disabled={!desc.value.trim() || previewing.value}>
            确认并合成
          </button>
          <button class="ab-btn is-ghost" onClick={() => props.onSubmit({ approved: false })}>
            放弃流程
          </button>
        </div>
      </div>
    );
  },
});
