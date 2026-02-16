"""
事件日志 ES 转换器

负责将 MongoDB 的 PersonalEventLog 文档转换为 Elasticsearch 的 EpisodicMemoryDoc 文档。
注意：复用 EpisodicMemoryDoc，通过 type 字段区分为 event_log。
支持个人和群组事件日志。
"""

from typing import List
import jieba

from core.oxm.es.base_converter import BaseEsConverter
from core.observation.logger import get_logger
from core.nlp.stopwords_utils import filter_stopwords
from infra_layer.adapters.out.search.elasticsearch.memory.episodic_memory import (
    EpisodicMemoryDoc,
)
from infra_layer.adapters.out.persistence.document.memory.personal_event_log import (
    PersonalEventLog as MongoPersonalEventLog,
)

logger = get_logger(__name__)


class EventLogConverter(BaseEsConverter[EpisodicMemoryDoc]):
    """
    事件日志 ES 转换器
    
    将 MongoDB 的 PersonalEventLog 文档转换为 Elasticsearch 的 EpisodicMemoryDoc 文档。
    复用 EpisodicMemoryDoc，通过 type 字段标记为 event_log。
    支持个人和群组事件日志。
    """

    @classmethod
    def from_mongo(cls, source_doc: MongoPersonalEventLog) -> EpisodicMemoryDoc:
        """
        从 MongoDB PersonalEventLog 文档转换为 ES EpisodicMemoryDoc 文档

        Args:
            source_doc: MongoDB 的 PersonalEventLog 文档实例

        Returns:
            EpisodicMemoryDoc: ES 文档实例
        """
        if source_doc is None:
            raise ValueError("MongoDB 文档不能为空")

        try:
            # 构建搜索内容列表，用于 BM25 检索
            search_content = cls._build_search_content(source_doc)
            
            # 创建 ES 文档实例
            es_doc = EpisodicMemoryDoc(
                # 基础标识字段
                event_id=str(source_doc.id) if source_doc.id else "",
                user_id=source_doc.user_id,
                user_name=None,  # 个人事件日志没有 user_name
                # 时间字段
                timestamp=source_doc.timestamp,
                # 核心内容字段 - 使用 atomic_fact 作为 episode
                title=source_doc.atomic_fact[:50] if source_doc.atomic_fact else "",  # 取前50字符作为标题
                episode=source_doc.atomic_fact,
                search_content=search_content,  # BM25 搜索的核心字段
                summary=None,
                # 分类和标签字段
                group_id=source_doc.group_id,
                participants=source_doc.participants,
                type="event_log",  # 标记类型（去除 personal 前缀）
                keywords=None,
                linked_entities=None,
                # MongoDB 特有字段
                subject=source_doc.atomic_fact[:50] if source_doc.atomic_fact else "",
                memcell_event_id_list=[source_doc.parent_episode_id] if source_doc.parent_episode_id else None,
                # 扩展字段
                extend={
                    "parent_episode_id": source_doc.parent_episode_id,
                    "event_type": source_doc.event_type,
                    "vector_model": source_doc.vector_model,
                    **(source_doc.extend or {}),
                },
                # 审计字段
                created_at=source_doc.created_at,
                updated_at=source_doc.updated_at,
            )

            return es_doc

        except Exception as e:
            logger.error("从 MongoDB PersonalEventLog 文档转换为 ES 文档失败: %s", e)
            raise

    @classmethod
    def _build_search_content(cls, source_doc: MongoPersonalEventLog) -> List[str]:
        """
        构建搜索内容列表
        
        对中文文本进行分词，并过滤停用词，生成用于 BM25 检索的关键词列表。
        """
        search_content = []
        
        # 分词 atomic_fact
        if source_doc.atomic_fact:
            words = jieba.lcut(source_doc.atomic_fact)
            words = filter_stopwords(words)
            search_content.extend(words)
        
        # 去重并保持顺序
        seen = set()
        unique_content = []
        for word in search_content:
            if word not in seen and word.strip():
                seen.add(word)
                unique_content.append(word)
        
        return unique_content if unique_content else [""]

