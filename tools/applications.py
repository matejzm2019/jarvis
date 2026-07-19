"""Safe application discovery, opening, focusing, and process listing."""

from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import psutil
from pydantic import BaseModel, ConfigDict, Field
from rapidfuzz import fuzz, process

from assistant.models import RiskLevel, ToolResult
from config import ApplicationConfig, AllowedApplication
from tools.base import BaseTool, EmptyArguments

try:
    import win32con
    import win32gui
    import win32process
    import winreg
except ImportError:  # pragma: no cover - exercised only off Windows/missing pywin32
    win32con = win32gui = win32process = winreg = None  # type: ignore[assignment]


class ApplicationNameArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)


@dataclass(frozen=True, slots=True)
class ApplicationTarget:
    name: str
    path: Path | None
    source: str
    process_name: str | None = None
    uri: str | None = None


class ApplicationCatalog:
    """Resolve configured or locally discovered applications without model-supplied paths."""

    def __init__(self, config: ApplicationConfig, alias_provider: Callable[[], dict[str, str]] | None = None) -> None:
        self.config = config
        self.alias_provider = alias_provider

    def _allowed(self, query: str) -> AllowedApplication:
        choices: dict[str, AllowedApplication] = {}
        for app in self.config.allowlist:
            for label in (app.name, *app.aliases):
                choices[label] = app
        if self.alias_provider:
            by_name = {app.name.casefold(): app for app in self.config.allowlist}
            for alias, target in self.alias_provider().items():
                app = by_name.get(target.casefold())
                if app:
                    choices[alias] = app
        match = process.extractOne(query, choices.keys(), scorer=fuzz.WRatio)
        if not match or match[1] < self.config.fuzzy_match_threshold:
            raise ValueError(f"Application '{query}' is not in the configured allowlist")
        return choices[match[0]]

    @staticmethod
    def running() -> list[dict[str, Any]]:
        applications: dict[tuple[int, str], dict[str, Any]] = {}
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                name = proc.info.get("name") or ""
                if name:
                    applications[(proc.pid, name.casefold())] = {"pid": proc.pid, "name": name}
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                continue
        return sorted(applications.values(), key=lambda item: str(item["name"]).casefold())

    @staticmethod
    def _labels(app: AllowedApplication) -> tuple[str, ...]:
        return tuple(label.casefold() for label in (app.name, *app.aliases))

    def _labels_for_action(self, query: str) -> tuple[str, tuple[str, ...]]:
        try:
            app = self._allowed(query)
            return app.name, self._labels(app)
        except ValueError:
            if not self.config.allow_discovered_applications:
                raise
            return query, (query.casefold(),)

    def _running_target(self, app: AllowedApplication) -> ApplicationTarget | None:
        labels = self._labels(app)
        for proc in psutil.process_iter(["name", "exe"]):
            try:
                proc_name = str(proc.info.get("name") or "")
                stem = Path(proc_name).stem.casefold()
                if max((fuzz.WRatio(stem, label) for label in labels), default=0) < 82:
                    continue
                executable = proc.info.get("exe")
                path = Path(executable).resolve() if executable else None
                if path and path.is_file() and path.suffix.casefold() == ".exe":
                    return ApplicationTarget(app.name, path, "running process", proc_name)
            except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
                continue
        return None

    def _shortcut_target(self, app: AllowedApplication) -> ApplicationTarget | None:
        return self._shortcut_match(app.name, self._labels(app))

    @staticmethod
    def _shortcut_candidates() -> list[Path]:
        roots = [
            Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
            Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        ]
        candidates: list[Path] = []
        for root in roots:
            if not root.is_dir():
                continue
            for current, dirs, files in os.walk(root):
                dirs[:] = [item for item in dirs if not item.startswith(".")]
                candidates.extend(
                    Path(current) / item for item in files
                    if Path(item).suffix.casefold() in {".lnk", ".url"}
                )
        return candidates

    def _shortcut_match(self, name: str, labels: tuple[str, ...]) -> ApplicationTarget | None:
        scored = [
            (max(fuzz.WRatio(path.stem.casefold(), label) for label in labels), path)
            for path in self._shortcut_candidates()
        ]
        if not scored:
            return None
        score, path = max(scored, key=lambda item: item[0])
        return ApplicationTarget(path.stem if name == labels[0] else name, path, "Start Menu shortcut") if score >= 82 else None

    def _registry_target(self, app: AllowedApplication) -> ApplicationTarget | None:
        return self._registry_match(app.name, self._labels(app))

    def _registry_match(self, name: str, labels: tuple[str, ...]) -> ApplicationTarget | None:
        if winreg is None:
            return None
        locations = (
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\App Paths"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\App Paths"),
        )
        for hive, key_path in locations:
            try:
                with winreg.OpenKey(hive, key_path) as key:
                    index = 0
                    while True:
                        try:
                            subkey_name = winreg.EnumKey(key, index)
                            index += 1
                        except OSError:
                            break
                        stem = Path(subkey_name).stem.casefold()
                        if max(fuzz.WRatio(stem, label) for label in labels) < 82:
                            continue
                        try:
                            with winreg.OpenKey(key, subkey_name) as subkey:
                                raw, _ = winreg.QueryValueEx(subkey, None)
                            path = Path(str(raw).strip('"')).resolve()
                            if path.is_file() and path.suffix.casefold() == ".exe":
                                return ApplicationTarget(name, path, "App Paths registry")
                        except OSError:
                            continue
            except OSError:
                continue
        return None

    def _running_match(self, name: str, labels: tuple[str, ...]) -> ApplicationTarget | None:
        for proc in psutil.process_iter(["name", "exe"]):
            try:
                process_name = str(proc.info.get("name") or "")
                if max((fuzz.WRatio(Path(process_name).stem.casefold(), label) for label in labels), default=0) < 82:
                    continue
                executable = proc.info.get("exe")
                path = Path(executable).resolve() if executable else None
                if path and path.is_file() and path.suffix.casefold() == ".exe":
                    return ApplicationTarget(name, path, "running process", process_name)
            except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
                continue
        return None

    @staticmethod
    def _steam_roots() -> list[Path]:
        roots: list[Path] = []
        if winreg is not None:
            for hive, key_path, value_name in (
                (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
            ):
                try:
                    with winreg.OpenKey(hive, key_path) as key:
                        value, _ = winreg.QueryValueEx(key, value_name)
                    roots.append(Path(str(value)).expanduser().resolve(strict=False))
                except OSError:
                    continue
        expanded = list(roots)
        for root in roots:
            library_file = root / "steamapps/libraryfolders.vdf"
            try:
                content = library_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for raw in re.findall(r'"path"\s+"([^"]+)"', content, re.IGNORECASE):
                expanded.append(Path(raw.replace("\\\\", "\\")).resolve(strict=False))
        return list(dict.fromkeys(expanded))

    def _steam_match(self, query: str) -> ApplicationTarget | None:
        candidates: list[tuple[int, str, str]] = []
        for root in self._steam_roots():
            for manifest in (root / "steamapps").glob("appmanifest_*.acf"):
                try:
                    content = manifest.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                app_id = re.search(r'"appid"\s+"(\d+)"', content)
                name = re.search(r'"name"\s+"([^"]+)"', content)
                if app_id and name:
                    candidates.append((fuzz.WRatio(query.casefold(), name.group(1).casefold()), name.group(1), app_id.group(1)))
        if not candidates:
            return None
        score, name, app_id = max(candidates, key=lambda item: item[0])
        if score < max(82, self.config.fuzzy_match_threshold):
            return None
        return ApplicationTarget(name, None, "Steam library", uri=f"steam://rungameid/{app_id}")

    def resolve(self, query: str) -> ApplicationTarget:
        try:
            app = self._allowed(query)
        except ValueError:
            if not self.config.allow_discovered_applications:
                raise
            labels = (query.casefold(),)
            target = (
                self._shortcut_match(query, labels)
                or self._steam_match(query)
                or self._registry_match(query, labels)
                or self._running_match(query, labels)
            )
            if target:
                return target
            raise FileNotFoundError(
                f"Could not find installed application or Steam game matching '{query}'"
            ) from None
        if app.executable_path:
            path = Path(app.executable_path).expanduser().resolve()
            if path.is_file() and path.suffix.casefold() in {".exe", ".lnk"}:
                return ApplicationTarget(app.name, path, "configured path", path.name)
            raise FileNotFoundError(f"Configured path for {app.name} does not exist")
        target = self._running_target(app) or self._shortcut_target(app) or self._registry_target(app)
        if not target:
            raise FileNotFoundError(
                f"Could not resolve {app.name}; configure its executable_path or install a Start Menu shortcut"
            )
        return target

    def focus(self, query: str) -> dict[str, Any]:
        if win32gui is None or win32process is None or win32con is None:
            raise RuntimeError("pywin32 is required for window focusing")
        app_name, labels = self._labels_for_action(query)
        matches: list[tuple[int, str, int]] = []

        def collect(hwnd: int, _: object) -> None:
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd).strip()
            if not title:
                return
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            try:
                name = psutil.Process(pid).name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return
            score = max(fuzz.WRatio(Path(name).stem.casefold(), label) for label in labels)
            if score >= 80:
                matches.append((hwnd, title, pid))

        win32gui.EnumWindows(collect, None)
        if not matches:
            raise FileNotFoundError(f"No visible window found for {app_name}")
        hwnd, title, pid = matches[0]
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        return {"application": app_name, "name": app_name, "title": title, "pid": pid}

    def close(self, query: str) -> dict[str, Any]:
        """Request graceful close for visible windows of one allowlisted application."""
        if win32gui is None or win32process is None or win32con is None:
            raise RuntimeError("pywin32 is required for application closing")
        app_name, labels = self._labels_for_action(query)
        handles: list[int] = []

        def collect(hwnd: int, _: object) -> None:
            if not win32gui.IsWindowVisible(hwnd) or not win32gui.GetWindowText(hwnd).strip():
                return
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            try:
                name = Path(psutil.Process(pid).name()).stem.casefold()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return
            if max(fuzz.WRatio(name, label) for label in labels) >= 80:
                handles.append(hwnd)

        win32gui.EnumWindows(collect, None)
        if not handles:
            raise FileNotFoundError(f"No visible window found for {app_name}")
        for hwnd in handles:
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        time.sleep(0.3)
        remaining = sum(bool(win32gui.IsWindow(hwnd)) for hwnd in handles)
        return {"application": app_name, "requested": len(handles), "remaining": remaining}

    @staticmethod
    def foreground() -> dict[str, Any]:
        if win32gui is None or win32process is None:
            raise RuntimeError("pywin32 is required for foreground-window detection")
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            raise RuntimeError("No foreground window is available")
        title = win32gui.GetWindowText(hwnd)
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        try:
            process_name = psutil.Process(pid).name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            process_name = "unknown"
        return {"title": title, "application": process_name, "pid": pid, "handle": hwnd}


class OpenApplicationTool(BaseTool[ApplicationNameArguments]):
    name = "open_application"
    description = "Open a configured or locally discovered installed application or Steam game by name; never accepts an executable path from the model."
    argument_model = ApplicationNameArguments
    risk = RiskLevel.LOW

    def __init__(self, catalog: ApplicationCatalog) -> None:
        super().__init__()
        self.catalog = catalog

    async def execute(self, arguments: ApplicationNameArguments) -> ToolResult:
        target = await asyncio.to_thread(self.catalog.resolve, arguments.name)
        if target.path is None and target.uri is None:
            raise FileNotFoundError(f"No launch path found for {target.name}")
        if os.name != "nt" or not hasattr(os, "startfile"):
            raise RuntimeError("Opening applications is supported only on Windows")
        await asyncio.to_thread(os.startfile, target.uri or str(target.path))  # type: ignore[attr-defined]
        return ToolResult(
            success=True,
            tool=self.name,
            message=f"Opened {target.name}.",
            data={"application": target.name, "source": target.source},
        )


class FocusApplicationTool(BaseTool[ApplicationNameArguments]):
    name = "focus_application"
    description = "Bring a visible window of a configured or discovered running application to the foreground."
    argument_model = ApplicationNameArguments
    risk = RiskLevel.MEDIUM

    def __init__(self, catalog: ApplicationCatalog) -> None:
        super().__init__()
        self.catalog = catalog

    async def execute(self, arguments: ApplicationNameArguments) -> ToolResult:
        data = await asyncio.to_thread(self.catalog.focus, arguments.name)
        return ToolResult(success=True, tool=self.name, message=f"Focused {data['application']}.", data=data)


class CloseApplicationTool(BaseTool[ApplicationNameArguments]):
    name = "close_application"
    description = "Request graceful close of visible windows for a configured or discovered application; never force-kill processes."
    argument_model = ApplicationNameArguments
    risk = RiskLevel.MEDIUM

    def __init__(self, catalog: ApplicationCatalog) -> None:
        super().__init__()
        self.catalog = catalog

    async def execute(self, arguments: ApplicationNameArguments) -> ToolResult:
        data = await asyncio.to_thread(self.catalog.close, arguments.name)
        message = f"Requested close for {data['application']}."
        if data["remaining"]:
            message += f" {data['remaining']} window(s) remain open."
        return ToolResult(success=True, tool=self.name, message=message, data=data)


class ListRunningApplicationsTool(BaseTool[EmptyArguments]):
    name = "list_running_applications"
    description = "List currently running local processes by application name and process ID."
    argument_model = EmptyArguments

    def __init__(self, catalog: ApplicationCatalog) -> None:
        super().__init__()
        self.catalog = catalog

    async def execute(self, arguments: EmptyArguments) -> ToolResult:
        items = await asyncio.to_thread(self.catalog.running)
        return ToolResult(success=True, tool=self.name, message=f"Found {len(items)} running processes.", data={"applications": items})


class FindInstalledApplicationTool(BaseTool[ApplicationNameArguments]):
    name = "find_installed_application"
    description = "Find an installed application or Steam game using configured paths, Start Menu, Steam manifests, App Paths, or running processes."
    argument_model = ApplicationNameArguments

    def __init__(self, catalog: ApplicationCatalog) -> None:
        super().__init__()
        self.catalog = catalog

    async def execute(self, arguments: ApplicationNameArguments) -> ToolResult:
        target = await asyncio.to_thread(self.catalog.resolve, arguments.name)
        return ToolResult(success=True, tool=self.name, message=f"Found {target.name}.", data={"application": target.name, "source": target.source})


class GetForegroundApplicationTool(BaseTool[EmptyArguments]):
    name = "get_foreground_application"
    description = "Get the real foreground Windows application and window title."
    argument_model = EmptyArguments

    def __init__(self, catalog: ApplicationCatalog) -> None:
        super().__init__()
        self.catalog = catalog

    async def execute(self, arguments: EmptyArguments) -> ToolResult:
        data = await asyncio.to_thread(self.catalog.foreground)
        return ToolResult(success=True, tool=self.name, message=f"Foreground application: {data['application']}.", data=data)
