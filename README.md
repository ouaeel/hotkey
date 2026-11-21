# Hotkey

A tiny, **zero-dependency** global hotkey manager for Windows.
One file to configure, a tray icon to live in, and **no background CPU** — it sleeps
inside the Win32 message loop until you press a key.

```text
                    ⚡  no pip install  ·  no polling  ·  hooks only when needed
```

| | |
|---|---|
| **Idle CPU** | 0.0 % (blocked in `GetMessage`) |
| **Memory** | ~26 MB working set, 1 thread (tray-only mode) |
| **Dependencies** | Python standard library only |
| **Hotkey engine** | `RegisterHotKey` — real OS hotkeys, work in games and fullscreen apps |
| **UI** | tray icon + optional tkinter editor (English / Français / العربية with RTL layout, enlarged fonts) |
| **Config** | `hotkeys.json`, auto-reloaded on save |

---

## Quick start

1. Double-click **`Hotkey.pyw`** (or `run.bat`).
2. A mint lightning icon appears in the system tray.
3. Press one of the starter hotkeys:

| Shortcut | What happens |
|---|---|
| `Ctrl+Alt+T` | Terminal |
| `Ctrl+Alt+E` | File Explorer (home) |
| `Ctrl+Alt+B` | Browser |
| `Ctrl+Alt+D` | Types today's date |
| `Ctrl+Alt+Shift+S` | Screenshot (region) |
| `Ctrl+Alt+Shift+C` | Calculator |
| `Ctrl+Alt+Shift+V` | Types the clipboard as plain text |
| `Ctrl+Alt+Shift+← / →` | Snap active window left / right |
| `Ctrl+Alt+Shift+M` | Mute / unmute |
| `Ctrl+Alt+Shift+L` | Lock the PC |
| `Ctrl+Alt+Shift+P` | Pause **all** hotkeys (press again to resume) |

4. **Double-click the tray icon** to open the visual editor.
   Right-click the tray icon for a menu with the active hotkey list, reload,
   autostart, pause and quit.

> Windows may hide new tray icons in the overflow flyout (`^`). Drag the icon onto
> the taskbar if you want it always visible.

---

## The editor

- Add / edit / delete hotkeys without touching JSON. **Edit** and **Delete**
  stay disabled until a row is selected; an empty list shows a short hint.
- **Type** / **Capture** toggle: capture mode records the key or mouse button
  you press. A line under the field confirms the parsed shortcut immediately,
  or explains why it is not valid yet. **Steps** builds a leader sequence such
  as `Ctrl+K > D`.
- **Only in app**: leave blank to work everywhere, or type an app name
  (`chrome.exe`, `code`) to scope the shortcut. **Detect** hides the dialog for
  four seconds — switch to the app you want and it is filled in for you.
  **Any** clears it back to global.
- Mouse buttons work too: `mouse4` / `mouse5` (side buttons), `mouse_middle`,
  or `ctrl+mouse_left` / `ctrl+mouse_right`.
- Per-hotkey **Advanced JSON** for extra options (`cwd`, `fallback`, `repeat`, …).
  It is pretty-printed and scrollable; duplicate steps/speed are managed by the
  macro recorder.
- Changes are saved atomically and applied immediately — no restart.
- `Ctrl+N` new, `Ctrl+E` edit, `Delete` remove, double-click to edit.
- Typing a shortcut manually also works: `ctrl+alt+k`, `win+shift+s`, `f13`.

---

## Configuration (`hotkeys.json`)

```json
{
  "version": 1,
  "settings": {
    "show_notifications": true,
    "notify_on_start": false,
    "reload_on_change": true,
    "language": "en",
    "typing_delay_ms": 2,
    "suspend_hotkey": "ctrl+alt+shift+p"
  },
  "hotkeys": [
    {
      "keys": "ctrl+alt+t",
      "action": "open",
      "value": "wt.exe",
      "fallback": "powershell.exe",
      "description": "Terminal"
    },
    {
      "keys": "ctrl+alt+d",
      "action": "type",
      "value": "{date} — {time}"
    },
    {
      "keys": "j+k",
      "action": "media",
      "value": "play_pause",
      "description": "Chord: play/pause"
    },
    {
      "keys": "ctrl+alt+t",
      "action": "keys",
      "value": "ctrl+shift+t",
      "app": "chrome.exe",
      "description": "Chrome only: reopen closed tab"
    }
  ]
}
```

Every entry needs `keys` and `action`. `value` is the action's main argument.
`description` is cosmetic (shown in the tray menu and the editor).

Restart the app or press **Reload** after a manual edit. Saving the file while the
app is running is enough if `reload_on_change` is `true` (default).

### Settings

| Key | Meaning |
|---|---|
| `show_notifications` | Tray balloons for reloads and errors |
| `notify_on_start` | Balloon when the app starts |
| `reload_on_change` | Watch `hotkeys.json` and apply edits automatically |
| `language` | Interface language: `en`, `fr` or `ar` (default `en`) |
| `typing_delay_ms` | Delay between typed characters (0–50 ms) |
| `hold_ms` | Long-press / double-click threshold in ms (150–3000, default 400) |
| `suspend_hotkey` | Shortcut that pauses/resumes everything (always active) |

The settings window's top header has a ⚙ button to the right of
**Open hotkeys.json**. It opens a small **Quick settings** window containing the
language selector (English, Français and العربية) and a **Show notifications**
on/off switch. Hovering the gear shows its current notification state in the
status bar. Changes save `settings.language` / `settings.show_notifications`
and immediately re-translate the editor and tray menu.
العربية switches the whole interface to right-to-left layout; reopen the macro
control window to translate that one. Invalid values fall back to English with
a warning in the log.

Interface fonts use a 1.2× boost with a minimum UI scale of 1.1, so labels and
the hotkey list stay readable on high-DPI and standard displays alike. While the
settings window is open, firing a saved shortcut (press, double-click or
long-press) selects and briefly highlights its row.

### Long press, double click and chords

Every hotkey has a **Trigger** (editor dropdown or `"trigger"` in JSON):

| Trigger | Fires when |
|---|---|
| `press` (default) | The key goes down — same as before |
| `double` | The key is pressed twice within `hold_ms` |
| `hold` | The key has been held for `hold_ms` (default 400 ms) |

```json
{ "keys": "ctrl+alt+m", "action": "media", "value": "mute", "trigger": "double" }
```

**Chords** — press two or three non-modifier keys together, e.g. `j+k` or
`ctrl+j+k`. They are detected by a passive low-level keyboard hook (installed
only when a config actually uses chords or tap/hold) and fire the instant all
keys are down. The editor captures them automatically: hold `J`, press `K`,
release both → `J+K`.

`hold_ms` lives in `settings` (150–3000 ms) and can be overridden per hotkey
with `"hold_ms": 600` in its Advanced JSON.

### Per-app hotkeys

By default a hotkey works in **every** app. Set **Only in app** in the editor
(or `"app"` in JSON) to limit it to one or more programs:

```json
{ "keys": "ctrl+alt+t", "action": "open", "value": "wt.exe",
  "description": "Terminal everywhere" },
{ "keys": "ctrl+alt+t", "action": "keys", "value": "ctrl+shift+t",
  "app": "chrome.exe", "description": "Chrome: reopen closed tab" },
{ "keys": "ctrl+alt+t", "action": "run", "value": "code .",
  "apps": ["code.exe", "cursor.exe"], "description": "Editor: open project" }
```

- `app` is a name (`chrome.exe`), a stem (`chrome`), or a wildcard
  (`*code*`). Case does not matter.
- `apps` takes a list. Both forms are accepted, and the editor writes a
  comma-separated list as `apps`.
- The **most specific rule wins**: inside Chrome, the Chrome entry runs and
  the global one is skipped; everywhere else the global one runs. That is how
  one shortcut can mean different things per app.
- **Detect** in the editor hides the dialog for four seconds — switch to the
  target app and its executable name is captured.

Global hotkeys still use `RegisterHotKey`. App-scoped hotkeys use the passive
keyboard hook (Windows' native hotkeys cannot filter by window), and so does a
global hotkey that shares its combo with a scoped one.

### Actions

| `action` | `value` | Example |
|---|---|---|
| `open` | App, file, folder or URL | `"wt.exe"`, `"https://github.com"`, `"%USERPROFILE%\\Desktop"` |
| `run` | Command line, hidden window | `"python -m http.server 8000"` |
| `type` | Text typed into the active app | `"Hello {user}, it is {time}"` |
| `keys` | Keystrokes to send (`,` = sequence) | `"ctrl+v"`, `"ctrl+a, delete"` |
| `clip` | Copy text to the clipboard | `"{date}"` |
| `paste` | Type the clipboard as plain text | *(no value)* |
| `media` | `play_pause` `next` `prev` `stop` `volume_up` `volume_down` `mute` | `"volume_up"` |
| `window` | `left` `right` `top` `bottom` `maximize` `minimize` `restore` `center` `topmost` `close` | `"left"` |
| `system` | `lock` `sleep` `screenshot` `recycle` `taskmanager` | `"screenshot"` |
| `app` | `settings` `reload` `suspend` `config` `log` `quit` | `"reload"` |

#### Extra options (top level next to `value`)

| Option | Used by | Meaning |
|---|---|---|
| `fallback` | `open` | Second target if the first one fails (e.g. `wt.exe` → `powershell.exe`) |
| `cwd` | `run` | Working directory for the command |
| `repeat` | `media` | How many times to press the key (volume steps) |
| `delay_ms` | `keys` | Pause between comma-separated combos |
| `paste` | `clip` | `true` also sends `Ctrl+V` after copying |
| `enabled` | all | `false` keeps the entry but does not register it |
| `trigger` | all | `press` (default), `double`, `hold`, or `tap` |
| `hold_ms` | all | override the long-press threshold for this hotkey |
| `app` / `apps` | all | limit the hotkey to an app (name, stem or wildcard) |

#### Text tokens (`type`, `clip`)

| Token | Output |
|---|---|
| `{date}` | `2026-11-20` |
| `{time}` | `19:42` |
| `{datetime}` | `2026-11-20 19:42` |
| `{day}` | `Friday` |
| `{date:%d/%m/%Y}` | Any `strftime` format |
| `{clip}` | Current clipboard text |
| `{user}` | Windows username |
| `{computer}` | Computer name |
| `{uuid}` | Random UUID |
| `{newline}` `{tab}` | Handy inside text |

---

## Command line

```bat
python Hotkey.pyw                     :: start (console visible)
pythonw Hotkey.pyw                    :: start silently
python Hotkey.pyw --verbose           :: log to stderr
python Hotkey.pyw --settings          :: start + open the editor
python Hotkey.pyw --reload            :: reload the running instance
python Hotkey.pyw --quit              :: stop the running instance
python Hotkey.pyw --list              :: print configured hotkeys
python Hotkey.pyw --validate          :: check the JSON and report problems
python Hotkey.pyw --self-test --full  :: hardware/OS diagnostics
python Hotkey.pyw --install-autostart
python Hotkey.pyw --remove-autostart
```

`--config "D:\path\my-hotkeys.json"` runs with a different file.

Only one instance runs at a time (named mutex); a second launch exits quietly so
Windows startup never duplicates it.

---

## Autostart

Use the tray menu (**Start with Windows**), the editor checkbox, or
`install-autostart.bat`. It writes a single value under

```text
HKCU\Software\Microsoft\Windows\CurrentVersion\Run
```

which launches `pythonw Hotkey.pyw --config <your file>`. No admin rights needed.
Turn it off the same way, or run `python Hotkey.pyw --remove-autostart`.

---

## Files

```text
hotkey\
  Hotkey.pyw              launcher (no console window)
  run.bat                 start in the background
  run-console.bat         start with a visible log
  install-autostart.bat   enable autostart
  hotkeys.json            your configuration
  hk\
    app.py                hidden window, message loop, tray, hotkey registry
    actions.py            what each action does
    config.py             JSON load/validate/atomic save
    gui.py                tkinter editor (loaded only when opened)
    hooks.py              keyboard/mouse hook + press/double/hold engine
    icon.py               generates the tray icon at runtime
    keys.py               key names ↔ virtual-key codes
    selftest.py           diagnostics
    win32.py              ctypes bindings
  build\                  nothing important (fallback for generated icons)
```

Runtime data lives in `%LOCALAPPDATA%\Hotkey\`:

- `hotkey.log` — errors and hotkey activity (rotated, 128 KB × 2)
- `hotkey.ico`, `hotkey-paused.ico` — cached tray icons

---

## How it stays light

- **No keyboard hooks for ordinary hotkeys.** Unlike AutoHotkey-style tools, it
  uses `RegisterHotKey`, so Windows wakes the process only when *your* combo is
  pressed. Nothing scans keystrokes, nothing timers-poll the keyboard. The
  passive hook is installed only when a config uses chords, double click, hold,
  mouse buttons or per-app scoping.
- **One thread, one window.** The tray icon and all hotkeys share a single hidden
  window and message loop. The tkinter editor is imported and started only when
  you open it.
- **Zero third-party packages.** `ctypes`, `json`, `subprocess`, `zlib`,
  `tkinter` — all standard library.
- **No disk churn.** The config file's timestamp is checked by a 2.5 s timer
  (`WM_TIMER`), so external edits still load instantly without a file-watcher
  thread.
- **Lazy imports.** `tkinter`, `winreg` and heavy helpers load on demand.

Measured on this machine with 11 hotkeys: **0.0 % CPU over 10 s idle**, about
**26 MB working set**, **1 thread**, ~180 handles.

---

## Troubleshooting

**The hotkey does nothing.**
Another app already owns it. Open `%LOCALAPPDATA%\Hotkey\hotkey.log` — conflicts
are logged as `hotkey unavailable: ...`. Pick another combination (the editor
warns about duplicates inside your own config, not other apps').

**Nothing starts.**
Run `run-console.bat` and read the output, or `python Hotkey.pyw --self-test`.
A fatal startup error is also written to `%LOCALAPPDATA%\Hotkey\crash.log` and
shown in a message box.

**Python is not installed.**
Install Python 3.10+ from python.org and tick *Add python.exe to PATH*. tkinter is
included in the official installer.

**Typed text loses characters in a slow app.**
Raise `typing_delay_ms` (e.g. `8`) in `settings`.

**A hotkey is swallowed in a game.**
Run the game in borderless/windowed mode, or use a rarer combo: `RegisterHotKey`
combos are global, but some games grab raw keyboard input before Windows.

**Screenshot hotkey opens the snipping overlay.**
That is `ms-screenclip:` — the same tool as `Win+Shift+S`. Region capture needs
the overlay; there is no cheaper built-in way without extra dependencies.

---

## Uninstall

1. Right-click the tray icon → **Quit**.
2. Tray menu → **Start with Windows** (if enabled), or run
   `python Hotkey.pyw --remove-autostart`.
3. Delete the `hotkey` folder and `%LOCALAPPDATA%\Hotkey`.

---

## New in this release

### Summon window (`summon`)

Focus, minimize or launch an app with one key:

    { "keys": "f13", "action": "summon", "value": "chrome.exe" }

Behaviour on each press: if the window is focused it is minimized; if it is
running in the background it is restored and focused; if it is not running it
is launched. The target is matched by executable name.

### Leader-key sequences

Type a prefix, release it, then a second key:

    { "keys": "ctrl+k > d", "action": "keys", "value": "ctrl+shift+delete" }

`ctrl+k` arms a short leader window (configurable `leader_timeout_ms`,
default 1200 ms); the next bare key completes the sequence. Pressing the
prefix shows a tray balloon listing the available next keys.

### Profiles

Entries may be tagged with one or more profiles:

    { "keys": "ctrl+alt+t", "action": "open", "value": "wt.exe", "profile": "Work" }

Untagged entries run everywhere. Switch the active profile from the tray
submenu, the settings window's Profile dropdown, or a hotkey:

    { "keys": "ctrl+alt+p", "action": "profile", "value": "next" }

`value` may be a profile name or `next` to cycle.

### Minimal macro recorder

An entry with action `macro` stores a list of recorded keys **and mouse
clicks/drags**. In the editor, choose **Macro** and click **Record**; the
dialog hides, your keys and mouse buttons (with timing and screen positions)
are captured, and **Esc** stops recording. Replay speed is adjustable.
Mouse movements are replayed along a slightly irregular, eased path instead
of jumping instantly, so the cursor looks human rather than mechanical.
Screen-position macros work best on a fixed layout.

Pressing a macro hotkey does **not** start it instantly: it loads the macro
into a small **Macro control** window so you can set it up first. The tray menu
item **Show / hide macro controls** raises it or hides it again. The window
shows a progress bar and has **Run / Repeat**, **Times** (how many runs),
**Speed**, **Stop** (finish the current run, then quit) and **Cancel** (abort
immediately). Speed and Times are live: changing them while a macro is playing
affects the current playback. **Close** only hides the window; playback keeps
running.

You can also choose your own **Start with** and **Stop with** keys/buttons in
that window: click the button, then press any key or mouse button anywhere
(including `Mouse4`/`Mouse5`, and a modifier such as `Ctrl+Mouse5`); press
**Esc** while capturing to clear it. These are saved in `hotkeys.json` as
`macro_start_hotkey` / `macro_stop_hotkey` and work globally even when the
control window is hidden. The start key plays the loaded macro with the current
settings; the stop key aborts immediately, like **Cancel**. For safety, a bare
letter or arrow cannot be used as a global macro key — use a combo, an
`F13`–`F24` key, a media key or a mouse button.

## Notes & limits

- Windows only (uses Win32 directly).
- Single-key hotkeys are refused unless they are `F13`–`F24`, media keys or a
  mouse side button, so you cannot accidentally disable normal typing.
- Mouse hotkeys run on a passive low-level mouse hook, installed only when a
  config uses one. Only a bound side button (`Mouse4`/`Mouse5`) is swallowed,
  so other apps stop seeing that button; left/right/middle clicks always get
  through, even when they are part of a chord such as `Mouse5+MouseLeft`.
- If a side button has its own hotkey *and* appears in a chord, the chord
  wins: the single hotkey fires when you release the button without
  completing the chord (`Mouse5` alone copies, `Mouse5+Mouse4` runs only the
  chord).
- Hotkeys are paused while the edit dialog is open, so pressing the buttons
  you are recording never runs the old hotkeys in the background.
- One key or button can be used up to three times, once per trigger: for
  example `Mouse5` with trigger *Double click* = copy and `Mouse5` with
  trigger *Long press (hold)* = `win+e`. The same action twice on one button
  is refused: with the action identical there is nothing to tell the entries
  apart, so the button could not choose.
- The same shortcut may also repeat with different app scopes (one global plus
  one per app), and the scoped rule wins inside that app.
- Hotkeys are registered while the app runs; **Suspend** releases them all so
  other apps can use those combos temporarily.
- App-scoped hotkeys compare the **foreground process** (a cached exe-name
  lookup), so they also work in fullscreen apps; there is no per-app polling.
- Chords, double click, hold and per-app scoping use a passive low-level
  keyboard hook, installed only when a config actually needs them. The hook
  only sees key presses (never text), nothing is stored or sent, and it runs
  at 0 % idle CPU. It cannot see keys typed into elevated (admin) windows
  unless the app is elevated too — in that case those hotkeys simply do not
  fire there.
- `run` commands start hidden with `CREATE_NO_WINDOW`. Long-running servers keep
  running after the hotkey is released; use Task Manager or your own script to
  stop them.

MIT-style: do whatever you want with it. Built to be read, changed and kept
running for years.
