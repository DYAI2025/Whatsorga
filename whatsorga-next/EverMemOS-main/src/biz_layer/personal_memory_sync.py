"""PersonalSemanticMemory 和 PersonalEventLog 到 Milvus 同步服务

负责将 PersonalSemanticMemory 和 PersonalEventLog 同步到 Milvus 向量数据库。
"""

from typing import Optional, List, Dict, Any
import logging
from datetime import datetime

from infra_layer.adapters.out.persistence.document.memory.personal_semantic_memory import (
    PersonalSemanticMemory,
)
from infra_layer.adapters.out.persistence.document.memory.personal_event_log import (
    PersonalEventLog,
)
from infra_layer.adapters.out.search.repository.semantic_memory_milvus_repository import (
    SemanticMemoryMilvusRepository,
)
from infra_layer.adapters.out.search.repository.event_log_milvus_repository import (
    EventLogMilvusRepository,
)
from infra_layer.adapters.out.search.repository.semantic_memory_es_repository import (
    SemanticMemoryEsRepository,
)
from infra_layer.adapters.out.search.repository.event_log_es_repository import (
    EventLogEsRepository,
)
from agentic_layer.vectorize_service import DeepInfraVectorizeServiceInterface
from core.di import get_bean_by_type, service
from common_utils.datetime_utils import get_now_with_timezone

logger = logging.getLogger(__name__)


@service(name="personal_memory_sync_service", primary=True)
class PersonalMemorySyncService:
    """PersonalSemanticMemory 和 PersonalEventLog 到 Milvus 同步服务
    
    将 PersonalSemanticMemory 和 PersonalEventLog 存储到 Milvus：
    1. PersonalSemanticMemory → SemanticMemoryCollection
    2. PersonalEventLog → EventLogCollection
    """

    def __init__(
        self,
        semantic_milvus_repo: Optional[SemanticMemoryMilvusRepository] = None,
        eventlog_milvus_repo: Optional[EventLogMilvusRepository] = None,
        semantic_es_repo: Optional[SemanticMemoryEsRepository] = None,
        eventlog_es_repo: Optional[EventLogEsRepository] = None,
        vectorize_service: Optional[DeepInfraVectorizeServiceInterface] = None,
    ):
        """初始化同步服务
        
        Args:
            semantic_milvus_repo: 语义记忆 Milvus 仓库实例（可选，不提供则从 DI 获取）
            eventlog_milvus_repo: 事件日志 Milvus 仓库实例（可选，不提供则从 DI 获取）
            semantic_es_repo: 语义记忆 ES 仓库实例（可选，不提供则从 DI 获取）
            eventlog_es_repo: 事件日志 ES 仓库实例（可选，不提供则从 DI 获取）
            vectorize_service: 向量化服务实例（可选，不提供则从 DI 获取）
        """
        self.semantic_milvus_repo = semantic_milvus_repo or get_bean_by_type(
            SemanticMemoryMilvusRepository
        )
        self.eventlog_milvus_repo = eventlog_milvus_repo or get_bean_by_type(
            EventLogMilvusRepository
        )
        self.semantic_es_repo = semantic_es_repo or get_bean_by_type(
            SemanticMemoryEsRepository
        )
        self.eventlog_es_repo = eventlog_es_repo or get_bean_by_type(
            EventLogEsRepository
        )
        
        if vectorize_service is None:
            from agentic_layer.vectorize_service import get_vectorize_service
            self.vectorize_service = get_vectorize_service()
        else:
            self.vectorize_service = vectorize_service
        
        logger.info("PersonalMemorySyncService 初始化完成")

    @staticmethod
    def _normalize_datetime(value: Optional[datetime | str]) -> Optional[datetime]:
        """将 str/None 转为 datetime（仅日期字符串也支持）"""
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and value:
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                try:
                    return datetime.strptime(value, "%Y-%m-%d")
                except ValueError:
                    logger.warning("无法解析日期字符串: %s", value)
                    return None
        return None

    async def sync_semantic_memory(
        self, 
        semantic_memory: PersonalSemanticMemory,
        sync_to_es: bool = True,
        sync_to_milvus: bool = True
    ) -> Dict[str, int]:
        """同步单个 PersonalSemanticMemory 到 Milvus 和 ES
        
        Args:
            semantic_memory: PersonalSemanticMemory 文档对象
            sync_to_es: 是否同步到 ES（默认 True）
            sync_to_milvus: 是否同步到 Milvus（默认 True）
            
        Returns:
            同步统计信息 {"semantic_memory": 1}
        """
        stats = {"semantic_memory": 0, "es_records": 0}
        
        try:
            # 从 MongoDB 读取已有的 vector
            content = semantic_memory.content or ""
            evidence = semantic_memory.evidence or ""
            
            # 使用 content + evidence 作为搜索内容
            search_content = [content, evidence]
            
            # 从 MongoDB 读取 embedding，如果没有则跳过
            embedding = semantic_memory.vector
            if not embedding:
                logger.warning(f"语义记忆 {semantic_memory.id} 没有 embedding，跳过同步")
                return stats
            
            # 处理时间字段
            start_time_dt = (
                self._normalize_datetime(semantic_memory.start_time)
                or get_now_with_timezone()
            )
            end_time_dt = self._normalize_datetime(semantic_memory.end_time)
            duration_days = semantic_memory.duration_days or 0
            
            # 同步到 Milvus
            if sync_to_milvus:
                await self.semantic_milvus_repo.create_and_save_semantic_memory(
                    memory_id=str(semantic_memory.id),
                    user_id=semantic_memory.user_id,  # 个人记忆，user_id 不为空
                    content=content,
                    parent_episode_id=semantic_memory.parent_episode_id or "",
                    vector=embedding,
                    group_id=getattr(semantic_memory, 'group_id', None),
                    participants=getattr(semantic_memory, 'participants', None),
                    start_time=start_time_dt,
                    end_time=end_time_dt,
                    duration_days=duration_days,
                    evidence=evidence,
                    search_content=search_content,
                    extend={
                        "source_episode_id": semantic_memory.parent_episode_id or "",
                    },
                )
                stats["semantic_memory"] += 1
                logger.debug(f"已同步语义记忆到 Milvus: {semantic_memory.id}")
            
            # 同步到 ES
            if sync_to_es:
                await self.semantic_es_repo.create_and_save_semantic_memory(
                    memory_id=str(semantic_memory.id),
                    user_id=semantic_memory.user_id,
                    timestamp=start_time_dt,
                    content=content,
                    parent_episode_id=semantic_memory.parent_episode_id or "",
                    group_id=getattr(semantic_memory, 'group_id', None),
                    participants=getattr(semantic_memory, 'participants', None),
                    start_time=start_time_dt,
                    end_time=end_time_dt,
                    duration_days=duration_days,
                    evidence=evidence,
                    search_content=search_content,
                    extend={
                        "source_episode_id": semantic_memory.parent_episode_id or "",
                    },
                )
                stats["es_records"] += 1
                logger.debug(f"已同步语义记忆到 ES: {semantic_memory.id}")
            
        except Exception as e:
            logger.error(f"同步语义记忆失败: {e}", exc_info=True)
            raise
        
        return stats

    async def sync_event_log(
        self,
        event_log: PersonalEventLog,
        sync_to_es: bool = True,
        sync_to_milvus: bool = True
    ) -> Dict[str, int]:
        """同步单个 PersonalEventLog 到 Milvus 和 ES
        
        Args:
            event_log: PersonalEventLog 文档对象
            sync_to_es: 是否同步到 ES（默认 True）
            sync_to_milvus: 是否同步到 Milvus（默认 True）
            
        Returns:
            同步统计信息 {"event_log": 1}
        """
        stats = {"event_log": 0, "es_records": 0}
        
        try:
            # 从 MongoDB 读取已有的 vector
            atomic_fact = event_log.atomic_fact or ""
            vector = event_log.vector
            if not vector:
                logger.warning(f"事件日志 {event_log.id} 没有 embedding，跳过同步")
                return stats
            
            # 同步到 Milvus
            if sync_to_milvus:
                await self.eventlog_milvus_repo.create_and_save_event_log(
                    log_id=str(event_log.id),
                    user_id=event_log.user_id,  # 个人记忆，user_id 不为空
                    atomic_fact=atomic_fact,
                    parent_episode_id=event_log.parent_episode_id or "",
                    timestamp=event_log.timestamp or get_now_with_timezone(),
                    vector=vector,
                    group_id=getattr(event_log, 'group_id', None),
                    participants=getattr(event_log, 'participants', None),
                )
                stats["event_log"] += 1
                logger.debug(f"已同步事件日志到 Milvus: {event_log.id}")
            
            # 同步到 ES
            if sync_to_es:
                await self.eventlog_es_repo.create_and_save_event_log(
                    log_id=str(event_log.id),
                    user_id=event_log.user_id,
                    atomic_fact=atomic_fact,
                    search_content=[atomic_fact],  # ES 需要 search_content
                    parent_episode_id=event_log.parent_episode_id or "",
                    timestamp=event_log.timestamp or get_now_with_timezone(),
                    group_id=getattr(event_log, 'group_id', None),
                    participants=getattr(event_log, 'participants', None),
                )
                stats["es_records"] += 1
                logger.debug(f"已同步事件日志到 ES: {event_log.id}")
            
        except Exception as e:
            logger.error(f"同步事件日志失败: {e}", exc_info=True)
            raise
        
        return stats

    async def sync_batch_semantic_memories(
        self,
        semantic_memories: List[PersonalSemanticMemory],
        sync_to_es: bool = True,
        sync_to_milvus: bool = True
    ) -> Dict[str, int]:
        """批量同步 PersonalSemanticMemory
        
        Args:
            semantic_memories: PersonalSemanticMemory 列表
            sync_to_es: 是否同步到 ES（默认 True）
            sync_to_milvus: 是否同步到 Milvus（默认 True）
            
        Returns:
            同步统计信息
        """
        total_stats = {"semantic_memory": 0, "es_records": 0}
        
        for sem_mem in semantic_memories:
            try:
                stats = await self.sync_semantic_memory(
                    sem_mem, 
                    sync_to_es=sync_to_es,
                    sync_to_milvus=sync_to_milvus
                )
                total_stats["semantic_memory"] += stats.get("semantic_memory", 0)
                total_stats["es_records"] += stats.get("es_records", 0)
            except Exception as e:
                logger.error(f"批量同步语义记忆失败: {sem_mem.id}, 错误: {e}")
        
        # Flush
        if sync_to_milvus and total_stats["semantic_memory"] > 0:
            await self.semantic_milvus_repo.flush()
        
        return total_stats

    async def sync_batch_event_logs(
        self,
        event_logs: List[PersonalEventLog],
        sync_to_es: bool = True,
        sync_to_milvus: bool = True
    ) -> Dict[str, int]:
        """批量同步 PersonalEventLog
        
        Args:
            event_logs: PersonalEventLog 列表
            sync_to_es: 是否同步到 ES（默认 True）
            sync_to_milvus: 是否同步到 Milvus（默认 True）
            
        Returns:
            同步统计信息
        """
        total_stats = {"event_log": 0, "es_records": 0}
        
        for evt_log in event_logs:
            try:
                stats = await self.sync_event_log(
                    evt_log,
                    sync_to_es=sync_to_es,
                    sync_to_milvus=sync_to_milvus
                )
                total_stats["event_log"] += stats.get("event_log", 0)
                total_stats["es_records"] += stats.get("es_records", 0)
            except Exception as e:
                logger.error(f"批量同步事件日志失败: {evt_log.id}, 错误: {e}")
        
        # Flush
        if sync_to_milvus and total_stats["event_log"] > 0:
            await self.eventlog_milvus_repo.flush()
        
        return total_stats

