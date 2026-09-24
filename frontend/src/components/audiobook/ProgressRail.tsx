import { defineComponent, ref, watch, onBeforeUnmount } from "vue";
import gsap from "gsap";
import { RAIL_PHASES } from "./types";

export default defineComponent({
  name: "ProgressRail",
  props: {
    phase: { type: String, required: true },
    awaiting: { type: Boolean, default: false },
  },
  setup(props) {
    const dotRefs = ref<HTMLElement[]>([]);
    let tween: gsap.core.Tween | null = null;

    watch(() => props.phase, () => {
      const idx = RAIL_PHASES.findIndex((p) => p.key === props.phase);
      const el = dotRefs.value[idx];
      if (el) {
        tween?.kill();
        tween = gsap.fromTo(el, { scale: 1.5 }, { scale: 1, duration: 0.45, ease: "spring(1, 80, 12)" });
      }
    });

    onBeforeUnmount(() => { tween?.kill(); tween = null; });

    return () => {
      const cur = RAIL_PHASES.findIndex((x) => x.key === props.phase);
      return (
        <div class="ab-rail">
          {RAIL_PHASES.map((p, i) => {
            const done = cur > i || props.phase === "done";
            const active = cur === i && props.phase !== "done";
            const reviewing = active && props.awaiting;
            return (
              <div class={{ "ab-rail-step": true, "is-done": done, "is-active": active }}>
                <span ref={(el) => { if (el) dotRefs.value[i] = el as HTMLElement; }}
                  class="ab-rail-dot" />
                {reviewing
                  ? <span class="ab-rail-flag" title={`${p.label} · 人审中`}>人审中</span>
                  : <span class="ab-rail-label">{p.label}</span>}
              </div>
            );
          })}
        </div>
      );
    };
  },
});
