import { defineComponent, ref, watch, Teleport, type PropType } from "vue";
import {
  VueFlow,
  Handle,
  Position,
  MarkerType,
  ConnectionMode,
  getBezierPath,
  BaseEdge,
  applyNodeChanges,
  applyEdgeChanges,
  type Connection,
  type NodeChange,
  type EdgeChange,
} from "@vue-flow/core";
import "@vue-flow/core/dist/style.css";
import "@vue-flow/core/dist/theme-default.css";
import { Background } from "@vue-flow/background";
import { Controls } from "@vue-flow/controls";
import "@vue-flow/controls/dist/style.css";
import { MiniMap } from "@vue-flow/minimap";
import "@vue-flow/minimap/dist/style.css";
import { type Worldline } from "../api";
import WlMiniMap from "./WlMiniMap";
import { Button } from ".";
import { useConfirm } from "./ConfirmDialog";
import {
  PhPlus,
  PhTrash,
  PhX,
  PhGitBranch,
  PhCode,
  PhDownloadSimple,
} from "@phosphor-icons/vue";
import gsap from "gsap";

type ArrowType =
  | "undirected"
  | "bidirectional"
  | "unidirectional-left"
  | "unidirectional-right";

interface EdgeRelation {
  id: string;
  from: string;
  to: string;
  label: string;
  arrowType: ArrowType;
  sourceHandle?: string;
  targetHandle?: string;
}

interface WlNodeInfo {
  id: string;
  title: string;
  description: string;
  color: string;
  textColor: string;
  fontSize: number;
  fontWeight: string;
  fontStyle: string;
  x: number;
  y: number;
}

const ARROW_TYPE_OPTIONS: { value: ArrowType; icon: any }[] = [
  {
    value: "unidirectional-right",
    icon: (
      <svg width="32" height="16" viewBox="0 0 32 16">
        <line
          x1="2"
          y1="8"
          x2="24"
          y2="8"
          stroke="currentColor"
          stroke-width="1.5"
        />
        <polygon points="24,4 30,8 24,12" fill="currentColor" />
      </svg>
    ),
  },
  {
    value: "unidirectional-left",
    icon: (
      <svg width="32" height="16" viewBox="0 0 32 16">
        <line
          x1="8"
          y1="8"
          x2="30"
          y2="8"
          stroke="currentColor"
          stroke-width="1.5"
        />
        <polygon points="8,4 2,8 8,12" fill="currentColor" />
      </svg>
    ),
  },
  {
    value: "bidirectional",
    icon: (
      <svg width="32" height="16" viewBox="0 0 32 16">
        <line
          x1="8"
          y1="8"
          x2="24"
          y2="8"
          stroke="currentColor"
          stroke-width="1.5"
        />
        <polygon points="8,4 2,8 8,12" fill="currentColor" />
        <polygon points="24,4 30,8 24,12" fill="currentColor" />
      </svg>
    ),
  },
  {
    value: "undirected",
    icon: (
      <svg width="32" height="16" viewBox="0 0 32 16">
        <line
          x1="2"
          y1="8"
          x2="30"
          y2="8"
          stroke="currentColor"
          stroke-width="1.5"
        />
      </svg>
    ),
  },
];

const DEFAULT_NODE_COLOR = "#6366f1";
const DEFAULT_TEXT_COLOR = "#ffffff";
const DEFAULT_FONT_SIZE = 12;
const DEFAULT_FONT_WEIGHT = "600";
const DEFAULT_FONT_STYLE = "normal";
const DEFAULT_ARROW_TYPE: ArrowType = "unidirectional-right";
const DEFAULT_NODE_X = 0;
const DEFAULT_NODE_Y = 0;

function serializeWorldlineText(
  name: string,
  nodes: WlNodeInfo[],
  edges: EdgeRelation[],
): string {
  if (!nodes.length) return `[世界线: ${name}]\n\n(空)`;

  const idToIdx: Record<string, number> = {};
  for (let i = 0; i < nodes.length; i++) {
    idToIdx[nodes[i].id] = i + 1;
  }

  const lines: string[] = [`[世界线: ${name}]`, "", "## 节点"];
  for (const n of nodes) {
    const idx = idToIdx[n.id] ?? "?";
    const title = n.title.trim();
    const desc = n.description.trim();
    lines.push(desc ? `(${idx}) ${title} | ${desc}` : `(${idx}) ${title}`);
  }

  if (edges.length) {
    lines.push("", "## 关系");
    for (const e of edges) {
      const fi = idToIdx[e.from] ?? "?";
      const ti = idToIdx[e.to] ?? "?";
      const label = e.label.trim();
      const at = e.arrowType || DEFAULT_ARROW_TYPE;
      let arrow: string;
      if (at === "bidirectional") arrow = "<-->";
      else if (at === "undirected") arrow = "---";
      else if (at === "unidirectional-left") arrow = "<--";
      else arrow = "-->";
      if (label) lines.push(`(${fi}) --[${label}]--${arrow[0]} (${ti})`);
      else lines.push(`(${fi}) ${arrow} (${ti})`);
    }
  }

  return lines.join("\n");
}

function getEdgeMarkers(arrowType: ArrowType) {
  const arrow = {
    type: MarkerType.ArrowClosed,
    width: 14,
    height: 10,
    color: "#6b7280",
  };
  switch (arrowType) {
    case "unidirectional-right":
      return { markerEnd: arrow, markerStart: undefined };
    case "unidirectional-left":
      return { markerEnd: undefined, markerStart: arrow };
    case "bidirectional":
      return { markerEnd: arrow, markerStart: arrow };
    case "undirected":
      return { markerEnd: undefined, markerStart: undefined };
    default:
      return { markerEnd: arrow, markerStart: undefined };
  }
}

interface WlNodeData extends Record<string, unknown> {
  label: string;
  description: string;
  color: string;
  textColor: string;
  fontSize: number;
  fontWeight: string;
  fontStyle: string;
  onSelect: (id: string) => void;
}

const WlNodeComp = defineComponent({
  name: "WlNodeComp",
  props: {
    id: { type: String, required: true },
    data: { type: Object as PropType<WlNodeData>, required: true },
    selected: { type: Boolean, default: false },
  },
  setup(props) {
    return () => {
      const d = props.data;
      return (
        <div
          class={`wl-circle-node${props.selected ? " selected" : ""}`}
          style={{
            background: d.color || DEFAULT_NODE_COLOR,
            color: d.textColor || DEFAULT_TEXT_COLOR,
            fontSize: `${d.fontSize || DEFAULT_FONT_SIZE}px`,
            fontWeight: d.fontWeight || DEFAULT_FONT_WEIGHT,
            fontStyle: d.fontStyle || DEFAULT_FONT_STYLE,
          }}
          onClick={(e) => {
            e.stopPropagation();
            d.onSelect(props.id);
          }}
        >
          <Handle
            type="target"
            position={Position.Top}
            id="top"
            class="wl-handle"
          />
          <Handle
            type="target"
            position={Position.Left}
            id="left"
            class="wl-handle"
          />
          <span class="wl-circle-node-title">{d.label}</span>
          <div class="wl-circle-node-tooltip">
            <div class="wl-tooltip-title">{d.label}</div>
            {d.description && (
              <div class="wl-tooltip-desc">{d.description}</div>
            )}
          </div>
          <Handle
            type="source"
            position={Position.Bottom}
            id="bottom"
            class="wl-handle"
          />
          <Handle
            type="source"
            position={Position.Right}
            id="right"
            class="wl-handle"
          />
        </div>
      );
    };
  },
});

const nodeTypes = { wlNode: WlNodeComp };

interface WlEdgeData extends Record<string, unknown> {
  label: string;
  arrowType: ArrowType;
  onSelect: (edgeId: string) => void;
}

const WlEdgeComp = defineComponent({
  name: "WlEdgeComp",
  props: {
    id: { type: String, required: true },
    sourceX: { type: Number, required: true },
    sourceY: { type: Number, required: true },
    targetX: { type: Number, required: true },
    targetY: { type: Number, required: true },
    sourcePosition: { type: String as PropType<Position>, required: true },
    targetPosition: { type: String as PropType<Position>, required: true },
    data: { type: Object as PropType<WlEdgeData>, default: undefined },
    selected: { type: Boolean, default: false },
    markerEnd: { type: String, default: undefined },
    markerStart: { type: String, default: undefined },
  },
  setup(props) {
    return () => {
      const d = props.data;
      const [edgePath, labelX, labelY] = getBezierPath({
        sourceX: props.sourceX,
        sourceY: props.sourceY,
        targetX: props.targetX,
        targetY: props.targetY,
        sourcePosition: props.sourcePosition,
        targetPosition: props.targetPosition,
      });
      return (
        <g
          class="story-wl-rf-edge"
          onClick={(e) => {
            e.stopPropagation();
            d?.onSelect(props.id);
          }}
          style={{ cursor: "pointer" }}
        >
          <path d={edgePath} fill="none" stroke="transparent" stroke-width={16} />
          <BaseEdge
            id={props.id}
            path={edgePath}
            markerEnd={props.markerEnd}
            markerStart={props.markerStart}
            style={{
              stroke: props.selected ? "#6366f1" : "#6b7280",
              strokeWidth: props.selected ? 2 : 1.5,
            }}
          />
          {(d?.label || props.selected) && (
            <g transform={`translate(${labelX}, ${labelY})`}>
              <rect
                x={-36}
                y={-10}
                width={72}
                height={20}
                rx={4}
                fill={props.selected ? "#eef2ff" : "#f3f4f6"}
                stroke={props.selected ? "#6366f1" : "#d1d5db"}
                stroke-width={0.5}
              />
              <text
                x={0}
                y={4}
                text-anchor="middle"
                font-size={9}
                font-weight={500}
                fill={d?.label ? (props.selected ? "#6366f1" : "#6b7280") : "#9ca3af"}
                font-style={d?.label ? "normal" : "italic"}
              >
                {d?.label || "点击编辑"}
              </text>
            </g>
          )}
        </g>
      );
    };
  },
});

const edgeTypes = { wlEdge: WlEdgeComp };

type Selection =
  | { type: "node"; id: string }
  | { type: "edge"; id: string }
  | null;

export default defineComponent({
  name: "WorldlineOverlay",
  props: {
    projectName: { type: String, required: true },
    wlVisualOpen: { type: Boolean, default: false },
    wlJsonOpen: { type: Boolean, default: false },
    onCloseVisual: { type: Function as PropType<() => void>, required: true },
    onCloseJson: { type: Function as PropType<() => void>, required: true },
    currentWl: { type: Object as PropType<Worldline | null>, default: null },
    wlNodes: { type: Array as PropType<WlNodeInfo[]>, default: () => [] },
    edgeRelations: { type: Array as PropType<EdgeRelation[]>, default: () => [] },
    wlNodeMap: {
      type: Object as PropType<Record<string, WlNodeInfo[]>>,
      default: () => ({}),
    },
    setWlNodeMap: {
      type: Function as PropType<(v: Record<string, WlNodeInfo[]>) => void>,
      required: true,
    },
    setEdgeRelations: {
      type: Function as PropType<(v: EdgeRelation[]) => void>,
      required: true,
    },
    loadWorldlines: { type: Function as PropType<() => void>, required: true },
    onPersistWorldlines: {
      type: Function as PropType<() => Promise<void>>,
      default: undefined,
    },
    onRenameWorldline: {
      type: Function as PropType<(wlId: string, name: string) => Promise<void>>,
      default: undefined,
    },
  },
  setup(props) {
    const { confirm } = useConfirm();
    const overlayRef = ref<HTMLDivElement | null>(null);
    const jsonRef = ref<HTMLDivElement | null>(null);
    const editingWlName = ref(false);
    const wlNameDraft = ref("");
    const selection = ref<Selection>(null);
    const rfNodes = ref<any[]>([]);
    const rfEdges = ref<any[]>([]);
    let prevSyncKey = "";
    let saveTimer: ReturnType<typeof setTimeout> | null = null;

    const rfInstance = ref<any>(null);
    const pendingFit = ref(false);

    const runFitView = (padding = 0.22) => {
      const rf = rfInstance.value;
      if (!rf || rfNodes.value.length === 0) return;
      try {
        rf.fitView({ padding, duration: 320 });
      } catch {
      }
    };

    const onRfReady = (instance: any) => {
      rfInstance.value = instance;
      if (pendingFit.value || props.wlVisualOpen) {
        pendingFit.value = false;
        requestAnimationFrame(() => runFitView());
      }
    };

    watch(
      () => [props.wlVisualOpen, () => props.currentWl?.id],
      ([open]) => {
        if (open) {
          if (rfInstance.value) runFitView();
          else pendingFit.value = true;
        }
      },
    );

    const updateNodeMap = (
      updater: (prev: Record<string, WlNodeInfo[]>) => Record<string, WlNodeInfo[]>,
    ) => {
      props.setWlNodeMap(updater(props.wlNodeMap));
    };
    const updateEdgeRelations = (
      updater: (prev: EdgeRelation[]) => EdgeRelation[],
    ) => {
      props.setEdgeRelations(updater(props.edgeRelations));
    };

    watch(
      () => props.wlVisualOpen,
      (open) => {
        if (!open) return;
        requestAnimationFrame(() => {
          const el = overlayRef.value;
          if (el)
            gsap.fromTo(
              el,
              { opacity: 0 },
              { opacity: 1, duration: 0.2, ease: "power2.out" },
            );
        });
      },
    );
    watch(
      () => props.wlJsonOpen,
      (open) => {
        if (!open) return;
        requestAnimationFrame(() => {
          const el = jsonRef.value;
          if (el)
            gsap.fromTo(
              el,
              { opacity: 0, y: 16, scale: 0.98 },
              { opacity: 1, y: 0, scale: 1, duration: 0.25, ease: "power3.out" },
            );
        });
      },
    );

    const saveToBackend = () => {
      const wl = props.currentWl;
      if (!wl) return;
      if (saveTimer) clearTimeout(saveTimer);
      saveTimer = setTimeout(() => {
        props.onPersistWorldlines?.().catch(() => {});
      }, 800);
    };

    watch(
      [
        () => props.wlNodeMap,
        () => props.edgeRelations,
        () => props.currentWl,
      ],
      () => {
        if (!props.currentWl) return;
        saveToBackend();
      },
    );

    const handleCreateNode = () => {
      const wl = props.currentWl;
      if (!wl) return;
      const nodeId = `node-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
      const newNode: WlNodeInfo = {
        id: nodeId,
        title: `节点 ${(props.wlNodeMap[wl.id]?.length || 0) + 1}`,
        description: "",
        color: DEFAULT_NODE_COLOR,
        textColor: DEFAULT_TEXT_COLOR,
        fontSize: DEFAULT_FONT_SIZE,
        fontWeight: DEFAULT_FONT_WEIGHT,
        fontStyle: DEFAULT_FONT_STYLE,
        x: (Math.random() - 0.5) * 120,
        y: (Math.random() - 0.5) * 80,
      };
      updateNodeMap((prev) => ({
        ...prev,
        [wl.id]: [...(prev[wl.id] || []), newNode],
      }));
    };

    const handleStartEditWlName = () => {
      if (!props.currentWl) return;
      wlNameDraft.value = props.currentWl.name || "主线";
      editingWlName.value = true;
    };
    const handleSaveWlName = async () => {
      const wl = props.currentWl;
      if (!wl) return;
      try {
        await props.onRenameWorldline?.(wl.id, wlNameDraft.value);
        editingWlName.value = false;
        props.loadWorldlines();
      } catch {
      }
    };
    const handleCancelEditWlName = () => (editingWlName.value = false);

    const removeNodeById = (id: string) => {
      const wl = props.currentWl;
      if (!wl) return;
      updateNodeMap((prev) => ({
        ...prev,
        [wl.id]: (prev[wl.id] || []).filter((n) => n.id !== id),
      }));
      updateEdgeRelations((prev) =>
        prev.filter((e) => e.from !== id && e.to !== id),
      );
    };

    const removeEdgeById = (id: string) => {
      updateEdgeRelations((prev) => prev.filter((r) => r.id !== id));
    };

    let pendingNodeRemoves: Extract<NodeChange, { type: "remove" }>[] = [];
    let pendingEdgeRemoves: Extract<EdgeChange, { type: "remove" }>[] = [];
    let pendingDeleteQueued = false;

    const flushPendingDelete = async () => {
      const nodeRemoves = pendingNodeRemoves;
      const edgeRemoves = pendingEdgeRemoves;
      pendingNodeRemoves = [];
      pendingEdgeRemoves = [];
      if (nodeRemoves.length === 0 && edgeRemoves.length === 0) return;

      const nodeIds = new Set(nodeRemoves.map((c) => c.id));
      const edgeIds = new Set(edgeRemoves.map((c) => c.id));
      const nodeCount = nodeIds.size;
      const edgeCount = edgeIds.size;

      const targets: string[] = [];
      if (nodeCount > 0)
        targets.push(
          nodeCount > 1
            ? `${nodeCount} 个节点`
            : `节点「${props.wlNodes.find((n) => nodeIds.has(n.id))?.title || "未命名"}」`,
        );
      if (edgeCount > 0)
        targets.push(edgeCount > 1 ? `${edgeCount} 条关系` : "关系");
      const relatedEdgeCount = props.edgeRelations.filter(
        (e) => (nodeIds.has(e.from) || nodeIds.has(e.to)) && !edgeIds.has(e.id),
      ).length;

      const ok = await confirm({
        title:
          nodeCount > 0 && edgeCount > 0
            ? "删除节点与关系"
            : nodeCount > 0
              ? "删除节点"
              : "删除关系",
        message: `确定要删除${targets.join("及")}吗？${
          relatedEdgeCount > 0
            ? `与之相连的 ${relatedEdgeCount} 条关系将一并删除，`
            : ""
        }不可恢复。`,
        danger: true,
        confirmText: "确认删除",
      });
      if (!ok) return;
      for (const id of nodeIds) removeNodeById(id);
      for (const id of edgeIds) removeEdgeById(id);
      selection.value = null;
      rfNodes.value = applyNodeChanges(
        nodeRemoves,
        rfNodes.value as any,
      ) as any;
      rfEdges.value = applyEdgeChanges(
        edgeRemoves,
        rfEdges.value as any,
      ) as any;
    };

    const queueDeleteConfirm = () => {
      if (pendingDeleteQueued) return;
      pendingDeleteQueued = true;
      Promise.resolve().then(() => {
        pendingDeleteQueued = false;
        void flushPendingDelete();
      });
    };

    const onRfNodesChange = (changes: NodeChange[]) => {
      const wl = props.currentWl;
      const removes = changes.filter((c) => c.type === "remove");
      const others = changes.filter((c) => c.type !== "remove");
      if (removes.length > 0) {
        pendingNodeRemoves.push(...removes);
        queueDeleteConfirm();
      }
      for (const change of others) {
        if (change.type === "position" && change.position && wl) {
          const pos = change.position;
          updateNodeMap((prev) => ({
            ...prev,
            [wl.id]: (prev[wl.id] || []).map((n) =>
              n.id === change.id ? { ...n, x: pos.x, y: pos.y } : n,
            ),
          }));
        }
      }
      if (others.length > 0) {
        rfNodes.value = applyNodeChanges(others, rfNodes.value as any) as any;
      }
    };

    const onRfEdgesChange = (changes: EdgeChange[]) => {
      const removes = changes.filter((c) => c.type === "remove");
      const others = changes.filter((c) => c.type !== "remove");
      if (removes.length > 0) {
        pendingEdgeRemoves.push(...removes);
        queueDeleteConfirm();
      }
      if (others.length > 0) {
        rfEdges.value = applyEdgeChanges(others, rfEdges.value as any) as any;
      }
    };

    const onConnect = (connection: Connection) => {
      if (!connection.source || !connection.target) return;
      const edgeId = `edge-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      updateEdgeRelations((prev) => [
        ...prev,
        {
          id: edgeId,
          from: connection.source!,
          to: connection.target!,
          label: "",
          arrowType: DEFAULT_ARROW_TYPE,
          sourceHandle: connection.sourceHandle ?? undefined,
          targetHandle: connection.targetHandle ?? undefined,
        },
      ]);
    };

    const handleNodeClick = (node: any) => {
      selection.value = { type: "node", id: node.id };
    };
    const handleEdgeClick = (edge: any) => {
      selection.value = { type: "edge", id: edge.id };
    };
    const handlePaneClick = () => {
      selection.value = null;
    };

    watch(
      [() => props.wlVisualOpen, () => props.wlNodes, () => props.edgeRelations],
      () => {
        if (!props.wlVisualOpen || props.wlNodes.length === 0) {
          if (!props.wlVisualOpen) {
            rfInstance.value = null;
            pendingFit.value = false;
          }
          if (prevSyncKey !== "__empty__") {
            rfNodes.value = [];
            rfEdges.value = [];
            prevSyncKey = "__empty__";
          }
          return;
        }
        const idKey = props.wlNodes.map((n) => n.id).join(",");
        const edgeKey = props.edgeRelations
          .map((e) => `${e.from}->${e.to}:${e.label}:${e.arrowType}`)
          .join(";");
        const nodeStyleKey = props.wlNodes
          .map(
            (n) =>
              `${n.id}:${n.title}:${n.description}:${n.color}:${n.textColor}:${n.fontSize}:${n.fontWeight}:${n.fontStyle}`,
          )
          .join(",");
        const syncKey = `${idKey}|${edgeKey}|${nodeStyleKey}`;
        if (syncKey === prevSyncKey) return;
        const isFirstSync = prevSyncKey === "" || prevSyncKey === "__empty__";
        prevSyncKey = syncKey;
        rfNodes.value = props.wlNodes.map((n) => ({
          id: n.id,
          type: "wlNode",
          position: { x: n.x ?? DEFAULT_NODE_X, y: n.y ?? DEFAULT_NODE_Y },
          data: {
            label: n.title || "未命名",
            description: n.description,
            color: n.color || DEFAULT_NODE_COLOR,
            textColor: n.textColor || DEFAULT_TEXT_COLOR,
            fontSize: n.fontSize || DEFAULT_FONT_SIZE,
            fontWeight: n.fontWeight || DEFAULT_FONT_WEIGHT,
            fontStyle: n.fontStyle || DEFAULT_FONT_STYLE,
            onSelect: (id: string) =>
              (selection.value = { type: "node", id }),
          },
        }));
        rfEdges.value = props.edgeRelations.map((rel) => {
          const markers = getEdgeMarkers(rel.arrowType || DEFAULT_ARROW_TYPE);
          return {
            id: rel.id,
            source: rel.from,
            target: rel.to,
            sourceHandle: rel.sourceHandle || undefined,
            targetHandle: rel.targetHandle || undefined,
            type: "wlEdge",
            markerEnd: markers.markerEnd,
            markerStart: markers.markerStart,
            data: {
              label: rel.label,
              arrowType: rel.arrowType || DEFAULT_ARROW_TYPE,
              onSelect: (edgeId: string) =>
                (selection.value = { type: "edge", id: edgeId }),
            },
          };
        });
        if (isFirstSync) {
          if (rfInstance.value) requestAnimationFrame(() => runFitView());
          else pendingFit.value = true;
        }
      },
      { immediate: true },
    );

    const handleExportJson = () => {
      const exportData = {
        worldline: {
          id: props.currentWl?.id,
          name: props.currentWl?.name || "主线",
          description: props.currentWl?.description || "",
        },
        nodes: props.wlNodes.map((n) => ({
          id: n.id,
          title: n.title || "",
          description: n.description || "",
          color: n.color,
          textColor: n.textColor,
          fontSize: n.fontSize,
          fontWeight: n.fontWeight,
          fontStyle: n.fontStyle,
          x: n.x,
          y: n.y,
        })),
        edges: props.edgeRelations.map((e) => ({
          id: e.id,
          from: e.from,
          to: e.to,
          label: e.label || "",
          arrowType: e.arrowType,
          sourceHandle: e.sourceHandle,
          targetHandle: e.targetHandle,
        })),
        text: serializeWorldlineText(
          props.currentWl?.name || "主线",
          props.wlNodes,
          props.edgeRelations,
        ),
      };
      const blob = new Blob([JSON.stringify(exportData, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${props.projectName}_worldlines.json`;
      a.click();
      URL.revokeObjectURL(url);
    };

    const renderPropPanel = () => {
      const sel = selection.value;
      if (!sel) {
        return (
          <div class="wl-prop-panel wl-prop-empty">
            <span>点击节点或边线查看属性</span>
          </div>
        );
      }

      if (sel.type === "node") {
        const node = props.wlNodes.find((n) => n.id === sel.id);
        if (!node)
          return (
            <div class="wl-prop-panel wl-prop-empty">
              <span>节点未找到</span>
            </div>
          );
        const update = (patch: Partial<WlNodeInfo>) => {
          const wl = props.currentWl;
          if (!wl) return;
          updateNodeMap((prev) => ({
            ...prev,
            [wl.id]: (prev[wl.id] || []).map((n) =>
              n.id === sel.id ? { ...n, ...patch } : n,
            ),
          }));
        };
        const deleteNode = async () => {
          if (!props.currentWl) return;
          const relatedEdges = props.edgeRelations.filter(
            (e) => e.from === sel.id || e.to === sel.id,
          ).length;
          const ok = await confirm({
            title: "删除节点",
            message: `确定要删除节点「${node.title || "未命名"}」吗？${
              relatedEdges > 0 ? `与之相连的 ${relatedEdges} 条关系将一并删除，` : ""
            }不可恢复。`,
            danger: true,
            confirmText: "确认删除",
          });
          if (!ok) return;
          removeNodeById(sel.id);
          selection.value = null;
        };
        return (
          <div class="wl-prop-panel">
            <div class="wl-prop-header">
              <span class="wl-prop-title">节点属性</span>
              <button
                class="wl-prop-delete-btn"
                onClick={deleteNode}
                title="删除节点"
              >
                <PhTrash size={12} />
              </button>
            </div>
            <div class="wl-prop-field">
              <label>标题</label>
              <input
                value={node.title}
                onInput={(e) =>
                  update({ title: (e.target as HTMLInputElement).value })
                }
              />
            </div>
            <div class="wl-prop-field">
              <label>描述</label>
              <textarea
                value={node.description}
                onInput={(e) =>
                  update({
                    description: (e.target as HTMLTextAreaElement).value,
                  })
                }
                rows={3}
                style={{ resize: "none" }}
              />
            </div>
            <div class="wl-prop-field">
              <label>节点颜色</label>
              <div class="wl-prop-color-row">
                <input
                  type="color"
                  value={node.color || DEFAULT_NODE_COLOR}
                  onInput={(e) =>
                    update({ color: (e.target as HTMLInputElement).value })
                  }
                />
                <span class="wl-prop-color-hex">
                  {node.color || DEFAULT_NODE_COLOR}
                </span>
              </div>
            </div>
            <div class="wl-prop-field">
              <label>标题文字颜色</label>
              <div class="wl-prop-color-row">
                <input
                  type="color"
                  value={node.textColor || DEFAULT_TEXT_COLOR}
                  onInput={(e) =>
                    update({ textColor: (e.target as HTMLInputElement).value })
                  }
                />
                <span class="wl-prop-color-hex">
                  {node.textColor || DEFAULT_TEXT_COLOR}
                </span>
              </div>
            </div>
            <div class="wl-prop-field">
              <label>标题样式</label>
              <div class="wl-prop-toolbar">
                <button
                  class={`wl-prop-toolbar-btn${node.fontWeight === "700" ? " active" : ""}`}
                  onClick={() =>
                    update({
                      fontWeight: node.fontWeight === "700" ? "400" : "700",
                    })
                  }
                  title="粗体"
                >
                  <strong>B</strong>
                </button>
                <button
                  class={`wl-prop-toolbar-btn${node.fontStyle === "italic" ? " active" : ""}`}
                  onClick={() =>
                    update({
                      fontStyle:
                        node.fontStyle === "italic" ? "normal" : "italic",
                    })
                  }
                  title="斜体"
                >
                  <em>I</em>
                </button>
                <div class="wl-prop-toolbar-sep" />
                <select
                  class="wl-prop-toolbar-select"
                  value={node.fontSize || DEFAULT_FONT_SIZE}
                  onChange={(e) =>
                    update({
                      fontSize: Number((e.target as HTMLSelectElement).value),
                    })
                  }
                >
                  {[8, 9, 10, 11, 12, 13, 14, 16, 18, 20, 24].map((s) => (
                    <option key={s} value={s}>
                      {s}px
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>
        );
      }

      if (sel.type === "edge") {
        const rel = props.edgeRelations.find((r) => r.id === sel.id);
        const currentLabel = rel?.label || "";
        const currentArrowType = rel?.arrowType || DEFAULT_ARROW_TYPE;
        const updateEdge = (patch: Partial<EdgeRelation>) => {
          updateEdgeRelations((prev) => {
            const idx = prev.findIndex((r) => r.id === sel.id);
            if (idx >= 0) {
              return prev.map((r, i) => (i === idx ? { ...r, ...patch } : r));
            }
            const rfEdge = rfEdges.value.find((e) => e.id === sel.id);
            if (!rfEdge) return prev;
            return [
              ...prev,
              {
                id: sel.id,
                from: rfEdge.source,
                to: rfEdge.target,
                label: "",
                arrowType: DEFAULT_ARROW_TYPE,
                ...patch,
              },
            ];
          });
        };
        const deleteEdge = async () => {
          const ok = await confirm({
            title: "删除关系",
            message: `确定要删除该关系${currentLabel ? `「${currentLabel}」` : ""}吗？不可恢复。`,
            danger: true,
            confirmText: "确认删除",
          });
          if (!ok) return;
          removeEdgeById(sel.id);
          selection.value = null;
        };
        return (
          <div class="wl-prop-panel">
            <div class="wl-prop-header">
              <span class="wl-prop-title">边属性</span>
              <button
                class="wl-prop-delete-btn"
                onClick={deleteEdge}
                title="删除边"
              >
                <PhTrash size={12} />
              </button>
            </div>
            <div class="wl-prop-field">
              <label>关系描述</label>
              <input
                value={currentLabel}
                onInput={(e) =>
                  updateEdge({ label: (e.target as HTMLInputElement).value })
                }
                placeholder="描述节点间关系..."
              />
            </div>
            <div class="wl-prop-field">
              <label>箭头类型</label>
              <div class="wl-prop-arrow-options">
                {ARROW_TYPE_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    class={`wl-prop-arrow-btn${currentArrowType === opt.value ? " active" : ""}`}
                    onClick={() => updateEdge({ arrowType: opt.value })}
                    title={opt.value}
                  >
                    {opt.icon}
                  </button>
                ))}
              </div>
            </div>
          </div>
        );
      }

      return null;
    };

    return () => (
      <Teleport to="body">
        {props.wlVisualOpen && (
          <div class="story-editor-overlay" ref={overlayRef}>
            <div class="wl-editor-shell">
              <div class="wl-editor-main">
                <div class="wl-editor-toolbar">
                  <div class="wl-editor-toolbar-left">
                    <PhGitBranch
                      size={14}
                      weight="fill"
                      style={{ color: "var(--color-accent)" }}
                    />
                    <span class="wl-editor-toolbar-title">世界线</span>
                    {props.currentWl &&
                      (editingWlName.value ? (
                        <div class="story-wl-name-edit">
                          <input
                            class="story-wl-name-input"
                            value={wlNameDraft.value}
                            onInput={(e) =>
                              (wlNameDraft.value = (
                                e.target as HTMLInputElement
                              ).value)
                            }
                            onKeydown={(e) => {
                              if (e.key === "Enter") handleSaveWlName();
                              if (e.key === "Escape") handleCancelEditWlName();
                            }}
                            autofocus
                          />
                          <button
                            class="story-wl-name-btn"
                            onClick={handleSaveWlName}
                          >
                            ✓
                          </button>
                          <button
                            class="story-wl-name-btn"
                            onClick={handleCancelEditWlName}
                          >
                            ✕
                          </button>
                        </div>
                      ) : (
                        <button
                          class="story-wl-popup-wl-name-btn"
                          onClick={handleStartEditWlName}
                          title="点击编辑世界线名称"
                        >
                          {props.currentWl.name || "主线"}
                        </button>
                      ))}
                  </div>
                  <div class="wl-editor-toolbar-right">
                    <Button size="sm" variant="secondary" onClick={handleCreateNode}>
                      <PhPlus size={12} /> 新建节点
                    </Button>
                    <button
                      class="story-editor-close-btn"
                      onClick={props.onCloseVisual}
                    >
                      <PhX size={14} weight="bold" />
                    </button>
                  </div>
                </div>
                <div class="wl-editor-canvas-area">
                  {!props.currentWl && (
                    <div class="story-wl-timeline-empty">
                      <span>暂无世界线数据</span>
                    </div>
                  )}
                  {props.currentWl && props.wlNodes.length === 0 && (
                    <div class="story-wl-timeline-empty">
                      暂无发展节点，点击“新建节点”添加
                    </div>
                  )}
                  {props.currentWl && props.wlNodes.length > 0 && (
                    <div class="story-wl-rf-container">
                      <VueFlow
                        nodes={rfNodes.value}
                        edges={rfEdges.value}
                        onNodesChange={onRfNodesChange}
                        onEdgesChange={onRfEdgesChange}
                        onConnect={onConnect}
                        onNodeClick={handleNodeClick}
                        onEdgeClick={handleEdgeClick}
                        onPaneClick={handlePaneClick}
                        onPaneReady={onRfReady}
                        minZoom={0.2}
                        maxZoom={3}
                        nodeTypes={nodeTypes as any}
                        edgeTypes={edgeTypes as any}
                        defaultEdgeOptions={{ type: "wlEdge" }}
                        connectionLineStyle={{
                          stroke: "#6366f1",
                          strokeWidth: 1.5,
                        }}
                        connectionMode={ConnectionMode.Loose}
                        deleteKeyCode="Delete"
                      >
                        <Controls showInteractive={false} position="bottom-right" />
                        <WlMiniMap
                          nodes={rfNodes.value}
                          edges={rfEdges.value}
                          selectedNodeId={selection.value?.type === "node" ? selection.value.id : undefined}
                          selectedEdgeId={selection.value?.type === "edge" ? selection.value.id : undefined}
                        />
                        <Background gap={16} />
                      </VueFlow>
                    </div>
                  )}
                </div>
              </div>
              <div class="wl-editor-sidebar">{renderPropPanel()}</div>
            </div>
          </div>
        )}

        {props.wlJsonOpen && (
          <div class="story-editor-overlay">
            <div class="story-wl-popup" ref={jsonRef}>
              <div class="story-editor-titlebar">
                <div class="story-editor-titlebar-left">
                  <span class="story-editor-chapter-id">
                    <PhCode size={12} weight="fill" />
                  </span>
                  <span class="story-wl-popup-title">世界线 JSON</span>
                </div>
                <div class="story-editor-titlebar-right">
                  <Button size="sm" variant="secondary" onClick={handleExportJson}>
                    <PhDownloadSimple size={12} /> 导出
                  </Button>
                  <button class="story-editor-close-btn" onClick={props.onCloseJson}>
                    <PhX size={14} weight="bold" />
                  </button>
                </div>
              </div>
              <div class="story-wl-popup-body">
                <pre class="story-wl-json-preview">
                  {JSON.stringify(
                    {
                      worldline: {
                        id: props.currentWl?.id,
                        name: props.currentWl?.name || "主线",
                        description: props.currentWl?.description || "",
                      },
                      nodes: props.wlNodes.map((n) => ({
                        id: n.id,
                        title: n.title || "",
                        description: n.description || "",
                        color: n.color,
                        textColor: n.textColor,
                        fontSize: n.fontSize,
                        fontWeight: n.fontWeight,
                        fontStyle: n.fontStyle,
                        x: n.x,
                        y: n.y,
                      })),
                      edges: props.edgeRelations.map((e) => ({
                        id: e.id,
                        from: e.from,
                        to: e.to,
                        label: e.label || "",
                        arrowType: e.arrowType,
                        sourceHandle: e.sourceHandle,
                        targetHandle: e.targetHandle,
                      })),
                    },
                    null,
                    2,
                  )}
                </pre>
                <div class="story-wl-text-section">
                  <div class="story-wl-text-label">text (精简文本)</div>
                  <pre class="story-wl-text-preview">
                    {serializeWorldlineText(
                      props.currentWl?.name || "主线",
                      props.wlNodes,
                      props.edgeRelations,
                    )}
                  </pre>
                </div>
              </div>
            </div>
          </div>
        )}
      </Teleport>
    );
  },
});
