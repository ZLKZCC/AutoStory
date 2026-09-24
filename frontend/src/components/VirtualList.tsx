import { defineComponent, ref, type PropType, type VNode } from "vue";
import { PhArrowUp } from "@phosphor-icons/vue";
import "./VirtualList.css";

export default defineComponent({
  name: "VirtualList",
  props: {
    data: { type: Array as PropType<any[]>, default: () => [] },
    renderItem: {
      type: Function as PropType<(item: any, index: number) => VNode>,
      required: true,
    },
    itemKey: {
      type: Function as PropType<(item: any, index: number) => string | number>,
      default: undefined,
    },
    hasMore: { type: Boolean, default: false },
    loadingMore: { type: Boolean, default: false },
    onLoadMore: { type: Function as PropType<() => void>, default: undefined },
    totalCount: { type: Number, default: undefined },
    emptyContent: { type: null as unknown as PropType<VNode | string | null>, default: null },
    footer: { type: null as unknown as PropType<VNode | null>, default: null },
  },
  setup(props) {
    const scrollRef = ref<HTMLDivElement | null>(null);
    const showScrollTop = ref(false);

    const handleScroll = (e: Event) => {
      const el = e.target as HTMLDivElement;
      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
      showScrollTop.value = !atBottom;
      if (atBottom && props.hasMore && !props.loadingMore && props.onLoadMore) {
        props.onLoadMore();
      }
    };

    const handleScrollTop = () => {
      scrollRef.value?.scrollTo({ top: 0, behavior: "smooth" });
    };

    return () => (
      <div class="vlist-wrapper">
        <div
          ref={scrollRef}
          onScroll={handleScroll}
          style={{ height: "100%", overflowY: "auto" }}
        >
          {props.data.length === 0 ? (
            <div class="vlist-empty">{props.emptyContent}</div>
          ) : (
            props.data.map((item, index) => (
              <div key={props.itemKey ? props.itemKey(item, index) : index}>
                {props.renderItem(item, index)}
              </div>
            ))
          )}
          <div class="vlist-footer">
            {props.loadingMore && (
              <div class="vlist-loader">
                <span class="vlist-loader-dot" />
                <span class="vlist-loader-dot" />
                <span class="vlist-loader-dot" />
              </div>
            )}
            {props.footer}
          </div>
        </div>
        {showScrollTop.value && (
          <button class="vlist-scroll-top" onClick={handleScrollTop} title="回到顶部">
            <PhArrowUp size={14} weight="bold" />
          </button>
        )}
        {props.totalCount !== undefined && props.totalCount > 0 && (
          <div class="vlist-count">共 {props.totalCount} 项</div>
        )}
      </div>
    );
  },
});
