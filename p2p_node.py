"""
p2p_node.py
-----------
P2P networking layer.

Every peer is BOTH (Section 8):
  * a TCP server  -> accepts incoming connections from other peers
  * a TCP client  -> initiates connections to other peers

No central server is used anywhere.
"""

import os
import socket
import sys
import threading
import uuid

import protocol


def make_peer_id() -> str:
    """Short unique id like 'a83f21c4' (as shown in assignment 7.3)."""
    return uuid.uuid4().hex[:8]


def enable_keepalive(sock):
    """Enable TCP keepalive so a SILENT loss (Wi-Fi off, cable pulled)
    is detected in roughly 20-40 seconds instead of hanging forever."""
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        if sys.platform == "win32":
            # (enabled, first probe after 10 s, re-probe every 3 s)
            sock.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 10000, 3000))
        else:
            if hasattr(socket, "TCP_KEEPIDLE"):        # Linux
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 10)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 5)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
            elif hasattr(socket, "TCP_KEEPALIVE"):     # macOS
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPALIVE, 10)
    except OSError:
        pass   # best-effort; OS defaults still apply


class PeerConnection:
    """Represents ONE connection between this peer and one remote peer."""

    def __init__(self, sock: socket.socket, address, node: "P2PNode"):
        self.sock = sock
        self.address = address            # (ip, port) of the remote socket
        self.node = node
        self.peer_id = None               # filled after HELLO / HELLO_ACK
        self.peer_name = None
        self.peer_port = None             # remote peer's LISTENING port
        self.alive = True
        self.send_lock = threading.Lock() # avoid interleaved writes

    # ---------- sending ----------
    def send_json(self, message: dict):
        with self.send_lock:
            protocol.send_message(self.sock, message)

    def send_file_bytes(self, filepath: str):
        """Send raw file bytes in chunks (Step 9). Metadata goes first."""
        with self.send_lock:
            with open(filepath, "rb") as f:
                while True:
                    chunk = f.read(protocol.CHUNK_SIZE)
                    if not chunk:
                        break
                    self.sock.sendall(chunk)

    # ---------- receiving ----------
    def listen(self):
        """Receive loop for this connection (own thread — Step 4)."""
        try:
            while self.alive:
                message = protocol.recv_message(self.sock)
                self.node.handle_message(self, message)
        except Exception:
            pass                          # peer disconnected / bad data
        finally:
            self.close()

    def close(self):
        if not self.alive:
            return
        self.alive = False
        try:
            self.sock.close()
        except OSError:
            pass
        self.node.remove_connection(self)


class P2PNode:
    """One running peer = TCP server + TCP client + connection table."""

    def __init__(self, name: str, port: int, on_event=None, on_change=None):
        self.peer_id = make_peer_id()
        self.peer_name = name
        self.port = port

        self.on_event = on_event          # callback(str) -> UI log
        self.on_change = on_change        # callback()    -> peer list changed

        self.connections = []             # all live PeerConnection objects
        self.table_lock = threading.Lock()

        self.server_socket = None
        self.running = False

    # ================= events =================
    def emit(self, text: str):
        if self.on_event:
            self.on_event(text)

    def changed(self):
        if self.on_change:
            self.on_change()

    # ================= address helpers =================
    def _resolve_host(self, host: str):
        """Accept an IP address OR a hostname (e.g. 'localhost').
        Returns an IPv4 string, or None if it cannot be resolved."""
        try:
            infos = socket.getaddrinfo(host, None, socket.AF_INET,
                                       socket.SOCK_STREAM)
            return infos[0][4][0]
        except OSError:
            return None

    def _is_self_address(self, host: str, port: int) -> bool:
        """True if host:port points at THIS peer (blocks self-connection)."""
        if port != self.port:
            return False
        candidates = set()
        try:
            for info in socket.getaddrinfo(host, port, socket.AF_INET):
                candidates.add(info[4][0])
        except OSError:
            pass
        local = {"127.0.0.1"}
        try:
            local.update(socket.gethostbyname_ex(socket.gethostname())[2])
        except OSError:
            pass
        return bool(candidates & local)

    # ============== SERVER role (Step 1) ==============
    def start(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(("0.0.0.0", self.port))
        self.server_socket.listen()
        self.running = True
        threading.Thread(target=self._accept_loop, daemon=True).start()
        self.emit(f"[SYSTEM] Peer started: {self.peer_name} "
                  f"[{self.peer_id}] on port {self.port}")

    def _accept_loop(self):
        while self.running:
            try:
                sock, addr = self.server_socket.accept()
            except OSError:
                break                     # server socket closed
            enable_keepalive(sock)
            conn = PeerConnection(sock, addr, self)
            self.add_connection(conn)
            threading.Thread(target=conn.listen, daemon=True).start()

    # ============== CLIENT role (Step 2 + handshake Step 3) ==============
    def connect(self, host: str, port: int) -> bool:
        """Connect to another peer and perform the HELLO handshake.
        Every failure is logged gracefully — the app never crashes."""

        # ---- Invalid IP / host ----
        ip = self._resolve_host(host)
        if ip is None:
            self.emit("[ERROR] Connection failed: Invalid IP address or host")
            return False

        # ---- Connecting to yourself ----
        if self._is_self_address(host, port):
            self.emit("[ERROR] You cannot connect to yourself")
            return False

        # ---- Already connected to that peer? ----
        with self.table_lock:
            for conn in self.connections:
                same_outgoing = conn.address == (ip, port)
                same_peer = (conn.address[0] == ip
                             and conn.peer_port == port)
                if same_outgoing or same_peer:
                    name = conn.peer_name or f"{ip}:{port}"
                    self.emit(f"[ERROR] Already connected to {name}")
                    return False

        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            enable_keepalive(sock)
            sock.settimeout(5.0)          # No answer -> timeout after 5 s
            sock.connect((ip, port))
        except socket.timeout:
            self.emit(f"[ERROR] Connection failed: No answer from "
                      f"{host}:{port} (timed out after 5 s)")
            self._safe_close(sock)
            return False
        except ConnectionRefusedError:
            self.emit("[ERROR] Connection failed: Connection refused "
                      "(is the peer running?)")
            self._safe_close(sock)
            return False
        except OSError as e:
            self.emit(f"[ERROR] Connection failed: {e}")
            self._safe_close(sock)
            return False

        # ---- HELLO handshake ----
        try:
            protocol.send_message(
                sock, protocol.build_hello(self.peer_id, self.peer_name,
                                           self.port))
            sock.settimeout(5.0)
            reply = protocol.recv_message(sock)
            sock.settimeout(None)
        except socket.timeout:
            self.emit("[ERROR] Connection failed: No answer "
                      "(handshake timed out after 5 s)")
            self._safe_close(sock)
            return False
        except OSError as e:
            self.emit(f"[ERROR] Handshake failed: {e}")
            self._safe_close(sock)
            return False

        if not isinstance(reply, dict) or reply.get("type") != protocol.HELLO_ACK:
            self.emit("[ERROR] Unexpected reply (expected hello_ack)")
            self._safe_close(sock)
            return False

        # ---- safety: somehow talked to ourselves ----
        if reply.get("peer_id") == self.peer_id:
            self.emit("[ERROR] You cannot connect to yourself")
            self._safe_close(sock)
            return False

        # ---- already connected to this peer_id? ----
        with self.table_lock:
            dup = next((c for c in self.connections
                        if c.peer_id == reply.get("peer_id")), None)
        if dup is not None:
            name = dup.peer_name or f"{ip}:{port}"
            self.emit(f"[ERROR] Already connected to {name}")
            self._safe_close(sock)
            return False

        conn = PeerConnection(sock, (ip, port), self)
        conn.peer_id = reply.get("peer_id")
        conn.peer_name = reply.get("peer_name")
        conn.peer_port = reply.get("port")

        self.add_connection(conn)
        threading.Thread(target=conn.listen, daemon=True).start()
        self.emit(f"[SYSTEM] Connected to {conn.peer_name} "
                  f"({conn.peer_id}) at {ip}:{port}")
        return True

    @staticmethod
    def _safe_close(sock):
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    # ============== protocol handling (Steps 3, 5, 7, 8) ==============
    def handle_message(self, conn: PeerConnection, message: dict):
        mtype = message.get("type")

        if mtype == protocol.HELLO:
            conn.peer_id = message.get("peer_id")
            conn.peer_name = message.get("peer_name")
            conn.peer_port = message.get("port")
            try:
                protocol.send_message(
                    conn.sock,
                    protocol.build_hello_ack(self.peer_id, self.peer_name,
                                             self.port))
            except OSError:
                conn.close()
                return
            self.emit(f"[SYSTEM] {conn.peer_name} ({conn.peer_id}) "
                      f"connected from {conn.address[0]}")
            self.changed()

        elif mtype == protocol.TEXT:
            self.emit(f"{message.get('sender_name')} -> You: "
                      f"{message.get('message')}")

        elif mtype == protocol.FILE:
            self._receive_file(conn, message)

        else:
            self.emit(f"[SYSTEM] Unknown message type: {mtype}")

    # ============== file receiving (Steps 8 + 9) ==============
    def _receive_file(self, conn: PeerConnection, meta: dict):
        filename = protocol.sanitize_filename(meta.get("filename",
                                                       "unnamed_file"))
        try:
            filesize = int(meta.get("filesize", -1))
        except (TypeError, ValueError):
            filesize = -1

        # ---- Invalid filesize: the stream can no longer be trusted ----
        if filesize < 0 or filesize > protocol.MAX_FILE_SIZE:
            self.emit(f"[ERROR] Invalid file metadata (filesize={filesize}); "
                      f"disconnecting sender")
            conn.close()
            return

        os.makedirs(protocol.DOWNLOAD_DIR, exist_ok=True)
        path = os.path.join(protocol.DOWNLOAD_DIR, filename)

        try:
            f = open(path, "wb")
        except OSError as e:
            self.emit(f"[ERROR] Cannot save file: {e}")
            self._drain(conn.sock, filesize)   # discard to stay in sync
            return

        received = 0
        write_failed = False
        try:
            with f:
                while received < filesize:
                    remaining = filesize - received
                    chunk = conn.sock.recv(min(protocol.CHUNK_SIZE, remaining))
                    if not chunk:
                        raise ConnectionError("peer disconnected mid-transfer")
                    received += len(chunk)
                    if not write_failed:
                        try:
                            f.write(chunk)
                        except OSError:
                            # e.g. DISK FULL: discard the rest so the
                            # connection stays usable, error is logged
                            write_failed = True
                            self.emit("[ERROR] Cannot write file "
                                      "(disk full?) — transfer aborted")
        except (ConnectionError, OSError) as e:
            self.emit(f"[ERROR] File transfer failed: {e}")

        # ---- incomplete / unwritten file: delete partial data ----
        if write_failed or received < filesize:
            try:
                os.remove(path)
            except OSError:
                pass
            return

        sender = conn.peer_name or "Unknown"
        self.emit(f"[SYSTEM] File received: {filename} "
                  f"({received} bytes) from {sender}")

    @staticmethod
    def _drain(sock, num_bytes: int):
        """Read and discard num_bytes so the TCP stream stays in sync."""
        remaining = num_bytes
        try:
            while remaining > 0:
                chunk = sock.recv(min(protocol.CHUNK_SIZE, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
        except OSError:
            pass

    # ============== public messaging API (Steps 7 + 8) ==============
    def send_text(self, peer_id: str, text: str) -> bool:
        conn = self.get_connection(peer_id)
        if conn is None:
            self.emit("[ERROR] Select a connected peer first")
            return False
        try:
            conn.send_json(protocol.build_text(self.peer_id, self.peer_name,
                                               text))
        except OSError as e:
            self.emit(f"[ERROR] Send failed: {e}")
            conn.close()
            return False
        self.emit(f"You -> {conn.peer_name}: {text}")
        return True

    def send_file(self, peer_id: str, filepath: str) -> bool:
        conn = self.get_connection(peer_id)
        if conn is None:
            self.emit("[ERROR] Select a connected peer first")
            return False

        if not os.path.isfile(filepath):
            self.emit("[ERROR] File not found")
            return False
        try:
            filesize = os.path.getsize(filepath)
        except OSError:
            self.emit("[ERROR] Cannot read file")
            return False

        filename = os.path.basename(filepath)

        try:
            # Stage 1: metadata  ->  Stage 2: raw bytes in chunks
            conn.send_json(protocol.build_file(
                self.peer_id, self.peer_name, filename, filesize))
            conn.send_file_bytes(filepath)
        except FileNotFoundError:
            self.emit("[ERROR] File not found")
            return False
        except PermissionError:
            self.emit("[ERROR] Cannot read file")
            return False
        except OSError as e:
            self.emit(f"[ERROR] File send failed: {e}")
            conn.close()
            return False

        self.emit(f"[SYSTEM] File sent: {filename} "
                  f"({filesize} bytes) to {conn.peer_name}")
        return True

    # ============== connection table (Step 10) ==============
    def add_connection(self, conn: PeerConnection):
        with self.table_lock:
            self.connections.append(conn)
        self.changed()

    def remove_connection(self, conn: PeerConnection):
        with self.table_lock:
            if conn in self.connections:
                self.connections.remove(conn)
            else:
                return
        name = conn.peer_name or f"{conn.address[0]}:{conn.address[1]}"
        self.emit(f"[SYSTEM] {name} disconnected")
        self.changed()

    def get_connection(self, peer_id: str):
        with self.table_lock:
            for conn in self.connections:
                if conn.peer_id == peer_id:
                    return conn
        return None

    def peer_summaries(self):
        """[(peer_id, display_text), ...] for the UI list (Section 7.3)."""
        with self.table_lock:
            conns = list(self.connections)
        result = []
        for c in conns:
            ip = c.address[0]
            port = c.peer_port if c.peer_port else c.address[1]
            name = c.peer_name or "?"
            pid = c.peer_id or "?"
            result.append((pid, f"{name}({pid}) [{ip}:{port}]"))
        return result

    # ============== stop ==============
    def stop(self):
        self.running = False
        with self.table_lock:
            conns = list(self.connections)
        for conn in conns:
            conn.close()
        if self.server_socket is not None:
            try:
                self.server_socket.close()
            except OSError:
                pass
        self.emit("[SYSTEM] Peer stopped")