"""
protocol.py
-----------
Application-level protocol for the P2P network.

Message framing (needed because TCP is a byte stream, not message stream):

    [ 4-byte length ][ JSON payload ]

The receiver first reads the 4-byte length, then reads EXACTLY that
many bytes. This defines where one message ends and the next begins.

Message types:
    hello      -> handshake request  (peer_id, peer_name, port)
    hello_ack  -> handshake reply    (peer_id, peer_name, port)
    text       -> chat message       (sender_id, sender_name, message)
    file       -> file metadata      (sender_id, sender_name, filename, filesize)
                  (raw file bytes follow immediately, in chunks)
"""

import json
import os
import struct

HEADER_SIZE = 4                 # bytes used for the length prefix
CHUNK_SIZE = 64 * 1024          # 64 KB per chunk for file transfers (Step 9)
DOWNLOAD_DIR = "downloads"      # where received files are stored (7.6)
MAX_FILE_SIZE = 4 * 1024 * 1024 * 1024   # 4 GB — bigger metadata is invalid


def sanitize_filename(name) -> str:
    """Make a received filename safe.

    Hostile names like '..\\..\\virus.exe' or '/etc/passwd' are reduced to a
    bare filename, so received files are ALWAYS saved inside downloads/.
    """
    if not isinstance(name, str):
        name = "unnamed_file"
    name = name.replace("\\", "/")   # normalise Windows separators too
    name = name.split("/")[-1]       # keep only the last path component
    name = name.replace("\x00", "").strip()
    name = name.lstrip(".")          # no hidden files, no ".." tricks
    if not name:
        name = "unnamed_file"
    if len(name) > 150:              # keep extension readable
        root, ext = os.path.splitext(name)
        name = root[:150 - len(ext)] + ext
    return name

HELLO = "hello"
HELLO_ACK = "hello_ack"
TEXT = "text"
FILE = "file"


# ---------------- message builders (Step 5) ----------------

def build_hello(peer_id, peer_name, port):
    return {"type": HELLO, "peer_id": peer_id,
            "peer_name": peer_name, "port": port}


def build_hello_ack(peer_id, peer_name, port):
    return {"type": HELLO_ACK, "peer_id": peer_id,
            "peer_name": peer_name, "port": port}


def build_text(sender_id, sender_name, message):
    return {"type": TEXT, "sender_id": sender_id,
            "sender_name": sender_name, "message": message}


def build_file(sender_id, sender_name, filename, filesize):
    return {"type": FILE, "sender_id": sender_id, "sender_name": sender_name,
            "filename": filename, "filesize": filesize}


# ---------------- framing helpers (Step 6) ----------------

def encode_message(message: dict) -> bytes:
    """dict -> [4-byte length][JSON bytes]."""
    payload = json.dumps(message).encode("utf-8")
    return struct.pack("!I", len(payload)) + payload


def send_message(sock, message: dict):
    """Send one framed JSON message."""
    sock.sendall(encode_message(message))


def recv_exact(sock, num_bytes: int) -> bytes:
    """Read EXACTLY num_bytes from the socket.

    TCP is a byte stream: one recv() may return fewer bytes than asked,
    so we must loop until we have everything.
    """
    data = b""
    while len(data) < num_bytes:
        chunk = sock.recv(min(4096, num_bytes - len(data)))
        if not chunk:
            raise ConnectionError("Peer disconnected")
        data += chunk
    return data


def recv_message(sock) -> dict:
    """Receive one framed JSON message -> dict."""
    header = recv_exact(sock, HEADER_SIZE)
    (length,) = struct.unpack("!I", header)
    payload = recv_exact(sock, length)
    return json.loads(payload.decode("utf-8"))