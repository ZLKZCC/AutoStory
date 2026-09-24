import { defineComponent, computed, type PropType } from "vue";
import "./ContextRing.css";

const RADIUS = 18;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

export default defineComponent({
  name: "ContextRing",
  props: {
    used: { type: Number, default: 0 },
    total: { type: Number, default: 0 },
    label: { type: String, default: "上下文" },
  },
  setup(props) {
    const ratio = computed(() => {
      if (!props.total || props.total <= 0) return 0;
      return Math.min(1, props.used / props.total);
    });
    const pct = computed(() => Math.round(ratio.value * 100));
    const dashOffset = computed(() => CIRCUMFERENCE * (1 - ratio.value));

    const colorClass = computed(() => {
      if (ratio.value >= 0.9) return "ring-error";
      if (ratio.value >= 0.7) return "ring-warning";
      return "ring-success";
    });

    const fmt = (n: number) => {
      if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
      return String(Math.round(n));
    };

    return () => (
      <div class={["ctx-ring", colorClass.value]} title={`${props.label}：${pct.value}%（${props.used}/${props.total}）`}>
        <svg viewBox="0 0 44 44" width="44" height="44">
          <circle
            cx="22" cy="22" r={RADIUS}
            fill="none"
            class="ring-track"
            stroke-width="3.5"
          />
          <circle
            cx="22" cy="22" r={RADIUS}
            fill="none"
            class="ring-progress"
            stroke-width="3.5"
            stroke-linecap="round"
            stroke-dasharray={CIRCUMFERENCE}
            stroke-dashoffset={dashOffset.value}
            transform="rotate(-90 22 22)"
          />
          <text
            x="22" y="22" text-anchor="middle" dominant-baseline="central"
            class="ring-text"
          >
            {pct.value}%
          </text>
        </svg>
        <span class="ring-sub">{fmt(props.used)} / {fmt(props.total)}</span>
      </div>
    );
  },
});
