"""Background controller joining wake word, voice, tray, and local UI."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path

from assistant.confirmation import TkConfirmationService
from assistant.orchestrator import JarvisOrchestrator
from assistant.state import AssistantStatus
from assistant.voice_runtime import VoiceAssistantRuntime
from audio.wake_word import WakeWordDetector, WakeWordError
from config import JarvisConfig
from llm.ollama_client import OllamaClient
from ui.notifications import NotificationCenter
from ui.settings_window import SettingsWindow
from ui.status_window import StatusWindow
from ui.tk_host import TkHost
from ui.tray import TrayApplication, TrayCallbacks
from utils.paths import LOG_DIR, PROJECT_ROOT, ensure_runtime_directories


class DesktopAssistantRuntime:
    """Run Jarvis continuously with local Windows UI and no cloud services."""

    def __init__(self, config: JarvisConfig, client: OllamaClient, config_path: Path) -> None:
        self.config = config
        self.client = client
        self.config_path = config_path.resolve()
        self.notifications = NotificationCenter()
        self.tk_host = TkHost()
        self.assistant = JarvisOrchestrator(
            config, client, confirmation_service=TkConfirmationService(self.notifications, self.tk_host)
        )
        self.voice = VoiceAssistantRuntime(
            config,
            self.assistant,
            before_activation=self._pause_wake_word,
            during_speech=self._resume_wake_word_for_interruption,
            after_activation=self._resume_wake_word,
        )
        self.wake_word = WakeWordDetector(config.wake_word, config.audio, self._wake_detected)
        self.status_window = StatusWindow(self.assistant.state, self.tk_host)
        self.settings_window = SettingsWindow(
            self.config_path,
            self.tk_host,
            lambda: self.notifications.notify("Settings saved. Restart Jarvis to apply them."),
        )
        self.tray = TrayApplication(self.assistant.state, self._tray_callbacks())
        self._loop: asyncio.AbstractEventLoop | None = None
        self._shutdown = asyncio.Event()
        self._wake_enabled = config.wake_word.enabled
        self._closing = False
        self._restart = False
        self._tk_task: asyncio.Task[None] | None = None
        self.log = logging.getLogger("jarvis.desktop")

    def _tray_callbacks(self) -> TrayCallbacks:
        return TrayCallbacks(
            start_listening=lambda: self._schedule(self._set_wake_enabled(True)),
            stop_listening=lambda: self._schedule(self._set_wake_enabled(False)),
            push_to_talk=self._push_to_talk,
            toggle_mute=lambda: self._schedule(self._toggle_mute()),
            stop_speaking=lambda: self._schedule(self.voice.stop_current()),
            open_settings=self.settings_window.open,
            open_status=self.status_window.open,
            open_logs=self._open_logs,
            clear_history=lambda: self._schedule(self._clear_history()),
            restart=lambda: self._request_shutdown(restart=True),
            quit=self._request_shutdown,
            is_muted=lambda: self.voice.muted,
            is_listening=lambda: self._wake_enabled,
        )

    def _schedule(self, coroutine: object) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            if hasattr(coroutine, "close"):
                coroutine.close()  # type: ignore[attr-defined]
            return
        loop.call_soon_threadsafe(asyncio.create_task, coroutine)

    def _push_to_talk(self) -> None:
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self.voice.request_activation)

    def _wake_detected(self, score: float) -> None:
        self.log.info("Wake word detected score=%.3f", score)
        self._push_to_talk()

    async def _pause_wake_word(self) -> None:
        if self.wake_word.is_running:
            await asyncio.to_thread(self.wake_word.stop)

    async def _resume_wake_word(self) -> None:
        delay = self.config.wake_word.resume_delay_seconds
        if delay:
            await asyncio.sleep(delay)
        if not self._closing and self._wake_enabled and not self.wake_word.is_running:
            try:
                await asyncio.to_thread(self.wake_word.start)
            except WakeWordError as exc:
                self.log.error("Wake-word restart failed: %s", exc)
                self.assistant.state.set(AssistantStatus.ERROR)
                self.notifications.notify(str(exc), "Jarvis wake-word error")

    async def _resume_wake_word_for_interruption(self) -> None:
        """Listen for a new wake word during speech so it can interrupt Piper."""
        if not self._closing and self._wake_enabled and not self.wake_word.is_running:
            try:
                await asyncio.to_thread(self.wake_word.start)
            except WakeWordError as exc:
                self.log.error("Wake-word barge-in start failed: %s", exc)

    async def _set_wake_enabled(self, enabled: bool) -> None:
        self._wake_enabled = enabled
        try:
            if enabled:
                await asyncio.to_thread(self.wake_word.start)
                self.notifications.notify(f"Listening for ‘{self.config.wake_word.phrase}’.")
            else:
                await asyncio.to_thread(self.wake_word.stop)
                self.notifications.notify("Wake-word listening stopped.")
        except WakeWordError as exc:
            self._wake_enabled = False
            self.assistant.state.set(AssistantStatus.ERROR)
            self.notifications.notify(str(exc), "Jarvis wake-word error")
        finally:
            self.tray.refresh_menu()

    async def _toggle_mute(self) -> None:
        await self.voice.set_muted(not self.voice.muted)
        self.notifications.notify("Assistant muted." if self.voice.muted else "Assistant unmuted.")
        self.tray.refresh_menu()

    async def _clear_history(self) -> None:
        self.assistant.conversation.clear()
        self.notifications.notify("Conversation history cleared.")

    @staticmethod
    def _open_logs() -> None:
        ensure_runtime_directories()
        if os.name == "nt":
            os.startfile(LOG_DIR)  # type: ignore[attr-defined]

    def _request_shutdown(self, restart: bool = False) -> None:
        self._restart = restart
        loop = self._loop
        if loop and not loop.is_closed():
            loop.call_soon_threadsafe(self._shutdown.set)

    async def start(self) -> None:
        """Start tray, hotkeys, voice services, and optional wake listening."""
        self._loop = asyncio.get_running_loop()
        self.tk_host.start()
        self._tk_task = asyncio.create_task(self._pump_tk(), name="jarvis-tk-pump")
        self.tray.start()
        self.notifications.attach(self.tray.notify)
        await self.voice.start()
        if self._wake_enabled:
            await self._set_wake_enabled(True)
        self.notifications.notify(
            f"Jarvis is ready. Push to talk: {self.config.hotkeys.push_to_talk}", "Jarvis ready"
        )

    async def _pump_tk(self) -> None:
        while not self._closing:
            self.tk_host.poll()
            await asyncio.sleep(0.02)

    async def run_forever(self) -> None:
        """Run until Quit or Restart is selected from the tray."""
        try:
            await self.start()
            await self._shutdown.wait()
        finally:
            await self.close()
        if self._restart:
            self._launch_restart()

    async def close(self) -> None:
        """Orderly stop all microphone, audio, hotkey, and UI resources."""
        if self._closing:
            return
        self._closing = True
        self._wake_enabled = False
        await asyncio.to_thread(self.wake_word.stop)
        await self.voice.close()
        self.settings_window.close()
        self.status_window.close()
        self.tk_host.stop()
        if self._tk_task and self._tk_task is not asyncio.current_task():
            self._tk_task.cancel()
            await asyncio.gather(self._tk_task, return_exceptions=True)
        self._tk_task = None
        self.notifications.detach()
        self.tray.stop()

    def _launch_restart(self) -> None:
        if getattr(sys, "frozen", False):
            subprocess.Popen(
                [sys.executable, "--config", str(self.config_path), "--tray"],
                cwd=Path(sys.executable).parent,
                close_fds=True,
                creationflags=0x00000008 | 0x00000200,
            )
            return
        python = Path(sys.executable)
        pythonw = python.with_name("pythonw.exe")
        executable = pythonw if pythonw.is_file() else python
        creation_flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0
        subprocess.Popen(
            [str(executable), str(PROJECT_ROOT / "main.py"), "--config", str(self.config_path), "--tray"],
            cwd=PROJECT_ROOT,
            close_fds=True,
            creationflags=creation_flags,
        )
