import { defineComponent, ref, watch, onBeforeUnmount, Teleport } from "vue";
import gsap from "gsap";
import { PhX } from "@phosphor-icons/vue";
import "./Modal.css";

export default defineComponent({
  name: "Modal",
  props: {
    open: { type: Boolean, default: false },
    title: { type: String, default: "" },
    width: { type: Number, default: 460 },
  },
  emits: ["close"],
  setup(props, { slots, emit }) {
    const overlayRef = ref<HTMLDivElement | null>(null);
    const panelRef = ref<HTMLDivElement | null>(null);
    let outsideClickCount = 0;
    let outsideClickTimer: ReturnType<typeof setTimeout> | null = null;

    const animateIn = () => {
      const overlay = overlayRef.value;
      const panel = panelRef.value;
      if (!overlay || !panel) return;

      gsap.set(overlay, { opacity: 0 });
      gsap.set(panel, { opacity: 0, scale: 0.96, y: 12 });

      gsap.to(overlay, { opacity: 1, duration: 0.22, ease: "power2.out" });
      gsap.to(panel, {
        opacity: 1,
        scale: 1,
        y: 0,
        duration: 0.4,
        ease: "power3.out",
      });
    };

    const animateOut = () => {
      const overlay = overlayRef.value;
      const panel = panelRef.value;
      if (!overlay || !panel) return Promise.resolve();

      return new Promise<void>((resolve) => {
        gsap.to(overlay, { opacity: 0, duration: 0.16, ease: "power2.in" });
        gsap.to(panel, {
          opacity: 0,
          scale: 0.97,
          y: -6,
          duration: 0.2,
          ease: "power3.in",
          onComplete: resolve,
        });
      });
    };

    const handleClose = async () => {
      await animateOut();
      emit("close");
    };

    const onKeydown = (e: KeyboardEvent) => {
      if (e.key === "Escape") handleClose();
    };

    watch(
      () => props.open,
      (open) => {
        if (open) {
          requestAnimationFrame(animateIn);
          window.addEventListener("keydown", onKeydown);
        } else {
          window.removeEventListener("keydown", onKeydown);
        }
      },
    );

    onBeforeUnmount(() => {
      window.removeEventListener("keydown", onKeydown);
      if (outsideClickTimer) clearTimeout(outsideClickTimer);
    });

    const onOverlayClick = (e: MouseEvent) => {
      if (e.target !== overlayRef.value) return;
      outsideClickCount += 1;
      if (outsideClickTimer) clearTimeout(outsideClickTimer);
      if (outsideClickCount >= 3) {
        outsideClickCount = 0;
        handleClose();
      } else {
        outsideClickTimer = setTimeout(() => {
          outsideClickCount = 0;
        }, 800);
      }
    };

    return () =>
      props.open ? (
        <Teleport to="body">
          <div ref={overlayRef} class="modal-overlay" onClick={onOverlayClick}>
            <div ref={panelRef} class="modal-panel" style={{ maxWidth: `${props.width}px` }}>
              <div class="modal-header">
                <span class="modal-title">{props.title}</span>
                <button class="modal-close-btn" onClick={handleClose}>
                  <PhX size={16} weight="light" />
                </button>
              </div>
              <div class="modal-body">{slots.default?.()}</div>
              {slots.footer && (
                <div class="modal-footer">{slots.footer()}</div>
              )}
            </div>
          </div>
        </Teleport>
      ) : null;
  },
});
