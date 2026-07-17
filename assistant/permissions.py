"""Central permission policy applied before every tool execution."""

from __future__ import annotations

from dataclasses import dataclass

from assistant.confirmation import ConfirmationService
from assistant.models import RiskLevel
from config import PermissionConfig


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    allowed: bool
    notify: bool = False
    requires_confirmation: bool = False
    reason: str = ""


class PermissionManager:
    """Evaluate and enforce tool risk without relying on model judgment."""

    def __init__(self, config: PermissionConfig, service: ConfirmationService) -> None:
        self.config = config
        self.service = service

    def assess(self, risk: RiskLevel) -> PermissionDecision:
        if risk is RiskLevel.LOW:
            return PermissionDecision(True)
        if risk is RiskLevel.MEDIUM:
            return PermissionDecision(True, notify=self.config.medium_action_notifications)
        return PermissionDecision(
            False,
            requires_confirmation=self.config.high_action_confirmation,
            reason="High-risk action requires explicit local confirmation.",
        )

    async def authorize(self, risk: RiskLevel, description: str) -> bool:
        decision = self.assess(risk)
        if decision.notify:
            await self.service.notify(description)
        if risk is RiskLevel.HIGH:
            if not decision.requires_confirmation:
                return False
            return await self.service.confirm(description)
        return decision.allowed

