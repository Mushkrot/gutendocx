# covers.py v1.5
# -*- coding: utf-8 -*-

import os
import pandas as pd
import re
import unicodedata
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps
import logging

# === CONFIGURATION ===

# Define script directory and fonts folder (relative to the script)
SCRIPT_DIR = Path(__file__).resolve().parent
FONTS_FOLDER = SCRIPT_DIR / "fonts"

# Paths to images (will be defined dynamically after selecting the Excel file)
BACKGROUND_IMAGE_PATH = None
LOGO_PATH = None
LOGO_SIZE = (400, 200)  # Width and height of logo in pixels

# Cover size (physical dimensions in cm)
COVER_WIDTH_CM = 15.2
COVER_HEIGHT_CM = 21.72

# Image parameters
RESOLUTION = 140  # DPI
IMAGE_WIDTH = int(COVER_WIDTH_CM / 2.54 * RESOLUTION)
IMAGE_HEIGHT = int(COVER_HEIGHT_CM / 2.54 * RESOLUTION)

# Fonts
SELECTED_FONT_NAME = "EuphoriaScript"
FONT_FILE = FONTS_FOLDER / f"{SELECTED_FONT_NAME}-Regular.ttf"
SECOND_FONT_NAME = "GreatVibes"  # or another system-installed font
SECOND_FONT_FILE = FONTS_FOLDER / f"{SECOND_FONT_NAME}-Regular.ttf"
ALTERNATIVE_FONT = "arial.ttf"

# Font sizes
TITLE_FONT_SIZE = 80
AUTHOR_FONT_SIZE = 60
ANCHOR_FONT_SIZE = 40
VOLUME_FONT_SIZE = 50

# Colors
BACKGROUND_COLOR = (108, 37, 36)  # Red
TEXT_COLOR = (255, 255, 255)

# Excel columns (A=0, B=1, ..., I=8)
COLUMN_MAPPING = {
    "ISBN": 0,
    "Author": 1,
    "Title": 2,
    "Volume": 3,
    "File_Code": 7,
    "Ancor": 8
}

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("covers.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# === FUNCTIONS ===

def clean_text(text):
    if pd.isna(text):
        return ""
    if isinstance(text, (float, int)):
        text = str(int(text)) if text.is_integer() else str(text)
    else:
        text = str(text)
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r'[^\w\s\-.,;:!?]', '', text)
    return text.strip()

def format_authors(authors):
    """Format authors."""
    if not authors or pd.isna(authors):
        return []
    
    authors_list = [clean_text(a) for a in str(authors).split(";")]
    formatted_authors = []
    
    for author in authors_list:
        parts = [part.strip() for part in author.split(",")]
        if len(parts) == 2:
            formatted_authors.append(f"{parts[1]} {parts[0]}")
        else:
            formatted_authors.append(author)
    
    return formatted_authors

def split_volume(volume_text):
    """Separate volume number and its title."""
    volume_text = clean_text(volume_text)
    if not volume_text:
        return None, None
    
    match = re.match(r"^([^\d]*?\b\w+\b[\s\-]*)(\d+)([\s\W]+)(.*)$", volume_text, re.IGNORECASE)
    if not match:
        return None, volume_text
    
    volume_prefix = f"{match.group(1).strip()} {match.group(2).strip()}"
    volume_name = re.sub(r"^[\s\W]+", "", match.group(4))
    volume_prefix = re.sub(r"[\s\-]+$", "", volume_prefix)
    
    return volume_prefix, volume_name

def font_measure_text(text, font):
    """Calculate text width using available methods."""
    try:
        return font.getlength(text)
    except AttributeError:
        try:
            bbox = font.getbbox(text)
            return bbox[2] - bbox[0]
        except AttributeError:
            dummy_img = Image.new('RGB', (1, 1))
            draw = ImageDraw.Draw(dummy_img)
            text_width, _ = draw.textsize(text, font=font)
            return text_width

def wrap_text(text, font, max_width):
    """Wrap text into multiple lines if it exceeds maximum width."""
    lines = []
    words = text.split()
    current_line = []
    
    for word in words:
        test_line = ' '.join(current_line + [word])
        text_width = font_measure_text(test_line, font)
        if text_width <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(' '.join(current_line))
            current_line = [word]
    
    if current_line:
        lines.append(' '.join(current_line))
    return lines

def apply_background(img):
    """Apply background image."""
    if BACKGROUND_IMAGE_PATH and BACKGROUND_IMAGE_PATH.exists():
        try:
            background = Image.open(BACKGROUND_IMAGE_PATH).convert("RGBA")
            background = background.resize((IMAGE_WIDTH, IMAGE_HEIGHT))
            img = Image.alpha_composite(img, background)
        except Exception as e:
            logging.error(f"Error loading background: {e}")
    return img

def apply_logo(img):
    """Add logo at the bottom."""
    if LOGO_PATH and LOGO_PATH.exists():
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
    """Load font with specified size."""
    try:
        if primary:
            return ImageFont.truetype(str(FONT_FILE), size)
        else:
            return ImageFont.truetype(str(SECOND_FONT_FILE), size)
    except Exception as e:
        logging.warning(f"Could not load font, using fallback: {e}")
        return ImageFont.truetype(ALTERNATIVE_FONT, size)

def create_image(data, output_path):
    """Create cover image."""
    try:
        img = Image.new('RGBA', (IMAGE_WIDTH, IMAGE_HEIGHT), BACKGROUND_COLOR + (255,))
        img = apply_background(img)
        draw = ImageDraw.Draw(img)
        
        title_font = load_font(TITLE_FONT_SIZE, primary=True)
        author_font = load_font(AUTHOR_FONT_SIZE, primary=False)
        anchor_font = load_font(ANCHOR_FONT_SIZE, primary=False)
        volume_font = load_font(VOLUME_FONT_SIZE, primary=False)
        
        y_pos = IMAGE_HEIGHT * 0.10
        
        # Draw title if available
        title_lines = wrap_text(data["title"], title_font, IMAGE_WIDTH * 0.8)
        for line in title_lines:
            text_width = font_measure_text(line, title_font)
            draw.text(
                ((IMAGE_WIDTH - text_width) / 2, y_pos),
                line,
                font=title_font,
                fill=TEXT_COLOR
            )
            y_pos += TITLE_FONT_SIZE + 40
        
        # Draw volume if available
        if data.get("volume"):
            volume_prefix, volume_name = split_volume(data["volume"])
        else:
            volume_prefix, volume_name = None, None
        
        if volume_prefix or volume_name:
            y_pos += 50
            if volume_prefix:
                volume_prefix_lines = wrap_text(volume_prefix, volume_font, IMAGE_WIDTH * 0.8)
                for line in volume_prefix_lines:
                    text_width = font_measure_text(line, volume_font)
                    draw.text(
                        ((IMAGE_WIDTH - text_width) / 2, y_pos),
                        line,
                        font=volume_font,
                        fill=TEXT_COLOR
                    )
                    y_pos += VOLUME_FONT_SIZE + 10
            if volume_name:
                volume_name_lines = wrap_text(volume_name, volume_font, IMAGE_WIDTH * 0.8)
                for line in volume_name_lines:
                    text_width = font_measure_text(line, volume_font)
                    draw.text(
                        ((IMAGE_WIDTH - text_width) / 2, y_pos),
                        line,
                        font=volume_font,
                        fill=TEXT_COLOR
                    )
                    y_pos += VOLUME_FONT_SIZE + 10
        
        # Draw anchor if available
        if data.get("anchor"):
            y_pos += 40
            anchor_lines = wrap_text(data["anchor"], anchor_font, IMAGE_WIDTH * 0.8)
            for line in anchor_lines:
                text_width = font_measure_text(line, anchor_font)
                draw.text(
                    ((IMAGE_WIDTH - text_width) / 2, y_pos),
                    line,
                    font=anchor_font,
                    fill=TEXT_COLOR
                )
                y_pos += ANCHOR_FONT_SIZE + 20
        
        # Draw authors if available
        for author in data["authors"]:
            author_lines = wrap_text(author, author_font, IMAGE_WIDTH * 0.8)
            for line in author_lines:
                text_width = font_measure_text(line, author_font)
                draw.text(
                    ((IMAGE_WIDTH - text_width) / 2, y_pos),
                    line,
                    font=author_font,
                    fill=TEXT_COLOR
                )
                y_pos += AUTHOR_FONT_SIZE + 20
        
        # Logo (uncomment if needed)
        # img = apply_logo(img)
        
        img.convert('RGB').save(output_path, 'JPEG', quality=95, dpi=(RESOLUTION, RESOLUTION))
        return True
        
    except Exception as e:
        logging.error(f"Error creating image: {e}")
        return False

def process_excel_file(file_path):
    """Process Excel file."""
    try:
        df = pd.read_excel(
            file_path,
            engine='openpyxl',
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
                
                base_name = re.sub(r'[^\w\-_.]', '_', base_name)
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

# === Main Block ===

if __name__ == "__main__":
    import tkinter as tk
    from tkinter import filedialog, messagebox
    import sys
    import subprocess

    root = tk.Tk()
    root.withdraw()
    excel_file = filedialog.askopenfilename(
        title="Select Excel file for processing",
        filetypes=[("Excel files", "*.xlsx")]
    )
    if not excel_file:
        logging.error("No file selected. Exiting.")
        exit(1)
    
    base_folder = Path(excel_file).parent
    BACKGROUND_IMAGE_PATH = base_folder / "background.png"
    LOGO_PATH = base_folder / "logo.png"
    OUTPUT_FOLDER = base_folder / "output"
    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
    
    process_excel_file(excel_file)
    logging.info(f"Covers saved in {OUTPUT_FOLDER}")
    
    # Open output folder automatically
    try:
        if sys.platform == "win32":
            os.startfile(OUTPUT_FOLDER)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", OUTPUT_FOLDER])
        else:
            subprocess.Popen(["xdg-open", OUTPUT_FOLDER])
    except Exception as e:
        logging.error(f"Error opening output folder: {e}")
    
    # Inform the user that processing is complete
    messagebox.showinfo("Process Completed", "All covers have been generated and saved in the output folder.")
