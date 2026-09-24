from pydantic import BaseModel, Field


class Assignment(BaseModel):
    target: str = Field(..., description="做什么：写作目标/分析目标/总结目标")
    must_include: list[str] = Field(default_factory=list, description="必须覆盖的要点")
    style: str = Field(default="自然、克制、有画面感", description="文风关键词（写作类任务用）")
    technique: str = Field(default="", description="指定手法（如：环境烘托/留白/对话推进）")
    length: str = Field(default="800-15000字", description="篇幅")
    pov: str = Field(default="第三人称", description="叙事视角（写作类任务用）")
    material: str = Field(default="", description="精选素材（范文片段/前情摘要/待分析文本），已由调用方裁剪")
    forbidden: list[str] = Field(default_factory=list, description="本任务额外禁项")


def render_assignment(assignment: Assignment) -> str:
    lines = [
        f"【任务】{assignment.target}",
        f"【必含要点】{'；'.join(assignment.must_include) or '无'}",
        f"【文风】{assignment.style}",
        f"【手法】{assignment.technique or '不限'}",
        f"【篇幅】{assignment.length}｜【视角】{assignment.pov}",
    ]
    if assignment.material:
        lines.append(f"【参考素材】\n{assignment.material}")
    if assignment.forbidden:
        lines.append(f"【额外禁令】{'；'.join(assignment.forbidden)}")
    return "\n".join(lines)
