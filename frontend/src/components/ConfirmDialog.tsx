import { defineComponent, ref, type PropType } from "vue";
import { inject, provide } from "vue";
import Modal from "./Modal";
import Button from "./Button";
import { PhWarning } from "@phosphor-icons/vue";

export interface ConfirmOptions {
  title: string;
  message: string;
  danger?: boolean;
  confirmText?: string;
}

type ConfirmFn = (opts: ConfirmOptions) => Promise<boolean>;

const CONFIRM_KEY = Symbol("confirm-dialog");

export function useConfirm(): { confirm: ConfirmFn } {
  const fn = inject<ConfirmFn>(CONFIRM_KEY);
  if (!fn) throw new Error("useConfirm 需在 <ConfirmDialog /> 内部使用");
  return { confirm: fn };
}

export default defineComponent({
  name: "ConfirmDialog",
  props: {
    provide: { type: Boolean, default: true },
  },
  setup(props, { slots }) {
    const open = ref(false);
    const opts = ref<ConfirmOptions | null>(null);
    let resolve: ((v: boolean) => void) | null = null;

    const confirm: ConfirmFn = (o) =>
      new Promise<boolean>((res) => {
        resolve?.(false);
        opts.value = o;
        open.value = true;
        resolve = res;
      });

    if (props.provide) provide(CONFIRM_KEY, confirm);

    const done = (v: boolean) => {
      open.value = false;
      resolve?.(v);
      resolve = null;
    };

    return () => (
      <>
        {slots.default?.()}
        <Modal
          open={open.value}
          onClose={() => done(false)}
          title={opts.value?.title || "确认操作"}
          width={400}
        >
          <div style={{ display: "flex", gap: "12px", alignItems: "flex-start" }}>
            {opts.value?.danger && (
              <PhWarning
                size={20}
                weight="fill"
                style={{
                  color: "var(--color-error)",
                  flexShrink: 0,
                  marginTop: "2px",
                }}
              />
            )}
            <div
              style={{
                fontSize: "13px",
                color: "var(--color-text-secondary)",
                lineHeight: 1.6,
              }}
            >
              {opts.value?.message}
            </div>
          </div>
          <div
            style={{
              display: "flex",
              gap: "8px",
              justifyContent: "flex-end",
              marginTop: "16px",
            }}
          >
            <Button size="sm" variant="ghost" onClick={() => done(false)}>
              取消
            </Button>
            <Button
              size="sm"
              variant={opts.value?.danger ? "danger" : "primary"}
              onClick={() => done(true)}
            >
              {opts.value?.confirmText || "确认"}
            </Button>
          </div>
        </Modal>
      </>
    );
  },
});
