"""工具通用辅助：从运行期 RunnableConfig 读当前项目。

project_id 不再放 AgentState，改为由 streaming 层注入 config["configurable"]，
工具函数声明 `config: RunnableConfig` 形参（LangGraph 自动注入），再经本辅助取出。
"""
from langchain_core.runnables.config import RunnableConfig


def current_project(config: RunnableConfig) -> int:
    """取出当前项目 id。

    agent_stream.run 在组装 config 时把 project_id 塞进 configurable；
    resume 每轮重新传 config，故该值在整条流的生命周期内稳定。
    """
    return (config or {}).get("configurable", {}).get("project_id", 0)