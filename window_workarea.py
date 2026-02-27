#!/usr/bin/env python3
"""Window work-area helpers for Tk apps on Windows."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import tkinter as tk


_MONITOR_DEFAULTTONEAREST = 2
_SPI_GETWORKAREA = 0x0030


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", _RECT),
        ("rcWork", _RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def _normalize_area(left: int, top: int, right: int, bottom: int) -> tuple[int, int, int, int] | None:
    if right <= left or bottom <= top:
        return None
    return int(left), int(top), int(right), int(bottom)


def _get_area_from_monitor(hwnd: int) -> tuple[int, int, int, int] | None:
    if os.name != "nt" or hwnd <= 0:
        return None
    try:
        user32 = ctypes.windll.user32
        monitor = user32.MonitorFromWindow(wintypes.HWND(hwnd), _MONITOR_DEFAULTTONEAREST)
        if not monitor:
            return None
        monitor_info = _MONITORINFO()
        monitor_info.cbSize = ctypes.sizeof(_MONITORINFO)
        ok = user32.GetMonitorInfoW(monitor, ctypes.byref(monitor_info))
        if not ok:
            return None
        return _normalize_area(
            monitor_info.rcWork.left,
            monitor_info.rcWork.top,
            monitor_info.rcWork.right,
            monitor_info.rcWork.bottom,
        )
    except Exception:
        return None


def _get_primary_work_area() -> tuple[int, int, int, int] | None:
    if os.name != "nt":
        return None
    try:
        user32 = ctypes.windll.user32
        rect = _RECT()
        ok = user32.SystemParametersInfoW(_SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
        if not ok:
            return None
        return _normalize_area(rect.left, rect.top, rect.right, rect.bottom)
    except Exception:
        return None


def get_window_work_area(root: "tk.Tk | tk.Toplevel") -> tuple[int, int, int, int]:
    """Return (left, top, right, bottom) for current window monitor work area."""
    hwnd = 0
    try:
        hwnd = int(root.winfo_id())
    except Exception:
        hwnd = 0

    area = _get_area_from_monitor(hwnd) or _get_primary_work_area()
    if area is not None:
        return area

    sw = max(1, int(root.winfo_screenwidth()))
    sh = max(1, int(root.winfo_screenheight()))
    return 0, 0, sw, sh


def clamp_window_rect(
    *,
    x: int,
    y: int,
    width: int,
    height: int,
    work_area: tuple[int, int, int, int],
    min_width: int = 1,
    min_height: int = 1,
) -> tuple[int, int, int, int]:
    """Clamp a window rect into work-area bounds."""
    left, top, right, bottom = work_area
    area_w = max(1, right - left)
    area_h = max(1, bottom - top)

    min_w = max(1, int(min_width))
    min_h = max(1, int(min_height))
    w = min(area_w, max(min_w, int(width)))
    h = min(area_h, max(min_h, int(height)))

    max_x = right - w
    max_y = bottom - h
    clamped_x = min(max(int(x), left), max_x)
    clamped_y = min(max(int(y), top), max_y)
    return clamped_x, clamped_y, w, h

