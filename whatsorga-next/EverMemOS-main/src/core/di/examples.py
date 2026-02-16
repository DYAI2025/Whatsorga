# -*- coding: utf-8 -*-
"""
依赖注入系统使用示例
"""

from abc import ABC, abstractmethod
from typing import List

from di import (
    component,
    service,
    repository,
    factory,
    mock_impl,
    get_bean,
    get_bean_by_type,
    get_beans_by_type,
    enable_mock_mode,
    disable_mock_mode,
    scan_packages,
    register_bean,
    register_factory,
)
from core.di.utils import print_container_info


# ===================== 接口定义 =====================


class UserService(ABC):
    """用户服务接口"""

    @abstractmethod
    def get_user(self, user_id: int) -> dict:
        pass

    @abstractmethod
    def create_user(self, user_data: dict) -> dict:
        pass


class UserRepository(ABC):
    """用户存储接口"""

    @abstractmethod
    def find_by_id(self, user_id: int) -> dict:
        pass

    @abstractmethod
    def save(self, user: dict) -> dict:
        pass


class NotificationService(ABC):
    """通知服务接口"""

    @abstractmethod
    def send_notification(self, message: str, recipient: str):
        pass


# ===================== 实现类 =====================


@repository("mysql_user_repo")
class MySQLUserRepository(UserRepository):
    """MySQL用户存储实现"""

    def find_by_id(self, user_id: int) -> dict:
        print(f"从MySQL数据库查询用户: {user_id}")
        return {"id": user_id, "name": f"User {user_id}", "source": "mysql"}

    def save(self, user: dict) -> dict:
        print(f"保存用户到MySQL: {user}")
        return {**user, "id": 123, "source": "mysql"}


@repository("redis_user_repo")
class RedisUserRepository(UserRepository):
    """Redis用户存储实现"""

    def find_by_id(self, user_id: int) -> dict:
        print(f"从Redis缓存查询用户: {user_id}")
        return {"id": user_id, "name": f"User {user_id}", "source": "redis"}

    def save(self, user: dict) -> dict:
        print(f"保存用户到Redis: {user}")
        return {**user, "id": 123, "source": "redis"}


@repository("primary_user_repo", primary=True)
class PrimaryUserRepository(UserRepository):
    """主要用户存储实现"""

    def find_by_id(self, user_id: int) -> dict:
        print(f"从主存储查询用户: {user_id}")
        return {"id": user_id, "name": f"User {user_id}", "source": "primary"}

    def save(self, user: dict) -> dict:
        print(f"保存用户到主存储: {user}")
        return {**user, "id": 123, "source": "primary"}


@service("user_service")
class UserServiceImpl(UserService):
    """用户服务实现"""

    def __init__(self, user_repository: UserRepository):
        self.user_repository = user_repository

    def get_user(self, user_id: int) -> dict:
        return self.user_repository.find_by_id(user_id)

    def create_user(self, user_data: dict) -> dict:
        return self.user_repository.save(user_data)


@service("email_notification")
class EmailNotificationService(NotificationService):
    """邮件通知服务"""

    def send_notification(self, message: str, recipient: str):
        print(f"发送邮件通知到 {recipient}: {message}")


@service("sms_notification")
class SMSNotificationService(NotificationService):
    """短信通知服务"""

    def send_notification(self, message: str, recipient: str):
        print(f"发送短信通知到 {recipient}: {message}")


@service("primary_notification", primary=True)
class PrimaryNotificationService(NotificationService):
    """主要通知服务"""

    def send_notification(self, message: str, recipient: str):
        print(f"发送主要通知到 {recipient}: {message}")


# ===================== Mock实现 =====================


@mock_impl("mock_user_service")
class MockUserService(UserService):
    """Mock用户服务"""

    def __init__(self, user_repository: UserRepository):
        self.user_repository = user_repository

    def get_user(self, user_id: int) -> dict:
        print(f"Mock: 获取用户服务调用")
        return self.user_repository.find_by_id(user_id)

    def create_user(self, user_data: dict) -> dict:
        print(f"Mock: 创建用户服务调用")
        return self.user_repository.save(user_data)


@mock_impl("mock_user_repo")
class MockUserRepository(UserRepository):
    """Mock用户存储"""

    def find_by_id(self, user_id: int) -> dict:
        print(f"Mock: 查询用户 {user_id}")
        return {"id": user_id, "name": f"Mock User {user_id}", "source": "mock"}

    def save(self, user: dict) -> dict:
        print(f"Mock: 保存用户 {user}")
        return {**user, "id": 999, "source": "mock"}


@mock_impl("mock_notification")
class MockNotificationService(NotificationService):
    """Mock通知服务"""

    def send_notification(self, message: str, recipient: str):
        print(f"Mock: 发送通知到 {recipient}: {message}")


# ===================== Factory示例 =====================


@factory(UserRepository, "factory_user_repo")
def create_user_repository() -> UserRepository:
    """Factory方法创建用户存储"""
    print("通过Factory创建用户存储")
    return MySQLUserRepository()


# ===================== 复杂服务示例 =====================


@service("order_service")
class OrderService:
    """订单服务（演示复杂依赖注入）"""

    def __init__(
        self,
        user_service: UserService,
        notification_service: NotificationService,
        user_repositories: List[UserRepository],  # 注入所有UserRepository实现
    ):
        self.user_service = user_service
        self.notification_service = notification_service
        self.user_repositories = user_repositories

    def create_order(self, user_id: int, product: str):
        # 获取用户信息
        user = self.user_service.get_user(user_id)
        print(f"创建订单: {user['name']} 购买 {product}")

        # 发送通知
        self.notification_service.send_notification(
            f"订单确认: {product}", f"user_{user_id}@example.com"
        )

        # 显示所有可用的存储实现
        print(f"可用的存储实现数量: {len(self.user_repositories)}")

        return {"order_id": 12345, "user_id": user_id, "product": product}


# ===================== 示例函数 =====================


def demo_basic_usage():
    """基本用法演示"""
    print("\n=== 基本用法演示 ===")

    # 根据名称获取Bean
    user_service = get_bean("user_service")
    assert user_service is not None, "应该能够获取到 user_service"
    assert isinstance(
        user_service, UserServiceImpl
    ), "获取的应该是 UserServiceImpl 实例"

    user = user_service.get_user(1)
    print(f"获取到的用户: {user}")
    assert user is not None, "应该能够获取到用户数据"
    assert user["id"] == 1, "用户ID应该是1"
    assert "name" in user, "用户数据应该包含name字段"

    # 根据类型获取Bean（Primary实现）
    notification_service = get_bean_by_type(NotificationService)
    assert notification_service is not None, "应该能够获取到通知服务"
    assert isinstance(
        notification_service, PrimaryNotificationService
    ), "应该获取到Primary实现"

    notification_service.send_notification("欢迎使用系统", "admin@example.com")
    print("✅ 基本用法演示通过")


def demo_multiple_implementations():
    """多实现演示"""
    print("\n=== 多实现演示 ===")

    # 获取所有NotificationService实现
    notification_services = get_beans_by_type(NotificationService)
    assert (
        len(notification_services) >= 3
    ), f"应该至少有3个通知服务实现，实际获取到{len(notification_services)}个"
    print(f"发现 {len(notification_services)} 个通知服务实现")

    # 验证每个服务都是NotificationService的实例
    for i, service in enumerate(notification_services):
        assert isinstance(
            service, NotificationService
        ), f"第{i+1}个服务应该是NotificationService的实例"
        service.send_notification(f"消息{i+1}", f"user{i+1}@example.com")

    # 获取Primary实现
    primary_service = get_bean_by_type(NotificationService)
    assert isinstance(
        primary_service, PrimaryNotificationService
    ), "Primary实现应该是PrimaryNotificationService"
    print(f"Primary实现: {type(primary_service).__name__}")
    print("✅ 多实现演示通过")


def demo_complex_service():
    """复杂服务演示"""
    print("\n=== 复杂服务演示 ===")

    order_service = get_bean("order_service")
    assert order_service is not None, "应该能够获取到订单服务"
    assert isinstance(order_service, OrderService), "获取的应该是OrderService实例"

    # 验证依赖注入正确
    assert order_service.user_service is not None, "用户服务依赖应该被正确注入"
    assert order_service.notification_service is not None, "通知服务依赖应该被正确注入"
    assert len(order_service.user_repositories) > 0, "用户存储依赖列表不应该为空"

    order = order_service.create_order(1, "笔记本电脑")
    assert order is not None, "应该创建成功订单"
    assert order["user_id"] == 1, "订单用户ID应该正确"
    assert order["product"] == "笔记本电脑", "订单产品应该正确"
    print("✅ 复杂服务演示通过")


def demo_mock_mode():
    """Mock模式演示"""
    print("\n=== Mock模式演示 ===")

    # 记录原始实现类型
    original_user_service = get_bean_by_type(UserService)
    original_notification_service = get_bean_by_type(NotificationService)

    # 启用Mock模式
    enable_mock_mode()
    print("已启用Mock模式")

    # 获取服务（将返回Mock实现）
    user_service = get_bean_by_type(UserService)
    assert user_service is not None, "Mock模式下应该能够获取到用户服务"
    # 在Mock模式下，可能返回Mock实现或原实现，这取决于具体的Mock配置

    user = user_service.get_user(1)
    assert user is not None, "Mock模式下应该能够获取到用户数据"
    print(f"Mock模式下获取的用户: {user}")

    notification_service = get_bean_by_type(NotificationService)
    assert notification_service is not None, "Mock模式下应该能够获取到通知服务"
    notification_service.send_notification("Mock测试消息", "test@example.com")

    # 禁用Mock模式
    disable_mock_mode()
    print("已禁用Mock模式")

    # 验证恢复到原始实现
    restored_user_service = get_bean_by_type(UserService)
    restored_notification_service = get_bean_by_type(NotificationService)

    # 类型应该和原始的一致
    assert type(restored_user_service) == type(
        original_user_service
    ), "禁用Mock模式后应该恢复原始用户服务实现"
    assert type(restored_notification_service) == type(
        original_notification_service
    ), "禁用Mock模式后应该恢复原始通知服务实现"

    print("✅ Mock模式演示通过")


def demo_factory():
    """Factory演示"""
    print("\n=== Factory演示 ===")

    # 通过Factory获取实例
    factory_repo = get_bean("factory_user_repo")
    assert factory_repo is not None, "应该能够通过Factory获取到用户存储"
    assert isinstance(
        factory_repo, UserRepository
    ), "Factory创建的应该是UserRepository实例"
    assert isinstance(
        factory_repo, MySQLUserRepository
    ), "Factory创建的应该是MySQLUserRepository实例"

    user = factory_repo.find_by_id(999)
    assert user is not None, "Factory创建的实例应该能够正常工作"
    assert user["id"] == 999, "查询的用户ID应该正确"
    assert user["source"] == "mysql", "数据源应该是mysql"
    print(f"Factory创建的实例查询结果: {user}")
    print("✅ Factory演示通过")


def run_all_demos():
    """运行所有演示"""
    print("🚀 依赖注入系统演示开始")

    # 打印容器信息
    print_container_info()

    # 运行各种演示
    demo_basic_usage()
    demo_multiple_implementations()
    demo_complex_service()
    demo_mock_mode()
    demo_factory()

    print("\n✅ 所有演示通过")


# ===================== 高级使用示例 =====================


@component("config_manager")
class ConfigManager:
    """配置管理器"""

    def __init__(self):
        self.config = {
            "database_url": "mysql://localhost:3306/test",
            "redis_url": "redis://localhost:6379",
            "debug": True,
        }

    def get(self, key: str, default=None):
        return self.config.get(key, default)


@service("advanced_user_service")
class AdvancedUserService:
    """高级用户服务（演示更复杂的依赖）"""

    def __init__(
        self,
        primary_repo: UserRepository,  # 会注入Primary实现
        config: ConfigManager,
        notification: NotificationService,  # 会注入Primary实现
    ):
        self.primary_repo = primary_repo
        self.config = config
        self.notification = notification
        self.debug = config.get("debug", False)

    def register_user(self, user_data: dict):
        if self.debug:
            print(f"Debug模式: 注册用户 {user_data}")

        # 保存用户
        user = self.primary_repo.save(user_data)

        # 发送欢迎通知
        self.notification.send_notification(
            "欢迎注册！", user_data.get("email", "unknown@example.com")
        )

        return user


def demo_advanced_features():
    """高级功能演示"""
    print("\n=== 高级功能演示 ===")

    advanced_service = get_bean("advanced_user_service")
    assert advanced_service is not None, "应该能够获取到高级用户服务"
    assert isinstance(
        advanced_service, AdvancedUserService
    ), "获取的应该是AdvancedUserService实例"

    # 验证依赖注入
    assert advanced_service.primary_repo is not None, "主存储依赖应该被正确注入"
    assert isinstance(
        advanced_service.primary_repo, MySQLUserRepository
    ), "作为接口没有primary的匹配，所以注入的是MySQLUserRepository，工厂的优先级高于其他"
    assert advanced_service.config is not None, "配置管理器依赖应该被正确注入"
    assert isinstance(
        advanced_service.config, ConfigManager
    ), "应该注入ConfigManager实例"
    assert advanced_service.notification is not None, "通知服务依赖应该被正确注入"
    assert isinstance(
        advanced_service.notification, PrimaryNotificationService
    ), "应该注入Primary通知服务实现"

    test_user_data = {"name": "张三", "email": "zhangsan@example.com"}

    user = advanced_service.register_user(test_user_data)
    assert user is not None, "应该成功注册用户"
    assert user["name"] == "张三", "用户姓名应该正确"
    assert user["source"] == "mysql", "数据源应该是mysql"
    print(f"注册结果: {user}")
    print("✅ 高级功能演示通过")


if __name__ == "__main__":
    # 装饰器已经自动注册了组件
    print("📦 使用装饰器自动注册的组件")
    print("✅ 组件注册完成\n")

    # 运行演示
    run_all_demos()
    demo_advanced_features()
