"""Key-name <-> Windows virtual-key mapping, and hotkey combo parsing.

No dependencies: everything here is plain Python data.
"""
from __future__ import annotations

import re

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

# --- virtual key codes -------------------------------------------------------
_VK: dict[str, int] = {
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "return": 0x0D,
    "esc": 0x1B, "escape": 0x1B, "space": 0x20,
    "pgup": 0x21, "pageup": 0x21, "pgdn": 0x22, "pagedown": 0x22,
    "end": 0x23, "home": 0x24,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "prtsc": 0x2C, "printscreen": 0x2C, "print": 0x2C,
    "insert": 0x2D, "ins": 0x2D, "delete": 0x2E, "del": 0x2E,
    "win": 0x5B, "lwin": 0x5B, "rwin": 0x5C, "apps": 0x5D, "menu": 0x5D,
    "sleep": 0x5F, "capslock": 0x14, "caps": 0x14,
    "pause": 0x13, "numlock": 0x90, "scrolllock": 0x91,
    "multiply": 0x6A, "add": 0x6B, "subtract": 0x6D, "decimal": 0x6E,
    "divide": 0x6F, "separator": 0x6C,
    "semicolon": 0xBA, "equals": 0xBB, "comma": 0xBC, "minus": 0xBD,
    "period": 0xBE, "dot": 0xBE, "slash": 0xBF, "grave": 0xC0,
    "backtick": 0xC0, "tilde": 0xC0, "lbracket": 0xDB, "rbracket": 0xDD,
    "backslash": 0xDC, "quote": 0xDE, "apostrophe": 0xDE,
    "volume_mute": 0xAD, "mute": 0xAD,
    "volume_down": 0xAE, "volumedown": 0xAE,
    "volume_up": 0xAF, "volumeup": 0xAF,
    "media_next": 0xB0, "medianext": 0xB0,
    "media_prev": 0xB1, "mediaprev": 0xB1,
    "media_stop": 0xB2, "mediastop": 0xB2,
    "media_play": 0xB3, "media_play_pause": 0xB3, "playpause": 0xB3,
    "browser_back": 0xA6, "browser_forward": 0xA7, "browser_refresh": 0xA8,
    "browser_stop": 0xA9, "browser_search": 0xAA, "browser_favorites": 0xAB,
    "browser_home": 0xAC,
    "lbutton": 0x01, "rbutton": 0x02, "mbutton": 0x04,
    "mouse_left": 0x01, "mouse_right": 0x02, "mouse_middle": 0x04,
    "xbutton1": 0x05, "xbutton2": 0x06, "mouse4": 0x05, "mouse5": 0x06,
    # display forms ("MouseMiddle") must parse back when the editor saves
    "mouseleft": 0x01, "mouseright": 0x02, "mousemiddle": 0x04,
    "mediaplaypause": 0xB3,
    "shift": 0xA0, "lshift": 0xA0, "rshift": 0xA1,
    "ctrl": 0xA2, "lctrl": 0xA2, "rctrl": 0xA3,
    "alt": 0xA4, "lalt": 0xA4, "ralt": 0xA5,
}
for _i in range(1, 25):
    _VK[f"f{_i}"] = 0x6F + _i
for _i in range(10):
    _VK[f"numpad{_i}"] = 0x60 + _i
for _c in "abcdefghijklmnopqrstuvwxyz":
    _VK[_c] = ord(_c.upper())
for _d in "0123456789":
    _VK[_d] = ord(_d)

# mouse buttons: 0x01 left, 0x02 right, 0x04 middle, 0x05/0x06 side buttons
MOUSE_VKS = frozenset((0x01, 0x02, 0x04, 0x05, 0x06))

# Names emitted by MouseRecorderHook ("left", "x1", ...) are not the same as
# the names accepted by parse_all/name_to_vk ("mouse_left", "mouse4", ...).
MOUSE_BUTTON_ALIASES = {
    "left": "mouse_left", "right": "mouse_right", "middle": "mouse_middle",
    "x1": "mouse4", "x2": "mouse5",
}


def normalize_mouse_button(name: str) -> str:
    """Translate a recorder button name into a real key name.

    ``name_to_vk("left")`` is the Left arrow, so recorder names must never be
    passed straight to it. Unknown names are returned unchanged.
    """
    text = str(name or "").strip().lower()
    return MOUSE_BUTTON_ALIASES.get(text, text)


def is_mouse_vk(vk: int) -> bool:
    """True for virtual keys that belong to a mouse button."""
    return vk in MOUSE_VKS


# keys that are safe to register without any modifier
_SAFE_BARE = {f"f{i}" for i in range(13, 25)} | {
    "media_next", "media_prev", "media_stop", "media_play_pause",
    "volume_up", "volume_down", "volume_mute", "playpause",
    "xbutton1", "xbutton2", "mouse4", "mouse5", "mouse_middle", "mbutton",
    "mousemiddle", "mediaplaypause",
}

_MODS = {
    "ctrl": MOD_CONTROL, "control": MOD_CONTROL, "ctl": MOD_CONTROL,
    "alt": MOD_ALT, "option": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN, "windows": MOD_WIN, "super": MOD_WIN,
    "meta": MOD_WIN, "cmd": MOD_WIN,
}

_DISPLAY = {
    "enter": "Enter", "tab": "Tab", "esc": "Esc", "space": "Space",
    "backspace": "Backspace", "delete": "Delete", "insert": "Insert",
    "home": "Home", "end": "End", "pgup": "PgUp", "pgdn": "PgDn",
    "left": "Left", "right": "Right", "up": "Up", "down": "Down",
    "prtsc": "PrtSc", "pause": "Pause", "capslock": "CapsLock",
    "numlock": "NumLock", "scrolllock": "ScrollLock", "apps": "Menu",
    "media_play_pause": "MediaPlayPause", "media_next": "MediaNext",
    "media_prev": "MediaPrev", "media_stop": "MediaStop", "media_play": "MediaPlayPause",
    "volume_up": "VolumeUp", "volume_down": "VolumeDown",
    "volume_mute": "VolumeMute", "sleep": "Sleep",
    "minus": "Minus", "equals": "Equals", "comma": "Comma",
    "period": "Period", "slash": "Slash", "backslash": "Backslash",
    "semicolon": "Semicolon", "quote": "Quote", "grave": "Grave",
    "lbracket": "LBracket", "rbracket": "RBracket",
    "lbutton": "MouseLeft", "rbutton": "MouseRight", "mbutton": "MouseMiddle",
    "mouse_left": "MouseLeft", "mouse_right": "MouseRight",
    "mouse_middle": "MouseMiddle",
    "xbutton1": "Mouse4", "xbutton2": "Mouse5",
    "mouse4": "Mouse4", "mouse5": "Mouse5",
}


class HotkeyError(ValueError):
    """Raised when a hotkey string cannot be understood."""


def _canon(name: str) -> str:
    name = name.strip().lower()
    name = {"control": "ctrl", "escape": "esc", "return": "enter",
            "pageup": "pgup", "pagedown": "pgdn", "del": "delete",
            "ins": "insert", "printscreen": "prtsc", "dot": "period",
            "backtick": "grave", "tilde": "grave", "apostrophe": "quote",
            "win": "win"}.get(name, name)
    return name


def parse_all(combo: str, allow_bare: bool = False) -> tuple[int, tuple[int, ...]]:
    """Parse a combo into (modifier mask, ordered virtual-key tuple).

    Accepts single shortcuts ('ctrl+alt+t') and chords of up to three keys
    ('j+k', 'ctrl+j+k').  ``allow_bare`` relaxes the modifier rule for the
    single keys that follow a leader prefix ('ctrl+k > d').
    """
    if not isinstance(combo, str) or not combo.strip():
        raise HotkeyError("hotkey is empty")
    raw = combo.strip().lower()
    parts = [p for p in (raw.split("+") if "+" in raw else raw.split()) if p.strip()]
    if not parts:
        raise HotkeyError(f"invalid hotkey {combo!r}")
    mods = 0
    names: list[str] = []
    for part in parts:
        name = _canon(part)
        if name in _MODS:
            mods |= _MODS[name]
        elif name in _VK:
            if name in names:
                raise HotkeyError(f"key {part!r} is repeated in {combo!r}")
            names.append(name)
        else:
            raise HotkeyError(f"unknown key {part!r} in hotkey {combo!r}")
    if not names:
        raise HotkeyError(f"hotkey {combo!r} needs at least one key")
    if len(names) > 3:
        raise HotkeyError(f"hotkey {combo!r} has too many keys (max 3)")
    if (len(names) == 1 and mods == 0 and names[0] not in _SAFE_BARE
            and not allow_bare):
        raise HotkeyError(f"hotkey {combo!r} needs a modifier (Ctrl/Alt/Shift/Win) "
                          "or use two keys together (e.g. j+k)")
    return mods, tuple(_VK[name] for name in names)


_SEQUENCE_SPLIT = re.compile(r"\s*(?:→|->|>)\s*")


def is_sequence(combo: str) -> bool:
    """True when the text looks like a leader sequence ('ctrl+k > d')."""
    return isinstance(combo, str) and bool(_SEQUENCE_SPLIT.search(combo.strip()))


def parse_sequence(combo: str) -> tuple[tuple[int, tuple[int, ...]], ...]:
    """Parse 'ctrl+k > d' into ((mods, (vk,)), (0, (vk,))).

    The first step is a normal hotkey; every following step is exactly one
    bare key (modifiers typed there are ignored).  A sequence needs at least
    two steps.
    """
    if not is_sequence(combo):
        raise HotkeyError("a leader sequence needs at least two steps "
                          "(for example: Ctrl+K > D)")
    parts = [p for p in _SEQUENCE_SPLIT.split(combo.strip()) if p.strip()]
    if len(parts) < 2:
        raise HotkeyError("a leader sequence needs at least two steps "
                          "(for example: Ctrl+K > D)")
    if len(parts) > 4:
        raise HotkeyError(f"{combo!r} has too many leader steps (max 4)")
    steps: list[tuple[int, tuple[int, ...]]] = []
    for index, part in enumerate(parts):
        mods, vks = parse_all(part, allow_bare=index > 0)
        if len(vks) != 1:
            raise HotkeyError(f"leader step {index + 1} in {combo!r} must be "
                              "a single key")
        if index == 0:
            if is_mouse_vk(vks[0]):
                raise HotkeyError("a leader sequence needs a keyboard prefix")
        elif mods:
            raise HotkeyError(f"leader step {index + 1} in {combo!r} must be a "
                              "bare key (the prefix modifiers are not held)")
        steps.append((mods, vks))
    return tuple(steps)


def format_sequence(steps) -> str:
    """Render parsed steps back to 'Ctrl+K > D'."""
    return " > ".join(format_many(mods, vks) for mods, vks in steps)


def parse(combo: str, allow_bare: bool = False) -> tuple[int, int]:
    """Parse 'ctrl+alt+t' into (modifier mask, virtual-key code).

    ``allow_bare`` is for synthetic keystrokes, where a bare key such as
    ``delete`` is safe: the bare-key rule only protects global hotkey
    registration from hijacking ordinary typing.
    """
    mods, vks = parse_all(combo, allow_bare=allow_bare)
    if len(vks) != 1:
        raise HotkeyError(f"{combo!r} is a chord; the hook engine handles those")
    return mods, vks[0]


def is_chord(combo: str) -> bool:
    try:
        return len(parse_all(combo)[1]) > 1
    except HotkeyError:
        return False


def _vk_to_name(vk: int) -> str:
    for name, code in _VK.items():
        if code == vk:
            if name in _DISPLAY:
                return _DISPLAY[name]
            if len(name) == 1:
                return name.upper()
            if name.startswith("f") and name[1:].isdigit():
                return name.upper()
            if name.startswith("numpad"):
                return name[0].upper() + name[1:]
            return name.replace("_", " ").title().replace(" ", "")
    return f"0x{vk:02X}"


def format_many(mods: int, vks: tuple[int, ...] | list[int]) -> str:
    """Render a modifier mask + one or more keys back to 'Ctrl+J+K'."""
    bits = []
    if mods & MOD_CONTROL:
        bits.append("Ctrl")
    if mods & MOD_ALT:
        bits.append("Alt")
    if mods & MOD_SHIFT:
        bits.append("Shift")
    if mods & MOD_WIN:
        bits.append("Win")
    bits.extend(_vk_to_name(vk) for vk in vks)
    return "+".join(bits)


def format_combo(mods: int, vk: int) -> str:
    """Render a modifier mask + virtual key back to 'Ctrl+Alt+T'."""
    return format_many(mods, (vk,))


def pretty(combo: str) -> str:
    """Canonical display form of a user supplied combo (never raises)."""
    try:
        return format_many(*parse_all(combo))
    except HotkeyError:
        return combo


_KEYSYM = {
    "return": "enter", "escape": "esc", "prior": "pgup", "next": "pgdn",
    "print": "prtsc", "caps_lock": "capslock", "num_lock": "numlock",
    "scroll_lock": "scrolllock", "menu": "apps", "backslash": "backslash",
    "bar": "backslash", "slash": "slash", "question": "slash",
    "period": "period", "comma": "comma", "semicolon": "semicolon",
    "colon": "semicolon", "apostrophe": "quote", "quotedbl": "quote",
    "minus": "minus", "underscore": "minus", "equal": "equals",
    "plus": "equals", "bracketleft": "lbracket", "bracketright": "rbracket",
    "grave": "grave", "asciitilde": "grave", "space": "space",
    "delete": "delete", "insert": "insert", "home": "home", "end": "end",
    "left": "left", "right": "right", "up": "up", "down": "down",
    "tab": "tab", "backspace": "backspace", "pause": "pause",
    "kp_0": "numpad0", "kp_1": "numpad1", "kp_2": "numpad2",
    "kp_3": "numpad3", "kp_4": "numpad4", "kp_5": "numpad5",
    "kp_6": "numpad6", "kp_7": "numpad7", "kp_8": "numpad8",
    "kp_9": "numpad9", "kp_multiply": "multiply", "kp_add": "add",
    "kp_subtract": "subtract", "kp_divide": "divide", "kp_decimal": "decimal",
}

MODIFIER_KEYSYMS = {
    "control_l", "control_r", "shift_l", "shift_r", "alt_l", "alt_r",
    "win_l", "win_r", "super_l", "super_r", "meta_l", "meta_r",
}

# virtual keys that only act as modifiers (never bound as chord keys)
def keysym_to_name(keysym: str) -> str | None:
    """Translate a Tk keysym into one of our key names (or None)."""
    if not keysym:
        return None
    ks = keysym.lower()
    if ks in MODIFIER_KEYSYMS:
        return None
    if ks in _KEYSYM:
        return _KEYSYM[ks]
    if len(ks) == 1 and (ks.isalnum() or ks in "`-=[]\\;',./"):
        return _canon(ks)
    if ks.startswith("f") and ks[1:].isdigit() and 1 <= int(ks[1:]) <= 24:
        return ks
    return None


def mods_from_state(state: int) -> int:
    """Best-effort modifier mask from a Tk event.state value.

    Tk on Windows reports Alt with the 0x20000 bit.  The 0x8 (Mod1) bit has
    to be ignored: it is set on every key press on Windows, which made every
    recorded combo come out with a phantom Alt.  Callers also OR in the
    physical state (win32.current_mods()) for the Win key.
    """
    mods = 0
    if state & 0x0001:
        mods |= MOD_SHIFT
    if state & 0x0004:
        mods |= MOD_CONTROL
    if state & 0x20000:
        mods |= MOD_ALT
    if state & 0x0040:
        mods |= MOD_WIN
    return mods


def name_to_vk(name: str) -> int | None:
    """Return the virtual key for one of our key names (or None)."""
    if not name:
        return None
    name = _canon(name)
    if name in _MODS:
        return None
    if name in _VK:
        return _VK[name]
    return None
