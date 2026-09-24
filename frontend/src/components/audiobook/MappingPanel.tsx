import { defineComponent, type PropType, ref, computed } from "vue";
import type { AudiobookAnswer, MappingPayload, MappingEntry, CatalogItem } from "./types";

interface MappingRow {
  extracted_name: string;
  stage_id: number | null;
  confidence?: number;
  reason?: string;
}

export default defineComponent({
  name: "MappingPanel",
  props: {
    payload: { type: Object as PropType<MappingPayload>, required: true },
    onSubmit: {
      type: Function as PropType<(answer: AudiobookAnswer) => void>,
      required: true,
    },
  },
  setup(props) {
    const entries = () => props.payload.mapping?.entries ?? [];
    const rows = ref<MappingRow[]>(
      entries().map((e) => ({
        extracted_name: e.extracted_name,
        stage_id: e.stage_id ?? null,
        confidence: e.confidence,
        reason: e.reason,
      })),
    );
    const options = computed<CatalogItem[]>(() => props.payload.stage_catalog ?? []);
    const feedbackOpen = ref(false);
    const feedbackText = ref("");

    const allLinked = computed(() =>
      rows.value.length > 0 && rows.value.every((r) => r.stage_id != null));
    const dirty = computed(() =>
      rows.value.some((r, i) => r.stage_id !== (entries()[i]?.stage_id ?? null)));

    const submit = (approved: boolean, withFeedback: boolean) => {
      if (approved) {
        const catalog = options.value;
        const clean: MappingEntry[] = rows.value
          .filter((r) => r.stage_id != null)
          .map((r) => {
            const cat = catalog.find((o) => o.stage_id === r.stage_id);
            return {
              extracted_name: r.extracted_name,
              character_id: cat?.character_id ?? 0,
              stage_id: r.stage_id as number,
              ...(r.confidence != null ? { confidence: r.confidence } : {}),
              ...(r.reason ? { reason: r.reason } : {}),
            };
          });
        props.onSubmit({
          approved: true,
          ...(dirty.value ? { edited: { entries: clean } } : {}),
        });
      } else if (withFeedback) {
        props.onSubmit({ approved: false, feedback: feedbackText.value });
      } else {
        props.onSubmit({ approved: false });
      }
    };

    return () => (
      <div class="ab-panel">
        <p class="ab-panel-title">本章提取到 {rows.value.length} 个人物，请为每个人物选出作品里对应的角色阶段
          （同一个角色阶段可以多个人物共用，但每个人物都要配上）：</p>
        {rows.value.map((r) => (
          <div class="ab-mapping-row">
            <span class="ab-mapping-name" title={r.extracted_name}>{r.extracted_name}</span>
            <span class="ab-mapping-arrow">→</span>
            <select class="ab-select" value={r.stage_id ?? ""}
              onChange={(e: Event) => {
                const val = (e.target as HTMLSelectElement).value;
                r.stage_id = val ? Number(val) : null;
              }}>
              <option value="">（还没配对）</option>
              {options.value.map((o) => (
                <option value={o.stage_id}>
                  {o.character_name} · {o.stage_name}（第{o.chapter_index}章起）
                </option>
              ))}
            </select>
          </div>
        ))}
        {feedbackOpen.value && (
          <textarea class="ab-feedback" value={feedbackText.value}
            onInput={(e: Event) => { feedbackText.value = (e.target as HTMLTextAreaElement).value; }}
            rows={2}
            placeholder="说明为什么要重配，如：主角成年后应该用第12章起的那个阶段" />
        )}
        <div class="ab-actions">
          <button class="ab-btn is-primary" onClick={() => submit(true, false)}
            disabled={!allLinked.value}>
            {rows.value.length === 0 ? "本章没有要配对的人物" : allLinked.value ? "确认配对" : "还有人物没配对"}
          </button>
          {feedbackOpen.value
            ? <button class="ab-btn" disabled={!feedbackText.value.trim()}
                onClick={() => submit(false, true)}>提交反馈、重新配对</button>
            : <button class="ab-btn" onClick={() => { feedbackOpen.value = true; }}>让 AI 重新配</button>}
          <button class="ab-btn is-ghost" onClick={() => submit(false, false)}>放弃流程</button>
        </div>
      </div>
    );
  },
});
