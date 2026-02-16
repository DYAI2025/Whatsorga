"""
结果保存工具

提供统一的结果保存功能，支持 JSON、pickle 等格式。
"""
import json
import pickle
from pathlib import Path
from typing import Any, Dict


class ResultSaver:
    """结果保存器"""
    
    def __init__(self, output_dir: Path):
        """
        初始化保存器
        
        Args:
            output_dir: 输出目录
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def save_json(self, data: Any, filename: str):
        """
        保存 JSON 文件
        
        Args:
            data: 要保存的数据
            filename: 文件名
        """
        filepath = self.output_dir / filename
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    
    def load_json(self, filename: str) -> Any:
        """
        加载 JSON 文件
        
        Args:
            filename: 文件名
            
        Returns:
            加载的数据
        """
        filepath = self.output_dir / filename
        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")
        
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def save_pickle(self, data: Any, filename: str):
        """
        保存 pickle 文件
        
        Args:
            data: 要保存的数据
            filename: 文件名
        """
        filepath = self.output_dir / filename
        with open(filepath, 'wb') as f:
            pickle.dump(data, f)
    
    def load_pickle(self, filename: str) -> Any:
        """
        加载 pickle 文件
        
        Args:
            filename: 文件名
            
        Returns:
            加载的数据
        """
        filepath = self.output_dir / filename
        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")
        
        with open(filepath, 'rb') as f:
            return pickle.load(f)
    
    def file_exists(self, filename: str) -> bool:
        """检查文件是否存在"""
        return (self.output_dir / filename).exists()

