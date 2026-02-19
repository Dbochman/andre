"""Winamp-inspired mini player window using tkinter."""

from __future__ import annotations

import hashlib
import json
import logging
import sys
import threading
import time
import tkinter as tk

from .config import get_config_dir, load_config, save_config

log = logging.getLogger(__name__)

# Layout constants
WIN_W, WIN_H = 420, 116
ART_SIZE = 80
ART_PAD = 10
BAR_H = 6

# Colors
BG = "#1a1a1a"
FG = "#ffffff"
FG_DIM = "#999999"
FG_DARK = "#666666"
BAR_BG = "#333333"
BAR_FG = "#28d7fe"
ART_PLACEHOLDER = "#333333"
AIRHORN_ON = "#ff9800"
AIRHORN_OFF = "#555555"

# Status indicator colors
STATUS_GREEN = "#4caf50"
STATUS_YELLOW = "#ffc107"
STATUS_GREY = "#9e9e9e"
STATUS_SIZE = 8


def _fmt_time(seconds):
    """Format seconds as M:SS."""
    s = max(0, int(seconds))
    return f"{s // 60}:{s % 60:02d}"


class MiniPlayerWindow:
    """Borderless always-on-top mini player (display only).

    Reads JSON lines from stdin (track info, position, paused/status/queue/airhorn state).
    Writes JSON lines to stdout (commands, close notification).
    Reflects server playback state with airhorn toggle and up-next display.
    """

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("EchoNest Mini Player")
        self.root.overrideredirect(True)
        self.root.wm_attributes("-topmost", True)
        self.root.configure(bg=BG)
        self.root.geometry(f"{WIN_W}x{WIN_H}")
        self.root.resizable(False, False)

        # State
        self._title = "No track playing"
        self._artist = ""
        self._duration = 0.0
        self._position = 0.0
        self._paused = False
        self._last_pos_time = time.time()
        self._blink_counter = 0
        self._art_photo = None  # prevent GC
        self._art_cache_dir = get_config_dir() / "art_cache"
        self._art_cache_dir.mkdir(parents=True, exist_ok=True)
        self._closing = False
        self._status = "disconnected"
        self._sync_paused = False
        self._airhorn_enabled = True
        self._up_next = ""

        # Drag state
        self._drag_x = 0
        self._drag_y = 0

        # Restore saved position
        cfg = load_config()
        sx = cfg.get("miniplayer_x")
        sy = cfg.get("miniplayer_y")
        if sx is not None and sy is not None:
            try:
                x, y = int(sx), int(sy)
                sw = self.root.winfo_screenwidth()
                sh = self.root.winfo_screenheight()
                x = max(0, min(x, sw - WIN_W))
                y = max(0, min(y, sh - WIN_H))
                self.root.geometry(f"+{x}+{y}")
            except (ValueError, TypeError):
                pass

        self._build_ui()
        self._bind_drag()

        # Start stdin reader thread
        self._stdin_thread = threading.Thread(target=self._read_stdin, daemon=True)
        self._stdin_thread.start()

        # Start 250ms interpolation timer
        self._tick()

    def _build_ui(self):
        # Album art placeholder
        self._art_canvas = tk.Canvas(
            self.root, width=ART_SIZE, height=ART_SIZE,
            bg=ART_PLACEHOLDER, highlightthickness=0,
        )
        self._art_canvas.place(x=ART_PAD, y=10)

        # Right side: text + progress
        text_x = ART_PAD + ART_SIZE + 12
        text_w = WIN_W - text_x - ART_PAD

        # Status dot + title row
        self._status_canvas = tk.Canvas(
            self.root, width=STATUS_SIZE, height=STATUS_SIZE,
            bg=BG, highlightthickness=0,
        )
        self._status_canvas.place(x=text_x, y=16)
        self._status_dot = self._status_canvas.create_oval(
            0, 0, STATUS_SIZE, STATUS_SIZE, fill=STATUS_GREY, width=0,
        )

        title_x = text_x + STATUS_SIZE + 6
        title_w = text_w - STATUS_SIZE - 6 - 20

        self._title_label = tk.Label(
            self.root, text=self._title, font=("Helvetica", 12, "bold"),
            fg=FG, bg=BG, anchor="w", width=0,
        )
        self._title_label.place(x=title_x, y=10, width=title_w)

        self._artist_label = tk.Label(
            self.root, text=self._artist, font=("Helvetica", 10),
            fg=FG_DIM, bg=BG, anchor="w", width=0,
        )
        self._artist_label.place(x=title_x, y=32, width=title_w)

        # Play/pause toggle + progress bar + time
        ctrl_y = 58
        self._state_label = tk.Label(
            self.root, text="\u23f8", font=("Helvetica", 12),
            fg=FG_DIM, bg=BG, cursor="hand2",
        )
        self._state_label.place(x=text_x, y=ctrl_y - 4)
        self._state_label.bind("<Button-1>", self._on_play_pause)

        bar_x = text_x + 24
        bar_w = text_w - 24 - 62

        self._bar_canvas = tk.Canvas(
            self.root, width=bar_w, height=BAR_H,
            bg=BAR_BG, highlightthickness=0,
        )
        self._bar_canvas.place(x=bar_x, y=ctrl_y + 4)
        self._bar_w = bar_w
        self._bar_fill = self._bar_canvas.create_rectangle(
            0, 0, 0, BAR_H, fill=BAR_FG, width=0,
        )

        self._time_label = tk.Label(
            self.root, text="0:00/0:00", font=("Helvetica", 9),
            fg=FG_DIM, bg=BG, anchor="e",
        )
        self._time_label.place(x=bar_x + bar_w + 4, y=ctrl_y - 1, width=58)

        # Bottom row: status text | airhorn | up next
        bottom_y = ctrl_y + 18
        self._status_label = tk.Label(
            self.root, text="Disconnected", font=("Helvetica", 8),
            fg=FG_DIM, bg=BG, anchor="w",
        )
        self._status_label.place(x=bar_x, y=bottom_y, width=120)

        # Airhorn toggle — canvas dot + text (emoji fg color doesn't work on macOS)
        airhorn_w = 70
        self._airhorn_frame = tk.Frame(self.root, bg=BG, cursor="hand2")
        self._airhorn_frame.place(x=bar_x + 120, y=bottom_y - 1)
        self._airhorn_dot = tk.Canvas(
            self._airhorn_frame, width=8, height=8,
            bg=BG, highlightthickness=0,
        )
        self._airhorn_dot.pack(side="left", padx=(0, 3), pady=4)
        self._airhorn_dot_id = self._airhorn_dot.create_oval(
            0, 0, 8, 8, fill=AIRHORN_ON, width=0,
        )
        self._airhorn_text = tk.Label(
            self._airhorn_frame, text="Airhorns", font=("Helvetica", 8),
            fg=FG_DIM, bg=BG,
        )
        self._airhorn_text.pack(side="left")
        for w in (self._airhorn_frame, self._airhorn_dot, self._airhorn_text):
            w.bind("<Button-1>", self._on_airhorn_toggle)

        # Up next label — full width below album art
        next_y = 10 + ART_SIZE + 6  # below album art
        self._next_label = tk.Label(
            self.root, text="", font=("Helvetica", 8),
            fg=FG_DARK, bg=BG, anchor="w",
        )
        self._next_label.place(x=ART_PAD, y=next_y, width=WIN_W - 2 * ART_PAD)

        # Close button (top-right corner)
        close_btn = tk.Label(
            self.root, text="\u2715", font=("Helvetica", 10),
            fg=FG_DIM, bg=BG, cursor="hand2",
        )
        close_btn.place(x=WIN_W - 20, y=4)
        close_btn.bind("<Button-1>", lambda e: self._close())

    def _bind_drag(self):
        self.root.bind("<Button-1>", self._on_drag_start)
        self.root.bind("<B1-Motion>", self._on_drag_motion)

    def _on_drag_start(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def _on_drag_motion(self, event):
        x = self.root.winfo_x() + event.x - self._drag_x
        y = self.root.winfo_y() + event.y - self._drag_y
        self.root.geometry(f"+{x}+{y}")

    # ------------------------------------------------------------------
    # Status indicator
    # ------------------------------------------------------------------

    def _update_status_ui(self):
        """Update the status dot color and status text."""
        s = self._status
        if s in ("syncing", "connected"):
            color = STATUS_GREEN
            if self._paused:
                text = "Paused"
            elif self._title and self._title != "No track playing":
                text = "Now Playing"
            else:
                text = "Connected"
        elif s in ("paused", "override"):
            color = STATUS_YELLOW
            text = "Sync Paused" if s == "paused" else "Override"
        elif s == "waiting":
            color = STATUS_GREY
            text = "Waiting"
        else:
            color = STATUS_GREY
            text = "Disconnected"

        self._status_canvas.itemconfig(self._status_dot, fill=color)
        self._status_label.config(text=text)
        # Update play/pause icon: ⏸ = playing (click to pause), ▶ = paused (click to resume)
        if self._sync_paused or self._paused:
            self._state_label.config(text="\u25b6")
        else:
            self._state_label.config(text="\u23f8")

    # ------------------------------------------------------------------
    # Play/Pause toggle
    # ------------------------------------------------------------------

    def _on_play_pause(self, event):
        """Toggle sync pause/resume."""
        if self._sync_paused:
            self._send({"type": "command", "cmd": "resume"})
        else:
            self._send({"type": "command", "cmd": "pause"})
        return "break"  # prevent drag

    # ------------------------------------------------------------------
    # IPC: stdin reader
    # ------------------------------------------------------------------

    def _read_stdin(self):
        """Read JSON lines from stdin in a background thread."""
        try:
            if sys.stdin is None:
                log.warning("stdin is None (windowed mode) — miniplayer IPC disabled")
                return
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if self._closing:
                    return
                self.root.after(0, self._handle_message, msg)
        except (EOFError, OSError):
            pass
        finally:
            if not self._closing:
                self.root.after(0, self._close)

    def _handle_message(self, msg):
        msg_type = msg.get("type", "")

        if msg_type == "track":
            self._title = msg.get("title", "")
            self._artist = msg.get("artist", "")
            self._duration = float(msg.get("duration", 0))
            self._paused = bool(msg.get("paused", False))
            self._position = 0.0
            self._last_pos_time = time.time()

            self._title_label.config(text=self._title)
            self._artist_label.config(text=self._artist)
            self._state_label.config(text="\u23f8" if not self._paused else "\u25b6")
            self._update_progress()
            self._update_status_ui()

            # Fetch album art in background
            big_img = msg.get("big_img", "")
            if big_img:
                threading.Thread(
                    target=self._fetch_art, args=(big_img,), daemon=True
                ).start()
            else:
                self._show_placeholder()

        elif msg_type == "position":
            self._position = float(msg.get("pos", 0))
            self._last_pos_time = time.time()
            self._update_progress()

        elif msg_type == "paused":
            self._paused = bool(msg.get("paused", False))
            self._state_label.config(text="\u23f8" if not self._paused else "\u25b6")
            if not self._paused:
                self._last_pos_time = time.time()
                self._time_label.config(fg=FG_DIM)
            self._update_status_ui()

        elif msg_type == "status":
            self._status = msg.get("status", "disconnected")
            self._sync_paused = self._status in ("paused", "override")
            self._update_status_ui()

        elif msg_type == "airhorn":
            self._airhorn_enabled = bool(msg.get("enabled", True))
            self._update_airhorn_ui()

        elif msg_type == "queue":
            tracks = msg.get("tracks", [])
            if tracks:
                self._up_next = f"Up next: {tracks[0]}"
            else:
                self._up_next = ""
            self._next_label.config(text=self._up_next)

        elif msg_type == "quit":
            self._close()

    # ------------------------------------------------------------------
    # Airhorn toggle
    # ------------------------------------------------------------------

    def _on_airhorn_toggle(self, event):
        self._airhorn_enabled = not self._airhorn_enabled
        self._update_airhorn_ui()
        self._send({"type": "command", "cmd": "toggle_airhorn"})
        return "break"  # prevent drag

    def _update_airhorn_ui(self):
        color = AIRHORN_ON if self._airhorn_enabled else AIRHORN_OFF
        self._airhorn_dot.itemconfig(self._airhorn_dot_id, fill=color)
        self._airhorn_text.config(fg=color)

    # ------------------------------------------------------------------
    # Album art
    # ------------------------------------------------------------------

    def _fetch_art(self, url):
        """Download album art, cache to disk, display."""
        try:
            import requests
            from PIL import Image

            url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
            cache_path = self._art_cache_dir / f"{url_hash}.jpg"

            if not cache_path.exists():
                resp = requests.get(url, timeout=10)
                resp.raise_for_status()
                cache_path.write_bytes(resp.content)

            img = Image.open(cache_path)
            img = img.resize((ART_SIZE, ART_SIZE), Image.LANCZOS)

            self.root.after(0, self._set_art, img)
        except Exception as e:
            log.debug("Art fetch failed: %s", e)
            self.root.after(0, self._show_placeholder)

    def _set_art(self, pil_img):
        from PIL import ImageTk
        self._art_photo = ImageTk.PhotoImage(pil_img)
        self._art_canvas.delete("all")
        self._art_canvas.create_image(0, 0, anchor="nw", image=self._art_photo)

    def _show_placeholder(self):
        self._art_canvas.delete("all")
        self._art_canvas.configure(bg=ART_PLACEHOLDER)
        self._art_photo = None

    # ------------------------------------------------------------------
    # Progress / timer
    # ------------------------------------------------------------------

    def _tick(self):
        """250ms interpolation timer."""
        if self._closing:
            return
        self._blink_counter += 1
        self._update_progress()

        # Paused time blink: toggle every 4 ticks (~1s)
        if self._paused and self._blink_counter % 4 == 0:
            current_fg = self._time_label.cget("fg")
            self._time_label.config(fg=BG if current_fg != BG else FG_DIM)

        self.root.after(250, self._tick)

    def _update_progress(self):
        if self._duration <= 0:
            self._bar_canvas.coords(self._bar_fill, 0, 0, 0, BAR_H)
            self._time_label.config(text="0:00/0:00")
            return

        if self._paused:
            pos = self._position
        else:
            elapsed_since = time.time() - self._last_pos_time
            pos = min(self._position + elapsed_since, self._duration)

        frac = min(pos / self._duration, 1.0)
        fill_w = int(frac * self._bar_w)
        self._bar_canvas.coords(self._bar_fill, 0, 0, fill_w, BAR_H)
        self._time_label.config(text=f"{_fmt_time(pos)}/{_fmt_time(self._duration)}")

    # ------------------------------------------------------------------
    # IPC: stdout writer
    # ------------------------------------------------------------------

    def _send(self, msg):
        try:
            if sys.stdout is None:
                return
            sys.stdout.write(json.dumps(msg) + "\n")
            sys.stdout.flush()
        except (BrokenPipeError, OSError):
            pass

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------

    def _close(self):
        if self._closing:
            return
        self._closing = True

        try:
            x = self.root.winfo_x()
            y = self.root.winfo_y()
            save_config({"miniplayer_x": x, "miniplayer_y": y})
        except Exception:
            pass

        self._send({"type": "closed"})

        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.mainloop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    MiniPlayerWindow().run()
