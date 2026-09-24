import { defineComponent, type PropType, ref } from "vue";
import type { AudiobookAnswer, ScriptPayload } from "./types";

export default defineComponent({
  name: "ScriptPanel",
  props: {
    payload: { type: Object as PropType<ScriptPayload>, required: true },
    onSubmit: {
      type: Function as PropType<(answer: AudiobookAnswer) => void>,
      required: true,
    },
  },
  setup(props) {
    const previewOpen = ref(false);
    const feedbackOpen = ref(false);
    const feedbackText = ref("");
    const ov = () => props.payload.script_overview;

    const submit = (approved: boolean, withFeedback: boolean) => {
      if (approved) props.onSubmit({ approved: true });
      else if (withFeedback) props.onSubmit({ approved: false, feedback: feedbackText.value });
      else props.onSubmit({ approved: false });
    };

    return () => (
      <div class="ab-panel">
        <p class="ab-panel-title">{props.payload.summary}</p>
        <div class="ab-script-stats">
          <span class="ab-chip">{ov().segments} 段</span>
          <span class="ab-chip">BGM {ov().bgm} 轨</span>
          <span class="ab-chip">SFX {ov().sfx} 处</span>
          {ov().speakers.map((s) => <span class="ab-chip is-speaker">{s}</span>)}
        </div>
        {(ov().warnings?.length ?? 0) > 0 && (
          <ul class="ab-warnings">
            {ov().warnings.map((w) => <li title={w}>{w}</li>)}
          </ul>
        )}
        {(props.payload.preview?.length ?? 0) > 0 && (
          <>
            <button class="ab-preview-toggle" onClick={() => { previewOpen.value = !previewOpen.value; }}>
              {previewOpen.value ? "收起脚本预览" : `展开脚本预览（前 ${props.payload.preview!.length} 段）`}
            </button>
            {previewOpen.value && (
              <ol class="ab-preview-list">
                {props.payload.preview!.map((s) => (
                  <li>
                    <span class="ab-preview-speaker" title={s.speaker}>{s.speaker}</span>
                    <span class="ab-preview-text" title={s.text}>{s.text}</span>
                  </li>
                ))}
              </ol>
            )}
          </>
        )}
        {feedbackOpen.value && (
          <textarea class="ab-feedback" value={feedbackText.value}
            onInput={(e: Event) => { feedbackText.value = (e.target as HTMLTextAreaElement).value; }}
            rows={2}
            placeholder="说明打回原因，如：开头两句合成一段，旁白太多切成两段" />
        )}
        <div class="ab-actions">
          <button class="ab-btn is-primary" onClick={() => submit(true, false)}>确认并合成</button>
          {feedbackOpen.value
            ? <button class="ab-btn" disabled={!feedbackText.value.trim()}
                onClick={() => submit(false, true)}>提交反馈、重编脚本</button>
            : <button class="ab-btn" onClick={() => { feedbackOpen.value = true; }}>让 AI 重编脚本</button>}
          <button class="ab-btn is-ghost" onClick={() => submit(false, false)}>放弃流程</button>
        </div>
      </div>
    );
  },
});
