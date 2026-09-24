import { defineComponent, type PropType, ref } from "vue";
import type { AudiobookAnswer, NamingPayload } from "./types";

export default defineComponent({
  name: "NamingPanel",
  props: {
    payload: { type: Object as PropType<NamingPayload>, required: true },
    onSubmit: {
      type: Function as PropType<(answer: AudiobookAnswer) => void>,
      required: true,
    },
  },
  setup(props) {
    const name = ref(props.payload.current ?? "");

    const confirm = () => {
      const text = name.value.trim();
      if (!text) return;
      props.onSubmit({ approved: true, edited: { name: text } });
    };

    return () => (
      <div class="ab-panel">
        <p class="ab-panel-title">{props.payload.summary || "为本次有声书命名（将作为音频成品的名字）"}</p>
        <div class="ab-naming-row">
          <input
            class="ab-input ab-naming-input"
            type="text"
            value={name.value}
            placeholder="如：第一卷·风起"
            maxlength={50}
            onInput={(e: Event) => { name.value = (e.target as HTMLInputElement).value; }}
            onKeydown={(e: KeyboardEvent) => { if (e.key === "Enter") confirm(); }}
          />
        </div>
        <div class="ab-actions">
          <button class="ab-btn is-primary" onClick={confirm} disabled={!name.value.trim()}>
            确认命名
          </button>
          <button class="ab-btn is-ghost" onClick={() => props.onSubmit({ approved: false })}>
            放弃流程
          </button>
        </div>
      </div>
    );
  },
});
