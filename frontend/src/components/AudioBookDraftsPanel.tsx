import { defineComponent, type PropType, ref, onMounted } from "vue";
import Button from "./Button";
import MiniAudioPlayer from "./MiniAudioPlayer";
import { stageMeta } from "./audiobook/statusMeta";
import { PhTrash, PhFileAudio, PhPlay } from "@phosphor-icons/vue";
import {
  getProjectAudioScripts,
  getAudioScriptAudioUrl,
  deleteAudioScript,
} from "../api/audiobook";
import { ApiError } from "../api/client";
import { useWorkspaceStore } from "../stores/workspace";
import { useAudiobookStore } from "../stores/audiobook";
import type { ToastType } from "../stores/toast";
import type { AudioScriptItem } from "../api/types";
import "./audiobook/shared.css";

export default defineComponent({
  name: "AudioBookDraftsPanel",
  props: {
    projectId: { type: Number as PropType<number>, required: true },
    onToast: { type: Function as PropType<(t: ToastType, msg: string) => void>, default: undefined },
    onOpenScript: { type: Function as PropType<(id: number) => void>, default: undefined },
    onCountChange: { type: Function as PropType<(n: number) => void>, default: undefined },
  },
  setup(props, { expose }) {
    const ws = useWorkspaceStore();
    const abStore = useAudiobookStore();
    const items = ref<AudioScriptItem[]>([]);
    const loading = ref(false);

    const load = async () => {
      if (loading.value || !props.projectId) return;
      loading.value = true;
      try {
        const res = await getProjectAudioScripts(props.projectId, 1, 200);
        items.value = (res.data?.List ?? []).slice().reverse();
        props.onCountChange?.(items.value.length);
      } catch (e) {
        const msg = e instanceof ApiError ? e.message : "草稿列表加载失败";
        props.onToast?.("error", msg);
      } finally {
        loading.value = false;
      }
    };
    onMounted(load);
    expose({ reload: load });

    const remove = async (s: AudioScriptItem) => {
      if (abStore.synthOf(s.id)?.running) {
        props.onToast?.("warning", "这一本正在合成，等它完成再删除");
        return;
      }
      try {
        await deleteAudioScript(s.id);
        items.value = items.value.filter((x) => x.id !== s.id);
        props.onCountChange?.(items.value.length);
      } catch (e) {
        const msg = e instanceof ApiError ? e.message : "删除失败";
        props.onToast?.("error", msg);
      }
    };

    const chapterLabel = (chapterId: number) => {
      const ch = ws.chapters.find((c) => c.id === chapterId);
      return ch ? `第 ${ch.chapter_index + 1} 章` : "";
    };

    return () => (
      <>
        {items.value.length === 0 && !loading.value && (
          <p class="ab-hub-empty">还没有有声书，在上方选一章就能开始做</p>
        )}
        <div class="abw-list">
          {items.value.map((s) => {
            const meta = stageMeta(s);
            const chLabel = chapterLabel(s.chapter_id);
            return (
              <div class="abw-draft-item" key={s.id}>
                <div class="abw-draft-main">
                  {chLabel && <span class="abw-draft-chapter">{chLabel}</span>}
                  <span class="abw-draft-name" title={s.name}>{s.name}</span>
                  <span class={`abw-badge ${meta.cls}`}>{meta.label}</span>
                </div>
                <div class="abw-draft-actions">
                  {s.audio_path && (
                    <span class="abw-draft-player">
                      <PhFileAudio size={14} weight="light" />
                      <MiniAudioPlayer src={getAudioScriptAudioUrl(s.id)} />
                    </span>
                  )}
                  <Button size="sm" variant="secondary" onClick={() => props.onOpenScript?.(s.id)} title="打开面板，从推导出的那一步继续">
                    <PhPlay size={14} weight="light" />
                    继续
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => remove(s)} title="删除">
                    <PhTrash size={14} weight="light" />
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      </>
    );
  },
});
