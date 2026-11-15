"""Модуль A — сбор данных и модель пользователя (Python)."""

from .module_a import ModuleA
from .user_model_manager import UserModelManager
from .package_builder import PackageBuilder
from .validation import ValidationError, validate_interaction_event
from .types import (
    DEFAULT_CONFIG,
    ModuleAConfig,
    InteractionEvent,
    UserModel,
    PackageAtoB,
    AdaptationResult,
    EventType,
    PackageTrigger,
)
from .storage import InMemoryStorage, ScMemoryStorage, HybridStorage, IStorage
from .frontend.event_collector import EventCollector
from .mocks.module_b import MockModuleB
from .mocks.module_c import MockModuleC

__all__ = [
    "ModuleA",
    "UserModelManager",
    "PackageBuilder",
    "ValidationError",
    "validate_interaction_event",
    "DEFAULT_CONFIG",
    "ModuleAConfig",
    "InteractionEvent",
    "UserModel",
    "PackageAtoB",
    "AdaptationResult",
    "EventType",
    "PackageTrigger",
    "InMemoryStorage",
    "ScMemoryStorage",
    "HybridStorage",
    "IStorage",
    "EventCollector",
    "MockModuleB",
    "MockModuleC",
]

__version__ = "0.7.0"
