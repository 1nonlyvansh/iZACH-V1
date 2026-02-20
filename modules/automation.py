import os
import webbrowser
import pyautogui
import time
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL

def set_exact_volume(level):
    """Sets system volume (0 to 100)."""
    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._sid, CLSCTX_ALL, None)
    volume = cast(interface, POINTER(IAudioEndpointVolume))
    volume.SetMasterVolumeLevelScalar(level / 100, None)
    print(f"🔊 Volume set to {level}%")

def play_specific_youtube(song_name, background_mode=False):
    """Searches and plays a song on YouTube."""
    url = f"https://www.youtube.com/results?search_query={song_name.replace(' ', '+')}"
    webbrowser.open(url)
    time.sleep(3)
    # Click the first video result
    pyautogui.click(x=600, y=400) 
    if background_mode:
        time.sleep(1)
        pyautogui.hotkey('alt', 'tab')

def play_specific_spotify(song_name):
    """Uses Spotify's URI scheme to play music."""
    os.system("start spotify")
    time.sleep(2)
    # Use hotkey to focus search
    pyautogui.hotkey('ctrl', 'l') 
    pyautogui.write(song_name)
    time.sleep(1)
    pyautogui.press('enter')
    time.sleep(1)
    # Fallback to your calibrated Spotify coordinates
    pyautogui.click(x=1008, y=293) 

def system_media_control(command):
    if command == "pause" or command == "play":
        pyautogui.press('playpause')
    elif command == "next":
        pyautogui.press('nexttrack')
    elif command == "prev":
        pyautogui.press('prevtrack')