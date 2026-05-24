# Akita AdStream Use Cases

Akita AdStream's unique architecture—combining modern Wayland screen capture, low-latency FFmpeg processing, and the zero-configuration Reticulum Network Stack—makes it incredibly versatile. Because clients automatically discover the server on the mesh network and gracefully handle reconnects, the system is ideal for highly resilient "deploy and forget" video broadcasting.

Here are some of the best use cases for deploying Akita AdStream:

## 1. Retail Digital Signage & Advertising
**The Scenario:** A retail store wants to broadcast promotional videos, sales announcements, and dynamic advertisements to multiple screens scattered throughout the building.
**Why AdStream:** 
- **Zero Configuration:** Employees just plug in the display monitors (running the client script). They don't need to know IP addresses or configure Wi-Fi routers; Reticulum automatically discovers the server.
- **Synchronized Marketing:** A single backend machine runs the advertising loop, ensuring all screens show the exact same messaging simultaneously.

## 2. Corporate Office Dashboards & KPIs
**The Scenario:** An office wants to display live metrics, analytics dashboards, and company announcements on monitors in breakrooms, hallways, and the sales floor.
**Why AdStream:**
- **Dynamic Content:** Instead of building a custom web app for smart TVs, a single server can just run a web browser fullscreen and mirror it across the entire office.
- **Resilience:** If the network drops momentarily, the auto-reconnect feature ensures the dashboards come right back online without manual intervention.

## 3. Fast Food & Restaurant Menu Boards
**The Scenario:** A restaurant needs to display dynamic, animated digital menus above the counter that change based on the time of day (e.g., breakfast vs. lunch menus).
**Why AdStream:**
- **Centralized Control:** A manager can update the menu on the main server in the back office, and the new feed is instantly broadcasted to all the overhead screens.
- **Resource Efficiency:** The ability to lower FPS and adjust resolution means you can run this efficiently over older, existing network hardware.

## 4. Information Kiosks in Public Spaces
**The Scenario:** Deploying synchronized information displays in places like train stations, airports, museums, or trade shows.
**Why AdStream:**
- **Encrypted Mesh Transport:** Reticulum's built-in encryption ensures that unauthorized users cannot easily intercept or hijack the broadcast feed in public or shared network spaces.
- **Scalability:** The server's multi-client broadcasting can easily handle an expanding fleet of kiosks without significant configuration overhead.

## 5. Classroom & Lecture Hall Mirroring
**The Scenario:** A presenter or professor wants to share their Linux Wayland desktop screen to auxiliary displays in a large auditorium.
**Why AdStream:**
- **No HDMI Splitters:** Eliminates the need for expensive AV hardware, long cable runs, or complex casting protocols.
- **Low Latency:** Optimized FFmpeg/PipeWire pipelines ensure that what the presenter does is mirrored with minimal delay.

## 6. Live Event & Overflow Room Feeds
**The Scenario:** A conference or live event has reached capacity, and attendees need to watch a live feed of the stage from an overflow room in the same building.
**Why AdStream:**
- **Ad-hoc Networking:** With Reticulum, even if the primary internet goes down, the local mesh network continues to carry the video stream flawlessly.

## 7. Emergency Alert Broadcasting
**The Scenario:** A school campus or factory needs to instantly override all display screens to push emergency alerts, weather warnings, or evacuation routes.
**Why AdStream:**
- **Instant Central Command:** The Web UI dashboard allows an administrator to instantly connect clients to a high-priority video feed containing safety instructions.
