import json
import logging
import mimetypes
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR
STATIONS_PATH = BASE_DIR / "stations.json"
PORT = int(os.environ.get("PORT", "10000"))
MPV_SOCKET = os.environ.get("MPV_SOCKET", "/tmp/mpv.sock")
MPV_AUDIO_DEVICE = os.environ.get("MPV_AUDIO_DEVICE", "auto")
RECONNECT_INTERVAL = max(5, int(os.environ.get("RECONNECT_INTERVAL", "10")))
STREAM_RECONNECT_OPTIONS = {
    "reconnect": "1",
    "reconnect_at_eof": "1",
    "reconnect_streamed": "1",
    "reconnect_delay_max": "10",
}
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
LOGGER = logging.getLogger("radio")

STATE = {
    "current_station": None,
    "playing": False,
    "volume": 80,
    "error": None,
    "auto_reconnect": False,
    "loading": False,
    "playlist_started": False,
}
STATE_LOCK = threading.RLock()
MPV_PROCESS = None
MPV_PROCESS_LOCK = threading.Lock()


def youtube_playlist_url(url):
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in YOUTUBE_HOSTS:
            return None
    except ValueError:
        return None

    query = parse_qs(parsed.query)
    ids = query.get("list", [])
    if len(ids) != 1 or not re.fullmatch(r"[A-Za-z0-9_-]+", ids[0]):
        return None

    playlist_id = ids[0]
    if playlist_id.startswith("RD"):
        video_id = query.get("v", [""])[0]
        if parsed.hostname == "youtu.be":
            video_id = parsed.path.lstrip("/")
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            # A Mix saved as a playlist URL may still encode its seed video in the list ID.
            seed = re.fullmatch(r"RD([A-Za-z0-9_-]{11})", playlist_id)
            video_id = seed.group(1) if seed else ""
        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}&list={playlist_id}"

    return f"https://www.youtube.com/playlist?list={playlist_id}"


def load_stations():
    with STATIONS_PATH.open("r", encoding="utf-8") as file:
        data = json.load(file)
    stations = []
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("name"), str) and isinstance(item.get("url"), str):
            station = {"name": item["name"], "url": item["url"]}
            if youtube_playlist_url(station["url"]):
                station["type"] = "youtube_playlist"
            stations.append(station)
    return stations


def save_stations(stations):
    with STATIONS_PATH.open("w", encoding="utf-8") as file:
        entries = [{"name": station["name"], "url": station["url"]} for station in stations]
        json.dump(entries, file, ensure_ascii=False, indent=2)


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
            "--vid=no",
            f"--audio-device={MPV_AUDIO_DEVICE}",
            "--volume=80",
        ]

        MPV_PROCESS = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=None,
        )
        LOGGER.info("started mpv pid=%s", MPV_PROCESS.pid)

        deadline = time.time() + 120
        while time.time() < deadline:
            if Path(MPV_SOCKET).exists():
                return
            if MPV_PROCESS.poll() is not None:
                break
            time.sleep(0.1)

        raise RuntimeError("mpv did not create its IPC socket")


def mpv_command(command):
    ensure_mpv_running()
    payload = json.dumps({"command": command, "request_id": 1}).encode("utf-8") + b"\n"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(3)
        client.connect(MPV_SOCKET)
        client.sendall(payload)
        with client.makefile("rb") as responses:
            for line in responses:
                response = json.loads(line)
                if response.get("request_id") == 1:
                    return response
    raise RuntimeError("mpv returned no response")


def mpv_control(command):
    response = mpv_command(command)
    if response.get("error") != "success":
        raise RuntimeError(f"mpv: {response.get('error')}")


def refresh_state():
    with STATE_LOCK:
        try:
            pause = mpv_command(["get_property", "pause"]).get("data")
            volume = mpv_command(["get_property", "volume"]).get("data")
            idle = mpv_command(["get_property", "idle-active"]).get("data")
            station = STATE["current_station"]
            if station and station.get("type") == "youtube_playlist":
                position = mpv_command(["get_property", "playlist-pos"]).get("data")
                audio = mpv_command(["get_property", "audio-params"]).get("data")
                # Older mpv versions report an unavailable position instead of -1 at EOF.
                if idle and position in (None, -1):
                    STATE["current_station"] = None
                    if not STATE["playlist_started"]:
                        STATE["error"] = "Não foi possível reproduzir a playlist do YouTube."
                    STATE["loading"] = False
                else:
                    STATE["playlist_started"] = STATE["playlist_started"] or bool(audio)
                    STATE["loading"] = not audio and not pause
                STATE["playing"] = bool(audio) and not pause and not idle
            else:
                filename = mpv_command(["get_property", "filename"]).get("data")
                STATE["playing"] = bool(filename) and not pause and not idle
        except Exception as exc:
            STATE["playing"] = False
            STATE["error"] = str(exc)
            return snapshot_state()

        if isinstance(volume, (int, float)):
            STATE["volume"] = max(0, min(100, int(volume)))
        if STATE["playing"]:
            STATE["error"] = None
        return snapshot_state()


def snapshot_state():
    with STATE_LOCK:
        return {
            "current_station": STATE["current_station"],
            "playing": STATE["playing"],
            "loading": STATE["loading"],
            "volume": STATE["volume"],
            "error": STATE["error"],
        }


def set_error(message):
    with STATE_LOCK:
        STATE["error"] = message


def play_station(station, *, reconnect=False):
    playlist_url = youtube_playlist_url(station["url"])
    if playlist_url and not shutil.which("yt-dlp"):
        raise RuntimeError("Instale o yt-dlp para reproduzir playlists do YouTube.")

    with STATE_LOCK:
        # HTTP EOF is normal for a track and must advance the playlist.
        stream_options = {} if playlist_url else STREAM_RECONNECT_OPTIONS
        mpv_control(["set_property", "stream-lavf-o", stream_options])
        ytdl_options = {}
        if playlist_url:
            ytdl_options["yes-playlist"] = ""
            if urlparse(playlist_url).path == "/watch":
                # Generated mixes can contain hundreds of recommendations.
                ytdl_options["playlist-end"] = "20"
        mpv_control(["set_property", "ytdl-raw-options", ytdl_options])
        url = f"ytdl://{playlist_url}" if playlist_url else station["url"]
        mpv_control(["loadfile", url, "replace"])
        mpv_control(["set_property", "pause", False])
        STATE["current_station"] = station
        STATE["auto_reconnect"] = not playlist_url
        STATE["loading"] = bool(playlist_url)
        STATE["playlist_started"] = False
        STATE["error"] = None
    LOGGER.info("%s station: %s (%s)", "reconnected" if reconnect else "playing", station["name"], station["url"])


def reconnect_loop():
    """Reload the selected station after mpv reaches EOF or loses the stream."""
    while True:
        time.sleep(RECONNECT_INTERVAL)
        with STATE_LOCK:
            station = STATE["current_station"]
            if not STATE["auto_reconnect"] or not station:
                continue

            try:
                paused = mpv_command(["get_property", "pause"]).get("data")
                idle = mpv_command(["get_property", "idle-active"]).get("data")
                if not paused and idle:
                    LOGGER.warning("stream ended or disconnected; reconnecting %s", station["name"])
                    play_station(station, reconnect=True)
            except Exception as exc:
                set_error(f"reconnect failed: {exc}")
                LOGGER.exception("failed to reconnect %s", station["name"])


def spotify_status():
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "raspotify"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() == "active"
    except Exception:
        return False


def spotify_set(enable):
    action = "start" if enable else "stop"
    subprocess.run(
        ["sudo", "systemctl", action, "raspotify"],
        capture_output=True, timeout=10,
    )


class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/stations":
            return self.respond_json({"stations": load_stations()})
        if parsed.path == "/api/status":
            return self.respond_json(refresh_state())
        if parsed.path == "/api/spotify":
            return self.respond_json({"active": spotify_status()})
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
                play_station(station)
                return self.respond_json(refresh_state())

            if parsed.path == "/api/pause":
                with STATE_LOCK:
                    mpv_control(["set_property", "pause", True])
                return self.respond_json(refresh_state())

            if parsed.path == "/api/resume":
                with STATE_LOCK:
                    if not STATE["current_station"]:
                        return self.respond_json({"error": "no station selected"}, HTTPStatus.BAD_REQUEST)
                    mpv_control(["set_property", "pause", False])
                return self.respond_json(refresh_state())

            if parsed.path == "/api/stop":
                with STATE_LOCK:
                    mpv_control(["stop"])
                    STATE["current_station"] = None
                    STATE["playing"] = False
                    STATE["error"] = None
                    STATE["auto_reconnect"] = False
                    STATE["loading"] = False
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
                playlist_url = youtube_playlist_url(url)
                url = playlist_url or url
                stations = load_stations()
                if any(s["url"] == url or (playlist_url and youtube_playlist_url(s["url"]) == playlist_url) for s in stations):
                    return self.respond_json({"error": "station already exists"}, HTTPStatus.CONFLICT)
                stations.append({"name": name, "url": url})
                save_stations(stations)
                return self.respond_json(refresh_state())

            if parsed.path == "/api/spotify":
                enable = body.get("active", True)
                spotify_set(enable)
                return self.respond_json({"active": spotify_status()})

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
    threading.Thread(target=reconnect_loop, name="stream-reconnect", daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), RequestHandler)
    server.serve_forever()
