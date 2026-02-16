# Dependency Injection Framework Documentation

This is a fully-featured Python dependency injection framework that supports all the requirements you've outlined.

## Core Features

✨ **Interface and Multiple Implementations** - One interface can have multiple implementations, automatically resolving the best implementation
⭐ **Primary Mechanism** - When multiple implementations exist, the Primary implementation is prioritized  
🧪 **Mock Mode** - Supports automatic switching to Mock implementations in test environments
🏭 **Factory Functionality** - Supports factory methods for bean creation, flexible control over instance creation
🔄 **Circular Dependency Detection** - Automatically detects and prevents circular dependencies with clear error messages
📡 **Auto Scanning** - Intelligently scans project files and automatically registers annotated components
🛠️ **Convenient Tools** - Rich utility functions to simplify daily usage

## Quick Start

### Basic Usage

```python
from di import component, service, repository, get_bean_by_type
from abc import ABC, abstractmethod

# Define interface
class UserRepository(ABC):
    @abstractmethod
    def find_by_id(self, user_id: int) -> dict:
        pass

# Implementation class
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

# Usage
user_service = get_bean_by_type(UserService)
user = user_service.get_user(1)
```

### Multiple Implementations and Primary Mechanism

```python
@repository("mysql_repo")
class MySQLUserRepository(UserRepository):
    def find_by_id(self, user_id: int) -> dict:
        return {"id": user_id, "source": "mysql"}

@repository("redis_repo")  
class RedisUserRepository(UserRepository):
    def find_by_id(self, user_id: int) -> dict:
        return {"id": user_id, "source": "redis"}

# Primary implementation
@repository("primary_repo", primary=True)
class PrimaryUserRepository(UserRepository):
    def find_by_id(self, user_id: int) -> dict:
        return {"id": user_id, "source": "primary"}

# Get Primary implementation
repo = get_bean_by_type(UserRepository)  # Returns PrimaryUserRepository

# Get all implementations
all_repos = get_beans_by_type(UserRepository)  # Returns all 3 implementations
```

### Mock Mode

```python
from di import mock_impl, enable_mock_mode, disable_mock_mode

# Mock implementation
@mock_impl("mock_user_repo")
class MockUserRepository(UserRepository):
    def find_by_id(self, user_id: int) -> dict:
        return {"id": user_id, "name": "Mock User"}

# Enable Mock mode
enable_mock_mode()

# Now gets the Mock implementation
repo = get_bean_by_type(UserRepository)  # Returns MockUserRepository

# Disable Mock mode
disable_mock_mode()
```

### Factory Functionality

```python
from di import factory

@factory(UserRepository, "factory_repo")
def create_user_repository() -> UserRepository:
    # Complex creation logic
    config = load_config()
    if config.use_cache:
        return RedisUserRepository()
    else:
        return MySQLUserRepository()

# Each call executes the factory method
repo = get_bean("factory_repo")
```

## Decorator Reference

### @component - General Component
```python
@component("my_component")
class MyComponent:
    pass
```

### @service - Service Layer Component
```python
@service("user_service")
class UserService:
    def __init__(self, repository: UserRepository):
        self.repository = repository
```

### @repository - Data Access Layer Component
```python
@repository("user_repository")
class UserRepositoryImpl(UserRepository):
    pass
```

### @mock_impl - Mock Implementation
```python
@mock_impl("mock_service")
class MockServiceImpl(ServiceInterface):
    pass
```

### @factory - Factory Method
```python
@factory(ServiceInterface, "service_factory")
def create_service() -> ServiceInterface:
    return ComplexServiceImpl()
```

## Utility Functions

```python
from di import (
    get_bean, get_beans, get_bean_by_type, get_beans_by_type,
    register_bean, register_factory, contains_bean,
    enable_mock_mode, disable_mock_mode, clear_container,
    print_container_info
)

# Get Bean
bean = get_bean("bean_name")
bean = get_bean_by_type(BeanType)
beans = get_beans_by_type(BeanType)

# Register Bean
register_bean(MyClass, instance, name="my_bean")
register_factory(MyClass, factory_method)

# Mock mode control
enable_mock_mode()
disable_mock_mode()

# Container management
clear_container()
print_container_info()
```

## Auto Scanning

```python
from di import scan_packages, auto_scan

# Auto scan project (intelligently detects directory structure)
auto_scan()

# Scan specific path
scan_packages("path/to/src")

# Exclude paths during scanning
scan_packages("src", exclude_paths=["test", "mock"])
```

## Circular Dependency Detection

The framework automatically detects circular dependencies and throws `CircularDependencyError`:

```python
@service("service_a")
class ServiceA:
    def __init__(self, service_b: 'ServiceB'):
        pass

@service("service_b") 
class ServiceB:
    def __init__(self, service_a: ServiceA):
        pass

# Will throw CircularDependencyError when retrieved
try:
    service = get_bean_by_type(ServiceA)
except CircularDependencyError as e:
    print(f"Circular dependency detected: {e}")
```

## Advanced Features

### Lazy Injection
```python
from di import lazy_inject

class MyService:
    def __init__(self):
        # Lazy dependency retrieval to avoid circular dependencies
        self.lazy_repo = lazy_inject(UserRepository)
    
    def process(self):
        repo = self.lazy_repo()  # Retrieved when called
        return repo.find_by_id(1)
```

### Function Dependency Injection
```python
from di import inject

@inject
def process_user(user_service: UserService, config: ConfigManager):
    # Parameters are automatically injected
    user = user_service.get_user(1)
    return user
```

### Conditional Registration
```python
from di import conditional_register

conditional_register(
    lambda: os.getenv("ENV") == "production",
    ProductionService,
    instance
)
```

## Complete Example

Please refer to the `examples.py` file for complete usage examples, including:
- Basic usage demonstration
- Multiple implementation management
- Mock mode switching
- Factory functionality usage
- Complex service dependency injection

## Best Practices

1. **Interface Design** - Use abstract base classes to define clear interfaces
2. **Primary Mechanism** - Provide Primary implementations for commonly used interfaces
3. **Mock Testing** - Provide Mock implementations for external dependencies
4. **Factory Pattern** - Use Factory for complex object creation
5. **Avoid Circular Dependencies** - Design to avoid circular dependencies, use lazy injection when necessary

