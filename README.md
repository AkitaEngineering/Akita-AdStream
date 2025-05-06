# Akita AdStream

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

**Organization:** Akita Engineering
**Version:** 0.4.0 (as of May 6, 2025)

## 1. Project Overview

Akita AdStream is a Python-based application designed to capture the screen (or a selected window) of a Linux host machine running Wayland and stream it in real-time to one or more client machines on the same local network. Communication and service discovery are handled by the [Reticulum Network Stack](https://reticulum.network/), ensuring encrypted and resilient connections. The video stream is processed using FFmpeg for capture and encoding on the server, and FFplay for playback on the client.

This tool is primarily intended for scenarios like:
* Local advertising displays.
* Information kiosks.
* Simple screen sharing within a trusted local network where audio is not required.

## 2. Features

* **Screen Capture:** Captures screen content from a Wayland-based Linux server using PipeWire and `xdg-desktop-portal`.
* **Real-time Streaming:** Encodes and streams video with low latency.
* **Reticulum Powered:** Uses Reticulum for:
    * Service announcement and discovery (clients can find servers automatically).
    * Secure, encrypted point-to-point links for video data.
* **Configurable Stream Parameters:** Server allows configuration of resolution, FPS, video quality (CRF), GOP size, and encoding preset via command-line arguments.
* **Max Clients Limit:** Server can be configured to limit the number of concurrent client connections.
* **Heartbeat Mechanism:** Application-level ping/pong messages ensure active connections and help detect unresponsive clients/server.
* **Command-Line Interface:** Both server and client are controlled via CLI arguments.
* **Logging:** Utilizes Python's `logging` module for better diagnostics, with configurable log levels.
* **Automatic Re-discovery (Client):** Client attempts to re-discover and connect if a link is lost.

## 3. Prerequisites

* **Python:** Version 3.7+
* **Reticulum:** The RNS Python library. Install via pip: `pip install rns`
* **Server Machine:**
    * Linux operating system running Wayland.
    * **FFmpeg:** Compiled with PipeWire support. (Most modern distributions provide this).
    * **PipeWire:** Must be running.
    * **`xdg-desktop-portal`:** And a relevant backend for your desktop environment (e.g., `xdg-desktop-portal-gtk`, `xdg-desktop-portal-wlr`). This is necessary for screen capture permissions on Wayland.
* **Client Machine(s):**
    * **FFplay:** (Part of the FFmpeg suite). Must be installed and in the system's PATH.

## 4. Setup

1.  **Get the Code:**
    * Download `server.py` and `client.py`.
2.  **Install Dependencies:**
    * Ensure Python, RNS, FFmpeg (server), and FFplay (client) are installed.
3.  **Reticulum Identities:**
    * The first time `server.py` or `client.py` is run, it will automatically create a Reticulum identity file in a user-specific data directory (e.g., `~/.local/share/AkitaAdStreamServer/server_identity` or `~/.local/share/AkitaAdStreamClient/client_identity`).
4.  **Wayland Server Setup (Crucial):**
    * Verify that `xdg-desktop-portal` and an appropriate backend are running on your Wayland server machine.
    * When you start `server.py` for the first time, FFmpeg (launched by the server script) will request screen capture permission via PipeWire. **A system dialog should appear on your server's desktop.** You *must* interact with this dialog to select the screen (or window) you wish to share and grant permission.
    * Your desktop environment may offer an option to "remember" this permission.

## 5. Running the Application

Open terminal windows on your server and client machines.

**A. Starting the Server (`server.py`)**

Navigate to the directory containing `server.py` and run:
```bash
python server.py [OPTIONS]
```
Example Server Startup:
```bash
python server.py --nickname "LobbyScreenNorth" --res 1920x1080 --fps 25 --crf 25 --max-clients 3 --loglevel INFO
```
B. Starting the Client (client.py)

Navigate to the directory containing client.py and run:
```bash
python client.py [OPTIONS]
```
Example Client Startup:
```
python client.py --aspect "video_stream/lobby_feed" --loglevel INFO
```

## 6. Command-Line Options

Both scripts support various command-line arguments for configuration. Use the --help flag to see all available options:
```bash
python server.py --help
python client.py --help
```

## 7. Troubleshooting 

- *Server: No Screen Selection Dialog / FFmpeg Fails:*
  - Ensure xdg-desktop-portal and a suitable backend are running.
  - Verify FFmpeg has PipeWire support.
  - Check server logs (use --loglevel DEBUG).
  - Run server.py from a terminal within your active Wayland session.
- *Client: No Server Found:*
  - Verify server is running and announcing on the correct --aspect.
  - Check network connectivity and firewalls.
  - Increase client --timeout.
  - Video Issues: Check client/server logs. Adjust server stream parameters (--crf, --fps, --res, --preset).

## 8. License

This project is licensed under the GNU General Public License v3.0.
See the LICENSE file or visit https://www.gnu.org/licenses/gpl-3.0.en.html for details.

## 9. Contributing
Contributions are welcome! Please feel free to fork the repository, make changes, and submit pull requests. For major changes, please open an issue first to discuss what you would like to change.  



