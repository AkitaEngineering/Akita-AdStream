# Akita AdStream

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

**Organization:** Akita Engineering  
**Version:** 0.6.0  

---

## 1. Project Overview

Akita AdStream is a robust Python-based application designed to duplicate the video output of a Linux Wayland host to multiple client machines over a local network. It leverages the Reticulum Network Stack for encrypted, configuration-free service discovery and transport, and FFmpeg/FFplay for low-latency video processing.

This tool is optimized for:
- Digital Signage / Advertising Displays
- Information Kiosks
- Passive Screen Mirroring

---

## 2. Features

- **Wayland Native:** Uses PipeWire and xdg-desktop-portal for modern Linux screen capture.
- **Interactive Web Dashboard:** A sleek, dark-themed control panel to monitor bandwidth, connected clients, change resolutions on the fly, and start/stop the stream.
- **Zero-Config Networking:** Clients automatically discover servers via Reticulum announcements.
- **Resilient Connectivity:** Active Ping/Pong mechanism detects dead connections instantly, and clients automatically search for the server if the link drops.
- **Resource Efficient:** Configurable resolution, FPS, and CRF to match network conditions.
- **Persistent Configuration:** Changes made in the web UI survive system reboots.

---

## 3. Architecture

- **CLI (`akita/cli.py`):** Uses Typer to handle the `akita` command interface.
- **Server (`akita/server.py`):** Manages the Wayland capture, FFmpeg subprocess, and client sessions over Reticulum links.
- **Dashboard (`akita/dashboard.py` & `akita/web/`):** FastAPI backend and vanilla HTML/JS/CSS frontend with modern Glassmorphism aesthetics.
- **Client (`akita/client.py`):** Encapsulates discovery and playback logic, piping data directly to `ffplay` stdin.

---

## 4. Setup & Installation

We provide a streamlined install script that handles system dependencies, the Python virtual environment, Reticulum configuration, and sets up a `systemd` background service for `rnsd`.

### Automated Installation (Linux)

Run the automated installer script:

```bash
chmod +x install.sh
./install.sh
```

**The installer will:**
1. Install `ffmpeg`, `pipewire`, and Python 3 tools via `apt` or `pacman`.
2. Set up an isolated Python `.venv` and install the pip requirements.
3. Create the `akita` global alias in `~/.local/bin`.
4. Generate the default Reticulum configuration if it's missing.
5. Create and start the `rnsd.service` systemd daemon so Reticulum runs in the background on boot.

---

## 5. Usage

### Start the Server & Dashboard

To start the server and the interactive web dashboard on your host machine:

```bash
akita server start --nickname "LobbyScreen" --res 1280x720 --fps 20 --web-dashboard
```

Once running:
- **Accept the "Share Screen" prompt:** Wayland requires you to select the monitor to share.
- **Access the Dashboard:** Open a web browser to [http://localhost:8000](http://localhost:8000) to monitor and control your stream.

### Connect a Client

On a receiving machine, start the client module:

```bash
akita client connect
```

The client will automatically discover the server on the Reticulum mesh and begin streaming video via `ffplay`.

---

## 6. Configuration Options

### Server Options (`akita server start`)
- `--nickname` — Friendly name for announcements
- `--res` — Resolution (default: `1280x720`)
- `--fps` — Framerate (default: `20`)
- `--max-clients` — Limit connections (default: `0` / unlimited)
- `--web-dashboard / --no-web-dashboard` — Enable/disable the FastAPI web UI
- `--aspect` — Reticulum aspect string (must match client)

### Client Options (`akita client connect`)
- `--aspect` — Reticulum aspect to search for
- `--reconnect-delay` — Seconds to wait before reconnecting

---

## 7. License

- **License:** GNU General Public License v3.0 (GPLv3) — Akita Engineering.

See [LICENSE](LICENSE) for the full license text. SPDX: `GPL-3.0-only`.
