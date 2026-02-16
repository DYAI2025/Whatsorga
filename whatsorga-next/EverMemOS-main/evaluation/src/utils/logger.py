"""
日志工具

提供统一的日志记录功能。
"""
import logging
from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.logging import RichHandler


def setup_logger(
    log_file: Optional[Path] = None,
    level: int = logging.INFO,
    name: str = "evaluation"
) -> logging.Logger:
    """
    设置日志器
    
    Args:
        log_file: 日志文件路径（可选）
        level: 日志级别
        name: 日志器名称
        
    Returns:
        配置好的 Logger 实例
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # 清除已有的 handlers
    logger.handlers.clear()
    
    # 添加 Rich Console Handler（彩色输出）
    console_handler = RichHandler(
        rich_tracebacks=True,
        show_time=False,
        show_path=False
    )
    console_handler.setLevel(level)
    logger.addHandler(console_handler)
    
    # 添加文件 Handler（如果指定了日志文件）
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(level)
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger


def get_console() -> Console:
    """获取 Rich Console 实例"""
    return Console()

