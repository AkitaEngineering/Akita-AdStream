#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2025 Akita Engineering
# License: GPLv3

import RNS
import platformdirs
import subprocess
import threading
import time
import os
import argparse
import logging
from dataclasses import dataclass

# --- Configuration Constants ---
APP_NAME = "AkitaAdStreamServer"
DEFAULT_ASPECT = "video_stream/ad_feed"
DEFAULT_NICKNAME = "Akita_Server_Main"
DEFAULT_MAX_CLIENTS = 0  # 0 = unlimited (matches README)

# Protocol Messages
PING_MESSAGE = b"__AKITA_ADS_PING__"
PONG_MESSAGE = b"__AKITA_ADS_PONG__"
MAX_CLIENTS_MSG = b"MAX_CLIENTS_REACHED"

# Logging Config
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(threadName)s] - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("AkitaServer")

@dataclass
class StreamSettings:
    res: tuple
    fps: int
    crf: int
    gop: int
    preset: str
    max_clients: int
    heartbeat_interval: int
    heartbeat_timeout: int

class ClientSession:
    """Tracks state for a single connected client."""
    def __init__(self, link):
        self.link = link
        self.link_id = RNS.prettyhexrep(link.hash)
        self.connected_at = time.time()
        self.last_pong = time.time()
        self.last_ping = time.time()
        self.bytes_sent = 0

class WaylandStreamServer:
    def __init__(self, args):
        self.args = args
        self.settings = StreamSettings(
            res=self._parse_res(args.res),
            fps=args.fps,
            crf=args.crf,
            gop=args.fps * args.gop_seconds,
            preset=args.preset,
            max_clients=args.max_clients,
            heartbeat_interval=args.heartbeat_interval,
            heartbeat_timeout=args.heartbeat_timeout
        )
        
        self.rns_identity = None
        self.announce_dest = None
        self.running = False
        
        # State Management
        self.lock = threading.RLock()
        self.ffmpeg_process = None
        self.clients = {} # Map[link_hash_str, ClientSession]
        
        # Threads
        self.heartbeat_thread = None
        self.announce_timer = None

    def _parse_res(self, res_str):
        try:
            w, h = map(int, res_str.split('x'))
            return (w, h)
        except ValueError:
            logger.critical(f"Invalid resolution format: {res_str}. Use WIDTHxHEIGHT.")
            exit(1)

    def initialize_rns(self):
        self.reticulum = RNS.Reticulum()
        user_dir = platformdirs.user_data_dir(self.args.app_name)
        os.makedirs(user_dir, exist_ok=True)
        id_path = os.path.join(user_dir, "server_identity")

        if os.path.exists(id_path):
            self.rns_identity = RNS.Identity.from_file(id_path)
            logger.info(f"Loaded Identity: {self.rns_identity}")
        else:
            self.rns_identity = RNS.Identity()
            self.rns_identity.to_file(id_path)
            logger.info("Created new Identity.")

        self.announce_dest = RNS.Destination(
            self.rns_identity,
            RNS.Destination.IN,
            RNS.Destination.SINGLE,
            self.args.app_name,
            self.args.aspect
        )
        self.announce_dest.set_link_established_callback(self._on_link_request)
        
        logger.info(f"Aspect: {self.args.app_name}/{self.args.aspect}")
        logger.info(f"Dest Hash: {RNS.prettyhexrep(self.announce_dest.hash)}")

    def _get_ffmpeg_cmd(self):
        return [
            'ffmpeg',
            '-loglevel', 'error',
            '-f', 'pipewire',
            '-framerate', str(self.settings.fps),
            '-i', 'portal',
            '-vf', f'scale={self.settings.res[0]}:{self.settings.res[1]}',
            '-c:v', 'libx264',
            '-preset', self.settings.preset,
            '-tune', 'zerolatency',
            '-crf', str(self.settings.crf),
            '-g', str(self.settings.gop),
            '-pix_fmt', 'yuv420p',
            '-f', 'mpegts',
            '-'
        ]

    def _monitor_ffmpeg_stderr(self, process):
        """Reads FFmpeg stderr to log errors."""
        try:
            for line in iter(process.stderr.readline, b''):
                if not line:
                    break
                log_line = line.decode('utf-8', errors='ignore').strip()
                if log_line:
                    logger.warning(f"[FFMPEG]: {log_line}")
        except Exception as e:
            logger.debug(f"FFmpeg stderr monitor error: {e}", exc_info=True)
        finally:
            if process.stderr:
                try:
                    process.stderr.close()
                except Exception:
                    pass

    def _ensure_ffmpeg_running(self):
        """Starts FFmpeg if not running. Must be called under self.lock."""
        if self.ffmpeg_process and self.ffmpeg_process.poll() is None:
            return True

        cmd = self._get_ffmpeg_cmd()
        logger.info("Starting FFmpeg (Wayland/PipeWire)...")
        logger.debug(f"Command: {' '.join(cmd)}")

        try:
            self.ffmpeg_process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            
            # Start stderr monitor and broadcast loop
            t = threading.Thread(target=self._monitor_ffmpeg_stderr, args=(self.ffmpeg_process,), daemon=True)
            t.start()
            
            t2 = threading.Thread(target=self._ffmpeg_broadcast_loop, args=(self.ffmpeg_process,), name="FFmpegBroadcast", daemon=True)
            t2.start()
            
            logger.info(f"FFmpeg started (PID: {self.ffmpeg_process.pid}). CHECK FOR PERMISSION DIALOG.")
            
            # Give it a moment to fail if permissions denied immediately
            time.sleep(2.0)
            if self.ffmpeg_process.poll() is not None:
                logger.error("FFmpeg died immediately. Permission denied or PipeWire issue.")
                self.ffmpeg_process = None
                return False
            return True
        except Exception as e:
            logger.error(f"Failed to start FFmpeg: {e}")
            self.ffmpeg_process = None
            return False

    def _stop_ffmpeg_if_idle(self):
        """Stops FFmpeg if no clients are connected. Must be called under self.lock."""
        if len(self.clients) == 0 and self.ffmpeg_process:
            logger.info("No active clients. Stopping FFmpeg.")
            try:
                self.ffmpeg_process.terminate()
                self.ffmpeg_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.ffmpeg_process.kill()
            except Exception as e:
                logger.error(f"Error stopping ffmpeg: {e}")
            finally:
                self.ffmpeg_process = None

    def _on_link_request(self, link):
        """Handle incoming RNS link."""
        client_id = RNS.prettyhexrep(link.hash)[:8]
        
        with self.lock:
            if self.settings.max_clients > 0 and len(self.clients) >= self.settings.max_clients:
                logger.warning(f"Rejecting {client_id}: Max clients reached.")
                try:
                    link.send(MAX_CLIENTS_MSG)
                except Exception as e:
                    logger.debug(f"Failed to notify client of max-clients: {e}")
                finally:
                    link.teardown()
                return

            logger.info(f"Accepting client: {client_id}")
            session = ClientSession(link)
            self.clients[RNS.prettyhexrep(link.hash)] = session
            
            link.set_packet_callback(self._on_packet)
            link.set_link_closed_callback(self._on_link_closed)

            if not self._ensure_ffmpeg_running():
                logger.error(f"Cannot stream to {client_id}: FFmpeg failed to start.")
                del self.clients[RNS.prettyhexrep(link.hash)]
                link.teardown()

    def _on_packet(self, message, packet):
        if message == PONG_MESSAGE:
            lid = RNS.prettyhexrep(packet.link.hash)
            with self.lock:
                if lid in self.clients:
                    self.clients[lid].last_pong = time.time()

    def _on_link_closed(self, link):
        lid = RNS.prettyhexrep(link.hash)
        with self.lock:
            if lid in self.clients:
                logger.info(f"Link closed: {lid[:8]}")
                del self.clients[lid]
            self._stop_ffmpeg_if_idle()

    def _ffmpeg_broadcast_loop(self, process):
        logger.info("FFmpeg broadcast loop started.")
        try:
            while self.running and process.poll() is None:
                if process.stdout:
                    chunk = process.stdout.read(4096)
                    if chunk:
                        with self.lock:
                            sessions = list(self.clients.values())
                        
                        for session in sessions:
                            if session.link.status == RNS.Link.ACTIVE:
                                try:
                                    session.link.send(chunk)
                                    session.bytes_sent += len(chunk)
                                except Exception as e:
                                    # Link might be closing, ignore
                                    pass
                    else:
                        time.sleep(0.005)
                else:
                    time.sleep(0.01)
        except Exception as e:
            logger.error(f"Broadcast loop error: {e}")
        finally:
            logger.info("FFmpeg broadcast loop ended.")

    def _heartbeat_checker(self):
        while self.running:
            time.sleep(2)
            now = time.time()
            timeout_threshold = now - self.settings.heartbeat_timeout
            
            with self.lock:
                sessions = list(self.clients.values())
                
            for session in sessions:
                # Check timeout
                if session.last_pong < timeout_threshold:
                    logger.warning(f"Client {session.link_id[:8]} timed out. Kicking.")
                    session.link.teardown()
                    continue
                
                # Send ping
                if now - session.last_ping > self.settings.heartbeat_interval:
                    if session.link.status == RNS.Link.ACTIVE:
                        try:
                            session.link.send(PING_MESSAGE)
                            session.last_ping = now
                        except Exception:
                            pass

    def _announce_loop(self):
        if not self.running: return
        
        # App Data format: key:value;key:value
        app_data = f"nickname:{self.args.nickname};res:{self.settings.res[0]}x{self.settings.res[1]};fps:{self.settings.fps}"
        try:
            self.announce_dest.announce(app_data.encode('utf-8'))
            logger.debug("Service Announced")
        except Exception as e:
            logger.error(f"Announce failed: {e}")

        if self.running:
            self.announce_timer = threading.Timer(120, self._announce_loop)
            self.announce_timer.daemon = True
            self.announce_timer.start()

    def start(self):
        self.running = True
        self.initialize_rns()
        
        # Start Heartbeat Checker
        self.heartbeat_thread = threading.Thread(target=self._heartbeat_checker, name="HeartbeatCheck", daemon=True)
        self.heartbeat_thread.start()
        
        # Initial Announce
        self._announce_loop()
        
        logger.info(f"--- {self.args.nickname} Running ---")
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Stopping...")
        finally:
            self.stop()

    def stop(self):
        self.running = False
        logger.info("Shutting down resources...")
        
        with self.lock:
            # Copy list to iterate
            sessions = list(self.clients.values())
            for sess in sessions:
                sess.link.teardown()
            
            if self.ffmpeg_process:
                self.ffmpeg_process.terminate()
                try: self.ffmpeg_process.wait(2)
                except: self.ffmpeg_process.kill()

        if self.announce_timer:
            self.announce_timer.cancel()
        
        RNS.Reticulum.exit_handler()
        logger.info("Shutdown complete.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Akita AdStream Server")
    parser.add_argument('--app-name', default=APP_NAME)
    parser.add_argument('--aspect', default=DEFAULT_ASPECT)
    parser.add_argument('--nickname', default=DEFAULT_NICKNAME)
    parser.add_argument('--res', default="1280x720", help="WIDTHxHEIGHT")
    parser.add_argument('--fps', type=int, default=20)
    parser.add_argument('--crf', type=int, default=28)
    parser.add_argument('--gop-seconds', type=int, default=2)
    parser.add_argument('--preset', default="ultrafast")
    parser.add_argument('--max-clients', type=int, default=DEFAULT_MAX_CLIENTS)
    parser.add_argument('--heartbeat-interval', type=int, default=15)
    parser.add_argument('--heartbeat-timeout', type=int, default=45)
    
    args = parser.parse_args()
    
    server = WaylandStreamServer(args)
    server.start()
