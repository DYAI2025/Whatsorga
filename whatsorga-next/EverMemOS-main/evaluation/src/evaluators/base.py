"""
Evaluator 基类

定义评估器的统一接口。
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any
from evaluation.src.core.data_models import AnswerResult, EvaluationResult


class BaseEvaluator(ABC):
    """评估器基类"""
    
    def __init__(self, config: dict):
        """
        初始化评估器
        
        Args:
            config: 评估配置
        """
        self.config = config
    
    @abstractmethod
    async def evaluate(
        self, 
        answer_results: List[AnswerResult]
    ) -> EvaluationResult:
        """
        评估答案结果
        
        Args:
            answer_results: 答案结果列表
            
        Returns:
            EvaluationResult: 评估结果
        """
        pass
    
    def get_name(self) -> str:
        """返回评估器名称"""
        return self.__class__.__name__

