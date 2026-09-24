import { defineComponent, type PropType, ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from "vue";

import type { CatalogItem, ExtractedChar } from "../api";

export interface LinkPair {
  extracted_name: string;
  character_id: number;
  stage_id: number;
}

interface NodeRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export default defineComponent({
  name: "MappingCanvas",
  props: {
    catalog: { type: Array as PropType<CatalogItem[]>, required: true },
    extracted: { type: Array as PropType<ExtractedChar[]>, required: true },
    modelValue: { type: Array as PropType<LinkPair[]>, required: true },
    onConfirmEnable: { type: Function as PropType<(ok: boolean) => void>, required: true },
  },
  emits: ["update:modelValue"],
  setup(props, { emit }) {
    const linkPairs = computed<LinkPair[]>({
      get: () => props.modelValue,
      set: (v) => emit("update:modelValue", v),
    });

    const pendingFrom = ref<string | null>(null);

    const startLink = (name: string) => {
      pendingFrom.value = pendingFrom.value === name ? null : name;
    };

    const endLink = (stage: CatalogItem) => {
      if (!pendingFrom.value) return;
      const rest = linkPairs.value.filter(
        (p) => p.extracted_name !== pendingFrom.value,
      );
      linkPairs.value = [...rest, {
        extracted_name: pendingFrom.value,
        character_id: stage.character_id,
        stage_id: stage.stage_id,
      }];
      pendingFrom.value = null;
    };

    const removeLink = (name: string) =>
      (linkPairs.value = linkPairs.value.filter(
        (p) => p.extracted_name !== name,
      ));

    const rootRef = ref<HTMLElement | null>(null);
    const leftRefs = ref<Record<number, HTMLElement | null>>({});
    const rightRefs = ref<Record<string, HTMLElement | null>>({});

    const leftRects = ref<Record<number, NodeRect>>({});
    const rightRects = ref<Record<string, NodeRect>>({});
    const rootRect = ref<NodeRect>({ x: 0, y: 0, w: 0, h: 0 });

    const measureAll = () => {
      if (!rootRef.value) return;
      const rr = rootRef.value.getBoundingClientRect();
      rootRect.value = {
        x: rr.left, y: rr.top, w: rr.width, h: rr.height,
      };
      for (const s of props.catalog) {
        const el = leftRefs.value[s.stage_id];
        if (el) {
          const r = el.getBoundingClientRect();
          leftRects.value[s.stage_id] = {
            x: r.left - rootRect.value.x,
            y: r.top - rootRect.value.y,
            w: r.width, h: r.height,
          };
        }
      }
      for (const e of props.extracted) {
        const el = rightRefs.value[e.name];
        if (el) {
          const r = el.getBoundingClientRect();
          rightRects.value[e.name] = {
            x: r.left - rootRect.value.x,
            y: r.top - rootRect.value.y,
            w: r.width, h: r.height,
          };
        }
      }
    };

    onMounted(async () => {
      await nextTick();
      measureAll();
      window.addEventListener("resize", measureAll);
      window.addEventListener("scroll", measureAll, true);
    });
    watch(
      [() => props.catalog, () => props.extracted],
      async () => {
        await nextTick();
        measureAll();
      },
    );
    onBeforeUnmount(() => {
      window.removeEventListener("resize", measureAll);
      window.removeEventListener("scroll", measureAll, true);
    });

    const lines = computed(() => {
      const drawn: { d: string; key: string }[] = [];
      for (const p of linkPairs.value) {
        const l = leftRects.value[p.stage_id];
        const r = rightRects.value[p.extracted_name];
        if (!l || !r) continue;
        const x1 = l.x + l.w;
        const y1 = l.y + l.h / 2;
        const x2 = r.x;
        const y2 = r.y + r.h / 2;
        const cx1 = x1 + (x2 - x1) * 0.4;
        const cx2 = x2 - (x2 - x1) * 0.4;
        drawn.push({
          key: `${p.extracted_name}-${p.stage_id}`,
          d: `M ${x1} ${y1} C ${cx1} ${y1}, ${cx2} ${y2}, ${x2} ${y2}`,
        });
      }
      return drawn;
    });

    const pendingLine = computed(() => {
      if (!pendingFrom.value) return null;
      const r = rightRects.value[pendingFrom.value];
      if (!r) return null;
      return {
        key: `pending-${pendingFrom.value}`,
        d: `M ${r.x} ${r.y + r.h / 2} L ${r.x - 30} ${r.y + r.h / 2}`,
      };
    });

    const allLinked = computed(() =>
      props.extracted.every((e) =>
        linkPairs.value.some((p) => p.extracted_name === e.name)));

    const report = () => props.onConfirmEnable(allLinked.value);
    watch([allLinked, () => props.catalog, () => props.extracted], report, {
      immediate: true,
    });

    return () => (
      <div class="mapping-canvas" ref={rootRef}>
        <div class="mapping-col mapping-left-col">
          <div class="mapping-col-head">本章可用角色阶段</div>
          {props.catalog.map((s) => {
            const linkedTo = linkPairs.value
              .filter((p) => p.stage_id === s.stage_id)
              .map((p) => p.extracted_name);
            return (
              <div
                key={s.stage_id}
                class="mapping-node mapping-left"
                ref={(el: any) => {
                  leftRefs.value[s.stage_id] = el as HTMLElement | null;
                }}
                onClick={() => endLink(s)}
                data-connected={linkedTo.length > 0 ? "true" : "false"}
              >
                <div class="mapping-node-title">
                  {s.character_name} · {s.stage_name}
                </div>
                <div class="mapping-node-sub">
                  第{s.chapter_index}章起 · {s.profile?.slice(0, 30) || "（无设定）"}
                </div>
                {linkedTo.length > 0 && (
                  <div class="mapping-node-badge">
                    连：{linkedTo.join("、")}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        <svg class="mapping-lines" aria-hidden="true">
          {lines.value.map((ln) => (
            <path
              key={ln.key}
              d={ln.d}
              fill="none"
              stroke="var(--accent, #5b8def)"
              stroke-width="2"
              stroke-linecap="round"
            />
          ))}
          {pendingLine.value && (
            <path
              key={pendingLine.value.key}
              d={pendingLine.value.d}
              fill="none"
              stroke="var(--accent, #5b8def)"
              stroke-width="1.5"
              stroke-dasharray="4 4"
              opacity="0.6"
            />
          )}
        </svg>

        <div class="mapping-col mapping-right-col">
          <div class="mapping-col-head">提取出的角色</div>
          {props.extracted.map((e) => {
            const linked = linkPairs.value.find(
              (p) => p.extracted_name === e.name);
            return (
              <div
                key={e.name}
                class="mapping-node mapping-right"
                ref={(el: any) => {
                  rightRefs.value[e.name] = el as HTMLElement | null;
                }}
                onClick={() => (linked ? removeLink(e.name) : startLink(e.name))}
                data-pending={pendingFrom.value === e.name ? "true" : "false"}
                data-linked={linked ? "true" : "false"}
              >
                <div class="mapping-node-title">
                  {e.name}
                  {e.aliases.length > 0 && (
                    <span class="mapping-alias">（{e.aliases.join("、")}）</span>
                  )}
                </div>
                <div class="mapping-node-sub">
                  {e.evidence?.slice(0, 30) || "（无证据）"}
                </div>
                {linked && (
                  <div class="mapping-node-badge mapping-node-badge-ok">
                    已连
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    );
  },
});
