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
- **Zero-Config Networking:** Clients automatically discover servers via Reticulum announcements.
- **Resilient Connectivity:**
  - **Heartbeats:** Active Ping/Pong mechanism detects dead connections instantly.
  - **Auto-Reconnect:** Clients automatically search for the server if the link drops.
- **Resource Efficient:** Configurable resolution, FPS, and CRF to match network conditions.
- **Thread-Safe Architecture:** Class-based design ensures stability under load.

---

## 3. Architecture

### Server (`server.py`)

- **WaylandStreamServer Class:** Manages the main event loop and FFmpeg subprocess.
- **Session Management:** Tracks connected clients via `ClientSession` objects.
- **Logic:** Enforces client limits, handles heartbeats, and streams MPEG-TS H.264 video over Reticulum Links.

### Client (`client.py`)

- **StreamClient Class:** Encapsulates discovery and playback logic.
- **Discovery:** Automatically finds servers broadcasting the configured Aspect.
- **Playback:** Pipes received data directly to FFplay stdin, handling stream resets and server restarts gracefully.

---

## 4. Prerequisites

- **Python:** 3.7+
- **Server:**
  - Linux (Wayland)
  - ffmpeg (with PipeWire support)
  - xdg-desktop-portal
- **Client:**
  - ffplay installed and available in PATH

---

## 5. Setup & Installation

### Get the Code

Download the following files:

- `server.py`
- `client.py`
- `requirements.txt`

### Install Python Dependencies

Run on both server and client machines:

    pip install -r requirements.txt

### System Dependencies (Server)

Ensure FFmpeg and Wayland tools are installed  
(Debian / Ubuntu example):

    sudo apt install ffmpeg xdg-desktop-portal

### System Dependencies (Client)

Ensure FFplay is installed (usually bundled with ffmpeg):

    sudo apt install ffmpeg

---

## 6. Usage

### Server

Start the server on the machine you wish to share:

    python server.py --nickname "LobbyScreen" --res 1280x720 --fps 20

**Note:** On first launch, you must accept the OS-level “Share Screen” permission dialog.

### Client

Start the client on receiving machines:

    python client.py

---

## 7. Configuration Options

### Server Arguments

- `--nickname` — Friendly name for announcements
- `--res` — Resolution (default: 1280x720)
- `--fps` — Framerate (default: 20)
- `--max-clients` — Limit connections (default: 0 / unlimited)
- `--aspect` — Reticulum aspect string (must match client)

### Client Arguments

- `--aspect` — Reticulum aspect to search for
- `--reconnect-delay` — Seconds to wait before reconnecting

---

## 8. License

GPLv3 — Akita Engineering
