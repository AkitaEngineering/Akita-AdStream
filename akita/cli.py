#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import typer
from rich.console import Console
from rich.theme import Theme
from rich.panel import Panel

# Custom Palette: White, Black, Gray, Orange, Baby Blue
custom_theme = Theme({
    "info": "white",
    "warning": "orange3", # Closest standard term to orange
    "error": "bold red",
    "accent": "light_sky_blue1", # Baby blue
    "subtle": "grey70",
})

console = Console(theme=custom_theme)
app = typer.Typer(name="akita", help="Akita AdStream - The Professional Streaming Mesh", no_args_is_help=True)
server_app = typer.Typer(name="server", help="Server commands")
client_app = typer.Typer(name="client", help="Client commands")

app.add_typer(server_app)
app.add_typer(client_app)

@server_app.command("start")
def start_server(
    nickname: str = typer.Option("Akita_Server_Main", "--nickname", "-n", help="Server Nickname"),
    res: str = typer.Option("1280x720", "--res", "-r", help="Resolution"),
    fps: int = typer.Option(20, help="Frames per second"),
    max_clients: int = typer.Option(0, help="Max clients (0 for unlimited)"),
    web_dashboard: bool = typer.Option(True, "--web/--no-web", help="Enable the web dashboard")
):
    """Start the Akita Wayland Stream Server"""
    console.print(Panel(f"Starting Server: [accent]{nickname}[/] at [subtle]{res}[/]", style="info", border_style="accent"))
    
    # We use a dataclass to mock the argparse namespace that the original server expects
    class Args:
        def __init__(self, nickname, res, fps, max_clients):
            self.app_name = "AkitaAdStreamServer"
            self.aspect = "video_stream/ad_feed"
            self.nickname = nickname
            self.res = res
            self.fps = fps
            self.crf = 28
            self.gop_seconds = 2
            self.preset = "ultrafast"
            self.max_clients = max_clients
            self.heartbeat_interval = 15
            self.heartbeat_timeout = 45

    args = Args(nickname, res, fps, max_clients)
    
    from akita.server import WaylandStreamServer
    server = WaylandStreamServer(args)
    import akita.dashboard as dashboard
    dashboard.current_server = server

    # Start the web dashboard if requested
    if web_dashboard:
        import threading
        from akita.dashboard import run_dashboard
        console.print("[info]Launching Web Dashboard on [accent]http://localhost:8000[/][/info]")
        t = threading.Thread(target=server.start, daemon=True)
        t.start()
        run_dashboard()
    else:
        server.start()

@client_app.command("connect")
def connect_client(
    aspect: str = typer.Option("video_stream/ad_feed", help="Reticulum Aspect")
):
    """Start the client and connect to available streams"""
    console.print(Panel("Starting Akita Client...", style="info", border_style="accent"))
    
    class Args:
        def __init__(self, aspect):
            self.app_name = "AkitaAdStreamClient"
            self.aspect = aspect
            self.timeout = 30
            self.reconnect_delay = 5

    args = Args(aspect)
    from akita.client import StreamClient
    client = StreamClient(args)
    client.start()

if __name__ == "__main__":
    app()
