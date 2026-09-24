import {
  defineComponent,
  ref,
  computed,
  watch,
  onMounted,
  type PropType,
} from "vue";
import {
  listCharacters,
  createCharacter,
  type CharacterInfo,
  type ChapterInfo,
} from "../api";
import { useProjectStore } from "../stores/projects";
import type { PendingChange } from "../stores/chat";
import CharacterPanel from "./CharacterPanel";
import { entityLabel } from "./DataChangeBubble";
import Modal from "./Modal";
import Button from "./Button";
import {
  PhMagnifyingGlass,
  PhPlus,
  PhSparkle,
  PhCheck,
  PhX,
  PhUsers,
} from "@phosphor-icons/vue";

export default defineComponent({
  name: "CharactersView",
  props: {
    projectName: { type: String, required: true },
    chapters: {
      type: Array as PropType<ChapterInfo[]>,
      default: () => [],
    },
    refreshSignal: { type: Number, default: 0 },
    pendingChanges: {
      type: Array as PropType<PendingChange[]>,
      default: () => [],
    },
    onResolveChange: {
      type: Function as PropType<(messageId: string, confirmed: boolean) => void>,
      default: undefined,
    },
  },
  setup(props) {
    const projectStore = useProjectStore();
    const projectId = computed(
      () =>
        projectStore.projects.find((p) => p.name === props.projectName)?.id ??
        null,
    );

    const characters = ref<CharacterInfo[]>([]);
    const charSearch = ref("");
    const newCharOpen = ref(false);
    const newCharName = ref("");
    const newCharGender = ref("");
    const newCharRole = ref("");

    const refreshCharacters = () => {
      if (projectId.value == null) return;
      listCharacters(projectId.value)
        .then((d) => (characters.value = d))
        .catch(() => {});
    };

    onMounted(refreshCharacters);
    watch(projectId, refreshCharacters);

    watch(
      () => props.refreshSignal,
      (sig) => {
        if (!sig) return;
        refreshCharacters();
      },
    );

    const handleCreateChar = async () => {
      if (!newCharName.value.trim() || projectId.value == null) return;
      try {
        await createCharacter(projectId.value, {
          character_name: newCharName.value.trim(),
          gender: newCharGender.value,
          role: newCharRole.value,
        });
        newCharOpen.value = false;
        newCharName.value = "";
        newCharGender.value = "";
        newCharRole.value = "";
        refreshCharacters();
      } catch {
      }
    };

    const renderPending = () => {
      const items = props.pendingChanges.filter(
        (p) => p.dataChange.entity === "characters",
      );
      if (items.length === 0) return null;
      return (
        <div class="canvas-pending">
          {items.map((i) => (
            <div class="canvas-pending-item" key={i.messageId}>
              <PhSparkle size={12} weight="fill" />
              <span class="canvas-pending-summary">
                {i.dataChange.summary || `${i.dataChange.action} · ${entityLabel(i.dataChange.entity)}`}
              </span>
              <button
                class="canvas-pending-btn accept"
                onClick={() => props.onResolveChange?.(i.messageId, true)}
              >
                <PhCheck size={11} /> 确认
              </button>
              <button
                class="canvas-pending-btn reject"
                onClick={() => props.onResolveChange?.(i.messageId, false)}
              >
                <PhX size={11} /> 放弃
              </button>
            </div>
          ))}
        </div>
      );
    };

    return () => (
      <div class="canvas-characters">
        {renderPending()}
        <div class="canvas-characters-head">
          <span class="canvas-section-label">角色</span>
          <div class="canvas-characters-search">
            <PhMagnifyingGlass size={14} weight="light" />
            <input
              class="canvas-characters-search-input"
              type="text"
              placeholder="搜索角色名..."
              value={charSearch.value}
              onInput={(e) => {
                charSearch.value = (e.target as HTMLInputElement).value;
              }}
            />
            <button
              class="icon-btn"
              onClick={() => (newCharOpen.value = true)}
              title="新建角色"
            >
              <PhPlus size={14} />
            </button>
          </div>
        </div>
        {characters.value.length === 0 ? (
          <div class="canvas-characters-empty">
            <PhUsers size={28} weight="light" />
            <p>{charSearch.value ? "未找到匹配的角色" : "暂无角色，点击 + 新建"}</p>
          </div>
        ) : (
          <div class="canvas-characters-list">
            {characters.value
              .filter((c) =>
                !charSearch.value ||
                c.character_name.includes(charSearch.value)
              )
              .map((c) => (
                <CharacterPanel
                      key={c.id}
                      character={c}
                      chapters={props.chapters}
                      onRefresh={refreshCharacters}
                    />
              ))}
          </div>
        )}

        <Modal
          open={newCharOpen.value}
          onClose={() => (newCharOpen.value = false)}
          title="新建角色"
          width={360}
        >
          <input
            class="input-field"
            value={newCharName.value}
            onInput={(e) =>
              (newCharName.value = (e.target as HTMLInputElement).value)
            }
            placeholder="角色名称"
            autofocus
          />
          <input
            class="input-field"
            value={newCharGender.value}
            onInput={(e) =>
              (newCharGender.value = (e.target as HTMLInputElement).value)
            }
            placeholder="性别（如：女）"
            style={{ marginTop: "8px" }}
          />
          <select
            class="input-field"
            value={newCharRole.value}
            onChange={(e) =>
              (newCharRole.value = (e.target as HTMLSelectElement).value)
            }
            style={{ marginTop: "8px" }}
          >
            <option value="">未设定</option>
            <option value="protagonist">主角</option>
            <option value="antagonist">反派</option>
            <option value="supporting">配角</option>
            <option value="extra">龙套</option>
          </select>
          <div
            style={{
              display: "flex",
              gap: "8px",
              justifyContent: "flex-end",
              marginTop: "12px",
            }}
          >
            <Button
              size="sm"
              variant="ghost"
              onClick={() => (newCharOpen.value = false)}
            >
              取消
            </Button>
            <Button
              size="sm"
              onClick={handleCreateChar}
              disabled={!newCharName.value.trim()}
            >
              创建
            </Button>
          </div>
        </Modal>
      </div>
    );
  },
});
