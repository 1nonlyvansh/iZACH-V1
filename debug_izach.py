import threading
import time
import os
import pyttsx3
import speech_recognition as sr
from modules.automation import system_media_control, open_app
from ui import JarvisUI

# --- SAFE MODE BRAIN (NO AI) ---
def start_brain(ui):
    def speak(text):
        ui.write_log(f"iZACH: {text}")
        try:
            engine = pyttsx3.init()
            engine.say(text)
            engine.runAndWait()
        except: pass

    time.sleep(1)
    speak("Safe Mode Online. AI is disabled.")

    while True:
        # Keep the window open
        time.sleep(1)

if __name__ == "__main__":
    app = JarvisUI(face_path="face.png")
    brain_thread = threading.Thread(target=start_brain, args=(app,), daemon=True)
    brain_thread.start()
    app.root.mainloop()