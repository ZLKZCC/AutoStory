import { defineComponent, type PropType, ref, computed } from "vue";
import type { AudiobookAnswer, ProposalPayload, NewCharDraft, VoiceSupplement } from "./types";

export default defineComponent({
  name: "ProposalPanel",
  props: {
    payload: { type: Object as PropType<ProposalPayload>, required: true },
    onSubmit: {
      type: Function as PropType<(answer: AudiobookAnswer) => void>,
      required: true,
    },
  },
  setup(props) {
    const checked = ref<Record<number, boolean>>({});
    const drafts = ref<NewCharDraft[]>(
      (props.payload.proposal?.new_characters ?? []).map((c) => ({ ...c })),
    );
    drafts.value.forEach((_, i) => { checked.value[i] = true; });

    const supps = ref<VoiceSupplement[]>(
      (props.payload.proposal?.voice_supplements ?? []).map((s) => ({ ...s })),
    );

    const feedbackOpen = ref(false);
    const feedbackText = ref("");

    const keptCount = computed(
      () => drafts.value.filter((_, i) => checked.value[i]).length);
    const filledSuppCount = computed(
      () => supps.value.filter((s) => s.voice_description.trim()).length);

    const stageNames = computed(() =>
      drafts.value
        .flatMap((c) => c.stages ?? [])
        .map((s) => s.stage_name)
        .join("、"));

    const canConfirm = computed(() => keptCount.value > 0 || filledSuppCount.value > 0);
    const confirmLabel = computed(() => {
      const parts: string[] = [];
      if (drafts.value.length) parts.push(`新建 ${keptCount.value} 个`);
      if (filledSuppCount.value) parts.push(`补 ${filledSuppCount.value} 处音色`);
      return parts.length ? `确认（${parts.join("、")}）` : "确认";
    });

    const submit = (approved: boolean, withFeedback: boolean) => {
      if (approved) {
        const kept = drafts.value.filter((_, i) => checked.value[i]);
        const proposal: {
          new_characters?: NewCharDraft[];
          voice_supplements?: VoiceSupplement[];
        } = {};
        if (kept.length !== drafts.value.length) proposal.new_characters = kept;
        if (supps.value.length) proposal.voice_supplements = supps.value.map((s) => ({ ...s }));
        props.onSubmit({
          approved: true,
          ...(Object.keys(proposal).length ? { edited: { proposal } } : {}),
        });
      } else if (withFeedback) {
        props.onSubmit({ approved: false, feedback: feedbackText.value });
      } else {
        props.onSubmit({ approved: false });
      }
    };

    return () => (
      <div class="ab-panel">
        <p class="ab-panel-title">
          {drafts.value.length > 0
            ? `本章提取到 ${drafts.value.length} 个作品里还没有的人物，确认要不要新建为角色（取消勾选就不建）：`
            : "本章没有要新建的人物，但有些已有角色还缺音色描述："}
        </p>
        {drafts.value.map((c, i) => (
          <div class={{ "ab-proposal-row": true, "is-off": !checked.value[i] }}>
            <input type="checkbox" checked={checked.value[i]}
              onChange={(e: Event) => { checked.value[i] = (e.target as HTMLInputElement).checked; }} />
            <input class="ab-input ab-input-name" type="text" value={c.character_name}
              onInput={(e: Event) => { c.character_name = (e.target as HTMLInputElement).value; }}
              disabled={!checked.value[i]} placeholder="角色名" />
            <input class="ab-input ab-input-gender" type="text" value={c.gender || ""}
              onInput={(e: Event) => { c.gender = (e.target as HTMLInputElement).value; }}
              disabled={!checked.value[i]} placeholder="性别" />
            <input class="ab-input ab-input-role" type="text" value={c.role || ""}
              onInput={(e: Event) => { c.role = (e.target as HTMLInputElement).value; }}
              disabled={!checked.value[i]} placeholder="角色定位" />
          </div>
        ))}
        {stageNames.value && (
          <p class="ab-panel-sub" title={`含拟建阶段：${stageNames.value}`}>
            含拟建阶段：{stageNames.value}
          </p>
        )}

        {supps.value.length > 0 && (
          <div class="ab-supp">
            <p class="ab-panel-sub">这些已有角色还缺音色描述，确认或改一下（合成时按它设计音色，留空则不补）：</p>
            {supps.value.map((s) => (
              <div class="ab-supp-row">
                <span class="ab-supp-name"
                  title={`${s.character_name ?? "角色"}${s.stage_name ? " · " + s.stage_name : ""}`}>
                  {s.character_name ?? "角色"}{s.stage_name ? ` · ${s.stage_name}` : ""}
                </span>
                <input class="ab-input ab-supp-input" type="text" value={s.voice_description}
                  placeholder="如：低沉沙哑的中年男声，语速偏慢"
                  onInput={(e: Event) => { s.voice_description = (e.target as HTMLInputElement).value; }} />
              </div>
            ))}
          </div>
        )}

        {feedbackOpen.value && (
          <textarea class="ab-feedback" value={feedbackText.value}
            onInput={(e: Event) => { feedbackText.value = (e.target as HTMLTextAreaElement).value; }}
            rows={2}
            placeholder="说明打回原因（会作为反馈交给提案重生成），如：小红不该新建，她是已有角色" />
        )}
        <div class="ab-actions">
          <button class="ab-btn is-primary" onClick={() => submit(true, false)}
            disabled={!canConfirm.value}>
            {confirmLabel.value}
          </button>
          {feedbackOpen.value
            ? <button class="ab-btn" disabled={!feedbackText.value.trim()}
                onClick={() => submit(false, true)}>提交反馈、重新提案</button>
            : <button class="ab-btn" onClick={() => { feedbackOpen.value = true; }}>让 AI 重新提案</button>}
          <button class="ab-btn is-ghost" onClick={() => submit(false, false)}>放弃流程</button>
        </div>
      </div>
    );
  },
});
