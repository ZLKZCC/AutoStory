from langchain_core.tools import BaseTool

from agent.tools import audiobook, chapter, character, chatrecord, delegation, project, research, volume


class ToolRegistry:
    """工具注册表单例。"""

    instance = None

    # 业务域 → 模块（键即 assemble() 的 domains 取值）
    DOMAIN_MODULES = {
        "project": project,
        "chapter": chapter,
        "volume": volume,
        "character": character,
        "audiobook": audiobook,
        "research": research,
        "chatrecord": chatrecord,
        "delegation": delegation,
    }

    def __new__(cls):
        if cls.instance is None:
            cls.instance = super().__new__(cls)
        return cls.instance

    def __init__(self):
        if getattr(self, "initialized", False):
            return
        self.initialized = True

        # 各域工具表
        self.by_domain: dict[str, list[BaseTool]] = {
            domain: list(getattr(module, "TOOLS", []))
            for domain, module in self.DOMAIN_MODULES.items()
        }
        # 工具名 → 显示名（各域 DISPLAY 合并）
        self.display: dict[str, str] = {}
        for module in self.DOMAIN_MODULES.values():
            self.display.update(getattr(module, "DISPLAY", {}))
        # 全量工具（进程内装配一次，各节点共用同一份，不各自组装）
        self.all: list[BaseTool] = [
            tool for tools in self.by_domain.values() for tool in tools
        ]
        # 工具名 → 工具（执行期按 tool_calls 里的名字取用）
        self.by_name: dict[str, BaseTool] = {tool.name: tool for tool in self.all}

    def assemble(self, domains: list[str] | None = None) -> list[BaseTool]:
        """按业务域装配工具列表。

        domains: None = 全部；传入子集如 ["project", "research"] = 只读安全态。
        audiobook 域的 audiobook_pipeline 走子图中断，装配上与普通工具无差别。
        """
        selected = domains or list(self.by_domain.keys())
        tools: list[BaseTool] = []
        for domain in selected:
            tools.extend(self.by_domain.get(domain, []))
        return tools

    def display_name(self, tool_name: str) -> str:
        """工具名 → 前端显示名（未登记时回退工具名本身）。"""
        return self.display.get(tool_name, tool_name)


registry = ToolRegistry()
