import threading
import time
import queue
import asyncio
import edge_tts
import pygame
import os
import re
import speech_recognition as sr
import pyautogui
from dotenv import load_dotenv
from logging_config import setup_logging
setup_logging()


# --- 1. MODULE IMPORTS ---
from modules.automation import (
    get_current_time,
    get_current_date
)
from modules.ai_handler import AIProvider
from modules.spotify_controller import SpotifyController
import modules.context_engine as context_engine
import modules.scheduler as scheduler
import modules.command_chain as command_chain
import modules.performance_guard as performance_guard
import modules.task_manager as task_manager
from modules.context_manager import ContextManager
from modules.whatsapp_handler import init_whatsapp

# Load environment variables
load_dotenv()

# --- 2. CONFIGURATION ---
pyautogui.FAILSAFE = False

GEMINI_KEYS = [
    "YOUR_GEMINI_KEY_HERE_1",
    "YOUR_GEMINI_KEY_HERE_2",
    "YOUR_GEMINI_KEY_HERE_3"
]
GROQ_KEY   = "YOUR_GROQ_KEY_HERE"
VOICE      = "en-US-ChristopherNeural"
TEMP_AUDIO = "speech.mp3"

# --- 3. GLOBAL OBJECTS ---
SPEECH_QUEUE = queue.Queue()
EXIT_SIGNAL  = False
app          = None
orchestrator = None
_speaking    = False

ai_manager  = AIProvider(GROQ_KEY, GEMINI_KEYS)
spotify_api = SpotifyController()

try:
    pygame.mixer.init()
    print("[SYSTEM] Audio Mixer Initialized.")
except Exception as e:
    print(f"[CRITICAL] Mixer Init Failed: {e}")

# --- 4. NEURAL TTS WORKER ---
async def generate_and_play(text):
    global _speaking
    try:
        from modules.interrupt_engine import get_interrupt_engine
        from modules.personality import extract_tone_rate
        ie = get_interrupt_engine()
        ie.reset()

        clean_text, rate = extract_tone_rate(text)
        communicate = edge_tts.Communicate(clean_text, VOICE, rate=rate)

        await communicate.save(TEMP_AUDIO)
        pygame.mixer.music.load(TEMP_AUDIO)
        pygame.mixer.music.play()
        _speaking = True
        ie.set_speaking(True)

        # Word-by-word live text (only when old tkinter UI is active)
        if app and hasattr(app, 'root'):
            words = clean_text.split()
            if words:
                chars_total = len(text)
                try:
                    duration = pygame.mixer.Sound(TEMP_AUDIO).get_length()
                except Exception:
                    duration = max(len(text) * 0.065, 1.5)

                displayed = []
                elapsed = 0.0
                for word in words:
                    displayed.append(word)
                    partial = " ".join(displayed)
                    word_ratio = (len(word) + 1) / chars_total
                    word_time  = duration * word_ratio
                    try:
                        app.root.after(0, lambda t=partial: app.update_live_text(t))
                    except RuntimeError:
                        break
                    await asyncio.sleep(word_time)
                    elapsed += word_time

        while pygame.mixer.music.get_busy():
            if ie.is_interrupted():
                pygame.mixer.music.stop()
                print("[INTERRUPT] Speech stopped.")
                break
            await asyncio.sleep(0.05)
        pygame.mixer.music.unload()

        if app and hasattr(app, 'root'):
            try:
                app.root.after(0, lambda: app.update_live_text(""))
            except RuntimeError:
                pass

    except Exception as e:
        print(f"[TTS ERROR] {e}")
    finally:
        _speaking = False
        try:
            from modules.interrupt_engine import get_interrupt_engine
            get_interrupt_engine().set_speaking(False)
        except Exception:
            pass

def tts_worker():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    while not EXIT_SIGNAL:
        try:
            text = SPEECH_QUEUE.get(timeout=0.5)
            if text is None:
                break
            loop.run_until_complete(generate_and_play(text))
            SPEECH_QUEUE.task_done()
            if app and hasattr(app, 'set_speaking'):
                app.set_speaking(False)
        except queue.Empty:
            continue
    loop.close()


def stop_speech():
    pygame.mixer.music.stop()
    while not SPEECH_QUEUE.empty():
        try:
            SPEECH_QUEUE.get_nowait()
            SPEECH_QUEUE.task_done()
        except Exception:
            break
    if app and hasattr(app, 'root'):
        try:
            app.root.after(0, lambda: app.update_live_text(""))
            app.root.after(0, lambda: app.set_speaking(False))
        except RuntimeError:
            pass
    print("[INTERRUPT] Queue cleared.")


# --- 5. CORE FUNCTIONS ---

def speak(text, tone: str = "casual"):
    if not text:
        return
    display_text = re.sub(r'<[^>]+>', '', text).strip()
    display_text = re.sub(r'^\[TONE:[^\]]+\]', '', display_text).strip()
    display_text = display_text.replace("iZACH:", "").strip()
    if not display_text:
        return
    if app and hasattr(app, 'write_log'):
        app.write_log(f"iZACH: {display_text}")
    if app and hasattr(app, 'set_speaking'):
        app.set_speaking(True)
    try:
        from modules.personality import add_ssml_tone
        toned = add_ssml_tone(display_text, tone)
        SPEECH_QUEUE.put(toned)
    except Exception:
        SPEECH_QUEUE.put(display_text)


def get_ai_response(query):
    from modules.memory import get_memory_as_context
    from modules.context_memory import get_context_memory
    from modules.personality import PERSONALITY_PROMPT, detect_sentiment, get_companion_response, get_tone_for_sentiment
    cm = get_context_memory()

    resolved    = cm.resolve_followup(query)
    parts       = []
    personal_mem = get_memory_as_context()
    if personal_mem:
        parts.append(personal_mem)

    history = cm.get_history_as_prompt(6)
    if history:
        parts.append(f"Recent conversation:\n{history}")

    parts.insert(0, PERSONALITY_PROMPT)

    if parts:
        full_query = "\n\n".join(parts) + f"\n\nUser: {resolved}"
    else:
        full_query = resolved

    response = ai_manager.send_message(full_query)

    from modules.response_generator import _detect_language
    lang      = _detect_language(query)
    sentiment = detect_sentiment(query)
    if lang == "en":
        companion = get_companion_response(sentiment)
        if companion and response:
            response = f"{companion} {response}"

    cm.add_turn(query, response or "")
    cm.update_entities_from_input(query)
    return response


def get_ai_response_raw(query):
    return ai_manager.send_message(query)


# --- 6. COMMAND LOOP ---

_recognizer = sr.Recognizer()
_recognizer.pause_threshold         = 2.5
_recognizer.phrase_threshold        = 0.2
_recognizer.non_speaking_duration   = 1.0
_recognizer.energy_threshold        = 250
_recognizer.dynamic_energy_threshold = False
_mic = None

def _init_mic():
    global _mic
    _mic = sr.Microphone()
    with _mic as source:
        _recognizer.adjust_for_ambient_noise(source, duration=1.5)
    print(f"[MIC] Calibrated. Energy threshold: {_recognizer.energy_threshold:.0f}")


def listen():
    global _mic
    if app and hasattr(app, 'is_mic_active') and not app.is_mic_active():
        time.sleep(0.5)
        return "none"
    if _mic is None:
        _init_mic()
    try:
        with _mic as source:
            print("[LISTENING...]")
            audio = _recognizer.listen(source, timeout=6, phrase_time_limit=15)
        return _recognizer.recognize_google(audio, language='en-in').lower()
    except sr.WaitTimeoutError:
        return "none"
    except Exception:
        return "none"


def safe_shutdown():
    global EXIT_SIGNAL
    EXIT_SIGNAL = True
    SPEECH_QUEUE.put(None)
    if orchestrator:
        orchestrator.stop_task_worker()
    pygame.mixer.quit()
    if app and hasattr(app, 'root'):
        app.root.quit()


# ─────────────────────────────────────────────────────────────
# start_brain — works with ui=None (Electron/headless) OR
#               ui=JarvisUI instance (old tkinter mode)
# ─────────────────────────────────────────────────────────────
def start_brain(ui=None):
    global app, orchestrator, chain_engine
    app = ui  # None when Electron UI is used

    # 1. Background services
    orchestrator = task_manager.TaskOrchestrator()
    orchestrator.start_task_worker()

    # 2. Performance Guard & Scheduler
    def _proactive_speak(msg):
        from modules.personality import detect_sentiment, get_tone_for_sentiment
        tone = get_tone_for_sentiment(detect_sentiment(msg))
        speak(msg, tone=tone)

    guard = performance_guard.PerformanceGuard(_proactive_speak)
    guard.start()
    reminder_engine = scheduler.TaskScheduler(speak, orchestrator)
    reminder_engine.start()

    # 3. Memory & Chain
    ctx_mgr = ContextManager()
    chain_engine = command_chain.CommandChain(
        context_handler=context_engine,
        scheduler_handler=reminder_engine,
        ai_handler=get_ai_response,
        raw_ai_handler=get_ai_response_raw,
        speak_func=speak,
        orchestrator=orchestrator,
        context_manager=ctx_mgr,
        spotify_handler=spotify_api
    )

    # 4. WhatsApp callbacks — real ones if old UI, dummy lambdas if headless
    from modules.whatsapp_handler import set_ui_callbacks
    if ui is not None:
        set_ui_callbacks(ui.add_notification, ui.add_error_log)
        ui.set_chain(chain_engine)
    else:
        set_ui_callbacks(
            lambda title, msg: print(f"[NOTIFY] {title}: {msg}"),
            lambda msg:        print(f"[ERROR LOG] {msg}")
        )

    init_whatsapp(speak, chain_engine.process, get_ai_response)

    # 5. AURA vision (only when old tkinter UI with camera panel is used)
    def _handle_gesture(gesture_name: str, action: str, metadata: dict):
        print(f"[GESTURE] {gesture_name} → {action}")
        if app and hasattr(app, '_camera_panel'):
            try:
                app.root.after(0, lambda g=gesture_name:
                    app._camera_panel.update_gesture_label(g))
            except Exception:
                pass
        GESTURE_SPEECH = {
            "volume_control":     None,
            "brightness_control": None,
            "play_pause":         "Toggled playback.",
            "mute_unmute":        "Toggled mute.",
            "next_track":         "Next track.",
            "prev_track":         "Previous track.",
            "show_desktop":       "Showing desktop.",
            "switch_desktops":    None,
        }
        msg = GESTURE_SPEECH.get(action)
        if msg:
            speak(msg)

    if app and hasattr(app, '_camera_panel'):
        app._camera_panel.start(on_gesture=_handle_gesture)

    # 6. Interrupt engine
    from modules.interrupt_engine import get_interrupt_engine
    ie = get_interrupt_engine()
    ie.set_stop_fn(stop_speech)

    # 7. Mic calibration (in background so startup is not delayed)
    threading.Thread(target=_init_mic, daemon=True).start()

    # 8. Response generator
    from modules.response_generator import init_response_generator
    init_response_generator(
        groq_key=os.getenv("GROQ_KEY", GROQ_KEY),
        gemini_keys=[
            os.getenv("GEMINI_KEY_1", GEMINI_KEYS[0]),
            os.getenv("GEMINI_KEY_2", GEMINI_KEYS[1]),
            os.getenv("GEMINI_KEY_3", GEMINI_KEYS[2]),
        ],
        speak_func=speak
    )

    # 9. MMA status check
    try:
        import requests as _req
        r = _req.get("http://localhost:6060/health", timeout=2)
        if r.status_code == 200:
            speak("MMA remote agent is online.")
        else:
            speak("MMA agent is offline.")
    except Exception:
        speak("MMA agent is offline.")

    speak("Assistant System Online.")

    # 10. Wake word
    import json as _json
    _ww_enabled = False
    try:
        with open("api_keys.json") as _f:
            _ww_enabled = _json.load(_f).get("wake_word_enabled", False)
    except Exception:
        pass

    if _ww_enabled:
        from modules.wake_word import init_wake_word
        def _on_wake():
            speak("Yes?", tone="casual")
        ww = init_wake_word(_on_wake)
        ww.start()
        print("[WAKE WORD] Active — say 'iZACH' to activate")
    else:
        print("[WAKE WORD] Disabled — always listening mode")

    # 11. Voice loop
    def voice_loop():
        # Wait for mic to finish calibrating before starting
        while _mic is None and not EXIT_SIGNAL:
            time.sleep(0.2)

        while not EXIT_SIGNAL:
            try:
                query = listen()
                if query == "none":
                    continue
                print(f"[USER]: {query}")
                if app and hasattr(app, 'root'):
                    try:
                        app.root.after(0, lambda q=query: app._chat.add_message("USER", q))
                    except Exception:
                        pass
                if any(w in query for w in ["shutdown", "exit", "stop izach"]):
                    speak("Systems offline.")
                    safe_shutdown()
                    break
                chain_engine.process(query)
            except Exception as e:
                print(f"[RUNTIME ERROR] {e}")
                continue

    threading.Thread(target=voice_loop, daemon=True).start()

    while not EXIT_SIGNAL:
        time.sleep(1)


# --- 7. MAIN ---
if __name__ == "__main__":
    threading.Thread(target=tts_worker, daemon=False).start()
    start_brain(ui=None)