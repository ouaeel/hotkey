"""Built-in diagnostics: python Hotkey.pyw --self-test [--full]"""
from __future__ import annotations

import ctypes
import logging
import os
import queue
import sys
import tempfile
import time

from . import actions, config, i18n, icon, keys, macro, win32


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
    return "chord + tap + hold"


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


def run(config_path: str, full: bool = False) -> int:
    print("Hotkey self-test")
    print(f"  python      {sys.version.split()[0]}")
    print(f"  config      {config_path}")
    results = Results()
    results.check("hotkey parsing", _test_keys)
    results.check("text tokens", _test_tokens)
    results.check("run action", _test_run_command)
    results.check("config round-trip", _test_config)
    results.check("language settings", _test_language)
    results.check("icon generation", _test_icon)
    results.check("OS hotkey dispatch", _test_hotkey_dispatch)
    results.check("trigger engine (chord/tap/hold)", _test_engine)
    results.check("per-app scope", _test_app_scope)
    results.check("leader sequences", _test_sequence)
    results.check("profiles", _test_profiles)
    results.check("macro control", _test_macro_control)
    results.check("validation + safe macro keys", _test_validation)
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
