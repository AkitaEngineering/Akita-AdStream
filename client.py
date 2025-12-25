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
import signal
import argparse
import logging

# --- Configuration ---
APP_NAME = "AkitaAdStreamClient"
DEFAULT_ASPECT = "video_stream/ad_feed"

# Messages
PING_MESSAGE = b"__AKITA_ADS_PING__"
PONG_MESSAGE = b"__AKITA_ADS_PONG__"
MAX_CLIENTS_MSG = b"MAX_CLIENTS_REACHED"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(threadName)s] - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("AkitaClient")

class StreamClient:
    def __init__(self, args):
        self.args = args
        self.rns_identity = None
        self.announce_handler = None
        self.server_link = None
        self.ffplay_process = None
        self.running = False
        
        self.lock = threading.RLock()
        self.bytes_received = 0
        self.last_server_info = {}

    def initialize_rns(self):
        user_dir = platformdirs.user_data_dir(self.args.app_name)
        os.makedirs(user_dir, exist_ok=True)
        id_path = os.path.join(user_dir, "client_identity")

        if os.path.exists(id_path):
            self.rns_identity = RNS.Identity.from_file(id_path)
        else:
            self.rns_identity = RNS.Identity()
            self.rns_identity.to_file(id_path)
            logger.info("Created new Identity.")

    def _get_ffplay_cmd(self, title):
        return [
            'ffplay',
            '-loglevel', 'error',
            '-fflags', 'nobuffer',
            '-flags', 'low_delay',
            '-probesize', '32',
            '-sync', 'ext',
            '-window_title', title,
            '-'
        ]

    def _start_ffplay(self, server_name):
        with self.lock:
            self._stop_ffplay() # Ensure clean slate
            
            title = f"Akita AdStream - {server_name}"
            cmd = self._get_ffplay_cmd(title)
            
            try:
                self.ffplay_process = subprocess.Popen(
                    cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE
                )
                
                # Monitor thread for ffplay errors
                t = threading.Thread(target=self._monitor_ffplay_stderr, args=(self.ffplay_process,), daemon=True)
                t.start()
                
                logger.info(f"FFplay started (PID: {self.ffplay_process.pid})")
            except FileNotFoundError:
                logger.critical("FFplay not found! Is ffmpeg installed?")
            except Exception as e:
                logger.error(f"Failed to start FFplay: {e}")

    def _stop_ffplay(self):
        with self.lock:
            if self.ffplay_process:
                try:
                    if self.ffplay_process.stdin: self.ffplay_process.stdin.close()
                    self.ffplay_process.terminate()
                    self.ffplay_process.wait(timeout=1)
                except:
                    try: self.ffplay_process.kill()
                    except: pass
                finally:
                    self.ffplay_process = None

    def _monitor_ffplay_stderr(self, process):
        try:
            for line in iter(process.stderr.readline, b''):
                logger.info(f"[FFPLAY]: {line.decode('utf-8', errors='ignore').strip()}")
        except: pass

    def _on_server_discovered(self, announce_hash, dest_hash, dest_type, app_name, aspects, app_data):
        if self.args.aspect not in aspects: return

        with self.lock:
            if self.server_link and self.server_link.status in [RNS.Link.ACTIVE, RNS.Link.PENDING]:
                return

            server_info = self._parse_app_data(app_data)
            logger.info(f"Discovered: {server_info.get('nickname')} ({server_info.get('res')})")
            
            dest = RNS.Destination(
                None, RNS.Destination.OUT, RNS.Destination.SINGLE,
                app_name, self.args.aspect
            )
            dest.hash = dest_hash
            dest.hexhash = RNS.hexrep(dest_hash, delimit=False)

            self.server_link = RNS.Link(dest, self.rns_identity)
            self.server_link.set_link_established_callback(self._on_link_established)
            self.server_link.set_link_closed_callback(self._on_link_closed)
            self.server_link.set_packet_callback(self._on_packet)
            
            self.last_server_info = server_info

    def _parse_app_data(self, data):
        info = {}
        try:
            parts = data.decode('utf-8').split(';')
            for p in parts:
                if ':' in p:
                    k, v = p.split(':', 1)
                    info[k] = v
        except: pass
        return info

    def _on_link_established(self, link):
        logger.info("Link established! Starting playback...")
        name = self.last_server_info.get('nickname', 'Server')
        self._start_ffplay(name)

    def _on_packet(self, message, packet):
        # Handle Control Messages
        if message == PING_MESSAGE:
            # logger.debug("Ping received")
            try: packet.link.send(PONG_MESSAGE)
            except: pass
            return
        
        if message == MAX_CLIENTS_MSG:
            logger.warning("Server full.")
            packet.link.teardown()
            return

        # Handle Video Data
        with self.lock:
            if self.ffplay_process and self.ffplay_process.stdin:
                try:
                    self.ffplay_process.stdin.write(message)
                    self.ffplay_process.stdin.flush()
                    self.bytes_received += len(message)
                except BrokenPipeError:
                    logger.warning("FFplay closed. Tearing down link.")
                    self._stop_ffplay()
                    packet.link.teardown()
                except Exception as e:
                    logger.error(f"Write error: {e}")

    def _on_link_closed(self, link):
        logger.warning("Link closed.")
        self._stop_ffplay()
        with self.lock:
            self.server_link = None
        
        if self.running:
            logger.info(f"Reconnecting in {self.args.reconnect_delay}s...")
            threading.Timer(self.args.reconnect_delay, self._start_discovery).start()

    def _start_discovery(self):
        if not self.running: return
        with self.lock:
            if self.server_link: return # Already connected
        
        # logger.info("Scanning for servers...")
        # Clear old handler if exists
        if self.announce_handler:
            try: self.announce_handler.cancel()
            except: pass
            
        RNS.Transport.find_path_to_aspects(self.rns_identity, [self.args.aspect])
        self.announce_handler = RNS.AnnounceHandler(
            aspect_filter=self.args.aspect,
            callback=self._on_server_discovered
        )

    def _stats_loop(self):
        while self.running:
            time.sleep(5)
            with self.lock:
                if self.server_link and self.server_link.status == RNS.Link.ACTIVE:
                    kb = self.bytes_received / 1024
                    logger.info(f"Receiving data: {kb:.1f} KB total since connect")

    def start(self):
        self.running = True
        self.initialize_rns()
        self._start_discovery()
        
        # Stats thread
        t = threading.Thread(target=self._stats_loop, daemon=True)
        t.start()
        
        logger.info("Client Running. Waiting for stream...")
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Exiting...")
        finally:
            self.stop()

    def stop(self):
        self.running = False
        with self.lock:
            if self.server_link:
                self.server_link.teardown()
            self._stop_ffplay()
        RNS.Reticulum.exit_handler()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Akita AdStream Client")
    parser.add_argument('--app-name', default=APP_NAME)
    parser.add_argument('--aspect', default=DEFAULT_ASPECT)
    parser.add_argument('--timeout', type=int, default=30)
    parser.add_argument('--reconnect-delay', type=int, default=5)
    
    args = parser.parse_args()
    
    client = StreamClient(args)
    client.start()
