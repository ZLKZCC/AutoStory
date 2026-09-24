from langchain_core.messages import HumanMessage, SystemMessage

from agent.subagents.base import invoke_with_tools
from agent.subagents.prompts import SUMMARIZER_PERSONA, SUMMARY_KINDS, SUMMARY_KIND_LENGTHS
from agent.tools.kb.summary import TOOLS as SUMMARY_KB_TOOLS


async def summarize(texts: list[str], previous: str = "", kind: str = "chat") -> str:
    """
    texts:    待总结的内容片段列表
    previous: 旧摘要（merge 类必传）
    kind:     场景标签，见 SUMMARY_KINDS；输出字数上限按 kind 从 SUMMARY_KIND_LENGTHS 取
              （逐层收敛：章≤1000 / 卷≤2000 / 全局≤3000 / 对话 merge~1000）。
              场景标签是轻量提示，方法论由子 agent 自己查 sm_ 库。
    """
    scene = SUMMARY_KINDS.get(kind, SUMMARY_KINDS["chat"])
    length_cap = SUMMARY_KIND_LENGTHS.get(kind, SUMMARY_KIND_LENGTHS["chat"])
    parts = []
    if previous:
        parts.append(f"【旧摘要】\n{previous}")
    parts.append("【新内容】\n" + "\n".join(text for text in texts if text))

    messages = [
        SystemMessage(
            f"{SUMMARIZER_PERSONA}\n\n{scene}。去修辞、保事实、高度提炼，"
            f"产出不超过 {length_cap} 字的摘要。"
        ),
        HumanMessage("需要总结的内容如下:\n\n" + "\n\n".join(parts)),
    ]
    return await invoke_with_tools(messages, SUMMARY_KB_TOOLS, purpose="summarize")
