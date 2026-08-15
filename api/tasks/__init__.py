"""Фоновые задачи приложения (живут в процессе api, запускаются в `lifespan`)."""

from __future__ import annotations

from api.tasks.notification_loop import NotificationLoop
from api.tasks.rollover_loop import RolloverLoop

__all__ = ["NotificationLoop", "RolloverLoop"]
