import asyncio

from assistant.models import RiskLevel
from tools.base import EmptyArguments
from tools.media_controls import GetCurrentTrackTool, PauseMusicTool, SetMediaVolumeTool, VolumeArguments


class FakeMediaController:
    def __init__(self) -> None:
        self.actions: list[str] = []
        self.volume = -1

    async def command(self, action: str):
        self.actions.append(action)
        return {"action": action, "backend": "fake", "confirmed": True}

    async def current_track(self):
        return {"title": "Song", "artist": "Artist", "album": "Album", "status": "playing"}

    async def set_volume(self, percent: int):
        self.volume = percent
        return {"volume_percent": percent, "confirmed": True}


def test_media_tools_use_shared_typed_controller() -> None:
    async def run() -> None:
        controller = FakeMediaController()
        pause = await PauseMusicTool(controller).execute(EmptyArguments())
        track = await GetCurrentTrackTool(controller).execute(EmptyArguments())
        volume_tool = SetMediaVolumeTool(controller)
        volume = await volume_tool.execute(VolumeArguments(percent=37))
        assert pause.success and controller.actions == ["pause"]
        assert track.data["title"] == "Song"
        assert volume.success and controller.volume == 37
        assert volume_tool.risk is RiskLevel.MEDIUM

    asyncio.run(run())
