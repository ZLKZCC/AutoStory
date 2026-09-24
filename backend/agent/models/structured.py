import json

from langchain_core.runnables import Runnable


class StructuredRunnable(Runnable):
    """bind_tools + 解析 tool_call → schema 实例

    两条解析路径：
      1) 优先取 tool_calls[0].args（模型按约束调了 tool）
      2) 兜底：模型没调 tool 而把 JSON 直接吐进 content（部分模型偏好如此）
    两者都失败 → 抛 ValueError，交由调用方重试

    注意 self._bound / self._schema 必须带下划线：Runnable 是 pydantic 模型，
    给不带下划线的实例属性赋值会被当字段校验而抛 ValueError（object has no field），
    它们未声明为字段，故不能改名成 bound / schema。
    """

    def __init__(self, model, schema):
        # bind_tools 接受 pydantic 类，各厂商内部 convert_to_openai_tool 生成 tool 定义
        self._bound = model.bind_tools([schema])
        self._schema = schema

    def parse_response(self, ai):
        if getattr(ai, "tool_calls", None):
            args = ai.tool_calls[0]["args"]
            if isinstance(args, str):          # 极少数实现返回未解析的 JSON 串
                args = json.loads(args)
            return self._schema.model_validate(args)

        content = (getattr(ai, "content", None) or "").strip()
        if content and content[0] in "[{":
            try:
                return self._schema.model_validate(json.loads(content))
            except Exception:
                pass

        raise ValueError(
            "结构化输出失败：模型未返回 tool_call，content 也非合法 JSON；"
            f"content={content[:120]!r}")

    def invoke(self, input, config=None, **kwargs):
        return self.parse_response(self._bound.invoke(input, config))

    async def ainvoke(self, input, config=None, **kwargs):
        return self.parse_response(await self._bound.ainvoke(input, config))


def structured_model(model, schema):
    """统一结构化输出入口：返回 Runnable（messages 列表 → schema 实例）"""
    return StructuredRunnable(model, schema)
