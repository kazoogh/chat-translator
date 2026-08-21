from __future__ import annotations

import sys
from typing import Any, ClassVar, Protocol

from game_chat_translator.models import Bounds, WindowIdentity


class ForegroundWindowError(RuntimeError):
    pass


class ForegroundWindowProvider(Protocol):
    def get_active_window(self) -> WindowIdentity | None: ...


class Win32ForegroundWindowProvider:
    """Read documented foreground-window metadata with minimum process rights.

    This adapter never reads game memory, modules, files, command lines, or network traffic.
    """

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    def get_active_window(self) -> WindowIdentity | None:
        if sys.platform != "win32":
            raise ForegroundWindowError("Win32 foreground-window metadata requires Windows")
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            if hasattr(user32, "SetProcessDpiAwarenessContext"):
                user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
                user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
                user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
            user32.GetForegroundWindow.argtypes = []
            user32.GetForegroundWindow.restype = wintypes.HWND
            user32.GetWindowThreadProcessId.argtypes = [
                wintypes.HWND,
                ctypes.POINTER(wintypes.DWORD),
            ]
            user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
            user32.GetWindowTextLengthW.restype = ctypes.c_int
            user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
            user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
            user32.IsIconic.argtypes = [wintypes.HWND]
            user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
            user32.MonitorFromWindow.restype = wintypes.HANDLE
            handle = user32.GetForegroundWindow()
            if not handle:
                return None

            process_id = wintypes.DWORD()
            user32.GetWindowThreadProcessId(handle, ctypes.byref(process_id))

            title_length = user32.GetWindowTextLengthW(handle)
            title_buffer = ctypes.create_unicode_buffer(max(1, title_length + 1))
            user32.GetWindowTextW(handle, title_buffer, len(title_buffer))
            class_buffer = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(handle, class_buffer, len(class_buffer))

            rect = wintypes.RECT()
            if not user32.GetClientRect(handle, ctypes.byref(rect)):
                raise OSError(ctypes.get_last_error(), "GetClientRect failed")
            origin = wintypes.POINT(0, 0)
            if not user32.ClientToScreen(handle, ctypes.byref(origin)):
                raise OSError(ctypes.get_last_error(), "ClientToScreen failed")

            executable = self._executable_basename(kernel32, process_id.value)
            monitor = user32.MonitorFromWindow(handle, 2)
            monitor_id = self._monitor_device_name(user32, monitor)
            if hasattr(user32, "GetDpiForWindow"):
                user32.GetDpiForWindow.argtypes = [wintypes.HWND]
                user32.GetDpiForWindow.restype = wintypes.UINT
                dpi = user32.GetDpiForWindow(handle)
            else:
                dpi = 96
            return WindowIdentity(
                process_id=process_id.value,
                executable=executable,
                title=title_buffer.value,
                window_class=class_buffer.value,
                client_bounds=Bounds(
                    left=origin.x,
                    top=origin.y,
                    width=rect.right - rect.left,
                    height=rect.bottom - rect.top,
                ),
                monitor_id=monitor_id,
                dpi=int(dpi or 96),
                minimized=bool(user32.IsIconic(handle)),
            )
        except (OSError, ValueError) as exc:
            raise ForegroundWindowError("Could not read foreground-window metadata") from exc

    @staticmethod
    def _monitor_device_name(user32: Any, monitor: int) -> str:
        import ctypes
        from ctypes import wintypes

        class MonitorInfo(ctypes.Structure):
            _fields_: ClassVar = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD),
                ("szDevice", wintypes.WCHAR * 32),
            ]

        info = MonitorInfo()
        info.cbSize = ctypes.sizeof(info)
        user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
        user32.GetMonitorInfoW.restype = wintypes.BOOL
        if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return str(info.szDevice)
        return "unknown-monitor"

    def _executable_basename(self, kernel32: Any, process_id: int) -> str:
        import ctypes
        from ctypes import wintypes
        from pathlib import PureWindowsPath

        open_process = kernel32.OpenProcess
        open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        open_process.restype = wintypes.HANDLE
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        process = open_process(self.PROCESS_QUERY_LIMITED_INFORMATION, False, process_id)
        if not process:
            return ""
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(buffer))
            if not kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
                return ""
            return PureWindowsPath(buffer.value).name
        finally:
            kernel32.CloseHandle(process)
