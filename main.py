import ctypes
# --- MANDATORY DPI FIX (MUST BE FIRST) ---
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except:
    ctypes.windll.user32.SetProcessDPIAware()

import speech_recognition as sr
import threading
import time
import os
import psutil
from google import genai 
from google.genai import types 
from word2number import w2n 
import pygame 
import pythoncom
from googlesearch import search 

# --- MODULES ---
from modules.automation import (
    play_specific_spotify, play_specific_youtube, 
    system_media_control, set_exact_volume
)
from modules.vision import analyze_screen_and_click, describe_screen
from ui import JarvisUI

# --- CONFIGURATION ---
GOOGLE_API_KEY = "AIzaSyAnwa1AMP2C0aX0RFKz3b6cWPVb4vkI61E"

try:
    client = genai.Client(api_key=GOOGLE_API_KEY)
    IZACH_PERSONA = "You are iZACH, a futuristic AI assistant. Concise, sarcastic, intelligent."
    chat = client.chats.create(
        model="gemini-2.5-flash",
        config=types.GenerateContentConfig(
            system_instruction=IZACH_PERSONA,
            temperature=0.7
        )
    )
except Exception as e:
    print(f"❌ SDK Init Error: {e}")

pygame.mixer.init()
IS_AWAKE = False
LAST_INTERACTION = time.time()
LAST_TOPIC = None

def speak(text):
    try: app.write_log(f"iZACH: {text}")
    except: pass
    clean_text = text.replace("*", "").replace("#", "")
    try:
        import pyttsx3
        pythoncom.CoInitialize()
        engine = pyttsx3.init('sapi5')
        engine.setProperty('rate', 170)
        engine.say(clean_text)
        engine.runAndWait()
    except: pass

def listen(silent=False):
    r = sr.Recognizer()
    with sr.Microphone() as source:
        if not hasattr(listen, "adj"): 
            r.adjust_for_ambient_noise(source, duration=0.5)
            listen.adj = True
        r.pause_threshold = 0.8
        if not silent: app.write_log("Listening...")
        try:
            audio = r.listen(source, timeout=None)
            q = r.recognize_google(audio, language='en-in')
            if not silent: app.write_log(f"You: {q}")
            return q.lower()
        except: return "none"

def ask_izach_direct(question):
    try:
        response = chat.send_message(question)
        return response.text
    except Exception as e:
        return f"Neural link error: {e}"

def start_brain(ui):
    pythoncom.CoInitialize()
    global app, IS_AWAKE, LAST_INTERACTION, LAST_TOPIC
    speak("Systems Online.")

    while True:
        query = listen(silent=not IS_AWAKE)
        if query == "none": continue

        if not IS_AWAKE:
            if any(w in query for w in ["wake", "jarvis", "izach"]):
                IS_AWAKE = True
                LAST_INTERACTION = time.time()
                speak("Online.")
            continue
        
        LAST_INTERACTION = time.time()
        
        # --- VISION COMMANDS ---
        if any(w in query for w in ["what is on my screen", "read my screen", "describe"]):
            speak("Scanning...")
            speak(describe_screen())

        elif any(word in query for word in ["click", "select", "press", "hit", "open"]):
            target = query.replace("click", "").replace("open", "").replace("select", "").strip()
            if target:
                speak(f"Targeting {target}...")
                result = analyze_screen_and_click(target)
                if "open" in query: # Double click for "open"
                    import pyautogui
                    pyautogui.click() 

        # --- MEDIA COMMANDS ---
        elif "play" in query:
            song = query.replace("play", "").replace("on youtube", "").replace("on spotify", "").strip()
            if "spotify" in query: play_specific_spotify(song)
            else: play_specific_youtube(song)

        elif "volume" in query:
            try:
                lvl = w2n.word_to_num(query)
                set_exact_volume(lvl)
            except: pass

        elif "shutdown" in query:
            speak("Powering down.")
            ui.root.quit()
            break
        else:
            speak(ask_izach_direct(query))

if __name__ == "__main__":
    app = JarvisUI(face_path="face.png")
    threading.Thread(target=start_brain, args=(app,), daemon=True).start()
    app.root.mainloop()