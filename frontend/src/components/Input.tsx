import { defineComponent } from "vue";
import "./Input.css";

export default defineComponent({
  name: "Input",
  inheritAttrs: false,
  props: {
    label: { type: String, default: "" },
    error: { type: String, default: "" },
    hint: { type: String, default: "" },
    value: { type: [String, Number], default: "" },
    placeholder: { type: String, default: undefined },
    type: { type: String, default: undefined },
  },
  emits: ["update:value"],
  setup(props, { attrs, emit }) {
    return () => (
      <div class={["input-wrapper", attrs.class as string]}>
        {props.label && <label class="input-label">{props.label}</label>}
        <input
          class={["input-field", props.error && "input-error"]}
          value={props.value}
          onInput={(e: Event) =>
            emit("update:value", (e.target as HTMLInputElement).value)
          }
          {...attrs}
          placeholder={props.placeholder}
          type={props.type}
        />
        {props.error && <span class="input-error-text">{props.error}</span>}
        {props.hint && !props.error && <span class="input-hint">{props.hint}</span>}
      </div>
    );
  },
});

export const Textarea = defineComponent({
  name: "Textarea",
  inheritAttrs: false,
  props: {
    label: { type: String, default: "" },
    error: { type: String, default: "" },
    value: { type: String, default: "" },
  },
  emits: ["update:value"],
  setup(props, { attrs, emit }) {
    return () => (
      <div class={["input-wrapper", attrs.class as string]}>
        {props.label && <label class="input-label">{props.label}</label>}
        <textarea
          class={["input-field", "input-textarea", props.error && "input-error"]}
          value={props.value}
          onInput={(e: Event) =>
            emit("update:value", (e.target as HTMLTextAreaElement).value)
          }
          {...attrs}
        />
        {props.error && <span class="input-error-text">{props.error}</span>}
      </div>
    );
  },
});
