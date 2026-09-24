import { defineComponent, ref, computed, type PropType } from "vue";
import { PhCheck, PhX, PhCaretDown } from "@phosphor-icons/vue";
import type { ToolCallInfo } from "../stores/chat";
import "./ToolCallBubble.css";

const ARG_LABELS: Record<string, string> = {
  project_name: "作品",
  action: "操作",
  title: "标题",
  name: "名称",
  id: "ID",
  query: "查询",
  query_type: "类型",
  url: "链接",
  path: "路径",
  content: "内容",
  section_id: "段落",
  chapter_id: "章节",
  chapter_index: "章节",
  character_id: "角色",
  worldline_id: "世界线",
  fragment_id: "片段",
  category: "分类",
  character: "角色",
  chapter: "章节",
  section: "段落",
};

const ARG_KEYS = Object.keys(ARG_LABELS);

const displayVal = (v: unknown, max = 64): string => {
  const s = typeof v === "string" ? v : JSON.stringify(v);
  if (s == null) return "";
  return s.length > max ? s.slice(0, max) + "…" : s;
};

interface Tok {
  t: string;
  c: string; // css class
}

function tokenizeJson(json: string): Tok[] {
  const toks: Tok[] = [];
  let i = 0;
  const push = (t: string, c: string) => toks.push({ t, c });
  while (i < json.length) {
    const ch = json[i];
    if (ch === '"') {
      let j = i + 1;
      while (j < json.length && json[j] !== '"') {
        if (json[j] === "\\") j++; // 跳过转义
        j++;
      }
      const str = json.slice(i, j + 1);
      let k = j + 1;
      while (k < json.length && /\s/.test(json[k])) k++;
      const isKey = json[k] === ":";
      push(str, isKey ? "tj-key" : "tj-str");
      i = j + 1;
    } else if (/[0-9]/.test(ch) || (ch === "-" && /[0-9]/.test(json[i + 1] || ""))) {
      let j = i + 1;
      while (j < json.length && /[0-9.eE+-]/.test(json[j])) j++;
      push(json.slice(i, j), "tj-num");
      i = j;
    } else if (json.startsWith("true", i) || json.startsWith("false", i) || json.startsWith("null", i)) {
      const word = json.startsWith("true", i) ? "true" : json.startsWith("false", i) ? "false" : "null";
      push(word, "tj-bool");
      i += word.length;
    } else {
      push(ch, "tj-punc");
      i++;
    }
  }
  return toks;
}

export default defineComponent({
  name: "ToolCallBubble",
  props: {
    toolCall: { type: Object as PropType<ToolCallInfo>, required: true },
  },
  setup(props) {
    const resultExpanded = ref(false);
    const tc = computed(() => props.toolCall);

    const argRows = computed(() => {
      const a = tc.value.arguments || {};
      return ARG_KEYS.filter((k) => a[k] != null && a[k] !== "").map((k) => ({
        key: k,
        label: ARG_LABELS[k],
        value: displayVal(a[k]),
      }));
    });

    const resultToks = computed<Tok[] | null>(() => {
      const r = tc.value.result;
      if (r == null) return null;
      if (typeof r === "string") return null; // 纯文本走 pre
      try {
        return tokenizeJson(JSON.stringify(r, null, 2).slice(0, 1400));
      } catch {
        return null;
      }
    });

    const resultText = computed(() => {
      const r = tc.value.result;
      if (r == null) return "";
      return typeof r === "string" ? (r.length > 800 ? r.slice(0, 800) + "…" : r) : "";
    });

    return () => {
      const t = tc.value;
      return (
        <div class={`tool-call tc-state-${t.status}`}>
          <div class="tool-call-main">
            <span class="tool-call-label">{t.displayName || t.toolName}</span>
            <span class="tool-call-status-text">
              {t.status === "calling" ? "执行中" : t.status === "success" ? "完成" : "失败"}
            </span>
            <span class={`tool-call-status tool-call-status-${t.status}`}>
              {t.status === "calling" && <span class="tool-call-spinner" />}
              {t.status === "success" && <PhCheck size={12} weight="bold" />}
              {t.status === "error" && <PhX size={12} weight="bold" />}
            </span>
          </div>

          {argRows.value.length > 0 && (
            <div class="tool-call-args">
              {argRows.value.map((r) => (
                <div class="tool-call-arg-row" key={r.key}>
                  <span class="tool-call-arg-key">{r.label}</span>
                  <span class="tool-call-arg-val">{r.value}</span>
                </div>
              ))}
            </div>
          )}

          {t.status === "success" && t.result != null && (
            <div class="tool-call-result">
              <button
                class="tool-call-toggle"
                onClick={() => (resultExpanded.value = !resultExpanded.value)}
              >
                <PhCaretDown size={10} weight="bold" class={resultExpanded.value ? "open" : ""} />
                {resultExpanded.value ? "收起结果" : "查看结果"}
              </button>
              {resultExpanded.value &&
                (resultToks.value ? (
                  <div class="tool-call-json">
                    {resultToks.value.map((tok, i) => (
                      <span key={i} class={tok.c}>{tok.t}</span>
                    ))}
                  </div>
                ) : (
                  <pre class="tool-call-pre">{resultText.value}</pre>
                ))}
            </div>
          )}

          {t.status === "error" && t.error && (
            <div class="tool-call-error">{t.error}</div>
          )}
        </div>
      );
    };
  },
});
