"""
应用启动模块

负责应用启动时的各种初始化操作
"""

import os

# 添加当前目录到Python路径
from common_utils.project_path import CURRENT_DIR

# 导入依赖注入相关模块
from core.di.scanner import ComponentScanner
from core.di.utils import get_beans, get_bean_by_type
from core.observation.logger import get_logger
from core.asynctasks.task_manager import TaskManager

# 推荐用法：模块顶部获取一次logger，后续直接使用（高性能）
logger = get_logger(__name__)

# 移除dotenv依赖，直接使用环境变量


def get_base_scan_path():
    """获取基础扫描路径"""
    return CURRENT_DIR


def get_default_scan_paths():
    """获取默认的扫描路径列表"""
    base_path = get_base_scan_path()
    return [
        os.path.join(base_path, "core/interface/controller/debug"),
        os.path.join(base_path, "core/lifespan"),
        os.path.join(base_path, "core/lock"),
        os.path.join(base_path, "core/cache"),
        os.path.join(base_path, "component"),
        os.path.join(base_path, "infra_layer"),
        os.path.join(base_path, "agentic_layer"),
        os.path.join(base_path, "biz_layer"),
    ]


def get_default_task_directories():
    """获取默认的任务目录列表"""
    base_path = get_base_scan_path()
    return [
        os.path.join(base_path, "core/asynctasks/examples"),
        os.path.join(base_path, "infra_layer/adapters/input/jobs"),
    ]


def setup_dependency_injection(scan_paths=None):
    """
    设置依赖注入框架

    Args:
        scan_paths (list[str], optional): 要扫描的路径列表。如果为None，使用默认路径

    Returns:
        ComponentScanner: 配置好的组件扫描器
    """
    logger.info("🚀 正在初始化依赖注入容器...")

    # 创建组件扫描器
    scanner = ComponentScanner()

    # 使用传入的路径或默认路径
    if scan_paths is None:
        scan_paths = get_default_scan_paths()

    # 获取基础扫描路径用于日志
    base_path = get_base_scan_path()
    logger.info("📁 基础扫描路径: %s", base_path)
    logger.info("🔍 扫描路径数量: %d", len(scan_paths))

    # 添加扫描路径
    for path in scan_paths:
        scanner.add_scan_path(path)
        logger.debug("  + %s", path)

    # 执行扫描和注册
    scanner.scan()
    logger.info("✅ 依赖注入设置完成")

    return scanner


def print_registered_beans():
    """打印所有注册的Bean"""
    logger.info("\n📋 已注册的Bean列表:")
    logger.info("-" * 50)

    all_beans = get_beans()
    for name, bean in all_beans.items():
        logger.info("  • %s: %s", name, type(bean).__name__)

    logger.info("\n📊 总计: %d 个Bean", len(all_beans))


def setup_async_tasks(task_directories=None):
    """
    设置异步任务

    Args:
        task_directories (list[str], optional): 要扫描的任务目录列表。如果为None，使用默认目录
    """
    logger.info("🔄 正在注册异步任务...")

    try:
        # 获取任务管理器
        task_manager = get_bean_by_type(TaskManager)

        # 使用传入的目录或默认目录
        if task_directories is None:
            task_directories = get_default_task_directories()

        logger.info("📂 任务目录数量: %d", len(task_directories))
        for directory in task_directories:
            logger.debug("  + %s", directory)

        # 自动扫描并注册任务
        task_manager.scan_and_register_tasks(task_directories)

        # 打印已注册的任务
        registered_tasks = task_manager.list_registered_task_names()
        logger.info("📋 已注册的任务列表: %s", registered_tasks)

        logger.info("✅ 异步任务注册完成")
    except Exception as e:
        logger.error("❌ 异步任务注册失败: %s", e)
        raise


def print_registered_tasks():
    """打印已注册的任务"""
    logger.info("\n📋 已注册的任务列表:")
    logger.info("-" * 50)

    task_manager = get_bean_by_type(TaskManager)

    registered_tasks = task_manager.list_registered_task_names()
    logger.info("📋 已注册的任务列表: %s", registered_tasks)


def setup_all(scan_paths=None, task_directories=None):
    """
    设置所有组件

    Args:
        scan_paths (list[str], optional): 依赖注入扫描路径列表。如果为None，使用默认路径
        task_directories (list[str], optional): 异步任务目录列表。如果为None，使用默认目录

    Returns:
        ComponentScanner: 配置好的组件扫描器
    """
    # 1. 设置依赖注入
    scanner = setup_dependency_injection(scan_paths)

    # 2. 设置异步任务
    # setup_async_tasks(task_directories)

    return scanner


if __name__ == "__main__":
    # 启动依赖注入
    setup_all()

    # 打印注册的Bean信息
    print_registered_beans()

    # 打印已注册的任务
    print_registered_tasks()

    logger.info("\n✨ 应用启动完成！")
