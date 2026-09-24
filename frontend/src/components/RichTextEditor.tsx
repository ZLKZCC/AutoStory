import { defineComponent, ref, watch, onBeforeUnmount, type PropType, type VNodeChild } from "vue";
import { useEditor, EditorContent } from "@tiptap/vue-3";
import StarterKit from "@tiptap/starter-kit";
import Underline from "@tiptap/extension-underline";
import TextAlign from "@tiptap/extension-text-align";
import Placeholder from "@tiptap/extension-placeholder";
import Highlight from "@tiptap/extension-highlight";
import {
  PhTextB,
  PhTextItalic,
  PhTextUnderline,
  PhTextStrikethrough,
  PhTextAlignLeft,
  PhTextAlignCenter,
  PhTextAlignRight,
  PhTextAlignJustify,
  PhListBullets,
  PhListNumbers,
  PhTextH,
  PhHighlighterCircle,
  PhArrowCounterClockwise,
  PhArrowClockwise,
  PhQuotes,
  PhCode,
  PhSparkle,
} from "@phosphor-icons/vue";

export default defineComponent({
  name: "RichTextEditor",
  props: {
    content: { type: String, default: "" },
    onChange: { type: Function as PropType<(html: string) => void>, required: true },
    placeholder: { type: String, default: "开始写作..." },
    className: { type: String, default: "" },
    toolbarClassName: { type: String, default: "" },
    bodyClassName: { type: String, default: "" },
    readOnly: { type: Boolean, default: false },
    minRows: { type: Number, default: 6 },
    onAskAboutSelection: {
      type: Function as PropType<(text: string) => void>,
      default: undefined,
    },
  },
  setup(props) {
    const stateVersion = ref(0);
    const rootEl = ref<HTMLDivElement | null>(null);
    const selectionText = ref("");
    const selectionPos = ref<{ top: number; left: number } | null>(null);

    const editorRef = useEditor({
      extensions: [
        StarterKit.configure({
          heading: { levels: [1, 2, 3] },
        }),
        Underline,
        TextAlign.configure({
          types: ["heading", "paragraph"],
        }),
        Placeholder.configure({
          placeholder: props.placeholder,
        }),
        Highlight.configure({
          multicolor: false,
        }),
      ],
      content: props.content,
      editable: !props.readOnly,
      onUpdate: ({ editor: e }) => {
        props.onChange(e.getHTML());
      },
      onTransaction: () => {
        stateVersion.value++;
      },
      editorProps: {
        attributes: {
          class: "rte-body",
          style: `min-height: ${props.minRows * 1.75}rem`,
        },
      },
    });

    watch(
      () => props.content,
      (content) => {
        const editor = editorRef.value;
        if (editor && !editor.isFocused && editor.getHTML() !== content) {
          editor.commands.setContent(content);
        }
      },
    );

    watch(
      () => props.readOnly,
      (readOnly) => {
        if (editorRef.value) editorRef.value.setEditable(!readOnly);
      },
    );

    const handleSelectionUpdate = ({ editor: e }: { editor: any }) => {
      if (!props.onAskAboutSelection) return;
      const { from, to, empty } = e.state.selection;
      if (empty || from === to) {
        selectionText.value = "";
        selectionPos.value = null;
        return;
      }
      const text = e.state.doc.textBetween(from, to, "\n");
      if (!text || !text.trim()) {
        selectionText.value = "";
        selectionPos.value = null;
        return;
      }
      selectionText.value = text;
      const coords = e.view.coordsAtPos(to);
      const root = rootEl.value;
      if (root) {
        const rect = root.getBoundingClientRect();
        selectionPos.value = {
          top: coords.top - rect.top - 32,
          left: Math.max(8, Math.min(coords.left - rect.left, rect.width - 96)),
        };
      }
    };

    watch(
      editorRef,
      (editor) => {
        if (!editor) return;
        editor.on("selectionUpdate", handleSelectionUpdate);
      },
      { immediate: true },
    );

    onBeforeUnmount(() => {
      const editor = editorRef.value;
      if (editor) editor.off("selectionUpdate", handleSelectionUpdate);
      editorRef.value?.destroy();
    });

    const act = (fn: () => void) => (e: MouseEvent) => {
      e.preventDefault();
      fn();
    };

    const handleAskAi = (e: MouseEvent) => {
      e.preventDefault();
      e.stopPropagation();
      const text = selectionText.value;
      selectionText.value = "";
      selectionPos.value = null;
      props.onAskAboutSelection?.(text);
    };

    return () => {
      const editor = editorRef.value;
      if (!editor) return null;
      void stateVersion.value;

      const tb = (
        command: string,
        args?: any,
        icon?: VNodeChild,
        label?: string,
      ) => (
        <button
          key={command + (args ?? "")}
          class={`rte-btn ${editor.isActive(command, args) ? "active" : ""}`}
          onMousedown={act(() =>
            (editor.chain().focus() as any)[command](args).run(),
          )}
          title={label || command}
          type="button"
          tabindex={-1}
        >
          {icon || <span class="rte-btn-label">{label || command}</span>}
        </button>
      );

      return (
        <div class={`rte ${props.className}`} ref={rootEl}>
          {!props.readOnly && (
            <div class={`rte-toolbar ${props.toolbarClassName}`}>
              <div class="rte-toolbar-group">
                {tb(
                  "toggleHeading",
                  { level: 1 },
                  <PhTextH size={14} weight="bold" />,
                  "标题1",
                )}
                {tb("toggleHeading", { level: 2 }, <PhTextH size={13} />, "标题2")}
                {tb(
                  "toggleHeading",
                  { level: 3 },
                  <PhTextH size={12} weight="light" />,
                  "标题3",
                )}
              </div>
              <div class="rte-toolbar-sep" />
              <div class="rte-toolbar-group">
                {tb(
                  "toggleBold",
                  undefined,
                  <PhTextB size={14} weight="bold" />,
                  "加粗",
                )}
                {tb("toggleItalic", undefined, <PhTextItalic size={14} />, "斜体")}
                {tb(
                  "toggleUnderline",
                  undefined,
                  <PhTextUnderline size={14} />,
                  "下划线",
                )}
                {tb(
                  "toggleStrike",
                  undefined,
                  <PhTextStrikethrough size={14} />,
                  "删除线",
                )}
                {tb(
                  "toggleHighlight",
                  undefined,
                  <PhHighlighterCircle size={14} />,
                  "高亮",
                )}
              </div>
              <div class="rte-toolbar-sep" />
              <div class="rte-toolbar-group">
                {tb("setTextAlign", "left", <PhTextAlignLeft size={14} />, "左对齐")}
                {tb(
                  "setTextAlign",
                  "center",
                  <PhTextAlignCenter size={14} />,
                  "居中",
                )}
                {tb(
                  "setTextAlign",
                  "right",
                  <PhTextAlignRight size={14} />,
                  "右对齐",
                )}
                {tb(
                  "setTextAlign",
                  "justify",
                  <PhTextAlignJustify size={14} />,
                  "两端对齐",
                )}
              </div>
              <div class="rte-toolbar-sep" />
              <div class="rte-toolbar-group">
                {tb(
                  "toggleBulletList",
                  undefined,
                  <PhListBullets size={14} />,
                  "无序列表",
                )}
                {tb(
                  "toggleOrderedList",
                  undefined,
                  <PhListNumbers size={14} />,
                  "有序列表",
                )}
                {tb("toggleBlockquote", undefined, <PhQuotes size={14} />, "引用")}
                {tb("toggleCodeBlock", undefined, <PhCode size={14} />, "代码块")}
              </div>
              <div class="rte-toolbar-sep" />
              <div class="rte-toolbar-group">
                {tb("undo", undefined, <PhArrowCounterClockwise size={14} />, "撤销")}
                {tb("redo", undefined, <PhArrowClockwise size={14} />, "重做")}
              </div>
            </div>
          )}
          <EditorContent
            editor={editor}
            class={`rte-content ${props.bodyClassName}`}
          />
          {props.onAskAboutSelection && selectionText.value.trim() && selectionPos.value && (
            <div
              class="rte-ask-ai"
              style={{
                top: `${selectionPos.value.top}px`,
                left: `${selectionPos.value.left}px`,
              }}
              onMousedown={handleAskAi}
              title="把选段发给对话"
            >
              <PhSparkle size={12} weight="fill" />
              <span>问 AI</span>
            </div>
          )}
        </div>
      );
    };
  },
});
