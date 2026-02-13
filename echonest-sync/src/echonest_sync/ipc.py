"""Thread-safe IPC channel between tray GUI (main thread) and sync engine (background thread)."""

import queue
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Command:
    """GUI → Engine command."""
    type: str
    kwargs: dict = field(default_factory=dict)


@dataclass
class Event:
    """Engine → GUI event."""
    type: str
    timestamp: float = field(default_factory=time.time)
    kwargs: dict = field(default_factory=dict)


class SyncChannel:
    """Bidirectional channel between GUI and engine.

    Two queue.Queue instances — no sockets, no pipes. Works because
    the engine runs as a thread in the same process.
    """

    def __init__(self):
        self._commands: queue.Queue[Command] = queue.Queue()
        self._events: queue.Queue[Event] = queue.Queue()

    # --- GUI → Engine ---

    def send_command(self, cmd: str, **kwargs: Any) -> None:
        """Send a command from GUI to engine.

        Commands: 'pause', 'resume', 'snooze', 'quit'
        """
        self._commands.put(Command(type=cmd, kwargs=kwargs))

    def get_commands(self) -> list[Command]:
        """Non-blocking drain of all pending commands."""
        cmds = []
        while True:
            try:
                cmds.append(self._commands.get_nowait())
            except queue.Empty:
                break
        return cmds

    # --- Engine → GUI ---

    def emit(self, event_type: str, **kwargs: Any) -> None:
        """Emit an event from engine to GUI.

        Events: 'connected', 'disconnected', 'track_changed',
                'status_changed', 'user_override'
        """
        self._events.put(Event(type=event_type, kwargs=kwargs))

    def get_events(self) -> list[Event]:
        """Non-blocking drain of all pending events."""
        events = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                break
        return events
