"""Desktop and GSConnect (KDE Connect) alerts."""

from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from dataclasses import dataclass


@dataclass
class PushResult:
    desktop: bool
    gsconnect: bool
    device: str
    detail: str


def notify_desktop(title: str, body: str) -> bool:
    if not shutil.which("notify-send"):
        return False
    try:
        subprocess.run(
            ["notify-send", "--app-name=Assistant", "--urgency=normal", title, body],
            check=False,
            timeout=5,
        )
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


def _list_gsconnect_devices() -> list[tuple[str, str, bool]]:
    if not shutil.which("gdbus"):
        return []
    try:
        raw = subprocess.check_output(
            [
                "gdbus",
                "call",
                "--session",
                "--dest",
                "org.gnome.Shell.Extensions.GSConnect",
                "--object-path",
                "/org/gnome/Shell/Extensions/GSConnect",
                "--method",
                "org.freedesktop.DBus.ObjectManager.GetManagedObjects",
            ],
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []
    devices: list[tuple[str, str, bool]] = []
    for line in raw.splitlines():
        if "object path" not in line:
            continue
        path = line.split('"')[1]
        if "/Device/" not in path:
            continue
        try:
            name_out = subprocess.check_output(
                [
                    "gdbus",
                    "call",
                    "--session",
                    "--dest",
                    "org.gnome.Shell.Extensions.GSConnect",
                    "--object-path",
                    path,
                    "--method",
                    "org.freedesktop.DBus.Properties.Get",
                    "org.gnome.Shell.Extensions.GSConnect.Device",
                    "Name",
                ],
                text=True,
                timeout=3,
            )
            connected_out = subprocess.check_output(
                [
                    "gdbus",
                    "call",
                    "--session",
                    "--dest",
                    "org.gnome.Shell.Extensions.GSConnect",
                    "--object-path",
                    path,
                    "--method",
                    "org.freedesktop.DBus.Properties.Get",
                    "org.gnome.Shell.Extensions.GSConnect.Device",
                    "Connected",
                ],
                text=True,
                timeout=3,
            )
            name = name_out.strip().split("(")[-1].rstrip("),").strip("'")
            connected = "true" in connected_out.lower()
            devices.append((path, name, connected))
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            continue
    return devices


def push_gsconnect(title: str, body: str, device_path: str | None = None) -> tuple[bool, str]:
    devices = _list_gsconnect_devices()
    if not devices:
        return False, "No GSConnect devices found. Pair your phone in GNOME Settings."
    target = None
    if device_path:
        for path, name, connected in devices:
            if path == device_path and connected:
                target = (path, name)
                break
    if target is None:
        for path, name, connected in devices:
            if connected:
                target = (path, name)
                break
    if target is None:
        return False, "No connected GSConnect device."
    path, name = target
    def dbus_str(value: str) -> str:
        escaped = value.replace("'", "'\\''")
        return f"'{escaped}'"

    nid = str(uuid.uuid4())
    payload = (
        "{'appName': <'Assistant'>, "
        f"'id': <'{nid}'>, "
        f"'title': <{dbus_str(title)}>, "
        f"'text': <{dbus_str(body)}>, "
        f"'ticker': <{dbus_str(title)}>, "
        f"'time': <'{nid[:8]}'>, "
        "'isClearable': <true>}"
    )
    try:
        subprocess.run(
            [
                "gdbus",
                "call",
                "--session",
                "--dest",
                "org.gnome.Shell.Extensions.GSConnect",
                "--object-path",
                path,
                "--method",
                "org.gtk.Actions.Activate",
                "sendNotification",
                f"[<{payload}>]",
                "[]",
            ],
            check=True,
            timeout=8,
        )
        return True, name
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)


def push_alert(title: str, body: str, use_gsconnect: bool, device_path: str = "") -> PushResult:
    desktop = notify_desktop(title, body)
    gs_ok = False
    device = ""
    detail = "Desktop notification sent." if desktop else "notify-send unavailable."
    if use_gsconnect:
        gs_ok, info = push_gsconnect(title, body, device_path or None)
        device = info if gs_ok else ""
        detail = f"{detail} GSConnect: {info}."
    return PushResult(desktop=desktop, gsconnect=gs_ok, device=device, detail=detail)
