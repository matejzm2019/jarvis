import asyncio

from assistant.models import RiskLevel
from assistant.permissions import PermissionManager
from config import PermissionConfig


class FakeConfirmation:
    def __init__(self, confirmed: bool = False) -> None:
        self.confirmed = confirmed
        self.notifications: list[str] = []
        self.confirmations: list[str] = []

    async def notify(self, message: str) -> None:
        self.notifications.append(message)

    async def confirm(self, message: str) -> bool:
        self.confirmations.append(message)
        return self.confirmed


def test_low_risk_runs_without_prompt() -> None:
    service = FakeConfirmation()
    manager = PermissionManager(PermissionConfig(), service)
    assert asyncio.run(manager.authorize(RiskLevel.LOW, "inspect"))
    assert not service.notifications and not service.confirmations


def test_medium_risk_notifies() -> None:
    service = FakeConfirmation()
    manager = PermissionManager(PermissionConfig(), service)
    assert asyncio.run(manager.authorize(RiskLevel.MEDIUM, "open file"))
    assert service.notifications == ["open file"]


def test_high_risk_requires_positive_confirmation() -> None:
    denied = PermissionManager(PermissionConfig(), FakeConfirmation(False))
    approved_service = FakeConfirmation(True)
    approved = PermissionManager(PermissionConfig(), approved_service)
    assert not asyncio.run(denied.authorize(RiskLevel.HIGH, "dangerous action"))
    assert asyncio.run(approved.authorize(RiskLevel.HIGH, "dangerous action"))
    assert approved_service.confirmations == ["dangerous action"]

