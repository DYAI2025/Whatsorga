# -*- coding: utf-8 -*-
"""
依赖注入框架

功能特性:
- 接口和多个实现支持
- Primary实现机制
- Mock模式支持
- Factory功能
- 循环依赖检测
- 自动扫描注册
"""

from core.di.container import DIContainer, get_container
from core.di.decorators import (
    component,
    service,
    repository,
    factory,
    injectable,
    mock_impl,
)
from core.di.scanner import ComponentScanner
from core.di.utils import (
    get_bean,
    get_beans,
    get_bean_by_type,
    get_beans_by_type,
    register_bean,
    register_factory,
    enable_mock_mode,
    disable_mock_mode,
    clear_container,
    scan_packages,
)
from core.di.exceptions import (
    DIException,
    CircularDependencyError,
    BeanNotFoundError,
    DuplicateBeanError,
    FactoryError,
)

__all__ = [
    # 核心容器
    'DIContainer',
    'get_container',
    # 装饰器
    'component',
    'service',
    'repository',
    'factory',
    'injectable',
    'mock_impl',
    # 扫描器
    'ComponentScanner',
    # 工具函数
    'get_bean',
    'get_beans',
    'get_bean_by_type',
    'get_beans_by_type',
    'register_bean',
    'register_factory',
    'enable_mock_mode',
    'disable_mock_mode',
    'clear_container',
    'scan_packages',
    # 异常类
    'DIException',
    'CircularDependencyError',
    'BeanNotFoundError',
    'DuplicateBeanError',
    'FactoryError',
]
