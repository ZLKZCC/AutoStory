import { defineComponent, computed, ref, watch, type PropType } from "vue";
import AudioBookWizard from "./AudioBookWizard";
import AudioBookDraftsPanel from "./AudioBookDraftsPanel";
import Button from "./Button";
import { useWorkspaceStore } from "../stores/workspace";
import { useAudiobookStore } from "../stores/audiobook";
import { useToast } from "../stores/toast";
import type { ToastType } from "../stores/toast";
import { PhArrowClockwise } from "@phosphor-icons/vue";
import "./audiobook/shared.css";

type WizardExposed = { loadScript: (scriptId: number) => void; step?: { value: number } };
type DraftsExposed = { reload: () => void };

export default defineComponent({
  name: "AudioBookHub",
  props: {
    refreshSignal: { type: Number, default: 0 },
    onToast: { type: Function as PropType<(t: ToastType, msg: string) => void>, default: undefined },
  },
  setup(props) {
    const ws = useWorkspaceStore();
    const { addToast } = useToast();
    const wizardRef = ref<WizardExposed | null>(null);
    const draftsRef = ref<DraftsExposed | null>(null);

    const toast = (t: ToastType, msg: string) => {
      if (props.onToast) props.onToast(t, msg);
      else addToast({ type: t, title: msg, duration: 3000 });
    };

    const abStore = useAudiobookStore();
    const flowActive = computed(() => abStore.step > 2 || abStore.anyBusy);

    watch(() => [ws.projectId, props.refreshSignal], () => {
      draftsRef.value?.reload?.();
    });

    const openInWizard = (id: number) => {
      wizardRef.value?.loadScript?.(id);
    };

    return () => (
      <div class="ab-hub">
        <AudioBookWizard ref={wizardRef} />

        <div class="ab-hub-drafts" hidden={flowActive.value}>
          <div class="ab-hub-head">
            <span class="ab-hub-title">本项目全部有声书</span>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => draftsRef.value?.reload?.()}
              title="刷新草稿列表"
            >
              <PhArrowClockwise size={14} weight="light" />
            </Button>
          </div>
          <AudioBookDraftsPanel
            ref={draftsRef}
            projectId={ws.projectId ?? 0}
            onToast={toast}
            onOpenScript={openInWizard}
          />
        </div>
      </div>
    );
  },
});
