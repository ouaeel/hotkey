"""Optional tkinter settings window. Imported lazily so the tray-only mode
never pays the tkinter import cost or allocation."""
from __future__ import annotations

import ctypes
import gc
import json
import math
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from . import __version__, config, i18n, icon, keys, win32
from .actions import SPECS

FONT = "Segoe UI"
MONO = "Consolas"
FONT_BOOST = 1.3


def _font(size: int, *style: str) -> tuple:
    return (FONT, max(8, round(size * FONT_BOOST)), *style)


def _mono(size: int) -> tuple:
    return (MONO, max(8, round(size * FONT_BOOST)))


def _symbol_font(size: int = 10) -> tuple:
    return ("Segoe UI Symbol", max(9, round(size * FONT_BOOST)))


def _start(lang: str) -> str:
    """Side where the first item of a RTL-aware row belongs."""
    return "right" if i18n.is_rtl(lang) else "left"


def _end(lang: str) -> str:
    return "left" if i18n.is_rtl(lang) else "right"


def _near(lang: str) -> str:
    """Text anchor on the reading-start side."""
    return "e" if i18n.is_rtl(lang) else "w"


def _far(lang: str) -> str:
    return "w" if i18n.is_rtl(lang) else "e"


def _justify(lang: str) -> str:
    """Tk text justification matching the reading direction."""
    return "right" if i18n.is_rtl(lang) else "left"


def _pad(lang: str, before: int, after: int = 0) -> tuple[int, int]:
    """Mirror horizontal padding for a RTL row."""
    return (after, before) if i18n.is_rtl(lang) else (before, after)


def _columns(lang: str) -> tuple[int, int]:
    """Label column and value column for a two-column RTL-aware form."""
    return (1, 0) if i18n.is_rtl(lang) else (0, 1)


def _apply_window_icon(win) -> None:
    """Put the generated icon on any Tk window (title bar and taskbar).

    Toplevel dialogs do not inherit the main window's icon on Windows, so
    every form calls this explicitly.  A missing/broken icon must never stop
    the UI from opening.
    """
    try:
        from .app import data_dir
        active, _ = icon.ensure_icon(data_dir())
        win.iconbitmap(active)
        try:
            win32.set_window_icon(int(win.winfo_id()), active)
        except Exception:
            pass
    except Exception:
        pass


def _translate_widgets(widget, t) -> None:
    """Translate static widget text once, down the whole child tree."""
    for child in widget.winfo_children():
        if isinstance(child, (ttk.Combobox, ttk.Entry, tk.Text, tk.Canvas)):
            pass
        else:
            try:
                text = child.cget("text")
                if text:
                    child.configure(text=t(str(text)))
            except (tk.TclError, TypeError):
                pass
        if isinstance(child, ttk.Treeview):
            for column in child["columns"]:
                try:
                    heading = child.heading(column, "text")
                    if heading:
                        child.heading(column, text=t(str(heading)))
                except tk.TclError:
                    pass
        _translate_widgets(child, t)


PAD = 8
PAD_L = 24
SPEED_CHOICES = ("0.25x", "0.5x", "0.75x", "1x", "1.5x", "2x", "3x", "4x")

TRIGGER_LABELS = {
    "press": "Instant (press)",
    "double": "Double click",
    "tap": "On release (tap)",  # legacy: still parsed, no longer offered
    "hold": "Long press (hold)",
}
# Tk button numbers -> our key names (Windows: 2 = middle, 3 = right)
MOUSE_BUTTONS = {1: "mouse_left", 2: "mouse_middle", 3: "mouse_right",
                 4: "mouse4", 5: "mouse5"}


def _palette() -> dict:
    dark = True
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            dark = winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except OSError:
        pass
    if dark:
        return {
            "dark": True, "bg": "#0F141C", "panel": "#171E29", "panel2": "#1E2734",
            "hover": "#26313F", "fg": "#E8EEF7", "muted": "#94A3B8",
            "border": "#2A3543", "accent": "#3DDC97", "accent_fg": "#04241A",
            "accent_hover": "#5AE7AB", "sel": "#1F3B33", "error": "#F87171",
        }
    return {
        "dark": False, "bg": "#F4F6FA", "panel": "#FFFFFF", "panel2": "#EDF1F6",
        "hover": "#E2E8F0", "fg": "#141C26", "muted": "#5B6B7F",
        "border": "#D8DFE8", "accent": "#12B981", "accent_fg": "#FFFFFF",
        "accent_hover": "#0EA271", "sel": "#D8F5EA", "error": "#DC2626",
    }


def _scale_factor() -> float:
    try:
        dpi = ctypes.windll.user32.GetDpiForSystem()
    except Exception:
        dpi = 96
    return max(1.1, dpi / 96.0)


def _tip(widget, var: tk.StringVar, text) -> None:
    """Show a short explanation in an existing status label on hover."""
    previous = {"text": ""}

    def enter(_event=None) -> None:
        try:
            previous["text"] = var.get()
        except tk.TclError:
            previous["text"] = ""
        var.set(text() if callable(text) else text)

    def leave(_event=None) -> None:
        try:
            var.set(previous["text"])
        except tk.TclError:
            pass

    widget.bind("<Enter>", enter)
    widget.bind("<Leave>", leave)


def _mod_labels(mods: int) -> list[str]:
    labels: list[str] = []
    for bit, name in (
        (keys.MOD_CONTROL, "Ctrl"), (keys.MOD_ALT, "Alt"),
        (keys.MOD_SHIFT, "Shift"), (keys.MOD_WIN, "Win"),
    ):
        if mods & bit:
            labels.append(name)
    return labels


def _key_info(entry, t) -> str:
    """Compact technical detail for the main shortcut list."""
    bits: list[str] = []
    if entry.seq:
        bits.append(t("Leader · {count} steps", count=len(entry.seq)))
    elif len(entry.vks) > 1:
        bits.append(t("Chord · {count} keys", count=len(entry.vks)))
    mods = _mod_labels(entry.mods)
    if mods:
        bits.append("+".join(mods))
    if entry.vks:
        codes = ", ".join(f"0x{vk:02X}" for vk in entry.vks[:4])
        bits.append(f"VK {codes}")
        if len(entry.vks) > 4:
            bits.append(f"+{len(entry.vks) - 4}")
    return " · ".join(bits) or "—"


def _trigger_label(trigger: str, t) -> str:
    name = trigger if trigger in TRIGGER_LABELS else "press"
    return t(TRIGGER_LABELS[name])


def _entry_scope(entry, t) -> str:
    parts: list[str] = []
    if entry.apps:
        parts.append(entry.scope())
    if entry.profiles:
        parts.append(t("Profile: {name}", name=entry.profile_scope()))
    return " · ".join(parts) or t("All apps")


def _entry_detail(entry, t) -> str:
    parts: list[str] = []
    if entry.action == "macro":
        steps = entry.extra.get("steps") or []
        parts.append(t("{count} steps", count=len(steps)))
        speed = entry.extra.get("speed")
        if speed is not None:
            parts.append(t("Speed {speed}", speed=_speed_label(speed)))
    if entry.value:
        parts.append(str(entry.value))
    if entry.description:
        parts.append(entry.description)
    return "  ·  ".join(parts) or "—"


class SettingsWindow:
    def __init__(self, app):
        self.app = app
        self.path = app.path
        self.cfg = config.load(self.path)
        self.raw = self.cfg.raw or {}
        self.entries = list(self.cfg.entries)
        self.settings = dict(self.cfg.settings)
        self.lang = i18n.normalize(self.settings.get("language"))
        self.rtl = i18n.is_rtl(self.lang)
        self.pending_settings: dict[str, object] = {}
        self._fire_job: str | None = None
        self._flash_jobs: dict[str, tuple[str, tuple[str, ...]]] = {}
        self._countdown: dict | None = None
        self._countdown_job: str | None = None
        self.pal = _palette()
        self.scale = _scale_factor()
        self.root = tk.Tk()
        self.root.withdraw()

    def t(self, text: str, **kwargs: object) -> str:
        return i18n.tr(text, self.lang, **kwargs)

    def _rebuild(self) -> None:
        # A Toplevel is also a child of root, so take the tiny timer down before
        # the widget tree is replaced, then bring it back with the new language.
        pending = None
        if self._countdown is not None:
            pending = (str(self._countdown.get("kind", "")),
                       float(self._countdown.get("delay", 0) or 0))
        self._close_countdown(restore=False)
        for attr in ("_status_job", "_power_job", "_page_job"):
            job = getattr(self, attr, None)
            if job is not None:
                try:
                    self.root.after_cancel(job)
                except (tk.TclError, ValueError):
                    pass
            setattr(self, attr, None)
        for job, _previous in self._flash_jobs.values():
            try:
                self.root.after_cancel(job)
            except tk.TclError:
                pass
        self._flash_jobs.clear()
        self._close_language_window()
        self._power_var = None
        self._power_cancel_btn = None
        self._page_overlay = None
        self._page_anim = False
        for child in list(self.root.winfo_children()):
            child.destroy()
        self._build()
        _translate_widgets(self.root, self.t)
        if pending is not None:
            self.root.withdraw()
            self._show_countdown(*pending)

    def _notifications_enabled(self) -> bool:
        return bool(self.settings.get("show_notifications", True))

    def _apply_preference_changes(self, changes: dict[str, object]) -> bool:
        """Save gear-window preferences without touching unsaved hotkey edits."""
        current = config.load(self.path)
        raw = dict(current.raw or {})
        raw["version"] = 1
        settings = dict(current.settings)
        settings.update(changes)
        raw["settings"] = settings
        if "hotkeys" not in raw:
            raw["hotkeys"] = [e.to_json() for e in self.entries]
        try:
            config.save_raw(self.path, raw)
        except OSError as exc:
            messagebox.showerror(
                self.t("Hotkey"),
                self.t("Could not save preferences:\n{error}", error=exc),
                parent=self.root)
            return False
        self.cfg = config.load(self.path)
        self.raw = self.cfg.raw or {}
        self.settings = dict(self.cfg.settings)
        self.app.request_reload()
        return True

    def _set_language(self, forced: str | None = None) -> None:
        code = (i18n.normalize(forced) if forced is not None
                else i18n.code_from_display(self.var_language.get(), self.lang))
        if code == self.lang:
            self.var_language.set(i18n.display(code))
            return
        if not self._apply_preference_changes({"language": code}):
            self.var_language.set(i18n.display(self.lang))
            return
        self.lang = code
        self.rtl = i18n.is_rtl(code)
        self._rebuild()
        self._status(self.t("Language set to {language}",
                            language=i18n.display(code)))

    def _close_language_window(self) -> None:
        """Destroy the small quick-settings window if it is open."""
        for attr in ("_lang_win_update_job",):
            job = getattr(self, attr, None)
            if job is not None:
                try:
                    self.root.after_cancel(job)
                except (tk.TclError, ValueError):
                    pass
        win = getattr(self, "_lang_win", None)
        if win is not None:
            try:
                win.destroy()
            except tk.TclError:
                pass
        self._lang_win = None
        self._lang_win_update_job = None
        self._lang_win_combo = None
        self._lang_win_notify = None
        self._lang_win_notify_var = None
        self._lang_win_apply = None
        self._lang_win_version_var = None
        self._lang_win_latest_var = None
        self._lang_win_update_var = None
        self._lang_win_check = None

    def _update_status_snapshot(self) -> dict:
        """Read the app's update status, with a fallback for simple owners."""
        snapshot = getattr(self.app, "update_snapshot", None)
        if callable(snapshot):
            try:
                return snapshot()
            except Exception:
                pass
        return {
            "state": "idle", "version": "",
            "message": "Not checked yet", "kwargs": {},
            "current": __version__,
        }

    def _apply_update_status(self, status: dict) -> None:
        """Reflect one update snapshot in the gear window."""
        state = str(status.get("state") or "idle")
        latest = str(status.get("version") or "")
        if state == "new" and latest:
            latest_text = latest
        elif state == "current":
            latest_text = self.t("You are up to date")
        else:
            latest_text = "—"
        version_var = getattr(self, "_lang_win_latest_var", None)
        if version_var is not None:
            version_var.set(latest_text)
        key = str(status.get("message") or "Not checked yet")
        kwargs = status.get("kwargs")
        if not isinstance(kwargs, dict):
            kwargs = {}
        status_var = getattr(self, "_lang_win_update_var", None)
        if status_var is not None:
            status_var.set(self.t(key, **kwargs))
        button = getattr(self, "_lang_win_check", None)
        if button is not None:
            try:
                button.configure(
                    state="disabled" if state == "checking" else "normal")
            except tk.TclError:
                pass

    def _poll_update(self) -> None:
        """Drain update results on the Tk thread; never block the app loop."""
        win = getattr(self, "_lang_win", None)
        events = getattr(self.app, "update_events", None)
        if win is None or events is None:
            return
        try:
            if not win.winfo_exists():
                return
        except tk.TclError:
            return
        try:
            while True:
                self._apply_update_status(events.get_nowait())
        except queue.Empty:
            pass
        self._lang_win_update_job = self.root.after(300, self._poll_update)

    def _power_snapshot(self) -> dict:
        snapshot = getattr(self.app, "power_status", None)
        if callable(snapshot):
            try:
                return snapshot()
            except Exception:
                pass
        return {"active": False, "action": "", "seconds_left": 0.0}

    @staticmethod
    def _power_label(action: object) -> str:
        return {
            "sleep": "Sleep", "shutdown": "Shutdown", "restart": "Restart",
        }.get(str(action), "Shutdown")

    def _power_text(self, status: dict) -> str:
        if not status.get("active"):
            return self.t("No power action scheduled")
        action = status.get("action")
        label = self.t(self._power_label(action))
        left = max(0.0, float(status.get("seconds_left") or 0))
        if left >= 60:
            return self.t("Scheduled: {action} in {minutes} min",
                          action=label, minutes=max(1, round(left / 60)))
        return self.t("Scheduled: {action} in {seconds} s",
                      action=label, seconds=max(1, int(left)))

    def _update_power_status(self) -> None:
        status = self._power_snapshot()
        text = self._power_text(status)
        variable = getattr(self, "_power_var", None)
        if variable is not None:
            variable.set(text)
        hero = getattr(self, "_power_hero_var", None)
        if hero is not None:
            hero.set(text)
        button = getattr(self, "_power_cancel_btn", None)
        if button is not None:
            try:
                button.configure(
                    state="normal" if status.get("active") else "disabled")
            except tk.TclError:
                pass

    def _refresh_power_status(self) -> None:
        page = getattr(self, "page_power", None)
        if page is None:
            return
        try:
            if not page.winfo_exists():
                return
        except tk.TclError:
            return
        self._update_power_status()
        self._power_job = self.root.after(1000, self._refresh_power_status)

    def _close_countdown(self, *, restore: bool = True) -> None:
        """Tear down the tiny timer; optionally bring the settings window back."""
        job = getattr(self, "_countdown_job", None)
        if job is not None:
            try:
                self.root.after_cancel(job)
            except (tk.TclError, ValueError):
                pass
        self._countdown_job = None
        state = getattr(self, "_countdown", None)
        self._countdown = None
        if state is not None:
            try:
                win = state.get("win")
                if win is not None and win.winfo_exists():
                    win.destroy()
            except tk.TclError:
                pass
        if restore:
            try:
                if self.root.winfo_exists() and not self.root.winfo_ismapped():
                    self.root.deiconify()
                    self.root.lift()
            except tk.TclError:
                pass

    def _cancel_countdown(self) -> None:
        """Cancel the scheduled action from the timer's Cancel/close button."""
        canceller = getattr(self.app, "cancel_power_action", None)
        if callable(canceller):
            try:
                canceller()
            except Exception:
                pass
        self._close_countdown(restore=True)
        self._update_power_status()

    @staticmethod
    def _countdown_text(seconds: float) -> str:
        total = max(0, int(seconds + 0.999))
        minutes_left, secs = divmod(total, 60)
        return f"{minutes_left:02d}:{secs:02d}"

    def _show_countdown(self, action: str, minutes: float) -> None:
        """Replace the settings window with a tiny always-on-top countdown."""
        self._close_countdown(restore=False)
        p = self.pal
        near = _near(self.lang)
        just = _justify(self.lang)
        delay = max(0.0, float(minutes))
        win = tk.Toplevel(self.root)
        win.withdraw()
        win.title(self.t("Power timer"))
        win.resizable(False, False)
        win.configure(bg=p["bg"])
        try:
            win.attributes("-topmost", True)
        except tk.TclError:
            pass
        _apply_window_icon(win)

        frame = tk.Frame(win, bg=p["panel"], highlightbackground=p["border"],
                         highlightthickness=1,
                         padx=int(18 * self.scale), pady=int(14 * self.scale))
        frame.pack(fill="both", expand=True, padx=1, pady=1)
        tk.Label(frame, text=self.t("Power timer"), font=_font(9, "bold"),
                 bg=p["panel"], fg=p["muted"], anchor=near,
                 justify=just).pack(fill="x")
        action_lbl = tk.Label(
            frame, text=self.t(self._power_label(action)),
            font=_font(12, "bold"), bg=p["panel"], fg=p["accent"],
            anchor=near, justify=just)
        action_lbl.pack(fill="x", pady=(int(6 * self.scale), 0))
        time_lbl = tk.Label(frame, text=self._countdown_text(delay * 60),
                            font=_mono(30), bg=p["panel"], fg=p["fg"])
        time_lbl.pack(fill="x", pady=(int(8 * self.scale),
                                     int(10 * self.scale)))
        cancel = tk.Button(
            frame, text=self.t("Cancel"), command=self._cancel_countdown,
            bg=p["panel2"], fg=p["fg"], activebackground=p["hover"],
            activeforeground=p["fg"], relief="flat", bd=0,
            font=_font(10, "bold"), padx=int(16 * self.scale),
            pady=int(6 * self.scale), cursor="hand2")
        cancel.pack(fill="x")
        win.protocol("WM_DELETE_WINDOW", self._cancel_countdown)

        self._countdown = {
            "win": win, "time": time_lbl, "action": action_lbl,
            "cancel": cancel, "kind": str(action), "delay": delay,
            "started": time.monotonic(),
        }
        win.update_idletasks()
        width = win.winfo_width() or int(230 * self.scale)
        height = win.winfo_height() or int(170 * self.scale)
        screen_w, screen_h = win.winfo_screenwidth(), win.winfo_screenheight()
        x = 24 if self.rtl else max(0, screen_w - width - 24)
        y = max(0, screen_h - height - 56)
        win.geometry(f"+{x}+{y}")
        win.deiconify()
        win.lift()
        win.focus_set()
        self._tick_countdown()

    def _tick_countdown(self) -> None:
        """Refresh the tiny timer once a second and watch for cancellation."""
        state = getattr(self, "_countdown", None)
        if state is None:
            return
        job = getattr(self, "_countdown_job", None)
        if job is not None:
            try:
                self.root.after_cancel(job)
            except (tk.TclError, ValueError):
                pass
        self._countdown_job = None
        status = self._power_snapshot()
        if not status.get("active"):
            elapsed = time.monotonic() - float(state.get("started", 0))
            if elapsed >= max(0.0, float(state.get("delay", 0)) * 60.0 - 0.75):
                # Timer fired (or the PC is going away): end the settings
                # window too, so the tray can open a fresh one afterwards.
                self._close_countdown(restore=False)
                self._close()
                return
            self._close_countdown(restore=True)
            self._update_power_status()
            return
        left = float(status.get("seconds_left") or 0)
        if left <= 0:
            left = max(0.0, float(state.get("delay", 0)) * 60.0 -
                       (time.monotonic() - float(state.get("started", 0))))
        label = state.get("time")
        try:
            text = self._countdown_text(left)
            if str(label.cget("text")) != text:
                label.configure(text=text)
        except tk.TclError:
            self._close_countdown(restore=False)
            return
        self._countdown_job = self.root.after(1000, self._tick_countdown)

    def _show_language_window(self) -> None:
        """Open the gear window with language and notification settings."""
        existing = getattr(self, "_lang_win", None)
        if existing is not None:
            try:
                if existing.winfo_exists():
                    existing.lift()
                    existing.focus_set()
                    return
            except tk.TclError:
                pass
        self._close_language_window()

        p = self.pal
        start, end = _start(self.lang), _end(self.lang)
        just = _justify(self.lang)
        win = tk.Toplevel(self.root)
        self._lang_win = win
        win.title(self.t("Quick settings"))
        win.transient(self.root)
        win.resizable(False, False)
        win.configure(bg=p["bg"])
        _apply_window_icon(win)
        try:
            win32.set_dark_titlebar(win.winfo_id(), p["dark"])
        except Exception:
            pass

        body = ttk.Frame(win, padding=(PAD_L, 18, PAD_L, PAD_L))
        body.pack(fill="both", expand=True)
        selector = ttk.Frame(body)
        selector.pack(fill="x")
        ttk.Label(selector, text=self.t("Interface language"),
                  style="Muted.TLabel", justify=just).pack(side=start)
        combo = ttk.Combobox(
            selector, state="readonly", width=14,
            values=[i18n.display(code) for code in i18n.LANGUAGES])
        combo.current(i18n.LANGUAGES.index(self.lang))
        combo.pack(side=start, padx=_pad(self.lang, 10))
        self._lang_win_combo = combo

        notify_row = ttk.Frame(body)
        notify_row.pack(fill="x", pady=(PAD_L, 0))
        notify_var = tk.BooleanVar(
            master=win, value=self._notifications_enabled())
        self._lang_win_notify = ttk.Checkbutton(
            notify_row, text=self.t("Show notifications"),
            variable=notify_var, justify=just)
        self._lang_win_notify.pack(side=start)
        self._lang_win_notify_var = notify_var

        auto_row = ttk.Frame(body)
        auto_row.pack(fill="x", pady=(8, 0))
        autostart_var = tk.BooleanVar(
            master=win, value=bool(self.app.autostart_enabled()))
        self._lang_win_autostart = ttk.Checkbutton(
            auto_row, text=self.t("Start with Windows"),
            variable=autostart_var, justify=just)
        self._lang_win_autostart.pack(side=start)
        self._lang_win_autostart_var = autostart_var
        _tip(self._lang_win_autostart, self.status_var,
             self.t("Run this app automatically when you sign in"))

        current_row = ttk.Frame(body)
        current_row.pack(fill="x", pady=(PAD_L, 0))
        ttk.Label(current_row, text=self.t("Current version:"),
                  style="Muted.TLabel", justify=just).pack(side=start)
        self._lang_win_version_var = tk.StringVar(master=win, value=__version__)
        ttk.Label(current_row, textvariable=self._lang_win_version_var,
                  justify=just).pack(side=start, padx=_pad(self.lang, 8))

        newest_row = ttk.Frame(body)
        newest_row.pack(fill="x", pady=(6, 0))
        ttk.Label(newest_row, text=self.t("New version:"),
                  style="Muted.TLabel", justify=just).pack(side=start)
        self._lang_win_latest_var = tk.StringVar(master=win, value="—")
        ttk.Label(newest_row, textvariable=self._lang_win_latest_var,
                  justify=just).pack(side=start, padx=_pad(self.lang, 8))

        update_status = tk.StringVar(master=win, value="")
        self._lang_win_update_var = update_status
        ttk.Label(body, textvariable=update_status, style="Muted.TLabel",
                  justify=just, wraplength=300).pack(fill="x", pady=(6, 0))

        update_buttons = ttk.Frame(body)
        update_buttons.pack(fill="x", pady=(8, 0))

        def check_version() -> None:
            self._apply_update_status(
                {"state": "checking", "message": "Checking…"})
            request = getattr(self.app, "request_update_check", None)
            if callable(request):
                request()

        def open_releases() -> None:
            opener = getattr(self.app, "open_path", None)
            snapshot = self._update_status_snapshot()
            url = str(snapshot.get("url") or "")
            if callable(opener) and url:
                opener(url)

        self._lang_win_check = ttk.Button(
            update_buttons, text=self.t("Check version"), command=check_version)
        self._lang_win_check.pack(side=start)
        ttk.Button(update_buttons, text=self.t("Open releases page"),
                   command=open_releases).pack(
                       side=start, padx=_pad(self.lang, 0, 8))

        self._apply_update_status(self._update_status_snapshot())

        def close() -> None:
            self._close_language_window()

        def apply() -> None:
            code = i18n.code_from_display(combo.get(), self.lang)
            enabled = bool(notify_var.get())
            autostart = bool(autostart_var.get())
            auto_changed = autostart != bool(self.app.autostart_enabled())
            changes: dict[str, object] = {}
            if code != self.lang:
                changes["language"] = code
            if enabled != self._notifications_enabled():
                changes["show_notifications"] = enabled
            if not changes and not auto_changed:
                close()
                return
            # Do the registry write first: if it fails, no preferences have
            # been saved and the visible UI still matches the stored language.
            if auto_changed:
                try:
                    self.app.set_autostart(autostart)
                except OSError as exc:
                    autostart_var.set(self.app.autostart_enabled())
                    messagebox.showerror(
                        self.t("Hotkey"),
                        self.t("Could not update autostart:\n{error}", error=exc),
                        parent=self.root)
                    return
            if changes and not self._apply_preference_changes(changes):
                return
            close()
            if "language" in changes:
                self.lang = code
                self.rtl = i18n.is_rtl(code)
                self._rebuild()
            messages = []
            if "language" in changes:
                messages.append(self.t("Language set to {language}",
                                       language=i18n.display(code)))
            if "show_notifications" in changes:
                messages.append(
                    self.t("Notifications enabled") if enabled
                    else self.t("Notifications disabled"))
            if auto_changed:
                messages.append(
                    self.t("Autostart enabled") if autostart
                    else self.t("Autostart disabled"))
            self._status(" · ".join(messages))

        ttk.Separator(body, orient="horizontal").pack(
            fill="x", pady=(PAD_L + 4, 0))
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(PAD_L, 0))
        self._lang_win_apply = ttk.Button(
            buttons, text=self.t("Apply"), style="Accent.TButton",
            command=apply)
        self._lang_win_apply.pack(side=end)
        ttk.Button(buttons, text=self.t("Close"),
                   command=close).pack(side=end, padx=_pad(self.lang, 0, 8))
        win.protocol("WM_DELETE_WINDOW", close)
        win.bind("<Escape>", lambda _e: close())
        combo.bind("<Return>", lambda _e: apply())

        if getattr(self.app, "update_events", None) is not None:
            self._lang_win_update_job = self.root.after(300, self._poll_update)
        win.update_idletasks()
        width, height = win.winfo_width(), win.winfo_height()
        parent_x, parent_y = self.root.winfo_rootx(), self.root.winfo_rooty()
        parent_w, parent_h = self.root.winfo_width(), self.root.winfo_height()
        x = parent_x + max(0, (parent_w - width) // 2)
        y = parent_y + max(0, (parent_h - height) // 2)
        win.geometry(f"+{x}+{y}")
        win.lift()
        combo.focus_set()

    def _build_power_page(self, parent) -> None:
        """Build the dedicated Power page inside the main settings window."""
        start = _start(self.lang)
        just = _justify(self.lang)
        near = _near(self.lang)
        job = getattr(self, "_power_job", None)
        if job is not None:
            try:
                self.root.after_cancel(job)
            except (tk.TclError, ValueError):
                pass
        self._power_job = None

        ttk.Label(parent, text=self.t("POWER"), style="Section.TLabel",
                  justify=just).pack(anchor=near, padx=PAD_L, pady=(12, 2))
        ttk.Label(parent, text=self.t("Power description"),
                  style="Sub.TLabel", justify=just,
                  wraplength=int(620 * self.scale)).pack(
                      anchor=near, padx=PAD_L, pady=(0, 12))

        card = self._card(parent, side="x", padx=PAD_L,
                          pady=(0, PAD_L), padding=(20, 18))

        hero = ttk.Frame(card, style="Hero.TFrame", padding=(16, 14))
        hero.pack(fill="x", pady=(0, 16))
        self._power_hero_var = tk.StringVar(master=card, value="")
        ttk.Label(hero, textvariable=self._power_hero_var,
                  style="Hero.TLabel", justify=just,
                  wraplength=int(520 * self.scale)).pack(
                      fill="x", anchor=near)

        action_row = ttk.Frame(card, style="Card.TFrame")
        action_row.pack(fill="x")
        ttk.Label(action_row, text=self.t("Action"),
                  style="CardMuted.TLabel", justify=just).pack(side=start)
        power_action = ttk.Combobox(
            action_row, state="readonly", width=18,
            values=[self.t("Sleep"), self.t("Shutdown"), self.t("Restart")])
        power_action.current(0)
        power_action.pack(side=start, padx=_pad(self.lang, 10))
        self._power_action_combo = power_action

        delay_row = ttk.Frame(card, style="Card.TFrame")
        delay_row.pack(fill="x", pady=(10, 0))
        ttk.Label(delay_row, text=self.t("Delay (minutes)"),
                  style="CardMuted.TLabel", justify=just).pack(side=start)
        delay_var = tk.StringVar(master=card, value="10")
        self._power_delay_var = delay_var
        ttk.Spinbox(delay_row, from_=0, to=1440, increment=1, width=10,
                    textvariable=delay_var).pack(
                        side=start, padx=_pad(self.lang, 10))
        ttk.Label(delay_row, text=self.t("0 = now"),
                  style="CardMuted.TLabel", justify=just).pack(side=start)

        status_var = tk.StringVar(master=card, value="")
        self._power_var = status_var

        def plan_power() -> None:
            actions = ("sleep", "shutdown", "restart")
            index = power_action.current()
            action = actions[index] if 0 <= index < len(actions) else "sleep"
            raw = delay_var.get().strip()
            try:
                delay = float(raw)
            except ValueError:
                status_var.set(self.t("Enter minutes (0-1440)."))
                return
            if not math.isfinite(delay) or delay < 0 or delay > 1440:
                status_var.set(self.t("Enter minutes (0-1440)."))
                return
            shown = str(int(delay)) if delay.is_integer() else f"{delay:g}"
            if action in ("shutdown", "restart"):
                confirmed = messagebox.askyesno(
                    self.t("Confirm shutdown" if action == "shutdown"
                           else "Confirm restart"),
                    self.t("Shut down this PC in {minutes} min?"
                           if action == "shutdown"
                           else "Restart this PC in {minutes} min?",
                           minutes=shown), parent=self.root)
                if not confirmed:
                    return
            scheduler = getattr(self.app, "schedule_power_action", None)
            if not callable(scheduler):
                return
            try:
                scheduler(action, delay)
            except Exception as exc:
                status_var.set(
                    self.t("Power action failed: {error}", error=exc))
                self._update_power_status()
                return
            self._update_power_status()
            if delay > 0:
                self.root.withdraw()
                self._show_countdown(action, delay)

        def cancel_power() -> None:
            canceller = getattr(self.app, "cancel_power_action", None)
            if callable(canceller):
                try:
                    canceller()
                except Exception as exc:
                    status_var.set(
                        self.t("Power action failed: {error}", error=exc))
            self._close_countdown(restore=True)
            self._update_power_status()

        buttons = ttk.Frame(card, style="Card.TFrame")
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text=self.t("Schedule"),
                   style="Accent.TButton", command=plan_power).pack(side=start)
        self._power_cancel_btn = ttk.Button(
            buttons, text=self.t("Cancel power action"),
            style="Danger.TButton", command=cancel_power, state="disabled")
        self._power_cancel_btn.pack(side=start, padx=_pad(self.lang, 8, 0))
        ttk.Label(card, textvariable=status_var, style="CardMuted.TLabel",
                  justify=just, wraplength=int(620 * self.scale)).pack(
                      fill="x", anchor=near, pady=(10, 0))
        self._update_power_status()
        self._power_job = self.root.after(1000, self._refresh_power_status)

    def _card(self, parent, *, side: str = "x", padx=None, pady=None,
              padding=None, expand: bool = False) -> ttk.Frame:
        """A card with a hairline border, for a more finished look."""
        wrap = tk.Frame(parent, bg=self.pal["border"], bd=0)
        wrap.pack(fill=side, expand=expand, padx=padx, pady=pady)
        card = ttk.Frame(wrap, style="Card.TFrame",
                         padding=padding or (PAD_L, PAD_L))
        card.pack(fill="both", expand=True, padx=1, pady=1)
        return card

    def _update_nav_styles(self) -> None:
        for entry in getattr(self, "_nav_rows", {}).values():
            try:
                entry["paint"]()
            except (tk.TclError, KeyError):
                pass

    def _stop_page_animation(self) -> None:
        job = getattr(self, "_page_job", None)
        if job is not None:
            try:
                self.root.after_cancel(job)
            except (tk.TclError, ValueError):
                pass
        self._page_job = None
        overlay = getattr(self, "_page_overlay", None)
        if overlay is not None:
            try:
                overlay.destroy()
            except tk.TclError:
                pass
        self._page_overlay = None
        if not getattr(self, "_page_anim", False):
            return
        for page in getattr(self, "_pages", {}).values():
            try:
                page.place_forget()
            except tk.TclError:
                pass
        page = getattr(self, "_pages", {}).get(
            getattr(self, "_active_page", "shortcuts"))
        if page is not None:
            try:
                page.grid(row=0, column=0, sticky="nsew")
            except tk.TclError:
                pass
        self._page_anim = False

    def _show_page(self, name: str, animate: bool = True,
                   force: bool = False) -> None:
        pages = getattr(self, "_pages", {})
        if name not in pages:
            return
        previous = getattr(self, "_active_page", "shortcuts")
        if name == previous and not force:
            self._update_nav_styles()
            return
        self._stop_page_animation()
        self._active_page = name
        self._update_nav_styles()
        if animate and previous in pages and previous != name:
            self._animate_page_switch(previous, name)
            return
        for key, page in pages.items():
            try:
                if key == name:
                    page.grid(row=0, column=0, sticky="nsew")
                    page.tkraise()
                else:
                    page.grid_remove()
            except tk.TclError:
                pass

    def _animate_page_switch(self, old_name: str, new_name: str) -> None:
        """Short cross-fade + slide, built only from stdlib Tk primitives."""
        pages = getattr(self, "_pages", {})
        old, new = pages[old_name], pages[new_name]
        order = ("shortcuts", "power")
        forward = order.index(new_name) > order.index(old_name)
        direction = (1 if forward else -1) * (-1 if self.rtl else 1)
        distance = max(8, int(18 * self.scale))
        fades = ("", "gray12", "gray25", "gray50", "gray75")
        reveal_fades = tuple(reversed(fades))
        self._page_anim = True

        old.grid_forget()
        new.grid_forget()
        old.place(x=0, y=0, relwidth=1, relheight=1)
        new.place(x=direction * distance, y=0, relwidth=1, relheight=1)
        new.tkraise()

        overlay = tk.Canvas(self.page_host, highlightthickness=0, bd=0,
                            bg=self.pal["bg"])
        rect = overlay.create_rectangle(0, 0, 4, 4, fill=self.pal["bg"],
                                        stipple="")
        overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.page_host.tk.call("raise", str(overlay))
        self._page_overlay = overlay

        def resize(_event=None) -> None:
            try:
                overlay.coords(rect, 0, 0,
                               max(1, overlay.winfo_width()),
                               max(1, overlay.winfo_height()))
            except tk.TclError:
                pass

        overlay.bind("<Configure>", resize)
        resize()

        def fade_out(step: int) -> None:
            if not self._page_anim:
                return
            if step >= len(fades):
                old.place_forget()
                reveal(0)
                return
            progress = step / (len(fades) - 1)
            overlay.itemconfigure(rect, stipple=fades[step])
            old.place(x=int(-direction * distance * progress), y=0,
                      relwidth=1, relheight=1)
            self._page_job = self.root.after(18, lambda: fade_out(step + 1))

        def reveal(step: int) -> None:
            if not self._page_anim:
                return
            if step >= len(reveal_fades):
                try:
                    overlay.destroy()
                except tk.TclError:
                    pass
                self._page_overlay = None
                new.place_forget()
                new.grid(row=0, column=0, sticky="nsew")
                self._page_anim = False
                self._page_job = None
                return
            progress = step / (len(reveal_fades) - 1)
            overlay.itemconfigure(rect, stipple=reveal_fades[step])
            new.place(x=int(direction * distance * (1 - progress)), y=0,
                      relwidth=1, relheight=1)
            self._page_job = self.root.after(18, lambda: reveal(step + 1))

        fade_out(0)

    def _apply_style(self) -> None:
        p = self.pal
        try:
            self.root.tk.call("tk", "scaling", self.scale)
        except tk.TclError:
            pass
        s = ttk.Style(self.root)
        s.theme_use("clam")
        body = _font(10)
        s.configure(".", background=p["bg"], foreground=p["fg"], font=body,
                    focuscolor=p["accent"])
        s.configure("TFrame", background=p["bg"])
        s.configure("TSeparator", background=p["border"])
        s.configure("Card.TFrame", background=p["panel"])
        s.configure("TLabel", background=p["bg"], foreground=p["fg"])
        s.configure("Card.TLabel", background=p["panel"], foreground=p["fg"],
                    font=_font(10))
        s.configure("Muted.TLabel", foreground=p["muted"], font=_font(10))
        s.configure("CardMuted.TLabel", background=p["panel"],
                    foreground=p["muted"], font=_font(10))
        s.configure("Warning.TLabel", foreground=p["error"], font=_font(10, "bold"))
        s.configure("Title.TLabel", font=_font(22, "bold"))
        s.configure("Brand.TLabel", font=_symbol_font(22),
                    foreground=p["accent"], background=p["bg"])
        s.configure("Section.TLabel", foreground=p["muted"], font=_font(10, "bold"))
        s.configure("Sub.TLabel", foreground=p["muted"], font=_font(11))
        s.configure("Badge.TLabel", background=p["panel2"], foreground=p["muted"],
                    font=_font(9), padding=(10, 5))
        s.configure("Sidebar.TFrame", background=p["panel"])
        s.configure("SidebarHeading.TLabel", background=p["panel"],
                    foreground=p["muted"], font=_font(10, "bold"))
        s.configure("SidebarFoot.TLabel", background=p["panel"],
                    foreground=p["muted"], font=_font(9))
        s.configure("Hero.TFrame", background=p["panel2"])
        s.configure("Hero.TLabel", background=p["panel2"], foreground=p["fg"],
                    font=_font(13, "bold"))
        s.configure("Sidebar.TButton", background=p["panel"],
                    foreground=p["muted"], borderwidth=0,
                    bordercolor=p["panel"], lightcolor=p["panel"],
                    darkcolor=p["panel"], relief="flat",
                    anchor=_near(self.lang),
                    padding=(16, 12), font=_font(11, "bold"))
        s.configure("SidebarActive.TButton", background=p["sel"],
                    foreground=p["accent"], borderwidth=0,
                    bordercolor=p["sel"], lightcolor=p["sel"],
                    darkcolor=p["sel"], relief="flat",
                    anchor=_near(self.lang),
                    padding=(16, 12), font=_font(11, "bold"))
        s.map("Sidebar.TButton", background=[("active", p["hover"])],
              foreground=[("active", p["fg"])])
        s.map("SidebarActive.TButton", background=[("active", p["hover"])],
              foreground=[("active", p["accent_hover"])])
        s.configure("TButton", background=p["panel2"], foreground=p["fg"],
                    borderwidth=0, padding=(16, 10), focusthickness=2,
                    font=_font(10))
        s.configure("Icon.TButton", font=_symbol_font(12), padding=(10, 9))
        s.map("TButton", background=[("active", p["hover"]), ("disabled", p["panel2"])])
        s.configure("Accent.TButton", background=p["accent"], foreground=p["accent_fg"],
                    borderwidth=0, padding=(20, 11), font=_font(11, "bold"))
        s.map("Accent.TButton", background=[("active", p["accent_hover"]),
                                            ("disabled", p["panel2"])],
              foreground=[("disabled", p["muted"])])
        s.configure("Danger.TButton", background=p["panel2"], foreground=p["error"])
        s.map("Danger.TButton", background=[("active", p["hover"])])
        s.configure("Treeview", background=p["panel"], fieldbackground=p["panel"],
                    foreground=p["fg"], borderwidth=0, relief="flat",
                    bordercolor=p["panel"], lightcolor=p["panel"],
                    darkcolor=p["panel"], rowheight=int(40 * self.scale))
        s.configure("Treeview.Heading", background=p["panel"], foreground=p["muted"],
                    relief="flat", borderwidth=0, font=_font(10, "bold"),
                    padding=(8, 10))
        s.map("Treeview.Heading", background=[("active", p["panel"])])
        s.map("Treeview", background=[("selected", p["sel"])],
              foreground=[("selected", p["fg"])])
        s.configure("TEntry", fieldbackground=p["panel2"], foreground=p["fg"],
                    insertcolor=p["fg"], borderwidth=1, padding=9,
                    bordercolor=p["border"], lightcolor=p["panel2"],
                    darkcolor=p["panel2"], focuscolor=p["accent"])
        s.configure("TSpinbox", fieldbackground=p["panel2"],
                    background=p["panel2"], foreground=p["fg"],
                    arrowcolor=p["muted"], borderwidth=1, padding=8,
                    bordercolor=p["border"], lightcolor=p["panel2"],
                    darkcolor=p["panel2"], focuscolor=p["accent"])
        s.map("TSpinbox",
              fieldbackground=[("readonly", p["panel2"])],
              background=[("active", p["hover"])],
              foreground=[("disabled", p["muted"])],
              arrowcolor=[("active", p["accent"])])
        s.configure("TCombobox", fieldbackground=p["panel2"], background=p["panel2"],
                    foreground=p["fg"], arrowcolor=p["muted"], borderwidth=1,
                    padding=8, bordercolor=p["border"], lightcolor=p["panel2"],
                    darkcolor=p["panel2"], focuscolor=p["accent"])
        s.map("TCombobox", fieldbackground=[("readonly", p["panel2"])],
              background=[("readonly", p["panel2"]), ("active", p["panel2"])],
              foreground=[("readonly", p["fg"])],
              arrowcolor=[("active", p["accent"])])
        s.configure("TCheckbutton", background=p["bg"], foreground=p["fg"],
                    indicatorbackground=p["panel2"], indicatorforeground=p["accent"],
                    indicatormargin=(0, 0, 8, 0))
        s.map("TCheckbutton", background=[("active", p["bg"])])
        s.configure("Vertical.TScrollbar", background=p["panel2"], troughcolor=p["panel"],
                    bordercolor=p["panel"], arrowcolor=p["muted"], relief="flat",
                    lightcolor=p["panel2"], darkcolor=p["panel2"],
                    arrowsize=int(12 * self.scale))
        s.map("Vertical.TScrollbar", background=[("active", p["hover"])])
        s.configure("TScrollbar", background=p["panel2"], troughcolor=p["panel"],
                    bordercolor=p["panel"], arrowcolor=p["muted"],
                    lightcolor=p["panel2"], darkcolor=p["panel2"])
        self.root.option_add("*TCombobox*Listbox.background", p["panel2"])
        self.root.option_add("*TCombobox*Listbox.foreground", p["fg"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", p["accent"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", p["accent_fg"])

    def _build(self) -> None:
        p = self.pal
        r = self.root
        r.title(self.t("Hotkey — Settings"))
        r.configure(bg=p["bg"])
        r.protocol("WM_DELETE_WINDOW", self._close)
        r.minsize(int(720 * self.scale), int(480 * self.scale))
        _apply_window_icon(r)
        screen_w, screen_h = r.winfo_screenwidth(), r.winfo_screenheight()
        w = min(int(1020 * self.scale), max(int(720 * self.scale), screen_w - 24))
        h = min(int(660 * self.scale), max(int(480 * self.scale), screen_h - 24))
        x = max(0, (screen_w - w) // 2)
        y = max(0, (screen_h - h) // 2 - 20)
        r.geometry(f"{w}x{h}+{x}+{y}")
        self.status_var = tk.StringVar(master=r, value="")
        # Kept for callers that change language without the gear window.
        self.var_language = tk.StringVar(
            master=r, value=i18n.display(self.lang))

        start, end = _start(self.lang), _end(self.lang)
        near = _near(self.lang)
        just = _justify(self.lang)
        header = ttk.Frame(r, padding=(PAD_L, 14, PAD_L, 10))
        header.pack(fill="x")
        title_box = ttk.Frame(header)
        title_box.pack(side=start)
        title_text = ttk.Frame(title_box)
        title_text.pack(side=start)
        self.title_lbl = ttk.Label(
            title_text, text="Hotkey", style="Title.TLabel")
        self.title_lbl.pack(anchor=near)
        ttk.Label(title_text, text=self.t("Shortcuts & power"),
                  style="Sub.TLabel").pack(anchor=near)
        self.count_lbl = ttk.Label(header, text="", style="Badge.TLabel")
        self.count_lbl.pack(side=start, padx=_pad(self.lang, 18, 0))
        header_actions = ttk.Frame(header)
        header_actions.pack(side=end)
        self.btn_reload = ttk.Button(header_actions, text="Reload",
                                     command=self._reload)
        self.btn_reload.pack(side=start)

        btn_open = ttk.Button(header_actions, text="Open hotkeys.json",
                              command=self.app.open_config)
        btn_open.pack(side=start, padx=_pad(self.lang, 8))
        _tip(btn_open, self.status_var,
             self.t("Open hotkeys.json in your default editor"))

        self.btn_language = ttk.Button(
            header_actions, text="⚙", style="Icon.TButton",
            command=self._show_language_window)
        self.btn_language.pack(side=start, padx=_pad(self.lang, 8))
        _tip(self.btn_language, self.status_var,
             lambda: (f"{self.t('Quick settings')} · v{__version__} · "
                      f"{self.t('Show notifications')}: "
                      f"{self.t('On' if self._notifications_enabled() else 'Off')}"))
        _tip(self.btn_reload, self.status_var,
             self.t("Reload from disk (discards unsaved UI state)"))

        self._active_page = getattr(self, "_active_page", "shortcuts")
        self._sidebar_visible = True
        self._page_job = None
        self._page_overlay = None
        self._page_anim = False
        self._nav_buttons = {}
        self._nav_rows = {}

        ttk.Separator(r, orient="horizontal").pack(fill="x")

        main = ttk.Frame(r)
        main.pack(fill="both", expand=True)
        self.page_host = ttk.Frame(main)
        self.page_host.pack(side=end, fill="both", expand=True)
        self.sidebar = ttk.Frame(
            main, style="Sidebar.TFrame",
            width=int(216 * self.scale), padding=(12, 16))
        self.sidebar.pack(side=start, fill="y", before=self.page_host)
        self.sidebar.pack_propagate(False)
        ttk.Label(self.sidebar, text=self.t("Settings tools"),
                  style="SidebarHeading.TLabel", anchor=near,
                  justify=just).pack(fill="x", padx=_pad(self.lang, 8, 0),
                                     pady=(0, 14))
        for name, label, glyph in (
                ("shortcuts", "Shortcuts", "⌨"),
                ("power", "Power", "⏻")):
            row = tk.Frame(self.sidebar, bg=p["panel"], cursor="hand2")
            row.pack(fill="x", pady=(0, 6))
            bar = tk.Frame(row, bg=p["panel"], width=4)
            bar.pack(side=_start(self.lang), fill="y")
            icon = tk.Label(row, text=glyph, font=_symbol_font(13),
                            bg=p["panel"], fg=p["muted"], width=2)
            icon.pack(side=start, padx=_pad(self.lang, 12, 0), pady=11)
            text = tk.Label(row, text=self.t(label), font=_font(11, "bold"),
                            bg=p["panel"], fg=p["muted"], anchor=near)
            text.pack(side=start, fill="x", expand=True,
                      padx=_pad(self.lang, 10, 10), pady=11)
            entry = {"row": row, "icon": icon, "text": text, "bar": bar,
                     "label": label}
            self._nav_rows[name] = entry

            def paint(_hover: bool = False, _name=name, _entry=entry) -> None:
                active = _name == getattr(self, "_active_page", "shortcuts")
                bg = (p["hover"] if _hover else
                      p["sel"] if active else p["panel"])
                fg = p["accent"] if active else p["fg"]
                _entry["row"].configure(bg=bg)
                _entry["icon"].configure(bg=bg, fg=fg)
                _entry["text"].configure(bg=bg, fg=fg)
                _entry["bar"].configure(bg=p["accent"] if active else bg)

            entry["paint"] = paint
            row.invoke = lambda _name=name: self._show_page(_name)
            for widget in (row, icon, text):
                widget.bind(
                    "<Button-1>",
                    lambda _e, _name=name: self._show_page(_name))
                widget.bind(
                    "<Enter>", lambda _e, _paint=paint: _paint(True))
                widget.bind(
                    "<Leave>", lambda _e, _paint=paint: _paint(False))
        ttk.Label(self.sidebar, text=f"v{__version__}",
                  style="SidebarFoot.TLabel").place(
                      relx=0.0 if not self.rtl else 1.0, rely=1.0,
                      x=10 if not self.rtl else -10, y=-8,
                      anchor="nw" if not self.rtl else "ne")

        self.page_host.columnconfigure(0, weight=1)
        self.page_host.rowconfigure(0, weight=1)
        self.page_shortcuts = ttk.Frame(self.page_host)
        self.page_power = ttk.Frame(self.page_host)
        self._pages = {
            "shortcuts": self.page_shortcuts,
            "power": self.page_power,
        }

        self.banner = ttk.Frame(self.page_shortcuts,
                                padding=(PAD_L, 0, PAD_L, 6))
        self.banner_lbl = ttk.Label(self.banner, style="Warning.TLabel",
                                    justify=just)
        self.banner_lbl.pack(side=start)
        ttk.Button(self.banner, text="Open file", padding=(8, 3),
                   command=self.app.open_config).pack(side=end)

        self._after_banner = ttk.Separator(self.page_shortcuts,
                                           orient="horizontal")
        self._after_banner.pack(fill="x", padx=PAD_L)
        ttk.Label(self.page_shortcuts, text="SHORTCUTS",
                  style="Section.TLabel").pack(
                      anchor=near, padx=PAD_L, pady=(8, 2))

        bar = ttk.Frame(self.page_shortcuts, padding=(PAD_L, 4, PAD_L, 10))
        bar.pack(fill="x")
        bar_actions = ttk.Frame(bar)
        bar_actions.pack(side=start)
        self.btn_add = ttk.Button(bar_actions, text="+  Add hotkey",
                                  style="Accent.TButton", command=self._add)
        self.btn_add.pack(side=start)
        self.btn_edit = ttk.Button(bar_actions, text="Edit", state="disabled",
                                   command=self._edit_selected)
        self.btn_edit.pack(side=start, padx=_pad(self.lang, 8))
        self.btn_delete = ttk.Button(bar_actions, text="Delete",
                                     style="Danger.TButton", state="disabled",
                                     command=self._delete_selected)
        self.btn_delete.pack(side=start, padx=_pad(self.lang, 8))
        self.hint = ttk.Label(bar, text="Double-click a row to edit",
                              style="Muted.TLabel", justify=just)
        self.hint.pack(side=end, pady=(8, 0))
        profile_box = ttk.Frame(bar)
        profile_box.pack(side=end, padx=_pad(self.lang, 8))
        self.var_profile = tk.StringVar(
            master=self.root, value=(self.app.cfg.active_profile or "(none)"))
        ttk.Label(profile_box, text="Profile:", style="Muted.TLabel").pack(
            side=start)
        self.cmb_profile = ttk.Combobox(
            profile_box, textvariable=self.var_profile, state="readonly",
            width=14, values=["(none)"] + list(self.app.profile_names()))
        self.cmb_profile.pack(side=start, padx=_pad(self.lang, 8))
        self.cmb_profile.bind("<<ComboboxSelected>>",
                             lambda _e: self._switch_profile())

        card = self._card(self.page_shortcuts, side="both", padx=PAD_L,
                          pady=(0, PAD_L), padding=(PAD + 4, PAD + 4),
                          expand=True)
        tree_col, scroll_col = (1, 0) if self.rtl else (0, 1)
        card.columnconfigure(tree_col, weight=1)
        card.columnconfigure(scroll_col, weight=0)
        card.rowconfigure(0, weight=1)
        base_columns = ("keys", "keyinfo", "trigger", "action",
                        "scope", "detail", "on")
        columns = tuple(reversed(base_columns)) if self.rtl else base_columns
        self.tree = ttk.Treeview(card, columns=columns, show="headings",
                                 selectmode="browse")
        headings = {
            "keys": "Shortcut",
            "keyinfo": "Key info",
            "trigger": "Trigger",
            "action": "Action",
            "scope": "Where",
            "detail": "Target / note",
            "on": "State",
        }
        for column, heading in headings.items():
            self.tree.heading(
                column, text=heading,
                anchor="center" if column == "on" else near)
        widths = {
            "keys": 160, "keyinfo": 150, "trigger": 105,
            "action": 100, "scope": 150, "detail": 250, "on": 48,
        }
        for column, width in widths.items():
            self.tree.column(
                column, width=int(width * self.scale),
                minwidth=int(max(40, width * 0.6) * self.scale),
                anchor="center" if column == "on" else near,
                stretch=(column == "detail"))
        self.empty = ttk.Label(
            card, text="No hotkeys yet.\nClick “+ Add hotkey” or press Ctrl+N to create one.",
            style="Muted.TLabel", justify=just)
        self.empty.place(relx=0.55 if self.rtl else 0.45,
                         rely=0.45, anchor="center")
        yscroll = ttk.Scrollbar(card, orient="vertical", command=self.tree.yview)
        yscroll.grid(row=0, column=scroll_col, sticky="ns")
        xscroll = ttk.Scrollbar(card, orient="horizontal", command=self.tree.xview)
        xscroll.grid(row=1, column=tree_col, sticky="ew")
        self.tree.grid(row=0, column=tree_col, sticky="nsew")
        self.tree.configure(yscrollcommand=yscroll.set,
                            xscrollcommand=xscroll.set)
        self.tree.tag_configure("off", foreground=p["muted"])
        self.tree.tag_configure("fired", background=p["accent"],
                                foreground=p["accent_fg"])
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._update_buttons())
        self.tree.bind("<Double-1>", lambda _e: self._edit_selected())
        self.tree.bind("<Return>", lambda _e: self._edit_selected())
        self.tree.bind("<Delete>", lambda _e: self._delete_selected())

        self._build_power_page(self.page_power)
        self._show_page(self._active_page, animate=False, force=True)

        foot = ttk.Frame(r, padding=(PAD_L, 10, PAD_L, 14))
        foot.pack(fill="x")
        foot_end = ttk.Frame(foot)
        foot_end.pack(side=end)
        self.status = ttk.Label(foot_end, textvariable=self.status_var,
                                style="Muted.TLabel", justify=just)
        self.status.pack(side=end)

        self.root.bind("<Control-n>", lambda _e: self._add())
        self.root.bind("<Control-e>", lambda _e: self._edit_selected())
        self.root.update_idletasks()
        win32.set_dark_titlebar(self.root.winfo_id(), p["dark"])

        self._refresh()

    def _refresh(self) -> None:
        selected = self._selection()
        self.tree.delete(*self.tree.get_children())
        enabled = sum(1 for e in self.entries if e.enabled)
        total = len(self.entries)
        scoped = sum(1 for e in self.entries if e.apps)
        profs = sum(1 for e in self.entries if e.profiles)
        self.count_lbl.configure(
            text=self.t("{count} shortcuts · {enabled} active", count=total, enabled=enabled)
                 + (self.t(" · {count} per-app", count=scoped) if scoped else "")
                 + (self.t(" · {count} profiled", count=profs) if profs else ""))
        for i, entry in enumerate(self.entries):
            values = (
                entry.display,
                _key_info(entry, self.t),
                _trigger_label(entry.trigger, self.t),
                _short_action(entry.action, self.lang),
                _entry_scope(entry, self.t),
                _entry_detail(entry, self.t),
                self.t("On") if entry.enabled else self.t("Off"),
            )
            self.tree.insert("", "end", iid=str(i),
                             values=tuple(reversed(values)) if self.rtl else values,
                             tags=() if entry.enabled else ("off",))
        if selected is not None and selected < len(self.entries):
            self.tree.selection_set(str(selected))
            self.tree.see(str(selected))
        if self.entries:
            self.empty.place_forget()
        else:
            self.empty.lift()
            self.empty.place(relx=0.55 if self.rtl else 0.45,
                             rely=0.45, anchor="center")
        self._update_banner()
        self._base_status = self.t("Saved to hotkeys.json · {count} active",
                                   count=enabled)
        self.status_var.set(self._base_status)
        self.status.configure(foreground=self.pal["muted"])
        self._update_buttons()

    def _update_buttons(self) -> None:
        index = self._selection()
        has_selection = index is not None
        self.btn_edit.configure(state="normal" if has_selection else "disabled")
        self.btn_delete.configure(state="normal" if has_selection else "disabled")
        summary = self._selection_summary(index)
        if summary:
            self.status_var.set(summary)

    def _selection_summary(self, index: int | None = None) -> str:
        """Full one-line description shown while a shortcut row is selected."""
        if index is None:
            index = self._selection()
        if index is None or index >= len(self.entries):
            return getattr(self, "_base_status", "")
        entry = self.entries[index]
        parts = [
            entry.display,
            _key_info(entry, self.t),
            _trigger_label(entry.trigger, self.t),
            _short_action(entry.action, self.lang),
            _entry_scope(entry, self.t),
            _entry_detail(entry, self.t),
            self.t("On") if entry.enabled else self.t("Off"),
        ]
        return "   ·   ".join(part for part in parts if part)

    def _update_banner(self) -> None:
        problems = len(self.cfg.errors) + len(self.cfg.warnings)
        if not problems:
            self.banner.pack_forget()
            return
        key = ("⚠ {count} config problem — some hotkeys may be inactive"
               if problems == 1 else
               "⚠ {count} config problems — some hotkeys may be inactive")
        self.banner_lbl.configure(text=self.t(key, count=problems))
        self.banner.pack(before=self._after_banner, fill="x")

    def _status(self, text: str, error: bool = False) -> None:
        job = getattr(self, "_status_job", None)
        if job is not None:
            try:
                self.root.after_cancel(job)
            except tk.TclError:
                pass
        self.status_var.set(text)
        self.status.configure(foreground=self.pal["error"] if error else self.pal["muted"])
        self._status_job = self.root.after(5000, self._clear_status)

    def _clear_status(self) -> None:
        self._status_job = None
        self.status_var.set(getattr(self, "_base_status", ""))
        self.status.configure(foreground=self.pal["muted"])

    def _selection(self) -> int | None:
        sel = self.tree.selection()
        if not sel:
            return None
        try:
            return int(sel[0])
        except ValueError:
            return None

    def _poll_fire_events(self) -> None:
        events = getattr(self.app, "fire_events", None)
        if events is not None:
            try:
                while True:
                    self._flash_row(events.get_nowait())
            except queue.Empty:
                pass
        self._fire_job = self.root.after(80, self._poll_fire_events)

    def _flash_row(self, index: int) -> None:
        iid = str(index)
        if iid not in self.tree.get_children():
            return
        old = self._flash_jobs.pop(iid, None)
        if old is not None:
            previous = old[1]
            try:
                self.root.after_cancel(old[0])
            except tk.TclError:
                pass
        else:
            previous = tuple(self.tree.item(iid, "tags"))
        self.tree.selection_set(iid)
        self.tree.see(iid)
        self.tree.item(iid, tags=("fired",))

        def clear() -> None:
            self._flash_jobs.pop(iid, None)
            try:
                self.tree.item(iid, tags=previous)
            except tk.TclError:
                pass

        job = self.root.after(700, clear)
        self._flash_jobs[iid] = (job, previous)
        entry = next((e for e in self.entries if e.index == index), None)
        if entry is not None:
            self._status(self.t("Fired: {name}", name=entry.display))

    def _save(self, message: str | None = None) -> bool:
        # Read again right before writing: the macro panel may have saved a
        # Start/Stop key while this window was open. Keep current settings
        # (plus only the ones this window changed) and unknown keys intact.
        current = config.load(self.path)
        raw = dict(current.raw or {})
        raw["version"] = 1
        raw["hotkeys"] = [e.to_json() for e in self.entries]
        settings = dict(current.settings)
        settings.update(self.pending_settings)
        raw["settings"] = settings
        try:
            config.save_raw(self.path, raw)
        except OSError as exc:
            messagebox.showerror(
                self.t("Hotkey"),
                self.t("Could not save hotkeys.json:\n{error}", error=exc),
                parent=self.root)
            return False
        self.pending_settings.clear()
        self.app.request_reload()
        self.cfg = config.load(self.path)
        self.raw = self.cfg.raw or {}
        self.settings = dict(self.cfg.settings)
        self._refresh()
        self._status(message or self.t("Saved · hotkeys reloaded"))
        return True

    def _reload(self) -> None:
        self._close_language_window()
        cfg = config.load(self.path)
        self.cfg = cfg
        self.raw = cfg.raw or {}
        self.settings = dict(cfg.settings)
        self.lang = i18n.normalize(self.settings.get("language"))
        self.rtl = i18n.is_rtl(self.lang)
        self.pending_settings.clear()
        self.entries = list(cfg.entries)
        self._refresh()
        if hasattr(self, "cmb_profile"):
            self.var_profile.set(cfg.active_profile or "(none)")
            self.cmb_profile.configure(values=["(none)"] + list(self.app.profile_names()))
        if hasattr(self, "var_language"):
            self.var_language.set(i18n.display(self.lang))
            _translate_widgets(self.root, self.t)
        if cfg.errors:
            messagebox.showerror(self.t("Hotkey"), "\n".join(cfg.errors), parent=self.root)
            return
        self._status(self.t("Reloaded from disk"))

    def _select_row(self, index: int | None) -> None:
        if index is None or index < 0:
            return
        iid = str(index)
        if iid in self.tree.get_children():
            self.tree.selection_set(iid)
            self.tree.see(iid)

    def _switch_profile(self) -> None:
        name = self.var_profile.get()
        if name == "(none)":
            name = ""
        try:
            self.app.set_profile(name)
        except Exception as exc:
            messagebox.showerror(self.t("Hotkey"), str(exc), parent=self.root)
            return
        self._reload()

    def _add(self) -> None:
        entry = Editor(self, None).result
        if entry is None:
            return
        entry.index = len(self.entries)
        self.entries.append(entry)
        if self._save(self.t("Added {name}", name=entry.display)):
            self._select_row(len(self.entries) - 1)

    def _edit_selected(self) -> None:
        idx = self._selection()
        if idx is None:
            self._status(self.t("Select a hotkey first"), error=True)
            return
        entry = Editor(self, self.entries[idx]).result
        if entry is None:
            return
        entry.index = idx
        self.entries[idx] = entry
        if self._save(self.t("Updated {name}", name=entry.display)):
            self._select_row(idx)

    def _delete_selected(self) -> None:
        idx = self._selection()
        if idx is None:
            self._status(self.t("Select a hotkey first"), error=True)
            return
        entry = self.entries[idx]
        if not messagebox.askyesno(
                self.t("Delete hotkey"),
                self.t("Delete {name} ({label})?",
                       name=entry.display, label=entry.label()),
                parent=self.root):
            return
        del self.entries[idx]
        for i, item in enumerate(self.entries):
            item.index = i
        next_index = min(idx, len(self.entries) - 1)
        if self._save(self.t("Deleted {name}", name=entry.display)):
            self._select_row(next_index)

    def _close(self) -> None:
        try:
            if not self.root.winfo_exists():
                return
        except tk.TclError:
            return
        self._close_countdown(restore=False)
        for attr in ("_fire_job", "_status_job", "_power_job", "_page_job"):
            job = getattr(self, attr, None)
            if job is not None:
                try:
                    self.root.after_cancel(job)
                except (tk.TclError, ValueError):
                    pass
        for job, _previous in self._flash_jobs.values():
            try:
                self.root.after_cancel(job)
            except tk.TclError:
                pass
        self._close_language_window()
        self.root.destroy()

    def run(self) -> None:
        self._apply_style()
        self._build()
        _translate_widgets(self.root, self.t)
        self.root.deiconify()
        self._fire_job = self.root.after(80, self._poll_fire_events)
        self.root.mainloop()


class Editor:
    def __init__(self, owner: SettingsWindow, entry: config.Entry | None):
        self.owner = owner
        self.pal = owner.pal
        self.scale = owner.scale
        self.lang = i18n.normalize(getattr(owner, "lang", "en"))
        self.rtl = i18n.is_rtl(self.lang)
        self.original = entry
        self.result: config.Entry | None = None
        self._capture = True
        self._held_keys: list[int] = []
        self._chord_done = False
        self._typing_mode = False
        self._detecting = False
        self._detect_job: str | None = None
        self._seq_mode = bool(entry and getattr(entry, "seq", ()))
        self._seq_steps: list = list(entry.seq) if (entry and getattr(entry, "seq", ())) else []
        self._macro_steps: list = list((entry.extra.get("steps") if entry else []) or [])
        try:
            self._macro_speed = float((entry.extra.get("speed") if entry else 1.0) or 1.0)
        except (TypeError, ValueError):
            self._macro_speed = 1.0
        self._recording = False
        self._rec_hook = None
        self._rec_mouse_hook = None
        self._rec_status = None
        self._rec_queue = None
        self._rec_pending = None
        self._rec_last_end = 0.0
        self._rec_started = 0.0
        self._rec_poll_job = None
        self._poll_job = None
        self._scroll_job = None
        self._focus_job = None

        self.top = tk.Toplevel(owner.root)
        self.top.withdraw()
        self.top.title(self.t("Edit hotkey" if entry else "New hotkey"))
        self.top.configure(bg=self.pal["bg"])
        _apply_window_icon(self.top)
        self.top.transient(owner.root)
        self.top.resizable(False, True)
        self._build()
        _translate_widgets(self.top, self.t)
        self._center()
        self.top.grab_set()
        self.top.deiconify()
        self.top.update_idletasks()
        win32.set_dark_titlebar(self.top.winfo_id(), self.pal["dark"])
        self._take_focus()
        self._pause_app(True, capture=True)
        self._poll_job = self.top.after(100, self._poll_mouse)
        try:
            owner.root.wait_window(self.top)
        finally:
            self._pause_app(False)

    def t(self, text: str, **kwargs: object) -> str:
        return i18n.tr(text, self.lang, **kwargs)

    def _pause_app(self, paused: bool, capture: bool = False) -> None:
        """Silence the tray app while a shortcut is being recorded.

        Otherwise pressing the buttons you are recording runs the old
        hotkey (copy/paste, chords) inside this dialog.  Capture mode also
        keeps the side buttons swallowed so they cannot act as Back/Forward.
        """
        pause = getattr(getattr(self.owner, "app", None), "pause_hotkeys", None)
        if pause is None:
            return
        try:
            pause(paused, capture=capture)
        except TypeError:  # older App with the one-argument API
            try:
                pause(paused)
            except Exception:
                pass
        except Exception:
            pass

    def _center(self) -> None:
        """Place the dialog in the middle of the screen (above the taskbar)."""
        self.top.update_idletasks()
        form = getattr(self, "_form", None)
        footer = getattr(self, "_footer", None)
        scrollbar = getattr(self, "_scrollbar", None)
        form_w = form.winfo_reqwidth() if form else 0
        footer_w = footer.winfo_reqwidth() if footer else 0
        bar_w = scrollbar.winfo_reqwidth() if scrollbar else 0
        width = max(
            self.top.winfo_reqwidth(),
            form_w + bar_w + int(48 * self.scale),
            footer_w + int(48 * self.scale),
            int(620 * self.scale),
        )
        try:
            left, upper, right, lower = win32.get_work_area()
            screen_w, screen_h = right - left, lower - upper
        except Exception:
            left = upper = 0
            screen_w = self.top.winfo_screenwidth()
            screen_h = self.top.winfo_screenheight()
        form_h = form.winfo_reqheight() if form else 0
        footer_h = footer.winfo_reqheight() if footer else int(80 * self.scale)
        wanted = form_h + footer_h + int(70 * self.scale)
        height = min(max(wanted, int(460 * self.scale)), screen_h - 24)
        width = min(width, screen_w - 24)
        x = left + max(0, (screen_w - width) // 2)
        y = upper + max(0, (screen_h - height) // 2)
        self.top.geometry(f"{width}x{height}+{x}+{y}")

    def _queue_scroll_refresh(self) -> None:
        """Recompute the form's scroll region after dynamic fields change."""
        if getattr(self, "_scroll_job", None):
            return
        try:
            self._scroll_job = self.top.after_idle(self._refresh_scrollregion)
        except tk.TclError:
            pass

    def _refresh_scrollregion(self) -> None:
        self._scroll_job = None
        canvas = getattr(self, "_canvas", None)
        form = getattr(self, "_form", None)
        win = getattr(self, "_form_win", None)
        if canvas is None or form is None or win is None:
            return
        try:
            canvas.itemconfigure(win, width=max(1, canvas.winfo_width()))
            canvas.configure(scrollregion=canvas.bbox("all"))
        except tk.TclError:
            pass

    def _stop_jobs(self) -> None:
        """Cancel pending Tk callbacks before the dialog is destroyed."""
        for name in ("_poll_job", "_scroll_job", "_rec_poll_job", "_detect_job",
                     "_focus_job"):
            job = getattr(self, name, None)
            if job is None:
                continue
            try:
                self.top.after_cancel(job)
            except tk.TclError:
                pass
            setattr(self, name, None)

    def _on_mousewheel(self, event) -> None:
        canvas = getattr(self, "_canvas", None)
        if canvas is None:
            return
        try:
            region = canvas.cget("scrollregion")
            if not region:
                return
            _x1, y1, _x2, y2 = (float(v) for v in region.split())
            view_h = canvas.winfo_height()
            if y2 - y1 <= view_h:
                return
            step = -1 if event.delta > 0 else 1
            canvas.yview_scroll(step * 3, "units")
        except (tk.TclError, ValueError):
            return

    def _take_focus(self) -> None:
        """Make the dialog really own the keyboard on Windows.

        A tray app runs in the background, and Windows then blocks a plain
        focus_force(): the window shows up but swallows every key press, so
        shortcuts are never captured.  A short topmost pulse plus focusing
        the shortcut field fixes that without asking the user to click.
        """
        try:
            self.top.lift()
            self.top.attributes("-topmost", True)
            self.top.focus_force()
            self.ent_keys.focus_set()
        except tk.TclError:
            return
        self._focus_job = self.top.after(180, self._settle_focus)

    def _settle_focus(self) -> None:
        self._focus_job = None
        try:
            self.top.attributes("-topmost", False)
            self.top.focus_force()
            self.ent_keys.focus_set()
        except tk.TclError:
            pass

    def _label(self, parent, text: str, row: int, hint: str = "") -> None:
        label_col, hint_col = _columns(self.lang)
        just = _justify(self.lang)
        hint_just = "left" if self.rtl else "right"
        ttk.Label(parent, text=text, justify=just).grid(
            row=row, column=label_col, sticky=_near(self.lang), pady=(10, 2))
        if hint:
            ttk.Label(parent, text=hint, style="Muted.TLabel",
                      font=_font(8), justify=hint_just).grid(
                row=row, column=hint_col, sticky=_far(self.lang), pady=(10, 2))

    def _validate_keys(self) -> None:
        """Show immediately whether the captured shortcut is usable."""
        if not hasattr(self, "key_hint"):
            return
        combo = self.var_keys.get().strip()
        if not combo:
            self.key_hint.configure(
                text=self.t("Press a key or mouse button to capture it…"),
                foreground=self.pal["muted"])
            return
        try:
            if self._seq_mode or ">" in combo:
                seq = keys.parse_sequence(combo)
                text = self.t("Leader sequence · {count} steps", count=len(seq))
            else:
                mods, vks = keys.parse_all(combo)
                text = keys.format_many(mods, vks)
                if len(vks) > 1:
                    text += self.t(" · chord")
            self.key_hint.configure(text=f"✓ {text}", foreground=self.pal["accent"])
        except keys.HotkeyError as exc:
            self.key_hint.configure(text=f"⚠ {self.t(str(exc))}",
                                    foreground=self.pal["error"])

    def _build(self) -> None:
        p = self.pal
        start, end = _start(self.lang), _end(self.lang)
        near = _near(self.lang)
        just = _justify(self.lang)
        label_col, value_col = _columns(self.lang)
        outer = ttk.Frame(self.top, padding=(22, 18, 22, 16))
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        # The form scrolls in its own row.  The action bar and error label live
        # in fixed rows below it, so the scrollbar can never cover them.
        scroll_area = ttk.Frame(outer)
        scroll_area.grid(row=0, column=0, sticky="nsew")
        canvas_col, scroll_col = (1, 0) if self.rtl else (0, 1)
        scroll_area.columnconfigure(canvas_col, weight=1)
        scroll_area.columnconfigure(scroll_col, weight=0)
        scroll_area.rowconfigure(0, weight=1)
        canvas = tk.Canvas(scroll_area, highlightthickness=0, bg=p["bg"], bd=0,
                           width=int(560 * self.scale),
                           height=int(300 * self.scale))
        self._scrollbar = ttk.Scrollbar(scroll_area, orient="vertical",
                                        command=canvas.yview)
        canvas.grid(row=0, column=canvas_col, sticky="nsew")
        self._scrollbar.grid(row=0, column=scroll_col, sticky="ns")
        canvas.configure(yscrollcommand=self._scrollbar.set)
        form = ttk.Frame(canvas, padding=_pad(self.lang, 0, 8))
        self._form = form
        self._canvas = canvas
        self._form_win = canvas.create_window(
            (0, 0), window=form, anchor="ne" if self.rtl else "nw")
        form.bind("<Configure>", lambda _e: self._queue_scroll_refresh())
        canvas.bind("<Configure>", lambda _e: self._queue_scroll_refresh())
        self.top.bind("<MouseWheel>", self._on_mousewheel)
        def on_destroy(event) -> None:
            # Child widgets also send <Destroy> to the toplevel bindtag.
            # Only the dialog itself going away should cancel its jobs.
            if event.widget is self.top:
                self._stop_jobs()

        self.top.bind("<Destroy>", on_destroy)
        form.columnconfigure(value_col, weight=1)

        # shortcut
        self._label(form, "Shortcut", 0, "press a key or mouse button")
        row = ttk.Frame(form)
        row.grid(row=1, column=0, columnspan=2, sticky="ew")
        entry_row = ttk.Frame(row)
        entry_row.pack(fill="x")
        self.var_keys = tk.StringVar(
            master=self.top,
            value=keys.format_sequence(self._seq_steps) if self._seq_steps
            else (self.original.keys if self.original else ""))
        self.ent_keys = ttk.Entry(entry_row, textvariable=self.var_keys, width=34,
                                  justify=just)
        self.ent_keys.pack(side=start, fill="x", expand=True)
        self.top.bind("<KeyPress>", self._on_press)
        self.top.bind("<KeyRelease>", self._on_release)
        # left/middle/right only on the field, so the dialog buttons stay usable
        for button in (1, 2, 3):
            self.ent_keys.bind(f"<Button-{button}>", self._on_mouse)
        # side buttons anywhere in the window
        self.top.bind("<Button-4>", self._on_mouse)
        self.top.bind("<Button-5>", self._on_mouse)
        self.btn_clear = ttk.Button(entry_row, text="Clear", width=7,
                                    command=self._clear)
        self.btn_clear.pack(side=start, padx=_pad(self.lang, 6))
        self.btn_type = ttk.Button(entry_row, text="Type", width=7,
                                   command=self._toggle_type)
        self.btn_type.pack(side=start, padx=_pad(self.lang, 6))
        self.btn_steps = ttk.Button(entry_row, text="Steps", width=7,
                                    command=self._toggle_steps)
        self.btn_steps.pack(side=start, padx=_pad(self.lang, 6))
        self.key_hint = ttk.Label(row, text="", style="Muted.TLabel",
                                  font=_font(8), justify=just)
        self.key_hint.pack(anchor=near, pady=(3, 0))
        self.var_keys.trace_add("write", lambda *_a: self._validate_keys())

        # action
        self._label(form, "Action", 2)
        self._action_by_label = {self.t(spec.label): name for name, spec in SPECS.items()}
        self.var_action = tk.StringVar(
            master=self.top,
            value=self.t(SPECS[self.original.action].label)
            if self.original and self.original.action in SPECS
            else self.t(SPECS["open"].label))
        combo = ttk.Combobox(form, textvariable=self.var_action, state="readonly",
                             values=list(self._action_by_label), justify=just)
        combo.grid(row=3, column=0, columnspan=2, sticky="ew")
        combo.bind("<<ComboboxSelected>>", lambda _e: self._sync_fields())

        # trigger
        self._label(form, "Trigger", 4, "single keys only")
        self._trigger_by_label = {self.t(label): key
                                  for key, label in TRIGGER_LABELS.items()}
        self._trigger_choices = [self.t(TRIGGER_LABELS[k])
                                 for k in ("press", "double", "hold", "tap")]
        self._trigger_press = self.t(TRIGGER_LABELS["press"])
        trigger_key = self.original.trigger if self.original else "press"
        # Map the stored trigger key ("hold") to its display label.  Looking
        # the key up in _trigger_by_label (which is keyed by labels) always
        # fell back to "press", so reopening a hold/double entry showed
        # Instant and saving silently downgraded the trigger.
        self.var_trigger = tk.StringVar(
            master=self.top,
            value=_trigger_label(trigger_key, self.t))
        self.cmb_trigger = ttk.Combobox(form, textvariable=self.var_trigger, state="readonly",
                                       values=self._trigger_choices, justify=just)
        self.cmb_trigger.grid(row=5, column=0, columnspan=2, sticky="ew")

        # app scope
        self._label(form, "Only in app", 6, "blank = every app")
        app_row = ttk.Frame(form)
        app_row.grid(row=7, column=0, columnspan=2, sticky="ew")
        self.var_apps = tk.StringVar(
            master=self.top,
            value=", ".join(self.original.apps) if self.original else "")
        try:
            known = list(win32.list_running_apps())
        except Exception:
            known = []
        self.cmb_apps = ttk.Combobox(app_row, textvariable=self.var_apps,
                                     values=known, justify=just)
        self.cmb_apps.pack(side=start, fill="x", expand=True)
        self.btn_detect = ttk.Button(app_row, text="Detect", width=8,
                                     command=self._detect_app)
        self.btn_detect.pack(side=start, padx=_pad(self.lang, 6))
        self.btn_any = ttk.Button(app_row, text="Any", width=6,
                                  command=lambda: self.var_apps.set(""))
        self.btn_any.pack(side=start, padx=_pad(self.lang, 6))

        # profiles
        self._label(form, "Profiles", 8, "comma = only in those profiles")
        prof_row = ttk.Frame(form)
        prof_row.grid(row=9, column=0, columnspan=2, sticky="ew")
        self.var_profiles = tk.StringVar(
            master=self.top,
            value=", ".join(self.original.profiles) if self.original else "")
        try:
            known_profiles = list(self.owner.app.profile_names())
        except Exception:
            known_profiles = []
        self.cmb_profiles = ttk.Combobox(prof_row, textvariable=self.var_profiles,
                                        values=known_profiles, justify=just)
        self.cmb_profiles.pack(side=start, fill="x", expand=True)
        ttk.Button(prof_row, text="Any", width=6,
                   command=lambda: self.var_profiles.set("")).pack(
            side=start, padx=_pad(self.lang, 6))

        # dynamic value
        self.lbl_value = ttk.Label(form, text="Target", justify=just)
        self.lbl_value.grid(row=10, column=label_col, sticky=near, pady=(10, 2))
        self.value_holder = ttk.Frame(form)
        self.value_holder.grid(row=11, column=0, columnspan=2, sticky="ew")
        self.var_value = tk.StringVar(master=self.top)
        self.txt_value: tk.Text | None = None
        self.cmb_value: ttk.Combobox | None = None
        self.ent_value: ttk.Entry | None = None
        self.lbl_value_hint = ttk.Label(form, text="", style="Muted.TLabel",
                                        font=_font(8),
                                        wraplength=int(520 * self.scale),
                                        justify=just)
        self.lbl_value_hint.grid(row=12, column=0, columnspan=2,
                                 sticky=near, pady=(3, 0))

        # description
        self._label(form, "Description", 13, "optional")
        self.var_desc = tk.StringVar(
            master=self.top,
            value=self.original.description if self.original else "")
        self.ent_desc = ttk.Entry(form, textvariable=self.var_desc, justify=just)
        self.ent_desc.grid(row=14, column=0, columnspan=2, sticky="ew")

        # advanced (pretty-printed so a long option list stays readable)
        self._label(form, "Advanced JSON", 15, "cwd, fallback, repeat, paste, hold_ms…")
        extra = dict(self.original.extra) if self.original else {}
        extra.pop("steps", None)
        extra.pop("speed", None)
        extra_frame = ttk.Frame(form)
        extra_frame.grid(row=16, column=0, columnspan=2, sticky="ew")
        self.txt_extra = tk.Text(
            extra_frame, height=3, wrap="word", bg=p["panel2"], fg=p["fg"],
            insertbackground=p["fg"], relief="flat", font=_mono(9),
            padx=8, pady=6)
        self.txt_extra.tag_configure("align", justify=just)
        self.txt_extra.pack(side=start, fill="both", expand=True)
        extra_scroll = ttk.Scrollbar(extra_frame, orient="vertical",
                                     command=self.txt_extra.yview)
        extra_scroll.pack(side=end, fill="y")
        self.txt_extra.configure(yscrollcommand=extra_scroll.set)
        if extra:
            self.txt_extra.insert(
                "1.0", json.dumps(extra, indent=2, ensure_ascii=False), "align")

        self.var_enabled = tk.BooleanVar(
            master=self.top,
            value=self.original.enabled if self.original else True)
        ttk.Checkbutton(form, text="Enabled", variable=self.var_enabled,
                        justify=just).grid(
            row=17, column=label_col, sticky=near, pady=(12, 0))

        ttk.Separator(outer, orient="horizontal").grid(
            row=1, column=0, sticky="ew", pady=(12, 0))
        self._footer = ttk.Frame(outer)
        self._footer.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(self._footer, text="Save hotkey", style="Accent.TButton",
                   command=self._save).pack(side=end)
        ttk.Button(self._footer, text="Cancel",
                   command=self._cancel).pack(side=end, padx=_pad(self.lang, 0, 8))
        self.err = ttk.Label(outer, text="", foreground=p["error"],
                             justify=just)
        self.err.grid(row=3, column=0, sticky="ew", pady=(6, 0))

        self._sync_fields()
        self._validate_keys()
        self._queue_scroll_refresh()
        self.top.bind("<Escape>", lambda _e: self._cancel())
        self.ent_keys.focus_set()

    def _sync_fields(self) -> None:
        near = _near(self.lang)
        just = _justify(self.lang)
        action = self._action_by_label.get(self.var_action.get(), "open")
        spec = SPECS[action]
        for widget in self.value_holder.winfo_children():
            widget.destroy()
        self.ent_value = self.cmb_value = self.txt_value = None
        self.lbl_value.configure(text=self.t(spec.field or "Value"))
        self.lbl_value_hint.configure(text=self.t(spec.hint))
        current = self.original.value if (self.original and self.original.action == action) else ""
        if action == "summon":
            self.cmb_value = ttk.Combobox(
                self.value_holder, values=list(win32.list_running_apps()),
                justify=just)
            self.cmb_value.set(current)
            self.cmb_value.pack(fill="x")
        elif action == "profile":
            vals = list(self.owner.app.profile_names()) + ["next"]
            self.cmb_value = ttk.Combobox(self.value_holder, values=vals,
                                          justify=just)
            self.cmb_value.set(current or (vals[0] if vals else "next"))
            self.cmb_value.pack(fill="x")
        elif action == "macro":
            self._build_macro_ui(current)
        elif spec.options:
            self.cmb_value = ttk.Combobox(self.value_holder, state="readonly",
                                          values=list(spec.options), justify=just)
            self.cmb_value.set(current or spec.options[0])
            self.cmb_value.pack(fill="x")
        elif action in ("type", "clip"):
            self.txt_value = tk.Text(self.value_holder, height=4, wrap="word",
                                     bg=self.pal["panel2"], fg=self.pal["fg"],
                                     insertbackground=self.pal["fg"], relief="flat",
                                     font=_font(10), padx=8, pady=8)
            self.txt_value.tag_configure("align", justify=just)
            self.txt_value.insert("1.0", current, "align")
            self.txt_value.pack(fill="x")
        elif action == "paste":
            ttk.Label(self.value_holder, text="Uses the current clipboard contents.",
                      style="Muted.TLabel", justify=just).pack(anchor=near)
        else:
            self.ent_value = ttk.Entry(self.value_holder,
                                       textvariable=self.var_value,
                                       justify=just)
            self.var_value.set(current)
            self.ent_value.pack(fill="x")

        # chords / sequences can only fire instantly
        combo = self.var_keys.get().strip()
        is_chord = False
        is_seq = ">" in combo or self._seq_mode
        try:
            is_chord = keys.is_chord(combo)
        except Exception:
            pass
        if is_chord or is_seq or action in ("macro",):
            self.var_trigger.set(self._trigger_press)
            self.cmb_trigger.configure(state="disabled")
        else:
            self.cmb_trigger.configure(state="readonly")
        _translate_widgets(self.value_holder, self.t)
        self._queue_scroll_refresh()

    def _build_macro_ui(self, current: str = "") -> None:
        start, end = _start(self.lang), _end(self.lang)
        just = _justify(self.lang)
        frame = ttk.Frame(self.value_holder)
        frame.pack(fill="x")
        top = ttk.Frame(frame)
        top.pack(fill="x")
        self.macro_lbl = ttk.Label(
            top, text=self.t("Steps: {count}", count=len(self._macro_steps)),
            justify=just)
        self.macro_lbl.pack(side=start)
        ttk.Button(top, text="Record", width=8,
                   command=self._start_record).pack(
            side=start, padx=_pad(self.lang, 8))
        ttk.Button(top, text="Clear", width=7,
                   command=self._clear_macro).pack(
            side=start, padx=_pad(self.lang, 6))
        ttk.Label(top, text="Speed:", style="Muted.TLabel",
                  justify=just).pack(side=start, padx=_pad(self.lang, 12))
        self.cmb_macro_speed = ttk.Combobox(top, state="readonly", width=7,
                                            values=SPEED_CHOICES, justify=just)
        speed = getattr(self, "_macro_speed", 1.0) or 1.0
        label = _speed_label(speed)
        if label not in SPEED_CHOICES:
            label = "1x"
        self.cmb_macro_speed.set(label)
        self.cmb_macro_speed.pack(side=start, padx=_pad(self.lang, 4))
        preview_row = ttk.Frame(frame)
        preview_row.pack(fill="both", pady=(6, 0))
        self.macro_preview = tk.Text(
            preview_row, height=5, wrap="word", bg=self.pal["panel2"],
            fg=self.pal["fg"], relief="flat", font=_mono(9), padx=8, pady=6,
            state="disabled")
        self.macro_preview.tag_configure("align", justify=just)
        self.macro_preview.pack(side=start, fill="both", expand=True)
        preview_scroll = ttk.Scrollbar(preview_row, orient="vertical",
                                       command=self.macro_preview.yview)
        preview_scroll.pack(side=end, fill="y")
        self.macro_preview.configure(yscrollcommand=preview_scroll.set)
        self._refresh_macro_preview()
        self._queue_scroll_refresh()

    def _refresh_macro_preview(self) -> None:
        if not hasattr(self, "macro_preview"):
            return
        self.macro_preview.configure(state="normal")
        self.macro_preview.delete("1.0", "end")
        for i, step in enumerate(self._macro_steps, 1):
            if isinstance(step, dict):
                if "mouse" in step:
                    line = self.t(
                        "Mouse {button} ({x},{y}) -> ({x2},{y2})   (+{wait} ms)",
                        button=step["mouse"], x=step.get("x"), y=step.get("y"),
                        x2=step.get("x2"), y2=step.get("y2"),
                        wait=step.get("wait", 0))
                    self.macro_preview.insert("end", f"{i}. {line}\n", "align")
                else:
                    keys_text = step.get("keys", "")
                    wait = step.get("wait", step.get("delay", 0))
                    self.macro_preview.insert(
                        "end", f"{i}. {keys_text}   (+{wait} ms)\n", "align")
            else:
                self.macro_preview.insert("end", f"{i}. {step}\n", "align")
        self.macro_preview.configure(state="disabled")
        if hasattr(self, "macro_lbl"):
            self.macro_lbl.configure(
                text=self.t("Steps: {count}", count=len(self._macro_steps)))
        self._queue_scroll_refresh()

    def _clear_macro(self) -> None:
        if not messagebox.askyesno(
                self.t("Clear macro"), self.t("Remove all recorded steps?"),
                parent=self.top):
            return
        self._macro_steps = []
        self._refresh_macro_preview()

    def _start_record(self) -> None:
        if self._recording:
            return
        if self._macro_steps and not messagebox.askyesno(
                self.t("Record macro"),
                self.t("Replace the existing recorded steps?"),
                parent=self.top):
            return
        # withdraw dialog so the user can work in the target app
        try:
            self.top.grab_release()
        except tk.TclError:
            pass
        self._recording = True
        self._macro_steps = []
        self._rec_pending = None
        self._rec_last_end = time.monotonic()
        self._rec_started = time.monotonic()
        import queue as _q
        self._rec_queue = _q.Queue()
        try:
            from .hooks import KeyboardHook
            self._rec_hook = KeyboardHook(self._rec_event)
            if not getattr(self._rec_hook, "installed", True):
                raise RuntimeError("could not install keyboard hook")
            from .hooks import MouseRecorderHook
            self._rec_mouse_hook = MouseRecorderHook(self._rec_mouse_event)
            if not getattr(self._rec_mouse_hook, "installed", True):
                raise RuntimeError("could not install mouse hook")
        except Exception as exc:
            self._recording = False
            for hook in (self._rec_hook, self._rec_mouse_hook):
                if hook is not None:
                    try:
                        hook.close()
                    except Exception:
                        pass
            self._rec_hook = self._rec_mouse_hook = None
            # The dialog was not hidden yet, but the grab was released before
            # installing the hooks. Put it back or its buttons stop responding.
            try:
                self.top.grab_set()
            except tk.TclError:
                pass
            messagebox.showerror(
                self.t("Record macro"),
                self.t("Could not start recording:\n{error}", error=exc),
                parent=self.top)
            self._refresh_macro_preview()
            return
        # status window
        self._rec_status = tk.Toplevel(self.top)
        try:
            self._rec_status.overrideredirect(True)
            self._rec_status.attributes("-topmost", True)
        except tk.TclError:
            pass
        self._rec_status.configure(bg=self.pal["accent"])
        lbl = tk.Label(
            self._rec_status,
            text=self.t("● Recording macro — press Esc to stop"),
            bg=self.pal["accent"], fg=self.pal["accent_fg"],
            font=_font(10, "bold"), padx=12, pady=6)
        lbl.pack()
        try:
            sw = self.top.winfo_screenwidth()
            self._rec_status.geometry(f"+{(sw - 320) // 2}+40")
        except tk.TclError:
            pass
        self.top.withdraw()
        self._rec_poll_job = self.top.after(40, self._poll_record)

    def _rec_event(self, kind: str, vk: int) -> None:
        if not self._recording or self._rec_queue is None:
            return
        try:
            self._rec_queue.put_nowait(("key", kind, vk, time.monotonic(),
                                        win32.current_mods()))
        except Exception:
            pass

    def _rec_mouse_event(self, kind: str, button: str, x: int, y: int) -> None:
        if not self._recording or self._rec_queue is None:
            return
        try:
            self._rec_queue.put_nowait(("mouse", kind, button, int(x), int(y),
                                        time.monotonic()))
        except Exception:
            pass

    def _poll_record(self) -> None:
        if not self._recording:
            return
        now = time.monotonic()
        # hard limits
        if (len(self._macro_steps) >= 600
                or now - self._rec_started > 180):
            self._finish_record()
            return
        q = self._rec_queue
        while q is not None and not q.empty():
            try:
                item = q.get_nowait()
            except Exception:
                break
            if not isinstance(item, tuple) or not item:
                continue
            if item[0] == "key":
                _tag, kind, vk, t, mods = item
                if kind == "down":
                    if vk == 0x1B and mods == 0:
                        self._finalize_pending(t)
                        self._finish_record()
                        return
                    if self._rec_pending is not None:
                        self._finalize_pending(t)
                    self._rec_pending = {"type": "key", "vk": vk,
                                         "mods": mods, "t": t}
                else:
                    if (self._rec_pending is not None
                            and self._rec_pending.get("type") == "key"
                            and self._rec_pending.get("vk") == vk):
                        self._finalize_pending(t)
            elif item[0] == "mouse":
                _tag, kind, button, x, y, t = item
                if kind == "down":
                    if self._rec_pending is not None:
                        self._finalize_pending(t)
                    self._rec_pending = {"type": "mouse", "button": button,
                                         "x": x, "y": y, "t": t}
                else:
                    if (self._rec_pending is not None
                            and self._rec_pending.get("type") == "mouse"
                            and self._rec_pending.get("button") == button):
                        p = self._rec_pending
                        self._rec_pending = None
                        wait = max(0, int((p["t"] - self._rec_last_end) * 1000))
                        hold = max(15, int((t - p["t"]) * 1000))
                        self._macro_steps.append({
                            "mouse": button,
                            "x": int(p["x"]), "y": int(p["y"]),
                            "x2": int(x), "y2": int(y),
                            "wait": wait, "hold": hold,
                        })
                        self._rec_last_end = t
        # update status count
        if self._rec_status is not None:
            try:
                for w in self._rec_status.winfo_children():
                    if isinstance(w, tk.Label):
                        w.configure(text=self.t(
                            "● Recording macro — {count} steps — Esc to stop",
                            count=len(self._macro_steps)))
            except tk.TclError:
                pass
        try:
            self._rec_poll_job = self.top.after(40, self._poll_record)
        except tk.TclError:
            self._rec_poll_job = None

    def _finalize_pending(self, up_time: float | None = None) -> None:
        p = self._rec_pending
        if p is None:
            return
        self._rec_pending = None
        if p.get("type") == "key":
            t = up_time if up_time is not None else p["t"] + 0.05
            wait = max(0, int((p["t"] - self._rec_last_end) * 1000))
            hold = max(15, int((t - p["t"]) * 1000))
            combo = keys.format_many(p["mods"], (p["vk"],))
            self._macro_steps.append({"keys": combo, "wait": wait, "hold": hold})
            self._rec_last_end = t
        elif p.get("type") == "mouse":
            t = up_time if up_time is not None else p["t"] + 0.05
            wait = max(0, int((p["t"] - self._rec_last_end) * 1000))
            hold = max(15, int((t - p["t"]) * 1000))
            self._macro_steps.append({
                "mouse": p["button"],
                "x": int(p["x"]), "y": int(p["y"]),
                "x2": int(p["x"]), "y2": int(p["y"]),
                "wait": wait, "hold": hold,
            })
            self._rec_last_end = t

    def _finish_record(self) -> None:
        if not self._recording:
            return
        self._recording = False
        if self._rec_poll_job is not None:
            try:
                self.top.after_cancel(self._rec_poll_job)
            except tk.TclError:
                pass
            self._rec_poll_job = None
        # finalize a key/mouse that is still held
        self._finalize_pending()
        if self._rec_hook is not None:
            try:
                self._rec_hook.close()
            except Exception:
                pass
            self._rec_hook = None
        if self._rec_mouse_hook is not None:
            try:
                self._rec_mouse_hook.close()
            except Exception:
                pass
            self._rec_mouse_hook = None
        if self._rec_status is not None:
            try:
                self._rec_status.destroy()
            except tk.TclError:
                pass
            self._rec_status = None
        try:
            self.top.deiconify()
            self.top.lift()
            self.top.focus_force()
            self.top.grab_set()
        except tk.TclError:
            pass
        self._refresh_macro_preview()
        try:
            self.ent_keys.focus_set()
        except tk.TclError:
            pass

    def _set_capture(self, enabled: bool) -> None:
        self._capture = enabled
        self._typing_mode = not enabled
        self.btn_type.configure(text=self.t("Type" if enabled else "Capture"))
        try:
            self.ent_keys.configure(state="normal")
        except tk.TclError:
            pass
        if enabled:
            self._held_keys.clear()
            self._chord_done = False

    def _toggle_steps(self) -> None:
        self._seq_mode = not self._seq_mode
        if self._seq_mode:
            # seed from the current field if it is a single combo
            if not self._seq_steps:
                combo = self.var_keys.get().strip()
                if combo and ">" not in combo:
                    try:
                        mods, vks = keys.parse_all(combo)
                        self._seq_steps = [(mods, vks)]
                    except keys.HotkeyError:
                        self._seq_steps = []
            self.var_keys.set(keys.format_sequence(self._seq_steps) if self._seq_steps else "")
            self._held_keys.clear()
            self._chord_done = False
            self.var_trigger.set(self._trigger_press)
            try:
                self.cmb_trigger.configure(state="disabled")
            except tk.TclError:
                pass
            self.btn_steps.configure(text=self.t("Single"))
        else:
            if self._seq_steps:
                mods, vks = self._seq_steps[0]
                self.var_keys.set(keys.format_many(mods, vks))
            self._seq_steps = []
            try:
                self.cmb_trigger.configure(state="readonly")
            except tk.TclError:
                pass
            self.btn_steps.configure(text=self.t("Steps"))
        self.ent_keys.focus_set()

    def _toggle_type(self) -> None:
        self._set_capture(not self._capture)
        self.ent_keys.focus_set()

    def _clear(self) -> None:
        self.var_keys.set("")
        self._held_keys.clear()
        self._chord_done = False
        self._seq_steps = []
        try:
            self.cmb_trigger.configure(state="readonly")
        except tk.TclError:
            pass

    def _apps(self) -> tuple[str, ...]:
        """Parse the "Only in app" field: comma/semicolon separated names."""
        raw = self.var_apps.get().replace(";", ",")
        names: list[str] = []
        for part in raw.split(","):
            name = win32.normalize_app(part)
            if name and name not in names:
                names.append(name)
        return tuple(names)

    def _profiles(self) -> tuple[str, ...]:
        raw = self.var_profiles.get().replace(";", ",")
        names: list[str] = []
        seen: set[str] = set()
        for part in raw.split(","):
            name = part.strip()
            key = name.casefold()
            if name and key not in seen:
                seen.add(key)
                names.append(name)
        return tuple(names)

    def _restore_owner(self) -> None:
        if self._detect_job is not None:
            try:
                self.top.after_cancel(self._detect_job)
            except tk.TclError:
                pass
            self._detect_job = None
        self._detecting = False
        try:
            if self.owner.root.winfo_exists():
                self.owner.root.deiconify()
        except tk.TclError:
            pass

    def _detect_app(self) -> None:
        """Hide the dialog, then bind to whatever app becomes active."""
        if self._detecting:
            return
        self._detecting = True
        self._detect_deadline = time.monotonic() + 4.0
        self._detect_tick()
        try:
            self.top.grab_release()
        except tk.TclError:
            pass
        self.top.withdraw()
        try:
            self.owner.root.withdraw()
        except tk.TclError:
            pass

    def _detect_tick(self) -> None:
        if not self._detecting:
            return
        left = max(0, int(self._detect_deadline - time.monotonic() + 0.999))
        self.err.configure(text=self.t(
            "Switch to the target app — detecting in {count} s…", count=left))
        if left == 0:
            self._finish_detect()
            return
        self._detect_job = self.top.after(200, self._detect_tick)

    def _finish_detect(self) -> None:
        self._restore_owner()
        try:
            if not self.top.winfo_exists():
                return
        except tk.TclError:
            return
        try:
            exe = win32.foreground_app()
        except Exception:
            exe = ""
        try:
            self.top.deiconify()
            self.top.lift()
            self.top.focus_force()
            self.top.grab_set()
        except tk.TclError:
            return
        if exe:
            self.var_apps.set(exe)
            self.err.configure(text=self.t("Bound to {exe}", exe=exe))
        else:
            self.err.configure(
                text=self.t("Could not detect the app — type its .exe name"))
            return
        try:
            self.ent_keys.focus_set()
        except tk.TclError:
            pass

    def _record(self, vk: int, mods: int) -> None:
        """Append one pressed key or mouse button to the shortcut."""
        if self._seq_mode:
            if vk in self._held_keys:
                return
            self._held_keys.append(vk)
            step_mods = mods if not self._seq_steps else 0
            self._seq_steps.append((step_mods, (vk,)))
            self.var_keys.set(keys.format_sequence(self._seq_steps))
            self._chord_done = True
            self.var_trigger.set(self._trigger_press)
            try:
                self.cmb_trigger.configure(state="disabled")
            except tk.TclError:
                pass
            return
        if vk in self._held_keys:
            return
        self._held_keys.append(vk)
        if len(self._held_keys) >= 2:
            self.var_keys.set(keys.format_many(mods, self._held_keys))
            self._chord_done = True
            self.cmb_trigger.configure(state="disabled")
            self.var_trigger.set(self._trigger_press)
        else:
            self.var_keys.set(keys.format_many(mods, [vk]))
            self._chord_done = False
            try:
                self.cmb_trigger.configure(state="readonly")
            except tk.TclError:
                pass

    def _on_mouse(self, event) -> str | None:
        if self._typing_mode or not self._capture or self._seq_mode:
            return None
        name = MOUSE_BUTTONS.get(int(getattr(event, "num", 0) or 0))
        vk = keys.name_to_vk(name) if name else None
        if vk is None:
            return None
        self._record(vk, win32.current_mods())
        return "break"

    def _poll_mouse(self) -> None:
        """Watch the side buttons: Tk on Windows ignores XBUTTON messages."""
        self._poll_job = None
        try:
            app = getattr(self.owner, "app", None)
            events = getattr(app, "capture_events", None) if app else None
            if events is not None:
                while True:
                    try:
                        kind, vk, mods = events.get_nowait()
                    except queue.Empty:
                        break
                    if (self._capture and not self._typing_mode
                            and not self._seq_mode):
                        if kind == "down":
                            self._record(vk, mods)
                        elif vk in self._held_keys:
                            self._held_keys.remove(vk)
                            if not self._held_keys:
                                self._chord_done = False
            if self._capture and not self._typing_mode and not self._seq_mode:
                mods = win32.current_mods()
                for name in ("mouse4", "mouse5"):
                    vk = keys.name_to_vk(name)
                    if vk is None:
                        continue
                    if win32.is_key_down(vk):
                        self._record(vk, mods)
                    elif vk in self._held_keys:
                        self._held_keys.remove(vk)
                        if not self._held_keys:
                            self._chord_done = False
            self._poll_job = self.top.after(35, self._poll_mouse)
        except tk.TclError:
            pass

    def _on_press(self, event) -> str | None:
        if self._typing_mode or not self._capture:
            return None
        # Don't capture when typing in other fields
        focused = self.top.focus_get()
        text_widgets = {self.ent_desc, self.txt_extra, self.ent_value}
        if self.txt_value is not None:
            text_widgets.add(self.txt_value)
        if focused in text_widgets:
            return None
        # Also ignore comboboxes
        if isinstance(focused, ttk.Combobox):
            return None
        ks = (event.keysym or "").lower()
        if ks in keys.MODIFIER_KEYSYMS:
            return "break"
        name = keys.keysym_to_name(event.keysym)
        if name is None:
            return "break"
        vk = keys.name_to_vk(name)
        if vk is None:
            return "break"
        if vk in self._held_keys:
            return "break"
        # The physical state is the truth: Tk's event.state carries a
        # phantom Alt bit and modifiers can outlive their release event.
        mods = keys.mods_from_state(event.state) | win32.current_mods()
        self._record(vk, mods)
        return "break"

    def _on_release(self, event) -> None:
        if self._typing_mode:
            return
        focused = self.top.focus_get()
        text_widgets = {self.ent_desc, self.txt_extra, self.ent_value}
        if self.txt_value is not None:
            text_widgets.add(self.txt_value)
        if focused in text_widgets or isinstance(focused, ttk.Combobox):
            return
        ks = (event.keysym or "").lower()
        if ks not in keys.MODIFIER_KEYSYMS:
            name = keys.keysym_to_name(event.keysym)
            if name is not None:
                try:
                    vk = keys.name_to_vk(name)
                except keys.HotkeyError:
                    return
                if vk in self._held_keys:
                    self._held_keys.remove(vk)
        if not self._held_keys:
            self._chord_done = False

    def _value(self) -> str:
        if self.txt_value is not None:
            return self.txt_value.get("1.0", "end-1c")
        if self.cmb_value is not None:
            return self.cmb_value.get()
        return self.var_value.get()

    def _save(self) -> None:
        if self._detecting:
            self._restore_owner()
        self.err.configure(text="")
        combo = self.var_keys.get().strip()
        seq: tuple = ()
        try:
            if self._seq_mode or ">" in combo:
                seq = keys.parse_sequence(combo)
                if len(seq) < 2:
                    raise keys.HotkeyError(
                        self.t("a leader sequence needs at least two steps"))
                mods, vks = seq[0]
            else:
                mods, vks = keys.parse_all(combo)
        except keys.HotkeyError as exc:
            self.err.configure(text=self.t(str(exc)))
            return
        action = self._action_by_label.get(self.var_action.get(), "open")
        value = self._value()
        if action not in ("paste", "macro") and not value.strip():
            self.err.configure(text=self.t("This action needs a value."))
            return
        extra: dict = {}
        raw_extra = self.txt_extra.get("1.0", "end-1c").strip()
        if raw_extra:
            try:
                extra = json.loads(raw_extra)
                if not isinstance(extra, dict):
                    raise ValueError("must be a JSON object")
            except ValueError as exc:
                self.err.configure(
                    text=f"{self.t('Advanced JSON')}: {exc}")
                return
        if action == "macro":
            speed_label = getattr(self, "cmb_macro_speed", None)
            speed = 1.0
            if speed_label is not None:
                speed = _speed_value(speed_label.get())
            if not self._macro_steps:
                self.err.configure(
                    text=self.t("Record at least one step for the macro."))
                return
            extra["steps"] = list(self._macro_steps)
            extra["speed"] = speed
        trigger = self._trigger_by_label.get(self.var_trigger.get(), "press")
        if len(vks) > 1 or seq:
            trigger = "press"
        apps = self._apps()
        profiles = self._profiles()
        for other in self.owner.entries:
            if other is self.original:
                continue
            same_combo = (other.mods == mods
                          and frozenset(other.vks) == frozenset(vks)
                          and other.seq == seq)
            # leader sequences with the same prefix but different following
            # keys are allowed; only an identical sequence is a duplicate
            if seq and other.seq and other.mods == mods and frozenset(other.vks) == frozenset(vks):
                # same prefix: allowed if the following steps differ
                if other.seq == seq:
                    same_combo = True
                else:
                    same_combo = False
            if (same_combo and other.trigger == trigger
                    and other.apps == apps
                    and config.profiles_overlap(other.profiles, profiles)):
                where = (self.t("(in {apps})", apps=", ".join(apps))
                         if apps else "")
                detail = self.t("is already used by \"{label}\"{where}",
                                label=other.label(), where=where)
                self.err.configure(
                    text=f"{keys.format_many(mods, vks)} {detail}")
                return
            same_steps = True
            if action == "macro":
                # Two macros on one combo can be perfectly valid when they
                # use different triggers or record different steps.
                same_steps = (
                    other.extra.get("steps") == extra.get("steps")
                    and other.extra.get("speed", 1.0) == extra.get("speed", 1.0))
            # Different triggers are allowed when the actions differ, but two
            # entries doing the same thing on one button are still a mistake.
            if (same_combo and other.apps == apps
                    and config.profiles_overlap(other.profiles, profiles)
                    and other.action == action
                    and other.value.strip() == value.strip()
                    and same_steps):
                what = value.strip() if action == "keys" else action
                detail = self.t(
                    "already does \"{what}\" ({label}) - same button, same action",
                    what=what, label=other.label())
                self.err.configure(
                    text=f"{keys.format_many(mods, vks)} {detail}")
                return
        self.result = config.Entry(
            keys=combo, action=action, value=value, extra=extra,
            description=self.var_desc.get().strip(), enabled=self.var_enabled.get(),
            mods=mods, vk=vks[0] if vks else 0, vks=vks, trigger=trigger,
            apps=apps, profiles=profiles,
            seq=seq,
            index=self.original.index if self.original else 0,
        )
        self._stop_jobs()
        self.top.destroy()

    def _cancel(self) -> None:
        self._restore_owner()
        self._stop_jobs()
        self.result = None
        self.top.destroy()


def _short_action(action: str, lang: str = "en") -> str:
    label = {
        "open": "Open", "run": "Run", "type": "Type", "keys": "Keys",
        "clip": "Copy", "paste": "Paste", "media": "Media",
        "window": "Window", "pin": "Pin", "system": "System", "app": "App",
        "summon": "Summon", "macro": "Macro", "profile": "Profile",
    }.get(action, action)
    return i18n.tr(label, lang)


class _MacroPanel:
    """Tiny floating playback controller.

    It owns its own Tk interpreter in a daemon thread, so it can be opened
    from a hotkey even when the settings window is closed.  Other threads
    never touch Tk - they only push commands onto ``self.q``.
    """

    def __init__(self, app):
        self.app = app
        self.control = app.macro
        settings = getattr(getattr(app, "cfg", None), "settings", {}) or {}
        self.lang = i18n.normalize(settings.get("language"))
        self.rtl = i18n.is_rtl(self.lang)
        self.q: queue.Queue = queue.Queue()
        self.ready = threading.Event()
        self.closed = threading.Event()
        self.control.on_update = self._sync
        self.thread = threading.Thread(target=self._run, daemon=True,
                                       name="macro-panel")
        self.thread.start()
        self.ready.wait(5.0)
        self.show()

    def t(self, text: str, **kwargs: object) -> str:
        return i18n.tr(text, self.lang, **kwargs)

    def show(self) -> None:
        self.q.put(("show", None))

    def toggle(self) -> None:
        self.q.put(("toggle", None))

    def close(self) -> None:
        self.q.put(("close", None))
        # Wait for the Tk thread to finish so its Variables are released there
        # instead of during interpreter shutdown on the wrong thread.
        self.closed.wait(1.0)

    def _sync(self) -> None:
        self.q.put(("sync", None))

    def _apply_style(self, root: tk.Tk) -> tuple[dict, float]:
        pal, scale = _palette(), _scale_factor()
        try:
            root.tk.call("tk", "scaling", scale)
        except tk.TclError:
            pass
        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=pal["bg"])
        style.configure("Card.TFrame", background=pal["panel2"],
                        bordercolor=pal["border"], borderwidth=1,
                        relief="solid")
        style.configure("TLabel", background=pal["bg"], foreground=pal["fg"],
                        font=_font(9))
        style.configure("CardSub.TLabel", background=pal["panel2"],
                        foreground=pal["muted"], font=_font(8))
        style.configure("Title.TLabel", background=pal["bg"],
                        foreground=pal["fg"], font=_font(12, "bold"))
        style.configure("Sub.TLabel", background=pal["bg"],
                        foreground=pal["muted"], font=_font(8))
        style.configure("Name.TLabel", background=pal["panel2"],
                        foreground=pal["accent"], font=_font(10, "bold"))
        style.configure("Status.TLabel", background=pal["bg"],
                        foreground=pal["fg"], font=_font(9, "bold"))
        style.configure("Progress.TLabel", background=pal["bg"],
                        foreground=pal["muted"], font=_font(8))
        style.configure("TButton", background=pal["panel"],
                        foreground=pal["fg"], bordercolor=pal["border"],
                        padding=(9, 5), font=_font(9))
        style.map("TButton", background=[("active", pal["hover"]),
                                         ("disabled", pal["panel2"])])
        style.configure("Accent.TButton", background=pal["accent"],
                        foreground=pal["accent_fg"], bordercolor=pal["accent"],
                        padding=(12, 6), font=_font(9, "bold"))
        style.map("Accent.TButton", background=[("active", pal["accent_hover"]),
                                                ("disabled", pal["panel2"])],
                  foreground=[("disabled", pal["muted"])])
        style.configure("Danger.TButton", background=pal["panel"],
                        foreground=pal["error"], bordercolor=pal["border"],
                        padding=(9, 5), font=_font(9))
        style.map("Danger.TButton", background=[("active", pal["hover"]),
                                                ("disabled", pal["panel2"])])
        style.configure("TEntry", fieldbackground=pal["panel"],
                        foreground=pal["fg"], bordercolor=pal["border"],
                        insertcolor=pal["fg"], padding=(6, 4))
        style.configure("TCombobox", fieldbackground=pal["panel"],
                        background=pal["panel"], foreground=pal["fg"],
                        bordercolor=pal["border"], padding=(6, 4))
        style.configure("TProgressbar", background=pal["accent"],
                        troughcolor=pal["panel"], bordercolor=pal["border"],
                        lightcolor=pal["accent"], darkcolor=pal["accent"],
                        thickness=8)
        root.option_add("*TCombobox*Listbox.background", pal["panel2"])
        root.option_add("*TCombobox*Listbox.foreground", pal["fg"])
        root.option_add("*TCombobox*Listbox.selectBackground", pal["accent"])
        root.option_add("*TCombobox*Listbox.selectForeground", pal["accent_fg"])
        win32.set_dark_titlebar(root.winfo_id(), pal["dark"])
        return pal, scale

    def _run(self) -> None:
        try:
            self._run_impl()
        except Exception:
            import logging
            logging.getLogger("hotkey").exception("macro panel failed")
            self.ready.set()
        finally:
            # _run_impl's locals are gone now. Collect here, on the Tk thread,
            # so cyclic widget/Variable references are not finalized later by
            # the main thread (which is not in this interpreter's main loop).
            gc.collect()
            self.closed.set()

    def _run_impl(self) -> None:
        root = tk.Tk()
        root.withdraw()
        root.title(self.t("Hotkey · Macro control"))
        _apply_window_icon(root)
        pal, scale = self._apply_style(root)
        root.configure(bg=pal["bg"])
        root.resizable(False, False)
        start, end = _start(self.lang), _end(self.lang)
        near = _near(self.lang)
        just = _justify(self.lang)

        main = ttk.Frame(root, padding=(16, 14, 16, 14))
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)

        head = ttk.Frame(main)
        head.pack(fill="x")
        ttk.Label(head, text=self.t("Macro control"),
                  style="Title.TLabel", justify=just).pack(side=start)
        ttk.Label(head, text=self.t("set up · then run"),
                  style="Sub.TLabel", justify=just).pack(
            side=start, padx=_pad(self.lang, 8), pady=(5, 0))
        btn_close = ttk.Button(head, text=self.t("Close"), padding=(8, 3),
                               command=root.withdraw)
        btn_close.pack(side=end)
        ttk.Separator(main, orient="horizontal").pack(fill="x", pady=(10, 9))

        snap = self.control.snapshot()
        # Tk objects stay local to this thread; Python then deallocates them
        # here too instead of from the main thread at process exit.
        var_times = tk.StringVar(master=root, value=str(snap["times"]))
        var_speed = tk.StringVar(master=root, value=_speed_label(snap["speed"]))
        var_status = tk.StringVar(master=root, value=self.t("Ready"))
        var_progress = tk.StringVar(master=root, value="—")
        var_help = tk.StringVar(master=root, value="")

        card = ttk.Frame(main, style="Card.TFrame", padding=(12, 10))
        card.pack(fill="x")
        label_col, value_col = _columns(self.lang)
        card.columnconfigure(value_col, weight=1)
        ttk.Label(card, text=self.t("LOADED MACRO"),
                  style="CardSub.TLabel", justify=just).grid(
            row=0, column=0, columnspan=2, sticky=near)
        lbl_name = ttk.Label(card, text=snap["name"] or "—", style="Name.TLabel",
                             justify=just)
        lbl_name.grid(row=1, column=0, columnspan=2, sticky=near, pady=(2, 9))

        ttk.Label(card, text=self.t("Times"), justify=just).grid(
            row=2, column=label_col, sticky=near)
        ent_times = ttk.Entry(card, textvariable=var_times, width=6,
                              justify=just)
        ent_times.grid(row=2, column=value_col, sticky=near)
        ttk.Label(card, text=self.t("how many runs"),
                  style="CardSub.TLabel", justify=just).grid(
            row=2, column=value_col, sticky=_far(self.lang))

        ttk.Label(card, text=self.t("Speed"), justify=just).grid(
            row=3, column=label_col, sticky=near, pady=(8, 0))
        cmb_speed = ttk.Combobox(
            card, textvariable=var_speed, width=9, values=SPEED_CHOICES,
            justify=just)
        cmb_speed.grid(row=3, column=value_col, sticky=near, pady=(8, 0))
        ttk.Label(card, text=self.t("live"), style="CardSub.TLabel",
                  justify=just).grid(
            row=3, column=value_col, sticky=_far(self.lang), pady=(8, 0))

        ttk.Separator(card, orient="horizontal").grid(
            row=4, column=0, columnspan=2, sticky="ew", pady=(10, 8))
        ttk.Label(card, text=self.t("Start with"),
                  style="CardSub.TLabel", justify=just).grid(
            row=5, column=label_col, sticky=near)
        btn_start_key = ttk.Button(card, text=self.t("Set key"),
                                   command=lambda: begin_capture("start"))
        btn_start_key.grid(row=5, column=value_col, sticky="ew")
        ttk.Label(card, text=self.t("Stop with"),
                  style="CardSub.TLabel", justify=just).grid(
            row=6, column=label_col, sticky=near, pady=(6, 0))
        btn_stop_key = ttk.Button(card, text=self.t("Set key"),
                                  command=lambda: begin_capture("stop"))
        btn_stop_key.grid(row=6, column=value_col, sticky="ew", pady=(6, 0))
        ttk.Label(card,
                  text=self.t("click, then press a key · Esc clears"),
                  style="CardSub.TLabel", justify=just).grid(
            row=7, column=0, columnspan=2, sticky=near, pady=(6, 0))

        capturing = None
        cap_kb = None
        cap_mouse = None
        key_overrides: dict[str, str] = {}

        def key_setting(which: str) -> str:
            if which in key_overrides:
                return key_overrides[which]
            name = "macro_start_hotkey" if which == "start" else "macro_stop_hotkey"
            try:
                return str(self.app.cfg.settings.get(name) or "").strip()
            except Exception:
                return ""

        def refresh_key_labels() -> None:
            for which, button in (("start", btn_start_key),
                                  ("stop", btn_stop_key)):
                combo = key_setting(which)
                if combo:
                    text = self.t(
                        "Start: {combo}" if which == "start" else "Stop: {combo}",
                        combo=combo)
                else:
                    text = self.t("Set start key" if which == "start"
                                  else "Set stop key")
                if capturing == which:
                    text = self.t("Press a key…")
                button.configure(text=text)

        def end_capture(combo: str) -> None:
            nonlocal capturing, cap_kb, cap_mouse
            which = capturing
            if which is None:
                return
            capturing = None
            for hook in (cap_kb, cap_mouse):
                if hook is not None:
                    try:
                        hook.close()
                    except Exception:
                        pass
            cap_kb = cap_mouse = None
            ok = self.app.set_macro_key(which, combo)
            if ok is False:
                var_status.set(
                    self.t("That key is not safe globally — try a combo"))
            else:
                key_overrides[which] = combo
                label = self.t("Start" if which == "start" else "Stop")
                var_status.set(
                    self.t("{label} key cleared", label=label) if not combo
                    else self.t("{label} key set to {combo}",
                                label=label, combo=combo))
            refresh_key_labels()

        def on_hook_key(kind: str, vk: int) -> None:
            # Low-level hook: works even when another window has focus.
            if capturing is None or kind != "down":
                return
            mods = win32.current_mods()
            combo = "" if vk == 0x1B and mods == 0 else keys.format_many(
                mods, (vk,))
            self.q.put(("capture", combo))

        def on_hook_mouse(kind: str, button: str, x: int, y: int) -> None:
            if capturing is None or kind != "down":
                return
            # Recorder names ("x1") are not key names ("mouse4"); without this
            # translation a side button becomes the Left arrow or nothing.
            name = keys.normalize_mouse_button(button)
            vk = keys.name_to_vk(name)
            if vk is not None:
                mods = win32.current_mods()
                self.q.put(("capture", keys.format_many(mods, (vk,))))

        def begin_capture(which: str) -> None:
            nonlocal capturing, cap_kb, cap_mouse
            if cap_kb is not None or cap_mouse is not None:
                end_capture("")
            capturing = which
            refresh_key_labels()
            var_status.set(self.t("Press a key or mouse button anywhere…"))
            try:
                from .hooks import KeyboardHook, MouseRecorderHook
                cap_kb = KeyboardHook(on_hook_key)
                cap_mouse = MouseRecorderHook(on_hook_mouse)
                if (not getattr(cap_kb, "installed", True)
                        or not getattr(cap_mouse, "installed", True)):
                    raise RuntimeError("hook unavailable")
            except Exception as exc:
                for hook in (cap_kb, cap_mouse):
                    if hook is not None:
                        try:
                            hook.close()
                        except Exception:
                            pass
                capturing = None
                cap_kb = cap_mouse = None
                refresh_key_labels()
                var_status.set(self.t("Capture failed: {error}", error=exc))
            root.focus_force()

        refresh_key_labels()

        def apply_config(_event=None) -> None:
            self.control.set_times(var_times.get())
            self.control.set_speed(_speed_value(var_speed.get()))
            var_times.set(str(self.control.snapshot()["times"]))

        def run_macro() -> None:
            if self.control.snapshot()["running"]:
                return
            self.control.set_times(var_times.get())
            self.control.set_speed(_speed_value(var_speed.get()))
            try:
                self.app.run_last_macro()
            except Exception:
                pass

        ent_times.bind("<Return>", apply_config)
        ent_times.bind("<FocusOut>", apply_config)
        cmb_speed.bind("<<ComboboxSelected>>", apply_config)
        cmb_speed.bind("<Return>", apply_config)

        buttons = ttk.Frame(main)
        buttons.pack(fill="x", pady=(12, 0))
        btn_run = ttk.Button(buttons, text=self.t("▶  Run / Repeat"),
                             style="Accent.TButton", command=run_macro)
        btn_run.pack(side=start, fill="x", expand=True)
        btn_stop = ttk.Button(buttons, text=self.t("Stop"),
                              command=self.control.stop)
        btn_stop.pack(side=start, padx=_pad(self.lang, 6))
        btn_cancel = ttk.Button(buttons, text=self.t("Cancel"),
                                style="Danger.TButton",
                                command=self.control.cancel)
        btn_cancel.pack(side=start, padx=_pad(self.lang, 6))

        for widget, text in (
            (btn_close, "Hide this window; the tray menu can show it again"),
            (btn_start_key, "Choose a global key that starts the loaded macro"),
            (btn_stop_key, "Choose a global key that stops the current run"),
            (ent_times, "How many full runs to play (can change while running)"),
            (cmb_speed, "Playback speed (can change while running)"),
            (btn_run, "Play the loaded macro with the settings above"),
            (btn_stop, "Finish the current run, then stop"),
            (btn_cancel, "Abort immediately"),
        ):
            _tip(widget, var_help, self.t(text))

        status_row = ttk.Frame(main)
        status_row.pack(fill="x", pady=(11, 0))
        dot = tk.Canvas(status_row, width=10, height=10, bg=pal["bg"],
                        highlightthickness=0)
        dot.pack(side=start)
        dot_id = dot.create_oval(2, 2, 9, 9, fill=pal["muted"], outline="")
        ttk.Label(status_row, textvariable=var_status,
                  style="Status.TLabel", justify=just).pack(
            side=start, padx=_pad(self.lang, 6))
        ttk.Label(main, textvariable=var_progress,
                  style="Progress.TLabel", justify=just).pack(
            fill="x", pady=(3, 0), anchor=near)
        bar = ttk.Progressbar(main, orient="horizontal", mode="determinate")
        bar.pack(fill="x", pady=(5, 0))
        ttk.Label(main, textvariable=var_help, style="Sub.TLabel",
                  justify=just, wraplength=int(330 * scale)).pack(
            fill="x", pady=(4, 0), anchor=near)
        _translate_widgets(main, self.t)

        root.update_idletasks()
        width = max(root.winfo_reqwidth(), int(340 * scale))
        height = root.winfo_reqheight()
        try:
            left, upper, right, lower = win32.get_work_area()
        except Exception:
            left, upper, right, lower = 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()
        x = left + 24 if self.rtl else max(left, right - width - 24)
        y = max(upper, lower - height - 48)
        root.geometry(f"{width}x{height}+{x}+{y}")
        root.protocol("WM_DELETE_WINDOW", root.withdraw)

        def show_window() -> None:
            root.deiconify()
            root.lift()
            root.focus_force()
            try:
                root.attributes("-topmost", True)
                root.after(400, lambda: root.attributes("-topmost", False))
            except tk.TclError:
                pass

        self.ready.set()

        def poll() -> None:
            sync = False
            while True:
                try:
                    action, _value = self.q.get_nowait()
                except queue.Empty:
                    break
                if action == "sync":
                    sync = True
                if action == "begin_capture":
                    begin_capture(str(_value or "start"))
                if action == "capture" and capturing:
                    end_capture(str(_value or ""))
                if action == "show":
                    show_window()
                elif action == "hide":
                    root.withdraw()
                elif action == "toggle":
                    try:
                        if root.state() == "withdrawn":
                            show_window()
                        else:
                            root.withdraw()
                    except tk.TclError:
                        show_window()
                elif action == "close":
                    for hook in (cap_kb, cap_mouse):
                        if hook is not None:
                            try:
                                hook.close()
                            except Exception:
                                pass
                    root.destroy()
                    return
            refresh_key_labels()
            s = self.control.snapshot()
            if capturing:
                var_status.set(self.t("Press a key or mouse button…"))
            if sync:
                if root.focus_get() not in (ent_times, cmb_speed):
                    var_times.set(str(s["times"]))
                    var_speed.set(_speed_label(s["speed"]))
            lbl_name.configure(text=s["name"] or "—")
            if not capturing:
                if s["running"] and s["cancelling"]:
                    var_status.set(self.t("Cancelling…"))
                    color = pal["error"]
                elif s["running"] and s["stopping"]:
                    var_status.set(self.t("Finishing run…"))
                    color = pal["muted"]
                elif s["running"]:
                    var_status.set(self.t("Running"))
                    color = pal["accent"]
                elif s["loaded"]:
                    var_status.set(self.t("Ready — press Run"))
                    color = pal["accent_hover"]
                else:
                    var_status.set(self.t("Ready"))
                    color = pal["muted"]
                dot.itemconfig(dot_id, fill=color)
            if s["running"]:
                var_progress.set(self.t(
                    "run {run}/{total}   ·   step {step}/{steps}",
                    run=s["run"], total=s["total_runs"],
                    step=s["step"], steps=s["steps"]))
            elif s["loaded"]:
                var_progress.set(self.t(
                    "{steps} steps   ·   {times} runs   ·   {speed} speed",
                    steps=s["steps"], times=s["times"],
                    speed=_speed_label(s["speed"])))
            else:
                var_progress.set(
                    self.t("no macro loaded — press a macro hotkey"))
            total = max(1, int(s["steps"]) * int(s["total_runs"]))
            done = 0
            if s["running"]:
                done = (int(s["run"]) - 1) * int(s["steps"]) + int(s["step"])
            bar.configure(maximum=total, value=max(0, min(total, done)))
            btn_run.configure(
                state="disabled" if s["running"] or not s["loaded"] else "normal")
            btn_stop.configure(
                state="normal" if s["running"] and not s["stopping"] else "disabled")
            btn_cancel.configure(state="normal" if s["running"] else "disabled")
            root.after(80, poll)

        root.after(80, poll)
        root.mainloop()

def _speed_label(value) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = 1.0
    return f"{v:g}x"


def _speed_value(text) -> float:
    raw = str(text).strip().lower().rstrip("x")
    try:
        return float(raw)
    except ValueError:
        return 1.0


def open_macro_panel(app) -> _MacroPanel:
    """Create the lazy macro controller; safe to call from any thread."""
    return _MacroPanel(app)
