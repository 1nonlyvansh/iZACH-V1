import ctypes
import json
import io
import time
import threading
from concurrent.futures import ThreadPoolExecutor
import pyautogui
import pytesseract
from PIL import Image, ImageGrab
from google import genai

# --- 1. DPI AWARENESS ---
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except:
    ctypes.windll.user32.SetProcessDPIAware()

# --- 2. CONFIGURATION ---
GOOGLE_API_KEY = "AIzaSyAnwa1AMP2C0aX0RFKz3b6cWPVb4vkI61E"
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
client = genai.Client(api_key=GOOGLE_API_KEY)

# --- 3. LIVE FRAME BUFFER (The "Memory" Eye) ---
# This runs in the background so iZACH "always" has the latest frame ready.
latest_frame = None
frame_lock = threading.Lock()

def screen_capture_daemon():
    global latest_frame
    while True:
        # Capture directly into RAM
        img = ImageGrab.grab(all_screens=True)
        with frame_lock:
            latest_frame = img
        time.sleep(0.4) # Refresh roughly 2.5 times per second

# Start the background "Eye"
threading.Thread(target=screen_capture_daemon, daemon=True).start()

# --- 4. OPTIMIZED UTILITIES ---

def get_latest_frame():
    with frame_lock:
        if latest_frame is None:
            return None
        return latest_frame.copy()

def prepare_for_ai(img):
    """Downsamples image to 540p and compresses to JPEG to speed up API upload."""
    w, h = img.size
    # Resizing cuts the data sent to Google by 75%
    small_img = img.resize((w // 2, h // 2), Image.Resampling.LANCZOS)
    img_byte_arr = io.BytesIO()
    small_img.save(img_byte_arr, format='JPEG', quality=60)
    return Image.open(img_byte_arr)

# --- 5. PARALLEL ANALYSIS ---

def analyze_screen_and_click(user_instruction):
    print(f"⚡ iZACH Parallel Scan: '{user_instruction}'")
    current_img = get_latest_frame()
    if not current_img: return "Camera warming up..."

    # Compress the version we send to the AI
    ai_img = prepare_for_ai(current_img)

    with ThreadPoolExecutor() as executor:
        # Run OCR and AI Vision at the same time
        ocr_task = executor.submit(pytesseract.image_to_data, current_img, output_type=pytesseract.Output.DICT)
        ai_task = executor.submit(client.models.generate_content, 
                                 model="gemini-2.5-flash", 
                                 contents=[f"Find center of '{user_instruction}'. Return ONLY JSON: {{'x': 0-1000, 'y': 0-1000}}", ai_img])

        # 1. Try OCR first for text precision
        data = ocr_task.result()
        for i, text in enumerate(data['text']):
            if user_instruction.lower() in text.lower() and text.strip() != "":
                w, h = current_img.size
                nx = int(((data['left'][i] + data['width'][i]//2) / w) * 1000)
                ny = int(((data['top'][i] + data['height'][i]//2) / h) * 1000)
                execute_click(nx, ny)
                return

        # 2. Fallback to AI Vision for icons
        try:
            res_text = ai_task.result().text.replace("```json", "").replace("```", "").strip()
            coords = json.loads(res_text)
            execute_click(coords['x'], coords['y'])
        except:
            print("Target not found.")

def execute_click(nx, ny):
    sw, sh = pyautogui.size()
    tx = int((nx / 1000) * sw)
    ty = int((ny / 1000) * sh)
    pyautogui.click(tx, ty)

def describe_screen():
    img = get_latest_frame()
    if not img: return "Sensors initializing."
    ai_img = prepare_for_ai(img)
    try:
        response = client.models.generate_content(model="gemini-2.5-flash", contents=["Briefly describe the screen.", ai_img])
        return response.text.strip()
    except: return "Visual error."