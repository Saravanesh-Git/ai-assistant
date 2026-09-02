"""Read-only Linux system information tools."""

from __future__ import annotations

import os
import platform
import socket
import time
from pathlib import Path
from typing import Any

import psutil


def human_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} TB"


def _cpu_name() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except (OSError, IndexError):
        pass
    return platform.processor() or "Unknown"


def _os_name() -> str:
    try:
        values: dict[str, str] = {}
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key] = value.strip().strip('"')
        return values.get("PRETTY_NAME", platform.system())
    except OSError:
        return platform.platform()


def _format_uptime(seconds: float) -> str:
    total = max(0, int(seconds))
    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{days}d {hours}h {minutes}m"


def get_system_info_data() -> dict[str, Any]:
    memory = psutil.virtual_memory()
    return {
        "hostname": socket.gethostname(),
        "os": _os_name(),
        "kernel": platform.release(),
        "architecture": platform.machine(),
        "cpu": _cpu_name(),
        "cpu_cores": psutil.cpu_count(logical=True) or os.cpu_count() or 1,
        "ram_total": human_bytes(memory.total),
        "uptime": _format_uptime(time.time() - psutil.boot_time()),
    }


def get_cpu_usage_data() -> dict[str, Any]:
    try:
        load_average = [round(number, 2) for number in os.getloadavg()]
    except OSError:
        load_average = []
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "cores": psutil.cpu_count(logical=True) or os.cpu_count() or 1,
        "load_average": load_average,
    }


def get_memory_usage_data() -> dict[str, Any]:
    memory = psutil.virtual_memory()
    return {
        "total": human_bytes(memory.total),
        "used": human_bytes(memory.used),
        "available": human_bytes(memory.available),
        "percent": memory.percent,
    }


def get_disk_usage_data(path: str = "/") -> dict[str, Any]:
    candidate = Path(path).expanduser().resolve(strict=True)
    if not candidate.is_dir():
        raise ValueError("Disk usage path must be an existing directory")
    usage = psutil.disk_usage(str(candidate))
    return {
        "path": str(candidate),
        "total": human_bytes(usage.total),
        "used": human_bytes(usage.used),
        "free": human_bytes(usage.free),
        "percent": usage.percent,
    }


def get_battery_status_data() -> dict[str, Any]:
    battery = psutil.sensors_battery()
    if battery is None:
        return {"available": False}
    return {
        "available": True,
        "percent": round(battery.percent, 1),
        "plugged": bool(battery.power_plugged),
    }

