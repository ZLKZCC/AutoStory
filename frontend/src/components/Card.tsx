import { defineComponent, type PropType, type VNode, type CSSProperties } from "vue";
import "./Card.css";

export default defineComponent({
  name: "Card",
  props: {
    hover: { type: Boolean, default: true },
    cardStyle: { type: Object as PropType<CSSProperties>, default: undefined },
  },
  emits: ["click"],
  setup(props, { slots, emit }) {
    return () => (
      <div
        class={["card", props.hover && "card-hover"]}
        style={props.cardStyle}
        onClick={() => emit("click")}
      >
        {slots.default?.()}
      </div>
    );
  },
});

export const CardHeader = defineComponent({
  name: "CardHeader",
  props: {
    title: { type: String, default: "" },
    subtitle: { type: String, default: "" },
    action: { type: Object as PropType<VNode | null>, default: null },
  },
  setup(props, { slots }) {
    return () => (
      <div class="card-header">
        <div>
          <h3 class="card-title">{props.title}</h3>
          {props.subtitle && <p class="card-subtitle">{props.subtitle}</p>}
        </div>
        {(props.action || slots.action) && (
          <div class="card-action">{props.action ?? slots.action?.()}</div>
        )}
      </div>
    );
  },
});
