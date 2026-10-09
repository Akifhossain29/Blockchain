"""
main.py
-------
Tkinter GUI for the UAP P2P Network assignment.

Run:
    python main.py
"""

import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

from p2p_node import P2PNode


class P2PApp:

    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("UAP P2P Network")
        root.geometry("880x640")
        root.minsize(780, 520)

        self.node = None                 # P2PNode instance (after Start)
        self.events = queue.Queue()      # network threads -> UI (thread-safe)
        self.peer_ids = []               # listbox index -> peer_id
        self.selected_peer_id = None

        self._build_widgets()
        self._poll_events()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # UI construction (Section 12: all 12 required elements)
    #
    # Tkinter pack order matters:
    #   * TOP widgets   -> packed first (default side="top")
    #   * BOTTOM widgets-> packed next with side="bottom":
    #       statusbar first (very bottom), then Send File, then Send Text
    #     -> result: Send Text above, Send File below, statusbar last,
    #        and they are ALWAYS visible (window never needs enlarging)
    #   * MIDDLE (peers + log) packed last with expand=True -> fills
    #     all remaining space and resizes with the window
    # ------------------------------------------------------------------
    def _build_widgets(self):
        pad = {"padx": 8, "pady": 4}

        # ================= TOP: My Peer =================
        my = tk.LabelFrame(self.root, text="My Peer")
        my.pack(fill="x", **pad)

        tk.Label(my, text="Name:").grid(row=0, column=0, padx=6, pady=6)
        self.name_entry = tk.Entry(my, width=16)
        self.name_entry.grid(row=0, column=1, padx=2)
        self.name_entry.insert(0, "Sam")

        tk.Label(my, text="Port:").grid(row=0, column=2, padx=6)
        self.port_entry = tk.Entry(my, width=8)
        self.port_entry.grid(row=0, column=3, padx=2)
        self.port_entry.insert(0, "5000")

        self.start_btn = tk.Button(my, text="Start Peer", width=11,
                                   command=self.on_start)
        self.start_btn.grid(row=0, column=4, padx=6)
        self.stop_btn = tk.Button(my, text="Stop", width=7,
                                  command=self.on_stop, state="disabled")
        self.stop_btn.grid(row=0, column=5, padx=6)

        self.info_label = tk.Label(my, text="Peer not started", fg="gray")
        self.info_label.grid(row=1, column=0, columnspan=6, sticky="w", padx=6)

        # ================= TOP: Connect to Another Peer =================
        con = tk.LabelFrame(self.root, text="Connect to Another Peer")
        con.pack(fill="x", **pad)

        tk.Label(con, text="IP:").grid(row=0, column=0, padx=6, pady=6)
        self.ip_entry = tk.Entry(con, width=16)
        self.ip_entry.grid(row=0, column=1, padx=2)
        self.ip_entry.insert(0, "127.0.0.1")

        tk.Label(con, text="Port:").grid(row=0, column=2, padx=6)
        self.remote_port_entry = tk.Entry(con, width=8)
        self.remote_port_entry.grid(row=0, column=3, padx=2)
        self.remote_port_entry.insert(0, "5001")

        self.connect_btn = tk.Button(con, text="Connect", width=11,
                                     command=self.on_connect, state="disabled")
        self.connect_btn.grid(row=0, column=4, padx=6)

        # ============ BOTTOM: packed FIRST so they are ALWAYS visible =====
        # visual order (top -> bottom): Send Text, Send File, statusbar
        # pack order  (bottom -> up)  : statusbar, Send File, Send Text

        # ----- status bar (very bottom, code ager motoi) -----
        self.statusbar = tk.Label(self.root, text="", anchor="w",
                                  bd=1, relief="sunken")
        self.statusbar.pack(fill="x", side="bottom")

        # ----- Send File (niche) -----
        filef = tk.LabelFrame(self.root, text="Send File")
        filef.pack(fill="x", side="bottom", **pad)

        tk.Label(filef, text="Text, image, audio, video, PDF, ZIP, etc.").pack(
            side="left", padx=6, pady=6)
        self.file_btn = tk.Button(filef, text="Choose File & Send", width=18,
                                  command=self.on_send_file, state="disabled")
        self.file_btn.pack(side="right", padx=6, pady=6)

        # ----- Send Text (Send File er upore) -----
        send = tk.LabelFrame(self.root, text="Send Text")
        send.pack(fill="x", side="bottom", **pad)

        self.text_entry = tk.Entry(send)
        self.text_entry.pack(side="left", fill="x", expand=True, padx=6, pady=6)
        self.text_entry.bind("<Return>", lambda _e: self.on_send_text())
        self.send_btn = tk.Button(send, text="Send", width=10,
                                  command=self.on_send_text, state="disabled")
        self.send_btn.pack(side="right", padx=6)

        # ============ MIDDLE: fills all remaining space ====================
        body = tk.Frame(self.root)
        body.pack(fill="both", expand=True, **pad)

        peers = tk.LabelFrame(body, text="Connected Peers")
        peers.pack(side="left", fill="y", padx=(0, 6))

        self.peer_list = tk.Listbox(peers, width=34, height=6,
                                    exportselection=False)
        self.peer_list.pack(fill="both", expand=True, padx=4, pady=4)
        self.peer_list.bind("<<ListboxSelect>>", self.on_peer_select)

        logf = tk.LabelFrame(body, text="Messages / Events")
        logf.pack(side="left", fill="both", expand=True)

        self.log = tk.Text(logf, state="disabled", wrap="word", height=6)
        self.log.pack(fill="both", expand=True, padx=4, pady=4)

    # ------------------------------------------------------------------
    # Event polling: network threads communicate with UI via queue only
    # ------------------------------------------------------------------
    def _poll_events(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "log":
                    self._log(data)
                elif kind == "peers":
                    self._refresh_peer_list()
                elif kind == "enable_connect":
                    if self.node is not None:
                        self.connect_btn.configure(state="normal")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def _log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------
    def on_start(self):
        name = self.name_entry.get().strip()
        if not name:
            messagebox.showwarning("Missing name", "Please enter a peer name.")
            return
        try:
            port = int(self.port_entry.get().strip())
            if not (1 <= port <= 65535):
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid port",
                                 "Port must be an integer between 1 and 65535.")
            return

        node = P2PNode(
            name, port,
            on_event=lambda t: self.events.put(("log", t)),
            on_change=lambda: self.events.put(("peers", None)),
        )
        try:
            node.start()
        except OSError:
            messagebox.showerror(
                "Cannot listen on port",
                f"Cannot listen on port {port}.\n"
                f"It may already be in use by another program.")
            return

        self.node = node
        self.info_label.configure(text=f"{name} [ID: {node.peer_id}] Port {port}",
                                  fg="black")
        self.statusbar.configure(
            text=f"Peer started: {name} [{node.peer_id}] on port {port}")

        self.start_btn.configure(state="disabled")
        self.name_entry.configure(state="disabled")
        self.port_entry.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.connect_btn.configure(state="normal")
        self.send_btn.configure(state="normal")
        self.file_btn.configure(state="normal")

    def on_stop(self):
        if self.node is not None:
            self.node.stop()
            self.node = None

        self.selected_peer_id = None
        self.peer_list.delete(0, "end")
        self.peer_ids = []
        self.info_label.configure(text="Peer not started", fg="gray")
        self.statusbar.configure(text="Peer stopped")

        self.start_btn.configure(state="normal")
        self.name_entry.configure(state="normal")
        self.port_entry.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.connect_btn.configure(state="disabled")
        self.send_btn.configure(state="disabled")
        self.file_btn.configure(state="disabled")

    def on_connect(self):
        if self.node is None:
            return

        host = self.ip_entry.get().strip()
        if not host:
            messagebox.showerror("Missing IP",
                                 "Please enter an IP address or host.")
            return

        try:
            port = int(self.remote_port_entry.get().strip())
            if not (1 <= port <= 65535):
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid port",
                                 "Port must be a number between 1 and 65535.")
            return

        self.connect_btn.configure(state="disabled")
        node = self.node

        def worker():
            try:
                node.connect(host, port)   # all errors are logged by the node
            finally:
                self.events.put(("enable_connect", None))

        threading.Thread(target=worker, daemon=True).start()

    def on_peer_select(self, _event=None):
        selection = self.peer_list.curselection()
        if selection and 0 <= selection[0] < len(self.peer_ids):
            self.selected_peer_id = self.peer_ids[selection[0]]
        else:
            self.selected_peer_id = None

    def on_send_text(self):
        if self.node is None:
            return
        text = self.text_entry.get().strip()
        if not text:
            return
        if self.selected_peer_id is None:
            self._log("[ERROR] Select a connected peer first")
            messagebox.showwarning("No peer selected",
                                   "Select a connected peer from the list first.")
            return
        if self.node.send_text(self.selected_peer_id, text):
            self.text_entry.delete(0, "end")

    def on_send_file(self):
        if self.node is None:
            return
        if self.selected_peer_id is None:
            self._log("[ERROR] Select a connected peer first")
            messagebox.showwarning("No peer selected",
                                   "Select a connected peer from the list first.")
            return
        filepath = filedialog.askopenfilename(title="Choose a file to send")
        if not filepath:
            return
        threading.Thread(target=self.node.send_file,
                         args=(self.selected_peer_id, filepath),
                         daemon=True).start()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _refresh_peer_list(self):
        summaries = self.node.peer_summaries() if self.node else []
        self.peer_list.delete(0, "end")
        self.peer_ids = [pid for pid, _text in summaries]
        for _pid, text in summaries:
            self.peer_list.insert("end", text)

        if self.selected_peer_id in self.peer_ids:
            idx = self.peer_ids.index(self.selected_peer_id)
            self.peer_list.selection_clear(0, "end")
            self.peer_list.selection_set(idx)
        else:
            self.selected_peer_id = None

    def _on_close(self):
        if self.node is not None:
            self.node.stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    P2PApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()