import { defineComponent, type PropType, type VNode } from "vue";
import "./Button.css";

export default defineComponent({
  name: "Button",
  inheritAttrs: false,
  props: {
    variant: {
      type: String as PropType<"primary" | "secondary" | "ghost" | "danger">,
      default: "primary",
    },
    size: { type: String as PropType<"sm" | "md" | "lg">, default: "md" },
    loading: { type: Boolean, default: false },
    icon: { type: Object as PropType<VNode | null>, default: null },
    disabled: { type: Boolean, default: false },
    title: { type: String, default: undefined },
    style: { type: null, default: undefined },
  },
  emits: ["click"],
  setup(props, { slots, attrs, emit }) {
    return () => (
      <button
        class={[
          "btn",
          `btn-${props.variant}`,
          `btn-${props.size}`,
          props.loading && "btn-loading",
          attrs.class as string,
        ]}
        disabled={props.disabled || props.loading}
        onClick={(e) => emit("click", e)}
        {...attrs}
        title={props.title}
        style={props.style}
      >
        {props.loading && <span class="btn-spinner" />}
        {!props.loading && props.icon && <span class="btn-icon">{props.icon}</span>}
        {slots.default?.()}
      </button>
    );
  },
});
