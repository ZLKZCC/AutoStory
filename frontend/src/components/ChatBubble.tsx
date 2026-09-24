import { defineComponent, ref, computed, type PropType } from "vue";
import { marked } from "marked";
import { PhCopy, PhCheck } from "@phosphor-icons/vue";
import { useToast } from "../stores/toast";
import Avatar from "./Avatar";
import DataChangeBubble from "./DataChangeBubble";
import ToolCallBubble from "./ToolCallBubble";
import { AudiobookCard, type AudiobookAnswer } from "./audiobook";
import type { ChatMessage } from "../stores/chat";
import "./ChatBubble.css";

const renderMarkdown = (content: string) =>
  marked.parse(content, { async: false }) as string;

export default defineComponent({
  name: "ChatBubble",
  props: {
    message: { type: Object as PropType<ChatMessage>, required: true },
    showSender: { type: Boolean, default: false },
    onDataChangeConfirm: { type: Function as PropType<(msgId: string) => void>, default: undefined },
    onDataChangeRevert: { type: Function as PropType<(msgId: string) => void>, default: undefined },
    onAudiobookSubmit: {
      type: Function as PropType<(msgId: string, answer: AudiobookAnswer) => void>,
      default: undefined,
    },
  },
  setup(props) {
    const copied = ref(false);
    const { addToast } = useToast();

    const msg = computed(() => props.message);
    const html = computed(() => renderMarkdown(msg.value.content || ""));

    const canCopy = computed(
      () =>
        (msg.value.role === "user" ||
          (msg.value.role === "agent" && msg.value.status !== "thinking")) &&
        msg.value.content,
    );

    const handleCopy = () => {
      navigator.clipboard.writeText(msg.value.content || "").then(() => {
        copied.value = true;
        addToast({ type: "success", title: "已复制到剪贴板", duration: 1500 });
        setTimeout(() => (copied.value = false), 1500);
      });
    };

    const renderCopyBtn = () =>
      canCopy.value ? (
        <button
          class={`chat-copy-btn ${copied.value ? "copied" : ""}`}
          onClick={handleCopy}
          title="复制"
        >
          {copied.value ? <PhCheck size={13} weight="bold" /> : <PhCopy size={13} weight="light" />}
        </button>
      ) : null;

    const renderAgentBody = () => {
      const m = msg.value;
      if (m.status === "thinking") {
        return (
          <div class="chat-msg-agent-thinking">
            <span class="thinking-dots">
              <span class="thinking-dot" />
              <span class="thinking-dot" />
              <span class="thinking-dot" />
            </span>
            {m.statusText && <span class="thinking-status-text">{m.statusText}</span>}
          </div>
        );
      }
      if (m.status === "streaming") {
        return (
          <div class="chat-msg-bubble-wrap">
            <div class="chat-msg-bubble chat-msg-agent chat-msg-streaming">
              <div class="chat-msg-markdown" innerHTML={html.value} />
              <span class="streaming-cursor">
                <span class="cursor-dots">
                  <span class="cursor-dot" />
                  <span class="cursor-dot" />
                  <span class="cursor-dot" />
                </span>
              </span>
            </div>
            {renderCopyBtn()}
          </div>
        );
      }
      return (
        <div class="chat-msg-bubble-wrap">
          <div class="chat-msg-bubble chat-msg-agent">
            <div class="chat-msg-markdown" innerHTML={html.value} />
          </div>
          {renderCopyBtn()}
        </div>
      );
    };

    return () => {
      const m = msg.value;

      if (m.role === "agent" && m.status === "done" && !m.content) {
        return null;
      }

      if (m.role === "system") {
        return <div class="chat-msg chat-msg-system">{m.content}</div>;
      }

      const isUser = m.role === "user";
      const avatarActive =
        !isUser &&
        m.role === "agent" &&
        (m.status === "thinking" || m.status === "streaming");

      return (
        <div class={`chat-msg chat-msg-${m.role} ${isUser ? "chat-msg-user" : ""}`}>
          <div class={`chat-avatar-slot${props.showSender ? " has-avatar" : ""}`}>
            {props.showSender && (
              <Avatar kind={isUser ? "user" : "agent"} size={30} active={avatarActive} />
            )}
          </div>

          <div class="chat-msg-content">
            {isUser && (
              <>
                {props.showSender && <div class="chat-msg-sender">你</div>}
                <div class="chat-msg-bubble-wrap">
                  <div class="chat-msg-bubble">{m.content}</div>
                  {renderCopyBtn()}
                </div>
              </>
            )}

            {m.role === "agent" && (
              <>
                {props.showSender && <div class="chat-msg-sender">栗山眠</div>}
                {renderAgentBody()}
              </>
            )}

            {m.role === "tool_call" && m.toolCall && (
              <ToolCallBubble toolCall={m.toolCall} />
            )}

            {m.role === "data_change" && m.dataChange && (
              <DataChangeBubble
                data={m.dataChange}
                onConfirm={props.onDataChangeConfirm ? () => props.onDataChangeConfirm!(m.id) : undefined}
                onRevert={props.onDataChangeRevert ? () => props.onDataChangeRevert!(m.id) : undefined}
              />
            )}

            {m.role === "audiobook" && m.audiobook && (
              <AudiobookCard info={m.audiobook}
                onSubmit={(answer: AudiobookAnswer) => props.onAudiobookSubmit?.(m.id, answer)} />
            )}
          </div>
        </div>
      );
    };
  },
});
