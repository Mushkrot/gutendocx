# config.py v2.3
# -*- coding: utf-8 -*-

import tkinter as tk
from tkinter import messagebox
import json
import os
import sys
import math

# List of available font files (from the "fonts" folder)
FONT_OPTIONS = [
    "AlexBrush-Regular.ttf",
    "Allura-Regular.ttf",
    "AmaticSC-Regular.ttf",
    "ArchitectsDaughter-Regular.ttf",
    "DancingScript-VariableFont_wght.ttf",
    "EuphoriaScript-Regular.ttf",
    "GrandHotel-Regular.ttf",
    "GreatVibes-Regular.ttf",
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
    "WindSong-Medium.ttf",
    "WindSong-Regular.ttf"
]

# Default configuration values, extended with color parameters
DEFAULT_CONFIG = {
    # Title settings
    "TITLE_AREA_WIDTH_FACTOR": 0.8,     
    "TITLE_MAX_FONT_SIZE": 120,         
    "TITLE_MIN_FONT_SIZE": 30,          
    "TITLE_LINE_SPACING": 1.2,          
    "TITLE_TOP_MARGIN": 100,            
    "TITLE_TEXT_COLOR": "(255, 255, 224)",  # Light yellow
    
    # Volume (subtitle) settings
    "VOLUME_AREA_WIDTH_FACTOR": 0.8,    
    "VOLUME_RATIO": 0.8,                
    "VOLUME_MIN_FONT_SIZE": 50,         
    "VOLUME_MAX_FONT_SIZE": 100,        
    "VOLUME_LINE_SPACING": 1.2,         
    "VOLUME_TOP_MARGIN": 10,            
    
    # Anchor & Authors settings
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
    "ZONE3_MARGIN": 10,                 
    "ALLOW_ZONE4_OVERLAP_RATIO": 0.5,   
    "OTHER_TEXT_COLOR": "(255, 215, 0)",    # Gold
    
    # Additional settings
    "LOGO_SIZE": "400,200",                             
    "COVER_WIDTH_CM": 15.2,                             
    "COVER_HEIGHT_CM": 21.72,                           
    "RESOLUTION": 140,                                  
    "SELECTED_FONT_NAME": "EuphoriaScript-Regular.ttf", 
    "SECOND_FONT_NAME": "GreatVibes-Regular.ttf",       
    "ALTERNATIVE_FONT": "arial.ttf",                    
    "ZONE_COUNT": 4,                                    
    "BACKGROUND_COLOR": "(108, 37, 36)"                 
}

CONFIG_FILE = "config.json"

def load_config():
    """Load configuration from file if it exists; otherwise, return default settings."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
            # Ensure all default keys are present
            for key, val in DEFAULT_CONFIG.items():
                if key not in config:
                    config[key] = val
            return config
        except Exception as e:
            print("Error loading configuration, using default settings:", e)
            return DEFAULT_CONFIG.copy()
    else:
        return DEFAULT_CONFIG.copy()

def save_config(config):
    """Save the configuration to a file."""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

# Define explicit order for configuration keys to group them logically
KEYS_ORDER = [
    # Title settings
    "TITLE_AREA_WIDTH_FACTOR",
    "TITLE_MAX_FONT_SIZE",
    "TITLE_MIN_FONT_SIZE",
    "TITLE_LINE_SPACING",
    "TITLE_TOP_MARGIN",
    "TITLE_TEXT_COLOR",
    # Volume settings
    "VOLUME_AREA_WIDTH_FACTOR",
    "VOLUME_RATIO",
    "VOLUME_MIN_FONT_SIZE",
    "VOLUME_MAX_FONT_SIZE",
    "VOLUME_LINE_SPACING",
    "VOLUME_TOP_MARGIN",
    # Anchor & Authors settings
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
    "OTHER_TEXT_COLOR",
    # Additional settings
    "LOGO_SIZE",
    "COVER_WIDTH_CM",
    "COVER_HEIGHT_CM",
    "RESOLUTION",
    "SELECTED_FONT_NAME",
    "SECOND_FONT_NAME",
    "ALTERNATIVE_FONT",
    "ZONE_COUNT",
    "BACKGROUND_COLOR"
]

class ConfigGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Cover Settings Configuration")
        self.config_data = load_config()  # Load saved settings or defaults
        self.config_vars = {}
        
        # We'll arrange the options in two columns for a better layout.
        # Calculate half the number of keys.
        total_keys = len(KEYS_ORDER)
        half = math.ceil(total_keys / 2)
        
        # Create labels and input widgets in two columns.
        for idx, key in enumerate(KEYS_ORDER):
            col = 0 if idx < half else 2
            row = idx if idx < half else idx - half

            lbl = tk.Label(self, text=key)
            lbl.grid(row=row, column=col, padx=5, pady=2, sticky="w")
            
            # For font selection keys use OptionMenu
            if key in ["SELECTED_FONT_NAME", "SECOND_FONT_NAME", "ALTERNATIVE_FONT"]:
                var = tk.StringVar(value=str(self.config_data.get(key, DEFAULT_CONFIG[key])))
                opt = tk.OptionMenu(self, var, *FONT_OPTIONS)
                opt.config(width=20)
                opt.grid(row=row, column=col+1, padx=5, pady=2, sticky="w")
            else:
                var = tk.StringVar(value=str(self.config_data.get(key, DEFAULT_CONFIG[key])))
                ent = tk.Entry(self, textvariable=var, width=20)
                ent.grid(row=row, column=col+1, padx=5, pady=2, sticky="w")
            self.config_vars[key] = var
        
        btn_row = max(half, total_keys - half)
        reset_btn = tk.Button(self, text="Reset to Defaults", command=self.reset_defaults)
        reset_btn.grid(row=btn_row, column=0, columnspan=2, padx=5, pady=10, sticky="ew")
        
        run_btn = tk.Button(self, text="Run Processing", command=self.on_run)
        run_btn.grid(row=btn_row, column=2, columnspan=2, padx=5, pady=10, sticky="ew")
    
    def reset_defaults(self):
        """Reset all fields to the default settings."""
        for key, var in self.config_vars.items():
            var.set(str(DEFAULT_CONFIG[key]))
    
    def on_run(self):
        """Collect values, save configuration, and close the window."""
        config = {}
        for key, var in self.config_vars.items():
            val_str = var.get().strip()
            try:
                # For color and tuple-like values, keep as string.
                if key in ["BACKGROUND_COLOR", "TITLE_TEXT_COLOR", "OTHER_TEXT_COLOR", "LOGO_SIZE"]:
                    config[key] = val_str
                elif '.' in val_str:
                    config[key] = float(val_str)
                else:
                    config[key] = int(val_str)
            except ValueError:
                config[key] = val_str
        save_config(config)
        self.destroy()

if __name__ == "__main__":
    app = ConfigGUI()
    app.mainloop()
    sys.exit(0)
