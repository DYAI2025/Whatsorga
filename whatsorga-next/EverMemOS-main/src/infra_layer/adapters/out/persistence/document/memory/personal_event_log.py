"""
PersonalEventLog Beanie ODM 模型

存储从个人情景记忆中提取的事件日志（原子事实），每个个人 episode 可以有多条原子事实。
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from beanie import Indexed
from core.oxm.mongo.document_base import DocumentBase
from pydantic import Field, ConfigDict
from pymongo import IndexModel, ASCENDING, DESCENDING
from core.oxm.mongo.audit_base import AuditBase
from beanie import PydanticObjectId


class PersonalEventLog(DocumentBase, AuditBase):
    """
    个人事件日志文档模型

    存储从个人情景记忆（EpisodicMemory）中提取的原子事实。
    每个个人 episode 可以有多条原子事实，用于细粒度的事实检索。
    """

    # 核心字段（必填）
    user_id: str = Field(..., description="用户ID")
    atomic_fact: str = Field(..., min_length=1, description="原子事实内容")
    parent_episode_id: str = Field(..., description="父情景记忆的 event_id")

    # 时间信息
    timestamp: datetime = Field(..., description="事件发生时间")

    # 群组和参与者信息
    group_id: Optional[str] = Field(default=None, description="群组ID")
    participants: Optional[List[str]] = Field(default=None, description="相关参与者")

    # 向量和模型
    vector: Optional[List[float]] = Field(default=None, description="原子事实的文本向量")
    vector_model: Optional[str] = Field(default=None, description="使用的向量化模型")

    # 事件类型和扩展信息
    event_type: Optional[str] = Field(default=None, description="事件类型，如 Conversation")
    extend: Optional[Dict[str, Any]] = Field(default=None, description="扩展字段")

    model_config = ConfigDict(
        collection="personal_event_logs",
        validate_assignment=True,
        json_encoders={datetime: lambda dt: dt.isoformat()},
        json_schema_extra={
            "example": {
                "user_id": "user_12345",
                "atomic_fact": "用户在2024年1月1日去了成都",
                "parent_episode_id": "episode_001",
                "timestamp": "2024-01-01T10:00:00+08:00",
                "group_id": "group_travel",
                "participants": ["张三", "李四"],
                "vector": [0.1, 0.2, 0.3],
                "vector_model": "text-embedding-3-small",
                "event_type": "Conversation",
                "extend": {"location": "成都"}
            }
        },
    )

    @property
    def event_id(self) -> Optional[PydanticObjectId]:
        """兼容性属性，返回文档ID"""
        return self.id

    class Settings:
        """Beanie 设置"""

        name = "personal_event_logs"

        indexes = [
            # 用户ID索引
            IndexModel(
                [("user_id", ASCENDING)],
                name="idx_user_id",
            ),
            # 父情景记忆索引
            IndexModel(
                [("parent_episode_id", ASCENDING)],
                name="idx_parent_episode",
            ),
            # 用户ID和父情景记忆复合索引
            IndexModel(
                [("user_id", ASCENDING), ("parent_episode_id", ASCENDING)],
                name="idx_user_parent",
            ),
            # 用户ID和时间戳复合索引
            IndexModel(
                [("user_id", ASCENDING), ("timestamp", DESCENDING)],
                name="idx_user_timestamp",
            ),
            # 群组ID索引
            IndexModel(
                [("group_id", ASCENDING)],
                name="idx_group_id",
                sparse=True,
            ),
            # 创建时间索引
            IndexModel([("created_at", DESCENDING)], name="idx_created_at"),
            # 更新时间索引
            IndexModel([("updated_at", DESCENDING)], name="idx_updated_at"),
        ]

        validate_on_save = True
        use_state_management = True


# 导出模型
__all__ = ["PersonalEventLog"]

