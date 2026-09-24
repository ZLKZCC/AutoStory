from langchain_core.messages import AnyMessage
from langgraph.graph import MessagesState


class AgentState(MessagesState):
    project_name: str          # 项目名（注入 system prompt 让 AI 知道在哪个项目里创作）
    project_description: str   # 项目描述（同上；concept/worldline 仍由查询工具按需取）
    summary: str               # 跨轮对话摘要（compress 节点产出，context 节点消费）
    project_summary: str       # 项目摘要（Project.Project_summary，常驻上下文）
    context_window: int        # 当前模型上下文窗口（think 节点写入，压缩阈值与前端圆环共用）
    system_prompt: list[AnyMessage]  # 渲染好的系统提示（context 节点写；独立字段、不在 messages 里）
