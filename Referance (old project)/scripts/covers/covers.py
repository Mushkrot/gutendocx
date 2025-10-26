# covers.py v3.1 - Title vertical alignment
# -*- coding: utf-8 -*-

import sys
import os
import subprocess
import json
import ast

# Determine working directory (for config.json)
SCRIPT_DIR = os.path.abspath(".")

# Determine executable path
if getattr(sys, 'frozen', False):
    exe_path = sys.argv[0]
else:
    exe_path = sys.executable

# If launched without "--config", run configuration mode in a new console
if "--config" not in sys.argv:
    subprocess.run([exe_path, "--config"], creationflags=subprocess.CREATE_NEW_CONSOLE)

# If launched with "--config", run the configuration window and exit
if "--config" in sys.argv:
    from config import ConfigGUI
    app = ConfigGUI()
    app.mainloop()
    sys.exit(0)

# If config.json does not exist, create it with default settings
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")
if not os.path.exists(CONFIG_FILE):
    default_config = {
        "TITLE_AREA_WIDTH_FACTOR": 0.8,
        "TITLE_MAX_FONT_SIZE": 120,
        "TITLE_MIN_FONT_SIZE": 30,
        "TITLE_LINE_SPACING": 1.2,
        "TITLE_TOP_MARGIN": 100,
        "VOLUME_AREA_WIDTH_FACTOR": 0.8,
        "VOLUME_RATIO": 0.8,
        "VOLUME_MIN_FONT_SIZE": 50,
        "VOLUME_MAX_FONT_SIZE": 100,
        "VOLUME_LINE_SPACING": 1.2,
        "VOLUME_TOP_MARGIN": 10,
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
        "ANCHOR_MARGIN": 10,
        "LOGO_SIZE": "400,200",
        "COVER_WIDTH_CM": 15.2,
        "COVER_HEIGHT_CM": 21.72,
        "RESOLUTION": 140,
        "TITLE_FONT_NAME": "EuphoriaScript-Regular.ttf",
        "SECONDARY_FONT_NAME": "GreatVibes-Regular.ttf",
        "ALTERNATIVE_FONT": "arial.ttf",
        "TITLE_ZONE_PERCENT": 30,
        "SUBTITLE_ZONE_PERCENT": 25,
        "AUTHOR_ZONE_PERCENT": 20,
        "BACKGROUND_COLOR": "(108, 37, 36)",
        "TITLE_TEXT_COLOR": "(255, 255, 224)",
        "OTHER_TEXT_COLOR": "(255, 215, 0)"
    }
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(default_config, f, indent=4, ensure_ascii=False)

# Load configuration from config.json
with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    config = json.load(f)

# ------------------ Main Code ------------------

import re
import unicodedata
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps
import pandas as pd
import logging

# Paths
SCRIPT_DIR = Path(__file__).resolve().parent
FONTS_FOLDER = SCRIPT_DIR / "fonts"

BACKGROUND_IMAGE_PATH = None  # To be set later
LOGO_PATH = None              # To be set later

# Logo parameters
logo_size_str = config.get("LOGO_SIZE", "400,200")
LOGO_SIZE = tuple(map(int, logo_size_str.split(",")))

# Cover dimensions (in centimeters)
COVER_WIDTH_CM = config.get("COVER_WIDTH_CM", 15.2)
COVER_HEIGHT_CM = config.get("COVER_HEIGHT_CM", 21.72)

# Resolution and image dimensions
RESOLUTION = config.get("RESOLUTION", 140)
IMAGE_WIDTH = int(COVER_WIDTH_CM / 2.54 * RESOLUTION)
IMAGE_HEIGHT = int(COVER_HEIGHT_CM / 2.54 * RESOLUTION)

# Fonts
TITLE_FONT_NAME = config.get("TITLE_FONT_NAME", "EuphoriaScript-Regular.ttf")
FONT_FILE = FONTS_FOLDER / TITLE_FONT_NAME
SECONDARY_FONT_NAME = config.get("SECONDARY_FONT_NAME", "GreatVibes-Regular.ttf")
SECONDARY_FONT_FILE = FONTS_FOLDER / SECONDARY_FONT_NAME
ALTERNATIVE_FONT = config.get("ALTERNATIVE_FONT", "arial.ttf")

# Zone splitting percentages (new parameters)
TITLE_ZONE_PERCENT = config.get("TITLE_ZONE_PERCENT", 30)       # e.g., 30%
SUBTITLE_ZONE_PERCENT = config.get("SUBTITLE_ZONE_PERCENT", 25)   # e.g., 25%
AUTHOR_ZONE_PERCENT = config.get("AUTHOR_ZONE_PERCENT", 20)       # e.g., 20%
LOGO_ZONE_PERCENT = 100 - (TITLE_ZONE_PERCENT + SUBTITLE_ZONE_PERCENT + AUTHOR_ZONE_PERCENT)  # remaining

zone1_height = IMAGE_HEIGHT * (TITLE_ZONE_PERCENT / 100.0)
zone2_height = IMAGE_HEIGHT * (SUBTITLE_ZONE_PERCENT / 100.0)
zone3_height = IMAGE_HEIGHT * (AUTHOR_ZONE_PERCENT / 100.0)
zone4_height = IMAGE_HEIGHT * (LOGO_ZONE_PERCENT / 100.0)

zone1_top = 0
zone2_top = zone1_top + zone1_height
zone3_top = zone2_top + zone2_height
zone4_top = zone3_top + zone3_height

# Dynamic text parameters
TITLE_AREA_WIDTH_FACTOR = config.get("TITLE_AREA_WIDTH_FACTOR", 0.8)
TITLE_MAX_FONT_SIZE = config.get("TITLE_MAX_FONT_SIZE", 120)
TITLE_MIN_FONT_SIZE = config.get("TITLE_MIN_FONT_SIZE", 30)
TITLE_LINE_SPACING = config.get("TITLE_LINE_SPACING", 1.2)
TITLE_TOP_MARGIN = config.get("TITLE_TOP_MARGIN", 100)
# New parameter: Vertical alignment for title ("top", "center", "bottom")
TITLE_VERTICAL_ALIGN = config.get("TITLE_VERTICAL_ALIGN", "top")

VOLUME_AREA_WIDTH_FACTOR = config.get("VOLUME_AREA_WIDTH_FACTOR", 0.8)
VOLUME_RATIO = config.get("VOLUME_RATIO", 0.8)
VOLUME_MIN_FONT_SIZE = config.get("VOLUME_MIN_FONT_SIZE", 50)
VOLUME_MAX_FONT_SIZE = config.get("VOLUME_MAX_FONT_SIZE", 100)
VOLUME_LINE_SPACING = config.get("VOLUME_LINE_SPACING", 1.2)
VOLUME_TOP_MARGIN = config.get("VOLUME_TOP_MARGIN", 10)

ANCHOR_AREA_WIDTH_FACTOR = config.get("ANCHOR_AREA_WIDTH_FACTOR", 0.8)
AUTHORS_AREA_WIDTH_FACTOR = config.get("AUTHORS_AREA_WIDTH_FACTOR", 0.8)
ANCHOR_RATIO = config.get("ANCHOR_RATIO", 0.5)
ANCHOR_MIN_FONT_SIZE = config.get("ANCHOR_MIN_FONT_SIZE", 50)
ANCHOR_MAX_FONT_SIZE = config.get("ANCHOR_MAX_FONT_SIZE", 80)
AUTHOR_RATIO = config.get("AUTHOR_RATIO", 0.6)
AUTHOR_MIN_FONT_SIZE = config.get("AUTHOR_MIN_FONT_SIZE", 70)
AUTHOR_MAX_FONT_SIZE = config.get("AUTHOR_MAX_FONT_SIZE", 90)
ANCHOR_LINE_SPACING = config.get("ANCHOR_LINE_SPACING", 1.2)
AUTHOR_LINE_SPACING = config.get("AUTHOR_LINE_SPACING", 1.2)
ZONE3_MARGIN = config.get("ZONE3_MARGIN", 10)

# Colors (parse string to tuple)
BACKGROUND_COLOR = config.get("BACKGROUND_COLOR", "(108, 37, 36)")
if isinstance(BACKGROUND_COLOR, str):
    BACKGROUND_COLOR = ast.literal_eval(BACKGROUND_COLOR)
TITLE_TEXT_COLOR = config.get("TITLE_TEXT_COLOR", "(255, 255, 224)")
if isinstance(TITLE_TEXT_COLOR, str):
    TITLE_TEXT_COLOR = ast.literal_eval(TITLE_TEXT_COLOR)
OTHER_TEXT_COLOR = config.get("OTHER_TEXT_COLOR", "(255, 215, 0)")
if isinstance(OTHER_TEXT_COLOR, str):
    OTHER_TEXT_COLOR = ast.literal_eval(OTHER_TEXT_COLOR)

COLUMN_MAPPING = {
    "ISBN": 0,
    "Author": 1,
    "Title": 2,
    "Volume": 3,
    "File_Code": 7,
    "Ancor": 8
}

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("covers.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

# ---------------- Helper Functions ----------------
def clean_text(text):
    if pd.isna(text):
        return ""
    if isinstance(text, (float, int)):
        text = str(int(text)) if text.is_integer() else str(text)
    else:
        text = str(text)
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[^\w\s\-.,;:!?]", "", text)
    return text.strip()

def format_authors(authors):
    if not authors or pd.isna(authors):
        return []
    authors_list = [clean_text(a) for a in str(authors).split(";")]
    formatted = []
    for author in authors_list:
        parts = [p.strip() for p in author.split(",")]
        if len(parts) == 2:
            formatted.append(f"{parts[1]} {parts[0]}")
        else:
            formatted.append(author)
    return formatted[:2]

def split_volume_by_comma(volume_text):
    if not volume_text:
        return []
    parts = volume_text.split(",", 1)
    if len(parts) > 1:
        return [parts[0].strip(), parts[1].strip()]
    else:
        return [volume_text]

def font_measure_text(text, font):
    try:
        return font.getlength(text)
    except AttributeError:
        try:
            bbox = font.getbbox(text)
            return bbox[2] - bbox[0]
        except AttributeError:
            from PIL import ImageDraw
            dummy = Image.new("RGB", (1, 1))
            draw = ImageDraw.Draw(dummy)
            width, _ = draw.textsize(text, font=font)
            return width

def wrap_text(text, font, max_width):
    lines = []
    words = text.split()
    current = []
    for word in words:
        test_line = " ".join(current + [word])
        if font_measure_text(test_line, font) <= max_width:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return lines

def find_optimal_font_size_for_text(text, area_width, area_height, min_font, max_font, font_loader, line_spacing):
    if not text:
        return min_font, [], 0
    optimal = min_font
    best_lines = []
    best_height = 0
    low = min_font
    high = max_font
    while low <= high:
        mid = (low + high) // 2
        font = font_loader(mid)
        lines = wrap_text(text, font, area_width)
        total_height = len(lines) * mid * line_spacing
        if total_height <= area_height:
            optimal = mid
            best_lines = lines
            best_height = total_height
            low = mid + 1
        else:
            high = mid - 1
    return optimal, best_lines, best_height

def find_common_optimal_font_size_for_texts(texts, area_width, available_height, min_font, max_font, font_loader, line_spacing, inter_text_margin=0):
    if not texts:
        return min_font, [[] for _ in texts], 0
    optimal = min_font
    best_wrapped = [[] for _ in texts]
    best_total = 0
    low = min_font
    high = max_font
    while low <= high:
        mid = (low + high) // 2
        font = font_loader(mid)
        total = 0
        wrapped_all = []
        for text in texts:
            lines = wrap_text(text, font, area_width)
            total += len(lines) * mid * line_spacing
            wrapped_all.append(lines)
        total += inter_text_margin * (len(texts) - 1)
        if total <= available_height:
            optimal = mid
            best_wrapped = wrapped_all
            best_total = total
            low = mid + 1
        else:
            high = mid - 1
    return optimal, best_wrapped, best_total

def apply_background(img):
    if BACKGROUND_IMAGE_PATH and os.path.exists(BACKGROUND_IMAGE_PATH):
        try:
            background = Image.open(BACKGROUND_IMAGE_PATH).convert("RGBA")
            background = background.resize((IMAGE_WIDTH, IMAGE_HEIGHT))
            img = Image.alpha_composite(img, background)
        except Exception as e:
            logging.error(f"Error loading background: {e}")
    return img

def apply_logo(img):
    if LOGO_PATH and os.path.exists(LOGO_PATH):
        try:
            logo = Image.open(LOGO_PATH).convert("RGBA")
            logo = logo.resize(LOGO_SIZE)
            logo_x = (IMAGE_WIDTH - LOGO_SIZE[0]) // 2
            logo_y = IMAGE_HEIGHT - LOGO_SIZE[1] - 100
            img.paste(logo, (logo_x, logo_y), logo)
        except Exception as e:
            logging.error(f"Error loading logo: {e}")
    return img

def load_font(size, primary=True):
    from PIL import ImageFont
    try:
        if primary:
            return ImageFont.truetype(str(FONT_FILE), size)
        else:
            return ImageFont.truetype(str(SECONDARY_FONT_FILE), size)
    except Exception as e:
        logging.warning(f"Could not load font, using fallback: {e}")
        return ImageFont.truetype(ALTERNATIVE_FONT, size)

def create_image(data, output_path):
    try:
        img = Image.new("RGBA", (IMAGE_WIDTH, IMAGE_HEIGHT), BACKGROUND_COLOR + (255,))
        img = apply_background(img)
        draw = ImageDraw.Draw(img)
        
        # Zone boundaries based on percentages
        zone1_top = 0
        zone1_height = IMAGE_HEIGHT * (TITLE_ZONE_PERCENT / 100.0)
        zone2_top = zone1_top + zone1_height
        zone2_height = IMAGE_HEIGHT * (SUBTITLE_ZONE_PERCENT / 100.0)
        zone3_top = zone2_top + zone2_height
        zone3_height = IMAGE_HEIGHT * (AUTHOR_ZONE_PERCENT / 100.0)
        zone4_top = zone3_top + zone3_height
        zone4_height = IMAGE_HEIGHT * (LOGO_ZONE_PERCENT / 100.0)
        
        # Zone 1: Title (use TITLE_TEXT_COLOR)
        title_area_width = IMAGE_WIDTH * TITLE_AREA_WIDTH_FACTOR
        title_area_height = zone1_height - TITLE_TOP_MARGIN
        title_font_size, title_lines, title_total_height = find_optimal_font_size_for_text(
            data["title"], title_area_width, title_area_height,
            TITLE_MIN_FONT_SIZE, TITLE_MAX_FONT_SIZE,
            lambda s: load_font(s, primary=True), TITLE_LINE_SPACING
        )
        title_font = load_font(title_font_size, primary=True)
        # New logic for vertical alignment of title
        if TITLE_VERTICAL_ALIGN == "top":
            title_y = zone1_top + TITLE_TOP_MARGIN
        elif TITLE_VERTICAL_ALIGN == "center":
            title_y = zone1_top + TITLE_TOP_MARGIN + (title_area_height - title_total_height) / 2
        elif TITLE_VERTICAL_ALIGN == "bottom":
            title_y = zone1_top + TITLE_TOP_MARGIN + (title_area_height - title_total_height)
        else:
            title_y = zone1_top + TITLE_TOP_MARGIN + (title_area_height - title_total_height)
        for line in title_lines:
            text_width = font_measure_text(line, title_font)
            x = (IMAGE_WIDTH - text_width) / 2
            draw.text((x, title_y), line, font=title_font, fill=TITLE_TEXT_COLOR)
            title_y += title_font_size * TITLE_LINE_SPACING
        
        # Zone 2: Volume (Subtitle) (use OTHER_TEXT_COLOR)
        volume_text = clean_text(data.get("volume", ""))
        volume_parts = split_volume_by_comma(volume_text)
        if volume_parts:
            volume_area_width = IMAGE_WIDTH * VOLUME_AREA_WIDTH_FACTOR
            volume_candidate = int(title_font_size * VOLUME_RATIO)
            volume_candidate = max(VOLUME_MIN_FONT_SIZE, min(volume_candidate, VOLUME_MAX_FONT_SIZE))
            volume_area_height = zone2_height - VOLUME_TOP_MARGIN
            vol_font_size, vol_wrapped, vol_total_height = find_common_optimal_font_size_for_texts(
                volume_parts, volume_area_width, volume_area_height,
                VOLUME_MIN_FONT_SIZE, volume_candidate,
                lambda s: load_font(s, primary=False), VOLUME_LINE_SPACING
            )
            volume_font = load_font(vol_font_size, primary=False)
            volume_y = zone2_top + VOLUME_TOP_MARGIN + (volume_area_height - vol_total_height) / 2
            for block in vol_wrapped:
                for line in block:
                    text_width = font_measure_text(line, volume_font)
                    x = (IMAGE_WIDTH - text_width) / 2
                    draw.text((x, volume_y), line, font=volume_font, fill=OTHER_TEXT_COLOR)
                    volume_y += vol_font_size * VOLUME_LINE_SPACING
        
        # Zone 3: Anchor and Authors (use OTHER_TEXT_COLOR)
        anchor_text = clean_text(data.get("anchor", ""))
        authors_list = data.get("authors", [])
        
        anchor_candidate = int(title_font_size * ANCHOR_RATIO)
        anchor_candidate = max(ANCHOR_MIN_FONT_SIZE, min(anchor_candidate, ANCHOR_MAX_FONT_SIZE))
        anchor_font_size, anchor_lines, anchor_total_height = find_optimal_font_size_for_text(
            anchor_text,
            IMAGE_WIDTH * ANCHOR_AREA_WIDTH_FACTOR, zone3_height,
            ANCHOR_MIN_FONT_SIZE, anchor_candidate,
            lambda s: load_font(s, primary=False), ANCHOR_LINE_SPACING
        )
        anchor_font = load_font(anchor_font_size, primary=False)
        
        authors_area_width = IMAGE_WIDTH * AUTHORS_AREA_WIDTH_FACTOR
        authors_candidate = int(title_font_size * AUTHOR_RATIO)
        authors_candidate = max(AUTHOR_MIN_FONT_SIZE, min(authors_candidate, AUTHOR_MAX_FONT_SIZE))
        available_for_authors = zone3_height - anchor_total_height - ZONE3_MARGIN
        if available_for_authors < 0:
            available_for_authors = 0
        
        authors_wrapped = []
        authors_total_height = 0
        if authors_list and available_for_authors > 0:
            author_font_size, authors_wrapped, authors_total_height = find_common_optimal_font_size_for_texts(
                authors_list, authors_area_width, available_for_authors,
                AUTHOR_MIN_FONT_SIZE, authors_candidate,
                lambda s: load_font(s, primary=False), AUTHOR_LINE_SPACING, inter_text_margin=ZONE3_MARGIN
            )
            author_font = load_font(author_font_size, primary=False)
        else:
            author_font_size = AUTHOR_MIN_FONT_SIZE
            author_font = load_font(author_font_size, primary=False)
        
        anchor_y = zone3_top
        for line in anchor_lines:
            text_width = font_measure_text(line, anchor_font)
            x = (IMAGE_WIDTH - text_width) / 2
            draw.text((x, anchor_y), line, font=anchor_font, fill=OTHER_TEXT_COLOR)
            anchor_y += anchor_font.size * ANCHOR_LINE_SPACING
        
        authors_y = anchor_y + ZONE3_MARGIN
        for block in authors_wrapped:
            for line in block:
                text_width = font_measure_text(line, author_font)
                x = (IMAGE_WIDTH - text_width) / 2
                draw.text((x, authors_y), line, font=author_font, fill=OTHER_TEXT_COLOR)
                authors_y += author_font.size * AUTHOR_LINE_SPACING
            authors_y += ZONE3_MARGIN
        
        # Zone 4: (Optional: logo) - not used in this version
        # img = apply_logo(img)
        
        img.convert("RGB").save(output_path, "JPEG", quality=95, dpi=(RESOLUTION, RESOLUTION))
        return True
    except Exception as e:
        logging.error(f"Error creating image: {e}")
        return False

def process_excel_file(file_path):
    try:
        df = pd.read_excel(
            file_path,
            engine="openpyxl",
            header=None,
            usecols=list(COLUMN_MAPPING.values()),
            names=list(COLUMN_MAPPING.keys()),
            skiprows=0,
            dtype={col: str for col in COLUMN_MAPPING.keys()}
        )
        logging.info(f"Number of rows read: {len(df)}")
        for index, row in df.iterrows():
            try:
                data = {
                    "title": clean_text(row.get("Title")),
                    "authors": format_authors(row.get("Author")),
                    "anchor": clean_text(row.get("Ancor")),
                    "volume": clean_text(row.get("Volume"))
                }
                isbn = clean_text(row.get("ISBN"))
                file_code = clean_text(row.get("File_Code"))
                if isbn:
                    base_name = isbn
                elif file_code:
                    base_name = file_code
                else:
                    base_name = f"Untitled_{index + 1}"
                base_name = re.sub(r"[^\w\-_.]", "_", base_name)
                file_name = f"{base_name}.jpg"
                output_path = OUTPUT_FOLDER / file_name
                counter = 1
                while output_path.exists():
                    file_name = f"{base_name}_{counter}.jpg"
                    output_path = OUTPUT_FOLDER / file_name
                    counter += 1
                if create_image(data, output_path):
                    logging.info(f"Cover created: {file_name}")
                else:
                    logging.error(f"Failed to create cover for row {index + 1}")
            except Exception as e:
                logging.error(f"Error in row {index + 1}: {e}")
    except Exception as e:
        logging.error(f"Error reading file {file_path}: {e}")

if __name__ == "__main__":
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    excel_file = filedialog.askopenfilename(
        title="Select Excel file for processing",
        filetypes=[("Excel files", "*.xlsx")]
    )
    if not excel_file:
        logging.error("No file selected. Exiting.")
        sys.exit(1)
    base_folder = os.path.dirname(excel_file)
    BACKGROUND_IMAGE_PATH = os.path.join(base_folder, "background.png")
    LOGO_PATH = os.path.join(base_folder, "logo.png")
    OUTPUT_FOLDER = Path(base_folder) / "output"
    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
    process_excel_file(excel_file)
    logging.info(f"Covers saved in {OUTPUT_FOLDER}")
    try:
        if sys.platform == "win32":
            os.startfile(OUTPUT_FOLDER)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", OUTPUT_FOLDER])
        else:
            subprocess.Popen(["xdg-open", OUTPUT_FOLDER])
    except Exception as e:
        logging.error(f"Error opening output folder: {e}")
    print("All covers have been generated and saved in the output folder.")
