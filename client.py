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
DEFAULT_CLIENT_APP_NAME = "AkitaAdStreamClient" # Updated
DEFAULT_SERVICE_ASPECT = "video_stream/ad_feed"   # Must match server's default
DEFAULT_INITIAL_DISCOVERY_TIMEOUT = 30
DEFAULT_RECONNECT_DELAY = 10

# --- Ping/Pong Messages ---
PING_MESSAGE = b"__AKITA_ADS_PING__" # Must match server
PONG_MESSAGE = b"__AKITA_ADS_PONG__" # Must match server

args = None # Global for parsed arguments

# --- Logging Setup (basic, configured in main) ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(threadName)s - %(message)s')

# --- Global RNS & Process Variables ---
rns_identity = None
server_link = None
ffplay_process = None
announce_handler = None
running = True
discovered_server_info = {} # Holds info about the currently targeted/connected server
server_found_event = threading.Event() # For initial discovery synchronization
connection_attempt_lock = threading.Lock() # Prevents simultaneous connection attempts
last_known_server_details = None # Stores details of the last successfully connected server for quicker reconnect attempts


def get_ffplay_cmd(window_title="Akita AdStream"):
    """Constructs the FFplay command list."""
    return [
        'ffplay',
        '-loglevel', 'error',    # Reduce console output unless debugging ffplay
        '-fflags', 'nobuffer',   # Reduce input buffering for lower latency
        '-flags', 'low_delay',  # Reduce decoding delay
        '-probesize', '32',     # Smaller probesize for faster start of playback
        '-sync', 'ext',         # Synchronize to an external clock (the stream itself)
        '-window_title', window_title, # Custom window title
        '-'                     # Read input from stdin
    ]

def ffplay_stderr_monitor(pipe, process_pid):
    """Monitors and logs FFplay's stderr output in a separate thread."""
    try:
        for line in iter(pipe.readline, b''): # Read line by line
            log_line = line.decode('utf-8', errors='ignore').strip()
            if log_line: # FFplay might output some info/errors
                logging.info(f"[FFPLAY PID {process_pid}]: {log_line}")
        pipe.close()
    except Exception as e:
        logging.error(f"[FFPLAY PID {process_pid} STDERR_MONITOR]: Exception: {e}", exc_info=False)
    logging.info(f"[FFPLAY PID {process_pid} STDERR_MONITOR]: Stderr monitoring ended.")

def start_ffplay(server_name="Server"):
    """Starts the FFplay process if not already running."""
    global ffplay_process
    if ffplay_process and ffplay_process.poll() is None: # Check if already running
        logging.info("FFplay is already running.")
        return ffplay_process

    window_title = f"Akita AdStream - Streaming from {server_name}"
    current_ffplay_cmd = get_ffplay_cmd(window_title)
    logging.info(f"Starting FFplay: {' '.join(current_ffplay_cmd)}")
    try:
        ffplay_process = subprocess.Popen(current_ffplay_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        logging.info(f"FFplay process started with PID: {ffplay_process.pid}")

        if ffplay_process.stderr:
            stderr_thread = threading.Thread(
                target=ffplay_stderr_monitor,
                args=(ffplay_process.stderr, ffplay_process.pid),
                daemon=True,
                name=f"ffplay_stderr_{ffplay_process.pid}"
            )
            stderr_thread.start()
        return ffplay_process
    except FileNotFoundError:
        logging.error("FFplay command not found. Is FFplay installed and in PATH?")
        return None
    except Exception as e:
        logging.error(f"Error starting FFplay: {e}", exc_info=True)
        return None

def stop_ffplay():
    """Stops the FFplay process if it is running."""
    global ffplay_process
    if ffplay_process and ffplay_process.poll() is None: # Check if running
        logging.info("Stopping FFplay process...")
        try:
            if ffplay_process.stdin and not ffplay_process.stdin.closed:
                ffplay_process.stdin.close() # Signal FFplay to exit by closing its input
            ffplay_process.terminate() # Send SIGTERM
            ffplay_process.wait(timeout=2) # Wait for graceful exit
            if ffplay_process.poll() is None: # If still running
                logging.warning("FFplay did not terminate with SIGTERM, sending SIGKILL.")
                ffplay_process.kill() # Send SIGKILL
                ffplay_process.wait(timeout=2) # Wait for SIGKILL
        except subprocess.TimeoutExpired:
            logging.warning("FFplay did not terminate in time after SIGKILL attempt.")
        except Exception as e: # Catch other potential errors (e.g., stdin already closed)
            logging.error(f"Error stopping FFplay: {e}", exc_info=True)
        finally:
            ffplay_process = None # Clear the global reference
        logging.info("FFplay process stopped.")
    elif ffplay_process and ffplay_process.poll() is not None: # Already terminated
        logging.debug("FFplay already terminated, clearing reference.")
        ffplay_process = None


def initialize_rns():
    """Initializes the Reticulum Network Stack identity for the client."""
    global rns_identity
    user_data_dir = platformdirs.user_data_dir(args.app_name)
    if not os.path.exists(user_data_dir):
        os.makedirs(user_data_dir)
    identity_path = os.path.join(user_data_dir, "client_identity")

    logging.info(f"Looking for Reticulum identity at: {identity_path}")
    if os.path.exists(identity_path):
        rns_identity = RNS.Identity.from_file(identity_path)
        logging.info("Client Identity loaded from file.")
    else:
        logging.info("No client identity found, creating new one...")
        rns_identity = RNS.Identity()
        rns_identity.to_file(identity_path)
        logging.info("New client identity created and saved.")

    if rns_identity is None:
        logging.error("Client Reticulum identity could not be initialized.")
        return False
    return True

def parse_app_data(app_data_bytes):
    """Parses the app_data string from server announcements."""
    info = {"nickname": "Unknown Server", "res": "N/A", "fps": "N/A"}
    if not app_data_bytes:
        return info
    try:
        app_data_str = app_data_bytes.decode('utf-8')
        parts = app_data_str.split(';')
        for part in parts:
            if ':' in part:
                key, value = part.split(':', 1)
                if key == "nickname": info["nickname"] = value
                elif key == "res": info["res"] = value
                elif key == "fps": info["fps"] = value
    except Exception as e:
        logging.warning(f"Could not parse app_data '{app_data_bytes}': {e}")
    return info

def connect_to_server_destination(destination_details):
    """Initiates a connection to a server using provided details."""
    global server_link, discovered_server_info

    with connection_attempt_lock: # Ensure only one connection attempt at a time
        if server_link and (server_link.status == RNS.Link.ACTIVE or server_link.status == RNS.Link.PENDING):
            logging.debug("Connection attempt skipped: Link already active or pending.")
            return

        # Update discovered_server_info with the details of the server we are trying to connect to
        discovered_server_info = destination_details["parsed_app_data"]
        server_name = discovered_server_info.get('nickname', 'Unknown Server')
        dest_hash_str = RNS.prettyhexrep(destination_details["hash"])

        logging.info(f"Attempting to connect to {server_name} ({dest_hash_str})...")

        server_rns_destination = RNS.Destination(
            None, # We don't have the server's full Identity object, only its hash
            RNS.Destination.OUT,
            RNS.Destination.SINGLE,
            destination_details["app_name"],
            # Use the primary aspect we are interested in, assuming it's in the announced aspects
            args.aspect if args.aspect in destination_details["aspects"] else destination_details["aspects"][0]
        )
        server_rns_destination.hash = destination_details["hash"] # Set the destination hash
        server_rns_destination.hexhash = RNS.hexrep(destination_details["hash"], delimit=False)

        server_link = RNS.Link(server_rns_destination, rns_identity) # Our identity for the link
        server_link.set_link_established_callback(link_established_callback)
        server_link.set_link_closed_callback(link_closed_callback)
        server_link.set_packet_callback(packet_received_callback)
        # Consider adding a timeout for link establishment using a threading.Timer


def server_discovered_callback(announcement_hash, destination_hash, destination_type, app_name_from_announce, aspects, app_data):
    """Callback for when a server announcement is received."""
    global last_known_server_details, server_found_event

    if args.aspect not in aspects: # Filter for the aspect we are interested in
        return

    current_server_parsed_info = parse_app_data(app_data)
    logging.info(f"Discovered Video Server: {current_server_parsed_info['nickname']} ({RNS.prettyhexrep(destination_hash)})")
    logging.info(f"  Stream Info: Resolution: {current_server_parsed_info['res']}, FPS: {current_server_parsed_info['fps']}")

    # Store details of this discovered server. This could be one of many.
    # For now, we'll try to connect to the first one that matches our criteria or the most recent one.
    # A more advanced client might present a list or have a preference.
    server_details_for_connection = {
        "hash": destination_hash,
        "app_name": app_name_from_announce,
        "aspects": aspects,
        "parsed_app_data": current_server_parsed_info
    }
    
    # Update last_known_server_details with the most recent valid discovery
    last_known_server_details = server_details_for_connection
    server_found_event.set() # Signal that at least one server has been found

    # Attempt connection (guarded by connection_attempt_lock inside the function)
    connect_to_server_destination(server_details_for_connection)


def link_established_callback(link):
    """Callback for when a link to the server is successfully established."""
    global ffplay_process, discovered_server_info # Use the globally set discovered_server_info

    server_name_for_log = discovered_server_info.get('nickname', 'Server')
    dest_hash_str = RNS.prettyhexrep(link.destination.hash)

    logging.info(f"<<< Link established with {server_name_for_log} ({dest_hash_str}) >>>")
    logging.info("Waiting for video stream data...")
    
    # Start FFplay if not already running
    if not (ffplay_process and ffplay_process.poll() is None):
        ffplay_process = start_ffplay(server_name_for_log)
    
    if not ffplay_process:
        logging.error("Failed to start FFplay after link establishment. Tearing down link.")
        link.teardown()


def packet_received_callback(message, packet):
    """Callback for processing packets received from the server."""
    global server_link # To allow teardown from here if needed

    if message == PING_MESSAGE:
        logging.debug("PING received from server. Sending PONG.")
        try:
            # The packet object contains the link it arrived on
            packet.link.send(PONG_MESSAGE)
        except Exception as e:
            logging.warning(f"Failed to send PONG to server: {e}")
        return # Do not process PING as video data

    if message == b"MAX_CLIENTS_REACHED":
        logging.warning("Server indicated maximum clients reached. Closing link and stopping playback.")
        stop_ffplay() # Stop playback first
        if server_link: # server_link should be packet.link
             try:
                server_link.teardown()
             except Exception as e:
                logging.debug(f"Error tearing down link after MAX_CLIENTS: {e}")
        return

    # Assume any other message is video data
    if ffplay_process and ffplay_process.stdin and not ffplay_process.stdin.closed:
        try:
            ffplay_process.stdin.write(message)
            ffplay_process.stdin.flush() # Ensure data is sent to ffplay immediately
        except BrokenPipeError:
            logging.warning("FFplay pipe broken. User likely closed FFplay window.")
            if running: # Only act if not already shutting down
                stop_ffplay()
                if server_link: # server_link should be packet.link
                    try:
                        server_link.teardown()
                    except Exception as e:
                        logging.debug(f"Error tearing down link after broken ffplay pipe: {e}")
        except Exception as e:
            logging.error(f"Error writing video data to FFplay stdin: {e}", exc_info=True)
    elif ffplay_process and (ffplay_process.poll() is not None or (ffplay_process.stdin and ffplay_process.stdin.closed)):
        # This case means ffplay died or was closed, but we are still getting video packets.
        if running and server_link and server_link.status == RNS.Link.ACTIVE: # server_link should be packet.link
            logging.warning("FFplay process is not running or stdin is closed, but received video packet. Stopping link.")
            try:
                server_link.teardown()
            except Exception as e:
                logging.debug(f"Error tearing down link due to inactive ffplay: {e}")

def link_closed_callback(link):
    """Callback for when the link to the server is closed."""
    global server_link, server_found_event, discovered_server_info, last_known_server_details
    
    server_name = "server"
    if discovered_server_info: # Use info of the server we were connected to
        server_name = discovered_server_info.get('nickname', RNS.prettyhexrep(link.destination.hash if link.destination else "unknown"))
    elif last_known_server_details: # Fallback to last known if current was cleared
        server_name = last_known_server_details["parsed_app_data"].get('nickname', RNS.prettyhexrep(link.destination.hash if link.destination else "unknown"))


    logging.info(f"--- Link with {server_name} closed. ---")
    
    stop_ffplay() # Ensure ffplay is stopped
    
    with connection_attempt_lock: # Synchronize access to server_link
        server_link = None # Clear the active link reference
        
    # Don't clear last_known_server_details, as we might want to try reconnecting to it.
    # Clear current discovered_server_info as we are no longer connected to this specific instance.
    discovered_server_info = {} # Reset current server info
    server_found_event.clear() # Ready for new discoveries to set it

    if running: # If not in the process of shutting down
        logging.info(f"Attempting to re-discover servers in {args.reconnect_delay} seconds...")
        
        def delayed_start_discovery_task():
            if running: # Check running status again before actually starting
                start_discovery()
        
        # Use a timer to schedule re-discovery without blocking the callback
        reconnect_timer = threading.Timer(args.reconnect_delay, delayed_start_discovery_task)
        reconnect_timer.daemon = True # Ensure timer doesn't block exit
        reconnect_timer.start()

def start_discovery():
    """Initiates or restarts the server discovery process."""
    global announce_handler
    if not rns_identity:
        logging.error("Cannot start discovery, RNS identity not initialized.")
        return
    if not running:
        logging.info("Not starting discovery as client is shutting down.")
        return

    # Ensure no active connection attempt is in progress while resetting discovery
    with connection_attempt_lock:
        if server_link and (server_link.status == RNS.Link.ACTIVE or server_link.status == RNS.Link.PENDING):
            logging.debug("Discovery attempt skipped: link is already active or pending.")
            return

    logging.info(f"Searching for video servers with aspect: {args.aspect}")
    
    # Cancel previous AnnounceHandler if it exists and RNS is running
    if announce_handler:
        try:
            if RNS.Reticulum.is_running():
                announce_handler.cancel()
            else:
                logging.debug("Reticulum not running, cannot cancel previous announce_handler.")
        except Exception as e:
            logging.debug(f"Error cancelling previous announce_handler: {e}")
        announce_handler = None # Clear the old handler

    # If we have details of a previously connected server, try to find its path first.
    # This can sometimes speed up reconnection if the server is still on the same address.
    if last_known_server_details and last_known_server_details.get("hash"):
        logging.info(f"Probing for last known server: {last_known_server_details['parsed_app_data'].get('nickname', 'Unknown')}")
        RNS.Transport.find_path(last_known_server_details["hash"])
        # Note: This is just a probe. The AnnounceHandler is still needed for actual connection setup via announcement.

    # Request paths to any destination advertising the aspect.
    RNS.Transport.find_path_to_aspects(rns_identity, [args.aspect])

    # Create a new AnnounceHandler to listen for announcements.
    announce_handler = RNS.AnnounceHandler(
        aspect_filter=args.aspect, # Only react to announcements with this specific aspect
        callback=server_discovered_callback
    )
    logging.debug("New AnnounceHandler created and active.")


def parse_arguments_client():
    """Parses command-line arguments for the client."""
    global args
    parser = argparse.ArgumentParser(description="Akita AdStream - Video Stream Client.")
    parser.add_argument('--app-name', default=DEFAULT_CLIENT_APP_NAME, help=f"App name for Reticulum identity. Default: {DEFAULT_CLIENT_APP_NAME}")
    parser.add_argument('--aspect', default=DEFAULT_SERVICE_ASPECT, help=f"Reticulum service aspect to discover. Default: {DEFAULT_SERVICE_ASPECT}")
    parser.add_argument('--timeout', type=int, default=DEFAULT_INITIAL_DISCOVERY_TIMEOUT, help="Initial server discovery timeout (s).")
    parser.add_argument('--reconnect-delay', type=int, default=DEFAULT_RECONNECT_DELAY, help="Delay (s) before re-discovery after disconnect.")
    parser.add_argument('--loglevel', default='INFO', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'], help="Logging level.")
    args = parser.parse_args()

    logging.getLogger().setLevel(getattr(logging, args.loglevel.upper()))
    logging.info(f"Log level set to: {args.loglevel.upper()}")

def signal_handler_client(sig, frame):
    """Handles SIGINT/SIGTERM for graceful client shutdown."""
    global running, announce_handler, server_link
    logging.info("Shutdown signal received...")
    running = False # Signal all loops and threads to stop
    server_found_event.set() # Unblock main loop if it's waiting on this event

    if announce_handler:
        try:
            if RNS.Reticulum.is_running(): # Check if RNS is still up
                announce_handler.cancel()
        except Exception: pass # Ignore errors if already cancelled or RNS is down
    
    if server_link:
        try:
            server_link.teardown()
        except Exception: pass # Ignore errors if link is already torn down or RNS is down

    stop_ffplay() # Ensure ffplay is stopped before Reticulum fully exits

    # Give a moment for link teardowns and ffplay to close its pipes
    time.sleep(0.5)


if __name__ == "__main__":
    parse_arguments_client() # Parse args and set up logging first

    threading.current_thread().name = "MainClientThread" # Name the main thread

    signal.signal(signal.SIGINT, signal_handler_client)
    signal.signal(signal.SIGTERM, signal_handler_client)

    logging.info("Initializing Reticulum for Akita AdStream Client...")
    if not initialize_rns():
        logging.critical("Failed to initialize Reticulum. Exiting.")
        exit(1)

    start_discovery() # Initial call to start looking for servers

    logging.info(f"Waiting for a server for up to {args.timeout} seconds...")
    if not server_found_event.wait(timeout=args.timeout): # Wait for the event with a timeout
        if running: # Check if not shutting down during the wait
            logging.warning(f"No video servers found with aspect '{args.aspect}' within {args.timeout} seconds.")
            logging.info("Client will continue listening for announcements. Press Ctrl+C to exit.")
    else:
        if running: # Check if not shutting down
             logging.info("Server discovered. Connection process initiated (see logs above).")

    try:
        while running:
            time.sleep(1) # Keep main thread alive, checking 'running' status
            # The main work (discovery, connection, receiving packets) happens in RNS threads and callbacks.
    except KeyboardInterrupt: # Should be caught by signal_handler_client
        logging.info("KeyboardInterrupt caught in main client loop.")
    finally:
        logging.info("Main client loop ending.")
        # If the loop exited for a reason other than signal_handler_client setting running=False,
        # ensure cleanup is still attempted.
        if running:
            signal_handler_client(None, None) # Trigger shutdown sequence

        # This part executes after signal_handler_client has set `running` to False
        # and potentially waited for ffplay/links.
        logging.info("Calling RNS.Reticulum.exit_handler()...")
        RNS.Reticulum.exit_handler() # Cleanly shut down Reticulum
        # Wait a bit for RNS to fully shut down its threads
        time.sleep(1.5) 
        logging.info("Client shutdown complete.")
