"""Low-level keyboard/mouse hooks + press/tap/hold trigger engine.

Only used for features native RegisterHotKey cannot do (chords,
long-press and every mouse-button hotkey).  Plain keyboard hotkeys
never touch this module, so the tray-only baseline stays at one
thread with no hook installed.
"""
from __future__ import annotations

import ctypes
import time
from ctypes import (POINTER, Structure, WINFUNCTYPE, byref, c_int, c_uint32,
                    c_void_p, sizeof)
from dataclasses import dataclass, field

from . import win32
from . import keys as _keys

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
LLKHF_INJECTED = 0x10

# --- mouse hook -------------------------------------------------------------
WH_MOUSE_LL = 14
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_XBUTTONDOWN = 0x020B
WM_XBUTTONUP = 0x020C
XBUTTON1 = 0x0001
XBUTTON2 = 0x0002
VK_LBUTTON, VK_RBUTTON, VK_MBUTTON = 0x01, 0x02, 0x04
VK_XBUTTON1, VK_XBUTTON2 = 0x05, 0x06

MOUSE_MESSAGES = {
    WM_LBUTTONDOWN: ("down", VK_LBUTTON),
    WM_LBUTTONUP: ("up", VK_LBUTTON),
    WM_RBUTTONDOWN: ("down", VK_RBUTTON),
    WM_RBUTTONUP: ("up", VK_RBUTTON),
    WM_MBUTTONDOWN: ("down", VK_MBUTTON),
    WM_MBUTTONUP: ("up", VK_MBUTTON),
}

MODIFIER_VKS = frozenset((0x10, 0x11, 0x12, 0x5B, 0x5C, 0xA0, 0xA1, 0xA2,
                          0xA3, 0xA4, 0xA5))


class KBDLLHOOKSTRUCT(Structure):
    _fields_ = [("vkCode", c_uint32), ("scanCode", c_uint32), ("flags", c_uint32),
                ("time", c_uint32), ("dwExtraInfo", ctypes.c_size_t)]


class MSLLHOOKSTRUCT(Structure):
    _fields_ = [("pt", win32.POINT), ("mouseData", c_uint32),
                ("flags", c_uint32), ("time", c_uint32),
                ("dwExtraInfo", ctypes.c_size_t)]


class _HookProc:
    def __init__(self, on_event):
        self.on_event = on_event
        self._ref = None
        self.hook = 0

    def install(self) -> bool:
        if self.hook:
            return True
        self._ref = win32.HOOKPROC(self._callback)  # reuse WNDPROC type
        self.hook = win32.user32.SetWindowsHookExW(13, self._ref,
                                                      win32.kernel32.GetModuleHandleW(None), 0)
        if not self.hook:
            self._ref = None
            return False
        return True

    def _callback(self, ncode, wparam, lparam):
        try:
            if ncode == 0:
                info = ctypes.cast(ctypes.c_void_p(lparam), POINTER(KBDLLHOOKSTRUCT)).contents
                if not (info.flags & LLKHF_INJECTED):
                    vk = int(info.vkCode)
                    if vk not in MODIFIER_VKS:
                        if wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                            self.on_event("down", vk)
                        elif wparam in (WM_KEYUP, WM_SYSKEYUP):
                            self.on_event("up", vk)
        except Exception:
            pass
        return win32.user32.CallNextHookEx(0, ncode, wparam, lparam)

    def close(self) -> None:
        if self.hook:
            try:
                win32.user32.UnhookWindowsHookEx(self.hook)
            except Exception:
                pass
            self.hook = 0
            self._ref = None


@dataclass(frozen=True)
class Binding:
    index: int
    mods: int
    vks: tuple[int, ...]
    trigger: str = "press"
    hold_ms: int = 400
    apps: frozenset[str] = frozenset()
    seq: tuple[tuple[int, tuple[int, ...]], ...] = field(default_factory=tuple)


class TriggerEngine:
    """Pure state machine: fed key events, returns bindings to fire."""

    def __init__(self, bindings, leader_timeout_ms: int = 1200):
        self.bindings = list(bindings)
        self.pressed: set[int] = set()
        self._tap: dict[int, tuple[Binding, float]] = {}
        self._hold: dict[int, tuple[Binding, float]] = {}
        self._double: dict[int, tuple[Binding, float]] = {}
        self._armed: set[int] = set()
        self._scoped_vks = {vk for b in self.bindings if b.apps for vk in b.vks}
        self._leader_timeout = max(300, min(5000, int(leader_timeout_ms)))
        self._leader: list[Binding] = []
        self._leader_step: int = 0
        self._leader_deadline: float = 0.0
        self._leader_hint: str | None = None

    def take_hint(self) -> str | None:
        hint = self._leader_hint
        self._leader_hint = None
        return hint

    def needs_app(self, vk: int) -> bool:
        return vk in self._scoped_vks

    def _eligible(self, app: str) -> list[Binding]:
        matched = [b for b in self.bindings
                   if win32.app_matches(b.apps, app)]
        scoped = {(b.mods, b.vks, b.trigger) for b in matched if b.apps}
        if not scoped:
            return matched
        return [b for b in matched
                if b.apps or (b.mods, b.vks, b.trigger) not in scoped]

    def _clear_leader(self) -> None:
        self._leader = []
        self._leader_step = 0
        self._leader_deadline = 0.0
        self._leader_hint = None

    def _hint_for(self, bindings: list[Binding], step: int) -> str | None:
        if not bindings:
            return None
        prefix = _keys.format_many(bindings[0].mods, bindings[0].vks)
        next_keys: list[str] = []
        seen: set[str] = set()
        for b in bindings:
            if len(b.seq) <= step:
                continue
            _m, vks = b.seq[step]
            name = _keys.format_many(0, vks)
            if name not in seen:
                seen.add(name)
                next_keys.append(name)
        if not next_keys:
            return None
        return f"{prefix}  ->  {', '.join(next_keys)}"

    def feed_down(self, vk: int, mods: int, now: float,
                  app: str = "") -> list[Binding]:
        if vk in self.pressed:
            return []
        self.pressed.add(vk)

        if self._leader:
            if vk in MODIFIER_VKS:
                return []
            matches: list[Binding] = []
            for b in self._leader:
                if len(b.seq) <= self._leader_step:
                    continue
                step_mods, step_vks = b.seq[self._leader_step]
                if not (step_vks and step_vks[0] == vk):
                    continue
                if step_mods == 0:
                    if (mods & ~b.mods) == 0:
                        matches.append(b)
                elif step_mods == mods:
                    matches.append(b)
            if not matches:
                self._clear_leader()
            else:
                self._leader = matches
                self._leader_step += 1
                self._leader_deadline = now + self._leader_timeout / 1000.0
                # Fire every sequence that is complete at this step.  A longer
                # sequence sharing the same prefix stays armed, so both
                # "prefix > A" and "prefix > A > B" can be used.
                complete = [b for b in self._leader
                            if len(b.seq) == self._leader_step]
                if complete:
                    self._leader = [b for b in self._leader
                                    if len(b.seq) > self._leader_step]
                    if self._leader:
                        self._leader_deadline = now + self._leader_timeout / 1000.0
                        self._leader_hint = self._hint_for(
                            self._leader, self._leader_step)
                    else:
                        self._clear_leader()
                    return complete
                self._leader_hint = self._hint_for(self._leader, self._leader_step)
                return []

        fired: list[Binding] = []
        eligible = self._eligible(app)

        seq_prefix = [b for b in eligible
                      if b.seq and b.vks and b.vks[0] == vk
                      and b.mods == mods and b.trigger == "press"]
        if seq_prefix:
            self._leader = list(seq_prefix)
            self._leader_step = 1
            self._leader_deadline = now + self._leader_timeout / 1000.0
            self._leader_hint = self._hint_for(self._leader, self._leader_step)
            return fired

        for b in eligible:
            if b.seq:
                continue
            if b.mods != mods:
                continue
            if len(b.vks) > 1:
                if set(b.vks) <= self.pressed and b.index not in self._armed:
                    self._armed.add(b.index)
                    if self._tap:
                        self._tap = {i: (tb, ts)
                                     for i, (tb, ts) in self._tap.items()
                                     if tb.vks[0] not in b.vks}
                    if self._hold:
                        self._hold = {i: (hb, hd)
                                      for i, (hb, hd) in self._hold.items()
                                      if hb.vks[0] not in b.vks}
                    if self._double:
                        self._double = {i: (db, ds)
                                        for i, (db, ds) in self._double.items()
                                        if db.vks[0] not in b.vks}
                    fired.append(b)
            elif b.vks[0] == vk:
                if b.trigger == "hold":
                    self._hold[b.index] = (b, now + b.hold_ms / 1000.0)
                elif b.trigger == "tap":
                    self._tap[b.index] = (b, now)
                elif b.trigger == "double":
                    first = self._double.get(b.index)
                    if first is not None and now - first[1] <= b.hold_ms / 1000.0:
                        self._double.pop(b.index, None)
                        fired.append(b)
                    else:
                        self._double[b.index] = (b, now)
                else:
                    fired.append(b)
        return fired

    def feed_up(self, vk: int, now: float) -> list[Binding]:
        self.pressed.discard(vk)
        fired: list[Binding] = []
        for idx, (b, started) in list(self._tap.items()):
            if b.vks[0] == vk:
                self._tap.pop(idx, None)
                if now - started <= b.hold_ms / 1000.0:
                    fired.append(b)
        for idx, (b, _) in list(self._hold.items()):
            if b.vks[0] == vk:
                self._hold.pop(idx, None)
        for idx in list(self._armed):
            b = self._by_index().get(idx)
            if b and vk in b.vks and not set(b.vks) <= self.pressed:
                self._armed.discard(idx)
        return fired

    def due(self, now: float, mods: int, is_down,
            app: str | None = None) -> list[Binding]:
        if self._leader and now >= self._leader_deadline:
            self._clear_leader()
        fired: list[Binding] = []
        for idx, (b, deadline) in list(self._hold.items()):
            if now < deadline:
                continue
            if mods != b.mods or not is_down(b.vks[0]):
                self._hold.pop(idx, None)
                continue
            if b.apps and app is not None and not win32.app_matches(b.apps, app):
                self._hold.pop(idx, None)
                continue
            self._hold.pop(idx, None)
            fired.append(b)
        return fired

    def next_deadline(self) -> float | None:
        values = [d for _, d in self._hold.values()]
        if self._leader:
            values.append(self._leader_deadline)
        if not values:
            return None
        return min(values)

    def reset(self) -> None:
        self.pressed.clear()
        self._tap.clear()
        self._hold.clear()
        self._double.clear()
        self._armed.clear()
        self._clear_leader()

    def _by_index(self) -> dict[int, Binding]:
        return {b.index: b for b in self.bindings}


class KeyboardHook:
    def __init__(self, on_event):
        self.on_event = on_event
        self._proc = _HookProc(on_event)
        self.installed = self._proc.install()

    def close(self) -> None:
        self._proc.close()
        self.installed = False


class _MouseHookProc:
    def __init__(self, on_event):
        self.on_event = on_event
        self._ref = None
        self.hook = 0

    def install(self) -> bool:
        if self.hook:
            return True
        self._ref = win32.HOOKPROC(self._callback)
        self.hook = win32.user32.SetWindowsHookExW(
            WH_MOUSE_LL, self._ref, win32.kernel32.GetModuleHandleW(None), 0)
        if not self.hook:
            self._ref = None
            return False
        return True

    def _callback(self, ncode, wparam, lparam):
        swallow = False
        try:
            if ncode == 0:
                msg = int(wparam)
                info = ctypes.cast(ctypes.c_void_p(lparam),
                                   POINTER(MSLLHOOKSTRUCT)).contents
                # SendInput() marks macro-generated clicks as injected.  Feeding
                # those back into the trigger engine makes a macro that clicks a
                # mouse-button hotkey fire itself over and over.
                if info.flags & 0x00000001:  # LLMHF_INJECTED
                    return win32.user32.CallNextHookEx(0, ncode, wparam, lparam)
                event = MOUSE_MESSAGES.get(msg)
                if event is None and msg in (WM_XBUTTONDOWN, WM_XBUTTONUP):
                    button = (int(info.mouseData) >> 16) & 0xFFFF
                    if button == XBUTTON1:
                        vk = VK_XBUTTON1
                    elif button == XBUTTON2:
                        vk = VK_XBUTTON2
                    else:
                        vk = 0
                    if vk:
                        event = ("down" if msg == WM_XBUTTONDOWN else "up", vk)
                if event is not None:
                    swallow = bool(self.on_event(event[0], event[1]))
        except Exception:
            pass
        if swallow:
            return 1
        return win32.user32.CallNextHookEx(0, ncode, wparam, lparam)

    def close(self) -> None:
        if self.hook:
            try:
                win32.user32.UnhookWindowsHookEx(self.hook)
            except Exception:
                pass
            self.hook = 0
            self._ref = None


class MouseHook:
    def __init__(self, on_event):
        self.on_event = on_event
        self._proc = _MouseHookProc(on_event)
        self.installed = self._proc.install()

    def close(self) -> None:
        self._proc.close()
        self.installed = False


class _MouseRecorderProc:
    def __init__(self, on_event):
        self.on_event = on_event
        self._ref = None
        self.hook = 0

    def install(self) -> bool:
        if self.hook:
            return True
        self._ref = win32.HOOKPROC(self._callback)
        self.hook = win32.user32.SetWindowsHookExW(
            WH_MOUSE_LL, self._ref, win32.kernel32.GetModuleHandleW(None), 0)
        if not self.hook:
            self._ref = None
            return False
        return True

    def _callback(self, ncode, wparam, lparam):
        try:
            if ncode == 0:
                msg = int(wparam)
                info = ctypes.cast(ctypes.c_void_p(lparam),
                                   POINTER(MSLLHOOKSTRUCT)).contents
                if info.flags & 0x00000001:  # LLMHF_INJECTED
                    return win32.user32.CallNextHookEx(0, ncode, wparam, lparam)
                event = None
                if msg == WM_LBUTTONDOWN:
                    event = ("down", "left")
                elif msg == WM_LBUTTONUP:
                    event = ("up", "left")
                elif msg == WM_RBUTTONDOWN:
                    event = ("down", "right")
                elif msg == WM_RBUTTONUP:
                    event = ("up", "right")
                elif msg == WM_MBUTTONDOWN:
                    event = ("down", "middle")
                elif msg == WM_MBUTTONUP:
                    event = ("up", "middle")
                elif msg in (WM_XBUTTONDOWN, WM_XBUTTONUP):
                    button = (int(info.mouseData) >> 16) & 0xFFFF
                    name = "x1" if button == XBUTTON1 else ("x2" if button == XBUTTON2 else None)
                    if name:
                        event = ("down" if msg == WM_XBUTTONDOWN else "up", name)
                if event is not None:
                    try:
                        self.on_event(event[0], event[1],
                                      int(info.pt.x), int(info.pt.y))
                    except Exception:
                        pass
        except Exception:
            pass
        return win32.user32.CallNextHookEx(0, ncode, wparam, lparam)

    def close(self) -> None:
        if self.hook:
            try:
                win32.user32.UnhookWindowsHookEx(self.hook)
            except Exception:
                pass
            self.hook = 0
            self._ref = None


class MouseRecorderHook:
    def __init__(self, on_event):
        self.on_event = on_event
        self._proc = _MouseRecorderProc(on_event)
        self.installed = self._proc.install()

    def close(self) -> None:
        self._proc.close()
        self.installed = False
