# modules/ws_bridge.py
# WebSocket bridge — sends real-time events to the React UI

import json
import threading
import asyncio
import websockets

_clients = set()
_loop = None

async def _handler(ws):
    _clients.add(ws)
    try:
        async for msg in ws:
            # Commands from UI → pass to iZACH chain
            data = json.loads(msg)
            if data.get("type") == "command":
                from modules.command_chain import _chain_ref
                if _chain_ref:
                    threading.Thread(
                        target=_chain_ref.process,
                        args=(data["text"],),
                        daemon=True
                    ).start()
    finally:
        _clients.discard(ws)

async def _server():
    async with websockets.serve(_handler, "localhost", 5051):
        await asyncio.Future()  # run forever

def start_ws_bridge():
    global _loop
    _loop = asyncio.new_event_loop()
    threading.Thread(target=_loop.run_until_complete, args=(_server(),), daemon=True).start()
    print("[WS] Bridge started on port 5051")

def broadcast(event: dict):
    """Call this from anywhere in iZACH to push events to the UI."""
    if not _clients or not _loop:
        return
    msg = json.dumps(event)
    asyncio.run_coroutine_threadsafe(
        _broadcast_all(msg), _loop
    )

async def _broadcast_all(msg: str):
    dead = set()
    for ws in _clients:
        try:
            await ws.send(msg)
        except Exception:
            dead.add(ws)
    _clients -= dead