# UAP P2P Network — Peer-to-Peer Communication and File Sharing

**Course:** CSE 433 — Blockchain & Distributed Security Lab  
**Department:** Computer Science and Engineering (CSE)  
**University:** University of Asia Pacific (UAP)

## Project Overview

UAP P2P Network is a Python desktop application for direct peer-to-peer communication and file sharing over TCP sockets. Each running peer can accept incoming connections and initiate connections to other peers. No central application server is required.

The graphical user interface is built with Tkinter. The application supports peer discovery through a HELLO / HELLO_ACK exchange, text messaging, and binary file transfer.

## Features

- Start a peer with a custom name and listening port.
- Stop a running peer from the GUI.
- Connect to another peer using its IP address and port.
- Exchange peer IDs, names, and listening-port information through HELLO / HELLO_ACK messages.
- Send text messages to a selected connected peer; press Enter or click **Send**.
- Send binary files, including images, audio, video, PDFs, and ZIP files.
- Transfer file data in chunks of up to 64 KiB (65,536 bytes).
- Receive the advertised file size and read the file bytes until that size has been received.
- Handle connections and network activity using threads.
- Show connected peers and status/messages in the GUI.
- Sanitize received filenames so incoming files are saved under the `downloads/` directory rather than an arbitrary path.
- Reject file metadata that advertises a negative size or a size larger than 4 GiB.

## Requirements

- Python 3.9 or later
- Windows, Linux, or macOS
- Python standard library, including `socket`, `threading`, `tkinter`, `json`, `struct`, `uuid`, `os`, and `queue`

No third-party Python packages are required. On some Linux distributions, Tkinter may need to be installed separately through the operating system's package manager.

## Project Structure

```text
P2P_Network/
├── main.py                  # Tkinter GUI and user actions
├── p2p_node.py              # Peer lifecycle, TCP connections, handshake,
│                            # message handling, and file transfer
├── protocol.py              # Message types, JSON framing, and protocol helpers
├── requirements.txt         # Notes that no third-party packages are required
├── downloads/               # Received files and project-provided resources
└── screenshots/             # Example screenshots of the application
```

## Installation and Running

1. Install Python 3.9 or later.
2. Extract the project archive.
3. Open a terminal in the `P2P_Network` folder—the folder containing `main.py`.
4. Check the Python version:

   ```bash
   python --version
   ```

5. Start the application:

   ```bash
   python main.py
   ```

A Tkinter window titled **UAP P2P Network** should open.

## Connect Two Peers

For a same-computer test, run `python main.py` in two separate terminals so that two application windows are open.

### Peer A

1. In **My Peer**, enter `Alice` as the name and `5000` as the port.
2. Click **Start Peer**.

### Peer B

1. In the second window, enter `Bob` as the name and `5001` as the port.
2. Click **Start Peer**.
3. In **Connect to Another Peer**, enter `127.0.0.1` as the IP and `5000` as the port.
4. Click **Connect**.
5. Select the connected peer in **Connected Peers** to send a message or file.

The GUI initially fills in a sample peer name (`Sam`) and port (`5000`); change these values as needed. Each peer on the same computer must use a different listening port.

For two computers on the same LAN, enter the other computer's LAN IP address instead of `127.0.0.1`. Allow the selected TCP port through the computer's firewall if required.

## Send a Text Message

1. Select a peer in **Connected Peers**.
2. Enter text in **Send Text**.
3. Click **Send** or press Enter.
4. Review **Messages / Events** for sent messages and network events.

## Send a File

1. Select a peer in **Connected Peers**.
2. Click **Choose File & Send** in the **Send File** section.
3. Select the file.
4. The receiver stores the incoming file in the `downloads/` directory relative to the application's working directory.
5. Check **Messages / Events** for the transfer result.

Files are transferred as raw bytes, so the application does not need to interpret the file's contents. The receiver reads the number of bytes declared in the file metadata. The implementation uses a 64 KiB chunk size and a 4 GiB maximum advertised file size.

## Application-Level Protocol

TCP is a byte stream, so a single `recv()` call is not guaranteed to return one complete message. This project frames each JSON control message as:

```text
[4-byte unsigned length in network byte order][JSON payload]
```

The length header describes the number of bytes in the JSON payload. The receiver reads the complete header and then exactly the stated payload length before decoding the JSON.

### Message Types

**HELLO** — introduces the connecting peer:

```json
{
  "type": "hello",
  "peer_id": "a83f21c4",
  "peer_name": "Alice",
  "port": 5000
}
```

**HELLO_ACK** — acknowledges the peer and provides its identity information:

```json
{
  "type": "hello_ack",
  "peer_id": "92bd71e3",
  "peer_name": "Bob",
  "port": 5001
}
```

**TEXT** — carries a text message:

```json
{
  "type": "text",
  "sender_id": "a83f21c4",
  "sender_name": "Alice",
  "message": "Hi"
}
```

**FILE** — carries metadata before the raw file bytes are sent:

```json
{
  "type": "file",
  "sender_id": "a83f21c4",
  "sender_name": "Alice",
  "filename": "photo.jpg",
  "filesize": 2456789
}
```

After the FILE JSON message, the sender writes the file's raw bytes to the same TCP connection in chunks. The receiver reads exactly the advertised file size. The JSON framing is used for control messages; the raw file data immediately follows its FILE metadata message.

## Architecture

```text
Tkinter GUI (main.py)
        |
        v
P2P Node and Peer Connections (p2p_node.py)
        |
        +---- TCP server socket / incoming connections
        +---- TCP client sockets / outgoing connections
        +---- worker threads for connection handling
        |
        v
Protocol helpers (protocol.py)
        |
        +---- HELLO / HELLO_ACK / TEXT / FILE messages
        +---- 4-byte length-prefixed JSON framing
        +---- 64 KiB file-transfer chunks
```

## Screenshots

The following screenshots are included in the `screenshots/` folder:

### Application windows and peer setup

![Application windows and peer setup](screenshots/Screenshot%202026-10-09%20180737.png)

### Connected peers and message/event log

![Connected peers and message/event log](screenshots/Screenshot%202026-10-09%20180955.png)

### Peer communication example

![Peer communication example](screenshots/Screenshot%202026-10-09%20181050.png)

### File transfer example

![File transfer example](screenshots/Screenshot%202026-10-09%20181140.png)

### Project files

![Project files in VS Code](screenshots/Screenshot%202026-10-09%20181207.png)

## Limitations and Security Notes

- The project is intended primarily for same-computer and LAN testing; NAT traversal is not implemented.
- Internet-wide connectivity is not guaranteed.
- If a received file has the same name as an existing file in `downloads/`, the existing file may be overwritten.
- HELLO / HELLO_ACK provides peer identification for the application, but it is not cryptographic authentication.
- The application does not implement end-to-end encryption for text messages or transferred files. Use it for lab/testing purposes and do not send sensitive data over untrusted networks.
- File transfer requires the TCP connection to remain available until the transfer finishes.

## Conclusion

This project demonstrates peer-to-peer networking with Python TCP sockets and a Tkinter interface. It brings together direct peer connections, a simple application-level protocol, threaded connection handling, text messaging, and binary file transfer without a central server.

## Academic Use

Developed for educational purposes for **CSE 433 — Blockchain & Distributed Security Lab**, Department of Computer Science and Engineering, University of Asia Pacific.
