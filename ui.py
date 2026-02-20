import customtkinter as ctk
from PIL import Image
import os

class JarvisUI:
    def __init__(self, face_path="face.png"):
        # 1. Setup Main Window
        self.root = ctk.CTk()
        self.root.title("iZACH")
        self.root.geometry("400x500")
        self.root.configure(fg_color="black")
        
        # Keep window on top for 2 seconds then release
        self.root.attributes("-topmost", True)
        self.root.after(2000, lambda: self.root.attributes("-topmost", False))

        # 2. Status Label (Top)
        self.status_label = ctk.CTkLabel(
            self.root, 
            text="SYSTEM ONLINE", 
            font=("Courier New", 16, "bold"),
            text_color="#00FF00"
        )
        self.status_label.pack(pady=10)

        # 3. The Face (Updated to fix Warning)
        self.face_label = ctk.CTkLabel(self.root, text="")
        self.face_label.pack(expand=True)
        
        if os.path.exists(face_path):
            try:
                # Load Image using CTkImage (The correct modern way)
                img = Image.open(face_path)
                self.photo = ctk.CTkImage(light_image=img, dark_image=img, size=(250, 250))
                self.face_label.configure(image=self.photo)
            except Exception as e:
                print(f"UI Error: {e}")
                self.face_label.configure(text="[ IMAGE ERROR ]", text_color="red")
        else:
            self.face_label.configure(
                text="iZACH\n(No Face Found)", 
                font=("Impact", 30), 
                text_color="#00FFFF"
            )

        # 4. Terminal/Log Box (Bottom)
        self.terminal = ctk.CTkTextbox(
            self.root, 
            width=380, 
            height=150, 
            fg_color="#1a1a1a", 
            text_color="#00FF00",
            font=("Consolas", 12)
        )
        self.terminal.pack(pady=10, padx=10)
        self.terminal.insert("0.0", "Initializing...\n")
        self.terminal.configure(state="disabled")

    def write_log(self, text):
        """Updates the terminal box safely."""
        try:
            self.terminal.configure(state="normal")
            self.terminal.insert("end", f"> {text}\n")
            self.terminal.see("end") 
            self.terminal.configure(state="disabled")
            
            # Auto-update status
            if "Listening" in text:
                self.status_label.configure(text="LISTENING...", text_color="#FFD700")
            elif "iZACH" in text:
                self.status_label.configure(text="SPEAKING...", text_color="#00FFFF")
            else:
                self.status_label.configure(text="PROCESSING...", text_color="#00FF00")
                
            self.root.update_idletasks()
        except:
            pass