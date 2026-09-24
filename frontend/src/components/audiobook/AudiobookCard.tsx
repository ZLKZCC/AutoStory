import { defineComponent, type PropType, watch, ref, onBeforeUnmount } from "vue";
import gsap from "gsap";
import MiniAudioPlayer from "../MiniAudioPlayer";
import { getAudioScriptAudioUrl } from "../../api/audiobook";
import ProgressRail from "./ProgressRail";
import ProposalPanel from "./ProposalPanel";
import MappingPanel from "./MappingPanel";
import ScriptPanel from "./ScriptPanel";
import NarratorPanel from "./NarratorPanel";
import NamingPanel from "./NamingPanel";
import type { AudiobookAnswer, AudiobookCardInfo, AudiobookPayload } from "./types";
import "./AudiobookCard.css";

export default defineComponent({
  name: "AudiobookCard",
  props: {
    info: { type: Object as PropType<AudiobookCardInfo>, required: true },
    onSubmit: {
      type: Function as PropType<(answer: AudiobookAnswer) => void>,
      required: true,
    },
  },
  setup(props) {
    const panelRef = ref<HTMLElement | null>(null);
    let tween: gsap.core.Tween | null = null;

    watch(() => props.info.status, (s) => {
      if (s === "awaiting" && panelRef.value) {
        tween?.kill();
        tween = gsap.fromTo(panelRef.value,
          { opacity: 0, y: 8 },
          { opacity: 1, y: 0, duration: 0.35, ease: "spring(1, 90, 12)" });
      }
    });
    onBeforeUnmount(() => { tween?.kill(); tween = null; });

    const submit = (answer: AudiobookAnswer) => props.onSubmit(answer);

    return () => {
      const info = props.info;
      const rail = (
        <ProgressRail phase={info.phase} awaiting={info.status === "awaiting"} />
      );

      if (info.status === "done") {
        const src = info.scriptId ? getAudioScriptAudioUrl(info.scriptId) : undefined;
        return (
          <div class="ab-card is-done">
            {rail}
            <p class="ab-final is-ok" title={info.phaseDetail || "有声书已生成"}>
              {info.phaseDetail || "有声书已生成"}
            </p>
            {src && (
              <div class="ab-done-player">
                <MiniAudioPlayer src={src} />
              </div>
            )}
            {(info.warnings?.length ?? 0) > 0 && (
              <ul class="ab-warnings">{info.warnings!.map((w) => <li title={w}>{w}</li>)}</ul>
            )}
          </div>
        );
      }
      if (info.status === "cancelled") {
        return (
          <div class="ab-card is-cancelled">
            {rail}
            <p class="ab-final is-dim">流程已放弃</p>
          </div>
        );
      }
      if (info.status === "confirmed") {
        return (
          <div class="ab-card is-done">
            {rail}
            <p class="ab-final is-ok" title={info.phaseDetail || "已确认"}>
              已确认{info.phaseDetail ? ` · ${info.phaseDetail}` : ""}
            </p>
          </div>
        );
      }
      if (info.status === "reverted") {
        return (
          <div class="ab-card is-cancelled">
            {rail}
            <p class="ab-final is-dim" title={info.phaseDetail || "已撤销"}>
              已撤销{info.phaseDetail ? ` · ${info.phaseDetail}` : ""}
            </p>
          </div>
        );
      }
      if (info.status === "failed") {
        return (
          <div class="ab-card is-failed">
            {rail}
            <p class="ab-final is-err" title={info.phaseDetail || "流程已中断"}>
              {info.phaseDetail || "流程已中断"}
            </p>
          </div>
        );
      }
      if (info.status === "terminated") {
        return (
          <div class="ab-card is-cancelled">
            {rail}
            <p class="ab-final is-dim" title={info.phaseDetail || "应用关闭，流程已中断"}>
              {info.phaseDetail || "应用关闭，流程已中断"}
            </p>
          </div>
        );
      }
      if (info.status === "awaiting") {
        const p = info.payload as AudiobookPayload;
        return (
          <div class="ab-card is-awaiting">
            {rail}
            <div ref={panelRef}>
              {info.subtype === "naming" && <NamingPanel payload={p as any} onSubmit={submit} />}
              {info.subtype === "proposal" && <ProposalPanel payload={p as any} onSubmit={submit} />}
              {info.subtype === "mapping" && <MappingPanel payload={p as any} onSubmit={submit} />}
              {info.subtype === "script" && <ScriptPanel payload={p as any} onSubmit={submit} />}
              {info.subtype === "narrator" && (
                <NarratorPanel payload={p as any} callId={info.callId ?? ""} onSubmit={submit} />
              )}
            </div>
          </div>
        );
      }
      return (
        <div class="ab-card is-running">
          {rail}
          <p class="ab-running-detail">
            <span class="ab-spinner" />
            <span class="ab-running-text" title={info.phaseDetail}>
              {info.phaseDetail || "处理中…"}
            </span>
          </p>
        </div>
      );
    };
  },
});
