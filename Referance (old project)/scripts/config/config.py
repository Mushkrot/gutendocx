# covers.py v3.0 - Font list navigation improvement
# -*- coding: utf-8 -*-

import tkinter as tk
from tkinter import messagebox
from tkinter import ttk
import json
import os
import sys
import math

FONT_OPTIONS = sorted([
    "Algerian-Regular.ttf",
    "AlexBrush-Regular.ttf",
    "Allura-Regular.ttf",
    "AmaticSC-Regular.ttf",
    "ArchitectsDaughter-Regular.ttf",
    "Arial.ttf",
    "Baskerville-Old.ttf",
    "Blackletter-686-BT.ttf",
    "Castellar.ttf",
    "Courier-New.ttf",
    "DancingScript-VariableFont_wght.ttf",
    "Deutsch-Gothic.ttf",
    "EuphoriaScript-Regular.ttf",
    "Fette-Classic-UNZ-Fraktur.ttf",
    "Fette-UNZ-Fraktur.ttf",
    "Geneva.ttf",
    "GrandHotel-Regular.ttf",
    "GreatVibes-Regular.ttf",
    "Helvetica.ttf",
    "IndieFlower-Regular.ttf",
    "InknutAntiqua-Black.ttf",
    "InknutAntiqua-Bold.ttf",
    "InknutAntiqua-ExtraBold.ttf",
    "InknutAntiqua-Light.ttf",
    "InknutAntiqua-Medium.ttf",
    "InknutAntiqua-Regular.ttf",
    "InknutAntiqua-SemiBold.ttf",
    "Kalam-Bold.ttf",
    "Kalam-Light.ttf",
    "Kalam-Regular.ttf",
    "KaushanScript-Regular.ttf",
    "LibreBaskerville-Bold.ttf",
    "LibreBaskerville-Italic.ttf",
    "LibreBaskerville-Regular.ttf",
    "Lobster-Regular.ttf",
    "LobsterTwo-Bold.ttf",
    "LobsterTwo-BoldItalic.ttf",
    "LobsterTwo-Italic.ttf",
    "LobsterTwo-Regular.ttf",
    "Merriweather-Black.ttf",
    "Merriweather-BlackItalic.ttf",
    "Merriweather-Bold.ttf",
    "Merriweather-BoldItalic.ttf",
    "Merriweather-Italic.ttf",
    "Merriweather-Light.ttf",
    "Merriweather-LightItalic.ttf",
    "Merriweather-Regular.ttf",
    "MerriweatherSans-Italic-VariableFont_wght.ttf",
    "MerriweatherSans-VariableFont_wght.ttf",
    "NanumBrushScript-Regular.ttf",
    "Old-English-Text.ttf",
    "Pacifico-Regular.ttf",
    "PatrickHand-Regular.ttf",
    "PermanentMarker-Regular.ttf",
    "PlayfairDisplay-Italic-VariableFont_wght.ttf",
    "PlayfairDisplay-VariableFont_wght.ttf",
    "PlayfairDisplaySC-Black.ttf",
    "PlayfairDisplaySC-BlackItalic.ttf",
    "PlayfairDisplaySC-Bold.ttf",
    "PlayfairDisplaySC-BoldItalic.ttf",
    "PlayfairDisplaySC-Italic.ttf",
    "PlayfairDisplaySC-Regular.ttf",
    "Sacramento-Regular.ttf",
    "Satisfy-Regular.ttf",
    "Times-Sans.ttf",
    "UnifrakturCook-Bold.ttf",
    "WindSong-Medium.ttf",
    "WindSong-Regular.ttf"
], key=lambda s: s.lower())

# Calculating the maximum font name length for the Combobox
max_font_length = max(len(font) for font in FONT_OPTIONS) + 2

DEFAULT_CONFIG = {
    # Title Settings
    "TITLE_AREA_WIDTH_FACTOR": 0.8,
    "TITLE_MAX_FONT_SIZE": 120,
    "TITLE_MIN_FONT_SIZE": 30,
    "TITLE_LINE_SPACING": 1.2,
    "TITLE_TOP_MARGIN": 100,
    "TITLE_ZONE_PERCENT": 30,
    "TITLE_TEXT_COLOR": "(255, 255, 224)",
    "TITLE_VERTICAL_ALIGN": "top",
    
    # Volume (Subtitle) Settings
    "VOLUME_AREA_WIDTH_FACTOR": 0.8,
    "VOLUME_RATIO": 0.8,
    "VOLUME_MIN_FONT_SIZE": 50,
    "VOLUME_MAX_FONT_SIZE": 100,
    "VOLUME_LINE_SPACING": 1.2,
    "VOLUME_TOP_MARGIN": 10,
    "SUBTITLE_ZONE_PERCENT": 25,
    
    # Anchor & Authors Settings
    "ANCHOR_AREA_WIDTH_FACTOR": 0.8,
    "AUTHORS_AREA_WIDTH_FACTOR": 0.8,
    "ANCHOR_RATIO": 0.5,
    "ANCHOR_MIN_FONT_SIZE": 50,
    "ANCHOR_MAX_FONT_SIZE": 80,
    "AUTHOR_RATIO": 0.6,
    "AUTHOR_MIN_FONT_SIZE": 70,
    "AUTHOR_MAX_FONT_SIZE": 90,
    "ANCHOR_LINE_SPACING": 1.2,
    "AUTHOR_LINE_SPACING": 1.2,
    "AUTHOR_ZONE_PERCENT": 20,
    
    # Color Settings
    "TITLE_TEXT_COLOR": "(255, 255, 224)",
    "OTHER_TEXT_COLOR": "(255, 215, 0)",
    "BACKGROUND_COLOR": "(108, 37, 36)",
    
    # Additional Settings
    "LOGO_SIZE": "400,200",
    "COVER_WIDTH_CM": 15.2,
    "COVER_HEIGHT_CM": 21.72,
    "RESOLUTION": 140,
    "TITLE_FONT_NAME": "EuphoriaScript-Regular.ttf",
    "SECONDARY_FONT_NAME": "GreatVibes-Regular.ttf",
    "ALTERNATIVE_FONT": "arial.ttf"
}

CONFIG_FILE = "config.json"
def load_config():
    """Load configuration from file if it exists; otherwise, return default settings."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            for key, val in DEFAULT_CONFIG.items():
                if key not in cfg:
                    cfg[key] = val
            return cfg
        except Exception as e:
            print("Error loading configuration, using default settings:", e)
            return DEFAULT_CONFIG.copy()
    else:
        return DEFAULT_CONFIG.copy()

def save_config(cfg):
    """Save the configuration to a JSON file."""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)

def format_label(key):
    """Convert key from 'TITLE_AREA_WIDTH_FACTOR' to 'Title Area Width Factor'."""
    return key.replace("_", " ").title()

# Determining the order of keys grouped by topics
KEYS_ORDER = [
    # Title Settings
    "TITLE_AREA_WIDTH_FACTOR",
    "TITLE_MAX_FONT_SIZE",
    "TITLE_MIN_FONT_SIZE",
    "TITLE_LINE_SPACING",
    "TITLE_TOP_MARGIN",
    "TITLE_ZONE_PERCENT",
    "TITLE_TEXT_COLOR",
    "TITLE_VERTICAL_ALIGN",
    
    # Volume (Subtitle) Settings
    "VOLUME_AREA_WIDTH_FACTOR",
    "VOLUME_RATIO",
    "VOLUME_MIN_FONT_SIZE",
    "VOLUME_MAX_FONT_SIZE",
    "VOLUME_LINE_SPACING",
    "VOLUME_TOP_MARGIN",
    "SUBTITLE_ZONE_PERCENT",
    
    # Anchor & Authors Settings
    "ANCHOR_AREA_WIDTH_FACTOR",
    "AUTHORS_AREA_WIDTH_FACTOR",
    "ANCHOR_RATIO",
    "ANCHOR_MIN_FONT_SIZE",
    "ANCHOR_MAX_FONT_SIZE",
    "AUTHOR_RATIO",
    "AUTHOR_MIN_FONT_SIZE",
    "AUTHOR_MAX_FONT_SIZE",
    "ANCHOR_LINE_SPACING",
    "AUTHOR_LINE_SPACING",
    "AUTHOR_ZONE_PERCENT",
    
    # Color Settings
    "TITLE_TEXT_COLOR",
    "OTHER_TEXT_COLOR",
    "BACKGROUND_COLOR",
    
    # Additional Settings
    "LOGO_SIZE",
    "COVER_WIDTH_CM",
    "COVER_HEIGHT_CM",
    "RESOLUTION",
    "TITLE_FONT_NAME",
    "SECONDARY_FONT_NAME",
    "ALTERNATIVE_FONT"
]

class ConfigGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Cover Settings Configuration")
        self.config_data = load_config()
        self.config_vars = {}

        # Top label with the program version
        version_label = tk.Label(self, text="Covers Creator ver 1.3", font=("Arial", 14, "bold"))
        version_label.pack(pady=10)
        
        # Frame for placing settings
        options_frame = tk.Frame(self)
        options_frame.pack(padx=10, pady=10)
        
        total_keys = len(KEYS_ORDER)
        half = math.ceil(total_keys / 2)
        
        for idx, key in enumerate(KEYS_ORDER):
            col = 0 if idx < half else 2
            row = idx if idx < half else idx - half
            
            lbl = tk.Label(options_frame, text=format_label(key))
            lbl.grid(row=row, column=col, padx=5, pady=2, sticky="w")
            
            if key in ["TITLE_FONT_NAME", "SECONDARY_FONT_NAME", "ALTERNATIVE_FONT"]:
                var = tk.StringVar(value=str(self.config_data.get(key, DEFAULT_CONFIG[key])))
                opt = ttk.Combobox(options_frame, textvariable=var, values=FONT_OPTIONS, width=max_font_length)
                opt.grid(row=row, column=col+1, padx=5, pady=2, sticky="w")
            
            # For TITLE_VERTICAL_ALIGN, we keep an OptionMenu with fixed options.
            elif key == "TITLE_VERTICAL_ALIGN":
                var = tk.StringVar(value=str(self.config_data.get(key, DEFAULT_CONFIG[key])))
                opt = tk.OptionMenu(options_frame, var, "top", "center", "bottom")
                opt.config(width=10, anchor="w")
                opt.grid(row=row, column=col+1, padx=5, pady=2, sticky="w")
            else:
                var = tk.StringVar(value=str(self.config_data.get(key, DEFAULT_CONFIG[key])))
                ent = tk.Entry(options_frame, textvariable=var, width=20)
                ent.grid(row=row, column=col+1, padx=5, pady=2, sticky="w")
            self.config_vars[key] = var
        
        # Frame for buttons
        button_frame = tk.Frame(self)
        button_frame.pack(padx=10, pady=10, fill="x")
        
        reset_btn = tk.Button(button_frame, text="Reset To Defaults", command=self.reset_defaults)
        reset_btn.pack(side="left", expand=True, fill="x", padx=5, pady=10)
        
        run_btn = tk.Button(button_frame, text="Run Processing", command=self.on_run)
        run_btn.pack(side="left", expand=True, fill="x", padx=5, pady=10)
    
    def reset_defaults(self):
        """Reset all fields to the default settings."""
        for key, var in self.config_vars.items():
            var.set(str(DEFAULT_CONFIG[key]))
    
    def on_run(self):
        """Collect values, save configuration, and close the window."""
        cfg = {}
        for key, var in self.config_vars.items():
            val_str = var.get().strip()
            try:
                if key in ["BACKGROUND_COLOR", "TITLE_TEXT_COLOR", "OTHER_TEXT_COLOR", "LOGO_SIZE"]:
                    cfg[key] = val_str
                elif '.' in val_str:
                    cfg[key] = float(val_str)
                else:
                    cfg[key] = int(val_str)
            except ValueError:
                cfg[key] = val_str
        save_config(cfg)
        self.destroy()

if __name__ == "__main__":
    app = ConfigGUI()
    app.mainloop()
    sys.exit(0)
