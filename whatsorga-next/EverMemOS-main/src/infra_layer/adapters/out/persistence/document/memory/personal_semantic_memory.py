"""
PersonalSemanticMemory Beanie ODM 模型

存储从个人情景记忆中提取的语义记忆，每个个人 episode 可以有多条语义记忆。
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from beanie import Indexed
from core.oxm.mongo.document_base import DocumentBase
from pydantic import Field, ConfigDict
from pymongo import IndexModel, ASCENDING, DESCENDING
from core.oxm.mongo.audit_base import AuditBase
from beanie import PydanticObjectId


class PersonalSemanticMemory(DocumentBase, AuditBase):
    """
    个人语义记忆文档模型

    存储从个人情景记忆（EpisodicMemory）中提取的语义记忆。
    每个个人 episode 可以有多条语义记忆，用于描述在特定时间范围内的稳定认知。
    """

    # 核心字段（必填）
    user_id: str = Field(..., description="用户ID")
    content: str = Field(..., min_length=1, description="语义记忆内容")
    parent_episode_id: str = Field(..., description="父情景记忆的 event_id")

    # 时间范围字段
    start_time: Optional[str] = Field(default=None, description="语义记忆开始时间（日期字符串，如 2024-01-01）")
    end_time: Optional[str] = Field(default=None, description="语义记忆结束时间（日期字符串，如 2024-12-31）")
    duration_days: Optional[int] = Field(default=None, description="持续天数")

    # 群组和参与者信息
    group_id: Optional[str] = Field(default=None, description="群组ID")
    participants: Optional[List[str]] = Field(default=None, description="相关参与者")

    # 向量和模型
    vector: Optional[List[float]] = Field(default=None, description="语义记忆的文本向量")
    vector_model: Optional[str] = Field(default=None, description="使用的向量化模型")

    # 证据和扩展信息
    evidence: Optional[str] = Field(default=None, description="支持该语义记忆的证据")
    extend: Optional[Dict[str, Any]] = Field(default=None, description="扩展字段")

    model_config = ConfigDict(
        collection="personal_semantic_memories",
        validate_assignment=True,
        json_encoders={datetime: lambda dt: dt.isoformat()},
        json_schema_extra={
            "example": {
                "user_id": "user_12345",
                "content": "用户喜欢吃川菜，尤其是麻辣火锅",
                "parent_episode_id": "episode_001",
                "start_time": "2024-01-01",
                "end_time": "2024-12-31",
                "duration_days": 365,
                "group_id": "group_friends",
                "participants": ["张三", "李四"],
                "vector": [0.1, 0.2, 0.3],
                "vector_model": "text-embedding-3-small",
                "evidence": "多次在聊天中提到喜欢吃火锅",
                "extend": {"confidence": 0.9}
            }
        },
    )

    @property
    def event_id(self) -> Optional[PydanticObjectId]:
        """兼容性属性，返回文档ID"""
        return self.id

    class Settings:
        """Beanie 设置"""

        name = "personal_semantic_memories"

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
__all__ = ["PersonalSemanticMemory"]

