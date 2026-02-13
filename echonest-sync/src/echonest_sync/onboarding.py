"""Tkinter onboarding dialog for echonest-sync desktop app.

Runs as a **separate subprocess** to avoid event loop conflicts with
rumps/pystray. Invoke via: ``python -m echonest_sync.onboarding``
"""

import argparse
import logging
import sys
import tkinter as tk
from tkinter import font as tkfont

import requests

from .config import save_config, set_token

log = logging.getLogger(__name__)

DEFAULT_SERVER = "https://echone.st"
DEFAULT_CODE = "futureofmusic"


class OnboardingDialog:
    def __init__(self, server: str = DEFAULT_SERVER):
        self.server = server.rstrip("/")
        self.success = False

        self.root = tk.Tk()
        self.root.title("EchoNest Sync Setup")
        self.root.resizable(False, False)
        self.root.geometry("320x220")

        # Center on screen
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (w // 2)
        y = (self.root.winfo_screenheight() // 2) - (h // 2)
        self.root.geometry(f"+{x}+{y}")

        self._build_ui()

    def _build_ui(self):
        frame = tk.Frame(self.root, padx=20, pady=15)
        frame.pack(fill=tk.BOTH, expand=True)

        # Title
        title_font = tkfont.Font(family="Helvetica", size=14, weight="bold")
        tk.Label(frame, text="EchoNest Sync Setup", font=title_font).pack(pady=(0, 12))

        # Invite code
        tk.Label(frame, text="Invite code:").pack(anchor=tk.W)
        self.code_var = tk.StringVar(value=DEFAULT_CODE)
        self.code_entry = tk.Entry(frame, textvariable=self.code_var, width=30)
        self.code_entry.pack(fill=tk.X, pady=(2, 10))
        self.code_entry.bind("<Return>", lambda e: self._on_connect())

        # Connect button
        self.connect_btn = tk.Button(frame, text="Connect", command=self._on_connect)
        self.connect_btn.pack(pady=(0, 8))

        # Status label
        self.status_var = tk.StringVar(value="Ready")
        self.status_label = tk.Label(frame, textvariable=self.status_var)
        self.status_label.pack()

        # Spotify warning (secondary label, hidden by default)
        self.spotify_var = tk.StringVar()
        self.spotify_label = tk.Label(frame, textvariable=self.spotify_var, fg="orange")
        self.spotify_label.pack()

        self._check_spotify()

    def _check_spotify(self):
        """Show non-blocking warning if Spotify isn't running."""
        try:
            from .player import create_player
            player = create_player()
            if not player.is_running():
                self.spotify_var.set("Start Spotify for audio sync")
        except Exception:
            pass

    def _set_status(self, text: str, color: str = "black"):
        self.status_var.set(text)
        self.status_label.config(fg=color)
        self.root.update_idletasks()

    def _on_connect(self):
        code = self.code_var.get().strip()
        if not code:
            self._set_status("Enter an invite code", "red")
            return

        self.connect_btn.config(state=tk.DISABLED)
        self._set_status("Connecting...")

        # Run request in main thread (dialog is single-purpose, brief block is fine)
        try:
            resp = requests.post(
                f"{self.server}/api/sync-token",
                json={"invite_code": code},
                timeout=10,
            )
        except requests.exceptions.ConnectionError:
            self._set_status("Could not reach server", "red")
            self.connect_btn.config(state=tk.NORMAL)
            return
        except Exception as e:
            self._set_status(f"Connection error: {e}", "red")
            self.connect_btn.config(state=tk.NORMAL)
            return

        if resp.status_code == 200:
            data = resp.json()
            token = data.get("token", "")
            server_url = data.get("server", self.server)

            # Store token in keyring
            set_token(token)

            # Persist server URL to config
            save_config({"server": server_url})

            self._set_status("Connected!", "green")
            self.root.after(2000, self.root.destroy)
            self.success = True
        elif resp.status_code == 401:
            self._set_status("Invalid invite code", "red")
            self.connect_btn.config(state=tk.NORMAL)
        elif resp.status_code == 429:
            self._set_status("Too many attempts. Try again later.", "red")
            self.connect_btn.config(state=tk.NORMAL)
        else:
            self._set_status(f"Server error ({resp.status_code})", "red")
            self.connect_btn.config(state=tk.NORMAL)

    def run(self) -> bool:
        self.root.mainloop()
        return self.success


def main():
    parser = argparse.ArgumentParser(description="EchoNest Sync onboarding")
    parser.add_argument("--server", default=DEFAULT_SERVER, help="Server URL")
    args = parser.parse_args()

    dialog = OnboardingDialog(server=args.server)
    if dialog.run():
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
