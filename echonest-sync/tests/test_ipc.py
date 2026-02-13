"""Tests for IPC channel (command/event queues)."""

import threading
import time

from echonest_sync.ipc import Command, Event, SyncChannel


class TestSyncChannel:
    def test_send_and_drain_commands(self):
        ch = SyncChannel()
        ch.send_command("pause")
        ch.send_command("resume")
        cmds = ch.get_commands()
        assert len(cmds) == 2
        assert cmds[0].type == "pause"
        assert cmds[1].type == "resume"

    def test_empty_drain_returns_empty(self):
        ch = SyncChannel()
        assert ch.get_commands() == []
        assert ch.get_events() == []

    def test_emit_and_drain_events(self):
        ch = SyncChannel()
        ch.emit("connected")
        ch.emit("track_changed", uri="spotify:track:abc")
        events = ch.get_events()
        assert len(events) == 2
        assert events[0].type == "connected"
        assert events[1].type == "track_changed"
        assert events[1].kwargs["uri"] == "spotify:track:abc"

    def test_event_has_timestamp(self):
        ch = SyncChannel()
        before = time.time()
        ch.emit("connected")
        after = time.time()
        events = ch.get_events()
        assert len(events) == 1
        assert before <= events[0].timestamp <= after

    def test_command_kwargs(self):
        ch = SyncChannel()
        ch.send_command("snooze", duration=900)
        cmds = ch.get_commands()
        assert cmds[0].kwargs == {"duration": 900}

    def test_drain_clears_queue(self):
        ch = SyncChannel()
        ch.send_command("pause")
        assert len(ch.get_commands()) == 1
        assert len(ch.get_commands()) == 0

    def test_thread_safety(self):
        """Multiple threads can send/receive without errors."""
        ch = SyncChannel()
        errors = []

        def producer():
            try:
                for i in range(100):
                    ch.send_command("test", index=i)
                    ch.emit("event", index=i)
            except Exception as e:
                errors.append(e)

        def consumer():
            try:
                collected_cmds = 0
                collected_events = 0
                deadline = time.time() + 5
                while time.time() < deadline and (collected_cmds < 200 or collected_events < 200):
                    collected_cmds += len(ch.get_commands())
                    collected_events += len(ch.get_events())
                    time.sleep(0.01)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=producer) for _ in range(2)]
        consumer_thread = threading.Thread(target=consumer)

        consumer_thread.start()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        consumer_thread.join(timeout=5)

        assert not errors
