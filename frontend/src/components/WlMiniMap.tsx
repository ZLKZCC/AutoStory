import { defineComponent, computed, ref, type PropType } from "vue";
import { Panel, useVueFlow } from "@vue-flow/core";

interface MiniNode {
  id: string;
  position: { x: number; y: number };
  data?: { color?: string };
}

interface MiniEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string;
  targetHandle?: string;
  data?: { arrowType?: string };
}

const NODE_SIZE = 80;
const W = 200;
const H = 150;
const PAD = 12;

type Transform = { scale: number; ox: number; oy: number };

const toScreen = (t: Transform, fx: number, fy: number) => ({
  x: fx * t.scale + t.ox,
  y: fy * t.scale + t.oy,
});

const HANDLE_R = 5;
const HANDLES = {
  top: { dx: 0.5, dy: 0, ix: 0, iy: 1 },
  bottom: { dx: 0.5, dy: 1, ix: 0, iy: -1 },
  left: { dx: 0, dy: 0.5, ix: 1, iy: 0 },
  right: { dx: 1, dy: 0.5, ix: -1, iy: 0 },
} as const;
type HandleId = keyof typeof HANDLES;
const SOURCE_ORDER: HandleId[] = ["bottom", "right", "top", "left"];
const TARGET_ORDER: HandleId[] = ["top", "left", "bottom", "right"];
const pickHandle = (id: string | undefined, order: HandleId[]): HandleId =>
  id && (order as string[]).includes(id) ? (id as HandleId) : order[0];

const ctrlOffset = (d: number) => (d >= 0 ? 0.5 * d : 6.25 * Math.sqrt(-d));
const control = (pos: HandleId, x1: number, y1: number, x2: number, y2: number) => {
  switch (pos) {
    case "left":
      return { x: x1 - ctrlOffset(x1 - x2), y: y1 };
    case "right":
      return { x: x1 + ctrlOffset(x2 - x1), y: y1 };
    case "top":
      return { x: x1, y: y1 - ctrlOffset(y1 - y2) };
    default:
      return { x: x1, y: y1 + ctrlOffset(y2 - y1) };
  }
};

export default defineComponent({
  name: "WlMiniMap",
  props: {
    nodes: { type: Array as PropType<MiniNode[]>, default: () => [] },
    edges: { type: Array as PropType<MiniEdge[]>, default: () => [] },
    selectedNodeId: { type: String, default: undefined },
    selectedEdgeId: { type: String, default: undefined },
  },
  setup(props) {
    const { viewport, dimensions, setViewport } = useVueFlow();

    const transform = computed<Transform>(() => {
      const ns = props.nodes;
      let minX = Infinity,
        minY = Infinity,
        maxX = -Infinity,
        maxY = -Infinity;
      for (const n of ns) {
        minX = Math.min(minX, n.position.x);
        maxX = Math.max(maxX, n.position.x + NODE_SIZE);
        minY = Math.min(minY, n.position.y);
        maxY = Math.max(maxY, n.position.y + NODE_SIZE);
      }
      const vp = viewport.value;
      const dim = dimensions.value;
      if (dim.width && dim.height) {
        const vx = -vp.x / vp.zoom;
        const vy = -vp.y / vp.zoom;
        minX = Math.min(minX, vx);
        maxX = Math.max(maxX, vx + dim.width / vp.zoom);
        minY = Math.min(minY, vy);
        maxY = Math.max(maxY, vy + dim.height / vp.zoom);
      }
      if (!isFinite(minX)) return { scale: 1, ox: W / 2, oy: H / 2 };
      const scale = Math.min(
        (W - PAD * 2) / (maxX - minX),
        (H - PAD * 2) / (maxY - minY),
      );
      return {
        scale,
        ox: (W - (maxX - minX) * scale) / 2 - minX * scale,
        oy: (H - (maxY - minY) * scale) / 2 - minY * scale,
      };
    });

    const nodeRadius = computed(() =>
      Math.max((NODE_SIZE / 2) * transform.value.scale, 2.5),
    );

    const edgeShapes = computed(() => {
      const t = transform.value;
      const byId = new Map(props.nodes.map((n) => [n.id, n]));
      return props.edges.flatMap((e) => {
        const s = byId.get(e.source);
        const t2 = byId.get(e.target);
        if (!s || !t2) return [];
        const sh = pickHandle(e.sourceHandle, SOURCE_ORDER);
        const th = pickHandle(e.targetHandle, TARGET_ORDER);
        const sd = HANDLES[sh];
        const td = HANDLES[th];
        const p0f = {
          x: s.position.x + sd.dx * NODE_SIZE - sd.ix * HANDLE_R,
          y: s.position.y + sd.dy * NODE_SIZE - sd.iy * HANDLE_R,
        };
        const p3f = {
          x: t2.position.x + td.dx * NODE_SIZE - td.ix * HANDLE_R,
          y: t2.position.y + td.dy * NODE_SIZE - td.iy * HANDLE_R,
        };
        const c1f = control(sh, p0f.x, p0f.y, p3f.x, p3f.y);
        const c2f = control(th, p3f.x, p3f.y, p0f.x, p0f.y);
        const p0 = toScreen(t, p0f.x, p0f.y);
        const p1 = toScreen(t, c1f.x, c1f.y);
        const p2 = toScreen(t, c2f.x, c2f.y);
        const p3 = toScreen(t, p3f.x, p3f.y);
        const norm = (x: number, y: number) => {
          const len = Math.hypot(x, y);
          return len ? { x: x / len, y: y / len } : { x: 0, y: 0 };
        };
        let dEnd = norm(p3.x - p2.x, p3.y - p2.y);
        if (!dEnd.x && !dEnd.y) dEnd = { x: td.ix, y: td.iy };
        let dStart = norm(p0.x - p1.x, p0.y - p1.y);
        if (!dStart.x && !dStart.y) dStart = { x: sd.ix, y: sd.iy };
        const at = e.data?.arrowType;
        const selected = props.selectedEdgeId === e.id;
        const stroke = selected ? "#6366f1" : "#6b7280";
        const L = 5;
        const hw = L * 0.45;
        const head = (tip: { x: number; y: number }, d: { x: number; y: number }) =>
          `${tip.x},${tip.y} ${tip.x - d.x * L - d.y * hw},${tip.y - d.y * L + d.x * hw} ${tip.x - d.x * L + d.y * hw},${tip.y - d.y * L - d.x * hw}`;
        const heads: string[] = [];
        if (at !== "undirected" && at !== "unidirectional-left") heads.push(head(p3, dEnd));
        if (at === "unidirectional-left" || at === "bidirectional") heads.push(head(p0, dStart));
        return [
          {
            id: e.id,
            d: `M${p0.x},${p0.y} C${p1.x},${p1.y} ${p2.x},${p2.y} ${p3.x},${p3.y}`,
            heads,
            stroke,
            width: selected ? 1.8 : 1,
          },
        ];
      });
    });

    const nodeShapes = computed(() => {
      const t = transform.value;
      return props.nodes.map((n) => {
        const c = toScreen(t, n.position.x + NODE_SIZE / 2, n.position.y + NODE_SIZE / 2);
        return {
          id: n.id,
          cx: c.x,
          cy: c.y,
          r: nodeRadius.value,
          fill: n.data?.color || "#6366f1",
          selected: props.selectedNodeId === n.id,
        };
      });
    });

    const viewRect = computed(() => {
      const t = transform.value;
      const vp = viewport.value;
      const dim = dimensions.value;
      if (!dim.width) return null;
      const tl = toScreen(t, -vp.x / vp.zoom, -vp.y / vp.zoom);
      const br = toScreen(
        t,
        -vp.x / vp.zoom + dim.width / vp.zoom,
        -vp.y / vp.zoom + dim.height / vp.zoom,
      );
      return { x: tl.x, y: tl.y, w: br.x - tl.x, h: br.y - tl.y };
    });

    const maskPath = computed(() => {
      const vr = viewRect.value;
      if (!vr) return "";
      return `M0,0 H${W} V${H} H0 Z M${vr.x},${vr.y} h${vr.w} v${vr.h} h${-vr.w} Z`;
    });

    const svgEl = ref<SVGElement | null>(null);
    const dragging = ref(false);

    const toFlow = (clientX: number, clientY: number) => {
      const rect = svgEl.value!.getBoundingClientRect();
      const t = transform.value;
      return {
        x: (clientX - rect.left - t.ox) / t.scale,
        y: (clientY - rect.top - t.oy) / t.scale,
      };
    };

    const centerOn = (fx: number, fy: number) => {
      const vp = viewport.value;
      const dim = dimensions.value;
      if (!dim.width) return;
      setViewport({ x: dim.width / 2 - fx * vp.zoom, y: dim.height / 2 - fy * vp.zoom, zoom: vp.zoom });
    };

    const onPointerDown = (e: PointerEvent) => {
      dragging.value = true;
      (e.currentTarget as SVGElement).setPointerCapture(e.pointerId);
      const f = toFlow(e.clientX, e.clientY);
      centerOn(f.x, f.y);
    };

    const onPointerMove = (e: PointerEvent) => {
      if (!dragging.value) return;
      const f = toFlow(e.clientX, e.clientY);
      centerOn(f.x, f.y);
    };

    const onPointerUp = () => {
      dragging.value = false;
    };

    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const vp = viewport.value;
      const next = Math.min(4, Math.max(0.2, vp.zoom * (e.deltaY < 0 ? 1.15 : 1 / 1.15)));
      const f = toFlow(e.clientX, e.clientY);
      setViewport({
        x: f.x * vp.zoom + vp.x - f.x * next,
        y: f.y * vp.zoom + vp.y - f.y * next,
        zoom: next,
      });
    };

    return () => (
      <Panel position="bottom-left" class="wl-minimap">
        <svg
          ref={svgEl}
          width={W}
          height={H}
          role="img"
          aria-label="世界线缩略图"
          class={{ pannable: dragging.value }}
          onPointerdown={onPointerDown}
          onPointermove={onPointerMove}
          onPointerup={onPointerUp}
          onPointerleave={onPointerUp}
          onWheel={onWheel}
        >
          {maskPath.value && (
            <path d={maskPath.value} fill="rgba(245, 242, 238, 0.68)" fill-rule="evenodd" />
          )}
          {edgeShapes.value.map((e) => (
            <path key={e.id} d={e.d} fill="none" stroke={e.stroke} stroke-width={e.width} />
          ))}
          {nodeShapes.value.map((n) => (
            <circle
              key={n.id}
              cx={n.cx}
              cy={n.cy}
              r={n.r}
              fill={n.fill}
              stroke={n.selected ? "#6366f1" : "rgba(30, 22, 16, 0.18)"}
              stroke-width={n.selected ? 2 : 1}
            />
          ))}
          {edgeShapes.value.map((e) => (
            <g key={`${e.id}-heads`}>
              {e.heads.map((h, i) => (
                <polygon key={i} points={h} fill={e.stroke} />
              ))}
            </g>
          ))}
          {viewRect.value && (
            <rect
              x={viewRect.value.x}
              y={viewRect.value.y}
              width={viewRect.value.w}
              height={viewRect.value.h}
              fill="rgba(99, 102, 241, 0.06)"
              stroke="rgba(30, 22, 16, 0.35)"
              stroke-width={1}
              pointer-events="none"
            />
          )}
        </svg>
      </Panel>
    );
  },
});
