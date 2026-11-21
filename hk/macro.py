"""Shared state between macro playback and its small control window.

The playback thread owns the steps; the control window only reads a snapshot
and sends commands (stop / cancel / speed / times).  Everything is guarded by
one lock so no Tk or Win32 callback ever touches half-updated state.
"""
from __future__ import annotations

import threading


class MacroControl:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.steps: list = []
        self.name: str = "macro"
        self.times: int = 1
        self.speed: float = 1.0
        self.speed_touched: bool = False
        self.running: bool = False
        self.run_index: int = 0
        self.total_runs: int = 1
        self.step_index: int = 0
        self.total_steps: int = 0
        self.last_entry = None
        self.on_show = None          # callable(): bring the control window up
        self.on_update = None        # callable(): refresh the control window
        self._stop = False
        self._cancel = False

    # -- snapshot -------------------------------------------------------------
    def snapshot(self) -> dict:
        with self._lock:
            return {
                "name": self.name,
                "steps": self.total_steps,
                "times": self.times,
                "speed": self.speed,
                "running": self.running,
                "loaded": bool(self.steps),
                "run": self.run_index,
                "total_runs": self.total_runs,
                "step": self.step_index,
                "stopping": self._stop,
                "cancelling": self._cancel,
            }

    # -- configuration from the window ---------------------------------------
    def set_times(self, value) -> None:
        try:
            n = int(value)
        except (TypeError, ValueError):
            return
        with self._lock:
            self.times = max(1, min(999, n))
            # Keep the progress denominator in step with the visible setting,
            # including while a macro is playing. The worker re-reads it every
            # run so the change takes effect live.
            self.total_runs = self.times
        self._changed()

    def set_speed(self, value) -> None:
        try:
            s = float(value)
        except (TypeError, ValueError):
            return
        with self._lock:
            self.speed = max(0.1, min(8.0, s))
            self.speed_touched = True
        self._changed()

    def stop(self) -> None:
        """Finish the current run, then stop. Steps are not cut short."""
        with self._lock:
            self._stop = True
        self._changed()

    def cancel(self) -> None:
        """Abort immediately, at the next safe point inside the step loop."""
        with self._lock:
            self._cancel = True
            self._stop = True
        self._changed()

    # -- prepare (hotkey just loads the macro, does not start it) -------------
    def prepare(self, steps: list, name: str = "macro", entry=None,
                speed=None) -> None:
        with self._lock:
            self.steps = list(steps)
            self.name = str(name)
            self.last_entry = entry
            if speed is not None and not self.speed_touched:
                try:
                    self.speed = max(0.1, min(8.0, float(speed)))
                except (TypeError, ValueError):
                    pass
            self.running = False
            self.run_index = 0
            self.step_index = 0
            self.total_steps = len(self.steps)
            self.total_runs = self.times
            self._stop = False
            self._cancel = False
        self._changed()
        show = self.on_show
        if callable(show):
            try:
                show()
            except Exception:
                pass

    # -- playback -------------------------------------------------------------
    def begin(self, steps: list, name: str = "macro", entry=None,
              times: int | None = None, speed: float | None = None) -> None:
        with self._lock:
            if times is None:
                times = self.times
            if speed is None:
                speed = self.speed
            self.steps = list(steps)
            self.name = str(name)
            self.last_entry = entry
            self.times = max(1, min(999, int(times)))
            self.total_runs = self.times
            try:
                self.speed = max(0.1, min(8.0, float(speed)))
            except (TypeError, ValueError):
                self.speed = 1.0
            self.running = True
            self.run_index = 1
            self.step_index = 0
            self.total_steps = len(self.steps)
            self._stop = False
            self._cancel = False
        self._changed()
        show = self.on_show
        if callable(show):
            try:
                show()
            except Exception:
                pass

    def aborted(self) -> bool:
        with self._lock:
            return self._cancel

    def stopping(self) -> bool:
        with self._lock:
            return self._stop or self._cancel

    def progress(self, run: int, step: int) -> None:
        with self._lock:
            self.run_index = run
            self.step_index = step
        self._changed()

    def value(self) -> float:
        with self._lock:
            return self.speed

    def repeat_count(self) -> int:
        with self._lock:
            return self.times

    def finish(self) -> None:
        with self._lock:
            self.running = False
            # A cancelled run did not reach the last step; saying it did is
            # misleading in the progress line.
            if not self._cancel:
                self.step_index = self.total_steps
        self._changed()

    def _changed(self) -> None:
        cb = self.on_update
        if callable(cb):
            try:
                cb()
            except Exception:
                pass
