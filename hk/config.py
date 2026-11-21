"""hotkeys.json loading, validation and atomic saving."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field

from . import i18n, keys, update

DEFAULT_SETTINGS: dict = {
    "show_notifications": True,
    "notify_on_start": False,
    "reload_on_change": True,
    "typing_delay_ms": 2,
    "hold_ms": 400,
    "leader_timeout_ms": 1200,
    "suspend_hotkey": "ctrl+alt+shift+p",
    "language": "en",
    "macro_start_hotkey": "",
    "macro_stop_hotkey": "",
    "update_check": True,
    "update_private": False,
    "update_url": update.DEFAULT_URL,
    "update_interval_hours": 6,
    "update_token": "",
    "update_token_env": update.DEFAULT_TOKEN_ENV,
}

DEFAULT_HOTKEYS: list[dict] = [
    {
        "keys": "ctrl+alt+t", "action": "open", "value": "wt.exe",
        "fallback": "powershell.exe", "description": "Terminal",
    },
    {
        "keys": "ctrl+alt+e", "action": "open", "value": "%USERPROFILE%",
        "description": "File Explorer (home)",
    },
    {
        "keys": "ctrl+alt+b", "action": "open", "value": "https://www.google.com",
        "description": "Open browser",
    },
    {
        "keys": "ctrl+alt+d", "action": "type", "value": "{date}",
        "description": "Type today's date",
    },
    {
        "keys": "ctrl+alt+shift+s", "action": "system", "value": "screenshot",
        "description": "Screenshot (region)",
    },
    {
        "keys": "ctrl+alt+shift+c", "action": "open", "value": "calc.exe",
        "description": "Calculator",
    },
    {
        "keys": "ctrl+alt+shift+v", "action": "paste",
        "description": "Paste clipboard as plain text",
    },
    {
        "keys": "ctrl+alt+shift+left", "action": "window", "value": "left",
        "description": "Snap window left",
    },
    {
        "keys": "ctrl+alt+shift+right", "action": "window", "value": "right",
        "description": "Snap window right",
    },
    {
        "keys": "ctrl+alt+shift+m", "action": "media", "value": "mute",
        "description": "Mute / unmute",
    },
    {
        "keys": "ctrl+alt+shift+l", "action": "system", "value": "lock",
        "description": "Lock the PC",
    },
]


@dataclass(slots=True)
class Entry:
    keys: str
    action: str
    value: str = ""
    extra: dict = field(default_factory=dict)
    description: str = ""
    enabled: bool = True
    mods: int = 0
    vk: int = 0
    vks: tuple[int, ...] = field(default_factory=tuple)
    trigger: str = "press"
    apps: tuple[str, ...] = field(default_factory=tuple)
    index: int = 0
    seq: tuple[tuple[int, tuple[int, ...]], ...] = field(default_factory=tuple)
    profiles: tuple[str, ...] = field(default_factory=tuple)

    @property
    def display(self) -> str:
        if self.seq:
            return keys.format_sequence(self.seq)
        return keys.pretty(self.keys)

    @property
    def is_sequence(self) -> bool:
        return bool(self.seq)

    def label(self) -> str:
        return self.description or self.value or self.action

    def scope(self) -> str:
        """Human readable app scope ('' means every app)."""
        if not self.apps:
            return ""
        if len(self.apps) <= 2:
            return ", ".join(self.apps)
        return f"{self.apps[0]} +{len(self.apps) - 1}"

    def profile_scope(self) -> str:
        return ", ".join(self.profiles)

    def to_json(self) -> dict:
        data: dict = {"keys": self.keys, "action": self.action}
        if self.value:
            data["value"] = self.value
        for k, v in self.extra.items():
            data[k] = v
        if self.description:
            data["description"] = self.description
        if not self.enabled:
            data["enabled"] = False
        if self.trigger and self.trigger != "press":
            data["trigger"] = self.trigger
        if len(self.apps) == 1:
            data["app"] = self.apps[0]
        elif self.apps:
            data["apps"] = list(self.apps)
        if len(self.profiles) == 1:
            data["profile"] = self.profiles[0]
        elif self.profiles:
            data["profiles"] = list(self.profiles)
        return data


@dataclass
class Config:
    path: str
    settings: dict = field(default_factory=lambda: dict(DEFAULT_SETTINGS))
    entries: list[Entry] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    mtime: float = 0.0
    raw: dict = field(default_factory=dict)
    active_profile: str = ""

    def profiles(self) -> tuple[str, ...]:
        return profile_names(self.entries)

    def is_active(self, entry: Entry) -> bool:
        return entry_is_active(entry, self.active_profile)


def default_config() -> dict:
    return {
        "version": 1,
        "settings": dict(DEFAULT_SETTINGS),
        "hotkeys": [dict(item) for item in DEFAULT_HOTKEYS],
    }


def ensure_default(path: str) -> bool:
    """Create the config file with starter hotkeys if it does not exist."""
    if os.path.exists(path):
        return False
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    save_raw(path, default_config())
    return True


def _norm_app(name: str) -> str:
    text = str(name or "").strip().strip('"').replace("/", "\\").lower()
    return text.rsplit("\\", 1)[-1]


def _parse_apps(item: dict, where: str, warnings: list[str]) -> tuple[str, ...]:
    """Read "app" (string) or "apps" (list) from a hotkey object."""
    raw = item.get("apps", item.get("app"))
    if raw is None or raw == "":
        return ()
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, (list, tuple)):
        values = list(raw)
    else:
        warnings.append(f"{where}: \"app\" must be a name or a list of names; ignored")
        return ()
    result: list[str] = []
    for value in values:
        if not isinstance(value, str):
            warnings.append(f"{where}: app names must be strings; skipped one")
            continue
        name = _norm_app(value)
        if name and name not in result:
            result.append(name)
    return tuple(result)


def _parse_profiles(item: dict, where: str, warnings: list[str]) -> tuple[str, ...]:
    """Read "profile" (string) or "profiles" (list) from a hotkey object."""
    raw = item.get("profiles", item.get("profile"))
    if raw is None or raw == "":
        return ()
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, (list, tuple)):
        values = list(raw)
    else:
        warnings.append(f"{where}: \"profile\" must be a name or a list of names; ignored")
        return ()
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            warnings.append(f"{where}: profile names must be strings; skipped one")
            continue
        name = value.strip()
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            result.append(name)
    return tuple(result)


def profile_names(entries) -> tuple[str, ...]:
    """Every profile mentioned by an entry, in first-seen order."""
    names: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        for name in entry.profiles:
            key = name.casefold()
            if key not in seen:
                seen.add(key)
                names.append(name)
    return tuple(names)


def profiles_overlap(a, b) -> bool:
    """Can two entries ever be active at the same time?

    Untagged entries are always active, so they overlap with every profile.
    """
    left = {p.casefold() for p in a}
    right = {p.casefold() for p in b}
    if not left or not right:
        return True
    return bool(left & right)


def entry_is_active(entry: Entry, profile: str) -> bool:
    """Profile filter.  Untagged entries run everywhere; profile-switch
    hotkeys must stay reachable or you could never leave a profile."""
    if entry.action == "profile" or not entry.profiles:
        return True
    if not profile:
        return False
    want = profile.casefold()
    return any(p.casefold() == want for p in entry.profiles)


def _entry_from_json(item: dict, index: int, errors: list[str],
                     warnings: list[str]) -> Entry | None:
    where = f"hotkey #{index + 1}"
    if not isinstance(item, dict):
        errors.append(f"{where}: must be an object")
        return None
    combo = str(item.get("keys", "")).strip()
    if not combo:
        errors.append(f"{where}: missing \"keys\"")
        return None
    action = str(item.get("action", "")).strip().lower()
    if not action:
        errors.append(f"{where} ({combo}): missing \"action\"")
        return None
    seq: tuple[tuple[int, tuple[int, ...]], ...] = ()
    try:
        if keys.is_sequence(combo):
            seq = keys.parse_sequence(combo)
            mods, vks = seq[0]
        else:
            mods, vks = keys.parse_all(combo)
    except keys.HotkeyError as exc:
        errors.append(f"{where}: {exc}")
        return None
    extra = {
        k: v for k, v in item.items()
        if k not in ("keys", "action", "value", "description", "enabled",
                     "trigger", "app", "apps", "profile", "profiles")
    }
    value = item.get("value", "")
    if value is None:
        value = ""
    trigger = str(item.get("trigger", "press")).lower()
    if trigger not in ("press", "tap", "hold", "double"):
        warnings.append(f"{where} ({combo}): unknown trigger {trigger!r}; using press")
        trigger = "press"
    if (len(vks) > 1 or seq) and trigger != "press":
        warnings.append(
            f"{where} ({combo}): trigger {trigger!r} only works on single keys; using press")
        trigger = "press"
    apps = _parse_apps(item, where, warnings)
    profiles = _parse_profiles(item, where, warnings)
    return Entry(
        keys=combo,
        action=action,
        value=str(value),
        extra=extra,
        description=str(item.get("description", "") or ""),
        enabled=bool(item.get("enabled", True)),
        mods=mods,
        vk=vks[0] if vks else 0,
        vks=vks,
        trigger=trigger,
        apps=apps,
        index=index,
        seq=seq,
        profiles=profiles,
    )


def load(path: str) -> Config:
    cfg = Config(path=path)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        cfg.errors.append(f"config not found: {path}")
        return cfg
    except json.JSONDecodeError as exc:
        cfg.errors.append(f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}")
        return cfg
    except OSError as exc:
        cfg.errors.append(f"cannot read config: {exc}")
        return cfg

    if not isinstance(raw, dict):
        cfg.errors.append("config root must be a JSON object")
        return cfg
    cfg.raw = raw
    try:
        cfg.mtime = os.stat(path).st_mtime_ns
    except OSError:
        cfg.mtime = 0

    settings = raw.get("settings")
    cfg.settings = dict(DEFAULT_SETTINGS)
    if isinstance(settings, dict):
        for name in DEFAULT_SETTINGS:
            if name in settings:
                cfg.settings[name] = settings[name]
    elif settings is not None:
        cfg.errors.append("\"settings\" must be an object")

    try:
        cfg.settings["typing_delay_ms"] = max(0, min(50, int(cfg.settings["typing_delay_ms"])))
    except (TypeError, ValueError):
        cfg.settings["typing_delay_ms"] = DEFAULT_SETTINGS["typing_delay_ms"]

    try:
        cfg.settings["hold_ms"] = max(150, min(3000, int(cfg.settings["hold_ms"])))
    except (TypeError, ValueError):
        cfg.settings["hold_ms"] = DEFAULT_SETTINGS["hold_ms"]

    try:
        cfg.settings["leader_timeout_ms"] = max(
            300, min(5000, int(cfg.settings["leader_timeout_ms"])))
    except (TypeError, ValueError):
        cfg.settings["leader_timeout_ms"] = DEFAULT_SETTINGS["leader_timeout_ms"]

    try:
        cfg.settings["update_interval_hours"] = max(
            1, min(168, int(cfg.settings["update_interval_hours"])))
    except (TypeError, ValueError):
        cfg.settings["update_interval_hours"] = DEFAULT_SETTINGS["update_interval_hours"]
    for name in ("update_url", "update_token", "update_token_env"):
        cfg.settings[name] = str(cfg.settings.get(name) or "").strip()
    if not cfg.settings["update_url"]:
        cfg.settings["update_url"] = DEFAULT_SETTINGS["update_url"]

    requested_lang = str(cfg.settings.get("language") or "").strip().lower()
    lang = i18n.normalize(requested_lang)
    if requested_lang and requested_lang != lang:
        cfg.warnings.append(f"language {requested_lang!r} ignored; using {lang}")
    cfg.settings["language"] = lang

    active = raw.get("active_profile", "")
    if active is None:
        active = ""
    if not isinstance(active, str):
        cfg.warnings.append("\"active_profile\" must be a string; using no profile")
        active = ""
    cfg.active_profile = active.strip()

    suspend = cfg.settings.get("suspend_hotkey")
    if suspend:
        try:
            keys.parse(str(suspend))
        except keys.HotkeyError as exc:
            cfg.warnings.append(f"suspend_hotkey ignored: {exc}")
            cfg.settings["suspend_hotkey"] = ""

    # Macro start/stop keys are global. A bare letter or arrow would swallow
    # normal typing/navigation, so only combos and deliberately safe bare keys
    # (F13-F24, media keys, mouse buttons) are accepted.
    for name in ("macro_start_hotkey", "macro_stop_hotkey"):
        combo = str(cfg.settings.get(name) or "").strip()
        if not combo:
            continue
        try:
            keys.parse_all(combo)
        except keys.HotkeyError as exc:
            cfg.warnings.append(f"{name} ignored: {exc}")
            cfg.settings[name] = ""

    items = raw.get("hotkeys")
    if not isinstance(items, list):
        cfg.errors.append("\"hotkeys\" must be a list")
        return cfg
    for i, item in enumerate(items):
        entry = _entry_from_json(item, i, cfg.errors, cfg.warnings)
        if entry is not None:
            cfg.entries.append(entry)

    seen: dict[str, str] = {}
    seen_actions: dict[str, str] = {}
    for entry in cfg.entries:
        profiles = frozenset(p.casefold() for p in entry.profiles)
        norm = (f"{entry.mods}:{frozenset(entry.vks)}:{entry.seq}:"
                f"{entry.trigger}:{entry.apps}:{profiles}")
        if norm in seen:
            cfg.warnings.append(
                f"{entry.display} is duplicated (also used by \"{seen[norm]}\")"
            )
        else:
            seen[norm] = entry.label()
        macro_sig = ""
        if entry.action == "macro":
            # Macro bindings have an empty value; without the recorded steps
            # two different macros on the same combo look like duplicates.
            macro_sig = ":" + json.dumps(
                [entry.extra.get("steps"), entry.extra.get("speed", 1.0)],
                sort_keys=True, default=str)
        act = (f"{entry.mods}:{frozenset(entry.vks)}:{entry.seq}:{entry.trigger}:"
               f"{entry.action}:{entry.value.strip()}:{entry.apps}:{profiles}"
               f"{macro_sig}")
        if act in seen_actions:
            cfg.warnings.append(
                f"{entry.display} already does the same action "
                f"(also used by \"{seen_actions[act]}\")"
            )
        else:
            seen_actions[act] = entry.label()
    if cfg.active_profile and not any(
            any(p.casefold() == cfg.active_profile.casefold() for p in e.profiles)
            for e in cfg.entries):
        cfg.warnings.append(
            f"active_profile {cfg.active_profile!r} matches no hotkeys")
    return cfg


def save_raw(path: str, data: dict) -> None:
    folder = os.path.dirname(path) or "."
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".hotkeys-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def to_raw(cfg: Config) -> dict:
    data = {
        "version": 1,
        "settings": dict(cfg.settings),
        "hotkeys": [entry.to_json() for entry in cfg.entries],
    }
    if getattr(cfg, "active_profile", ""):
        data["active_profile"] = cfg.active_profile
    return data
