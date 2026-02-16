"""
配置加载工具

支持 YAML 配置文件加载，并进行环境变量替换。
"""
import os
import yaml
import re
from pathlib import Path
from typing import Dict, Any


def load_yaml(file_path: str) -> Dict[str, Any]:
    """
    加载 YAML 配置文件
    
    Args:
        file_path: YAML 文件路径
        
    Returns:
        解析后的配置字典
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    # 递归替换环境变量
    config = _replace_env_vars(config)
    
    return config


def _replace_env_vars(obj: Any) -> Any:
    """
    递归替换配置中的环境变量
    
    支持格式: ${VAR_NAME} 或 ${VAR_NAME:default_value}
    """
    if isinstance(obj, dict):
        return {key: _replace_env_vars(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [_replace_env_vars(item) for item in obj]
    elif isinstance(obj, str):
        # 匹配 ${VAR_NAME} 或 ${VAR_NAME:default}
        pattern = r'\$\{([^:}]+)(?::([^}]+))?\}'
        
        def replacer(match):
            var_name = match.group(1)
            default_value = match.group(2) if match.group(2) else ''
            return os.environ.get(var_name, default_value)
        
        return re.sub(pattern, replacer, obj)
    else:
        return obj


def save_yaml(config: Dict[str, Any], file_path: str):
    """
    保存配置到 YAML 文件
    
    Args:
        config: 配置字典
        file_path: 保存路径
    """
    Path(file_path).parent.mkdir(parents=True, exist_ok=True)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, indent=2)

