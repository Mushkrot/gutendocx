# config.py v2.0
# -*- coding: utf-8 -*-

import tkinter as tk
from tkinter import messagebox
import json
import os
import sys

# Default configuration values
DEFAULT_CONFIG = {
    "TITLE_AREA_WIDTH_FACTOR": 0.8,     # Fraction of width available for the title
    "TITLE_MAX_FONT_SIZE": 120,         # Maximum font size for the title
    "TITLE_MIN_FONT_SIZE": 30,          # Minimum font size for the title
    "TITLE_LINE_SPACING": 1.2,          # Line spacing multiplier for the title
    "TITLE_TOP_MARGIN": 100,            # Top margin for the title

    "VOLUME_AREA_WIDTH_FACTOR": 0.8,    # Fraction of width available for the volume (subtitle)
    "VOLUME_RATIO": 0.8,                # Ratio of volume font size relative to the title font size
    "VOLUME_MIN_FONT_SIZE": 50,         # Minimum font size for the volume text
    "VOLUME_MAX_FONT_SIZE": 100,        # Maximum font size for the volume text
    "VOLUME_LINE_SPACING": 1.2,         # Line spacing multiplier for the volume text
    "VOLUME_TOP_MARGIN": 10,            # Top margin for the volume text

    "ANCHOR_AREA_WIDTH_FACTOR": 0.8,    # Fraction of width available for the anchor text
    "AUTHORS_AREA_WIDTH_FACTOR": 0.8,   # Fraction of width available for the authors text
    "ANCHOR_RATIO": 0.5,                # Ratio of anchor font size relative to the title font size
    "ANCHOR_MIN_FONT_SIZE": 50,         # Minimum font size for the anchor text
    "ANCHOR_MAX_FONT_SIZE": 80,         # Maximum font size for the anchor text
    "AUTHOR_RATIO": 0.6,                # Ratio of author font size relative to the title font size
    "AUTHOR_MIN_FONT_SIZE": 70,         # Minimum font size for the authors text
    "AUTHOR_MAX_FONT_SIZE": 90,         # Maximum font size for the authors text
    "ANCHOR_LINE_SPACING": 1.2,         # Line spacing multiplier for the anchor text
    "AUTHOR_LINE_SPACING": 1.2,         # Line spacing multiplier for the authors text
    "ZONE3_MARGIN": 10,                 # Vertical margin between anchor and authors
    "ALLOW_ZONE4_OVERLAP_RATIO": 0.5    # Fraction of Zone 4 height available for anchor+authors
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

class ConfigGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Cover Settings Configuration")
        self.config_data = load_config()  # Load saved settings or defaults
        self.config_vars = {}
        row = 0
        
        # Create input fields for each configuration variable
        for key, val in self.config_data.items():
            lbl = tk.Label(self, text=key)
            lbl.grid(row=row, column=0, padx=5, pady=2, sticky="w")
            var = tk.StringVar(value=str(val))
            ent = tk.Entry(self, textvariable=var, width=10)
            ent.grid(row=row, column=1, padx=5, pady=2)
            self.config_vars[key] = var
            row += 1

        # Button to reset settings to default values
        reset_btn = tk.Button(self, text="Reset to Defaults", command=self.reset_defaults)
        reset_btn.grid(row=row, column=0, padx=5, pady=10, sticky="ew")
        
        # Button to run processing with the current settings
        run_btn = tk.Button(self, text="Run Processing", command=self.on_run)
        run_btn.grid(row=row, column=1, padx=5, pady=10, sticky="ew")

    def reset_defaults(self):
        """Reset all fields to the default settings."""
        for key, var in self.config_vars.items():
            var.set(str(DEFAULT_CONFIG[key]))
        # No confirmation message displayed

    def on_run(self):
        """Collect values, save configuration, and close the window."""
        config = {}
        for key, var in self.config_vars.items():
            val_str = var.get()
            try:
                if '.' in val_str:
                    config[key] = float(val_str)
                else:
                    config[key] = int(val_str)
            except ValueError:
                try:
                    config[key] = float(val_str)
                except Exception as e:
                    messagebox.showerror("Error", f"Invalid value for {key}")
                    return
        save_config(config)
        # Do not show confirmation message; simply close the window
        self.destroy()

if __name__ == "__main__":
    app = ConfigGUI()
    app.mainloop()
    sys.exit(0)
