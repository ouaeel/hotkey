"""Hotkey: a tiny, zero-dependency global hotkey manager for Windows.

Design notes
------------
* Hotkeys are registered with the OS (RegisterHotKey). No keyboard hooks, no
  polling, no background CPU: the process sleeps in GetMessage() until Windows
  wakes it up.
* The tray icon talks to the same hidden window, so there is exactly one
  message loop and one thread (the GUI opens in a throwaway thread only when
  the user asks for it).
* Config edits are picked up from disk automatically.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import logging
import os
import queue
import signal
import sys
import threading
import time
import winreg

from logging.handlers import RotatingFileHandler

from . import actions, config, hooks, i18n, icon, keys, macro, update, win32
from . import __version__

APP_NAME = "Hotkey"
APP_ID = "hotkey.tray.1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WM_TRAY = win32.WM_APP + 1
WM_RELOAD = win32.WM_APP + 2
WM_SETTINGS = win32.WM_APP + 3
WM_QUIT_APP = win32.WM_APP + 4
WM_HOOK_FIRE = win32.WM_APP + 6
WM_PAUSE = win32.WM_APP + 7
WM_MACROKEY = win32.WM_APP + 8
WM_UPDATE = win32.WM_APP + 9
WM_UPDATE_CHECK = win32.WM_APP + 10

TIMER_WATCH = 1
TIMER_HOLD = 2
TIMER_UPDATE = 3
UPDATE_FIRST_DELAY_MS = 10000
TRAY_UID = 1
# Only the two side buttons are ever eaten by the mouse hook. Swallowing a
# left/right/middle click (which a chord like "Mouse5+MouseLeft" used to do)
# leaves Windows with no click at all, which looks like a dead mouse.
SWALLOWABLE_MOUSE = frozenset((0x05, 0x06))
# A side button that is also part of a chord fires its own hotkey on
# release, inside this window, so the chord can cancel it. Keep the window
# generous: holding a side button for five seconds is not unusual.
CHORD_TAP_MS = 30000
HOTKEY_BASE = 100
ID_SUSPEND = 90

CMD_SETTINGS = 2000
CMD_RELOAD = 2001
CMD_CONFIG = 2002
CMD_AUTOSTART = 2003
CMD_SUSPEND = 2004
CMD_LOG = 2005
CMD_QUIT = 2006
CMD_MACRO = 2007
CMD_UPDATE = 2008
CMD_RELEASES = 2009
CMD_PROFILE_BASE = 3000

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "Hotkey"

log = logging.getLogger("hotkey")


def data_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.join(ROOT, "build")
    path = os.path.join(base, APP_NAME)
    try:
        os.makedirs(path, exist_ok=True)
        return path
    except OSError:
        fallback = os.path.join(ROOT, "build")
        os.makedirs(fallback, exist_ok=True)
        return fallback


class App:
    def __init__(self, config_path: str, use_tray: bool = True):
        self.path = os.path.abspath(config_path)
        self.use_tray = use_tray
        self.hwnd: int = 0
        self.cfg = config.Config(path=self.path)
        self.suspended = False
        self._paused = False
        self._registered: set[int] = set()
        self._by_id: dict[int, config.Entry] = {}
        self._failures: list[str] = []
        self._wndproc_ref = None
        self._icon_active = 0
        self._icon_paused = 0
        self._gui_open = False
        self._last_error = 0.0
        self._started = time.time()
        self._class_atom = 0
        self.hook = None
        self.mouse_hook = None
        self.engine = None
        self._swallowed: set[int] = set()
        self._entries_by_index: dict[int, config.Entry] = {}
        # Config writes requested from the settings/macro-panel Tk threads are
        # marshalled through this queue onto the single Win32 message loop.
        self._config_queue: queue.Queue = queue.Queue()
        # Recent hotkey fires, drained by the settings window to flash its row.
        # Bounded so a closed window cannot accumulate events forever.
        self.fire_events: queue.Queue[int] = queue.Queue(maxsize=1)
        # Update checks run in short-lived daemon threads and report back by
        # posting a message, keeping the main loop single-threaded.
        self._update_info: update.UpdateInfo | None = None
        self._update_manual = False
        self._update_busy = False
        # Status snapshots for the gear window.  The Tk thread drains this
        # queue on a short timer; nothing blocks the Win32 loop.
        self.update_events: queue.Queue[dict] = queue.Queue(maxsize=4)
        self._update_state: dict = {
            "state": "idle", "version": "", "message": "Not checked yet",
            "kwargs": {}, "url": self._releases_url(),
        }
        self.macro = macro.MacroControl()
        self.macro.on_show = self.show_macro_panel
        self._macro_panel = None

    # -- small conveniences used by the action engine / GUI -------------------
    @property
    def settings(self) -> dict:
        return self.cfg.settings

    def t(self, text: str, **kwargs: object) -> str:
        """Translate a UI string using the currently loaded language."""
        return i18n.tr(text, self.cfg.settings.get("language", "en"), **kwargs)

    @property
    def active_count(self) -> int:
        """Native registrations plus hook (chord/hold/mouse/per-app) bindings."""
        hooked = len(self.engine.bindings) if self.engine is not None else 0
        return len(self._by_id) + hooked

    def quit(self) -> None:
        self.request_quit()

    # -- lifecycle -----------------------------------------------------------
    def start(self) -> int:
        self._create_window()
        if self.use_tray:
            self._tray_init()
        self.load(initial=True)
        self._register_all()
        self._update_tray()
        win32.user32.SetTimer(win32.HWND(self.hwnd), TIMER_WATCH, 2500, None)
        self._schedule_update_check(UPDATE_FIRST_DELAY_MS)
        log.info("running: %d hotkeys, config=%s", self.active_count, self.path)
        if self._failures:
            log.warning("%d hotkey(s) unavailable", len(self._failures))
        elif self.cfg.settings.get("notify_on_start"):
            self.notify(APP_NAME, self.t(
                "{count} hotkeys active. Double-click the tray icon to edit them.",
                count=self.active_count))
        return self._loop()

    def _create_window(self) -> None:
        hinst = win32.kernel32.GetModuleHandleW(None)
        wc = win32.WNDCLASSW()
        wc.lpfnWndProc = win32.WNDPROC(self._wndproc)
        wc.hInstance = hinst
        wc.lpszClassName = "HotkeyMainWindow"
        wc.hIcon = win32.HICON(self._icon(active=True))
        self._wndproc_ref = wc  # keep the callback alive
        atom = win32.user32.RegisterClassW(ctypes.byref(wc))
        if not atom and ctypes.get_last_error() not in (0, 1410):
            raise OSError(ctypes.get_last_error(), "RegisterClassW failed")
        self._class_atom = atom
        self.hwnd = int(win32.user32.CreateWindowExW(
            0, "HotkeyMainWindow", APP_NAME, 0, 0, 0, 0, 0, None, None, hinst, None))
        if not self.hwnd:
            raise OSError(ctypes.get_last_error(), "CreateWindowExW failed")

    # -- icon ----------------------------------------------------------------
    def _icon(self, active: bool) -> int:
        if self._icon_active == 0:
            try:
                active_path, paused_path = icon.ensure_icon(data_dir())
                self._icon_active = win32.load_icon(active_path)
                self._icon_paused = win32.load_icon(paused_path)
            except Exception:  # pragma: no cover - cosmetic only
                log.exception("icon generation failed, using stock icon")
                self._icon_active = win32.load_icon(None)
                self._icon_paused = self._icon_active
        if active:
            return self._icon_active
        return self._icon_paused or self._icon_active

    def _tray_init(self) -> None:
        try:
            if not win32.tray_add(self.hwnd, TRAY_UID, self._icon(True),
                                  self._tooltip(), WM_TRAY):
                log.warning("tray icon not created (error %s)", ctypes.get_last_error())
        except Exception:  # pragma: no cover
            log.exception("tray icon could not be created")

    def _update_tray(self) -> None:
        if not self.use_tray:
            return
        try:
            win32.tray_update(self.hwnd, TRAY_UID,
                              self._icon(not self.suspended), self._tooltip())
        except Exception:  # pragma: no cover
            pass

    def _tooltip(self) -> str:
        state = (self.t("paused") if self.suspended
                 else self.t("{count} hotkeys active", count=self.active_count))
        return f"{APP_NAME} - {state}"

    # -- config --------------------------------------------------------------
    def load(self, initial: bool = False) -> bool:
        fresh = config.load(self.path)
        if fresh.errors:
            for err in fresh.errors:
                log.error("config: %s", err)
            if not initial:
                self.notify(self.t("Config problem"), fresh.errors[0],
                            error=True, force=True)
            try:
                self.cfg.mtime = os.stat(self.path).st_mtime_ns
            except OSError:
                pass
            return False
        self.cfg = fresh
        self._entries_by_index = {e.index: e for e in fresh.entries}
        for warn in fresh.warnings:
            log.warning("config: %s", warn)
        if initial:
            log.info("config loaded: %d hotkeys", len(fresh.entries))
        return True

    def reload(self) -> None:
        log.info("reload requested")
        if not self.load():
            return
        self._register_all()
        self._update_tray()
        if not self._failures:
            self.notify(APP_NAME, self.t(
                "Reloaded: {count} hotkeys active", count=self.active_count))

    def profile_names(self) -> list[str]:
        return list(config.profile_names(self.cfg.entries))

    def set_profile(self, name: str) -> str:
        name = str(name or "").strip()
        profiles = self.profile_names()
        if name.lower() in ("", "none", "off"):
            name = ""
        elif name.lower() in ("next", "cycle"):
            if not profiles:
                return "no profiles defined"
            current = self.cfg.active_profile
            idx = next((i for i, p in enumerate(profiles)
                        if p.casefold() == current.casefold()), -1)
            name = profiles[(idx + 1) % len(profiles)]
        else:
            match = next((p for p in profiles
                          if p.casefold() == name.casefold()), None)
            if match is not None:
                name = match
        raw = dict(self.cfg.raw or {})
        if name:
            raw["active_profile"] = name
        else:
            raw.pop("active_profile", None)
        try:
            config.save_raw(self.path, raw)
        except OSError as exc:
            self.notify(self.t("Cannot save"), str(exc), error=True, force=True)
            return f"profile switch failed: {exc}"
        self.load()
        self._register_all()
        self._update_tray()
        label = name or "none"
        self.notify(APP_NAME, self.t("Profile: {name}", name=label))
        return f"profile {label}"

    def _control_entries(self) -> list[config.Entry]:
        """Turn the chosen start/stop combos into ordinary bindings."""
        out: list[config.Entry] = []
        for setting, action, label, index in (
            ("macro_start_hotkey", "macro_start", "Macro start key", 1000),
            ("macro_stop_hotkey", "macro_stop", "Macro stop key", 1001),
        ):
            combo = str(self.cfg.settings.get(setting) or "").strip()
            if not combo:
                continue
            try:
                # Same safety rule as ordinary hotkeys: a bare letter/arrow
                # would hijack normal typing/navigation globally. Mouse
                # buttons, F13-F24 and media keys are deliberately allowed.
                mods, vks = keys.parse_all(combo)
            except keys.HotkeyError as exc:
                log.warning("invalid %s (%r): %s", setting, combo, exc)
                continue
            if len(vks) != 1:
                continue
            out.append(config.Entry(
                keys=keys.format_many(mods, vks), action=action,
                description=label, enabled=True, mods=mods,
                vk=vks[0], vks=vks, index=index,
            ))
        return out

    def set_macro_key(self, which: str, combo: str) -> bool:
        """Validate a chosen start/stop combo and queue it for the main loop.

        Called from the macro-panel Tk thread; it must never touch the shared
        config or call RegisterHotKey directly.
        """
        setting = "macro_start_hotkey" if which == "start" else "macro_stop_hotkey"
        combo = str(combo or "").strip()
        if combo:
            try:
                keys.parse_all(combo)
            except keys.HotkeyError as exc:
                log.warning("macro key not set (%s): %s", setting, exc)
                return False
        self._config_queue.put(("macro_key", setting, combo))
        try:
            win32.user32.PostMessageW(win32.HWND(self.hwnd), WM_MACROKEY, 0, 0)
        except Exception:
            log.exception("could not queue macro key change")
        return True

    def _apply_config_requests(self) -> None:
        """Run queued config writes on the single Win32 message-loop thread."""
        changed = False
        while True:
            try:
                item = self._config_queue.get_nowait()
            except queue.Empty:
                break
            if not isinstance(item, tuple) or item[0] != "macro_key":
                continue
            _tag, setting, combo = item
            raw = dict(self.cfg.raw or {})
            try:
                with open(self.path, "r", encoding="utf-8") as fh:
                    disk = json.load(fh)
                if isinstance(disk, dict):
                    raw = disk
            except (OSError, json.JSONDecodeError):
                pass
            settings = dict(raw.get("settings") or {})
            settings[setting] = combo
            raw["settings"] = settings
            try:
                config.save_raw(self.path, raw)
            except OSError as exc:
                log.error("could not save %s: %s", setting, exc)
                continue
            changed = True
        if changed:
            self.load()
            self._register_all()
            self._update_tray()

    def _register_all(self) -> None:
        self._unregister_all()
        self._stop_hook()
        self._failures = []
        if self._paused:
            return
        suspend = str(self.cfg.settings.get("suspend_hotkey") or "").strip()
        if suspend:
            try:
                mods, vk = keys.parse(suspend)
                if win32.user32.RegisterHotKey(win32.HWND(self.hwnd), ID_SUSPEND,
                                               mods | keys.MOD_NOREPEAT, vk):
                    self._registered.add(ID_SUSPEND)
                else:
                    self._failures.append(f"{keys.pretty(suspend)} (suspend hotkey in use)")
            except keys.HotkeyError as exc:
                self._failures.append(str(exc))
        if self.suspended:
            return

        native: list[config.Entry] = []
        bindings: list = []
        mouse_bindings: list = []
        seen: set[tuple[int, frozenset[int], str, tuple[str, ...]]] = set()
        seen_actions: dict[tuple, config.Entry] = {}
        entries = [e for e in self.cfg.entries
                   if config.entry_is_active(e, self.cfg.active_profile)]
        extras = self._control_entries()
        entries += extras
        for entry in extras:
            self._entries_by_index[entry.index] = entry
        # When a global and a profile-tagged entry share the same combo, the
        # profile-specific one wins for that profile. Sorting first also makes
        # the "preferred" choice below deterministic.
        entries.sort(key=lambda e: (not e.profiles, e.index))
        preferred: dict[tuple, config.Entry] = {}

        def overlap_key(entry: config.Entry) -> tuple:
            return (entry.mods, frozenset(entry.vks), entry.trigger,
                    entry.apps, entry.seq)

        for entry in entries:
            key = overlap_key(entry)
            old = preferred.get(key)
            if old is None or len(entry.profiles) > len(old.profiles):
                preferred[key] = entry
        chord_vks: set[int] = set()
        for entry in entries:
            if entry.enabled and len(entry.vks) > 1:
                chord_vks.update(entry.vks)

        def needs_hook(entry: config.Entry) -> bool:
            return bool(entry.apps) or any(
                keys.is_mouse_vk(vk) for vk in entry.vks
            ) or len(entry.vks) > 1 or entry.trigger != "press" or bool(entry.seq)

        hooked_combos = {
            (e.mods, frozenset(e.vks)) for e in entries
            if e.enabled and needs_hook(e)
        }

        for entry in entries:
            if not entry.enabled:
                continue
            if preferred.get(overlap_key(entry)) is not entry:
                # A more profile-specific entry owns this physical combo.
                continue
            sig = (entry.mods, frozenset(entry.vks), entry.trigger, entry.apps, entry.seq)
            if sig in seen:
                self._failures.append(f"{entry.display} is duplicated")
                continue
            seen.add(sig)
            act = (entry.mods, frozenset(entry.vks), entry.trigger,
                   entry.action, entry.value.strip(), entry.apps, entry.seq,
                   entry.profiles)
            if act in seen_actions:
                other = seen_actions[act]
                self._failures.append(
                    f"{entry.display} already does the same action as "
                    f"\"{other.label()}\"")
                continue
            seen_actions[act] = entry
            mouse = any(keys.is_mouse_vk(vk) for vk in entry.vks)
            # RegisterHotKey cannot filter by app, and a native hotkey would
            # swallow the combo everywhere.  Anything scoped therefore goes
            # through the hook, and so does a global entry sharing its combo.
            shared = (entry.mods, frozenset(entry.vks)) in hooked_combos
            if needs_hook(entry) or shared:
                try:
                    from .hooks import Binding
                    trigger = entry.trigger if len(entry.vks) == 1 else "press"
                    hold_ms = int(entry.extra.get(
                        "hold_ms", self.cfg.settings.get("hold_ms", 400)))
                    if (mouse and len(entry.vks) == 1 and entry.vk in chord_vks
                            and trigger == "press"):
                        # This button also starts a chord: wait for the release
                        # so the chord can cancel it instead of both actions
                        # running on the same press.
                        trigger = "tap"
                        hold_ms = max(hold_ms, CHORD_TAP_MS)
                    binding = Binding(
                        index=entry.index, mods=entry.mods, vks=entry.vks,
                        trigger=trigger, hold_ms=hold_ms,
                        apps=frozenset(entry.apps),
                        seq=entry.seq,
                    )
                    (mouse_bindings if mouse else bindings).append(binding)
                except Exception:
                    self._failures.append(f"{entry.display}: bad hook entry")
            else:
                native.append(entry)

        for entry in native:
            hid = HOTKEY_BASE + entry.index
            if win32.user32.RegisterHotKey(win32.HWND(self.hwnd), hid,
                                           entry.mods | keys.MOD_NOREPEAT, entry.vk):
                self._registered.add(hid)
                self._by_id[hid] = entry
            else:
                self._failures.append(self.t(
                    "{name} is already used by another app", name=entry.display))

        if bindings or mouse_bindings:
            self._start_hook(bindings, mouse_bindings)

        for failure in self._failures:
            log.warning("hotkey unavailable: %s", failure)
        if self._failures:
            self.notify(self.t("Some hotkeys are unavailable"),
                        self._failures[0], error=True)

    def _start_hook(self, bindings, mouse_bindings=(), leader_timeout_ms=None) -> None:
        from .hooks import KeyboardHook, MouseHook, TriggerEngine
        if leader_timeout_ms is None:
            leader_timeout_ms = self.cfg.settings.get("leader_timeout_ms", 1200)
        self.engine = TriggerEngine(list(bindings) + list(mouse_bindings),
                                   leader_timeout_ms=leader_timeout_ms)
        if bindings:
            try:
                self.hook = KeyboardHook(self._hook_event)
                if not self.hook.installed:
                    raise RuntimeError("SetWindowsHookEx failed")
                log.info("keyboard hook installed (%d bindings)", len(bindings))
            except Exception as exc:
                log.error("keyboard hook failed: %s", exc)
                self.hook = None
                self.notify(self.t("Long-press/chords disabled"),
                            str(exc), error=True)
        if mouse_bindings:
            try:
                self.mouse_hook = MouseHook(self._hook_event)
                if not self.mouse_hook.installed:
                    raise RuntimeError("SetWindowsHookEx failed")
                log.info("mouse hook installed (%d bindings)", len(mouse_bindings))
            except Exception as exc:
                log.error("mouse hook failed: %s", exc)
                self.mouse_hook = None
                self.notify(self.t("Mouse hotkeys disabled"),
                            str(exc), error=True)

    def _stop_hook(self) -> None:
        for hook in (self.hook, self.mouse_hook):
            if hook is not None:
                try:
                    hook.close()
                except Exception:
                    pass
        self.hook = None
        self.mouse_hook = None
        self.engine = None
        self._swallowed.clear()
        if self.hwnd:
            try:
                win32.user32.KillTimer(win32.HWND(self.hwnd), TIMER_HOLD)
            except Exception:
                pass

    def _hook_event(self, kind: str, vk: int) -> bool:
        """Feed one key/mouse event; True means the event was consumed."""
        if self.engine is None:
            self._swallowed.clear()
            return False
        try:
            mods = win32.current_mods()
            now = time.monotonic()
            app = win32.foreground_app() if self.engine.needs_app(vk) else ""
            fired = (self.engine.feed_down(vk, mods, now, app) if kind == "down"
                     else self.engine.feed_up(vk, now))
            for b in fired:
                self._post_fire(b.index)
            hint = self.engine.take_hint() if kind == "down" else None
            if hint:
                self.notify(self.t("Leader key"), hint)
            self._sync_hold_timer()
            return self._should_swallow(kind, vk, mods)
        except Exception:
            log.exception("hook event failed")
        return False

    def _should_swallow(self, kind: str, vk: int, mods: int) -> bool:
        """Decide whether the mouse hook eats this button event.

        Left/right/middle clicks always pass through, even when they are part
        of a chord: eating them while the app runs is indistinguishable from
        a broken mouse.  A side button is eaten only when a binding really
        uses it (on press, or when its chord is fully held), and its release
        is eaten only if that press was eaten - an unmatched eaten release
        would leave Windows stuck with the button down.
        """
        if vk not in SWALLOWABLE_MOUSE:
            return False
        if kind == "down":
            pressed = self.engine.pressed
            app = win32.foreground_app() if any(
                b.apps for b in self.engine.bindings) else ""
            eat = any(
                vk in b.vks and b.mods == mods
                and (not b.apps or win32.app_matches(b.apps, app))
                and (len(b.vks) == 1 or set(b.vks) <= pressed)
                for b in self.engine.bindings)
            if eat:
                self._swallowed.add(vk)
            return eat
        if vk in self._swallowed:
            self._swallowed.discard(vk)
            return True
        return False

    def _hold_still_down(self, vk: int) -> bool:
        """Still held when a long-press deadline expires?

        For mouse buttons the hook's own press/release events are the
        reliable source: GetAsyncKeyState() does not report the side
        buttons (and a swallowed press never reaches the queue), which is
        why long-press on a mouse button never fired.
        """
        if self.engine is not None and keys.is_mouse_vk(vk):
            return vk in self.engine.pressed
        return win32.is_key_down(vk)

    def _post_fire(self, index: int) -> None:
        try:
            win32.user32.PostMessageW(win32.HWND(self.hwnd), WM_HOOK_FIRE, index, 0)
        except Exception:
            pass

    def note_fire(self, index: int) -> None:
        """Remember a fired hotkey so an open settings window can flash it."""
        try:
            self.fire_events.put_nowait(index)
        except queue.Full:
            pass

    def _on_hook_fire(self, index: int) -> None:
        entry = self._entries_by_index.get(index)
        if entry is None:
            return
        self.note_fire(index)
        self._run_entry(entry, prepare_only=True)

    def _run_entry(self, entry: config.Entry, prepare_only: bool = False) -> None:
        detail = str(entry.value or entry.description or "").strip()
        log.info("hotkey %s -> %s%s", entry.display, entry.action,
                 f" ({detail})" if detail else "")
        try:
            what = actions.run(entry, self, prepare_only=prepare_only)
            log.debug("ok: %s", what)
        except actions.ActionError as exc:
            log.error("%s: %s", entry.display, exc)
            self.notify(self.t("{name} failed", name=entry.display),
                        str(exc), error=True, force=True)
        except Exception as exc:
            log.exception("%s crashed", entry.display)
            self.notify(self.t("{name} failed", name=entry.display),
                        str(exc), error=True, force=True)

    def _sync_hold_timer(self) -> None:
        if self.engine is None:
            return
        dl = self.engine.next_deadline()
        if dl is None:
            try:
                win32.user32.KillTimer(win32.HWND(self.hwnd), TIMER_HOLD)
            except Exception:
                pass
        else:
            try:
                win32.user32.SetTimer(win32.HWND(self.hwnd), TIMER_HOLD, 20, None)
            except Exception:
                pass

    def _unregister_all(self) -> None:
        for hid in list(self._registered):
            try:
                win32.user32.UnregisterHotKey(win32.HWND(self.hwnd), hid)
            except Exception:
                pass
        self._registered.clear()
        self._by_id.clear()

    # -- notifications / paths ----------------------------------------------
    def notify(self, title: str, text: str, error: bool = False, force: bool = False) -> None:
        if not self.use_tray:
            return
        if not force and not self.cfg.settings.get("show_notifications", True):
            return
        if error:
            now = time.time()
            if now - self._last_error < 3.0:
                return
            self._last_error = now
        kind = win32.NIIF_ERROR if error else win32.NIIF_INFO
        try:
            win32.tray_balloon(self.hwnd, TRAY_UID, title, text, kind)
        except Exception:  # pragma: no cover
            pass

    # -- updates --------------------------------------------------------------
    def _schedule_update_check(self, delay_ms: int) -> None:
        if not self.hwnd:
            return
        if not self.cfg.settings.get("update_check", True):
            win32.user32.KillTimer(win32.HWND(self.hwnd), TIMER_UPDATE)
            return
        win32.user32.SetTimer(win32.HWND(self.hwnd), TIMER_UPDATE, delay_ms, None)

    def _publish_update(self, state: str, latest: str = "",
                        message: str = "Not checked yet",
                        **kwargs: object) -> dict:
        """Store one status snapshot and hand it to the gear window."""
        status = {
            "state": state,
            "version": str(latest or ""),
            "message": message,
            "kwargs": dict(kwargs),
            "url": self._releases_url(),
        }
        self._update_state = status
        try:
            self.update_events.put_nowait(status)
        except queue.Full:
            try:
                self.update_events.get_nowait()
            except queue.Empty:
                pass
            try:
                self.update_events.put_nowait(status)
            except queue.Full:
                pass
        return status

    def request_update_check(self, manual: bool = True) -> None:
        """Ask the main loop to check, safe to call from the Tk thread."""
        if not self.hwnd:
            return
        try:
            win32.user32.PostMessageW(
                win32.HWND(self.hwnd), WM_UPDATE_CHECK, 1 if manual else 0, 0)
        except Exception:
            pass

    def update_snapshot(self) -> dict:
        """Current version/status for a window that just opened."""
        status = dict(self._update_state)
        status["current"] = __version__
        status["url"] = self._releases_url()
        return status

    def _check_updates(self, manual: bool = False) -> None:
        if self._update_busy:
            if manual:
                self._publish_update("checking", message="Checking…")
            return
        if not manual and not self.cfg.settings.get("update_check", True):
            return
        self._update_manual = manual
        url = str(self.cfg.settings.get("update_url") or update.DEFAULT_URL)
        token = update.token_from(self.cfg.settings)
        if self.cfg.settings.get("update_private") and not token:
            self._update_manual = False
            log.debug("update check skipped: private repo needs a token")
            self._publish_update(
                "blocked",
                message="Add a GitHub token to check this private repo")
            if manual:
                self.notify(self.t("Check for updates"),
                            self.t("Add a GitHub token to check this private repo"),
                            force=True)
            return
        self._update_busy = True
        self._publish_update("checking", message="Checking…")

        def worker() -> None:
            info = None
            try:
                info = update.check(url, token)
            except Exception as exc:
                log.debug("update check skipped: %s", exc)
                if manual:
                    self._publish_update("error", message="Update check failed")
                return
            finally:
                self._update_busy = False
            if info is not None or manual:
                self._update_info = info
                if info is not None:
                    self._publish_update(
                        "new", latest=info.version,
                        message="Update available: {version}", version=info.version)
                else:
                    self._publish_update("current", message="You are up to date")
                try:
                    win32.user32.PostMessageW(win32.HWND(self.hwnd), WM_UPDATE, 0, 0)
                except Exception:
                    pass

        threading.Thread(target=worker, name="update-check", daemon=True).start()

    def _on_update_result(self) -> None:
        info = self._update_info
        manual = self._update_manual
        self._update_manual = False
        if info is None:
            if manual:
                self.notify(self.t("Check for updates"),
                            self.t("You are up to date"), force=True)
            return
        log.info("update available: %s", info.version)
        self.notify(self.t("Update available"),
                    self.t("Version {version} is available", version=info.version))

    def _releases_url(self) -> str:
        if self._update_info is not None:
            return self._update_info.url
        base = str(self.cfg.settings.get("update_url") or update.DEFAULT_URL)
        if base.rstrip("/").endswith("/releases/latest"):
            return base.rstrip("/")[:-len("/releases/latest")] + "/releases"
        return "https://github.com/ouaeel/hotkey/releases"

    def open_config(self) -> None:
        config.ensure_default(self.path)
        self.open_path(self.path)

    def open_log(self) -> None:
        self.open_path(log_path())

    def open_path(self, target: str) -> None:
        try:
            win32.open_target(target)
        except OSError as exc:
            self.notify(self.t("Cannot open"), str(exc), error=True)

    # -- state toggles -------------------------------------------------------
    def toggle_suspend(self) -> None:
        self.suspended = not self.suspended
        self._register_all()
        self._update_tray()
        state = (self.t("paused - all hotkeys are free for other apps")
                 if self.suspended
                 else self.t("resumed - {count} hotkeys active",
                             count=self.active_count))
        log.info("suspend toggled: %s", state)
        self.notify(APP_NAME, state)

    def request_reload(self) -> None:
        win32.user32.PostMessageW(win32.HWND(self.hwnd), WM_RELOAD, 0, 0)

    def request_settings(self) -> None:
        win32.user32.PostMessageW(win32.HWND(self.hwnd), WM_SETTINGS, 0, 0)

    def pause_hotkeys(self, paused: bool) -> None:
        """Drop or restore every hotkey (used while one is recorded)."""
        win32.user32.PostMessageW(win32.HWND(self.hwnd), WM_PAUSE,
                                  1 if paused else 0, 0)

    def request_quit(self) -> None:
        win32.user32.PostMessageW(win32.HWND(self.hwnd), WM_QUIT_APP, 0, 0)

    def open_settings(self) -> None:
        if self._gui_open:
            return
        self._gui_open = True

        def worker() -> None:
            try:
                from .gui import SettingsWindow
                SettingsWindow(self).run()
            except Exception:
                log.exception("settings window failed")
            finally:
                self._gui_open = False

        threading.Thread(target=worker, name="settings", daemon=True).start()

    # -- autostart -----------------------------------------------------------
    def autostart_enabled(self) -> bool:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                value, _ = winreg.QueryValueEx(key, RUN_VALUE)
                return bool(value)
        except OSError:
            return False

    def autostart_command(self) -> str:
        exe = sys.executable
        if exe.lower().endswith("python.exe"):
            candidate = exe[:-len("python.exe")] + "pythonw.exe"
            if os.path.isfile(candidate):
                exe = candidate
        launcher = os.path.join(ROOT, "Hotkey.pyw")
        if not os.path.isfile(launcher):
            launcher = os.path.abspath(sys.argv[0])
        return f'"{exe}" "{launcher}" --config "{self.path}"'

    def set_autostart(self, enabled: bool) -> None:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            if enabled:
                winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, self.autostart_command())
            else:
                try:
                    winreg.DeleteValue(key, RUN_VALUE)
                except FileNotFoundError:
                    pass
        log.info("autostart %s", "enabled" if enabled else "disabled")

    def toggle_autostart(self) -> None:
        self.set_autostart(not self.autostart_enabled())
        self.notify(APP_NAME,
                    self.t("Starts with Windows") if self.autostart_enabled()
                    else self.t("Autostart disabled"))

    # -- message routing -----------------------------------------------------
    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == win32.WM_HOTKEY:
                self._on_hotkey(int(wparam))
                return 0
            if msg == WM_TRAY:
                event = int(lparam) & 0xFFFF
                if event in (win32.WM_LBUTTONDBLCLK,):
                    self.open_settings()
                elif event in (win32.WM_RBUTTONUP, win32.WM_CONTEXTMENU):
                    self._show_menu()
                return 0
            if msg == win32.WM_COMMAND:
                self._on_command(int(wparam) & 0xFFFF)
                return 0
            if msg == win32.WM_TIMER:
                if int(wparam) == TIMER_WATCH:
                    self._watch_config()
                elif int(wparam) == TIMER_HOLD and self.engine is not None:
                    now = time.monotonic()
                    mods = win32.current_mods()
                    app = (win32.foreground_app()
                           if any(b.apps for b in self.engine.bindings) else None)
                    fired = self.engine.due(now, mods, self._hold_still_down, app)
                    for b in fired:
                        self._post_fire(b.index)
                    self._sync_hold_timer()
                elif int(wparam) == TIMER_UPDATE:
                    self._check_updates()
                    hours = self.cfg.settings.get("update_interval_hours", 6)
                    try:
                        interval = max(1, int(hours)) * 3600 * 1000
                    except (TypeError, ValueError):
                        interval = 6 * 3600 * 1000
                    self._schedule_update_check(interval)
                return 0
            if msg == WM_UPDATE:
                self._on_update_result()
                return 0
            if msg == WM_UPDATE_CHECK:
                self._check_updates(manual=bool(int(wparam)))
                return 0
            if msg == WM_HOOK_FIRE:
                self._on_hook_fire(int(wparam))
                return 0
            if msg == WM_RELOAD:
                self.reload()
                return 0
            if msg == WM_MACROKEY:
                self._apply_config_requests()
                return 0
            if msg == WM_SETTINGS:
                self.open_settings()
                return 0
            if msg == WM_PAUSE:
                self._paused = bool(int(wparam))
                self._register_all()
                return 0
            if msg == WM_QUIT_APP or msg == win32.WM_CLOSE:
                self.shutdown()
                return 0
        except Exception:  # never let an exception escape the callback
            log.exception("window procedure error")
        return win32.user32.DefWindowProcW(win32.HWND(hwnd), msg, wparam, lparam)

    def _on_hotkey(self, hid: int) -> None:
        if hid == ID_SUSPEND:
            self.toggle_suspend()
            return
        entry = self._by_id.get(hid)
        if entry is None:
            return
        self.note_fire(entry.index)
        self._run_entry(entry, prepare_only=True)

    # -- macro control window -------------------------------------------------
    def show_macro_panel(self) -> None:
        """Open (or raise) the tiny playback controller, lazily, on demand."""
        try:
            if self._macro_panel is None:
                from .gui import open_macro_panel
                self._macro_panel = open_macro_panel(self)
            else:
                self._macro_panel.show()
        except Exception:  # pragma: no cover - cosmetic only
            log.exception("macro control window failed")

    def toggle_macro_panel(self) -> None:
        """Show the macro panel, or hide it if it is already visible."""
        if self._macro_panel is None:
            self.show_macro_panel()
            return
        try:
            self._macro_panel.toggle()
        except Exception:
            log.exception("could not toggle macro panel")

    def run_last_macro(self) -> None:
        entry = self.macro.last_entry
        if entry is None:
            entry = next((e for e in self.cfg.entries
                          if e.action == "macro" and e.enabled), None)
        if entry is None:
            self.notify(self.t("Macro"),
                        self.t("No macro hotkey is configured"), force=True)
            return
        self._run_entry(entry)

    def _on_command(self, cmd: int) -> None:
        if cmd == CMD_MACRO:
            self.toggle_macro_panel()
        elif cmd == CMD_SETTINGS:
            self.open_settings()
        elif cmd == CMD_RELOAD:
            self.reload()
        elif cmd == CMD_CONFIG:
            self.open_config()
        elif cmd == CMD_AUTOSTART:
            self.toggle_autostart()
        elif cmd == CMD_SUSPEND:
            self.toggle_suspend()
        elif cmd == CMD_LOG:
            self.open_log()
        elif cmd == CMD_UPDATE:
            self._check_updates(manual=True)
        elif cmd == CMD_RELEASES:
            self.open_path(self._releases_url())
        elif cmd == CMD_QUIT:
            self.request_quit()
        elif CMD_PROFILE_BASE <= cmd < CMD_PROFILE_BASE + 1000:
            profiles = self.profile_names()
            offset = cmd - CMD_PROFILE_BASE
            if offset == 999:
                self.set_profile("next")
            elif 0 <= offset < len(profiles):
                self.set_profile(profiles[offset])

    def _show_menu(self) -> None:
        title = f"{APP_NAME}  -  {self.t('{count} active', count=self.active_count)}"
        if self.cfg.active_profile:
            title += f"  [{self.cfg.active_profile}]"
        items: list[tuple] = [
            (0, title, False, True),
            (0, "---", False, False),
        ]
        active_entries = [e for e in self.cfg.entries
                          if e.enabled
                          and config.entry_is_active(e, self.cfg.active_profile)]
        shown = 0
        for entry in active_entries:
            if shown == 12:
                remaining = len(active_entries) - shown
                items.append((0, self.t(
                    "    ...{count} more (see settings)", count=remaining),
                    False, True))
                break
            scope = f"  [{entry.scope()}]" if entry.apps else ""
            prof = f"  @{entry.profiles[0]}" if entry.profiles else ""
            items.append((0, f"    {entry.display}   {entry.label()}{scope}{prof}",
                          False, True))
            shown += 1
        if not shown:
            items.append((0, self.t("    no hotkeys configured"), False, True))
        profile_items = []
        for i, pname in enumerate(self.profile_names()):
            profile_items.append((CMD_PROFILE_BASE + i, pname,
                                 self.cfg.active_profile.casefold() == pname.casefold(),
                                 False))
        if profile_items:
            profile_items.append((0, "---", False, False))
            profile_items.append((CMD_PROFILE_BASE + 999,
                                  self.t("Next profile"), False, False))
        extra = []
        if profile_items:
            extra.append((0, self.t("Profiles"), False, False, profile_items))
        extra += [
            (0, "---", False, False),
            (CMD_MACRO, self.t("Show / hide macro controls"), False, False),
            (CMD_SETTINGS, self.t("Hotkey settings..."), False, False),
            (CMD_RELOAD, self.t("Reload hotkeys"), False, False),
            (CMD_CONFIG, self.t("Open hotkeys.json"), False, False),
            (0, "---", False, False),
            (CMD_AUTOSTART, self.t("Start with Windows"),
             self.autostart_enabled(), False),
            (CMD_SUSPEND, self.t("Suspend all hotkeys"), self.suspended, False),
            (0, "---", False, False),
            (CMD_LOG, self.t("Open log"), False, False),
            (CMD_RELEASES, self.t("Open releases page"), False, False),
            (CMD_UPDATE,
             self.t("Update available: {version}",
                    version=self._update_info.version)
             if self._update_info else self.t("Check for updates"),
             False, False),
            (CMD_QUIT, self.t("Quit"), False, False),
        ]
        items += extra
        # menu_create_ex returns the root plus every submenu; all of them own
        # USER handles and must be destroyed, not just the root.
        menu, handles = win32.menu_create_ex(items)
        try:
            cmd = win32.menu_show(menu, self.hwnd)
        finally:
            for handle in reversed(handles):
                try:
                    win32.user32.DestroyMenu(win32.HMENU(handle))
                except Exception:
                    pass
        if cmd:
            self._on_command(cmd)

    def _watch_config(self) -> None:
        if not self.cfg.settings.get("reload_on_change", True):
            return
        try:
            mtime = os.stat(self.path).st_mtime_ns
        except OSError:
            return
        if mtime != self.cfg.mtime:
            log.info("config changed on disk, reloading")
            self.reload()

    # -- loop ----------------------------------------------------------------
    def _loop(self) -> int:
        msg = win32.MSG()
        while True:
            got = win32.user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if got > 0:
                win32.user32.TranslateMessage(ctypes.byref(msg))
                win32.user32.DispatchMessageW(ctypes.byref(msg))
                continue
            if got < 0:
                log.error("GetMessageW failed (error %s)", ctypes.get_last_error())
                return 1
            return 0

    def shutdown(self) -> None:
        log.info("shutting down")
        win32.user32.KillTimer(win32.HWND(self.hwnd), TIMER_WATCH)
        self.macro.cancel()
        if self._macro_panel is not None:
            try:
                self._macro_panel.close()
            except Exception:
                pass
        self._stop_hook()
        self._unregister_all()
        if self.use_tray:
            try:
                win32.tray_remove(self.hwnd, TRAY_UID)
            except Exception:
                pass
        if self.hwnd:
            win32.user32.DestroyWindow(win32.HWND(self.hwnd))
        win32.user32.PostQuitMessage(0)


def log_path() -> str:
    return os.path.join(data_dir(), "hotkey.log")


def setup_logging(verbose: bool) -> None:
    log.setLevel(logging.DEBUG if verbose else logging.INFO)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s", "%H:%M:%S")
    try:
        fh = RotatingFileHandler(log_path(), maxBytes=128 * 1024, backupCount=2,
                                 encoding="utf-8")
        fh.setFormatter(fmt)
        log.addHandler(fh)
    except OSError:
        pass
    if verbose or sys.stderr is not None:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        sh.setLevel(logging.DEBUG if verbose else logging.WARNING)
        log.addHandler(sh)


def acquire_single_instance():
    # CreateMutexW only promises a useful last-error when it fails; clear it
    # first so a stale ERROR_ALREADY_EXISTS cannot make a fresh launch exit.
    ctypes.set_last_error(0)
    handle = win32.kernel32.CreateMutexW(None, False, "Local\\HotkeyApp.SingleInstance")
    if not handle:
        return None
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        win32.kernel32.CloseHandle(handle)
        return None
    return handle


def default_config_path() -> str:
    return os.path.join(ROOT, "hotkeys.json")


def main(argv: list[str] | None = None) -> int:
    # pythonw.exe starts with stdout/stderr set to None; keep print() safe.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115

    parser = argparse.ArgumentParser(
        prog="hotkey", description="Zero-dependency global hotkey manager for Windows.")
    parser.add_argument("--config", default=default_config_path(),
                        help="path to hotkeys.json")
    parser.add_argument("--no-tray", action="store_true", help="run without a tray icon")
    parser.add_argument("--settings", action="store_true", help="open the settings window")
    parser.add_argument("--list", action="store_true", help="print configured hotkeys and exit")
    parser.add_argument("--validate", action="store_true", help="check the config and exit")
    parser.add_argument("--self-test", action="store_true", help="run built-in diagnostics")
    parser.add_argument("--full", action="store_true",
                        help="with --self-test: also test the clipboard")
    parser.add_argument("--install-autostart", action="store_true")
    parser.add_argument("--remove-autostart", action="store_true")
    parser.add_argument("--reload", action="store_true", help="ask the running app to reload")
    parser.add_argument("--quit", action="store_true", help="stop the running app")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    args = parser.parse_args(argv)

    win32.enable_dpi_awareness()
    setup_logging(args.verbose)
    path = os.path.abspath(args.config)

    if args.self_test:
        from .selftest import run as run_tests
        return run_tests(path, args.full)

    created = config.ensure_default(path)
    if created:
        log.info("created starter config at %s", path)

    if args.list:
        cfg = config.load(path)
        for err in cfg.errors:
            print(f"ERROR: {err}")
        for entry in cfg.entries:
            state = " " if entry.enabled else "off"
            scope = f"  [{entry.scope()}]" if entry.apps else ""
            print(f"{state} {entry.display:<22} {entry.action:<7} "
                  f"{entry.value or '':<34} {entry.description}{scope}")
        if not cfg.entries:
            print("(no hotkeys)")
        return 1 if cfg.errors else 0

    if args.validate:
        cfg = config.load(path)
        for err in cfg.errors:
            print(f"ERROR: {err}")
        for warn in cfg.warnings:
            print(f"WARN:  {warn}")
        if not cfg.errors:
            print(f"OK: {len(cfg.entries)} hotkeys in {path}")
        return 1 if cfg.errors else 0

    if args.install_autostart or args.remove_autostart:
        if args.install_autostart == args.remove_autostart:
            parser.error("choose either --install-autostart or --remove-autostart")
        app = App(path, use_tray=False)
        app.set_autostart(args.install_autostart)
        print(("Autostart enabled: " if args.install_autostart else "Autostart disabled: ")
              + app.autostart_command())
        return 0

    mutex = acquire_single_instance()
    if mutex is None:
        hwnd = win32.find_window("HotkeyMainWindow")
        if hwnd and args.quit:
            win32.user32.PostMessageW(win32.HWND(hwnd), WM_QUIT_APP, 0, 0)
            print("Hotkey stopped.")
            return 0
        if hwnd and args.reload:
            win32.user32.PostMessageW(win32.HWND(hwnd), WM_RELOAD, 0, 0)
            print("Hotkey reloaded.")
            return 0
        if hwnd and args.settings:
            win32.user32.PostMessageW(win32.HWND(hwnd), WM_SETTINGS, 0, 0)
            return 0
        log.warning("Hotkey is already running")
        if args.settings:
            log.warning("...but its window could not be found")
        return 0

    app = App(path, use_tray=not args.no_tray)
    try:
        if hasattr(signal, "SIGINT"):
            signal.signal(signal.SIGINT, lambda *_: app.request_quit())
        if args.settings:
            threading.Timer(0.4, app.request_settings).start()
        return app.start()
    except Exception:
        log.exception("fatal error")
        return 1
    finally:
        win32.kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    raise SystemExit(main())
