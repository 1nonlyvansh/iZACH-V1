"""
modules/ui_api.py
REST API for the iZACH React/Electron UI.
Registered onto the same Flask app as whatsapp_handler (port 5050).
"""

import time
import threading
import psutil
from flask import Blueprint, request, jsonify
from flask_cors import CORS

ui_bp = Blueprint("ui_api", __name__)

# ── injected at startup ───────────────────────────────────────
_chain_fn    = None
_speak_fn    = None
_get_resp    = None
_spotify_api = None     # SpotifyController instance

# ── in-process message log ────────────────────────────────────
_message_log: list[dict] = []
MAX_LOG = 200

# ── psutil CPU primer (first call always returns 0 — call once at import) ──
psutil.cpu_percent(interval=None)


def register_ui_api(app, chain_fn, speak_fn, get_response_fn, spotify_handler=None):
    """
    Call once during startup from whatsapp_handler.init_whatsapp().
    spotify_handler — SpotifyController instance (optional but needed for /spotify)
    """
    global _chain_fn, _speak_fn, _get_resp, _spotify_api
    _chain_fn    = chain_fn
    _speak_fn    = speak_fn
    _get_resp    = get_response_fn
    _spotify_api = spotify_handler

    CORS(app, resources={r"/*": {"origins": [
        "http://localhost:5173",
        "http://localhost:4173",
        "app://*",
        "*",           # allow all in dev — tighten for production
    ]}})

    app.register_blueprint(ui_bp)
    print("[UI API] Registered on Flask app. CORS enabled for React/Electron.")


def _log_message(sender: str, text: str):
    global _message_log
    _message_log.append({
        "sender": sender,
        "text":   text,
        "ts":     time.strftime("%H:%M"),
        "epoch":  time.time(),
    })
    if len(_message_log) > MAX_LOG:
        _message_log = _message_log[-MAX_LOG:]


# ─────────────────────────────────────────────────────────────
# POST /command
# Body:    { "text": "play kanye" }
# Returns: { "ok": true, "response": "Playing Kanye West.", "ts": "14:32" }
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/command", methods=["POST", "OPTIONS"])
def ui_command():
    if request.method == "OPTIONS":
        return jsonify({}), 200

    data = request.get_json(silent=True) or {}
    text = (data.get("text") or data.get("command") or "").strip()

    if not text:
        return jsonify({"ok": False, "error": "Empty command"}), 400

    _log_message("YOU", text)
    try:
        from modules.ws_bridge import broadcast
        broadcast({"type": "chat", "sender": "YOU", "text": text, "ts": time.strftime("%H:%M")})
    except Exception:
        pass

    try:
        if _chain_fn is None:
            return jsonify({"ok": False, "error": "Backend not initialized"}), 503

        captured = []

        def _capture_speak(msg, **kwargs):
            if msg and msg.strip():
                import re as _re
                clean = _re.sub(r'<[^>]+>', '', msg).strip()
                clean = _re.sub(r'^\[TONE:[^\]]+\]', '', clean).strip()
                if clean:
                    captured.append(clean)
            # Still play TTS
            if _speak_fn:
                _speak_fn(msg, **kwargs)

        # Patch speak on the chain object for this request
        chain_obj     = getattr(_chain_fn, '__self__', None)
        original_speak = None
        if chain_obj and hasattr(chain_obj, 'speak'):
            original_speak    = chain_obj.speak
            chain_obj.speak   = _capture_speak

        _chain_fn(text)

        if chain_obj and original_speak is not None:
            chain_obj.speak = original_speak

        # If chain didn't speak, fall back to direct AI
        if not captured and _get_resp:
            resp = _get_resp(text)
            if resp:
                captured.append(resp)

        response_text = " ".join(captured).strip() or "Done."
        _log_message("iZACH", response_text)

        return jsonify({
            "ok":       True,
            "response": response_text,
            "ts":       time.strftime("%H:%M"),
        })

    except Exception as e:
        err = f"Backend error: {type(e).__name__}: {e}"
        print(f"[UI API] /command error: {err}")
        return jsonify({"ok": False, "error": err}), 500


# ─────────────────────────────────────────────────────────────
# GET /status
# FIX: use interval=0.1 so CPU is never 0
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/status", methods=["GET"])
def ui_status():
    try:
        # interval=0.1 gives a real reading every call (never 0)
        cpu = psutil.cpu_percent(interval=0.1)
        ram = psutil.virtual_memory()

        # iZACH process own stats
        proc_cpu = 0.0
        proc_mem = 0.0
        try:
            import os as _os
            p = psutil.Process(_os.getpid())
            proc_cpu = round(p.cpu_percent(interval=None), 1)
            proc_mem = round(p.memory_percent(), 1)
        except Exception:
            pass

        # Check WhatsApp bridge
        wa_online = False
        try:
            import requests as _req
            r = _req.get("http://localhost:3000/health", timeout=2)
            wa_online = r.json().get("status") == "connected"
        except Exception:
            pass

        # Check MMA agent
        mma_online = False
        try:
            import requests as _req
            r = _req.get("http://localhost:6060/health", timeout=2)
            mma_online = r.status_code == 200
        except Exception:
            pass

        return jsonify({
            "ok":           True,
            "cpu":          round(cpu, 1),
            "ram":          round(ram.percent, 1),
            "ram_used_gb":  round(ram.used  / 1e9, 2),
            "ram_total_gb": round(ram.total / 1e9, 2),
            "proc_cpu":     proc_cpu,
            "proc_mem":     proc_mem,
            "ts":           time.strftime("%H:%M:%S"),
            "whatsapp":     wa_online,
            "mma":          mma_online,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# GET /spotify
# Returns current track info from SpotifyController
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/spotify", methods=["GET"])
def ui_spotify():
    try:
        if _spotify_api is None:
            return jsonify({"ok": False, "error": "Spotify not initialised"}), 503

        pb = _spotify_api.sp.current_playback() if _spotify_api.sp else None

        if pb is None or not pb.get("is_playing"):
            return jsonify({
                "ok":        True,
                "playing":   False,
                "title":     "—",
                "artist":    "—",
                "device":    "—",
                "album_art": "",
                "progress":  0,
                "duration":  0,
                "volume":    0,
            })

        item   = pb.get("item", {}) or {}
        title  = item.get("name", "—")
        artist = ", ".join(a["name"] for a in item.get("artists", []))
        album  = item.get("album", {}) or {}
        images = album.get("images", [])
        art    = images[0]["url"] if images else ""
        device = pb.get("device", {}) or {}

        return jsonify({
            "ok":        True,
            "playing":   True,
            "title":     title,
            "artist":    artist,
            "device":    device.get("name", "—"),
            "album_art": art,
            "progress":  pb.get("progress_ms", 0),
            "duration":  item.get("duration_ms", 0),
            "volume":    device.get("volume_percent", 0),
            "shuffle":   pb.get("shuffle_state", False),
            "repeat":    pb.get("repeat_state", "off"),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# GET  /memory          — list all memory entries
# POST /memory          — add entry  { "key": "x", "value": "y" }
# DELETE /memory/<key>  — remove entry
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/memory", methods=["GET"])
def memory_list():
    try:
        from modules.memory import list_memory
        entries = list_memory()   # [(key, value, added), ...]
        return jsonify({
            "ok":   True,
            "data": [{"key": k, "value": v, "added": a} for k, v, a in entries],
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/memory", methods=["POST"])
def memory_add():
    try:
        data  = request.get_json(silent=True) or {}
        key   = data.get("key", "").strip()
        value = data.get("value", "").strip()
        if not key or not value:
            return jsonify({"ok": False, "error": "key and value required"}), 400
        from modules.memory import add_memory
        add_memory(key, value)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/memory/<path:key>", methods=["DELETE"])
def memory_delete(key):
    try:
        from modules.memory import remove_memory
        removed = remove_memory(key)
        return jsonify({"ok": removed, "error": None if removed else "Key not found"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# GET  /settings          — read api_keys.json
# POST /settings          — write api_keys.json
# ─────────────────────────────────────────────────────────────

import json as _json
SETTINGS_FILE = "api_keys.json"

@ui_bp.route("/settings", methods=["GET"])
def settings_get():
    try:
        with open(SETTINGS_FILE) as f:
            data = _json.load(f)
        # Never expose raw API keys to the frontend — send masked versions
        safe = {}
        for k, v in data.items():
            if "key" in k.lower() and isinstance(v, str) and len(v) > 8:
                safe[k] = v[:6] + "•" * (len(v) - 6)
            else:
                safe[k] = v
        return jsonify({"ok": True, "settings": safe})
    except FileNotFoundError:
        return jsonify({"ok": True, "settings": {}})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/settings", methods=["POST"])
def settings_post():
    try:
        incoming = request.get_json(silent=True) or {}
        # Load existing so we don't overwrite keys that weren't sent
        try:
            with open(SETTINGS_FILE) as f:
                existing = _json.load(f)
        except Exception:
            existing = {}

        # Only update non-key fields (never accept raw key overwrites from UI)
        allowed = {"wake_word_enabled", "voice", "theme", "language"}
        for k, v in incoming.items():
            if k in allowed:
                existing[k] = v

        with open(SETTINGS_FILE, "w") as f:
            _json.dump(existing, f, indent=2)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# GET /history
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/history", methods=["GET"])
def ui_history():
    n = min(int(request.args.get("n", 50)), MAX_LOG)
    return jsonify({"ok": True, "messages": _message_log[-n:]})


# ─────────────────────────────────────────────────────────────
# POST /stop  — stop TTS mid-speech
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/stop", methods=["POST"])
def ui_stop():
    try:
        import pygame as _pg
        _pg.mixer.music.stop()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500