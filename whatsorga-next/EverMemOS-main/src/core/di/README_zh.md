# 依赖注入框架使用文档

这是一个功能完整的Python依赖注入框架，支持您提出的所有需求。

## 核心功能

✨ **接口和多实现支持** - 一个接口可以有多个实现，自动解析最佳实现
⭐ **Primary机制** - 当有多个实现时，优先选择Primary实现  
🧪 **Mock模式** - 支持测试环境下的Mock实现自动切换
🏭 **Factory功能** - 支持工厂方法创建Bean，灵活控制实例创建
🔄 **循环依赖检测** - 自动检测并阻止循环依赖，给出清晰的错误提示
📡 **自动扫描** - 智能扫描项目文件，自动注册标记的组件
🛠️ **便捷工具** - 丰富的工具函数，简化日常使用

## 快速开始

### 基本使用

```python
from di import component, service, repository, get_bean_by_type
from abc import ABC, abstractmethod

# 定义接口
class UserRepository(ABC):
    @abstractmethod
    def find_by_id(self, user_id: int) -> dict:
        pass

# 实现类
@repository("mysql_user_repo")
class MySQLUserRepository(UserRepository):
    def find_by_id(self, user_id: int) -> dict:
        return {"id": user_id, "name": f"User {user_id}"}

@service("user_service")
class UserService:
    def __init__(self, user_repository: UserRepository):
        self.user_repository = user_repository
    
    def get_user(self, user_id: int) -> dict:
        return self.user_repository.find_by_id(user_id)

# 使用
user_service = get_bean_by_type(UserService)
user = user_service.get_user(1)
```

### 多实现和Primary机制

```python
@repository("mysql_repo")
class MySQLUserRepository(UserRepository):
    def find_by_id(self, user_id: int) -> dict:
        return {"id": user_id, "source": "mysql"}

@repository("redis_repo")  
class RedisUserRepository(UserRepository):
    def find_by_id(self, user_id: int) -> dict:
        return {"id": user_id, "source": "redis"}

# Primary实现
@repository("primary_repo", primary=True)
class PrimaryUserRepository(UserRepository):
    def find_by_id(self, user_id: int) -> dict:
        return {"id": user_id, "source": "primary"}

# 获取Primary实现
repo = get_bean_by_type(UserRepository)  # 返回PrimaryUserRepository

# 获取所有实现
all_repos = get_beans_by_type(UserRepository)  # 返回所有3个实现
```

### Mock模式

```python
from di import mock_impl, enable_mock_mode, disable_mock_mode

# Mock实现
@mock_impl("mock_user_repo")
class MockUserRepository(UserRepository):
    def find_by_id(self, user_id: int) -> dict:
        return {"id": user_id, "name": "Mock User"}

# 启用Mock模式
enable_mock_mode()

# 现在获取的是Mock实现
repo = get_bean_by_type(UserRepository)  # 返回MockUserRepository

# 禁用Mock模式
disable_mock_mode()
```

### Factory功能

```python
from di import factory

@factory(UserRepository, "factory_repo")
def create_user_repository() -> UserRepository:
    # 复杂的创建逻辑
    config = load_config()
    if config.use_cache:
        return RedisUserRepository()
    else:
        return MySQLUserRepository()

# 每次调用都会执行factory方法
repo = get_bean("factory_repo")
```

## 装饰器说明

### @component - 通用组件
```python
@component("my_component")
class MyComponent:
    pass
```

### @service - 服务层组件
```python
@service("user_service")
class UserService:
    def __init__(self, repository: UserRepository):
        self.repository = repository
```

### @repository - 数据访问层组件
```python
@repository("user_repository")
class UserRepositoryImpl(UserRepository):
    pass
```

### @mock_impl - Mock实现
```python
@mock_impl("mock_service")
class MockServiceImpl(ServiceInterface):
    pass
```

### @factory - Factory方法
```python
@factory(ServiceInterface, "service_factory")
def create_service() -> ServiceInterface:
    return ComplexServiceImpl()
```

## 工具函数

```python
from di import (
    get_bean, get_beans, get_bean_by_type, get_beans_by_type,
    register_bean, register_factory, contains_bean,
    enable_mock_mode, disable_mock_mode, clear_container,
    print_container_info
)

# 获取Bean
bean = get_bean("bean_name")
bean = get_bean_by_type(BeanType)
beans = get_beans_by_type(BeanType)

# 注册Bean
register_bean(MyClass, instance, name="my_bean")
register_factory(MyClass, factory_method)

# Mock模式控制
enable_mock_mode()
disable_mock_mode()

# 容器管理
clear_container()
print_container_info()
```

## 自动扫描

```python
from di import scan_packages, auto_scan

# 自动扫描项目（智能检测目录结构）
auto_scan()

# 扫描指定路径
scan_packages("path/to/src")

# 扫描时排除路径
scan_packages("src", exclude_paths=["test", "mock"])
```

## 循环依赖检测

框架会自动检测循环依赖并抛出 `CircularDependencyError`：

```python
@service("service_a")
class ServiceA:
    def __init__(self, service_b: 'ServiceB'):
        pass

@service("service_b") 
class ServiceB:
    def __init__(self, service_a: ServiceA):
        pass

# 获取时会抛出CircularDependencyError
try:
    service = get_bean_by_type(ServiceA)
except CircularDependencyError as e:
    print(f"检测到循环依赖: {e}")
```

## 高级功能

### 延迟注入
```python
from di import lazy_inject

class MyService:
    def __init__(self):
        # 延迟获取依赖，避免循环依赖
        self.lazy_repo = lazy_inject(UserRepository)
    
    def process(self):
        repo = self.lazy_repo()  # 调用时才获取
        return repo.find_by_id(1)
```

### 函数依赖注入
```python
from di import inject

@inject
def process_user(user_service: UserService, config: ConfigManager):
    # 参数会自动注入
    user = user_service.get_user(1)
    return user
```

### 条件注册
```python
from di import conditional_register

conditional_register(
    lambda: os.getenv("ENV") == "production",
    ProductionService,
    instance
)
```

## 完整示例

请查看 `examples.py` 文件获取完整的使用示例，包含：
- 基本用法演示
- 多实现管理
- Mock模式切换
- Factory功能使用
- 复杂服务依赖注入

## 最佳实践

1. **接口设计** - 使用抽象基类定义清晰的接口
2. **Primary机制** - 为常用接口提供Primary实现
3. **Mock测试** - 为外部依赖提供Mock实现
4. **Factory模式** - 对复杂对象创建使用Factory
5. **避免循环依赖** - 设计时避免循环依赖，必要时使用延迟注入 