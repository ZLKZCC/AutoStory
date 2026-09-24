import { defineComponent, ref, onMounted, onBeforeUnmount, type PropType } from "vue";
import { PhCaretDown } from "@phosphor-icons/vue";

export default defineComponent({
  name: "CustomDropdown",
  props: {
    value: { type: String, default: "" },
    options: { type: Array as PropType<{ value: string; label: string }[]>, default: () => [] },
    placeholder: { type: String, default: "请选择" },
  },
  emits: ["update:value", "change"],
  setup(props, { emit }) {
    const open = ref(false);
    const rootEl = ref<HTMLDivElement | null>(null);

    const onDocMouseDown = (e: MouseEvent) => {
      if (rootEl.value && !rootEl.value.contains(e.target as Node)) {
        open.value = false;
      }
    };
    onMounted(() => document.addEventListener("mousedown", onDocMouseDown));
    onBeforeUnmount(() => document.removeEventListener("mousedown", onDocMouseDown));

    return () => {
      const selected = props.options.find((o) => o.value === props.value);

      return (
        <div ref={rootEl} style={{ position: "relative", flex: 1 }}>
          <button
            class="input-field"
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              cursor: props.options.length > 0 ? "pointer" : "not-allowed",
              fontSize: "12px",
              textAlign: "left",
              opacity: props.options.length === 0 ? 0.5 : 1,
              transition: "border-color 0.15s ease, box-shadow 0.15s ease",
            }}
            onMouseenter={(e) => {
              if (props.options.length > 0) {
                (e.currentTarget as HTMLElement).style.borderColor =
                  "var(--color-accent)";
                (e.currentTarget as HTMLElement).style.boxShadow =
                  "0 0 0 2px rgba(217, 104, 48, 0.08)";
              }
            }}
            onMouseleave={(e) => {
              if (props.options.length > 0) {
                (e.currentTarget as HTMLElement).style.borderColor =
                  "var(--color-border)";
                (e.currentTarget as HTMLElement).style.boxShadow = "none";
              }
            }}
            onClick={() => props.options.length > 0 && (open.value = !open.value)}
          >
            <span
              style={{
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {selected ? selected.label : props.placeholder}
            </span>
            <PhCaretDown size={12} style={{ flexShrink: 0, marginLeft: "4px" }} />
          </button>
          {open.value && props.options.length > 0 && (
            <div
              style={{
                position: "absolute",
                top: "100%",
                left: 0,
                right: 0,
                zIndex: 100,
                marginTop: "2px",
                background: "var(--color-surface-solid)",
                border: "1px solid var(--color-border)",
                borderRadius: "var(--radius-sm)",
                overflow: "hidden",
              }}
            >
              {props.options.map((opt, idx) => (
                <button
                  key={opt.value}
                  style={{
                    display: "block",
                    width: "100%",
                    padding: "8px 12px",
                    fontSize: "12px",
                    textAlign: "left",
                    background:
                      opt.value === props.value
                        ? "var(--color-accent-light)"
                        : "transparent",
                    color:
                      opt.value === props.value
                        ? "var(--color-accent)"
                        : "var(--color-text-primary)",
                    border: "none",
                    borderBottom:
                      idx < props.options.length - 1
                        ? "1px solid var(--color-border-light)"
                        : "none",
                    cursor: "pointer",
                    transformOrigin: "left center",
                    transition:
                      "background 0.15s ease, color 0.15s ease, transform 0.15s ease, padding-left 0.15s ease",
                  }}
                  onMouseenter={(e) => {
                    const el = e.currentTarget as HTMLElement;
                    if (opt.value !== props.value) {
                      el.style.background = "var(--color-accent-subtle)";
                      el.style.color = "var(--color-accent)";
                    }
                    el.style.transform = "scale(1.02)";
                    el.style.paddingLeft = "16px";
                  }}
                  onMouseleave={(e) => {
                    const el = e.currentTarget as HTMLElement;
                    if (opt.value !== props.value) {
                      el.style.background = "transparent";
                      el.style.color = "var(--color-text-primary)";
                    }
                    el.style.transform = "scale(1)";
                    el.style.paddingLeft = "12px";
                  }}
                  onClick={() => {
                    emit("update:value", opt.value);
                    emit("change", opt.value);
                    open.value = false;
                  }}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          )}
        </div>
      );
    };
  },
});
