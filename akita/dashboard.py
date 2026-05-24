import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import os
import RNS

app = FastAPI(title="Akita Dashboard")

# This will be injected by cli.py
current_server = None

class ServerStatus(BaseModel):
    is_running: bool
    nickname: str
    aspect: str
    resolution: str
    fps: int
    max_clients: int
    active_clients: int
    ffmpeg_running: bool

class SettingsPayload(BaseModel):
    res: str
    fps: int
    max_clients: int

@app.get("/api/status", response_model=ServerStatus)
def get_status():
    if current_server is None:
        return ServerStatus(is_running=False, nickname="Offline", aspect="", resolution="", fps=0, max_clients=0, active_clients=0, ffmpeg_running=False)
    
    return ServerStatus(
        is_running=current_server.running,
        nickname=current_server.args.nickname,
        aspect=current_server.args.aspect,
        resolution=f"{current_server.settings.res[0]}x{current_server.settings.res[1]}",
        fps=current_server.settings.fps,
        max_clients=current_server.settings.max_clients,
        active_clients=len(current_server.clients),
        ffmpeg_running=(current_server.ffmpeg_process is not None and current_server.ffmpeg_process.poll() is None)
    )

@app.get("/api/clients")
def get_clients():
    if current_server is None:
        return []
    
    clients_list = []
    with current_server.lock:
        for cid, session in current_server.clients.items():
            clients_list.append({
                "full_id": cid,
                "id": cid[:12],
                "connected_at": session.connected_at,
                "bytes_sent": session.bytes_sent
            })
    return clients_list

@app.post("/api/control/{action}")
def control_server(action: str):
    if current_server is None: return {"error": "No server"}
    if action == "stop" and current_server.running:
        import threading
        threading.Thread(target=current_server.stop, daemon=True).start()
    elif action == "start" and not current_server.running:
        import threading
        threading.Thread(target=current_server.start, daemon=True).start()
    return {"status": "ok"}

@app.delete("/api/clients/{client_id}")
def kick_client(client_id: str):
    if current_server is None: return {"error": "No server"}
    with current_server.lock:
        if client_id in current_server.clients:
            current_server.clients[client_id].link.teardown()
            # It will be removed from the dict on link closed callback
    return {"status": "ok"}

@app.post("/api/settings")
def update_settings(payload: SettingsPayload):
    import json
    import platformdirs
    config_dir = platformdirs.user_data_dir("AkitaAdStreamServer")
    os.makedirs(config_dir, exist_ok=True)
    config_path = os.path.join(config_dir, "config.json")
    
    with open(config_path, "w") as f:
        json.dump(payload.dict(), f)
    
    if current_server is not None:
        current_server.settings.res = tuple(map(int, payload.res.split('x')))
        current_server.settings.fps = payload.fps
        current_server.settings.max_clients = payload.max_clients
        # Apply logic
        if current_server.ffmpeg_process:
            with current_server.lock:
                current_server.ffmpeg_process.terminate()
                try: current_server.ffmpeg_process.wait(2)
                except: current_server.ffmpeg_process.kill()
                current_server.ffmpeg_process = None
                if len(current_server.clients) > 0:
                    current_server._ensure_ffmpeg_running()

    return {"status": "saved"}

# Mount static files
WEB_DIR = os.path.join(os.path.dirname(__file__), "web")
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

@app.get("/")
def read_index():
    return FileResponse(os.path.join(WEB_DIR, "index.html"))

def run_dashboard():
    # Run the uvicorn server
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
