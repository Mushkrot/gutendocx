# covers.py v2.1
# -*- coding: utf-8 -*-

import os
import pandas as pd
import re
import unicodedata
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps
import logging

# === CONFIGURATION ===

# Script and fonts directories
SCRIPT_DIR = Path(__file__).resolve().parent  # Script directory
FONTS_FOLDER = SCRIPT_DIR / "fonts"           # Folder containing fonts

# Image paths (defined dynamically after selecting the Excel file)
BACKGROUND_IMAGE_PATH = None  # Path to background image
LOGO_PATH = None              # Path to logo image
LOGO_SIZE = (400, 200)        # Logo size in pixels (width, height)

# Cover physical size in centimeters
COVER_WIDTH_CM = 15.2  # Cover width in cm
COVER_HEIGHT_CM = 21.72  # Cover height in cm

# Image parameters
RESOLUTION = 140
IMAGE_WIDTH = int(COVER_WIDTH_CM / 2.54 * RESOLUTION)   # Image width in pixels
IMAGE_HEIGHT = int(COVER_HEIGHT_CM / 2.54 * RESOLUTION) # Image height in pixels

# Fonts settings
SELECTED_FONT_NAME = "EuphoriaScript"  # Primary font name
FONT_FILE = FONTS_FOLDER / f"{SELECTED_FONT_NAME}-Regular.ttf"  # Primary font file
SECOND_FONT_NAME = "GreatVibes"        # Secondary font name (or a system font)
SECOND_FONT_FILE = FONTS_FOLDER / f"{SECOND_FONT_NAME}-Regular.ttf"  # Secondary font file
ALTERNATIVE_FONT = "arial.ttf"         # Fallback font

# === DYNAMIC LAYOUT CONFIGURATION ===
# All variables below control the dynamic text layout and can be adjusted as needed.

ZONE_COUNT = 4               # Total number of horizontal zones (recommended: do not change)
ZONE_HEIGHT = IMAGE_HEIGHT / ZONE_COUNT  # Height of each zone in pixels

# Title (Zone 1) Settings
TITLE_AREA_WIDTH_FACTOR = 0.9   # Fraction of IMAGE_WIDTH available for the title
TITLE_MAX_FONT_SIZE = 120       # Maximum font size for title (recommended: 100-150)
TITLE_MIN_FONT_SIZE = 30        # Minimum font size for title (recommended: 20-40)
TITLE_LINE_SPACING = 1.2        # Line spacing multiplier for title text
TITLE_TOP_MARGIN = 10           # Additional top margin for the title within Zone 1
# Instead of a fixed TITLE_AREA_HEIGHT, we compute it as (ZONE_HEIGHT - TITLE_TOP_MARGIN)

# Volume (Zone 2) Settings
VOLUME_AREA_WIDTH_FACTOR = 0.9  # Fraction of IMAGE_WIDTH available for the volume text
VOLUME_RATIO = 0.67             # Ideal ratio of volume font size to title font size (0.6-0.7)
VOLUME_MIN_FONT_SIZE = 20       # Minimum font size for volume text (recommended: 15-25)
VOLUME_LINE_SPACING = 1.2       # Line spacing multiplier for volume text
VOLUME_TOP_MARGIN = 10          # Top margin for volume text within Zone 2

# Anchor and Authors (Zone 3) Settings
ANCHOR_AREA_WIDTH_FACTOR = 0.9  # Fraction of IMAGE_WIDTH available for anchor text
AUTHORS_AREA_WIDTH_FACTOR = 0.9 # Fraction of IMAGE_WIDTH available for authors text
ANCHOR_RATIO = 0.5              # Ratio of anchor font size relative to title font size (0.4-0.6)
AUTHOR_RATIO = 0.6              # Ratio of author font size relative to title font size (0.5-0.7)
ANCHOR_MIN_FONT_SIZE = 20       # Minimum font size for anchor text (15-25)
AUTHOR_MIN_FONT_SIZE = 30       # Minimum font size for authors text (increased to avoid being too small)
ANCHOR_LINE_SPACING = 1.2       # Line spacing multiplier for anchor text
AUTHOR_LINE_SPACING = 1.2       # Line spacing multiplier for authors text
ZONE3_MARGIN = 10               # Vertical margin in pixels between anchor and authors

# Additional zone overlap logic
# We allow anchor+authors to extend into Zone 4 by up to half of its height if needed
ALLOW_ZONE4_OVERLAP_RATIO = 0.5  # Fraction of Zone 4 height that can be used

# Colors
BACKGROUND_COLOR = (108, 37, 36)  # Background color (RGB)
TEXT_COLOR = (255, 255, 255)      # Text color (RGB)

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

# === HELPER FUNCTIONS ===

def clean_text(text):
    """Normalize and clean text from unwanted characters."""
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
    """Format authors by reordering name and surname; ignore extra authors beyond two."""
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
    
    # Limit to two authors maximum
    return formatted_authors[:2]

def split_volume_by_comma(volume_text):
    """
    If the volume text contains a comma (e.g. 'Tome 2, Sa vie...'),
    split it so that 'Tome 2' is the first line and the rest goes to the second line(s).
    """
    if not volume_text:
        return []
    splitted = volume_text.split(',', 1)
    if len(splitted) > 1:
        first_part = splitted[0].strip()
        second_part = splitted[1].strip()
        return [first_part, second_part]
    else:
        return [volume_text]

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
    """Wrap text into multiple lines so that each line fits within max_width."""
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

def find_optimal_font_size_for_text(text, area_width, area_height,
                                    min_font, max_font, font_loader,
                                    line_spacing):
    """
    Binary search to find the maximum font size for which the wrapped text
    fits within the given area. Returns (optimal_font_size, wrapped_lines, total_text_height).
    """
    if not text:
        return min_font, [], 0
    optimal_size = min_font
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
            optimal_size = mid
            best_lines = lines
            best_height = total_height
            low = mid + 1
        else:
            high = mid - 1
    return optimal_size, best_lines, best_height

def find_common_optimal_font_size_for_texts(texts, area_width, available_height,
                                            min_font, max_font, font_loader,
                                            line_spacing, inter_text_margin=0):
    """
    Binary search to find a single font size that fits multiple text blocks (each on its own lines).
    The total of their heights (plus inter_text_margin between blocks) must fit in available_height.
    Returns (optimal_font_size, [wrapped_lines_for_each_block], total_combined_height).
    """
    if not texts:
        return min_font, [[] for _ in texts], 0
    
    optimal_size = min_font
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
            block_height = len(lines) * mid * line_spacing
            total += block_height
            wrapped_all.append(lines)
        # Add vertical spacing between blocks
        total += inter_text_margin * (len(texts) - 1)
        
        if total <= available_height:
            optimal_size = mid
            best_wrapped = wrapped_all
            best_total = total
            low = mid + 1
        else:
            high = mid - 1
    
    return optimal_size, best_wrapped, best_total

def apply_background(img):
    """Apply background image if available."""
    if BACKGROUND_IMAGE_PATH and BACKGROUND_IMAGE_PATH.exists():
        try:
            background = Image.open(BACKGROUND_IMAGE_PATH).convert("RGBA")
            background = background.resize((IMAGE_WIDTH, IMAGE_HEIGHT))
            img = Image.alpha_composite(img, background)
        except Exception as e:
            logging.error(f"Error loading background: {e}")
    return img

def apply_logo(img):
    """Add logo at the bottom of the image."""
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
    """Load the specified font with a given size."""
    try:
        if primary:
            return ImageFont.truetype(str(FONT_FILE), size)
        else:
            return ImageFont.truetype(str(SECOND_FONT_FILE), size)
    except Exception as e:
        logging.warning(f"Could not load font, using fallback: {e}")
        return ImageFont.truetype(ALTERNATIVE_FONT, size)

def create_image(data, output_path):
    """Create the cover image with dynamic text layout."""
    try:
        # Create base image
        img = Image.new('RGBA', (IMAGE_WIDTH, IMAGE_HEIGHT), BACKGROUND_COLOR + (255,))
        img = apply_background(img)
        draw = ImageDraw.Draw(img)

        # Define the four horizontal zones
        zone_height = ZONE_HEIGHT
        zone1_top = 0
        zone2_top = zone_height
        zone3_top = zone_height * 2
        zone4_top = zone_height * 3
        zone4_height = zone_height

        # === Zone 1: Title ===
        # We set an extra top margin so the title doesn't go all the way up.
        title_area_width = IMAGE_WIDTH * TITLE_AREA_WIDTH_FACTOR
        title_area_height = zone_height - TITLE_TOP_MARGIN  # Space for title in zone 1
        title_font_size, title_lines, title_total_height = find_optimal_font_size_for_text(
            data["title"],
            area_width=title_area_width,
            area_height=title_area_height,
            min_font=TITLE_MIN_FONT_SIZE,
            max_font=TITLE_MAX_FONT_SIZE,
            font_loader=lambda s: load_font(s, primary=True),
            line_spacing=TITLE_LINE_SPACING
        )
        title_font = load_font(title_font_size, primary=True)
        # Place title so its bottom aligns with (zone1_top + zone_height), minus top margin
        title_y = zone1_top + TITLE_TOP_MARGIN + (title_area_height - title_total_height)
        for line in title_lines:
            text_width = font_measure_text(line, title_font)
            x = (IMAGE_WIDTH - text_width) / 2
            draw.text((x, title_y), line, font=title_font, fill=TEXT_COLOR)
            title_y += title_font_size * TITLE_LINE_SPACING

        # === Zone 2: Volume (split "Tome 2, ..." if needed) ===
        volume_text = clean_text(data.get("volume", ""))
        volume_parts = split_volume_by_comma(volume_text)  # e.g. ["Tome 2", "Sa vie et ses ouvrages"]
        if volume_parts:
            # Compute a single font size that fits all volume_parts in zone 2
            volume_area_width = IMAGE_WIDTH * VOLUME_AREA_WIDTH_FACTOR
            # Max font size is either volume_min_font_size or title_font_size*VOLUME_RATIO (whichever is bigger)
            volume_max_candidate = max(VOLUME_MIN_FONT_SIZE, int(title_font_size * VOLUME_RATIO))
            volume_area_height = zone_height - VOLUME_TOP_MARGIN

            vol_font_size, vol_wrapped, vol_total_height = find_common_optimal_font_size_for_texts(
                texts=volume_parts,
                area_width=volume_area_width,
                available_height=volume_area_height,
                min_font=VOLUME_MIN_FONT_SIZE,
                max_font=volume_max_candidate,
                font_loader=lambda s: load_font(s, primary=False),
                line_spacing=VOLUME_LINE_SPACING
            )
            volume_font = load_font(vol_font_size, primary=False)
            # Center volume text vertically within Zone 2
            volume_y = zone2_top + VOLUME_TOP_MARGIN + (volume_area_height - vol_total_height) / 2
            for lines_block in vol_wrapped:
                for line in lines_block:
                    text_width = font_measure_text(line, volume_font)
                    x = (IMAGE_WIDTH - text_width) / 2
                    draw.text((x, volume_y), line, font=volume_font, fill=TEXT_COLOR)
                    volume_y += vol_font_size * VOLUME_LINE_SPACING
                # No extra margin needed between parts, since find_common_optimal_font_size_for_texts
                # already accounted for them as separate blocks (they are sequentially placed).

        # === Zone 3: Anchor (top) + Authors (below anchor) ===
        anchor_text = clean_text(data.get("anchor", ""))
        authors_list = data.get("authors", [])

        # Calculate anchor font size
        anchor_area_width = IMAGE_WIDTH * ANCHOR_AREA_WIDTH_FACTOR
        anchor_max_candidate = max(ANCHOR_MIN_FONT_SIZE, int(title_font_size * ANCHOR_RATIO))
        # We first try to fit anchor in the full zone3 height
        anchor_font_size, anchor_lines, anchor_total_height = find_optimal_font_size_for_text(
            anchor_text,
            area_width=anchor_area_width,
            area_height=zone_height,  # initially just zone 3
            min_font=ANCHOR_MIN_FONT_SIZE,
            max_font=anchor_max_candidate,
            font_loader=lambda s: load_font(s, primary=False),
            line_spacing=ANCHOR_LINE_SPACING
        )
        anchor_font = load_font(anchor_font_size, primary=False)

        # Calculate authors font size (common for 1 or 2 authors)
        authors_area_width = IMAGE_WIDTH * AUTHORS_AREA_WIDTH_FACTOR
        # We'll allow anchor+authors to use zone3 plus half of zone4 if needed
        available_for_authors = zone_height + (zone4_height * ALLOW_ZONE4_OVERLAP_RATIO) - anchor_total_height - ZONE3_MARGIN
        if available_for_authors < 0:
            # If anchor alone doesn't fit, we'll scale down anchor first
            available_for_authors = 0

        # If no authors, we skip. If authors exist, find common font size
        authors_wrapped = []
        authors_total_height = 0
        if authors_list and available_for_authors > 0:
            authors_max_candidate = max(AUTHOR_MIN_FONT_SIZE, int(title_font_size * AUTHOR_RATIO))
            author_font_size, authors_wrapped, authors_total_height = find_common_optimal_font_size_for_texts(
                texts=authors_list,
                area_width=authors_area_width,
                available_height=available_for_authors,
                min_font=AUTHOR_MIN_FONT_SIZE,
                max_font=authors_max_candidate,
                font_loader=lambda s: load_font(s, primary=False),
                line_spacing=AUTHOR_LINE_SPACING,
                inter_text_margin=ZONE3_MARGIN
            )
            author_font = load_font(author_font_size, primary=False)
        else:
            author_font_size = AUTHOR_MIN_FONT_SIZE
            author_font = load_font(author_font_size, primary=False)

        # Combined anchor + authors total height
        combined_height = anchor_total_height + ZONE3_MARGIN + authors_total_height

        # If combined still doesn't fit in zone3 + half zone4, scale everything down proportionally
        max_anchor_authors = zone_height + (zone4_height * ALLOW_ZONE4_OVERLAP_RATIO)
        if combined_height > max_anchor_authors > 0:
            scale = max_anchor_authors / combined_height
            # Scale anchor
            new_anchor_size = int(anchor_font_size * scale)
            if new_anchor_size < ANCHOR_MIN_FONT_SIZE:
                new_anchor_size = ANCHOR_MIN_FONT_SIZE
            anchor_font = load_font(new_anchor_size, primary=False)
            anchor_lines = wrap_text(anchor_text, anchor_font, anchor_area_width)
            anchor_total_height = len(anchor_lines) * new_anchor_size * ANCHOR_LINE_SPACING

            # Scale authors
            new_author_size = int(author_font_size * scale)
            if new_author_size < AUTHOR_MIN_FONT_SIZE:
                new_author_size = AUTHOR_MIN_FONT_SIZE
            author_font = load_font(new_author_size, primary=False)
            new_authors_wrapped = []
            new_authors_total_height = 0
            for text in authors_list:
                lines = wrap_text(text, author_font, authors_area_width)
                new_authors_wrapped.append(lines)
                new_authors_total_height += len(lines) * new_author_size * AUTHOR_LINE_SPACING
            authors_wrapped = new_authors_wrapped
            authors_total_height = new_authors_total_height
            combined_height = anchor_total_height + ZONE3_MARGIN + authors_total_height

        # Draw anchor at the top of Zone 3
        anchor_y = zone3_top
        for line in anchor_lines:
            text_width = font_measure_text(line, anchor_font)
            x = (IMAGE_WIDTH - text_width) / 2
            draw.text((x, anchor_y), line, font=anchor_font, fill=TEXT_COLOR)
            anchor_y += anchor_font.size * ANCHOR_LINE_SPACING

        # Draw authors below anchor with margin
        authors_y = anchor_y + ZONE3_MARGIN
        for lines_block in authors_wrapped:
            for line in lines_block:
                text_width = font_measure_text(line, author_font)
                x = (IMAGE_WIDTH - text_width) / 2
                draw.text((x, authors_y), line, font=author_font, fill=TEXT_COLOR)
                authors_y += author_font.size * AUTHOR_LINE_SPACING
            authors_y += ZONE3_MARGIN  # extra space between multiple authors if needed

        # === Zone 4: Typically reserved for logo or other elements ===
        # Optionally, apply logo if desired
        # img = apply_logo(img)

        img.convert('RGB').save(output_path, 'JPEG', quality=95, dpi=(RESOLUTION, RESOLUTION))
        return True

    except Exception as e:
        logging.error(f"Error creating image: {e}")
        return False

def process_excel_file(file_path):
    """Process the Excel file and create covers for each row."""
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
