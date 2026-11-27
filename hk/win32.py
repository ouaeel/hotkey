"""Thin, dependency-free ctypes layer over the few Win32 calls the app needs.

Everything here is synchronous, allocation-light and only ever called in
response to a user action or a registered hotkey (no polling).
"""
from __future__ import annotations

import ctypes
import logging
import math
import os
import random
import time
from ctypes import (POINTER, WINFUNCTYPE, Structure, Union, byref, c_int,
                    c_int32, c_uint32, c_void_p, c_wchar_p, sizeof)

from . import keys as _keys

log = logging.getLogger("hotkey")

# Tag synthetic clicks made by this app's macro engine.  The mouse hook can
# then ignore only its own playback instead of every injected click (some
# mouse drivers inject real button presses too).
INJECT_TAG = 0x484B0001  # "HK"

MOD_ALT = _keys.MOD_ALT
MOD_CONTROL = _keys.MOD_CONTROL
MOD_SHIFT = _keys.MOD_SHIFT
MOD_WIN = _keys.MOD_WIN

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
try:
    powrprof = ctypes.WinDLL("powrprof", use_last_error=True)
except OSError:  # pragma: no cover - older / stripped systems
    powrprof = None

HWND = HANDLE = HINSTANCE = HICON = HCURSOR = HBRUSH = HMENU = c_void_p
UINT = c_uint32
DWORD = c_uint32
WORD = ctypes.c_ushort
LONG = c_int32
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
LRESULT = ctypes.c_ssize_t
HOOKPROC = WINFUNCTYPE(LRESULT, c_int, WPARAM, LPARAM)
WNDENUMPROC = WINFUNCTYPE(ctypes.c_bool, HWND, LPARAM)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
ULONG_PTR = ctypes.c_size_t
LPCWSTR = c_wchar_p
WNDPROC = WINFUNCTYPE(LRESULT, HWND, UINT, WPARAM, LPARAM)

TOKEN_ADJUST_PRIVILEGES = 0x0020
TOKEN_QUERY = 0x0008
SE_PRIVILEGE_ENABLED = 0x00000002
EWX_SHUTDOWN = 0x00000001
EWX_REBOOT = 0x00000002
EWX_FORCEIFHUNG = 0x00000010


class LUID(Structure):
    _fields_ = [("LowPart", DWORD), ("HighPart", c_int32)]


class LUID_AND_ATTRIBUTES(Structure):
    _fields_ = [("Luid", LUID), ("Attributes", DWORD)]


class TOKEN_PRIVILEGES(Structure):
    _fields_ = [("PrivilegeCount", DWORD),
                ("Privileges", LUID_AND_ATTRIBUTES * 1)]

# --- window messages / constants --------------------------------------------
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
WM_TIMER = 0x0113
WM_NULL = 0x0000
WM_HOTKEY = 0x0312
WM_APP = 0x8000
WM_SETICON = 0x0080
ICON_SMALL = 0
ICON_BIG = 1
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B
SW_MINIMIZE = 6
SW_MAXIMIZE = 3
SW_RESTORE = 9
GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
HWND_TOPMOST = c_void_p(-1)
HWND_NOTOPMOST = c_void_p(-2)
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SPI_GETWORKAREA = 0x0030
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x0040
MF_STRING = 0x0000
MF_SEPARATOR = 0x0800
MF_CHECKED = 0x0008
MF_GRAYED = 0x0001
MF_DISABLED = 0x0002
MF_POPUP = 0x0010
TPM_RIGHTBUTTON = 0x0002
TPM_LEFTALIGN = 0x0000
TPM_NONOTIFY = 0x0080
TPM_RETURNCMD = 0x0100
NIM_ADD = 0
NIM_MODIFY = 1
NIM_DELETE = 2
NIF_MESSAGE = 0x01
NIF_ICON = 0x02
NIF_TIP = 0x04
NIF_INFO = 0x10
NIIF_INFO = 0x01
NIIF_WARNING = 0x02
NIIF_ERROR = 0x03

VK_LWIN, VK_RWIN = 0x5B, 0x5C
VK_CONTROL, VK_MENU, VK_SHIFT = 0x11, 0x12, 0x10


class POINT(Structure):
    _fields_ = [("x", LONG), ("y", LONG)]


class RECT(Structure):
    _fields_ = [("left", LONG), ("top", LONG), ("right", LONG), ("bottom", LONG)]


class MSG(Structure):
    _fields_ = [("hWnd", HWND), ("message", UINT), ("wParam", WPARAM),
                ("lParam", LPARAM), ("time", DWORD), ("pt", POINT)]


class WNDCLASSW(Structure):
    _fields_ = [("style", UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", c_int), ("cbWndExtra", c_int),
                ("hInstance", HINSTANCE), ("hIcon", HICON),
                ("hCursor", HCURSOR), ("hbrBackground", HBRUSH),
                ("lpszMenuName", LPCWSTR), ("lpszClassName", LPCWSTR)]


class GUID(Structure):
    _fields_ = [("Data1", DWORD), ("Data2", WORD), ("Data3", WORD),
                ("Data4", ctypes.c_ubyte * 8)]


class NOTIFYICONDATAW(Structure):
    _fields_ = [("cbSize", DWORD), ("hWnd", HWND), ("uID", UINT),
                ("uFlags", UINT), ("uCallbackMessage", UINT), ("hIcon", HICON),
                ("szTip", ctypes.c_wchar * 128), ("dwState", DWORD),
                ("dwStateMask", DWORD), ("szInfo", ctypes.c_wchar * 256),
                ("uVersion", UINT), ("szInfoTitle", ctypes.c_wchar * 64),
                ("dwInfoFlags", DWORD), ("guidItem", GUID),
                ("hBalloonIcon", HICON)]


class MOUSEINPUT(Structure):
    _fields_ = [("dx", LONG), ("dy", LONG), ("mouseData", DWORD),
                ("dwFlags", DWORD), ("time", DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(Structure):
    _fields_ = [("wVk", WORD), ("wScan", WORD), ("dwFlags", DWORD),
                ("time", DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(Structure):
    _fields_ = [("uMsg", DWORD), ("wParamL", WORD), ("wParamH", WORD)]


class _INPUTUNION(Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", DWORD), ("u", _INPUTUNION)]


# --- prototypes (keep 64-bit arguments from being truncated) -----------------
user32.CreateWindowExW.argtypes = [DWORD, LPCWSTR, LPCWSTR, DWORD, c_int, c_int,
                                   c_int, c_int, HWND, HMENU, HINSTANCE, c_void_p]
user32.CreateWindowExW.restype = HWND
user32.DefWindowProcW.argtypes = [HWND, UINT, WPARAM, LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.RegisterClassW.argtypes = [POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = ctypes.c_ushort
user32.RegisterHotKey.argtypes = [HWND, c_int, UINT, UINT]
user32.RegisterHotKey.restype = ctypes.c_bool
user32.UnregisterHotKey.argtypes = [HWND, c_int]
user32.GetMessageW.argtypes = [POINTER(MSG), HWND, UINT, UINT]
user32.TranslateMessage.argtypes = [POINTER(MSG)]
user32.DispatchMessageW.argtypes = [POINTER(MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.PostMessageW.argtypes = [HWND, UINT, WPARAM, LPARAM]
user32.PostMessageW.restype = ctypes.c_bool
user32.SendMessageW.argtypes = [HWND, UINT, WPARAM, LPARAM]
user32.SendMessageW.restype = LRESULT
user32.SendMessageTimeoutW.argtypes = [
    HWND, UINT, WPARAM, LPARAM, UINT, UINT, POINTER(ctypes.c_size_t)]
user32.SendMessageTimeoutW.restype = LRESULT
user32.SendInput.argtypes = [UINT, POINTER(INPUT), c_int]
user32.SendInput.restype = UINT
user32.SetForegroundWindow.argtypes = [HWND]
user32.GetForegroundWindow.restype = HWND
user32.ShowWindow.argtypes = [HWND, c_int]
user32.IsWindowVisible.argtypes = [HWND]
user32.SetWindowPos.argtypes = [HWND, HWND, c_int, c_int, c_int, c_int, UINT]
user32.MoveWindow.argtypes = [HWND, c_int, c_int, c_int, c_int, ctypes.c_bool]
user32.GetWindowRect.argtypes = [HWND, POINTER(RECT)]
user32.GetWindowLongW.argtypes = [HWND, c_int]
user32.GetWindowLongW.restype = LONG
user32.IsIconic.argtypes = [HWND]
user32.IsIconic.restype = ctypes.c_bool
user32.AttachThreadInput.argtypes = [DWORD, DWORD, ctypes.c_bool]
user32.AttachThreadInput.restype = ctypes.c_bool
user32.BringWindowToTop.argtypes = [HWND]
user32.BringWindowToTop.restype = ctypes.c_bool
user32.SetFocus.argtypes = [HWND]
user32.SetFocus.restype = HWND
shell32.ShellExecuteW.argtypes = [HWND, c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p, c_int]
shell32.ShellExecuteW.restype = HINSTANCE
user32.SetTimer.argtypes = [HWND, ctypes.c_size_t, UINT, c_void_p]
user32.KillTimer.argtypes = [HWND, ctypes.c_size_t]
user32.LoadImageW.argtypes = [HINSTANCE, LPCWSTR, UINT, c_int, c_int, UINT]
user32.LoadImageW.restype = HANDLE
user32.LoadIconW.argtypes = [HINSTANCE, c_void_p]
user32.LoadIconW.restype = HICON
user32.DestroyIcon.argtypes = [HICON]
user32.DestroyIcon.restype = ctypes.c_int
user32.CreatePopupMenu.restype = HMENU
user32.AppendMenuW.argtypes = [HMENU, UINT, ctypes.c_size_t, LPCWSTR]
user32.TrackPopupMenu.argtypes = [HMENU, UINT, c_int, c_int, c_int, HWND, c_void_p]
user32.TrackPopupMenu.restype = c_int
user32.DestroyMenu.argtypes = [HMENU]
user32.GetCursorPos.argtypes = [POINTER(POINT)]
user32.SystemParametersInfoW.argtypes = [UINT, UINT, c_void_p, UINT]
user32.SystemParametersInfoW.restype = ctypes.c_bool
user32.EmptyClipboard.argtypes = []
shell32.Shell_NotifyIconW.argtypes = [DWORD, POINTER(NOTIFYICONDATAW)]
shell32.Shell_NotifyIconW.restype = ctypes.c_bool
user32.OpenClipboard.argtypes = [HWND]
user32.GetClipboardData.argtypes = [UINT]
user32.GetClipboardData.restype = HANDLE
user32.SetClipboardData.argtypes = [UINT, HANDLE]
user32.SetClipboardData.restype = HANDLE
kernel32.GlobalAlloc.argtypes = [UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = HANDLE
kernel32.GlobalLock.argtypes = [HANDLE]
kernel32.GlobalLock.restype = c_void_p
kernel32.GlobalUnlock.argtypes = [HANDLE]
kernel32.GlobalFree.argtypes = [HANDLE]
kernel32.GetModuleHandleW.argtypes = [LPCWSTR]
kernel32.GetModuleHandleW.restype = HINSTANCE
kernel32.GetCurrentThreadId.restype = DWORD
kernel32.CreateMutexW.argtypes = [c_void_p, ctypes.c_bool, LPCWSTR]
kernel32.CreateMutexW.restype = HANDLE
kernel32.CloseHandle.argtypes = [HANDLE]
kernel32.CloseHandle.restype = ctypes.c_bool
user32.DestroyWindow.argtypes = [HWND]
user32.PostQuitMessage.argtypes = [c_int]
user32.CloseClipboard.argtypes = []
user32.LockWorkStation.argtypes = []
shell32.SHEmptyRecycleBinW.argtypes = [HWND, LPCWSTR, DWORD]
kernel32.GetCurrentProcess.argtypes = []
kernel32.GetCurrentProcess.restype = HANDLE
advapi32.OpenProcessToken.argtypes = [HANDLE, DWORD, POINTER(HANDLE)]
advapi32.OpenProcessToken.restype = ctypes.c_bool
advapi32.LookupPrivilegeValueW.argtypes = [LPCWSTR, LPCWSTR, POINTER(LUID)]
advapi32.LookupPrivilegeValueW.restype = ctypes.c_bool
advapi32.AdjustTokenPrivileges.argtypes = [
    HANDLE, ctypes.c_bool, POINTER(TOKEN_PRIVILEGES), DWORD, c_void_p, c_void_p]
advapi32.AdjustTokenPrivileges.restype = ctypes.c_bool
user32.ExitWindowsEx.argtypes = [UINT, DWORD]
user32.ExitWindowsEx.restype = ctypes.c_bool
if powrprof is not None:
    powrprof.SetSuspendState.argtypes = [ctypes.c_bool, ctypes.c_bool, ctypes.c_bool]
    powrprof.SetSuspendState.restype = ctypes.c_bool
user32.GetAsyncKeyState.argtypes = [c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.FindWindowW.argtypes = [LPCWSTR, LPCWSTR]
user32.FindWindowW.restype = HWND
user32.SetWindowsHookExW.argtypes = [c_int, HOOKPROC, HINSTANCE, c_uint32]
user32.SetWindowsHookExW.restype = c_void_p
user32.UnhookWindowsHookEx.argtypes = [c_void_p]
user32.UnhookWindowsHookEx.restype = ctypes.c_bool
user32.CallNextHookEx.argtypes = [c_void_p, c_int, WPARAM, LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.EnumWindows.argtypes = [WNDENUMPROC, LPARAM]
user32.EnumWindows.restype = ctypes.c_bool
user32.GetWindowThreadProcessId.argtypes = [HWND, POINTER(DWORD)]
user32.GetWindowThreadProcessId.restype = DWORD
user32.GetWindowTextLengthW.argtypes = [HWND]
user32.GetWindowTextLengthW.restype = c_int
user32.GetWindowTextW.argtypes = [HWND, LPCWSTR, c_int]
user32.GetWindowTextW.restype = c_int
user32.IsWindowVisible.argtypes = [HWND]
user32.IsWindowVisible.restype = ctypes.c_bool
kernel32.OpenProcess.argtypes = [DWORD, ctypes.c_bool, DWORD]
kernel32.OpenProcess.restype = HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [HANDLE, DWORD, LPCWSTR, POINTER(DWORD)]
kernel32.QueryFullProcessImageNameW.restype = ctypes.c_bool


def get_work_area() -> tuple[int, int, int, int]:
    r = RECT()
    user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, byref(r), 0)
    return r.left, r.top, r.right, r.bottom


def foreground() -> int | None:
    h = user32.GetForegroundWindow()
    return int(h) if h else None


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    r = RECT()
    user32.GetWindowRect(HWND(hwnd), byref(r))
    return r.left, r.top, r.right, r.bottom


def show_window(hwnd: int, cmd: int) -> None:
    user32.ShowWindow(HWND(hwnd), cmd)


def move_window(hwnd: int, x: int, y: int, w: int, h: int) -> None:
    user32.MoveWindow(HWND(hwnd), x, y, w, h, True)


def is_topmost(hwnd: int) -> bool:
    """True when Windows already keeps this window above normal windows."""
    ex = user32.GetWindowLongW(HWND(hwnd), GWL_EXSTYLE)
    return bool(int(ex) & WS_EX_TOPMOST)


def set_topmost(hwnd: int, on: bool) -> bool:
    """Pin or unpin a window; returns True when the requested state was set."""
    insert = HWND_TOPMOST if on else HWND_NOTOPMOST
    ok = user32.SetWindowPos(HWND(hwnd), insert, 0, 0, 0, 0,
                             SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
    return bool(ok) and is_topmost(hwnd) == bool(on)


def toggle_topmost(hwnd: int) -> bool:
    """Flip the pin state; returns True when the window ended up pinned."""
    desired = not is_topmost(hwnd)
    if set_topmost(hwnd, desired):
        return desired
    return is_topmost(hwnd)


# --- clipboard --------------------------------------------------------------
def get_clipboard() -> str:
    for _ in range(15):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.02)
    else:
        return ""
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return ""
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def set_clipboard(text: str) -> bool:
    data = (text + "\0").encode("utf-16-le")
    for _ in range(15):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.02)
    else:
        return False
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            return False
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            kernel32.GlobalFree(handle)
            return False
        try:
            ctypes.memmove(ptr, data, len(data))
        finally:
            kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            return False
        return True
    finally:
        user32.CloseClipboard()


# --- synthetic input --------------------------------------------------------
def _key_input(vk: int = 0, scan: int = 0, flags: int = 0) -> INPUT:
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki.wVk = vk
    inp.ki.wScan = scan
    inp.ki.dwFlags = flags
    return inp


def _send(inputs: list[INPUT]) -> None:
    if not inputs:
        return
    arr = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), arr, sizeof(INPUT))


def send_text(text: str, delay_ms: int = 2) -> None:
    """Type arbitrary unicode text into the foreground window."""
    if not text:
        return
    chunk: list[INPUT] = []
    for ch in text:
        before = len(chunk)
        if ch == "\n":
            chunk += [_key_input(0x0D), _key_input(0x0D, 0, KEYEVENTF_KEYUP)]
        elif ch == "\t":
            chunk += [_key_input(0x09), _key_input(0x09, 0, KEYEVENTF_KEYUP)]
        else:
            encoded = ch.encode("utf-16-le")
            for i in range(0, len(encoded), 2):
                cu = int.from_bytes(encoded[i:i + 2], "little")
                chunk += [
                    _key_input(0, cu, KEYEVENTF_UNICODE),
                    _key_input(0, cu, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP),
                ]
        if delay_ms and len(chunk) > before:
            # The setting is "ms between characters", not between 24-character
            # batches. Flush one character at a time when a delay is requested.
            _send(chunk)
            chunk = []
            time.sleep(delay_ms / 1000)
        elif len(chunk) >= 48:
            _send(chunk)
            chunk = []
    _send(chunk)


def send_vk(vk: int, up: bool = False) -> None:
    _send([_key_input(vk, 0, KEYEVENTF_KEYUP if up else 0)])


def send_combo(mods: int, vk: int) -> None:
    down: list[INPUT] = []
    if mods & 0x0002:
        down.append(_key_input(VK_CONTROL))
    if mods & 0x0001:
        down.append(_key_input(VK_MENU))
    if mods & 0x0004:
        down.append(_key_input(VK_SHIFT))
    if mods & 0x0008:
        down.append(_key_input(VK_LWIN))
    _send(down)
    _send([_key_input(vk), _key_input(vk, 0, KEYEVENTF_KEYUP)])
    up: list[INPUT] = []
    if mods & 0x0008:
        up.append(_key_input(VK_LWIN, 0, KEYEVENTF_KEYUP))
    if mods & 0x0004:
        up.append(_key_input(VK_SHIFT, 0, KEYEVENTF_KEYUP))
    if mods & 0x0001:
        up.append(_key_input(VK_MENU, 0, KEYEVENTF_KEYUP))
    if mods & 0x0002:
        up.append(_key_input(VK_CONTROL, 0, KEYEVENTF_KEYUP))
    _send(up)


def load_icon(path: str | None) -> int:
    if path and os.path.isfile(path):
        handle = user32.LoadImageW(None, path, IMAGE_ICON, 0, 0,
                                   LR_LOADFROMFILE | LR_DEFAULTSIZE)
        if handle:
            return int(handle)
    return int(user32.LoadIconW(None, c_void_p(32512)))  # IDI_APPLICATION


def set_window_icon(hwnd: int, path: str) -> bool:
    """Set a Tk window's native icon (title bar and taskbar button).

    ``wm iconbitmap`` alone does not always produce a WM_SETICON handle on
    Windows, so send it explicitly as well.  A file-backed icon loaded with
    ``LoadImageW`` is ours to destroy; the shared IDI_APPLICATION fallback is
    not.
    """
    hicon = 0
    owned = False
    if path and os.path.isfile(path):
        hicon = int(user32.LoadImageW(None, path, IMAGE_ICON, 0, 0,
                                      LR_LOADFROMFILE | LR_DEFAULTSIZE) or 0)
        owned = bool(hicon)
    if not hicon:
        hicon = int(user32.LoadIconW(None, c_void_p(32512)) or 0)
    if not hicon:
        return False
    user32.SendMessageW(HWND(hwnd), WM_SETICON, ICON_SMALL, LPARAM(hicon))
    user32.SendMessageW(HWND(hwnd), WM_SETICON, ICON_BIG, LPARAM(hicon))
    if owned:
        user32.DestroyIcon(HICON(hicon))
    return True


def tray_add(hwnd: int, uid: int, icon: int, tip: str, callback_msg: int) -> bool:
    nid = NOTIFYICONDATAW()
    nid.cbSize = sizeof(NOTIFYICONDATAW)
    nid.hWnd = HWND(hwnd)
    nid.uID = uid
    nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
    nid.uCallbackMessage = callback_msg
    nid.hIcon = HICON(icon)
    nid.szTip = tip[:127]
    return bool(shell32.Shell_NotifyIconW(NIM_ADD, byref(nid)))


def tray_update(hwnd: int, uid: int, icon: int, tip: str) -> None:
    nid = NOTIFYICONDATAW()
    nid.cbSize = sizeof(NOTIFYICONDATAW)
    nid.hWnd = HWND(hwnd)
    nid.uID = uid
    nid.uFlags = NIF_ICON | NIF_TIP
    nid.hIcon = HICON(icon)
    nid.szTip = tip[:127]
    shell32.Shell_NotifyIconW(NIM_MODIFY, byref(nid))


def tray_remove(hwnd: int, uid: int) -> None:
    nid = NOTIFYICONDATAW()
    nid.cbSize = sizeof(NOTIFYICONDATAW)
    nid.hWnd = HWND(hwnd)
    nid.uID = uid
    shell32.Shell_NotifyIconW(NIM_DELETE, byref(nid))


def tray_balloon(hwnd: int, uid: int, title: str, text: str, kind: int = NIIF_INFO) -> None:
    nid = NOTIFYICONDATAW()
    nid.cbSize = sizeof(NOTIFYICONDATAW)
    nid.hWnd = HWND(hwnd)
    nid.uID = uid
    nid.uFlags = NIF_INFO
    nid.szInfoTitle = (title or "Hotkey")[:63]
    nid.szInfo = (text or "")[:255]
    nid.dwInfoFlags = kind
    shell32.Shell_NotifyIconW(NIM_MODIFY, byref(nid))


def find_window(class_name: str) -> int:
    """Handle of a running instance's hidden window, or 0."""
    return int(user32.FindWindowW(class_name, None) or 0)


def set_dark_titlebar(hwnd: int, dark: bool) -> None:
    """Match the OS title bar to the dark/light UI (Windows 10/11)."""
    try:
        user32.GetParent.argtypes = [HWND]
        user32.GetParent.restype = HWND
        frame = user32.GetParent(HWND(hwnd)) or HWND(hwnd)
        dwm = ctypes.WinDLL("dwmapi")
        value = c_int32(1 if dark else 0)
        for attr in (20, 19):
            if dwm.DwmSetWindowAttribute(frame, attr, byref(value), sizeof(value)) == 0:
                break
    except Exception:
        pass


def menu_create(items: list) -> int:
    """items: (id, label, checked, disabled[, children]). label '---' for separator."""
    menu, _ = menu_create_ex(items)
    return menu


def menu_create_ex(items: list) -> tuple[int, list[int]]:
    menu = user32.CreatePopupMenu()
    handles: list[int] = [menu]
    for item in items:
        item_id = item[0]
        label = item[1]
        checked = item[2] if len(item) > 2 else False
        disabled = item[3] if len(item) > 3 else False
        children = item[4] if len(item) > 4 else None
        if label == "---":
            user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            continue
        if children is not None:
            sub, sub_handles = menu_create_ex(children)
            handles.extend(sub_handles)
            user32.AppendMenuW(menu, MF_POPUP, sub, label)
            continue
        flags = MF_STRING
        if checked:
            flags |= MF_CHECKED
        if disabled:
            flags |= MF_GRAYED | MF_DISABLED
        user32.AppendMenuW(menu, flags, item_id, label)
    return int(menu), handles


def menu_show(menu: int, hwnd: int) -> int:
    pt = POINT()
    user32.GetCursorPos(byref(pt))
    user32.SetForegroundWindow(HWND(hwnd))
    cmd = user32.TrackPopupMenu(HMENU(menu), TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
                                pt.x, pt.y, 0, HWND(hwnd), None)
    user32.PostMessageW(HWND(hwnd), WM_NULL, 0, 0)
    return int(cmd)


# --- shell / power ----------------------------------------------------------
def open_target(target: str) -> None:
    os.startfile(target)  # noqa: S606 - intentional shell open


def lock_workstation() -> None:
    user32.LockWorkStation()


HWND_BROADCAST = 0xFFFF
WM_SYSCOMMAND = 0x0112
SC_MONITORPOWER = 0xF170
SMTO_BLOCK = 0x0001
SMTO_ABORTIFHUNG = 0x0002


def _turn_display_off() -> None:
    """Blank every display without waiting forever on a stuck window."""
    result = ctypes.c_size_t(0)
    user32.SendMessageTimeoutW(
        HWND(HWND_BROADCAST), WM_SYSCOMMAND, SC_MONITORPOWER, 2,
        SMTO_BLOCK | SMTO_ABORTIFHUNG, 2000, ctypes.byref(result))


def _modern_standby_sleep() -> None:
    """Trigger Modern Standby by locking and turning the display off.

    Windows 8+ systems using S0 Low Power Idle reject SetSuspendState with
    ERROR_NOT_SUPPORTED.  The supported fallback is the same transition the
    power button/Start-menu Sleep item performs: blank the display, which lets
    the power manager enter Modern Standby.
    """
    try:
        lock_workstation()
    except Exception:
        pass
    log.info("sleep: using modern-standby display-off fallback")
    _turn_display_off()


def suspend_pc() -> None:
    if powrprof is None:  # pragma: no cover - stripped-down Windows
        _modern_standby_sleep()
        return
    # Grant the shutdown privilege and force the transition for traditional
    # S1-S3 systems.  Modern-standby laptops report ERROR_NOT_SUPPORTED here.
    try:
        _enable_shutdown_privilege()
    except OSError:
        pass
    if powrprof.SetSuspendState(False, True, False):
        return
    error = ctypes.get_last_error()
    _modern_standby_sleep()
    if error not in (0, 50):  # keep a note for unusual failures
        log.warning("SetSuspendState failed (%s); display-off fallback used", error)


def _enable_shutdown_privilege() -> None:
    """Grant this process the right to call ExitWindowsEx."""
    token = HANDLE()
    if not advapi32.OpenProcessToken(
            kernel32.GetCurrentProcess(),
            TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    luid = LUID()
    try:
        if not advapi32.LookupPrivilegeValueW(
                None, "SeShutdownPrivilege", byref(luid)):
            raise ctypes.WinError(ctypes.get_last_error())
        privileges = TOKEN_PRIVILEGES(
            1, (LUID_AND_ATTRIBUTES * 1)(
                LUID_AND_ATTRIBUTES(luid, SE_PRIVILEGE_ENABLED)))
        ctypes.set_last_error(0)
        ok = advapi32.AdjustTokenPrivileges(
            token, False, byref(privileges), sizeof(privileges), None, None)
        error = ctypes.get_last_error()
        if not ok or error:
            raise ctypes.WinError(error)
    finally:
        kernel32.CloseHandle(token)


def shutdown_pc() -> None:
    """Shut Windows down, forcing only apps that refuse to close."""
    _enable_shutdown_privilege()
    if not user32.ExitWindowsEx(EWX_SHUTDOWN | EWX_FORCEIFHUNG, 0):
        raise ctypes.WinError(ctypes.get_last_error())


def restart_pc() -> None:
    """Restart Windows, forcing only apps that refuse to close."""
    _enable_shutdown_privilege()
    if not user32.ExitWindowsEx(EWX_REBOOT | EWX_FORCEIFHUNG, 0):
        raise ctypes.WinError(ctypes.get_last_error())


def empty_recycle_bin() -> int:
    return int(shell32.SHEmptyRecycleBinW(None, None, 0x7))


def current_mods() -> int:
    mods = 0
    if user32.GetAsyncKeyState(VK_SHIFT) & 0x8000:
        mods |= MOD_SHIFT
    if user32.GetAsyncKeyState(VK_CONTROL) & 0x8000:
        mods |= MOD_CONTROL
    if user32.GetAsyncKeyState(VK_MENU) & 0x8000:
        mods |= MOD_ALT
    if (user32.GetAsyncKeyState(VK_LWIN) & 0x8000) or (user32.GetAsyncKeyState(VK_RWIN) & 0x8000):
        mods |= MOD_WIN
    return mods


def is_key_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


# --- foreground application (per-app hotkeys) -------------------------------
def normalize_app(name: str) -> str:
    """Lower-case base name of an executable: 'C:\\X\\Chrome.EXE' -> 'chrome.exe'."""
    text = str(name or "").strip().strip('"').replace("/", "\\").lower()
    return text.rsplit("\\", 1)[-1]


def app_stem(name: str) -> str:
    name = normalize_app(name)
    return name[:-4] if name.endswith(".exe") else name


def app_matches(specs, exe: str) -> bool:
    """Does `exe` satisfy the user's app scope?

    An empty scope means "everywhere".  A scope may list full names
    ('chrome.exe'), stems ('chrome'), or a wildcard ('*code*').
    """
    if not specs:
        return True
    exe = normalize_app(exe)
    stem = app_stem(exe)
    for raw in specs:
        want = normalize_app(raw)
        if not want or want == "*":
            return True
        if want.startswith("*") or want.endswith("*"):
            core = want.strip("*")
            if not core or core in exe or core in stem:
                return True
            continue
        if want == exe or app_stem(want) == stem:
            return True
    return False


def _window_title(hwnd: int) -> str:
    length = int(user32.GetWindowTextLengthW(HWND(hwnd)))
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(HWND(hwnd), buf, length + 1)
    return buf.value


_pid_cache: dict[int, tuple[float, str]] = {}


def pid_exe(pid: int) -> str:
    """Executable base name for a process id (cached for a second)."""
    if not pid:
        return ""
    now = time.monotonic()
    hit = _pid_cache.get(pid)
    if hit is not None and now - hit[0] < 1.0:
        return hit[1]
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = DWORD(len(buf))
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, byref(size)):
            return ""
        name = normalize_app(buf.value)
    finally:
        kernel32.CloseHandle(handle)
    if len(_pid_cache) > 128:
        _pid_cache.clear()
    _pid_cache[pid] = (now, name)
    return name


def window_app(hwnd: int | None) -> str:
    """Executable name behind a window handle ('' when unavailable)."""
    if not hwnd:
        return ""
    pid = DWORD()
    user32.GetWindowThreadProcessId(HWND(hwnd), byref(pid))
    return pid_exe(int(pid.value))


def foreground_app() -> str:
    """Executable name of the app the user is looking at right now."""
    return window_app(foreground())


def foreground_title() -> str:
    hwnd = foreground()
    return _window_title(hwnd) if hwnd else ""


_running_cache: tuple[float, tuple[str, ...]] = (0.0, ())


def list_running_apps(max_age: float = 30.0) -> tuple[str, ...]:
    """Sorted executable names of apps with a visible, titled window."""
    global _running_cache
    now = time.monotonic()
    if now - _running_cache[0] < max_age and _running_cache[1]:
        return _running_cache[1]
    names: set[str] = set()

    def collect(hwnd, _lparam):
        try:
            if user32.IsWindowVisible(HWND(hwnd)) and user32.GetWindowTextLengthW(HWND(hwnd)):
                exe = window_app(int(hwnd))
                if exe:
                    names.add(exe)
        except Exception:
            pass
        return True

    callback = WNDENUMPROC(collect)
    user32.EnumWindows(callback, 0)
    result = tuple(sorted(names))
    _running_cache = (now, result)
    return result


def is_iconic(hwnd: int) -> bool:
    return bool(user32.IsIconic(HWND(hwnd)))


def find_app_window(exe: str) -> int | None:
    """Handle of a visible (or minimized) top-level window owned by ``exe``."""
    target = normalize_app(exe)
    if not target:
        return None
    fg = foreground()
    candidates: list[tuple[bool, int]] = []

    def collect(hwnd, _lparam):
        try:
            hwnd = int(hwnd)
            if not (user32.IsWindowVisible(HWND(hwnd))
                    or user32.IsIconic(HWND(hwnd))):
                return True
            if user32.GetWindowTextLengthW(HWND(hwnd)) <= 0:
                return True
            if user32.GetWindowLongW(HWND(hwnd), GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
                return True
            if app_matches([target], window_app(hwnd)):
                candidates.append((hwnd == fg, hwnd))
        except Exception:
            pass
        return True

    callback = WNDENUMPROC(collect)
    user32.EnumWindows(callback, 0)
    if not candidates:
        return None
    for is_fg, hwnd in candidates:
        if is_fg:
            return hwnd
    return candidates[0][1]


def activate_window(hwnd: int) -> None:
    """Bring a window to the foreground (works around SetForegroundWindow limits)."""
    hwnd = int(hwnd)
    if is_iconic(hwnd):
        show_window(hwnd, SW_RESTORE)
    fg = foreground()
    cur = kernel32.GetCurrentThreadId()
    attached: list[tuple[int, int]] = []
    try:
        if fg:
            fg_thread = user32.GetWindowThreadProcessId(HWND(fg), None)
            if fg_thread and fg_thread != cur:
                if user32.AttachThreadInput(cur, fg_thread, True):
                    attached.append((cur, fg_thread))
        target_thread = user32.GetWindowThreadProcessId(HWND(hwnd), None)
        if target_thread and target_thread != cur:
            if user32.AttachThreadInput(cur, target_thread, True):
                attached.append((cur, target_thread))
        user32.BringWindowToTop(HWND(hwnd))
        user32.SetForegroundWindow(HWND(hwnd))
    finally:
        for a, b in attached:
            try:
                user32.AttachThreadInput(a, b, False)
            except Exception:
                pass


def launch_app(target: str) -> None:
    target = os.path.expandvars(os.path.expanduser(target))
    if not target:
        raise OSError("nothing to launch")
    if os.path.isfile(target):
        os.startfile(target)  # noqa: S606
        return
    result = int(shell32.ShellExecuteW(None, "open", target, None, None, 1) or 0)
    if result <= 32:
        raise OSError(result, f"could not launch {target!r}")


def summon_app(target: str) -> str:
    """Focus, minimize or launch the window for ``target`` (by exe name)."""
    hwnd = find_app_window(target)
    if hwnd:
        if is_iconic(hwnd):
            show_window(hwnd, SW_RESTORE)
            activate_window(hwnd)
            return "restored"
        if foreground() == hwnd:
            show_window(hwnd, SW_MINIMIZE)
            return "minimized"
        activate_window(hwnd)
        return "focused"
    launch_app(target)
    return "launched"


def send_combo_many(mods: int, vks, hold_ms: int = 30) -> None:
    """Send a chord/sequence of virtual keys with modifiers held."""
    vks = tuple(vks)
    down: list[INPUT] = []
    if mods & MOD_CONTROL:
        down.append(_key_input(VK_CONTROL))
    if mods & MOD_ALT:
        down.append(_key_input(VK_MENU))
    if mods & MOD_SHIFT:
        down.append(_key_input(VK_SHIFT))
    if mods & MOD_WIN:
        down.append(_key_input(VK_LWIN))
    for vk in vks:
        down.append(_key_input(vk))
    _send(down)
    if hold_ms:
        time.sleep(max(0.001, hold_ms / 1000.0))
    up: list[INPUT] = []
    for vk in reversed(vks):
        up.append(_key_input(vk, 0, KEYEVENTF_KEYUP))
    if mods & MOD_WIN:
        up.append(_key_input(VK_LWIN, 0, KEYEVENTF_KEYUP))
    if mods & MOD_SHIFT:
        up.append(_key_input(VK_SHIFT, 0, KEYEVENTF_KEYUP))
    if mods & MOD_ALT:
        up.append(_key_input(VK_MENU, 0, KEYEVENTF_KEYUP))
    if mods & MOD_CONTROL:
        up.append(_key_input(VK_CONTROL, 0, KEYEVENTF_KEYUP))
    _send(up)

def enable_dpi_awareness() -> None:
    """Crisp text in the tkinter window on scaled displays."""
    try:
        user32.SetProcessDpiAwarenessContext.argtypes = [c_void_p]
        if user32.SetProcessDpiAwarenessContext(c_void_p(-4)):
            return
    except Exception:
        pass
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(1)
    except Exception:
        pass

user32.SetCursorPos.argtypes = [c_int, c_int]
user32.SetCursorPos.restype = ctypes.c_bool

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_XDOWN = 0x0080
MOUSEEVENTF_XUP = 0x0100

_MOUSE_BUTTON_DOWN = {
    "left": MOUSEEVENTF_LEFTDOWN,
    "right": MOUSEEVENTF_RIGHTDOWN,
    "middle": MOUSEEVENTF_MIDDLEDOWN,
    "x1": MOUSEEVENTF_XDOWN,
    "x2": MOUSEEVENTF_XDOWN,
}
_MOUSE_BUTTON_UP = {
    "left": MOUSEEVENTF_LEFTUP,
    "right": MOUSEEVENTF_RIGHTUP,
    "middle": MOUSEEVENTF_MIDDLEUP,
    "x1": MOUSEEVENTF_XUP,
    "x2": MOUSEEVENTF_XUP,
}


def get_cursor_pos() -> tuple[int, int]:
    pt = POINT()
    user32.GetCursorPos(byref(pt))
    return int(pt.x), int(pt.y)


def set_cursor_pos(x: int, y: int) -> None:
    user32.SetCursorPos(int(x), int(y))


def move_mouse_human(x: int, y: int, duration_ms: float = 260,
                     jitter: float = 2.0) -> None:
    """Move the cursor along a slightly irregular, eased path.

    A single SetCursorPos teleport looks robotic.  Small, uneven steps with a
    smoothstep curve and a tiny sideways wobble read as a human hand while
    still using only SetCursorPos (no extra hook, no injected input flag).
    """
    sx, sy = get_cursor_pos()
    dx, dy = float(x) - sx, float(y) - sy
    distance = math.hypot(dx, dy)
    if distance < 2.0:
        set_cursor_pos(x, y)
        return
    steps = max(6, min(48, int(distance / 14) + 6))
    base = max(0.0, float(duration_ms)) / 1000.0 / steps
    # perpendicular unit vector for the wobble
    px, py = (-dy / distance, dx / distance) if distance else (0.0, 0.0)
    for i in range(1, steps + 1):
        t = i / steps
        eased = t * t * (3.0 - 2.0 * t)
        wobble = 0.0 if i == steps else random.uniform(-jitter, jitter)
        nx = sx + dx * eased + px * wobble
        ny = sy + dy * eased + py * wobble
        set_cursor_pos(int(round(nx)), int(round(ny)))
        if base:
            time.sleep(base * random.uniform(0.65, 1.35))
    set_cursor_pos(int(x), int(y))


def send_mouse(button: str, down: bool) -> None:
    button = str(button).lower()
    if down:
        flag = _MOUSE_BUTTON_DOWN.get(button)
        data = 1 if button == "x1" else (2 if button == "x2" else 0)
    else:
        flag = _MOUSE_BUTTON_UP.get(button)
        data = 1 if button == "x1" else (2 if button == "x2" else 0)
    if not flag:
        return
    inp = INPUT()
    inp.type = 0  # INPUT_MOUSE
    inp.mi.dx = 0
    inp.mi.dy = 0
    inp.mi.mouseData = data
    inp.mi.dwFlags = flag
    inp.mi.time = 0
    inp.mi.dwExtraInfo = INJECT_TAG
    _send([inp])
