# -*- coding: utf-8 -*-
"""
依赖注入容器核心实现

锁使用策略：
- 纯读操作（如 is_mock_mode, contains_bean*）：无锁，因为读取不可变属性
- 修改容器状态的操作：使用 self._lock 保护
- 获取Bean的操作：需要锁，因为可能创建和缓存单例实例
- 全局容器创建：使用 _container_lock 保证单例
"""

import inspect
import abc
from typing import (
    Dict,
    Type,
    TypeVar,
    Optional,
    Any,
    List,
    Set,
    Callable,
    Union,
    get_origin,
    get_args,
)
from threading import RLock
from enum import Enum

from core.di.exceptions import (
    CircularDependencyError,
    BeanNotFoundError,
    DuplicateBeanError,
    FactoryError,
    DependencyResolutionError,
    MockNotEnabledError,
    PrimaryBeanConflictError,
)

T = TypeVar('T')


class BeanScope(Enum):
    """Bean作用域"""

    SINGLETON = "singleton"
    PROTOTYPE = "prototype"
    FACTORY = "factory"


class BeanDefinition:
    """Bean定义"""

    def __init__(
        self,
        bean_type: Type,
        bean_name: str = None,
        scope: BeanScope = BeanScope.SINGLETON,
        is_primary: bool = False,
        is_mock: bool = False,
        factory_method: Callable = None,
        instance: Any = None,
    ):
        self.bean_type = bean_type
        self.bean_name = bean_name or bean_type.__name__.lower()
        self.scope = scope
        self.is_primary = is_primary
        self.is_mock = is_mock
        self.factory_method = factory_method
        self.instance = instance
        self.dependencies: Set[Type] = set()

    def __repr__(self):
        return f"BeanDefinition(type={self.bean_type.__name__}, name={self.bean_name}, scope={self.scope.value})"


class DIContainer:
    """依赖注入容器"""

    def __init__(self):
        self._lock = RLock()
        # 按类型存储Bean定义 {Type: [BeanDefinition]}
        self._bean_definitions: Dict[Type, List[BeanDefinition]] = {}
        # 按名称存储Bean定义 {name: BeanDefinition}
        self._named_beans: Dict[str, BeanDefinition] = {}
        # 存储单例实例 {BeanDefinition: instance}
        self._singleton_instances: Dict[BeanDefinition, Any] = {}
        # Mock模式
        self._mock_mode = False
        # 依赖解析栈，用于检测循环依赖
        self._resolving_stack: List[Type] = []

        # 性能优化缓存
        # 类型继承关系缓存 {parent_type: [child_types]}
        self._inheritance_cache: Dict[Type, List[Type]] = {}
        # Primary Bean快速索引 {Type: BeanDefinition}
        self._primary_beans: Dict[Type, BeanDefinition] = {}
        # 候选Bean缓存 {(Type, mock_mode): [BeanDefinition]}
        self._candidates_cache: Dict[tuple, List[BeanDefinition]] = {}
        # 缓存失效标志
        self._cache_dirty = False

    def enable_mock_mode(self):
        """启用Mock模式"""
        with self._lock:
            if not self._mock_mode:
                self._mock_mode = True
                self._invalidate_cache()

    def disable_mock_mode(self):
        """禁用Mock模式"""
        with self._lock:
            if self._mock_mode:
                self._mock_mode = False
                self._invalidate_cache()

    def is_mock_mode(self) -> bool:
        """检查是否为Mock模式"""
        return self._mock_mode

    def register_bean(
        self,
        bean_type: Type[T],
        bean_name: str = None,
        scope: BeanScope = BeanScope.SINGLETON,
        is_primary: bool = False,
        is_mock: bool = False,
        instance: T = None,
    ) -> 'DIContainer':
        """注册Bean"""
        with self._lock:
            bean_def = BeanDefinition(
                bean_type=bean_type,
                bean_name=bean_name,
                scope=scope,
                is_primary=is_primary,
                is_mock=is_mock,
                instance=instance,
            )

            # 检查重复注册
            if bean_def.bean_name in self._named_beans:
                existing = self._named_beans[bean_def.bean_name]
                if not (is_mock or existing.is_mock):
                    raise DuplicateBeanError(bean_name=bean_def.bean_name)

            # 优化：检查Primary冲突 - 使用索引而不是遍历
            if is_primary:
                existing_primary = self._primary_beans.get(bean_type)
                if existing_primary and not existing_primary.is_mock:
                    raise PrimaryBeanConflictError(
                        bean_type, existing_primary.bean_type, bean_type
                    )

            # 注册Bean定义
            if bean_type not in self._bean_definitions:
                self._bean_definitions[bean_type] = []
            self._bean_definitions[bean_type].append(bean_def)
            self._named_beans[bean_def.bean_name] = bean_def

            # 更新Primary Bean索引
            if is_primary:
                self._primary_beans[bean_type] = bean_def

            # 分析依赖关系
            self._analyze_dependencies(bean_def)

            # 如果提供了实例，直接存储
            if instance is not None:
                self._singleton_instances[bean_def] = instance

            # 使缓存失效
            self._invalidate_cache()

            return self

    def register_factory(
        self,
        bean_type: Type[T],
        factory_method: Callable[[], T],
        bean_name: str = None,
        is_primary: bool = False,
        is_mock: bool = False,
    ) -> 'DIContainer':
        """注册Factory方法"""
        with self._lock:
            bean_def = BeanDefinition(
                bean_type=bean_type,
                bean_name=bean_name,
                scope=BeanScope.FACTORY,
                is_primary=is_primary,
                is_mock=is_mock,
                factory_method=factory_method,
            )

            # 检查重复注册
            if bean_def.bean_name in self._named_beans:
                existing = self._named_beans[bean_def.bean_name]
                if not (is_mock or existing.is_mock):
                    raise DuplicateBeanError(bean_name=bean_def.bean_name)

            # 注册Bean定义
            if bean_type not in self._bean_definitions:
                self._bean_definitions[bean_type] = []
            self._bean_definitions[bean_type].append(bean_def)
            self._named_beans[bean_def.bean_name] = bean_def

            # 更新Primary Bean索引
            if is_primary:
                self._primary_beans[bean_type] = bean_def

            # 使缓存失效
            self._invalidate_cache()

            return self

    def get_bean(self, bean_name: str) -> Any:
        """根据名称获取Bean"""
        with self._lock:
            if bean_name not in self._named_beans:
                raise BeanNotFoundError(bean_name=bean_name)

            bean_def = self._named_beans[bean_name]
            return self._create_instance(bean_def)

    def get_bean_by_type(self, bean_type: Type[T]) -> T:
        """根据类型获取Bean（返回Primary或唯一实现）"""
        with self._lock:
            candidates = self._get_candidates_with_priority(bean_type)

            if not candidates:
                raise BeanNotFoundError(bean_type=bean_type)

            # 如果只有一个候选者，返回它
            if len(candidates) == 1:
                return self._create_instance(candidates[0])

            # 多个候选者，返回优先级最高的
            return self._create_instance(candidates[0])

    def _get_candidates_with_priority(self, bean_type: Type) -> List[BeanDefinition]:
        """获取类型的候选Bean定义（按优先级排序）"""
        # 使用缓存键
        cache_key = (bean_type, self._mock_mode)

        # 检查缓存
        if cache_key in self._candidates_cache:
            return self._candidates_cache[cache_key]

        # 确保继承关系缓存是最新的
        self._build_inheritance_cache()

        # 按优先级收集候选者
        priority_candidates = []

        # 在Mock模式下，优先考虑Mock Bean
        if self._mock_mode:
            mock_candidates = []
            non_mock_candidates = []

            # 1. 最高优先级：Primary Bean（直接匹配）
            primary_bean = self._primary_beans.get(bean_type)
            if primary_bean and self._is_bean_available(primary_bean):
                if primary_bean.is_mock:
                    mock_candidates.append(primary_bean)
                else:
                    non_mock_candidates.append(primary_bean)

            # 2. 高优先级：直接匹配的非Primary Bean
            if bean_type in self._bean_definitions:
                direct_matches = [
                    bean_def
                    for bean_def in self._bean_definitions[bean_type]
                    if self._is_bean_available(bean_def) and not bean_def.is_primary
                ]
                # 按Mock状态分组
                mock_matches = [bd for bd in direct_matches if bd.is_mock]
                non_mock_matches = [bd for bd in direct_matches if not bd.is_mock]

                # 每组内部按Factory优先级排序
                mock_factory_beans = [
                    bd for bd in mock_matches if bd.scope == BeanScope.FACTORY
                ]
                mock_regular_beans = [
                    bd for bd in mock_matches if bd.scope != BeanScope.FACTORY
                ]
                non_mock_factory_beans = [
                    bd for bd in non_mock_matches if bd.scope == BeanScope.FACTORY
                ]
                non_mock_regular_beans = [
                    bd for bd in non_mock_matches if bd.scope != BeanScope.FACTORY
                ]

                mock_candidates.extend(mock_factory_beans)
                mock_candidates.extend(mock_regular_beans)
                non_mock_candidates.extend(non_mock_factory_beans)
                non_mock_candidates.extend(non_mock_regular_beans)

            # 3. 中优先级：接口/抽象类的实现类匹配
            # 先收集所有实现类的bean定义，然后统一排序
            all_mock_impls = []
            all_non_mock_impls = []

            impl_types = self._inheritance_cache.get(bean_type, [])
            for impl_type in impl_types:
                if impl_type in self._bean_definitions:
                    for bean_def in self._bean_definitions[impl_type]:
                        if self._is_bean_available(bean_def):
                            if bean_def.is_mock:
                                all_mock_impls.append(bean_def)
                            else:
                                all_non_mock_impls.append(bean_def)

            # 按Primary和Factory优先级排序所有实现
            def sort_impls(impls):
                primary_impls = [bd for bd in impls if bd.is_primary]
                other_impls = [bd for bd in impls if not bd.is_primary]
                factory_impls = [
                    bd for bd in other_impls if bd.scope == BeanScope.FACTORY
                ]
                regular_impls = [
                    bd for bd in other_impls if bd.scope != BeanScope.FACTORY
                ]
                return primary_impls + factory_impls + regular_impls

            mock_candidates.extend(sort_impls(all_mock_impls))
            non_mock_candidates.extend(sort_impls(all_non_mock_impls))

            # Mock Bean优先，然后是非Mock Bean
            priority_candidates = mock_candidates + non_mock_candidates

        else:
            # 非Mock模式下的原有逻辑
            # 1. 最高优先级：Primary Bean（直接匹配）
            primary_bean = self._primary_beans.get(bean_type)
            if primary_bean and self._is_bean_available(primary_bean):
                priority_candidates.append(primary_bean)

            # 2. 高优先级：直接匹配的非Primary Bean
            if bean_type in self._bean_definitions:
                direct_matches = [
                    bean_def
                    for bean_def in self._bean_definitions[bean_type]
                    if self._is_bean_available(bean_def) and not bean_def.is_primary
                ]
                # Factory优先于普通Bean
                factory_beans = [
                    bd for bd in direct_matches if bd.scope == BeanScope.FACTORY
                ]
                regular_beans = [
                    bd for bd in direct_matches if bd.scope != BeanScope.FACTORY
                ]
                priority_candidates.extend(factory_beans)
                priority_candidates.extend(regular_beans)

            # 3. 中优先级：接口/抽象类的实现类匹配
            # 先收集所有实现类的bean定义，然后统一排序
            all_impls = []

            impl_types = self._inheritance_cache.get(bean_type, [])
            for impl_type in impl_types:
                if impl_type in self._bean_definitions:
                    for bean_def in self._bean_definitions[impl_type]:
                        if self._is_bean_available(bean_def):
                            all_impls.append(bean_def)

            # 按Primary和Factory优先级排序所有实现
            primary_impls = [bd for bd in all_impls if bd.is_primary]
            other_impls = [bd for bd in all_impls if not bd.is_primary]
            factory_impls = [bd for bd in other_impls if bd.scope == BeanScope.FACTORY]
            regular_impls = [bd for bd in other_impls if bd.scope != BeanScope.FACTORY]

            priority_candidates.extend(primary_impls)
            priority_candidates.extend(factory_impls)
            priority_candidates.extend(regular_impls)

        # 缓存结果
        self._candidates_cache[cache_key] = priority_candidates
        return priority_candidates

    def get_beans_by_type(self, bean_type: Type[T]) -> List[T]:
        """根据类型获取所有Bean实现"""
        with self._lock:
            candidates = self._get_candidates_with_priority(bean_type)
            return [self._create_instance(bean_def) for bean_def in candidates]

    def get_beans(self) -> Dict[str, Any]:
        """获取所有已注册的Bean"""
        with self._lock:
            result = {}
            for name, bean_def in self._named_beans.items():
                if self._is_bean_available(bean_def):
                    try:
                        result[name] = self._create_instance(bean_def)
                    except Exception:
                        # 跳过无法创建的Bean
                        continue
            return result

    def contains_bean(self, bean_name: str) -> bool:
        """检查是否包含指定名称的Bean"""
        return bean_name in self._named_beans

    def contains_bean_by_type(self, bean_type: Type) -> bool:
        """检查是否包含指定类型的Bean"""
        return bean_type in self._bean_definitions

    def clear(self):
        """清空容器"""
        with self._lock:
            self._bean_definitions.clear()
            self._named_beans.clear()
            self._singleton_instances.clear()
            self._resolving_stack.clear()
            self._invalidate_cache()

    def list_all_beans_info(self) -> List[Dict[str, Any]]:
        """
        列出所有已注册的Bean信息

        Returns:
            Bean信息列表，每个Bean包含：
            - name: Bean名称
            - type_name: Bean类型名称
            - scope: Bean作用域
            - is_primary: 是否为Primary Bean
            - is_mock: 是否为Mock Bean
        """
        beans_info = []

        # 收集所有Bean信息
        for name, bean_def in self._named_beans.items():
            if self._is_bean_available(bean_def):
                beans_info.append(
                    {
                        'name': name,
                        'type_name': bean_def.bean_type.__name__,
                        'scope': bean_def.scope.value,
                        'is_primary': bean_def.is_primary,
                        'is_mock': bean_def.is_mock,
                    }
                )

        return beans_info

    def _invalidate_cache(self):
        """使所有缓存失效"""
        self._inheritance_cache.clear()
        self._candidates_cache.clear()
        self._cache_dirty = True

    def _is_bean_available(self, bean_def: BeanDefinition) -> bool:
        """检查Bean是否在当前模式下可用"""
        if self._mock_mode:
            # Mock模式下，mock和非mock的bean都可用
            return True
        else:
            # 非Mock模式下，只有非mock的bean可用
            return not bean_def.is_mock

    def _build_inheritance_cache(self):
        """构建类型继承关系缓存"""
        if not self._cache_dirty:
            return

        self._inheritance_cache.clear()

        # 获取已注册的类型
        registered_types = list(self._bean_definitions.keys())

        # 额外收集ABC父类类型（排除abc.ABC基类）
        all_parent_types = set(registered_types)
        for registered_type in registered_types:
            try:
                # 获取所有父类，特别是ABC抽象基类
                for base in registered_type.__mro__[1:]:  # 跳过自身
                    # 排除abc.ABC基类和object基类，它们太通用了
                    if (
                        base != abc.ABC
                        and base != object
                        and hasattr(base, '__abstractmethods__')
                    ):  # ABC类型
                        all_parent_types.add(base)
            except (AttributeError, TypeError):
                # 处理非类型的情况
                continue

        # 为所有类型（包括ABC父类）建立继承关系索引
        # parent_type -> [实现它的子类列表]
        for parent_type in all_parent_types:
            child_implementations = []
            for child_type in registered_types:
                if child_type != parent_type:
                    try:
                        if issubclass(child_type, parent_type):
                            child_implementations.append(child_type)
                    except TypeError:
                        # 处理非类型的情况
                        continue
            if child_implementations:
                self._inheritance_cache[parent_type] = child_implementations

        self._cache_dirty = False

    def _create_instance(self, bean_def: BeanDefinition) -> Any:
        """创建Bean实例"""
        # 检查循环依赖
        if bean_def.bean_type in self._resolving_stack:
            dependency_chain = self._resolving_stack + [bean_def.bean_type]
            raise CircularDependencyError(dependency_chain)

        # 处理不同作用域
        if bean_def.scope == BeanScope.SINGLETON:
            # 单例模式：检查缓存，如果有直接返回
            if bean_def in self._singleton_instances:
                return self._singleton_instances[bean_def]

        elif bean_def.scope == BeanScope.FACTORY:
            # 工厂模式：每次调用工厂方法创建新实例
            if bean_def.factory_method:
                try:
                    return bean_def.factory_method()
                except Exception as e:
                    raise FactoryError(bean_def.bean_type, str(e))
            else:
                raise FactoryError(bean_def.bean_type, "未设置Factory方法")

        elif bean_def.scope == BeanScope.PROTOTYPE:
            # 原型模式：每次都创建新实例，不缓存
            try:
                self._resolving_stack.append(bean_def.bean_type)
                return self._instantiate_with_dependencies(bean_def)
            finally:
                if bean_def.bean_type in self._resolving_stack:
                    self._resolving_stack.remove(bean_def.bean_type)

        # 如果有预设实例，直接返回
        if bean_def.instance is not None:
            return bean_def.instance

        # 创建新实例（SINGLETON 作用域）
        try:
            self._resolving_stack.append(bean_def.bean_type)
            instance = self._instantiate_with_dependencies(bean_def)

            # 存储单例实例
            if bean_def.scope == BeanScope.SINGLETON:
                self._singleton_instances[bean_def] = instance

            return instance
        finally:
            if bean_def.bean_type in self._resolving_stack:
                self._resolving_stack.remove(bean_def.bean_type)

    def _instantiate_with_dependencies(self, bean_def: BeanDefinition) -> Any:
        """实例化Bean并注入依赖"""
        bean_type = bean_def.bean_type

        # 获取构造函数签名
        try:
            signature = inspect.signature(bean_type.__init__)
        except Exception:
            # 如果无法获取签名，尝试无参构造
            return bean_type()

        # 准备构造函数参数
        init_params = {}
        for param_name, param in signature.parameters.items():
            if param_name == 'self':
                continue

            # 尝试根据类型注入依赖
            if param.annotation != inspect.Parameter.empty:
                try:
                    # 检查是否为泛型类型（如 List[T]）
                    origin = get_origin(param.annotation)
                    if origin is list or origin is List:
                        # 处理 List[T] 类型的依赖注入
                        args = get_args(param.annotation)
                        if args:
                            # 获取泛型参数类型
                            element_type = args[0]
                            # 注入该类型的所有实现
                            dependencies = self.get_beans_by_type(element_type)
                            init_params[param_name] = dependencies
                        else:
                            # 如果没有泛型参数，尝试空列表
                            init_params[param_name] = []
                    else:
                        # 普通类型的依赖注入
                        dependency = self.get_bean_by_type(param.annotation)
                        init_params[param_name] = dependency
                except BeanNotFoundError:
                    if param.default == inspect.Parameter.empty:
                        # 必需参数但找不到依赖
                        raise DependencyResolutionError(bean_type, param.annotation)

        return bean_type(**init_params)

    def _analyze_dependencies(self, bean_def: BeanDefinition):
        """分析Bean的依赖关系"""
        try:
            signature = inspect.signature(bean_def.bean_type.__init__)
            for param_name, param in signature.parameters.items():
                if param_name == 'self':
                    continue
                if param.annotation != inspect.Parameter.empty:
                    bean_def.dependencies.add(param.annotation)
        except Exception:
            # 如果无法分析，跳过
            pass


# 全局容器实例
_global_container: Optional[DIContainer] = None
_container_lock = RLock()


def get_container() -> DIContainer:
    """获取全局容器实例"""
    global _global_container
    if _global_container is None:
        with _container_lock:
            if _global_container is None:
                _global_container = DIContainer()
    return _global_container
