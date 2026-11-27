"""Built-in diagnostics: python Hotkey.pyw --self-test [--full]"""
from __future__ import annotations

import ctypes
import json
import logging
import os
import queue
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from . import actions, config, i18n, icon, keys, macro, update, win32


class Results:
    def __init__(self) -> None:
        self.failed = 0

    def check(self, name: str, fn) -> None:
        try:
            detail = fn()
            print(f"  PASS  {name}" + (f"  ({detail})" if detail else ""))
        except Exception as exc:
            self.failed += 1
            print(f"  FAIL  {name}: {exc}")


def _test_keys() -> str:
    cases = {
        "ctrl+alt+t": (keys.MOD_CONTROL | keys.MOD_ALT, 0x54),
        "Ctrl + Shift + F5": (keys.MOD_CONTROL | keys.MOD_SHIFT, 0x74),
        "win+space": (keys.MOD_WIN, 0x20),
        "media_play_pause": (0, 0xB3),
    }
    for combo, expected in cases.items():
        got = keys.parse(combo)
        assert got == expected, f"{combo}: {got} != {expected}"
    for bad in ("t", "ctrl+", "ctrl+alt+t+x", "hyper+q"):
        try:
            keys.parse(bad)
        except keys.HotkeyError:
            continue
        raise AssertionError(f"{bad!r} should be rejected")
    try:
        keys.parse("delete")
    except keys.HotkeyError:
        pass
    else:
        raise AssertionError("bare delete should be rejected as a hotkey")
    assert keys.parse("delete", allow_bare=True) == (0, 0x2E)
    # Recorder names must never reach name_to_vk unchanged: "left" is the
    # left arrow key, not the left mouse button.
    assert keys.normalize_mouse_button("x1") == "mouse4"
    assert keys.normalize_mouse_button("LEFT") == "mouse_left"
    assert keys.normalize_mouse_button("mouse5") == "mouse5"
    assert keys.name_to_vk(keys.normalize_mouse_button("middle")) == 0x04
    return f"{len(cases)} combos + mouse aliases"


def _test_tokens() -> str:
    out = actions.expand_tokens("{date:%Y}|{user}|{uuid}|{newline}|{tab}")
    parts = out.split("|")
    assert len(parts) == 5, out
    assert len(parts[0]) == 4 and parts[0].isdigit(), out
    assert parts[1], out
    assert len(parts[2]) == 36, out
    assert parts[3] == "\n" and parts[4] == "\t", repr(out)
    return out.replace("\n", "\\n").replace("\t", "\\t")


def _test_run_command() -> str:
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "ran.txt")
        actions._run_command(f'cmd /c echo ok > "{out}"', None)
        deadline = time.time() + 2.0
        content = ""
        while time.time() < deadline:
            try:
                with open(out, encoding="utf-8") as fh:
                    content = fh.read().strip()
                if content:
                    break
            except OSError:
                pass
            time.sleep(0.02)
        assert content == "ok", content
        time.sleep(0.05)  # let the detached cmd release the file before cleanup
    return "detached command"


def _test_topmost_api() -> str:
    """Pin/unpin uses HWND_TOPMOST and HWND_NOTOPMOST on the target window."""
    state = {"ex": 0}
    calls: list[str] = []
    flags: list[int] = []

    class FakeUser32:
        def GetWindowLongW(self, hwnd, index):
            assert index == win32.GWL_EXSTYLE
            return state["ex"]

        def SetWindowPos(self, hwnd, insert, x, y, width, height, options):
            if insert is win32.HWND_TOPMOST:
                calls.append("pin")
                state["ex"] |= win32.WS_EX_TOPMOST
            elif insert is win32.HWND_NOTOPMOST:
                calls.append("unpin")
                state["ex"] &= ~win32.WS_EX_TOPMOST
            else:
                calls.append("?")
            flags.append(int(options))
            return 1

    old_user = win32.user32
    win32.user32 = FakeUser32()
    try:
        assert not win32.is_topmost(99)
        assert win32.set_topmost(99, True) is True
        assert win32.is_topmost(99)
        assert win32.set_topmost(99, False) is True
        assert not win32.is_topmost(99)
        assert win32.toggle_topmost(99) is True
        assert win32.toggle_topmost(99) is False
    finally:
        win32.user32 = old_user
    assert calls == ["pin", "unpin", "pin", "unpin"], calls
    expected = win32.SWP_NOMOVE | win32.SWP_NOSIZE | win32.SWP_NOACTIVATE
    assert all(flag == expected for flag in flags), flags
    return "HWND_TOPMOST / HWND_NOTOPMOST + toggle"


def _test_pin_action() -> str:
    """The pin action targets the window active when the hotkey fires."""
    old_foreground = win32.foreground
    old_is_topmost = win32.is_topmost
    old_set_topmost = win32.set_topmost
    state = {"top": False, "foreground": 4242}
    calls: list[tuple[int, bool]] = []

    def fake_set(hwnd, on):
        calls.append((int(hwnd), bool(on)))
        state["top"] = bool(on)
        return True

    win32.foreground = lambda: state["foreground"]
    win32.is_topmost = lambda hwnd: state["top"]
    win32.set_topmost = fake_set
    ctx = type("Ctx", (), {"settings": {}})()

    def run(mode: str) -> str:
        entry = config.Entry(keys="ctrl+alt+p", action="pin", value=mode)
        return actions.run(entry, ctx)

    try:
        assert "pinned" in run("pin")
        assert calls[-1] == (4242, True) and state["top"], calls
        assert "unpinned" in run("unpin")
        assert calls[-1] == (4242, False) and not state["top"], calls
        assert "pinned" in run("toggle")
        assert calls[-1] == (4242, True), calls
        assert "unpinned" in run("toggle"), calls

        for bad in ("floating",):
            try:
                run(bad)
            except actions.ActionError:
                pass
            else:
                raise AssertionError(f"unknown pin mode {bad!r} accepted")

        state["foreground"] = None
        try:
            run("pin")
        except actions.ActionError:
            pass
        else:
            raise AssertionError("pin without an active window accepted")

        state["foreground"] = 4242
        win32.set_topmost = lambda hwnd, on: False
        try:
            run("pin")
        except actions.ActionError:
            pass
        else:
            raise AssertionError("refused pin was reported as success")
    finally:
        win32.foreground = old_foreground
        win32.is_topmost = old_is_topmost
        win32.set_topmost = old_set_topmost
    return "pin / unpin / toggle on the active window"


def _test_config() -> str:
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "hotkeys.json")
        config.ensure_default(path)
        cfg = config.load(path)
        assert not cfg.errors, cfg.errors
        assert len(cfg.entries) == len(config.DEFAULT_HOTKEYS)
        data = config.to_raw(cfg)
        config.save_raw(path, data)
        again = config.load(path)
        assert len(again.entries) == len(cfg.entries)
        bad = os.path.join(tmp, "bad.json")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("{ nope")
        assert config.load(bad).errors
        flags = os.path.join(tmp, "flags.json")
        config.save_raw(flags, {
            "version": 1, "settings": {}, "hotkeys": [
                {"keys": "ctrl+alt+f24", "action": "open", "value": "x",
                 "enabled": "false"},
                {"keys": "ctrl+alt+f23", "action": "open", "value": "x",
                 "enabled": "true"},
            ],
        })
        flag_cfg = config.load(flags)
        assert [e.enabled for e in flag_cfg.entries] == [False, True], (
            flag_cfg.entries, flag_cfg.warnings)
    return f"{len(config.DEFAULT_HOTKEYS)} starter hotkeys"


def _test_language() -> str:
    assert i18n.normalize("FR") == "fr"
    assert i18n.normalize("nonsense") == "en"
    assert i18n.code_from_display(i18n.display("ar")) == "ar"
    assert i18n.is_rtl("ar") and i18n.is_rtl("AR")
    assert not i18n.is_rtl("fr") and not i18n.is_rtl("en")
    assert not i18n.is_rtl("nonsense")
    assert i18n.tr("Quit", "fr") == "Quitter"
    assert i18n.tr("Quit", "ar") != "Quit"
    assert i18n.tr("Profile: {name}", "fr", name="Work") == "Profil : Work"
    assert "language" in config.DEFAULT_SETTINGS
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "lang.json")
        config.save_raw(path, {
            "version": 1, "settings": {"language": "fr"}, "hotkeys": [],
        })
        cfg = config.load(path)
        assert not cfg.errors and not cfg.warnings, (cfg.errors, cfg.warnings)
        assert cfg.settings["language"] == "fr", cfg.settings
        config.save_raw(path, {
            "version": 1, "settings": {"language": "xx"}, "hotkeys": [],
        })
        cfg = config.load(path)
        assert cfg.settings["language"] == "en", cfg.settings
        assert cfg.warnings, "invalid language should warn"
    return "en/fr/ar + config validation"


def _test_icon() -> str:
    with tempfile.TemporaryDirectory() as tmp:
        active, paused = icon.ensure_icon(tmp)
        for path in (active, paused):
            with open(path, "rb") as fh:
                head = fh.read(22)
            assert head[:4] == b"\x00\x00\x01\x00", "not an ICO"
        return f"{os.path.getsize(active)} bytes"


PM_REMOVE = 0x0001


def _test_hotkey_dispatch() -> str:
    hits: queue.Queue[int] = queue.Queue()

    def proc(hwnd, msg, wparam, lparam):
        if msg == win32.WM_HOTKEY:
            hits.put(int(wparam))
            return 0
        return win32.user32.DefWindowProcW(win32.HWND(hwnd), msg, wparam, lparam)

    callback = win32.WNDPROC(proc)
    hinst = win32.kernel32.GetModuleHandleW(None)
    wc = win32.WNDCLASSW()
    wc.lpfnWndProc = callback
    wc.hInstance = hinst
    wc.lpszClassName = "HotkeySelfTestWindow"
    win32.user32.RegisterClassW(ctypes.byref(wc))
    hwnd = win32.user32.CreateWindowExW(0, "HotkeySelfTestWindow", "selftest",
                                        0, 0, 0, 0, 0, None, None, hinst, None)
    assert hwnd, "window creation failed"
    hwnd = int(hwnd)
    registered = None
    try:
        for mods, vk, label in (
            (keys.MOD_CONTROL | keys.MOD_ALT | keys.MOD_SHIFT, 0x87, "ctrl+alt+shift+f24"),
            (keys.MOD_CONTROL | keys.MOD_ALT, 0x87, "ctrl+alt+f24"),
            (keys.MOD_CONTROL | keys.MOD_SHIFT, 0x87, "ctrl+shift+f24"),
        ):
            if win32.user32.RegisterHotKey(win32.HWND(hwnd), 777,
                                           mods | keys.MOD_NOREPEAT, vk):
                registered = label
                break
        assert registered, "all test hotkeys are in use by other apps"

        win32.user32.PostMessageW(win32.HWND(hwnd), win32.WM_HOTKEY, 777, 0)
        msg = win32.MSG()
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and hits.empty():
            if win32.user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                win32.user32.TranslateMessage(ctypes.byref(msg))
                win32.user32.DispatchMessageW(ctypes.byref(msg))
        assert hits.get_nowait() == 777, "WM_HOTKEY was not dispatched"
    finally:
        if registered:
            win32.user32.UnregisterHotKey(win32.HWND(hwnd), 777)
        win32.user32.DestroyWindow(win32.HWND(hwnd))
    return registered or ""


def _test_clipboard() -> str:
    original = win32.get_clipboard()
    probe = "hotkey-selftest-\u2713-42"
    try:
        assert win32.set_clipboard(probe), "set_clipboard failed"
        assert win32.get_clipboard() == probe, "clipboard round-trip mismatch"
    finally:
        win32.set_clipboard(original)
    return f"{len(probe)} chars"


def _test_engine() -> str:
    from .hooks import TriggerEngine, Binding
    # chord
    eng = TriggerEngine([Binding(index=1, mods=0, vks=(74, 75), trigger="press", hold_ms=400)])
    assert eng.feed_down(74, 0, 0.0) == []
    assert [b.index for b in eng.feed_down(75, 0, 0.0)] == [1]
    # tap: short press fires on release
    eng = TriggerEngine([Binding(index=2, mods=0, vks=(74,), trigger="tap", hold_ms=400)])
    assert eng.feed_down(74, 0, 1.0) == []
    assert [b.index for b in eng.feed_up(74, 1.1)] == [2]
    # hold: fires after deadline
    eng = TriggerEngine([Binding(index=3, mods=0, vks=(74,), trigger="hold", hold_ms=400)])
    assert eng.feed_down(74, 0, 2.0) == []
    assert eng.due(2.3, 0, lambda v: True) == []
    fired = eng.due(2.4, 0, lambda v: True)
    assert [b.index for b in fired] == [3], fired
    # release before deadline cancels
    eng.feed_down(74, 0, 3.0)
    eng.feed_up(74, 3.1)
    assert eng.due(3.5, 0, lambda v: True) == []
    # press + hold on the same combo must not double-fire.  A quick release
    # runs only press; holding past the deadline runs only hold.
    ctrl = keys.MOD_CONTROL
    press = Binding(index=10, mods=ctrl, vks=(6,), trigger="press")
    hold = Binding(index=11, mods=ctrl, vks=(6,), trigger="hold", hold_ms=400)
    eng = TriggerEngine([press, hold])
    assert eng.feed_down(6, ctrl, 4.0) == []
    assert [b.index for b in eng.feed_up(6, 4.1)] == [10], "quick press lost"
    assert eng.due(4.5, ctrl, lambda v: True) == []
    assert eng.feed_down(6, ctrl, 5.0) == []
    assert eng.due(5.3, ctrl, lambda v: True) == []
    assert [b.index for b in eng.due(5.5, ctrl, lambda v: True)] == [11], "hold lost"
    assert eng.feed_up(6, 5.6) == [], "press fired after hold"
    # tap owning the combo replaces press entirely
    tap = Binding(index=12, mods=ctrl, vks=(6,), trigger="tap", hold_ms=400)
    eng = TriggerEngine([press, tap])
    assert eng.feed_down(6, ctrl, 6.0) == []
    assert [b.index for b in eng.feed_up(6, 6.1)] == [12]
    # The chord-safe tap window is 30 s.  A matured hold must still cancel it,
    # otherwise releasing after the hold would fire both actions.
    chord_tap = Binding(index=13, mods=0, vks=(6,), trigger="tap", hold_ms=30000)
    chord_hold = Binding(index=14, mods=0, vks=(6,), trigger="hold", hold_ms=400)
    eng = TriggerEngine([chord_tap, chord_hold])
    assert eng.feed_down(6, 0, 7.0) == []
    assert [b.index for b in eng.due(7.5, 0, lambda v: True)] == [14]
    assert eng.feed_up(6, 7.6) == [], "chord tap fired after hold"
    assert eng.feed_down(6, 0, 8.0) == []
    assert [b.index for b in eng.feed_up(6, 8.1)] == [13], "quick tap lost"
    return "chord + tap + hold + trigger conflicts"


def _test_app_scope() -> str:
    from .hooks import Binding, TriggerEngine
    assert win32.app_matches([], "anything.exe")
    assert win32.app_matches(["chrome"], "chrome.exe")
    assert win32.app_matches(["chrome.exe"], "chrome")
    assert win32.app_matches(["*code*"], "vscode.exe")
    assert not win32.app_matches(["chrome.exe"], "firefox.exe")
    assert win32.normalize_app(r"C:\Apps\Code.EXE") == "code.exe"
    # same combo: the app-specific binding shadows the global one
    global_b = Binding(index=1, mods=0, vks=(74,), trigger="press")
    app_b = Binding(index=2, mods=0, vks=(74,), trigger="press",
                    apps=frozenset({"chrome.exe"}))
    eng = TriggerEngine([global_b, app_b])
    assert [b.index for b in eng.feed_down(74, 0, 0.0, "chrome.exe")] == [2]
    eng.feed_up(74, 0.1)
    assert [b.index for b in eng.feed_down(74, 0, 1.0, "notepad.exe")] == [1]
    eng.feed_up(74, 1.1)
    # nothing fires in an unrelated app when every binding is scoped
    only = TriggerEngine([app_b])
    assert only.feed_down(74, 0, 2.0, "notepad.exe") == []
    only.feed_up(74, 2.1)
    assert [b.index for b in only.feed_down(74, 0, 3.0, "chrome.exe")] == [2]
    # a tap must re-check the scope when the button is released elsewhere
    tap = Binding(index=3, mods=0, vks=(74,), trigger="tap",
                  apps=frozenset({"chrome.exe"}))
    taps = TriggerEngine([tap])
    assert taps.feed_down(74, 0, 4.0, "chrome.exe") == []
    assert taps.feed_up(74, 4.1, "explorer.exe") == []
    assert [b.index for b in taps.feed_up(74, 4.2, "chrome.exe")] == []
    assert taps.feed_down(74, 0, 5.0, "chrome.exe") == []
    assert [b.index for b in taps.feed_up(74, 5.1, "chrome.exe")] == [3]
    # config round-trip keeps the scope
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "scoped.json")
        config.save_raw(path, {
            "version": 1, "settings": {},
            "hotkeys": [{"keys": "ctrl+alt+t", "action": "open", "value": "x",
                         "apps": ["Chrome.EXE", "code"]}],
        })
        cfg = config.load(path)
        assert not cfg.errors, cfg.errors
        assert cfg.entries[0].apps == ("chrome.exe", "code"), cfg.entries[0].apps
        assert config.to_raw(cfg)["hotkeys"][0]["apps"] == ["chrome.exe", "code"]
    return "global + 2 apps"


def _test_foreground() -> str:
    apps = win32.list_running_apps()
    assert isinstance(apps, tuple) and apps, "no visible windows found"
    exe = win32.foreground_app()
    assert isinstance(exe, str), "foreground_app() must return a string"
    return f"{len(apps)} apps visible, active={exe or 'n/a'}"


def _test_sequence() -> str:
    from .hooks import TriggerEngine, Binding
    prefix_mods = keys.MOD_CONTROL
    prefix_vk = 0x4B  # K
    next_vk = 0x44    # D
    seq = ((prefix_mods, (prefix_vk,)), (0, (next_vk,)))
    binding = Binding(index=7, mods=prefix_mods, vks=(prefix_vk,),
                     trigger="press", seq=seq)
    eng = TriggerEngine([binding], leader_timeout_ms=1000)
    assert eng.feed_down(prefix_vk, prefix_mods, 0.0) == []
    hint = eng.take_hint()
    assert hint and "D" in hint, hint
    fired = eng.feed_down(next_vk, 0, 0.1)
    assert [b.index for b in fired] == [7], fired
    # timeout clears the pending leader
    eng2 = TriggerEngine([binding], leader_timeout_ms=1000)
    assert eng2.feed_down(prefix_vk, prefix_mods, 1.0) == []
    eng2.due(2.1, 0, lambda v: True)
    assert eng2.feed_down(next_vk, 0, 2.2) == []
    # a wrong key cancels the leader and falls through
    eng3 = TriggerEngine([binding], leader_timeout_ms=1000)
    eng3.feed_down(prefix_vk, prefix_mods, 2.0)
    assert eng3.feed_down(0x58, 0, 2.1) == []
    # A shorter complete sequence fires while a longer one with the same
    # prefix stays armed for the next key.
    short = Binding(index=8, mods=prefix_mods, vks=(prefix_vk,),
                    trigger="press", seq=seq)
    long_seq = seq + ((0, (0x41,)),)  # Ctrl+K > D > A
    long_b = Binding(index=9, mods=prefix_mods, vks=(prefix_vk,),
                     trigger="press", seq=long_seq)
    eng4 = TriggerEngine([short, long_b], leader_timeout_ms=1000)
    assert eng4.feed_down(prefix_vk, prefix_mods, 4.0) == []
    eng4.feed_up(prefix_vk, 4.01)
    fired = eng4.feed_down(next_vk, 0, 4.1)
    assert [b.index for b in fired] == [8], fired
    eng4.feed_up(next_vk, 4.11)
    fired = eng4.feed_down(0x41, 0, 4.2)
    assert [b.index for b in fired] == [9], fired
    return "prefix + follower + timeout + ambiguous prefix"


def _test_profiles() -> str:
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "profiles.json")
        config.save_raw(path, {
            "version": 1, "settings": {}, "active_profile": "Work",
            "hotkeys": [
                {"keys": "ctrl+alt+t", "action": "open", "value": "x"},
                {"keys": "ctrl+alt+u", "action": "open", "value": "y",
                 "profile": "Work"},
            ],
        })
        cfg = config.load(path)
        assert not cfg.errors, cfg.errors
        assert cfg.active_profile == "Work"
        assert config.profile_names(cfg.entries) == ("Work",)
        active_default = [e for e in cfg.entries
                          if config.entry_is_active(e, "")]
        assert len(active_default) == 1
        active_work = [e for e in cfg.entries
                       if config.entry_is_active(e, "Work")]
        assert len(active_work) == 2
        raw = config.to_raw(cfg)
        assert raw.get("active_profile") == "Work"
        config.save_raw(path, raw)
        again = config.load(path)
        assert again.active_profile == "Work"
    return "tagged entries + active filter"


def _test_macro_control() -> str:
    control = macro.MacroControl()
    control.set_times(2)
    control.set_speed(2.0)

    class Ctx:
        settings = {}

        def notify(self, *_args, **_kwargs):
            pass

    ctx = Ctx()
    ctx.macro = control
    entry = config.Entry(
        keys="F14", action="macro",
        extra={"steps": [{"wait": 1}, {"wait": 1}], "speed": 1.0},
    )
    # a hotkey only loads the macro; the following real start must still work
    actions.run(entry, ctx, prepare_only=True)
    assert not control.snapshot()["running"]
    # A second hotkey press during playback must not reset shared state.
    control.running = True
    control._stop = True
    try:
        actions.run(entry, ctx, prepare_only=True)
    except actions.ActionError:
        pass
    else:
        raise AssertionError("prepare_only reset a running macro")
    assert control.running and control._stop
    control.running = False
    control._stop = False
    actions.run(entry, ctx)
    deadline = time.time() + 2.0
    while control.snapshot()["running"] and time.time() < deadline:
        time.sleep(0.01)
    s = control.snapshot()
    assert not s["running"], s
    assert s["run"] == 2 and s["total_runs"] == 2, s
    assert s["speed"] == 2.0, s
    control.set_times(5)
    control.set_speed(0.5)
    assert control.snapshot()["times"] == 5
    assert control.snapshot()["speed"] == 0.5
    control.stop()
    assert control.stopping()
    control.cancel()
    assert control.aborted()

    # the user-chosen start/stop actions drive the same control object
    control.set_times(1)
    control.prepare([{"wait": 1}], "ready", entry=entry)
    actions.run(config.Entry(keys="F15", action="macro_start"), ctx)
    deadline = time.time() + 1.0
    while control.snapshot()["running"] and time.time() < deadline:
        time.sleep(0.01)
    assert control.snapshot()["run"] == 1
    actions.run(config.Entry(keys="F16", action="macro_stop"), ctx)
    assert control.aborted()

    # Times really changes the denominator mid-run; Stop only sets the
    # boundary flag, while Cancel flips the immediate-abort flag as well.
    live = macro.MacroControl()
    live.begin([{"wait": 50}] * 6, "live", times=2)
    live.set_times(4)
    ls = live.snapshot()
    assert ls["total_runs"] == 4 and live.repeat_count() == 4, ls
    live.progress(1, 3)
    live.stop()
    assert live.stopping() and not live.aborted()
    live.cancel()
    assert live.aborted()
    live.finish()
    ls = live.snapshot()
    assert not ls["running"] and ls["step"] < ls["steps"], ls
    done = macro.MacroControl()
    done.begin([{"wait": 1}], "done", times=1)
    done.finish()
    assert done.snapshot()["step"] == done.snapshot()["steps"]
    return "repeat count, live Times, stop/cancel, start/stop keys"


def _test_validation() -> str:
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "warnings.json")
        config.save_raw(path, {
            "version": 1, "settings": {},
            "hotkeys": [{
                "keys": "ctrl+alt+t", "action": "open", "value": "x",
                "trigger": "nonsense", "app": 7, "profile": 7,
            }],
        })
        cfg = config.load(path)
        assert not cfg.errors, cfg.errors
        assert len(cfg.warnings) >= 3, cfg.warnings
        assert cfg.entries and cfg.entries[0].trigger == "press"

    from . import app as appmod
    fake = appmod.App.__new__(appmod.App)
    fake.cfg = config.Config(path="")
    log = logging.getLogger("hotkey")
    old_level = log.level
    log.setLevel(logging.ERROR)  # the unsafe-key warning is expected here
    try:
        fake.cfg.settings["macro_start_hotkey"] = "t"   # bare letter: unsafe
        fake.cfg.settings["macro_stop_hotkey"] = "Mouse5"
        entries = fake._control_entries()
        assert [e.action for e in entries] == ["macro_stop"], entries
        fake.cfg.settings["macro_start_hotkey"] = "F13"  # safe bare key
        entries = fake._control_entries()
        assert [e.action for e in entries] == ["macro_start", "macro_stop"], entries
    finally:
        log.setLevel(old_level)
    return "config warnings + safe macro keys"


def _test_update() -> str:
    payloads = {
        "/new": {
            "tag_name": "v9.9.9", "prerelease": False,
            "html_url": "https://github.com/ouaeel/hotkey/releases/tag/v9.9.9",
            "body": "next release",
            "assets": [{"name": "hotkey-v9.9.9-source.zip",
                        "browser_download_url": "https://example/hotkey-v9.9.9-source.zip"}],
        },
        "/old": {"tag_name": "v0.0.1", "prerelease": False, "assets": []},
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps(payloads.get(self.path, {})).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        info = update.check(base + "/new", token="test")
        assert info is not None and info.version == "9.9.9", info
        assert info.url.endswith("hotkey-v9.9.9-source.zip"), info
        assert update.check(base + "/old") is None
    finally:
        server.shutdown()
        server.server_close()
    assert update.is_newer("v1.0.1", "1.0.0")
    assert not update.is_newer("1.0.0", "1.0.0")
    assert not update.is_newer("bad", "1.0.0")
    assert update.releases_page(update.DEFAULT_URL) == (
        "https://github.com/ouaeel/hotkey/releases")
    assert update.releases_page(
        "https://api.github.com/repos/fork/tool/releases/latest") == (
            "https://github.com/fork/tool/releases")
    assert update.releases_page(
        "https://github.com/fork/tool/releases") == (
            "https://github.com/fork/tool/releases")
    return "version compare + release parsing"


def _test_update_status() -> str:
    from .app import App

    # Ambient tokens must not turn this hermetic check into a live request.
    old_token = os.environ.pop(update.DEFAULT_TOKEN_ENV, None)
    try:
        app = App.__new__(App)
        app.hwnd = 0
        app.use_tray = False
        app.cfg = config.Config(path="")
        app.cfg.settings.update({
            "language": "en",
            "update_private": True,
            "update_url": update.DEFAULT_URL,
            "update_token": "",
            "update_token_env": update.DEFAULT_TOKEN_ENV,
        })
        app._update_info = None
        app._update_manual = False
        app._update_busy = False
        app.update_events = queue.Queue(maxsize=4)
        app._update_state = {
            "state": "idle", "version": "", "message": "Not checked yet",
            "kwargs": {}, "url": update.DEFAULT_URL,
        }
        app._check_updates(manual=True)
        status = app.update_events.get_nowait()
        assert status["state"] == "blocked", status
        assert status["message"] == "Add a GitHub token to check this private repo"
        assert app.update_snapshot()["current"] == update.__version__
        assert app._releases_url() == "https://github.com/ouaeel/hotkey/releases"
        return "gear status events"
    finally:
        if old_token is not None:
            os.environ[update.DEFAULT_TOKEN_ENV] = old_token


def _test_audit_fixes() -> str:
    """Regressions from the trigger/hook audit (single/double/chord/capture)."""
    from . import app as appmod
    from .hooks import Binding, TriggerEngine

    m4 = keys.name_to_vk("mouse4")
    m5 = keys.name_to_vk("mouse5")
    ctrl = keys.MOD_CONTROL

    def fire_all(eng, events):
        out: list[int] = []
        for when, kind, vk in events:
            got = (eng.feed_down(vk, 0, when) if kind == "down"
                   else eng.feed_up(vk, when))
            out.extend(b.index for b in got)
        return out

    dbl_click = [(0.0, "down", m4), (0.05, "up", m4),
                 (0.2, "down", m4), (0.25, "up", m4)]
    single_click = [(0.0, "down", m4), (0.05, "up", m4)]

    # 1) chord member with press + double: only the double action runs on a
    #    double click, and the press action still runs on a single click.
    shared = [Binding(0, 0, (m4,), "tap", 400),
              Binding(1, 0, (m4, m5), "press", 400),
              Binding(2, 0, (m4,), "double", 400)]
    assert fire_all(TriggerEngine(shared), dbl_click) == [2]
    eng = TriggerEngine(shared)
    assert fire_all(eng, single_click) == []
    assert [b.index for b in eng.due(0.45, 0, lambda v: False)] == [0]
    plain = [Binding(0, 0, (m4,), "press", 400),
             Binding(1, 0, (m4,), "double", 400)]
    assert fire_all(TriggerEngine(plain), dbl_click) == [1]
    eng = TriggerEngine(plain)
    assert fire_all(eng, single_click) == []
    assert [b.index for b in eng.due(0.45, 0, lambda v: False)] == [0]

    # 2) a chord cancels its own buttons regardless of config row order.
    parts = (Binding(0, 0, (m4,), "tap", 400),
             Binding(1, 0, (m4, m5), "press", 400),
             Binding(2, 0, (m5,), "hold", 400))
    for order in ((0, 1, 2), (2, 1, 0), (1, 0, 2)):
        eng = TriggerEngine([parts[i] for i in order])
        got = fire_all(eng, [(0.0, "down", m4), (0.01, "down", m5),
                             (0.02, "up", m5), (0.03, "up", m4)])
        assert got == [1], (order, got)
        assert eng.due(0.5, 0, lambda v: False) == []

    # 3) a lost release no longer leaves a mouse button permanently dead.
    eng = TriggerEngine([Binding(0, 0, (m5,), "hold", 400)])
    eng.feed_down(m5, 0, 0.0)
    assert eng.pressed == {m5}
    eng.feed_down(m5, 0, 0.6)  # its up event never arrived
    assert [b.index for b in eng.due(1.1, 0, lambda v: True)] == [0]
    eng.feed_up(m5, 1.2)
    assert eng.pressed == set()

    # 4) a tap on a chord member fires however long it was held.
    eng = TriggerEngine([Binding(0, 0, (m4,), "tap", 400)])
    eng.feed_down(m4, 0, 0.0)
    assert [b.index for b in eng.feed_up(m4, 41.0)] == [0]

    # 5) the first button of a chord is swallowed; clicks never are.
    fake = appmod.App.__new__(appmod.App)
    fake.engine = TriggerEngine([Binding(0, 0, (m4, m5), "press")])
    fake._swallowed = set()
    assert fake._should_swallow("down", m4, 0) is True
    assert fake._should_swallow("down", 0x01, 0) is False
    assert fake._should_swallow("up", m4, 0) is True
    assert fake._should_swallow("up", m4, 0) is False

    # 6) a native hotkey that prefixes a chord goes through the hook.
    prefix = config.Entry(keys="Ctrl+J", action="keys", value="x",
                          mods=ctrl, vk=0x4A, vks=(0x4A,))
    chord = config.Entry(keys="Ctrl+J+K", action="keys", value="y",
                         mods=ctrl, vk=0x4A, vks=(0x4A, 0x4B))
    plain_key = config.Entry(keys="Ctrl+T", action="keys", value="z",
                             mods=ctrl, vk=0x54, vks=(0x54,))
    combos = appmod.hooked_combos([prefix, chord, plain_key])
    assert (ctrl, frozenset((0x4A,))) in combos
    assert (ctrl, frozenset((0x54,))) not in combos

    # 7) capture mode swallows side buttons and queues them for the editor.
    fake = appmod.App.__new__(appmod.App)
    fake._capture_paused = True
    fake.capture_events = queue.Queue()
    assert fake._hook_event("down", m4) is True
    assert fake._hook_event("down", 0x01) is False  # left click must still work
    assert fake._hook_event("down", 0x4A) is False
    assert fake.capture_events.get_nowait()[1] == m4

    # 8) different macros on one combo are not duplicates.
    raw = {"version": 1, "settings": {}, "hotkeys": [
        {"keys": "mouse4", "action": "macro", "trigger": "press",
         "steps": [{"wait": 1}]},
        {"keys": "mouse4", "action": "macro", "trigger": "hold",
         "steps": [{"wait": 2}]},
    ]}
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "macros.json")
        config.save_raw(path, raw)
        cfg = config.load(path)
        assert not cfg.warnings, cfg.warnings
        raw["hotkeys"][1]["steps"] = [{"wait": 1}]
        raw["hotkeys"][1]["trigger"] = "press"
        config.save_raw(path, raw)
        cfg = config.load(path)
        assert cfg.warnings, "identical macros should warn"
    return "double + chord + lost-up + capture + duplicate guards"


def _test_power_actions() -> str:
    """Sleep/shutdown/restart scheduling is cancellable and never fires in tests."""
    from . import app as appmod

    calls: list[str] = []
    old_suspend, old_shutdown, old_restart = (
        win32.suspend_pc, win32.shutdown_pc, win32.restart_pc)
    win32.suspend_pc = lambda: calls.append("sleep")
    win32.shutdown_pc = lambda: calls.append("shutdown")
    win32.restart_pc = lambda: calls.append("restart")
    fake = None
    try:
        fake = appmod.App.__new__(appmod.App)
        fake._power_lock = threading.Lock()
        fake._power_timer = None
        fake._power_action = ""
        fake._power_deadline = 0.0
        fake._power_generation = 0
        fake.cfg = config.Config(path="")
        fake.use_tray = False
        fake.t = lambda text, **kw: text.format(**kw) if kw else text
        fake.notify = lambda *a, **kw: None
        fake._update_tray = lambda: None

        fake.schedule_power_action("sleep", 0)
        assert calls == ["sleep"], calls

        fake.schedule_power_action("shutdown", 10)
        status = fake.power_status()
        assert status["active"] and status["action"] == "shutdown", status
        assert 590 <= status["seconds_left"] <= 600, status
        stale = fake._power_timer.args[1]
        assert fake.cancel_power_action() is True
        assert not fake.power_status()["active"]
        fake._power_fired("shutdown", stale)  # raced callback must be ignored
        assert calls == ["sleep"], "cancelled timer still ran"

        fake.schedule_power_action("restart", 0)
        assert calls == ["sleep", "restart"], calls

        try:
            fake.schedule_power_action("hibernate", 1)
        except ValueError:
            pass
        else:
            raise AssertionError("unsupported power action was accepted")

        try:
            fake.schedule_power_action("sleep", float("nan"))
        except ValueError:
            pass
        else:
            raise AssertionError("NaN delay was accepted")

        entry = config.Entry(keys="ctrl+alt+f24", action="system",
                             value="shutdown")
        actions.run(entry, fake)
        assert calls[-1] == "shutdown", calls
        entry = config.Entry(keys="ctrl+alt+f24", action="system",
                             value="restart")
        actions.run(entry, fake)
        assert calls[-1] == "restart", calls
        old_recycle = win32.empty_recycle_bin
        win32.empty_recycle_bin = lambda: 1
        try:
            actions.run(config.Entry(keys="ctrl+alt+f24", action="system",
                                     value="recycle"), fake)
        except actions.ActionError:
            pass
        else:
            raise AssertionError("failed recycle was reported as success")
        finally:
            win32.empty_recycle_bin = old_recycle
    finally:
        if fake is not None:
            fake.cancel_power_action(notify=False)
        win32.suspend_pc = old_suspend
        win32.shutdown_pc = old_shutdown
        win32.restart_pc = old_restart
    return "timed sleep/shutdown/restart + cancel"


def _test_suspend_power_api() -> str:
    """Suspend uses S3 on old systems and display-off on Modern Standby."""
    attempts: list[tuple[bool, bool, bool]] = []
    privileged: list[bool] = []
    locked: list[bool] = []
    broadcast: list[tuple] = []

    class FakePowerOk:
        def SetSuspendState(self, hibernate, force, disable):
            attempts.append((bool(hibernate), bool(force), bool(disable)))
            return True

    class FakePowerUnsupported:
        def SetSuspendState(self, hibernate, force, disable):
            attempts.append((bool(hibernate), bool(force), bool(disable)))
            return False

    class FakeUser32:
        def LockWorkStation(self):
            locked.append(True)

        def SendMessageTimeoutW(self, hwnd, msg, wparam, lparam, flags,
                                timeout, result):
            broadcast.append((hwnd, msg, wparam, lparam, flags, timeout))
            return 1

    old_power = win32.powrprof
    old_user = win32.user32
    old_enable = win32._enable_shutdown_privilege
    win32.user32 = FakeUser32()
    win32._enable_shutdown_privilege = lambda: privileged.append(True)
    try:
        win32.powrprof = FakePowerOk()
        win32.suspend_pc()
        assert privileged, "suspend did not request the shutdown privilege"
        assert attempts == [(False, True, False)], attempts
        assert not locked and not broadcast

        win32.powrprof = FakePowerUnsupported()
        ctypes.set_last_error(50)  # ERROR_NOT_SUPPORTED
        win32.suspend_pc()
        assert locked, "modern-standby fallback did not lock the PC"
        assert broadcast and broadcast[-1][1:4] == (0x0112, 0xF170, 2), broadcast
    finally:
        win32.powrprof = old_power
        win32.user32 = old_user
        win32._enable_shutdown_privilege = old_enable
    return "S3 suspend + modern-standby display fallback"


def _test_restart_api() -> str:
    """Restart uses the Windows reboot flag and requests the privilege."""
    calls: list[tuple[int, int]] = []
    privileged: list[bool] = []

    class FakeUser32:
        def ExitWindowsEx(self, flags, reason):
            calls.append((int(flags), int(reason)))
            return True

    old_user = win32.user32
    old_enable = win32._enable_shutdown_privilege
    win32.user32 = FakeUser32()
    win32._enable_shutdown_privilege = lambda: privileged.append(True)
    try:
        win32.restart_pc()
    finally:
        win32.user32 = old_user
        win32._enable_shutdown_privilege = old_enable
    assert privileged, "restart did not request the shutdown privilege"
    assert calls == [(win32.EWX_REBOOT | win32.EWX_FORCEIFHUNG, 0)], calls
    return "EWX_REBOOT + privilege"


def _test_injected_clicks() -> str:
    """Third-party injected clicks work; only our macro clicks are ignored."""
    from . import hooks

    assert hooks._is_our_injection(0x01, win32.INJECT_TAG)
    assert not hooks._is_our_injection(0x01, 0)
    assert not hooks._is_our_injection(0x00, win32.INJECT_TAG)

    sent = []
    old_send = win32._send
    win32._send = lambda inputs: sent.extend(inputs)
    try:
        win32.send_mouse("x1", True)
    finally:
        win32._send = old_send
    assert len(sent) == 1 and sent[0].mi.dwExtraInfo == win32.INJECT_TAG
    return "driver-injected clicks accepted"


def _test_native_fallback() -> str:
    """Native hotkeys stolen by other apps still fire through the hook."""
    from .app import ID_SUSPEND, App

    mods, vk = keys.parse("ctrl+alt+f24")
    entry = config.Entry(
        keys="ctrl+alt+f24", action="run", value="x", index=7,
        enabled=True, mods=mods, vk=vk, vks=(vk,))
    cfg = config.Config(path="")
    cfg.entries.append(entry)
    cfg.settings["suspend_hotkey"] = "ctrl+alt+f23"

    app = App.__new__(App)
    app.hwnd = 0
    app.cfg = cfg
    app.use_tray = False
    app._paused = False
    app.suspended = False
    app._failures = []
    app._registered = set()
    app._by_id = {}
    app._entries_by_index = {entry.index: entry}
    captured: dict = {}
    app._stop_hook = lambda: None
    app._start_hook = lambda bindings, mouse_bindings=(), leader_timeout_ms=None: (
        captured.update(bindings=list(bindings), mouse=list(mouse_bindings)))

    old_register = win32.user32.RegisterHotKey
    win32.user32.RegisterHotKey = lambda *_a: 0
    try:
        app._register_all()
    finally:
        win32.user32.RegisterHotKey = old_register

    assert app._failures == [], app._failures
    indexes = {b.index for b in captured.get("bindings", [])}
    assert entry.index in indexes, indexes
    assert ID_SUSPEND in indexes, indexes
    suspend_entry = app._entries_by_index[ID_SUSPEND]
    assert (suspend_entry.action, suspend_entry.value) == ("app", "suspend")
    return "2 native fallbacks"


def _test_editor_trigger_roundtrip() -> str:
    """Reopening/saving a hold/double/tap entry must keep its trigger."""
    import tkinter as tk

    from . import gui

    class DummyApp:
        def profile_names(self):
            return []

        def pause_hotkeys(self, *_args, **_kwargs):
            return None

    class DummyOwner:
        def __init__(self):
            self.root = tk.Tk()
            self.root.withdraw()
            self.root.wait_window = lambda *_a, **_k: None
            self.pal = gui._palette()
            self.scale = 1.0
            self.lang = "en"
            self.app = DummyApp()
            self.entries = []

    for trigger in ("press", "hold", "double", "tap"):
        owner = DummyOwner()
        try:
            entry = config.Entry(
                keys="Mouse5", action="keys", value="ctrl+a",
                description="copy all", trigger=trigger, index=0,
                mods=0, vks=(6,), vk=6)
            editor = gui.Editor(owner, entry)
            expected = gui._trigger_label(trigger, editor.t)
            shown = editor.var_trigger.get()
            assert shown == expected, (trigger, shown, expected)
            choices = tuple(editor.cmb_trigger.cget("values"))
            assert gui._trigger_label("tap", editor.t) in choices, choices
            editor._save()
            assert editor.result is not None, trigger
            assert editor.result.trigger == trigger, (
                trigger, editor.result.trigger)
        finally:
            try:
                owner.root.destroy()
            except Exception:
                pass
    return "hold/double/tap preserved"


def _test_silent_startup() -> str:
    """A legacy start_with_window=true must never open the settings UI."""
    from .app import App

    app = App.__new__(App)
    app.path = ""
    app.use_tray = False
    app.hwnd = 0
    app.engine = None
    app._by_id = {}
    app._failures = []
    app.cfg = config.Config(path="")
    app.cfg.settings["start_with_window"] = True
    app.cfg.settings["notify_on_start"] = False

    calls: list[str] = []
    opened: list[bool] = []
    app._create_window = lambda: calls.append("window")
    app.load = lambda initial: calls.append(f"load:{initial}")
    app._register_all = lambda: calls.append("register")
    app._update_tray = lambda: calls.append("tray")
    app._schedule_update_check = lambda _delay: calls.append("update")
    app.open_settings = lambda: opened.append(True)
    app.notify = lambda *_a, **_k: calls.append("notify")
    app._loop = lambda: 0

    old_set_timer = win32.user32.SetTimer
    win32.user32.SetTimer = lambda *_a: 1
    try:
        assert app.start() == 0
    finally:
        win32.user32.SetTimer = old_set_timer
    assert opened == [], "settings window opened during startup"
    assert "load:True" in calls and "register" in calls, calls
    return "tray-only startup, legacy key ignored"


def run(config_path: str, full: bool = False) -> int:
    print("Hotkey self-test")
    print(f"  python      {sys.version.split()[0]}")
    print(f"  config      {config_path}")
    results = Results()
    results.check("hotkey parsing", _test_keys)
    results.check("text tokens", _test_tokens)
    results.check("run action", _test_run_command)
    results.check("topmost window API", _test_topmost_api)
    results.check("pin window action", _test_pin_action)
    results.check("config round-trip", _test_config)
    results.check("language settings", _test_language)
    results.check("icon generation", _test_icon)
    results.check("OS hotkey dispatch", _test_hotkey_dispatch)
    results.check("trigger engine (chord/tap/hold)", _test_engine)
    results.check("trigger audit regressions", _test_audit_fixes)
    results.check("per-app scope", _test_app_scope)
    results.check("leader sequences", _test_sequence)
    results.check("profiles", _test_profiles)
    results.check("macro control", _test_macro_control)
    results.check("power schedule", _test_power_actions)
    results.check("suspend power API", _test_suspend_power_api)
    results.check("restart power API", _test_restart_api)
    results.check("injected mouse clicks", _test_injected_clicks)
    results.check("native hotkey fallback", _test_native_fallback)
    results.check("editor trigger round-trip", _test_editor_trigger_roundtrip)
    results.check("silent startup", _test_silent_startup)
    results.check("validation + safe macro keys", _test_validation)
    results.check("update checker", _test_update)
    results.check("gear update status", _test_update_status)
    results.check("foreground app detection", _test_foreground)
    if full:
        results.check("clipboard (modifies + restores)", _test_clipboard)
    else:
        print("  SKIP  clipboard (pass --full to test, it briefly replaces it)")
    print()
    if results.failed:
        print(f"{results.failed} test(s) FAILED")
        return 1
    print("All good.")
    return 0
