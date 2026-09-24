import { defineComponent, type PropType, type CSSProperties } from "vue";
import "./Tag.css";

export default defineComponent({
  name: "Tag",
  props: {
    variant: {
      type: String as PropType<"default" | "success" | "warning" | "error" | "info">,
      default: "default",
    },
    size: { type: String as PropType<"sm" | "md">, default: "sm" },
    removable: { type: Boolean, default: false },
    tagStyle: { type: Object as PropType<CSSProperties>, default: undefined },
  },
  emits: ["remove"],
  setup(props, { slots, emit }) {
    return () => (
      <span class={`tag tag-${props.variant} tag-${props.size}`} style={props.tagStyle}>
        {slots.default?.()}
        {props.removable && (
          <button class="tag-remove" onClick={() => emit("remove")}>
            ×
          </button>
        )}
      </span>
    );
  },
});
