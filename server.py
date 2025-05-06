import RNS
import RNS.vendor.platformdirs as platformdirs
import subprocess
import threading
import time
import os
import signal
import argparse
import logging

# --- Default Configuration ---
DEFAULT_APP_NAME = "AkitaAdStreamServer" # Updated for project name
DEFAULT_SERVICE_ASPECT = "video_stream/ad_feed" # Generic aspect
DEFAULT_SERVER_NICKNAME = "AkitaAdStream_Server_v0.4" # Updated
DEFAULT_TARGET_STREAM_WIDTH = 1280
DEFAULT_TARGET_STREAM_HEIGHT = 720
DEFAULT_TARGET_FRAMERATE = 20
DEFAULT_VIDEO_CRF = "28"
DEFAULT_VIDEO_PRESET = "ultrafast"
DEFAULT_VIDEO_GOP_SECONDS = 2
DEFAULT_MAX_CLIENTS = 0
DEFAULT_HEARTBEAT_INTERVAL = 15
DEFAULT_HEARTBEAT_TIMEOUT = 45

# --- Ping/Pong Messages ---
PING_MESSAGE = b"__AKITA_ADS_PING__"
PONG_MESSAGE = b"__AKITA_ADS_PONG__"

args = None # Global for parsed arguments

# --- Logging Setup (basic, configured in main) ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(threadName)s - %(message)s')

# --- Global RNS & Process Variables ---
rns_identity = None
announce_destination = None
ffmpeg_process = None
running = True
stream_lock = threading.Lock()
active_clients = 0
client_heartbeat_data = {} # Key: link_id_str, Value: {"last_pong_time": time.time(), "link": link_object}
heartbeat_lock = threading.Lock()


def get_ffmpeg_cmd():
    """Constructs the FFmpeg command list based on current arguments."""
    return [
        'ffmpeg',
        '-loglevel', 'error',
        '-f', 'pipewire',
        '-framerate', str(args.fps),
        '-i', 'portal',
        '-vf', f'scale={args.res[0]}:{args.res[1]}',
        '-c:v', 'libx264',
        '-preset', args.preset,
        '-tune', 'zerolatency',
        '-crf', str(args.crf),
        '-g', str(args.fps * args.gop_seconds),
        '-pix_fmt', 'yuv420p',
        '-f', 'mpegts',
        '-'
    ]

def initialize_rns():
    """Initializes the Reticulum Network Stack identity and destination."""
    global rns_identity, announce_destination
    user_data_dir = platformdirs.user_data_dir(args.app_name)
    if not os.path.exists(user_data_dir):
        os.makedirs(user_data_dir)
    identity_path = os.path.join(user_data_dir, "server_identity")

    logging.info(f"Looking for Reticulum identity at: {identity_path}")
    if os.path.exists(identity_path):
        rns_identity = RNS.Identity.from_file(identity_path)
        logging.info("Identity loaded from file.")
    else:
        logging.info("No identity found, creating new one...")
        rns_identity = RNS.Identity()
        rns_identity.to_file(identity_path)
        logging.info("New identity created and saved.")

    if rns_identity is None:
        logging.error("Reticulum identity could not be initialized.")
        return False

    announce_destination = RNS.Destination(
        rns_identity, RNS.Destination.IN, RNS.Destination.SINGLE,
        args.app_name, args.aspect
    )
    announce_destination.set_link_established_callback(client_link_request_handler)

    logging.info(f"Service Announce Destination: {RNS.prettyhexrep(announce_destination.hash)}")
    logging.info(f"Listening for connections on aspect: {args.app_name}/{args.aspect}")
    logging.info(f"Streaming at: {args.res[0]}x{args.res[1]} @ {args.fps}fps, CRF {args.crf}, Preset {args.preset}")
    if args.max_clients > 0:
        logging.info(f"Max concurrent clients: {args.max_clients}")
    else:
        logging.info("Max concurrent clients: Unlimited")
    logging.info("INFO: When FFmpeg starts, a system dialog may appear to select the screen/window for capture.")
    return True

def ffmpeg_stderr_monitor(pipe, process_pid):
    """Monitors and logs FFmpeg's stderr output in a separate thread."""
    try:
        for line in iter(pipe.readline, b''): # Read line by line
            log_line = line.decode('utf-8', errors='ignore').strip()
            if log_line:
                logging.warning(f"[FFMPEG PID {process_pid} ERR]: {log_line}")
        pipe.close()
    except Exception as e:
        logging.error(f"[FFMPEG PID {process_pid} ERR_MONITOR]: Exception: {e}", exc_info=False) # Keep log concise
    logging.info(f"[FFMPEG PID {process_pid} ERR_MONITOR]: Stderr monitoring ended.")

def start_ffmpeg_process():
    """Starts or attaches to the FFmpeg process if not already running for active clients."""
    global ffmpeg_process, active_clients
    with stream_lock:
        if ffmpeg_process is None or ffmpeg_process.poll() is not None: # If no process or existing one died
            current_ffmpeg_cmd = get_ffmpeg_cmd()
            logging.info("Starting FFmpeg process for Wayland (PipeWire)...")
            logging.debug(f"FFmpeg command: {' '.join(current_ffmpeg_cmd)}")
            try:
                ffmpeg_process = subprocess.Popen(current_ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                logging.info(f"FFmpeg process started with PID: {ffmpeg_process.pid}")

                if ffmpeg_process.stderr:
                    stderr_thread = threading.Thread(
                        target=ffmpeg_stderr_monitor,
                        args=(ffmpeg_process.stderr, ffmpeg_process.pid),
                        daemon=True,
                        name=f"ffmpeg_stderr_{ffmpeg_process.pid}"
                    )
                    stderr_thread.start()

                time.sleep(2.5) # Allow time for portal interaction and FFmpeg initialization
                if ffmpeg_process.poll() is not None:
                    logging.error("FFmpeg process terminated immediately after start. Check logs for FFmpeg errors.")
                    logging.warning("Possible reasons: FFmpeg build (PipeWire?), xdg-desktop-portal, permission denied, or invalid FFmpeg params.")
                    ffmpeg_process = None # Clear the dead process
                    return None # Indicate failure
            except FileNotFoundError:
                logging.error("FFmpeg command not found. Is FFmpeg installed and in PATH?")
                return None
            except Exception as e:
                logging.error(f"Exception starting FFmpeg: {e}", exc_info=True)
                return None
        # If process is already running or successfully started
        active_clients += 1
        logging.info(f"Active clients (after ensuring FFmpeg): {active_clients}")
        return ffmpeg_process # Return the (potentially new) process handle

def stop_ffmpeg_if_no_clients():
    """Stops the FFmpeg process if there are no active clients."""
    global ffmpeg_process, active_clients
    with stream_lock:
        # active_clients is decremented by the caller (stream_to_client finally or heartbeat_checker)
        if active_clients <= 0 and ffmpeg_process and ffmpeg_process.poll() is None:
            logging.info("No active clients, stopping FFmpeg process...")
            try:
                ffmpeg_process.kill() # Send SIGKILL for a quicker stop
                ffmpeg_process.wait(timeout=5) # Wait for the process to terminate
            except subprocess.TimeoutExpired:
                logging.warning("FFmpeg did not terminate in time after SIGKILL.")
            except Exception as e:
                logging.error(f"Error stopping FFmpeg: {e}", exc_info=True)
            finally:
                ffmpeg_process = None # Clear the process handle
                active_clients = 0 # Ensure count is reset
            logging.info("FFmpeg process stopped.")
        elif active_clients < 0: # Should not happen with proper locking
            logging.warning("active_clients count is negative, resetting to 0.")
            active_clients = 0

def server_handle_pong(link_id_str):
    """Updates the last_pong_time for a client."""
    with heartbeat_lock:
        if link_id_str in client_heartbeat_data:
            client_heartbeat_data[link_id_str]["last_pong_time"] = time.time()
            logging.debug(f"[{link_id_str[:8]}] PONG received.")
        else:
            logging.warning(f"[{link_id_str[:8]}] PONG received for unknown or inactive link.")

def server_link_packet_handler(message, packet):
    """Handles incoming control packets (like PONG) on a client's streaming link."""
    link_id_str = RNS.prettyhexrep(packet.link.hash)
    if message == PONG_MESSAGE:
        server_handle_pong(link_id_str)
    else:
        logging.warning(f"[{link_id_str[:8]}] Received unexpected message on streaming link: {message[:30]}...")

def stream_to_client(link):
    """Handles streaming video data and PINGs to a single connected client."""
    global active_clients # To allow modification in finally block
    link_id_str = RNS.prettyhexrep(link.hash)
    client_id_short = link_id_str[:8]
    logging.info(f"[{client_id_short}] Starting stream and heartbeat logic...")

    with heartbeat_lock:
        client_heartbeat_data[link_id_str] = {
            "last_pong_time": time.time(),
            "link": link
        }
    link.set_packet_callback(server_link_packet_handler) # For PONGs

    # Ensure FFmpeg is running for this new client stream
    # The start_ffmpeg_process call handles active_clients increment
    local_ffmpeg_instance = start_ffmpeg_process()
    if not local_ffmpeg_instance:
        logging.error(f"[{client_id_short}] Failed to start/attach to FFmpeg for streaming. Closing link.")
        link.teardown() # This should trigger client_link_closed_callback
        # Decrement must happen if start_ffmpeg_process incremented then failed to return instance
        # However, start_ffmpeg_process only increments if it returns a valid process.
        # If it returns None, active_clients was not incremented by it for this attempt.
        # The caller (client_link_request_handler) doesn't increment, stream_to_client does via start_ffmpeg_process.
        # So, if local_ffmpeg_instance is None, active_clients was NOT incremented for this specific stream_to_client call.
        # We still need to clean up heartbeat data.
        with heartbeat_lock:
            client_heartbeat_data.pop(link_id_str, None)
        return # Exit this thread

    expected_ffmpeg_pid = local_ffmpeg_instance.pid
    last_ping_sent_time = time.time()

    try:
        while running and link.status == RNS.Link.ACTIVE:
            current_time = time.time()
            if current_time - last_ping_sent_time > args.heartbeat_interval:
                logging.debug(f"[{client_id_short}] Sending PING")
                try:
                    link.send(PING_MESSAGE)
                    last_ping_sent_time = current_time
                except Exception as e: # Link might have just closed
                    logging.warning(f"[{client_id_short}] Failed to send PING: {e}")
                    break # Exit loop if PING fails

            # Check FFmpeg process validity
            current_ffmpeg_is_valid = False
            with stream_lock: # Access global ffmpeg_process safely
                if ffmpeg_process and ffmpeg_process.pid == expected_ffmpeg_pid and ffmpeg_process.poll() is None:
                    current_ffmpeg_is_valid = True
            
            if not current_ffmpeg_is_valid:
                logging.warning(f"[{client_id_short}] Expected FFmpeg (PID {expected_ffmpeg_pid}) stopped/changed. Ending stream.")
                break
            
            # Send video data from the shared FFmpeg process
            if ffmpeg_process.stdout:
                # This read can block. Heartbeat timeout will handle unresponsive clients.
                # A more advanced version might use select() for non-blocking reads on stdout.
                chunk = ffmpeg_process.stdout.read(4096)
                if chunk:
                    try:
                        link.send(chunk)
                    except Exception as e: # Link might have closed during send
                        logging.warning(f"[{client_id_short}] Failed to send video chunk: {e}")
                        break # Exit loop
                else: # stdout pipe might have closed or no data temporarily
                    if ffmpeg_process.poll() is not None:
                        logging.info(f"[{client_id_short}] FFmpeg (PID {expected_ffmpeg_pid}) ended mid-stream. Stopping.")
                        break
                    time.sleep(0.005) # Small sleep if no data but process is alive
            else:
                logging.error(f"[{client_id_short}] FFmpeg stdout not available (PID {expected_ffmpeg_pid}). Stopping.")
                break
            
            time.sleep(0.001) # Yield for other threads (e.g., RNS processing PONGs)

    except RNS.exceptions.LinkClosedError:
        logging.info(f"[{client_id_short}] Link closed by remote during streaming.")
    except BrokenPipeError:
        logging.info(f"[{client_id_short}] Broken pipe during send, client link likely dropped.")
    except Exception as e:
        logging.error(f"[{client_id_short}] Unhandled error during streaming: {e}", exc_info=True)
    finally:
        logging.info(f"[{client_id_short}] Stream ended. Cleaning up client resources...")
        if link.status != RNS.Link.CLOSED: # Teardown if not already closed
            try:
                link.teardown()
            except Exception as e:
                logging.debug(f"[{client_id_short}] Exception during final link teardown: {e}")

        with stream_lock: # Safely decrement active_clients
            active_clients -= 1
        stop_ffmpeg_if_no_clients() # Check if FFmpeg can be stopped

        with heartbeat_lock: # Remove from heartbeat monitoring
            client_heartbeat_data.pop(link_id_str, None)
        logging.info(f"[{client_id_short}] Client resources cleaned up. Active clients now: {active_clients}")


def client_link_request_handler(link):
    """Handles new incoming link requests from clients."""
    client_id_short = RNS.prettyhexrep(link.hash)[:8]
    
    # Check max clients limit. active_clients is based on successfully started streams.
    # This check is a preliminary one. The actual increment happens in stream_to_client via start_ffmpeg_process.
    with stream_lock:
        # It's tricky to check active_clients here accurately before stream_to_client tries to start ffmpeg
        # and increments it. Let's assume if we are near max, we might reject.
        # A more robust way is to count established links in client_heartbeat_data.
        num_currently_monitored_clients = 0
        with heartbeat_lock:
            num_currently_monitored_clients = len(client_heartbeat_data)

        if args.max_clients > 0 and num_currently_monitored_clients >= args.max_clients:
            logging.warning(f"Max client limit ({args.max_clients}) reached (monitored: {num_currently_monitored_clients}). Rejecting new client {client_id_short}")
            try:
                link.send(b"MAX_CLIENTS_REACHED")
            except Exception as e:
                logging.debug(f"Could not send MAX_CLIENTS_REACHED to {client_id_short}: {e}")
            link.teardown()
            return

    logging.info(f"Client link request from: {client_id_short}. Accepted, starting handler thread.")
    link.set_link_closed_callback(client_link_closed_callback)
    
    handler_thread = threading.Thread(target=stream_to_client, args=(link,), name=f"ClientStream_{client_id_short}")
    handler_thread.daemon = True
    handler_thread.start()

def client_link_closed_callback(link):
    """Callback for when RNS reports a link has closed."""
    link_id_str = RNS.prettyhexrep(link.hash)
    client_id_short = link_id_str[:8]
    logging.info(f"RNS.Link for client {client_id_short} reports closed by RNS system.")
    # The stream_to_client's `finally` block is the primary place for resource cleanup,
    # including decrementing active_clients and removing from heartbeat_data.
    # This callback acts as a notification. If the stream_to_client thread is stuck
    # and doesn't reach its finally block, the heartbeat_checker should eventually clean up.
    # We can ensure removal from heartbeat_data here as a safeguard if the link is truly gone.
    with heartbeat_lock:
        if link_id_str in client_heartbeat_data:
            logging.debug(f"Ensuring {client_id_short} is removed from heartbeat monitoring due to link closed callback.")
            client_heartbeat_data.pop(link_id_str, None)
            # Decrementing active_clients here could lead to double-counting if stream_to_client also does it.
            # It's safer to let stream_to_client's finally block handle it, or the heartbeat timeout.

def heartbeat_checker():
    """Periodically checks for unresponsive clients based on PONG replies."""
    global active_clients # To allow modification if a client is forcefully removed
    while running:
        time.sleep(args.heartbeat_interval / 2) # Check more frequently than timeout itself
        if not running: break # Exit if server is shutting down

        with heartbeat_lock:
            current_link_ids = list(client_heartbeat_data.keys()) # Iterate over a copy
            for link_id_str in current_link_ids:
                if not running: break # Check again inside loop

                client_data = client_heartbeat_data.get(link_id_str) # Get latest data
                if client_data:
                    link_obj = client_data["link"]
                    last_pong = client_data["last_pong_time"]
                    client_id_short = link_id_str[:8]

                    if time.time() - last_pong > args.heartbeat_timeout:
                        logging.warning(f"[{client_id_short}] Heartbeat timeout. Client unresponsive. Tearing down link.")
                        try:
                            link_obj.teardown() # This should trigger its closed_callback and stream_to_client finally
                        except Exception as e:
                            logging.error(f"[{client_id_short}] Error tearing down link on heartbeat timeout: {e}")
                        
                        # The stream_to_client's finally block should handle active_clients decrement
                        # and removal from client_heartbeat_data.
                        # If the link teardown here is effective, the stream_to_client thread for this link
                        # will break its loop and execute its finally block.
                        # We remove it here to stop further checks if the callback system is slow.
                        client_heartbeat_data.pop(link_id_str, None)
                        # Do NOT decrement active_clients here directly to avoid race conditions.
                        # Rely on stream_to_client's finally block.
        if not running: break


def announce_service():
    """Periodically announces the server's presence on the Reticulum network."""
    if announce_destination and rns_identity:
        logging.info(f"Announcing {args.nickname} on aspect {args.aspect}...")
        app_data_str = f"nickname:{args.nickname};res:{args.res[0]}x{args.res[1]};fps:{args.fps}"
        try:
            announce_destination.announce(app_data_str.encode("utf-8"))
        except Exception as e:
            logging.error(f"Error during service announcement: {e}")

        if running: # Schedule next announcement only if server is still running
            announce_timer = threading.Timer(300, announce_service) # Announce every 5 minutes
            announce_timer.daemon = True # Ensure timer thread doesn't block exit
            announce_timer.start()

def parse_arguments():
    """Parses command-line arguments."""
    global args
    parser = argparse.ArgumentParser(description="Akita AdStream - Wayland Screen Streaming Server.")
    parser.add_argument('--app-name', default=DEFAULT_APP_NAME, help=f"App name for Reticulum. Default: {DEFAULT_APP_NAME}")
    parser.add_argument('--aspect', default=DEFAULT_SERVICE_ASPECT, help=f"Reticulum service aspect. Default: {DEFAULT_SERVICE_ASPECT}")
    parser.add_argument('--nickname', default=DEFAULT_SERVER_NICKNAME, help=f"Server name. Default: {DEFAULT_SERVER_NICKNAME}")
    parser.add_argument('--res', type=str, default=f"{DEFAULT_TARGET_STREAM_WIDTH}x{DEFAULT_TARGET_STREAM_HEIGHT}", help="Streaming resolution WIDTHxHEIGHT.")
    parser.add_argument('--fps', type=int, default=DEFAULT_TARGET_FRAMERATE, help="Target frames per second.")
    parser.add_argument('--crf', type=int, default=DEFAULT_VIDEO_CRF, help="H.264 CRF value (18-28).")
    parser.add_argument('--gop-seconds', type=int, default=DEFAULT_VIDEO_GOP_SECONDS, help="Keyframe interval in seconds.")
    parser.add_argument('--preset', default=DEFAULT_VIDEO_PRESET, choices=['ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium', 'slow', 'slower', 'veryslow'], help="libx264 encoding preset.")
    parser.add_argument('--max-clients', type=int, default=DEFAULT_MAX_CLIENTS, help="Max concurrent clients (0 for unlimited).")
    parser.add_argument('--heartbeat-interval', type=int, default=DEFAULT_HEARTBEAT_INTERVAL, help="Interval (s) for sending PINGs.")
    parser.add_argument('--heartbeat-timeout', type=int, default=DEFAULT_HEARTBEAT_TIMEOUT, help="Timeout (s) for PONG response.")
    parser.add_argument('--loglevel', default='INFO', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'], help="Logging level.")
    args = parser.parse_args()

    try:
        width, height = map(int, args.res.split('x'))
        args.res = (width, height)
    except ValueError:
        # Logging might not be fully set up if this fails early. Use print for critical startup error.
        print(f"CRITICAL: Invalid resolution format: {args.res}. Please use WIDTHxHEIGHT (e.g., 1280x720). Exiting.")
        exit(1)

    # Configure logging level based on parsed argument
    logging.getLogger().setLevel(getattr(logging, args.loglevel.upper()))
    logging.info(f"Log level set to: {args.loglevel.upper()}")


def signal_handler_main(sig, frame):
    """Handles SIGINT/SIGTERM for graceful shutdown."""
    global running
    logging.info("Shutdown signal received...")
    running = False # Signal all loops and threads to stop

    # FFmpeg termination
    if ffmpeg_process and ffmpeg_process.poll() is None:
        logging.info("Terminating FFmpeg process...")
        ffmpeg_process.terminate() # Try SIGTERM first
        try:
            ffmpeg_process.wait(timeout=2)
            if ffmpeg_process.poll() is None:
                logging.warning("FFmpeg did not terminate with SIGTERM, sending SIGKILL.")
                ffmpeg_process.kill()
                ffmpeg_process.wait(timeout=2) # Wait for SIGKILL
        except subprocess.TimeoutExpired:
            logging.warning("FFmpeg did not terminate after SIGKILL attempt within timeout.")
        except Exception as e:
            logging.error(f"Exception during FFmpeg shutdown: {e}", exc_info=False)
    
    # Give other threads a moment to notice the 'running' flag change
    # and attempt to clean up their resources (e.g., client stream threads).
    logging.info("Waiting briefly for threads to wind down...")
    time.sleep(1.0) # Increased slightly

    # Client stream threads are daemons, so they will be forcefully terminated
    # if they don't exit on their own when the main thread exits.
    # The `link.teardown()` in their finally blocks should help.

if __name__ == "__main__":
    parse_arguments() # Parse args and set up logging first

    threading.current_thread().name = "MainServerThread" # Name the main thread

    signal.signal(signal.SIGINT, signal_handler_main)
    signal.signal(signal.SIGTERM, signal_handler_main)

    logging.info(f"Initializing Reticulum for {args.nickname} Server...")
    if not initialize_rns():
        logging.critical("Failed to initialize Reticulum. Exiting.")
        exit(1)

    # Start the heartbeat checker thread
    hb_checker_thread = threading.Thread(target=heartbeat_checker, daemon=True, name="HeartbeatChecker")
    hb_checker_thread.start()
    logging.info("Heartbeat checker thread started.")

    announce_service() # Start the first announcement

    logging.info(f"{args.nickname} Server is running. Press Ctrl+C to exit.")
    
    try:
        while running:
            time.sleep(0.5) # Keep main thread alive, checking 'running' status
    except KeyboardInterrupt: # Should be caught by signal_handler_main
        logging.info("KeyboardInterrupt caught in main server loop.")
    finally:
        logging.info("Main server loop ending.")
        # If the loop exited for a reason other than signal_handler_main setting running=False,
        # (e.g., an unhandled exception in the loop itself, though unlikely here),
        # ensure cleanup is still attempted.
        if running: # This means signal_handler_main was not the primary cause of exit
            signal_handler_main(None, None) # Trigger shutdown sequence

        # This part executes after signal_handler_main has set `running` to False
        # and potentially waited for ffmpeg.
        logging.info("Calling RNS.Reticulum.exit_handler()...")
        RNS.Reticulum.exit_handler() # Cleanly shut down Reticulum
        # Wait a bit for RNS to fully shut down its threads
        time.sleep(1.5) 
        logging.info("Server shutdown complete.")
