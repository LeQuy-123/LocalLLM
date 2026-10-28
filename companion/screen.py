"""Screen awareness: foreground-window tracking (cheap, constant) + screenshots for the vision model (on demand)."""
from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes as wt
import io
import os

import mss
from PIL import Image

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


def foreground_window() -> tuple[str, str]:
    """Returns (process_name, window_title) of the active window."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "", ""
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    title = buf.value

    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    proc = ""
    handle = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if handle:
        size = wt.DWORD(512)
        pbuf = ctypes.create_unicode_buffer(512)
        if kernel32.QueryFullProcessImageNameW(handle, 0, pbuf, ctypes.byref(size)):
            proc = os.path.splitext(os.path.basename(pbuf.value))[0]
        kernel32.CloseHandle(handle)
    return proc, title


def idle_seconds() -> float:
    """Seconds since the last keyboard/mouse input."""
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wt.UINT), ("dwTime", wt.DWORD)]
    info = LASTINPUTINFO(cbSize=ctypes.sizeof(LASTINPUTINFO))
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    return (kernel32.GetTickCount() - info.dwTime) / 1000.0


def screenshot_b64(max_width: int = 1280) -> str:
    """Primary monitor as base64 JPEG (never written to disk)."""
    with mss.mss() as sct:
        shot = sct.grab(sct.monitors[1])
        img = Image.frombytes("RGB", shot.size, shot.rgb)
    if img.width > max_width:
        img = img.resize((max_width, int(img.height * max_width / img.width)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode()


def is_private(proc: str, title: str, blocklist: list[str]) -> bool:
    hay = f"{proc} {title}".lower()
    return any(word.lower() in hay for word in blocklist)
