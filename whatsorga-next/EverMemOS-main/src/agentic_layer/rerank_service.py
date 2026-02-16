"""
DeepInfra Rerank Service
DeepInfra重排序服务

This module provides methods to call DeepInfra API for reranking retrieved memories.
该模块提供调用DeepInfra API对检索到的记忆进行重排序的方法。
"""

from __future__ import annotations

import os
import asyncio
import aiohttp
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Union
from dataclasses import dataclass, field
import numpy as np

from core.di import get_bean, service

logger = logging.getLogger(__name__)


@dataclass
@service(name="deepinfra_rerank_config", primary=True)
class DeepInfraRerankConfig:
    """DeepInfra Rerank API配置类"""

    api_key: str = ""
    base_url: str = ""
    model: str = ""
    timeout: int = 30
    max_retries: int = 3
    batch_size: int = 10
    max_concurrent_requests: int = 5

    def __post_init__(self):
        """初始化后从环境变量加载配置值"""
        if not self.api_key:
            self.api_key = os.getenv("DEEPINFRA_API_KEY", "")
        if not self.base_url:
            self.base_url = os.getenv(
                "DEEPINFRA_RERANK_BASE_URL", "https://api.deepinfra.com/v1/inference"
            )
        if not self.model:
            self.model = os.getenv("DEEPINFRA_RERANK_MODEL", "Qwen/Qwen3-Reranker-4B")
        if self.timeout == 30:  # 使用默认值时才从环境变量读取
            self.timeout = int(os.getenv("DEEPINFRA_RERANK_TIMEOUT", "30"))
        if self.max_retries == 3:  # 使用默认值时才从环境变量读取
            self.max_retries = int(os.getenv("DEEPINFRA_RERANK_MAX_RETRIES", "3"))
        if self.batch_size == 10:  # 使用默认值时才从环境变量读取
            self.batch_size = int(os.getenv("DEEPINFRA_RERANK_BATCH_SIZE", "10"))
        if self.max_concurrent_requests == 5:  # 使用默认值时才从环境变量读取
            self.max_concurrent_requests = int(
                os.getenv("DEEPINFRA_RERANK_MAX_CONCURRENT", "5")
            )


class DeepInfraRerankError(Exception):
    """DeepInfra Rerank API错误异常类"""

    pass


@dataclass
class RerankMemResponse:
    """重排序后的记忆检索响应"""

    memories: List[Dict[str, List[Any]]] = field(default_factory=list)
    scores: List[Dict[str, List[float]]] = field(default_factory=list)
    rerank_scores: List[Dict[str, List[float]]] = field(
        default_factory=list
    )  # 重排序分数
    importance_scores: List[float] = field(default_factory=list)
    original_data: List[Dict[str, List[Dict[str, Any]]]] = field(default_factory=list)
    total_count: int = 0
    has_more: bool = False
    query_metadata: Any = field(default_factory=dict)
    metadata: Any = field(default_factory=dict)


class DeepInfraRerankServiceInterface(ABC):
    """DeepInfra重排序服务接口"""

    @abstractmethod
    async def rerank_memories(
        self, query: str, retrieve_response: Any
    ) -> RerankMemResponse:
        """
        对检索到的记忆进行重排序

        Args:
            query: 查询文本
            retrieve_response: RetrieveMemResponse对象

        Returns:
            重排序后的RerankMemResponse对象
        """
        pass


@service(name="rerank_service", primary=True)
class DeepInfraRerankService(DeepInfraRerankServiceInterface):
    """
    DeepInfra重排序服务类

    提供调用DeepInfra API对检索到的记忆进行重排序的方法
    """

    def __init__(self, config: Optional[DeepInfraRerankConfig] = None):
        """
        初始化DeepInfra重排序服务

        Args:
            config: DeepInfra重排序配置，如果为None则尝试从依赖注入获取，最后从环境变量读取
        """
        if config is None:
            try:
                # 尝试从依赖注入获取配置
                from core.di import get_bean

                config = get_bean("deepinfra_rerank_config")
            except Exception:
                # 如果依赖注入失败，从环境变量读取
                config = self._load_config_from_env()

        self.config = config
        self.session: Optional[aiohttp.ClientSession] = None
        self._semaphore = asyncio.Semaphore(config.max_concurrent_requests)

        logger.info(f"Initialized DeepInfra Rerank Service with model: {config.model}")

    def _load_config_from_env(self) -> DeepInfraRerankConfig:
        """从环境变量加载配置"""
        return DeepInfraRerankConfig(
            api_key=os.getenv("DEEPINFRA_API_KEY", ""),
            base_url=os.getenv(
                "DEEPINFRA_RERANK_BASE_URL", "https://api.deepinfra.com/v1/inference"
            ),
            model=os.getenv("DEEPINFRA_RERANK_MODEL", "Qwen/Qwen3-Reranker-4B"),
            timeout=int(os.getenv("DEEPINFRA_RERANK_TIMEOUT", "30")),
            max_retries=int(os.getenv("DEEPINFRA_RERANK_MAX_RETRIES", "3")),
            batch_size=int(os.getenv("DEEPINFRA_RERANK_BATCH_SIZE", "10")),
            max_concurrent_requests=int(
                os.getenv("DEEPINFRA_RERANK_MAX_CONCURRENT", "5")
            ),
        )

    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.close()

    async def _ensure_session(self):
        """确保HTTP会话已创建"""
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=self.config.timeout)
            self.session = aiohttp.ClientSession(
                timeout=timeout,
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
            )

    async def close(self):
        """关闭HTTP会话"""
        if self.session and not self.session.closed:
            await self.session.close()

    async def _make_rerank_request(
        self, query: str, documents: List[str], instruction: str = None
    ) -> Dict[str, Any]:
        """
        向DeepInfra API发送重排序请求

        Args:
            query: 查询文本
            documents: 要重排序的文档列表

        Returns:
            API响应数据

        Raises:
            DeepInfraRerankError: API请求失败时抛出
        """
        if not documents:
            return {"results": []}

        # 拆分成10个批次
        num_batches = 10
        # 使用numpy.array_split将文档分成大致相等的10个批次
        # We filter out empty batches that can be created if len(documents) < num_batches
        batches = [
            list(batch)
            for batch in np.array_split(documents, num_batches)
            if len(batch) > 0
        ]

        tasks = [
            self._send_rerank_request_batch(query, batch, instruction)
            for batch in batches
        ]

        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        all_scores = []
        total_input_tokens = 0
        last_response = None

        for i, result in enumerate(batch_results):
            if isinstance(result, Exception):
                logger.error(f"Rerank batch {i} failed: {result}")
                # For a failed batch, we must insert scores of a corresponding length
                # to maintain the correct document order. Let's use a very low score.
                batch_len = len(batches[i])
                all_scores.extend([-100.0] * batch_len)
                continue

            all_scores.extend(result.get("scores", []))
            total_input_tokens += result.get("input_tokens", 0)
            last_response = result

        if not last_response:
            raise DeepInfraRerankError("All rerank batches failed.")

        combined_response = {
            "scores": all_scores,
            "input_tokens": total_input_tokens,
            "request_id": last_response.get("request_id"),
            "inference_status": last_response.get("inference_status", {}),
        }

        return self._convert_response_format(combined_response, len(documents))

    async def _send_rerank_request_batch(
        self, query: str, documents: List[str], instruction: Optional[str] = None
    ) -> Dict[str, Any]:
        """向DeepInfra API发送单个重排序请求批次"""
        await self._ensure_session()

        # 构建请求数据 - 使用DeepInfra推理API格式
        if instruction is None:
            request_data = {
                "queries": [query],  # 查询列表
                "documents": documents,  # 文档列表
            }
        else:
            request_data = {
                "queries": [query],  # 查询列表
                "documents": documents,  # 文档列表
                "instruction": instruction,
            }

        # 使用推理API端点
        url = f"{self.config.base_url}/{self.config.model}"

        async with self._semaphore:
            for attempt in range(self.config.max_retries):
                try:
                    async with self.session.post(url, json=request_data) as response:
                        if response.status == 200:
                            return await response.json()
                        else:
                            error_text = await response.text()
                            logger.error(
                                f"DeepInfra Rerank API error (attempt {attempt + 1}): {response.status} - {error_text}"
                            )

                            if attempt < self.config.max_retries - 1:
                                await asyncio.sleep(2**attempt)  # 指数退避
                                continue
                            else:
                                raise DeepInfraRerankError(
                                    f"Rerank API request failed: {response.status} - {error_text}"
                                )

                except aiohttp.ClientError as e:
                    logger.error(
                        f"DeepInfra Rerank API client error (attempt {attempt + 1}): {e}"
                    )
                    if attempt < self.config.max_retries - 1:
                        await asyncio.sleep(2**attempt)
                        continue
                    else:
                        raise DeepInfraRerankError(f"Rerank client error: {e}")

                except Exception as e:
                    logger.error(
                        f"Unexpected rerank error (attempt {attempt + 1}): {e}"
                    )
                    if attempt < self.config.max_retries - 1:
                        await asyncio.sleep(2**attempt)
                        continue
                    else:
                        raise DeepInfraRerankError(f"Unexpected rerank error: {e}")

    def _convert_response_format(
        self, api_response: Dict[str, Any], num_documents: int
    ) -> Dict[str, Any]:
        """
        将DeepInfra推理API响应转换为重排序服务期望的格式

        Args:
            api_response: DeepInfra API原始响应
            num_documents: 文档数量

        Returns:
            转换后的响应格式
        """
        # 从API响应中提取scores
        scores = api_response.get("scores", [])

        # 确保scores长度与文档数量一致
        if len(scores) != num_documents:
            logger.warning(
                f"API返回的scores数量({len(scores)})与文档数量({num_documents})不匹配"
            )
            # 如果scores不足，用0填充
            while len(scores) < num_documents:
                scores.append(0.0)
            # 如果scores过多，截取
            scores = scores[:num_documents]

        # 对分数进行标准化处理
        # normalized_scores = self._normalize_scores(scores)

        # 创建索引和分数的配对
        # indexed_scores = [(i, score) for i, score in enumerate(normalized_scores)]
        indexed_scores = [(i, score) for i, score in enumerate(scores)]
        # indexed_scores = scores

        # 按分数降序排序
        indexed_scores.sort(key=lambda x: x[1], reverse=True)

        # 构建results格式
        results = []
        for rank, (original_index, score) in enumerate(indexed_scores):
            results.append(
                {"index": original_index, "relevance_score": score, "rank": rank}
            )

        logger.debug(f"原始分数: {scores}")
        # logger.debug(f"标准化后分数: {normalized_scores}")

        return {
            "results": results,
            "input_tokens": api_response.get("input_tokens", 0),
            "request_id": api_response.get("request_id"),
            "inference_status": api_response.get("inference_status", {}),
        }

    def _normalize_scores(self, scores: List[float]) -> List[float]:
        """
        对重排序分数进行标准化处理

        Args:
            scores: 原始分数列表

        Returns:
            标准化后的分数列表
        """
        if not scores:
            return scores

        # 方法1: 使用sigmoid函数将分数映射到0-1范围
        import math

        # 如果分数都很小（可能是logits），使用sigmoid
        max_score = max(scores)
        if max_score < 1.0:  # 如果最大分数小于1，可能是logits
            normalized = []
            for score in scores:
                # 使用sigmoid函数: 1 / (1 + e^(-x))
                sigmoid_score = 1 / (1 + math.exp(-score))
                normalized.append(sigmoid_score)
            return normalized

        # 方法2: 如果分数已经合理，使用min-max标准化
        min_score = min(scores)
        max_score = max(scores)

        if max_score == min_score:
            # 如果所有分数相同，返回均匀分布
            return [0.5] * len(scores)

        # Min-max标准化到0-1范围
        normalized = []
        for score in scores:
            normalized_score = (score - min_score) / (max_score - min_score)
            normalized.append(normalized_score)

        return normalized

    def _extract_memory_text(self, memory: Any) -> str:
        """
        从Memory对象中提取用于重排序的文本

        Args:
            memory: Memory对象

        Returns:
            提取的文本内容
        """
        # 优先使用episode，其次使用summary，最后使用subject
        if hasattr(memory, 'episode') and memory.episode:
            return memory.episode
        elif hasattr(memory, 'summary') and memory.summary:
            return memory.summary
        elif hasattr(memory, 'subject') and memory.subject:
            return memory.subject
        return str(memory)

    async def rerank_memories(
        self, query: str, retrieve_response: Any, instruction: str = None
    ) -> Union[RerankMemResponse, List[Dict[str, Any]]]:
        """
        对检索到的记忆进行重排序

        Args:
            query: 查询文本
            retrieve_response: RetrieveMemResponse对象或all_hits列表

        Returns:
            重排序后的RerankMemResponse对象（当输入是RetrieveMemResponse时）
            或重排序后的hit列表（当输入是all_hits列表时）
        """
        # 检查输入类型，如果是all_hits列表，则使用专门的方法处理
        if isinstance(retrieve_response, list):
            # 对于all_hits列表，直接返回重排序后的hit列表
            return await self._rerank_all_hits(query, retrieve_response, instruction)

        # 原有的处理RetrieveMemResponse的逻辑
        if not hasattr(retrieve_response, 'memories') or not retrieve_response.memories:
            # 如果没有记忆数据，直接返回空结果
            return RerankMemResponse(
                memories=[],
                scores=[],
                rerank_scores=[],
                importance_scores=[],
                original_data=[],
                total_count=0,
                has_more=False,
                query_metadata=getattr(retrieve_response, 'query_metadata', {}),
                metadata=getattr(retrieve_response, 'metadata', {}),
            )

        # 收集所有记忆和对应的文本
        all_memories = []
        all_texts = []
        memory_to_group_index = {}  # 记录每个记忆属于哪个群组

        for group_idx, memory_dict_by_group in enumerate(retrieve_response.memories):
            for group_id, memory_list in memory_dict_by_group.items():
                for mem_idx, memory in enumerate(memory_list):
                    all_memories.append((group_idx, group_id, mem_idx, memory))
                    all_texts.append(self._extract_memory_text(memory))
                    memory_to_group_index[len(all_memories) - 1] = (
                        group_idx,
                        group_id,
                        mem_idx,
                    )

        if not all_texts:
            # 如果没有文本内容，直接返回原始结果
            return RerankMemResponse(
                memories=retrieve_response.memories,
                scores=retrieve_response.scores,
                rerank_scores=[],
                importance_scores=getattr(retrieve_response, 'importance_scores', []),
                original_data=getattr(retrieve_response, 'original_data', []),
                total_count=getattr(retrieve_response, 'total_count', 0),
                has_more=getattr(retrieve_response, 'has_more', False),
                query_metadata=getattr(retrieve_response, 'query_metadata', {}),
                metadata=getattr(retrieve_response, 'metadata', {}),
            )

        # 调用重排序API
        try:

            rerank_result = await self._make_rerank_request(
                query, all_texts, instruction
            )

            if "results" not in rerank_result:
                raise DeepInfraRerankError(
                    "Invalid rerank API response: missing results field"
                )

            # 解析重排序结果
            rerank_scores = [
                item.get("relevance_score", 0.0) for item in rerank_result["results"]
            ]
            rerank_indices = [
                item.get("index", i) for i, item in enumerate(rerank_result["results"])
            ]

            # 按照重排序后的顺序重新组织记忆
            reranked_memories = []
            reranked_scores = []
            reranked_rerank_scores = []
            reranked_importance_scores = []
            reranked_original_data = []

            # 重新构建群组结构
            group_memories = {}
            group_scores = {}
            group_rerank_scores = {}
            group_original_data = {}

            for new_idx, original_idx in enumerate(rerank_indices):
                group_idx, group_id, mem_idx, memory = all_memories[original_idx]

                if group_id not in group_memories:
                    group_memories[group_id] = []
                    group_scores[group_id] = []
                    group_rerank_scores[group_id] = []
                    group_original_data[group_id] = []

                group_memories[group_id].append(memory)

                # 获取原始分数
                original_scores = retrieve_response.scores[group_idx].get(group_id, [])
                if mem_idx < len(original_scores):
                    group_scores[group_id].append(original_scores[mem_idx])
                else:
                    group_scores[group_id].append(0.0)

                # 添加重排序分数
                group_rerank_scores[group_id].append(rerank_scores[new_idx])

                # 获取原始数据
                original_data_list = retrieve_response.original_data[group_idx].get(
                    group_id, []
                )
                if mem_idx < len(original_data_list):
                    group_original_data[group_id].append(original_data_list[mem_idx])
                else:
                    group_original_data[group_id].append({})

            # 转换为列表格式
            reranked_memories = [group_memories]
            reranked_scores = [group_scores]
            reranked_rerank_scores = [group_rerank_scores]
            reranked_original_data = [group_original_data]

            # 保持原有的importance_scores
            reranked_importance_scores = getattr(
                retrieve_response, 'importance_scores', []
            )

            return RerankMemResponse(
                memories=reranked_memories,
                scores=reranked_scores,
                rerank_scores=reranked_rerank_scores,
                importance_scores=reranked_importance_scores,
                original_data=reranked_original_data,
                total_count=getattr(
                    retrieve_response, 'total_count', len(all_memories)
                ),
                has_more=getattr(retrieve_response, 'has_more', False),
                query_metadata=getattr(retrieve_response, 'query_metadata', {}),
                metadata=getattr(retrieve_response, 'metadata', {}),
            )

        except Exception as e:
            logger.error(f"Error during reranking: {e}")
            # 如果重排序失败，返回原始结果
            return RerankMemResponse(
                memories=retrieve_response.memories,
                scores=retrieve_response.scores,
                rerank_scores=[],
                importance_scores=getattr(retrieve_response, 'importance_scores', []),
                original_data=getattr(retrieve_response, 'original_data', []),
                total_count=getattr(retrieve_response, 'total_count', 0),
                has_more=getattr(retrieve_response, 'has_more', False),
                query_metadata=getattr(retrieve_response, 'query_metadata', {}),
                metadata=getattr(retrieve_response, 'metadata', {}),
            )

    async def _rerank_all_hits(
        self,
        query: str,
        all_hits: List[Dict[str, Any]],
        top_k: int = None,
        instruction: str = None,
    ) -> List[Dict[str, Any]]:
        """
        对all_hits列表进行重排序，返回top_k个结果

        Args:
            query: 查询文本
            all_hits: 搜索结果列表，每个元素是Dict[str, Any]
            top_k: 返回的最大结果数量，如果为None则返回所有结果

        Returns:
            重排序后的hit列表
        """
        if not all_hits:
            return []

        # 从all_hits中提取文本内容用于重排序
        all_texts = []
        logger.debug(f"开始提取文本内容，原始hits {all_hits}")
        for hit in all_hits:
            # 提取文本内容
            text = self._extract_text_from_hit(hit)
            all_texts.append(text)

        if not all_texts:
            return []

        # 调用重排序API
        try:
            logger.debug(f"开始重排序，查询文本: {query}, 文本数量: {len(all_texts)}")
            rerank_result = await self._make_rerank_request(
                query, all_texts, instruction
            )

            logger.debug(f"重排序结果: {rerank_result}")
            if "results" not in rerank_result:
                raise DeepInfraRerankError(
                    "Invalid rerank API response: missing results field"
                )

            # 解析重排序结果
            rerank_scores = [
                item.get("relevance_score", 0.0) for item in rerank_result["results"]
            ]
            rerank_indices = [
                item.get("index", i) for i, item in enumerate(rerank_result["results"])
            ]

            # 按照重排序后的顺序重新组织hits
            reranked_hits = []
            logger.debug(f"重排序结果索引: {rerank_indices}")
            for new_idx, original_idx in enumerate(rerank_indices):
                if 0 <= original_idx < len(all_hits):
                    hit = all_hits[original_idx].copy()  # 复制hit以避免修改原始数据
                    # 添加重排序分数到hit中
                    hit['_rerank_score'] = rerank_scores[original_idx]
                    reranked_hits.append(hit)

            # 如果指定了top_k，则只返回前top_k个结果
            if top_k is not None and top_k > 0:
                reranked_hits = reranked_hits[:top_k]

            logger.debug(f"重排序完成，返回 {len(reranked_hits)} 个结果")
            logger.debug(f"重排序结果: {reranked_hits}")
            return reranked_hits

        except Exception as e:
            logger.error(f"Error during reranking all_hits: {e}")
            # 如果重排序失败，返回原始结果（按原始得分排序）
            sorted_hits = sorted(
                all_hits, key=self._extract_score_from_hit, reverse=True
            )
            if top_k is not None and top_k > 0:
                sorted_hits = sorted_hits[:top_k]
            return sorted_hits

    def _extract_text_from_hit(self, hit: Dict[str, Any]) -> str:
        """
        从hit中提取用于重排序的文本

        Args:
            hit: 搜索结果hit

        Returns:
            提取的文本内容
        """
        # 优先使用episode，其次使用summary，最后使用subject
        if '_source' in hit:
            # ES格式
            source = hit['_source']
            if source.get('episode'):
                return source['episode']
            elif source.get('summary'):
                return source['summary']
            elif source.get('subject'):
                return source['subject']
        else:
            # Milvus格式
            if hit.get('episode'):
                return hit['episode']
            elif hit.get('summary'):
                return hit['summary']
            elif hit.get('subject'):
                return hit['subject']

        return str(hit)

    def _extract_score_from_hit(self, hit: Dict[str, Any]) -> float:
        """
        从hit中提取得分

        Args:
            hit: 搜索结果hit

        Returns:
            得分
        """
        if '_score' in hit:
            return hit['_score']
        elif 'score' in hit:
            return hit['score']
        return 1.0


def get_rerank_service() -> DeepInfraRerankServiceInterface:
    """获取重排序服务实例

    通过依赖注入框架获取服务实例，支持单例模式。
    """
    return get_bean("rerank_service")
