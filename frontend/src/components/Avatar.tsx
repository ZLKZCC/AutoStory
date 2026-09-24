import { defineComponent, type PropType } from "vue";
import { PhUser } from "@phosphor-icons/vue";
import agentIconUrl from "../../Icon.png";
import "./Avatar.css";

export default defineComponent({
  name: "Avatar",
  props: {
    kind: { type: String as PropType<"agent" | "user">, required: true },
    size: { type: Number, default: 30 },
    active: { type: Boolean, default: false },
  },
  setup(props) {
    return () => {
      const px = `${props.size}px`;
      const iconSize = Math.max(12, Math.round(props.size * 0.5));
      return (
        <span
          class={`avatar avatar-${props.kind}${props.active ? " avatar-active" : ""}`}
          style={{ width: px, height: px }}
          aria-hidden="true"
        >
          {props.kind === "agent" ? (
            <img src={agentIconUrl} alt="" class="avatar-img" />
          ) : (
            <PhUser size={iconSize} weight="light" class="avatar-user-icon" />
          )}
        </span>
      );
    };
  },
});
