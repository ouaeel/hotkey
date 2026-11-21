"""The action engine: what a hotkey actually does."""
from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime

from . import keys, win32

log = logging.getLogger("hotkey")

# Keep "run" commands from flashing a console window on Windows.
CREATE_NO_WINDOW = 0x08000000

_MACRO_LOCK = threading.Lock()

MEDIA_OPS = {
    "play_pause": 0xB3, "playpause": 0xB3, "next": 0xB0, "prev": 0xB1,
    "previous": 0xB1, "stop": 0xB2,
    "volume_up": 0xAF, "vol_up": 0xAF, "louder": 0xAF,
    "volume_down": 0xAE, "vol_down": 0xAE, "quieter": 0xAE,
    "mute": 0xAD,
}

WINDOW_OPS = ["left", "right", "top", "bottom", "maximize", "minimize",
              "restore", "center", "topmost", "close"]

SYSTEM_OPS = ["lock", "sleep", "screenshot", "recycle", "taskmanager"]

APP_OPS = ["settings", "reload", "suspend", "config", "log", "quit"]


class ActionError(RuntimeError):
    """A user-facing action failure."""


@dataclass(frozen=True)
class Spec:
    label: str
    field: str = ""
    hint: str = ""
    options: tuple[str, ...] = ()


SPECS: dict[str, Spec] = {
    "open": Spec(
        "Open app, file, folder or URL", "Target",
        "notepad.exe, %USERPROFILE%\\Desktop, https://example.com",
    ),
    "run": Spec(
        "Run command (no window)", "Command line",
        "python -m http.server 8000  (optional: cwd)",
    ),
    "type": Spec(
        "Type text into the active app", "Text",
        "Hello {user}! Today is {date}.  Tokens: {clip} {time} {newline} {tab}",
    ),
    "keys": Spec(
        "Send keystrokes", "Keys",
        "ctrl+v  or  ctrl+a, delete  (comma = sequence)",
    ),
    "clip": Spec(
        "Copy text to clipboard", "Text",
        "Copied at {time} from {computer}",
    ),
    "paste": Spec(
        "Type the clipboard as plain text", "",
        "Works in terminals, RDP and apps that block Ctrl+V",
    ),
    "media": Spec("Media / volume key", "Operation", options=tuple(MEDIA_OPS)),
    "window": Spec("Window control", "Operation", options=tuple(WINDOW_OPS)),
    "system": Spec("System command", "Operation", options=tuple(SYSTEM_OPS)),
    "app": Spec("Hotkey app command", "Operation", options=tuple(APP_OPS)),
    "summon": Spec(
        "Summon / toggle a window", "App",
        "chrome.exe, notepad.exe — focuses, minimizes or launches it",
    ),
    "macro": Spec(
        "Play a recorded macro", "Steps",
        "Recorded in the editor; keys only, with timing",
    ),
    "profile": Spec(
        "Switch hotkey profile", "Profile",
        "Work, Gaming, or 'next' to cycle",
    ),
}

_TOKEN = re.compile(
    r"\{(date|time|datetime|now|day|user|computer|uuid|clip|newline|tab)(?::([^}]*))?\}")

def expand_tokens(text: str) -> str:
    if "{" not in text:
        return text
    now = datetime.now()

    def repl(match: re.Match) -> str:
        name, fmt = match.group(1), match.group(2)
        if name == "newline":
            return "\n"
        if name == "tab":
            return "\t"
        if name == "clip":
            return win32.get_clipboard()
        if name == "user":
            return os.environ.get("USERNAME", "")
        if name == "computer":
            return os.environ.get("COMPUTERNAME", "")
        if name == "uuid":
            return str(uuid.uuid4())
        if name == "day":
            return now.strftime(fmt or "%A")
        if name in ("date", "time", "datetime", "now"):
            default = {"date": "%Y-%m-%d", "time": "%H:%M",
                       "datetime": "%Y-%m-%d %H:%M", "now": "%Y-%m-%d %H:%M:%S"}[name]
            return now.strftime(fmt or default)
        return match.group(0)

    return _TOKEN.sub(repl, text)


def _snap(hwnd: int, op: str) -> None:
    left, top, right, bottom = win32.get_work_area()
    width, height = right - left, bottom - top
    _x, _y, w, h = win32.window_rect(hwnd)
    if op == "left":
        win32.move_window(hwnd, left, top, width // 2, height)
    elif op == "right":
        win32.move_window(hwnd, left + width // 2, top, width - width // 2, height)
    elif op == "top":
        win32.move_window(hwnd, left, top, width, height // 2)
    elif op == "bottom":
        win32.move_window(hwnd, left, top + height // 2, width, height - height // 2)
    elif op == "maximize":
        win32.show_window(hwnd, win32.SW_MAXIMIZE)
    elif op == "minimize":
        win32.show_window(hwnd, win32.SW_MINIMIZE)
    elif op == "restore":
        win32.show_window(hwnd, win32.SW_RESTORE)
    elif op == "topmost":
        win32.toggle_topmost(hwnd)
    elif op == "close":
        win32.user32.PostMessageW(win32.HWND(hwnd), win32.WM_CLOSE, 0, 0)


def _center(hwnd: int) -> None:
    left, top, right, bottom = win32.get_work_area()
    x, y, w, h = win32.window_rect(hwnd)
    win32.move_window(hwnd, left + max(0, (right - left - w) // 2),
                      top + max(0, (bottom - top - h) // 2), w, h)


def _send_keys(value: str, delay_ms: int = 40) -> None:
    for part in [p.strip() for p in value.split(",") if p.strip()]:
        try:
            mods, vk = keys.parse(part)
        except keys.HotkeyError as exc:
            raise ActionError(str(exc)) from exc
        win32.send_combo(mods, vk)
        if delay_ms:
            time.sleep(delay_ms / 1000)


def _run_command(command: str, cwd: str | None) -> None:
    if not command.strip():
        raise ActionError("empty command")
    subprocess.Popen(command, shell=True, cwd=cwd or None,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW,
                     close_fds=True)


def _open_target(target: str) -> None:
    target = os.path.expandvars(os.path.expanduser(target))
    if not target:
        raise ActionError("nothing to open")
    win32.open_target(target)


def run(entry, ctx, prepare_only: bool = False) -> str:
    """Execute one hotkey action. Raises ActionError with a friendly message.

    ``prepare_only`` is used when a *hotkey* starts a macro: the steps are
    loaded into the control window but playback waits for its Run button.
    """
    action = entry.action
    value = entry.value or ""
    settings = ctx.settings

    if action == "open":
        target = os.path.expandvars(os.path.expanduser(value))
        try:
            _open_target(value)
        except OSError as exc:
            fallback = entry.extra.get("fallback")
            if fallback:
                try:
                    _open_target(str(fallback))
                    return f"opened {fallback}"
                except OSError:
                    pass
            raise ActionError(f"cannot open {target or value!r}: {exc.strerror or exc}") from exc
        return f"opened {target}"

    if action == "run":
        _run_command(value, entry.extra.get("cwd"))
        return "command started"

    if action == "type":
        text = expand_tokens(value)
        win32.send_text(text, int(settings.get("typing_delay_ms", 2)))
        return f"typed {len(text)} chars"

    if action == "keys":
        _send_keys(value, int(entry.extra.get("delay_ms", 40)))
        return f"sent {value}"

    if action == "clip":
        text = expand_tokens(value)
        if not win32.set_clipboard(text):
            raise ActionError("clipboard is busy, try again")
        if entry.extra.get("paste"):
            time.sleep(0.03)
            win32.send_combo(keys.MOD_CONTROL, 0x56)
            return "copied + pasted"
        return f"copied {len(text)} chars"

    if action == "paste":
        text = win32.get_clipboard()
        if not text:
            raise ActionError("clipboard is empty")
        win32.send_text(text, int(settings.get("typing_delay_ms", 2)))
        return f"pasted {len(text)} chars"

    if action == "media":
        vk = MEDIA_OPS.get(value.lower())
        if vk is None:
            raise ActionError(f"unknown media operation {value!r}")
        times = int(entry.extra.get("repeat", 2 if "volume" in value.lower() else 1))
        for _ in range(max(1, min(50, times))):
            win32.send_vk(vk)
            win32.send_vk(vk, up=True)
            time.sleep(0.02)
        return f"media {value}"

    if action == "window":
        hwnd = win32.foreground()
        if not hwnd:
            raise ActionError("no active window")
        op = value.lower()
        if op == "center":
            _center(hwnd)
        elif op in WINDOW_OPS:
            _snap(hwnd, op)
        else:
            raise ActionError(f"unknown window operation {value!r}")
        return f"window {op}"

    if action == "system":
        op = value.lower()
        if op == "lock":
            win32.lock_workstation()
        elif op == "sleep":
            win32.suspend_pc()
        elif op == "screenshot":
            win32.open_target("ms-screenclip:")
        elif op == "recycle":
            win32.empty_recycle_bin()
        elif op == "taskmanager":
            _run_command("taskmgr.exe", None)
        else:
            raise ActionError(f"unknown system operation {value!r}")
        return f"system {op}"

    if action == "app":
        op = value.lower()
        handlers = {
            "settings": ctx.open_settings,
            "reload": ctx.reload,
            "suspend": ctx.toggle_suspend,
            "config": ctx.open_config,
            "log": ctx.open_log,
            "quit": ctx.quit,
        }
        handler = handlers.get(op)
        if handler is None:
            raise ActionError(f"unknown app operation {value!r}")
        handler()
        return f"app {op}"

    if action == "summon":
        try:
            what = win32.summon_app(value)
        except OSError as exc:
            raise ActionError(f"cannot summon {value!r}: {exc}") from exc
        return f"summoned {value} ({what})"

    if action == "profile":
        setter = getattr(ctx, "set_profile", None)
        if not callable(setter):
            raise ActionError("profile switching is unavailable")
        return str(setter(value))

    if action == "macro_start":
        control = getattr(ctx, "macro", None)
        if control is None:
            raise ActionError("macro control is unavailable")
        if control.snapshot()["running"]:
            raise ActionError("a macro is already running")
        target = getattr(control, "last_entry", None)
        if target is None:
            entries = getattr(getattr(ctx, "cfg", None), "entries", ())
            target = next((e for e in entries if e.action == "macro"
                           and e.enabled), None)
        if target is None:
            raise ActionError("no macro is loaded — press a macro hotkey first")
        return run(target, ctx)

    if action == "macro_stop":
        control = getattr(ctx, "macro", None)
        if control is None:
            raise ActionError("macro control is unavailable")
        control.cancel()
        return "macro stopped"

    if action == "macro":
        steps = entry.extra.get("steps") or []
        if not isinstance(steps, list) or not steps:
            raise ActionError("macro has no recorded steps")
        control = getattr(ctx, "macro", None)
        if control is None:
            from . import macro as _macro
            control = _macro.MacroControl()
        saved_speed = entry.extra.get("speed", 1.0)

        # Loading a macro into the control window must not take the playback
        # lock - only actual playback does, and the worker releases it.
        if prepare_only:
            control.prepare(steps, entry.display, entry=entry, speed=saved_speed)
            return f"macro ready ({len(steps)} steps)"

        if not _MACRO_LOCK.acquire(blocking=False):
            raise ActionError("a macro is already running")

        def worker() -> None:
            cancelled = False
            run = 0
            try:
                control.begin(
                    steps, entry.display, entry=entry,
                    speed=None if getattr(control, "speed_touched", False) else saved_speed,
                )
                # ``repeat_count`` is re-read every iteration: changing Times
                # in the control box really does affect the current playback.
                while run < control.repeat_count():
                    if control.stopping():
                        break
                    run += 1
                    for index, step in enumerate(steps, 1):
                        # Cancel aborts at once. Stop only takes effect at the
                        # run boundary, so the current run finishes properly.
                        if control.aborted():
                            cancelled = True
                            break
                        control.progress(run, index)
                        speed = control.value()
                        if isinstance(step, dict):
                            keys_text = str(step.get("keys", "")).strip()
                            wait = step.get("wait", step.get("delay", 40))
                            hold = step.get("hold", 30)
                        else:
                            keys_text = str(step).strip()
                            wait, hold = 40, 30
                        try:
                            wait = float(wait)
                            hold = float(hold)
                        except (TypeError, ValueError):
                            wait, hold = 40.0, 30.0
                        if wait > 0:
                            time.sleep(min(wait, 250.0) / 1000.0 / speed)
                        if control.aborted():
                            cancelled = True
                            break
                        mouse_button = step.get("mouse") if isinstance(step, dict) else None
                        if mouse_button:
                            x = int(step.get("x", 0))
                            y = int(step.get("y", 0))
                            x2 = int(step.get("x2", x))
                            y2 = int(step.get("y2", y))
                            win32.move_mouse_human(x, y, 260.0 / speed)
                            win32.send_mouse(str(mouse_button), True)
                            if hold > 0:
                                time.sleep(min(hold, 500.0) / 1000.0 / speed)
                            if (x2, y2) != (x, y):
                                win32.move_mouse_human(x2, y2, 180.0 / speed)
                            win32.send_mouse(str(mouse_button), False)
                        elif keys_text:
                            try:
                                mods, vks = keys.parse_all(keys_text)
                            except keys.HotkeyError as exc:
                                raise ActionError(str(exc)) from exc
                            win32.send_combo_many(mods, vks, int(hold))
                    if cancelled or control.stopping():
                        break
            except Exception as exc:  # noqa: BLE001 - report to the user
                log.exception("macro playback failed")
                if not control.aborted():
                    try:
                        ctx.notify(f"{entry.display} failed", str(exc),
                                   error=True, force=True)
                    except Exception:
                        pass
            finally:
                control.finish()
                _MACRO_LOCK.release()

        threading.Thread(target=worker, name="macro", daemon=True).start()
        return f"macro ({len(steps)} steps)"

    raise ActionError(f"unknown action {action!r}")
