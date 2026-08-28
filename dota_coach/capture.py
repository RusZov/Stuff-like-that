from __future__ import annotations

from dataclasses import dataclass
import sys
import threading
from typing import Any


class CaptureError(RuntimeError):
    pass


class CaptureUnavailable(CaptureError):
    pass


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    pid: int
    width: int
    height: int

    @property
    def area(self) -> int:
        return max(0, self.width) * max(0, self.height)

    @property
    def aspect_ratio(self) -> float:
        if self.height <= 0:
            return 0.0
        return self.width / self.height


def choose_dota_window(windows: list[WindowInfo], title_contains: str = "Dota 2") -> WindowInfo | None:
    """Choose the largest visible client window matching the Dota title.

    The pure helper is intentionally separate from Win32 enumeration so it is
    deterministic and testable on Linux CI as well as Windows.
    """
    needle = title_contains.casefold()
    matches = [
        window
        for window in windows
        if needle in window.title.casefold() and window.width > 0 and window.height > 0
    ]
    if not matches:
        return None
    return max(matches, key=lambda window: (window.area, window.hwnd))


def list_visible_windows() -> list[WindowInfo]:
    """Enumerate visible top-level Windows windows with client dimensions."""
    if sys.platform != "win32":
        raise CaptureUnavailable("Win32 window enumeration is only available on Windows")

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    results: list[WindowInfo] = []

    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True

        title_length = user32.GetWindowTextLengthW(hwnd)
        if title_length <= 0:
            return True

        buffer = ctypes.create_unicode_buffer(title_length + 1)
        user32.GetWindowTextW(hwnd, buffer, title_length + 1)
        title = buffer.value.strip()
        if not title:
            return True

        rect = wintypes.RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return True
        width = max(0, int(rect.right - rect.left))
        height = max(0, int(rect.bottom - rect.top))

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        results.append(
            WindowInfo(
                hwnd=int(hwnd),
                title=title,
                pid=int(pid.value),
                width=width,
                height=height,
            )
        )
        return True

    callback_ref = EnumWindowsProc(callback)
    if not user32.EnumWindows(callback_ref, 0):
        raise CaptureError("EnumWindows failed")
    return results


def find_dota_window(title_contains: str = "Dota 2") -> WindowInfo:
    window = choose_dota_window(list_visible_windows(), title_contains)
    if window is None:
        raise CaptureError(f"No visible window containing {title_contains!r} was found")
    return window


def capture_window_frame(hwnd: int, timeout: float = 3.0) -> Any:
    """Capture one BGRA frame from an exact HWND using Windows Graphics Capture.

    Returns a copied ``numpy.ndarray`` owned by the caller. Importing this module
    remains dependency-free; ``windows-capture`` is loaded only when capture is
    requested. This function never captures the whole desktop and never uses
    template matching.
    """
    if sys.platform != "win32":
        raise CaptureUnavailable("Window capture is only available on Windows")
    if hwnd <= 0:
        raise ValueError("hwnd must be a positive window handle")
    if timeout <= 0:
        raise ValueError("timeout must be positive")

    try:
        from windows_capture import Frame, InternalCaptureControl, WindowsCapture
    except ImportError as exc:
        raise CaptureUnavailable(
            "Install the Windows capture extra: pip install -e '.[capture]'"
        ) from exc

    done = threading.Event()
    frames: list[Any] = []

    capture = WindowsCapture(
        cursor_capture=False,
        draw_border=False,
        window_hwnd=hwnd,
    )

    @capture.event
    def on_frame_arrived(frame: Frame, capture_control: InternalCaptureControl) -> None:
        # frame_buffer is a zero-copy view into a native mapped frame. Copy it
        # before leaving the callback so the caller owns stable memory.
        if not frames:
            frames.append(frame.frame_buffer.copy())
        capture_control.stop()
        done.set()

    @capture.event
    def on_closed() -> None:
        done.set()

    control = capture.start_free_threaded()
    if not done.wait(timeout):
        control.stop()
        control.wait()
        raise CaptureError(f"Timed out after {timeout:.1f}s waiting for a Dota window frame")

    control.wait()
    if not frames:
        raise CaptureError("Dota window closed before a frame was captured")
    return frames[0]


def capture_dota_frame(timeout: float = 3.0, title_contains: str = "Dota 2") -> tuple[WindowInfo, Any]:
    """Resolve the real Dota window and capture one frame from its HWND."""
    window = find_dota_window(title_contains)
    return window, capture_window_frame(window.hwnd, timeout=timeout)
