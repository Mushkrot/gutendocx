# config.py v2.5
# -*- coding: utf-8 -*-

import tkinter as tk
from tkinter import messagebox
import json
import os
import sys
import math

# List of available font files from the "fonts" folder
FONT_OPTIONS = [
    "AlexBrush-Regular.ttf",
    "Allura-Regular.ttf",
    "AmaticSC-Regular.ttf",
    "ArchitectsDaughter-Regular.ttf",
    "Arial.ttf",
    "Courier-New.ttf",
    "DancingScript-VariableFont_wght.ttf",
    "EuphoriaScript-Regular.ttf",
    "Geneva.ttf",
    "GrandHotel-Regular.ttf",
    "GreatVibes-Regular.ttf",
    "Helvetica.ttf",
    "IndieFlower-Regular.ttf",
    "Kalam-Bold.ttf",
    "Kalam-Light.ttf",
    "Kalam-Regular.ttf",
    "KaushanScript-Regular.ttf",
    "Lobster-Regular.ttf",
    "LobsterTwo-Bold.ttf",
    "LobsterTwo-BoldItalic.ttf",
    "LobsterTwo-Italic.ttf",
    "LobsterTwo-Regular.ttf",
    "NanumBrushScript-Regular.ttf",
    "Pacifico-Regular.ttf",
    "PatrickHand-Regular.ttf",
    "PermanentMarker-Regular.ttf",
    "Sacramento-Regular.ttf",
    "Satisfy-Regular.ttf",
    "Times-Sans.ttf",
    "WindSong-Medium.ttf",
    "WindSong-Regular.ttf"
]

# Calculate maximum length among font names for OptionMenu width
max_font_length = max(len(font) for font in FONT_OPTIONS) + 2

# Default configuration values with additional color settings.
# Colors are stored as strings representing tuples.
DEFAULT_CONFIG = {
    # Title Settings
    "TITLE_AREA_WIDTH_FACTOR": 0.8,                     # Fraction of cover width for title
    "TITLE_MAX_FONT_SIZE": 120,                         # Maximum title font size
    "TITLE_MIN_FONT_SIZE": 30,                          # Minimum title font size
    "TITLE_LINE_SPACING": 1.2,                          # Title line spacing multiplier
    "TITLE_TOP_MARGIN": 100,                            # Top margin for title
    # Volume (Subtitle) Settings
    "VOLUME_AREA_WIDTH_FACTOR": 0.8,                    # Fraction of cover width for subtitle
    "VOLUME_RATIO": 0.8,                                # Ratio of subtitle font size to title font size
    "VOLUME_MIN_FONT_SIZE": 50,                         # Minimum subtitle font size
    "VOLUME_MAX_FONT_SIZE": 100,                        # Maximum subtitle font size
    "VOLUME_LINE_SPACING": 1.2,                         # Subtitle line spacing multiplier
    "VOLUME_TOP_MARGIN": 10,                            # Top margin for subtitle
    # Anchor & Authors Settings
    "ANCHOR_AREA_WIDTH_FACTOR": 0.8,                    # Fraction of cover width for anchor text
    "AUTHORS_AREA_WIDTH_FACTOR": 0.8,                   # Fraction of cover width for authors text
    "ANCHOR_RATIO": 0.5,                                # Ratio of anchor font size to title font size
    "ANCHOR_MIN_FONT_SIZE": 50,                         # Minimum anchor font size
    "ANCHOR_MAX_FONT_SIZE": 80,                         # Maximum anchor font size
    "AUTHOR_RATIO": 0.6,                                # Ratio of authors font size to title font size
    "AUTHOR_MIN_FONT_SIZE": 70,                         # Minimum authors font size
    "AUTHOR_MAX_FONT_SIZE": 90,                         # Maximum authors font size
    "ANCHOR_LINE_SPACING": 1.2,                         # Anchor line spacing multiplier
    "AUTHOR_LINE_SPACING": 1.2,                         # Authors line spacing multiplier
    "ZONE3_MARGIN": 10,                                 # Vertical margin between anchor and authors
    "ALLOW_ZONE4_OVERLAP_RATIO": 0.5,                   # Fraction of Zone 4 height available if needed
    # Color Settings (grouped together)
    "TITLE_TEXT_COLOR": "(255, 255, 224)",              # Title text color (light yellow)
    "OTHER_TEXT_COLOR": "(255, 215, 0)",                # Other text color (gold)
    "BACKGROUND_COLOR": "(108, 37, 36)",                # Background color (RGB)
    # Additional Settings
    "LOGO_SIZE": "400,200",                             # Logo size as "width,height"
    "COVER_WIDTH_CM": 15.2,                             # Cover width in centimeters
    "COVER_HEIGHT_CM": 21.72,                           # Cover height in centimeters
    "RESOLUTION": 140,                                  # Image resolution (DPI scale factor)
    "TITLE_FONT_NAME": "EuphoriaScript-Regular.ttf",    # Title font name
    "SECONDARY_FONT_NAME": "GreatVibes-Regular.ttf",    # Secondary font name
    "ALTERNATIVE_FONT": "arial.ttf",                    # Fallback font name
    "ZONE_COUNT": 4                                     # Number of zones in cover layout
}

CONFIG_FILE = "config.json"

def load_config():
    """Load configuration from file if it exists; otherwise, return default settings."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            # Ensure all default keys are present
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

# Define the order of keys, grouped by theme.
KEYS_ORDER = [
    # Title Settings (except color)
    "TITLE_AREA_WIDTH_FACTOR",
    "TITLE_MAX_FONT_SIZE",
    "TITLE_MIN_FONT_SIZE",
    "TITLE_LINE_SPACING",
    "TITLE_TOP_MARGIN",
    # Volume (Subtitle) Settings
    "VOLUME_AREA_WIDTH_FACTOR",
    "VOLUME_RATIO",
    "VOLUME_MIN_FONT_SIZE",
    "VOLUME_MAX_FONT_SIZE",
    "VOLUME_LINE_SPACING",
    "VOLUME_TOP_MARGIN",
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
    "ZONE3_MARGIN",
    "ALLOW_ZONE4_OVERLAP_RATIO",
    # Color Settings (grouped together)
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
    "ALTERNATIVE_FONT",
    "ZONE_COUNT"
]

class ConfigGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Cover Settings Configuration")
        self.config_data = load_config()
        self.config_vars = {}
        
        # Arrange the options in two columns for a neat layout
        total_keys = len(KEYS_ORDER)
        half = math.ceil(total_keys / 2)
        
        for idx, key in enumerate(KEYS_ORDER):
            col = 0 if idx < half else 2
            row = idx if idx < half else idx - half
            
            # Use formatted label text
            lbl = tk.Label(self, text=format_label(key))
            lbl.grid(row=row, column=col, padx=5, pady=2, sticky="w")
            
            # For font selection keys, use an OptionMenu with left-aligned text
            if key in ["TITLE_FONT_NAME", "SECONDARY_FONT_NAME", "ALTERNATIVE_FONT"]:
                var = tk.StringVar(value=str(self.config_data.get(key, DEFAULT_CONFIG[key])))
                opt = tk.OptionMenu(self, var, *FONT_OPTIONS)
                opt.config(width=max_font_length, anchor="w")  # left-align the TITLE value
                opt.grid(row=row, column=col+1, padx=5, pady=2, sticky="w")
            else:
                var = tk.StringVar(value=str(self.config_data.get(key, DEFAULT_CONFIG[key])))
                ent = tk.Entry(self, textvariable=var, width=20)
                ent.grid(row=row, column=col+1, padx=5, pady=2, sticky="w")
            self.config_vars[key] = var
        
        btn_row = max(half, total_keys - half)
        reset_btn = tk.Button(self, text="Reset To Defaults", command=self.reset_defaults)
        reset_btn.grid(row=btn_row, column=0, columnspan=2, padx=5, pady=10, sticky="ew")
        
        run_btn = tk.Button(self, text="Run Processing", command=self.on_run)
        run_btn.grid(row=btn_row, column=2, columnspan=2, padx=5, pady=10, sticky="ew")
    
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
                # For color and tuple-like settings, keep as string.
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
