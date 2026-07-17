"""Read-only local system information using Python and Windows APIs."""

from __future__ import annotations

import asyncio
import ctypes
from ctypes import wintypes
import os
import platform
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import psutil
from pydantic import BaseModel, ConfigDict, Field

from assistant.models import ToolResult
from tools.base import BaseTool, EmptyArguments


class DiskArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(default="C:\\", max_length=20)


class SystemTool(BaseTool[Any]):
    argument_model = EmptyArguments


class GetCpuUsageTool(SystemTool):
    name = "get_cpu_usage"
    description = "Get current CPU utilization and processor information from the local computer."

    async def execute(self, arguments: EmptyArguments) -> ToolResult:
        percent = await asyncio.to_thread(psutil.cpu_percent, 0.2, True)
        data = {
            "overall_percent": round(sum(percent) / len(percent), 1) if percent else 0,
            "per_core_percent": percent,
            "logical_cores": psutil.cpu_count(),
            "physical_cores": psutil.cpu_count(logical=False),
            "processor": platform.processor(),
        }
        return ToolResult(success=True, tool=self.name, message=f"CPU usage is {data['overall_percent']}%.", data=data)


class GetMemoryUsageTool(SystemTool):
    name = "get_memory_usage"
    description = "Get current physical memory usage from the local computer."

    async def execute(self, arguments: EmptyArguments) -> ToolResult:
        memory = psutil.virtual_memory()
        data = {"total_bytes": memory.total, "available_bytes": memory.available, "used_bytes": memory.used, "percent": memory.percent}
        return ToolResult(success=True, tool=self.name, message=f"Memory usage is {memory.percent}%.", data=data)


class GetDiskUsageTool(BaseTool[DiskArguments]):
    name = "get_disk_usage"
    description = "Get capacity and usage for a local drive root."
    argument_model = DiskArguments

    async def execute(self, arguments: DiskArguments) -> ToolResult:
        path = Path(arguments.path)
        if os.name == "nt" and (len(path.anchor) != 3 or path != Path(path.anchor)):
            raise ValueError("Only a drive root such as C:\\ is allowed")
        usage = await asyncio.to_thread(psutil.disk_usage, str(path))
        data = {"path": str(path), "total_bytes": usage.total, "used_bytes": usage.used, "free_bytes": usage.free, "percent": usage.percent}
        return ToolResult(success=True, tool=self.name, message=f"Disk usage for {path} is {usage.percent}%.", data=data)


class GetBatteryStatusTool(SystemTool):
    name = "get_battery_status"
    description = "Get local battery percentage and charging state, when a battery exists."

    async def execute(self, arguments: EmptyArguments) -> ToolResult:
        battery = psutil.sensors_battery()
        if battery is None:
            return ToolResult(success=True, tool=self.name, message="No battery was detected.", data={"present": False})
        seconds = None if battery.secsleft < 0 else battery.secsleft
        data = {"present": True, "percent": battery.percent, "plugged_in": battery.power_plugged, "seconds_left": seconds}
        return ToolResult(success=True, tool=self.name, message=f"Battery is at {battery.percent}%.", data=data)


class GetNetworkStatusTool(SystemTool):
    name = "get_network_status"
    description = "List active local network interfaces without reading browser or authentication data."

    async def execute(self, arguments: EmptyArguments) -> ToolResult:
        interfaces = [
            {"name": name, "speed_mbps": stats.speed, "mtu": stats.mtu}
            for name, stats in psutil.net_if_stats().items() if stats.isup
        ]
        return ToolResult(success=True, tool=self.name, message=f"{len(interfaces)} network interfaces are active.", data={"interfaces": interfaces})


class GetCurrentTimeTool(SystemTool):
    name = "get_current_time"
    description = "Get the current local date, time, and timezone from Windows."

    async def execute(self, arguments: EmptyArguments) -> ToolResult:
        now = datetime.now().astimezone()
        return ToolResult(success=True, tool=self.name, message=now.strftime("%H:%M"), data={"iso": now.isoformat(), "timezone": str(now.tzinfo)})


class GetSystemUptimeTool(SystemTool):
    name = "get_system_uptime"
    description = "Get local Windows system boot time and uptime."

    async def execute(self, arguments: EmptyArguments) -> ToolResult:
        boot = datetime.fromtimestamp(psutil.boot_time()).astimezone()
        seconds = max(0, int(datetime.now().timestamp() - psutil.boot_time()))
        return ToolResult(success=True, tool=self.name, message=f"System uptime is {timedelta(seconds=seconds)}.", data={"boot_time": boot.isoformat(), "uptime_seconds": seconds})


class GetGpuInformationTool(SystemTool):
    name = "get_gpu_information"
    description = "Get graphics adapter names, driver versions, and reported memory through local Windows WMI."

    @staticmethod
    def _query() -> list[dict[str, Any]]:
        try:
            import win32com.client
        except ImportError as exc:
            raise RuntimeError("pywin32 is required for GPU information") from exc
        service = win32com.client.GetObject("winmgmts:")
        return [
            {
                "name": str(item.Name),
                "driver_version": str(item.DriverVersion),
                "adapter_ram_bytes": int(item.AdapterRAM) if item.AdapterRAM is not None else None,
            }
            for item in service.InstancesOf("Win32_VideoController")
        ]

    async def execute(self, arguments: EmptyArguments) -> ToolResult:
        items = await asyncio.to_thread(self._query)
        return ToolResult(success=True, tool=self.name, message=f"Found {len(items)} graphics adapters.", data={"adapters": items})


class GetConnectedBluetoothDevicesTool(SystemTool):
    name = "get_connected_bluetooth_devices"
    description = "List currently connected Bluetooth device names and addresses using native Windows Bluetooth APIs."

    @staticmethod
    def _query() -> list[dict[str, str]]:
        if os.name != "nt":
            raise RuntimeError("Bluetooth enumeration is supported only on Windows")

        class RadioParams(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD)]

        class SearchParams(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD), ("fReturnAuthenticated", wintypes.BOOL),
                ("fReturnRemembered", wintypes.BOOL), ("fReturnUnknown", wintypes.BOOL),
                ("fReturnConnected", wintypes.BOOL), ("fIssueInquiry", wintypes.BOOL),
                ("cTimeoutMultiplier", ctypes.c_ubyte), ("hRadio", wintypes.HANDLE),
            ]

        class SystemTime(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ushort) for name in (
                "year", "month", "day_of_week", "day", "hour", "minute", "second", "milliseconds"
            )]

        class DeviceInfo(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD), ("address", ctypes.c_ulonglong),
                ("class_of_device", wintypes.DWORD), ("connected", wintypes.BOOL),
                ("remembered", wintypes.BOOL), ("authenticated", wintypes.BOOL),
                ("last_seen", SystemTime), ("last_used", SystemTime),
                ("name", ctypes.c_wchar * 248),
            ]

        bluetooth = ctypes.WinDLL("bthprops.cpl")
        bluetooth.BluetoothFindFirstRadio.argtypes = [ctypes.POINTER(RadioParams), ctypes.POINTER(wintypes.HANDLE)]
        bluetooth.BluetoothFindFirstRadio.restype = wintypes.HANDLE
        bluetooth.BluetoothFindNextRadio.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.HANDLE)]
        bluetooth.BluetoothFindNextRadio.restype = wintypes.BOOL
        bluetooth.BluetoothFindRadioClose.argtypes = [wintypes.HANDLE]
        bluetooth.BluetoothFindRadioClose.restype = wintypes.BOOL
        bluetooth.BluetoothFindFirstDevice.argtypes = [ctypes.POINTER(SearchParams), ctypes.POINTER(DeviceInfo)]
        bluetooth.BluetoothFindFirstDevice.restype = wintypes.HANDLE
        bluetooth.BluetoothFindNextDevice.argtypes = [wintypes.HANDLE, ctypes.POINTER(DeviceInfo)]
        bluetooth.BluetoothFindNextDevice.restype = wintypes.BOOL
        bluetooth.BluetoothFindDeviceClose.argtypes = [wintypes.HANDLE]
        bluetooth.BluetoothFindDeviceClose.restype = wintypes.BOOL
        radio = wintypes.HANDLE()
        radio_find = bluetooth.BluetoothFindFirstRadio(
            ctypes.byref(RadioParams(ctypes.sizeof(RadioParams))), ctypes.byref(radio)
        )
        if not radio_find:
            return []
        devices: dict[int, dict[str, str]] = {}
        try:
            while True:
                params = SearchParams(ctypes.sizeof(SearchParams), False, False, False, True, False, 0, radio)
                info = DeviceInfo(dwSize=ctypes.sizeof(DeviceInfo))
                device_find = bluetooth.BluetoothFindFirstDevice(ctypes.byref(params), ctypes.byref(info))
                if device_find:
                    try:
                        while True:
                            if info.connected:
                                address = int(info.address)
                                devices[address] = {
                                    "name": info.name or "Unknown Bluetooth device",
                                    "address": ":".join(f"{address:012X}"[index:index + 2] for index in range(0, 12, 2)),
                                }
                            info.dwSize = ctypes.sizeof(DeviceInfo)
                            if not bluetooth.BluetoothFindNextDevice(device_find, ctypes.byref(info)):
                                break
                    finally:
                        bluetooth.BluetoothFindDeviceClose(device_find)
                next_radio = wintypes.HANDLE()
                if not bluetooth.BluetoothFindNextRadio(radio_find, ctypes.byref(next_radio)):
                    break
                ctypes.windll.kernel32.CloseHandle(radio)
                radio = next_radio
        finally:
            ctypes.windll.kernel32.CloseHandle(radio)
            bluetooth.BluetoothFindRadioClose(radio_find)
        return list(devices.values())

    async def execute(self, arguments: EmptyArguments) -> ToolResult:
        items = await asyncio.to_thread(self._query)
        return ToolResult(
            success=True, tool=self.name,
            message=f"Found {len(items)} connected Bluetooth devices.",
            data={"devices": items},
        )


def build_system_tools() -> list[BaseTool[Any]]:
    return [
        GetCpuUsageTool(), GetGpuInformationTool(), GetMemoryUsageTool(), GetDiskUsageTool(),
        GetBatteryStatusTool(), GetNetworkStatusTool(), GetCurrentTimeTool(), GetSystemUptimeTool(),
        GetConnectedBluetoothDevicesTool(),
    ]
