import { defineComponent, type PropType } from "vue";

export default defineComponent({
  name: "PanelResizer",
  props: {
    side: {
      type: String as PropType<"left" | "right">,
      default: "left",
    },
    step: { type: Number, default: 16 },
  },
  emits: ["dragstart", "dragmove", "dragend", "reset"],
  setup(props, { emit }) {
    let startX = 0;
    let dragging = false;

    const onPointerDown = (e: PointerEvent) => {
      if (e.button !== 0) return;
      dragging = true;
      startX = e.clientX;
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
      document.body.classList.add("panel-resizing");
      emit("dragstart");
      e.preventDefault();
    };

    const onPointerMove = (e: PointerEvent) => {
      if (!dragging) return;
      const dx = e.clientX - startX;
      if (dx === 0) return;
      emit("dragmove", props.side === "left" ? -dx : dx);
    };

    const endDrag = (e: PointerEvent) => {
      if (!dragging) return;
      dragging = false;
      const el = e.currentTarget as HTMLElement;
      if (el.hasPointerCapture(e.pointerId)) {
        el.releasePointerCapture(e.pointerId);
      }
      document.body.classList.remove("panel-resizing");
      emit("dragend");
    };

    const onKeydown = (e: KeyboardEvent) => {
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        emit("dragstart");
        emit("dragmove", -props.step);
        emit("dragend");
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        emit("dragstart");
        emit("dragmove", props.step);
        emit("dragend");
      } else if (e.key === "Enter" || e.key === "Escape") {
        e.preventDefault();
        emit("reset");
      }
    };

    return () => (
      <div
        class={`panel-resizer ${props.side}`}
        role="separator"
        aria-orientation="vertical"
        tabindex={0}
        title="拖拽调整宽度，双击恢复默认"
        onPointerdown={onPointerDown}
        onPointermove={onPointerMove}
        onPointerup={endDrag}
        onPointercancel={endDrag}
        onKeydown={onKeydown}
        onDblclick={() => emit("reset")}
      />
    );
  },
});
