import { defineComponent, type PropType } from "vue";
import {
  PhCheckCircle,
  PhPencilSimple,
  PhTrash,
  PhPlus,
  PhFileText,
  PhUser,
  PhGlobe,
  PhNotepad,
  PhMagnifyingGlass,
  PhArrowCounterClockwise,
  PhWarningCircle,
  PhBooks,
  PhSpeakerHigh,
  PhGear,
} from "@phosphor-icons/vue";
import type { DataChangeInfo } from "../stores/chat";
import "./DataChangeBubble.css";

type IconComp = ReturnType<typeof defineComponent>;

const ENTITY_LABELS: Record<string, { label: string; icon: IconComp }> = {
  outline: { label: "大纲", icon: PhFileText },
  chapters: { label: "章节", icon: PhNotepad },
  characters: { label: "角色", icon: PhUser },
  worldlines: { label: "世界线", icon: PhGlobe },
  volumes: { label: "卷", icon: PhBooks },
  audiobook: { label: "有声书", icon: PhSpeakerHigh },
  project_meta: { label: "项目设置", icon: PhGear },
  fragments: { label: "片段", icon: PhFileText },
  knowledge: { label: "素材库", icon: PhMagnifyingGlass },
};

export const entityLabel = (entity: string) => ENTITY_LABELS[entity]?.label ?? entity;

const ACTION_CONFIG: Record<
  string,
  { label: string; pendingLabel: string; icon: IconComp; className: string }
> = {
  create: { label: "已创建", pendingLabel: "创建", icon: PhPlus, className: "dc-action-create" },
  add_section: { label: "已添加", pendingLabel: "添加", icon: PhPlus, className: "dc-action-create" },
  update: { label: "已更新", pendingLabel: "更新", icon: PhPencilSimple, className: "dc-action-update" },
  update_section: { label: "已更新", pendingLabel: "更新", icon: PhPencilSimple, className: "dc-action-update" },
  append: { label: "已续写", pendingLabel: "续写", icon: PhPencilSimple, className: "dc-action-update" },
  delete: { label: "已删除", pendingLabel: "删除", icon: PhTrash, className: "dc-action-delete" },
  delete_section: { label: "已删除", pendingLabel: "删除", icon: PhTrash, className: "dc-action-delete" },
  add_stage: { label: "已添加阶段", pendingLabel: "添加阶段", icon: PhPlus, className: "dc-action-create" },
  update_stage: { label: "已更新阶段", pendingLabel: "更新阶段", icon: PhPencilSimple, className: "dc-action-update" },
  delete_stage: { label: "已删除阶段", pendingLabel: "删除阶段", icon: PhTrash, className: "dc-action-delete" },
  add_node: { label: "已添加节点", pendingLabel: "添加节点", icon: PhPlus, className: "dc-action-create" },
  update_node: { label: "已更新节点", pendingLabel: "更新节点", icon: PhPencilSimple, className: "dc-action-update" },
  delete_node: { label: "已删除节点", pendingLabel: "删除节点", icon: PhTrash, className: "dc-action-delete" },
  add_edge: { label: "已添加关系", pendingLabel: "添加关系", icon: PhPlus, className: "dc-action-create" },
  activate: { label: "已激活", pendingLabel: "激活", icon: PhCheckCircle, className: "dc-action-update" },
  regenerate: { label: "已重新生成", pendingLabel: "重新生成", icon: PhArrowCounterClockwise, className: "dc-action-update" },
};

export default defineComponent({
  name: "DataChangeBubble",
  props: {
    data: { type: Object as PropType<DataChangeInfo>, required: true },
  },
  emits: ["confirm", "revert"],
  setup(props, { emit }) {
    return () => {
      const data = props.data;
      const entityInfo = ENTITY_LABELS[data.entity] || { label: data.entity, icon: PhFileText };
      const actionInfo = ACTION_CONFIG[data.action] || {
        label: data.action,
        pendingLabel: data.action,
        icon: PhCheckCircle,
        className: "dc-action-update",
      };
      const EntityIcon = entityInfo.icon;
      const status = data.status || "confirmed";
      const headline =
        status === "confirmed"
          ? actionInfo.label
          : status === "reverted"
            ? `已撤销${actionInfo.pendingLabel}`
            : status === "failed"
              ? `${actionInfo.pendingLabel}失败`
              : status === "terminated"
                ? `已终止${actionInfo.pendingLabel}`
                : status === "resolving"
                  ? `${actionInfo.pendingLabel}中…`
                  : actionInfo.pendingLabel;

      return (
        <div class={`dc-bubble ${actionInfo.className} dc-status-${status}`}>
          <div class="dc-text">
            <div class="dc-icon">
              <EntityIcon size={13} weight="duotone" />
            </div>
            {status === "failed" && (
              <PhWarningCircle size={13} weight="fill" class="dc-fail-icon" />
            )}
            <span class="dc-label">{headline}</span>
            <span class="dc-entity">{entityInfo.label}</span>
            {data.summary && <span class="dc-summary">{data.summary}</span>}
          </div>

          {status === "pending" && (
            <div class="dc-actions">
              <button class="dc-btn dc-btn-confirm" onClick={() => emit("confirm")} title="确认">
                <PhCheckCircle size={13} weight="fill" />
                <span>确认</span>
              </button>
              <button class="dc-btn dc-btn-revert" onClick={() => emit("revert")} title="撤销">
                <PhArrowCounterClockwise size={13} weight="bold" />
                <span>撤销</span>
              </button>
            </div>
          )}

          {status === "resolving" && (
            <div class="dc-resolving">
              <span class="dc-spinner" />
              <span>处理中</span>
            </div>
          )}
        </div>
      );
    };
  },
});
