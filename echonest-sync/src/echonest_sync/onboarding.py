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
        self.root.geometry("280x200")

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

        # Big nest emoji
        emoji_font = tkfont.Font(size=64)
        self.emoji_var = tk.StringVar(value="\U0001FAB9")  # empty nest
        self.emoji_label = tk.Label(frame, textvariable=self.emoji_var, font=emoji_font)
        self.emoji_label.pack(pady=(10, 5))

        # Status label
        status_font = tkfont.Font(family="Helvetica", size=14)
        self.status_var = tk.StringVar(value="Connecting...")
        self.status_label = tk.Label(frame, textvariable=self.status_var, font=status_font)
        self.status_label.pack(pady=(0, 0))

        # Auto-connect after UI renders
        self.root.after(100, self._auto_connect)

    def _set_status(self, text: str, color: str = "black"):
        self.status_var.set(text)
        self.status_label.config(fg=color)
        self.root.update_idletasks()

    def _auto_connect(self):
        """Auto-connect with the default invite code."""
        try:
            resp = requests.post(
                f"{self.server}/api/sync-token",
                json={"invite_code": DEFAULT_CODE},
                timeout=10,
            )
        except requests.exceptions.ConnectionError:
            self._set_status("Could not reach server", "red")
            self.root.after(3000, self.root.destroy)
            return
        except Exception as e:
            self._set_status(f"Connection error: {e}", "red")
            self.root.after(3000, self.root.destroy)
            return

        if resp.status_code == 200:
            data = resp.json()
            token = data.get("token", "")
            server_url = data.get("server", self.server)
            set_token(token)
            save_config({"server": server_url})
            self.emoji_var.set("\U0001FABA")  # nest with eggs
            self._set_status("Connected!", "green")
            self.root.after(1500, self.root.destroy)
            self.success = True
        else:
            self._set_status("Setup failed — contact support", "red")
            self.root.after(3000, self.root.destroy)

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
