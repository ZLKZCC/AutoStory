from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class ChatRecordBase(BaseModel):
    # role: user | assistant（旧库行 "Human" 读取时兼容）；type: message | tool_call | interrupt | audiobook
    role: str = Field("user", description="角色")
    content: str = Field("", description="内容")
    timestamp: datetime = Field(..., description="时间戳")
    type: str = Field("", description="种类")
    # 行协议外层：tool_call / audiobook 行绑定的 call_id（镜像行据此认卡，不进 content）
    extra: str = Field("", description="扩展位（call_id）")
    model_config = ConfigDict(from_attributes=True)

class ChatRecordCreate(ChatRecordBase):
    pass

class ChatRecordDetail(ChatRecordBase):
    id: int = Field(..., description="聊天消息id")
