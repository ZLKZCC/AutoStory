import { defineComponent, ref, watch, onBeforeUnmount } from "vue";
import gsap from "gsap";
import "./PageLoader.css";

const MIN_DISPLAY_MS = 600;

export default defineComponent({
  name: "PageLoader",
  props: {
    loading: { type: Boolean, default: false },
    text: { type: String, default: "加载中..." },
  },
  setup(props, { slots }) {
    const loaderRef = ref<HTMLDivElement | null>(null);
    const logoRef = ref<HTMLDivElement | null>(null);
    const barRef = ref<HTMLDivElement | null>(null);
    const contentRef = ref<HTMLDivElement | null>(null);

    const showLoader = ref(props.loading);
    const contentVisible = ref(!props.loading);
    let showTime = props.loading ? Date.now() : 0;
    let activeTl: ReturnType<typeof gsap.timeline> | null = null;

    const killTl = () => {
      if (activeTl) {
        activeTl.kill();
        activeTl = null;
      }
    };

    const animateIn = () => {
      if (!loaderRef.value) return;
      showTime = Date.now();
      killTl();
      const tl = gsap.timeline();
      activeTl = tl;

      if (logoRef.value) {
        tl.fromTo(
          logoRef.value,
          { scale: 0.75, opacity: 0 },
          { scale: 1, opacity: 1, duration: 0.5, ease: "power2.out" },
        );
      }
      if (barRef.value) {
        tl.fromTo(
          barRef.value,
          { opacity: 0, y: 6 },
          { opacity: 1, y: 0, duration: 0.4, ease: "power2.out" },
          "-=0.2",
        );
      }
      gsap.set(loaderRef.value, { opacity: 0 });
      tl.to(loaderRef.value, { opacity: 1, duration: 0.3 }, 0);
    };

    const handleExit = () => {
      if (!loaderRef.value) {
        showLoader.value = false;
        contentVisible.value = true;
        return;
      }

      const elapsed = Date.now() - showTime;
      const delay = Math.max(0, MIN_DISPLAY_MS - elapsed);
      killTl();

      const tl = gsap.timeline({
        delay: delay / 1000,
        onComplete: () => {
          showLoader.value = false;
          contentVisible.value = true;
        },
      });
      activeTl = tl;

      tl.to(loaderRef.value, { opacity: 0, duration: 0.35, ease: "power2.inOut" });
      if (logoRef.value) {
        tl.to(logoRef.value, { scale: 1.12, opacity: 0, duration: 0.35, ease: "power2.in" }, 0);
      }
      if (barRef.value) {
        tl.to(barRef.value, { opacity: 0, y: -6, duration: 0.3, ease: "power2.in" }, 0);
      }
    };

    watch(
      () => props.loading,
      (loading) => {
        if (!loading && showLoader.value) {
          handleExit();
        } else if (loading && !showLoader.value) {
          showLoader.value = true;
          contentVisible.value = false;
        }
      },
    );

    watch(showLoader, (show) => {
      if (show) requestAnimationFrame(animateIn);
    });

    watch(contentVisible, (visible) => {
      if (!visible) return;
      requestAnimationFrame(() => {
        if (!contentRef.value) return;
        gsap.fromTo(
          contentRef.value,
          { opacity: 0, y: 12 },
          { opacity: 1, y: 0, duration: 0.45, ease: "power2.out" },
        );
      });
    });

    onBeforeUnmount(killTl);

    return () => (
      <div class="page-loader-root">
        {showLoader.value && (
          <div class="page-loader-overlay" ref={loaderRef}>
            <div class="page-loader-inner">
              <div class="page-loader-logo" ref={logoRef}>
                <img src="/logo.png" alt="" class="page-loader-logo-img" />
                <div class="page-loader-brand">
                  <span class="page-loader-auto">Auto</span>
                  <span class="page-loader-story">Story</span>
                </div>
              </div>
              <div class="page-loader-bar-wrap" ref={barRef}>
                <div class="page-loader-bar">
                  <div class="page-loader-bar-fill" />
                </div>
                <div class="page-loader-text">{props.text}</div>
              </div>
            </div>
          </div>
        )}
        {contentVisible.value && (
          <div class="page-loader-content" ref={contentRef}>
            {slots.default?.()}
          </div>
        )}
      </div>
    );
  },
});
