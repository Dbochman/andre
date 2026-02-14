"""Tkinter search dialog for finding and adding songs to the queue."""

import json
import logging
import tkinter as tk
from tkinter import messagebox, ttk

import requests

log = logging.getLogger(__name__)


class SearchDialog:
    """Standalone search-and-add dialog.

    Can run in its own process (subprocess) or on a background thread.
    Creates its own Tk() instance and mainloop().
    """

    def __init__(self, server: str, token: str):
        self.server = server.rstrip("/")
        self.token = token
        self._results = []  # list of {uri, title, artist}

    def show(self):
        self.root = tk.Tk()
        self.root.title("EchoNest — Search & Add Song")
        self.root.geometry("500x400")
        self.root.minsize(400, 300)

        # Search bar
        search_frame = tk.Frame(self.root)
        search_frame.pack(fill=tk.X, padx=10, pady=(10, 5))

        self.search_var = tk.StringVar()
        entry = tk.Entry(search_frame, textvariable=self.search_var, font=("Helvetica", 14))
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        entry.bind("<Return>", lambda _: self._do_search())
        entry.focus_set()

        search_btn = tk.Button(search_frame, text="Search", command=self._do_search)
        search_btn.pack(side=tk.RIGHT, padx=(5, 0))

        # Results treeview
        tree_frame = tk.Frame(self.root)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.tree = ttk.Treeview(tree_frame, columns=("title", "artist"), show="headings",
                                  selectmode="browse")
        self.tree.heading("title", text="Title")
        self.tree.heading("artist", text="Artist")
        self.tree.column("title", width=250)
        self.tree.column("artist", width=200)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree.bind("<Double-1>", lambda _: self._add_selected())

        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Add button
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        self.status_label = tk.Label(btn_frame, text="", anchor=tk.W)
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        add_btn = tk.Button(btn_frame, text="Add to Queue", command=self._add_selected)
        add_btn.pack(side=tk.RIGHT)

        self.root.mainloop()

    def _do_search(self):
        query = self.search_var.get().strip()
        if not query:
            return

        self.status_label.config(text="Searching...")
        self.root.update_idletasks()

        try:
            resp = requests.get(
                f"{self.server}/search/v2",
                params={"q": query},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            self.status_label.config(text=f"Search failed: {e}")
            return

        # Clear previous results
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._results.clear()

        # /search/v2 returns a JSON array of {uri, track_name, artist, images}
        tracks = data if isinstance(data, list) else data.get("tracks", data)
        if isinstance(tracks, dict):
            tracks = tracks.get("items", [])

        for track in tracks:
            title = track.get("track_name") or track.get("title") or track.get("name", "")
            artist = track.get("artist", "")
            uri = track.get("uri") or track.get("trackid", "")
            if not uri:
                continue
            self._results.append({"uri": uri, "title": title, "artist": artist})
            self.tree.insert("", tk.END, values=(title, artist))

        count = len(self._results)
        self.status_label.config(text=f"{count} result{'s' if count != 1 else ''}")

    def _add_selected(self):
        selection = self.tree.selection()
        if not selection:
            self.status_label.config(text="Select a track first")
            return

        idx = self.tree.index(selection[0])
        track = self._results[idx]

        try:
            resp = requests.post(
                f"{self.server}/api/add_song",
                headers={"Authorization": f"Bearer {self.token}",
                         "Content-Type": "application/json"},
                json={"track_uri": track["uri"]},
                timeout=10,
            )
            resp.raise_for_status()
            self.status_label.config(text=f"Added: {track['title']}")
        except Exception as e:
            self.status_label.config(text=f"Failed to add: {e}")


def launch_search(server: str, token: str) -> None:
    """Launch the search dialog, handling frozen vs pip-installed detection."""
    import sys

    _is_frozen = getattr(sys, "frozen", False)

    if _is_frozen:
        # Frozen build: run inline on a background thread
        import threading
        threading.Thread(
            target=lambda: SearchDialog(server, token).show(),
            daemon=True,
        ).start()
    else:
        # Pip install: spawn as subprocess
        import subprocess
        subprocess.Popen(
            [sys.executable, "-m", "echonest_sync.search",
             "--server", server, "--token", token],
        )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="EchoNest Search & Add")
    parser.add_argument("--server", required=True)
    parser.add_argument("--token", required=True)
    args = parser.parse_args()

    SearchDialog(args.server, args.token).show()
