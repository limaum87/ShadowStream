import json
import mimetypes
import os
import socket
import subprocess
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR
STATIONS_PATH = BASE_DIR / "stations.json"
PORT = int(os.environ.get("PORT", "10000"))
MPV_SOCKET = os.environ.get("MPV_SOCKET", "/tmp/mpv.sock")
MPV_AUDIO_DEVICE = os.environ.get("MPV_AUDIO_DEVICE", "auto")

STATE = {
    "current_station": None,
    "playing": False,
    "volume": 80,
    "error": None,
}
STATE_LOCK = threading.Lock()
MPV_PROCESS = None
MPV_PROCESS_LOCK = threading.Lock()


def load_stations():
    with STATIONS_PATH.open("r", encoding="utf-8") as file:
        data = json.load(file)
    stations = []
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("name"), str) and isinstance(item.get("url"), str):
            stations.append({"name": item["name"], "url": item["url"]})
    return stations


def save_stations(stations):
    with STATIONS_PATH.open("w", encoding="utf-8") as file:
        json.dump(stations, file, ensure_ascii=False, indent=2)


def get_station_by_url(url):
    for station in load_stations():
        if station["url"] == url:
            return station
    return None


def ensure_mpv_running():
    global MPV_PROCESS
    with MPV_PROCESS_LOCK:
        if MPV_PROCESS is not None and MPV_PROCESS.poll() is None and Path(MPV_SOCKET).exists():
            return

        try:
            os.remove(MPV_SOCKET)
        except FileNotFoundError:
            pass

        command = [
            "mpv",
            "--idle=yes",
            "--no-terminal",
            f"--input-ipc-server={MPV_SOCKET}",
            "--keep-open=no",
            "--force-window=no",
            "--audio-display=no",
            f"--audio-device={MPV_AUDIO_DEVICE}",
            "--volume=80",
        ]

        MPV_PROCESS = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        deadline = time.time() + 30
        while time.time() < deadline:
            if Path(MPV_SOCKET).exists():
                return
            if MPV_PROCESS.poll() is not None:
                break
            time.sleep(0.1)

        raise RuntimeError("mpv did not create its IPC socket")


def mpv_command(command):
    ensure_mpv_running()
    payload = json.dumps({"command": command}).encode("utf-8") + b"\n"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(3)
        client.connect(MPV_SOCKET)
        client.sendall(payload)
        response = client.recv(65536)
    if not response:
        raise RuntimeError("mpv returned no response")
    return json.loads(response.decode("utf-8"))


def refresh_state():
    with STATE_LOCK:
        error = STATE["error"]

    try:
        pause = mpv_command(["get_property", "pause"]).get("data")
        volume = mpv_command(["get_property", "volume"]).get("data")
        filename = mpv_command(["get_property", "filename"]).get("data")
        idle = mpv_command(["get_property", "idle-active"]).get("data")
    except Exception as exc:
        with STATE_LOCK:
            STATE["playing"] = False
            STATE["error"] = str(exc)
        return snapshot_state()

    with STATE_LOCK:
        if filename:
            matched_station = get_station_by_url(filename)
            if matched_station:
                STATE["current_station"] = matched_station
        elif idle:
            STATE["current_station"] = None
        STATE["playing"] = bool(filename) and not bool(pause) and not bool(idle)
        if isinstance(volume, (int, float)):
            STATE["volume"] = max(0, min(100, int(volume)))
        if error and (STATE["playing"] or idle):
            STATE["error"] = None
    return snapshot_state()


def snapshot_state():
    with STATE_LOCK:
        return {
            "current_station": STATE["current_station"],
            "playing": STATE["playing"],
            "volume": STATE["volume"],
            "error": STATE["error"],
        }


def set_error(message):
    with STATE_LOCK:
        STATE["error"] = message


class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/stations":
            return self.respond_json({"stations": load_stations()})
        if parsed.path == "/api/status":
            return self.respond_json(refresh_state())
        if parsed.path == "/health":
            return self.respond_json({"status": "ok"})
        return self.serve_static(parsed.path)

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw_body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return self.respond_json({"error": "invalid JSON"}, HTTPStatus.BAD_REQUEST)

        try:
            if parsed.path == "/api/play":
                url = body.get("url")
                station = get_station_by_url(url)
                if not station:
                    return self.respond_json({"error": "unknown station"}, HTTPStatus.BAD_REQUEST)
                mpv_command(["loadfile", station["url"], "replace"])
                mpv_command(["set_property", "pause", False])
                with STATE_LOCK:
                    STATE["current_station"] = station
                    STATE["error"] = None
                return self.respond_json(refresh_state())

            if parsed.path == "/api/pause":
                mpv_command(["set_property", "pause", True])
                return self.respond_json(refresh_state())

            if parsed.path == "/api/resume":
                if not snapshot_state()["current_station"]:
                    return self.respond_json({"error": "no station selected"}, HTTPStatus.BAD_REQUEST)
                mpv_command(["set_property", "pause", False])
                return self.respond_json(refresh_state())

            if parsed.path == "/api/stop":
                mpv_command(["stop"])
                with STATE_LOCK:
                    STATE["current_station"] = None
                    STATE["playing"] = False
                    STATE["error"] = None
                return self.respond_json(refresh_state())

            if parsed.path == "/api/volume":
                volume = body.get("volume")
                if not isinstance(volume, (int, float)):
                    return self.respond_json({"error": "volume must be numeric"}, HTTPStatus.BAD_REQUEST)
                volume = max(0, min(100, int(volume)))
                mpv_command(["set_property", "volume", volume])
                with STATE_LOCK:
                    STATE["volume"] = volume
                return self.respond_json(refresh_state())

            if parsed.path == "/api/stations":
                name = body.get("name", "").strip()
                url = body.get("url", "").strip()
                if not name or not url:
                    return self.respond_json({"error": "name and url required"}, HTTPStatus.BAD_REQUEST)
                stations = load_stations()
                if any(s["url"] == url for s in stations):
                    return self.respond_json({"error": "station already exists"}, HTTPStatus.CONFLICT)
                stations.append({"name": name, "url": url})
                save_stations(stations)
                return self.respond_json(refresh_state())

            if parsed.path == "/api/stations/delete":
                url = body.get("url", "").strip()
                if not url:
                    return self.respond_json({"error": "url required"}, HTTPStatus.BAD_REQUEST)
                stations = load_stations()
                filtered = [s for s in stations if s["url"] != url]
                if len(filtered) == len(stations):
                    return self.respond_json({"error": "station not found"}, HTTPStatus.NOT_FOUND)
                save_stations(filtered)
                return self.respond_json(refresh_state())

        except Exception as exc:
            set_error(str(exc))
            return self.respond_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

        return self.respond_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def serve_static(self, path):
        target = "/index.html" if path in {"/", ""} else path
        file_path = (STATIC_DIR / target.lstrip("/")).resolve()
        if STATIC_DIR not in file_path.parents and file_path != STATIC_DIR / "index.html":
            return self.respond_json({"error": "forbidden"}, HTTPStatus.FORBIDDEN)
        if not file_path.exists() or not file_path.is_file():
            file_path = STATIC_DIR / "index.html"
        content_type, _ = mimetypes.guess_type(str(file_path))
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or "text/html; charset=utf-8")
        self.end_headers()
        with file_path.open("rb") as file:
            self.wfile.write(file.read())

    def respond_json(self, payload, status=HTTPStatus.OK):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        return


if __name__ == "__main__":
    ensure_mpv_running()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), RequestHandler)
    server.serve_forever()
