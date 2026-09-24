import { defineComponent, ref, type PropType } from "vue";
import type { VolumeWithChapters, ChapterInfo } from "../api";
import { PhPlus, PhTrash, PhCaretRight, PhCaretDown } from "@phosphor-icons/vue";

const DRAG_THRESHOLD = 6;
const EDGE = 36;
const SCROLL_SPEED = 9;
const LAND_MS = 240;

export default defineComponent({
  name: "VolumeTree",
  props: {
    projectName: { type: String, required: true },
    volumes: { type: Array as PropType<VolumeWithChapters[]>, default: () => [] },
    selectedId: { type: Number as PropType<number | null>, default: null },
    onSelectChapter: { type: Function as PropType<(id: number) => void>, required: true },
    onToggleExpand: { type: Function as PropType<(volumeId: number) => void>, required: true },
    onCreateChapterInVolume: {
      type: Function as PropType<(volumeId: number, chapterId?: number, position?: "before" | "after") => void>,
      required: true,
    },
    onDeleteChapter: { type: Function as PropType<(chapterId: number) => void>, required: true },
    onMoveChapter: {
      type: Function as PropType<
        (dragId: number, targetId: number, position: "before" | "after", targetVolumeId: number) => void
      >,
      required: true,
    },
    onLoadMore: { type: Function as PropType<(volumeId: number) => void>, required: true },
  },
  setup(props) {
    const insertMenuId = ref<number | null>(null);
    const closeMenu = () => { insertMenuId.value = null; };
    const toggleMenu = (id: number) => {
      const next = insertMenuId.value === id ? null : id;
      insertMenuId.value = next;
      if (next != null) { document.addEventListener("click", closeMenu, { once: true }); }
    };
    const handleInsert = (volumeId: number, chapterId: number, position: "before" | "after") => {
      insertMenuId.value = null;
      props.onCreateChapterInVolume(volumeId, chapterId, position);
    };

    const listEl = ref<HTMLDivElement | null>(null);
    let suppressClick = false;
    let landTimer: ReturnType<typeof setTimeout> | null = null;

    type DragNode = {
      el: HTMLElement;
      volId: number;
      chId: number;
      host: HTMLElement | null;   // 所属卷的章节容器（占位条挂载点）
    };

    const drag = {
      pending: false, active: false, pointerId: -1, id: 0, fromPos: -1,
      startX: 0, startY: 0, lastX: 0, lastY: 0, grabX: 0, grabY: 0,
      tilt: 0, tiltTarget: 0, scale: 1, ghost: null as HTMLElement | null,
      nodes: [] as DragNode[], srcNode: null as DragNode | null, previewS: -1,
      placeholder: null as HTMLElement | null, raf: 0,
    };

    const hitTest = (viewY: number, rects: DOMRect[]): number => {
      for (let i = 0; i < drag.nodes.length; i++) {
        if (i === drag.fromPos) continue;
        const rc = rects[i];
        if (rc.height === 0) continue;
        if (viewY < rc.top + rc.height / 2) return i;
      }
      return drag.nodes.length;
    };

    const slotTarget = (s: number): { ch: DragNode; mode: "before" | "after" } | null => {
      const n = drag.nodes;
      const r = s < n.length ? n[s] : null;
      if (r && r.chId >= 0) return { ch: r, mode: "before" as const };
      const l = s > 0 ? n[s - 1] : null;
      if (l && l.chId >= 0) return { ch: l, mode: "after" as const };
      for (let i = s; i < n.length; i++) {
        if (n[i].chId >= 0) return { ch: n[i], mode: "before" as const };
      }
      return null;
    };

    const moveSlot = (s: number) => {
      const tgt = slotTarget(s);
      const slot = drag.placeholder;
      if (!tgt || !tgt.ch.host || !slot) return;
      const before = tgt.mode === "before" ? tgt.ch.el : tgt.ch.el.nextSibling;
      if (slot !== before) tgt.ch.host.insertBefore(slot, before ?? null);
    };

    const tick = () => {
      if (!drag.active) return;
      drag.tilt += (drag.tiltTarget - drag.tilt) * 0.22;
      drag.tiltTarget *= 0.86;
      if (drag.scale < 1.045) drag.scale = Math.min(1.045, drag.scale + 0.009);

      const list = listEl.value;
      if (list) {
        const r = list.getBoundingClientRect();
        if (drag.lastY < r.top + EDGE) list.scrollTop -= SCROLL_SPEED;
        else if (drag.lastY > r.bottom - EDGE) list.scrollTop += SCROLL_SPEED;
        const rects = drag.nodes.map((nd) => nd.el.getBoundingClientRect());
        const s = hitTest(drag.lastY, rects);
        if (s !== drag.previewS) { drag.previewS = s; moveSlot(s); }
      }

      if (drag.ghost) {
        drag.ghost.style.transform =
          `translate3d(${drag.lastX - drag.grabX}px, ${drag.lastY - drag.grabY}px, 0) ` +
          `rotate(${drag.tilt.toFixed(2)}deg) scale(${drag.scale.toFixed(3)})`;
      }
      drag.raf = requestAnimationFrame(tick);
    };

    const beginDrag = () => {
      const list = listEl.value;
      const srcEl = list?.querySelector<HTMLElement>(`[data-ch-id="${drag.id}"]`);
      if (!list || !srcEl) { drag.pending = false; return; }
      drag.active = true;
      closeMenu();
      suppressClick = false;
      document.body.classList.add("chapter-tree-dragging");

      const rect = srcEl.getBoundingClientRect();
      const ghost = srcEl.cloneNode(true) as HTMLElement;
      ghost.classList.add("chapter-tree-ghost");
      ghost.style.left = "0px";
      ghost.style.top = "0px";
      ghost.style.width = `${rect.width}px`;
      ghost.querySelectorAll(".chapter-tree-insert-menu").forEach((n) => n.remove());
      drag.grabX = drag.lastX - rect.left;
      drag.grabY = drag.lastY - rect.top;
      ghost.style.transform = `translate3d(${drag.lastX - drag.grabX}px, ${drag.lastY - drag.grabY}px, 0)`;
      document.body.appendChild(ghost);
      drag.ghost = ghost;

      drag.nodes = [];
      let fromPos = -1;
      list.querySelectorAll<HTMLElement>(".volume-header, [data-ch-id], .volume-load-more").forEach((el) => {
        const item = el.closest<HTMLElement>(".volume-tree-item");
        if (!item) return;
        const volId = Number(item.dataset.volId);
        const host = item.querySelector<HTMLElement>(".volume-chapters-list");
        const isSpacer = el.classList.contains("volume-header") || el.classList.contains("volume-load-more");
        const chId = isSpacer ? -1 : Number(el.dataset.chId);
        if (chId === drag.id) fromPos = drag.nodes.length;
        drag.nodes.push({ el, volId, chId, host });
      });
      if (fromPos < 0) { drag.active = false; drag.pending = false; return; }
      drag.fromPos = fromPos;
      drag.srcNode = drag.nodes[fromPos];

      srcEl.classList.add("chapter-tree-src-hidden");
      const slot = document.createElement("div");
      slot.className = "chapter-tree-drop-slot";
      slot.style.height = `${rect.height}px`;
      srcEl.parentElement?.insertBefore(slot, srcEl);
      drag.placeholder = slot;
      drag.previewS = fromPos; // 初始槽 = 原位（tick 中位次不变则不重插）
      drag.raf = requestAnimationFrame(tick);
    };

    const finishDrag = (commit: boolean) => {
      const { ghost, id } = drag;
      const s = drag.previewS >= 0 ? drag.previewS : drag.fromPos;
      drag.active = false;
      drag.pending = false;
      drag.pointerId = -1;
      cancelAnimationFrame(drag.raf);
      document.body.classList.remove("chapter-tree-dragging");

      drag.placeholder?.remove();
      drag.placeholder = null;
      drag.srcNode?.el.classList.remove("chapter-tree-src-hidden");
      drag.srcNode = null;

      if (commit) {
        const tgt = slotTarget(s);
        if (tgt && tgt.ch.chId >= 0 && tgt.ch.chId !== id) {
          props.onMoveChapter(id, tgt.ch.chId, tgt.mode, tgt.ch.volId);
        }
      }

      if (ghost) {
        if (landTimer != null) clearTimeout(landTimer);
        landTimer = setTimeout(() => { landTimer = null; ghost.remove(); }, LAND_MS + 40);
        requestAnimationFrame(() => {
          const real = listEl.value?.querySelector<HTMLElement>(`[data-ch-id="${id}"]`);
          if (real) {
            const r = real.getBoundingClientRect();
            ghost.style.transition = `transform ${LAND_MS}ms cubic-bezier(0.22, 1, 0.3, 1), opacity ${LAND_MS}ms ease-out`;
            ghost.style.transform = `translate3d(${r.left}px, ${r.top}px, 0) rotate(0deg) scale(1)`;
            ghost.style.opacity = "0";
            real.classList.add("just-landed");
            setTimeout(() => real.classList.remove("just-landed"), 540);
          } else { ghost.remove(); }
        });
      }
    };

    const onItemPointerDown = (e: PointerEvent, id: number) => {
      if (e.button !== 0) return;
      const target = e.target as HTMLElement;
      if (target.closest(".chapter-tree-insert, .chapter-tree-insert-menu, .chapter-tree-del")) return;
      drag.pending = true;
      drag.active = false;
      drag.pointerId = e.pointerId;
      drag.id = id;
      drag.previewS = -1;
      drag.tilt = drag.tiltTarget = 0;
      drag.scale = 1;
      drag.startX = drag.lastX = e.clientX;
      drag.startY = drag.lastY = e.clientY;
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    };

    const onItemPointerMove = (e: PointerEvent) => {
      if (!drag.pending || e.pointerId !== drag.pointerId) return;
      if (!drag.active) {
        const dx = e.clientX - drag.startX;
        const dy = e.clientY - drag.startY;
        if (dx * dx + dy * dy < DRAG_THRESHOLD * DRAG_THRESHOLD) return;
        beginDrag();
      }
      if (!drag.active) return;
      drag.tiltTarget = Math.max(-9, Math.min(9, drag.tiltTarget + (e.clientX - drag.lastX) * 0.22));
      drag.lastX = e.clientX;
      drag.lastY = e.clientY;
    };

    const onItemPointerUp = (e: PointerEvent) => {
      if (e.pointerId !== drag.pointerId) return;
      const wasDrag = drag.active;
      drag.pending = false;
      drag.pointerId = -1;
      if (wasDrag) { suppressClick = true; finishDrag(true); }
    };

    const onItemPointerCancel = (e: PointerEvent) => {
      if (e.pointerId !== drag.pointerId) return;
      if (drag.active) finishDrag(false);
      drag.pending = false;
      drag.pointerId = -1;
    };

    const renderChapterItem = (chapter: ChapterInfo, volumeId: number) => {
      const active = chapter.id === props.selectedId;
      return (
        <div
          data-ch-id={chapter.id}
          class={`chapter-tree-item ${active ? "active" : ""}`}
          onClick={() => {
            if (suppressClick) { suppressClick = false; return; }
            props.onSelectChapter(chapter.id);
          }}
          onPointerdown={(e: PointerEvent) => onItemPointerDown(e, chapter.id)}
          onPointermove={onItemPointerMove}
          onPointerup={onItemPointerUp}
          onPointercancel={onItemPointerCancel}
        >
          <span class="chapter-tree-index">{String(chapter.chapter_index + 1).padStart(2, "0")}</span>
          <span class="chapter-tree-body">
            <span class="chapter-tree-name">{chapter.title || "未命名章节"}</span>
            <span class="chapter-tree-words">{(chapter.word_count || 0).toLocaleString()} 字</span>
          </span>
          <span
            class="chapter-tree-insert"
            title="插入章节"
            onClick={(e: MouseEvent) => {
              e.stopPropagation();
              toggleMenu(chapter.id);
            }}
          >
            <PhPlus size={12} weight="light" />
          </span>
          {insertMenuId.value === chapter.id && (
            <div class="chapter-tree-insert-menu" onClick={(e: MouseEvent) => e.stopPropagation()}>
              <button class="chapter-tree-insert-option" onClick={() => handleInsert(volumeId, chapter.id, "before")}>
                在「{chapter.title || "未命名章节"}」前插入
              </button>
              <button class="chapter-tree-insert-option" onClick={() => handleInsert(volumeId, chapter.id, "after")}>
                在「{chapter.title || "未命名章节"}」后插入
              </button>
            </div>
          )}
          <span
            class="chapter-tree-del"
            title="删除章节"
            onClick={(e: MouseEvent) => {
              e.stopPropagation();
              props.onDeleteChapter(chapter.id);
            }}
          >
            <PhTrash size={12} weight="light" />
          </span>
        </div>
      );
    };

    const renderVolume = (vol: VolumeWithChapters) => {
      const expanded = vol.expanded ?? false;
      const chapters = vol.chapters;

      return (
        <div class="volume-tree-item" data-vol-id={vol.id}>
          <div class="volume-header" onClick={() => props.onToggleExpand(vol.id)}>
            {expanded ? <PhCaretDown size={16} /> : <PhCaretRight size={16} />}
            <span class="volume-name">{vol.name || `第${vol.volume_index + 1}卷`}</span>
            <span class="volume-stats">
              {vol.chapter_count ?? "?"}章 · {(vol.total_word_count || 0).toLocaleString()}字
            </span>
            <span
              class="volume-plus-btn"
              title="在此卷末尾添加章节"
              onClick={(e: MouseEvent) => {
                e.stopPropagation();
                props.onCreateChapterInVolume(vol.id);
              }}
            >
              <PhPlus size={14} weight="light" />
            </span>
          </div>

          {expanded && (
            <div class="volume-chapters-list">
              {vol.loading && (!chapters || chapters.length === 0) && (
                <div class="volume-loading">加载中...</div>
              )}
              {chapters && chapters.length > 0 && (
                <>
                  {chapters.map((chapter: ChapterInfo) => renderChapterItem(chapter, vol.id))}
                  {vol.hasMore && (
                    <button class="volume-load-more" onClick={() => props.onLoadMore(vol.id)}>
                      加载更多...
                    </button>
                  )}
                </>
              )}
              {chapters && chapters.length === 0 && !vol.loading && (
                <div class="volume-empty-hint">卷内暂无章节，点击右上 + 新建</div>
              )}
            </div>
          )}
        </div>
      );
    };

    return () => (
      <div class="volume-tree">
        <div class="chapter-tree-header">
          <span class="chapter-tree-title">目录</span>
          {props.volumes.length > 0 && (
            <span class="chapter-tree-count">
              {props.volumes.reduce((sum, v) => sum + (v.chapter_count || 0), 0)} 章 ·{" "}
              {props.volumes.reduce((sum, v) => sum + (v.total_word_count || 0), 0).toLocaleString()} 字
            </span>
          )}
        </div>

        {props.volumes.length === 0 && (
          <div class="volume-tree-empty">还没有卷，点击上方「+」创建第一卷</div>
        )}

        <div class="chapter-tree-list" ref={listEl}>
          {props.volumes.map((vol) => renderVolume(vol))}
        </div>
      </div>
    );
  },
});
