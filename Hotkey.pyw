#!/usr/bin/env pythonw
"""Hotkey launcher.

Double-click this file, or run:  pythonw Hotkey.pyw
Console output for debugging:    python Hotkey.pyw --verbose
"""
import ctypes
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _fatal() -> None:
    text = traceback.format_exc()
    try:
        folder = os.path.join(os.environ.get("LOCALAPPDATA") or ROOT, "Hotkey")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "crash.log"), "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    except OSError:
        pass
    try:
        ctypes.windll.user32.MessageBoxW(
            None,
            "Hotkey could not start.\n\n" + text.strip().splitlines()[-1] +
            "\n\nDetails: %LOCALAPPDATA%\\Hotkey\\crash.log",
            "Hotkey", 0x10)
    except Exception:
        pass


if __name__ == "__main__":
    try:
        from hk.app import main
        code = main()
    except SystemExit:
        raise
    except BaseException:
        _fatal()
        code = 1
    raise SystemExit(code)
