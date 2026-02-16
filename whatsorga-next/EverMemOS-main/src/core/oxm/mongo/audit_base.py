"""
MongoDB 审计基类

基于 Beanie ODM 的审计基类，包含通用的时间戳字段和自动处理逻辑。
"""

try:
    from datetime import datetime
    from typing import Optional
    from beanie import before_event, Insert, Update
    from pydantic import Field, BaseModel
    from common_utils.datetime_utils import get_now_with_timezone

    BEANIE_AVAILABLE = True
except ImportError:
    BEANIE_AVAILABLE = False


if BEANIE_AVAILABLE:

    class AuditBase(BaseModel):
        """
        审计基类

        包含通用的时间戳字段和自动处理逻辑
        """

        # 系统字段
        created_at: Optional[datetime] = Field(default=None, description="创建时间")
        updated_at: Optional[datetime] = Field(default=None, description="更新时间")

        @before_event(Insert)
        async def set_created_at(self):
            """插入前设置创建时间"""
            now = get_now_with_timezone()
            self.created_at = now
            self.updated_at = now

        @before_event(Update)
        async def set_updated_at(self):
            """更新前设置更新时间"""
            self.updated_at = get_now_with_timezone()

else:
    # 如果 Beanie 不可用，提供一个空的基类
    class AuditBase:
        """
        审计基类占位符

        当 Beanie 依赖不可用时使用
        """

        def __init__(self):
            raise ImportError(
                "Beanie ODM is not available. Please install beanie to use AuditBase."
            )


# 导出
__all__ = ["AuditBase", "BEANIE_AVAILABLE"]
