

class AgentSettings:
    """agent 可调参数。改这里的值，下一次取用处即生效。"""

    instance = None

    def __new__(cls):
        if cls.instance is None:
            cls.instance = super().__new__(cls)
        return cls.instance

    def __init__(self):
        if getattr(self, "initialized", False):
            return
        self.initialized = True

        # ── 轮内压缩 ──
        self.compress_ratio = 0.7      # 消息 token 达上下文窗口 70% 即触发压缩
        self.keep_tail = 8             # 压缩时保留的近端原文条数（起点，仍按 token 继续往前收）
        self.chars_per_token = 1.5     # token 近似计数系数（中文 1 汉字 ≈ 0.67 token，偏保守早压）

        # ── 子 agent ──
        self.max_tool_iter = 10        # 多轮检索上限（防模型无限调工具不收敛）


settings = AgentSettings()
