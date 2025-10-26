# covers.py v1.2
# -*- coding: utf-8 -*-

import os
import pandas as pd
import re
import unicodedata
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps
import logging

# === КОНФИГУРАЦИЯ ===

# Определяем директорию скрипта и папку со шрифтами (относительно скрипта)
SCRIPT_DIR = Path(__file__).resolve().parent
FONTS_FOLDER = SCRIPT_DIR / "fonts"

# Пути к изображениям (будут определены динамически после выбора Excel-файла)
BACKGROUND_IMAGE_PATH = None
LOGO_PATH = None
LOGO_SIZE = (400, 200)  # Ширина и высота логотипа в пикселях

# Размер обложки (физические размеры в см)
COVER_WIDTH_CM = 15.2
COVER_HEIGHT_CM = 21.72

# Параметры изображения
RESOLUTION = 140  # DPI
IMAGE_WIDTH = int(COVER_WIDTH_CM / 2.54 * RESOLUTION)
IMAGE_HEIGHT = int(COVER_HEIGHT_CM / 2.54 * RESOLUTION)

# Шрифты
SELECTED_FONT_NAME = "EuphoriaScript"
FONT_FILE = FONTS_FOLDER / f"{SELECTED_FONT_NAME}-Regular.ttf"
SECOND_FONT_NAME = "GreatVibes"  # или другой, установленный в системе
SECOND_FONT_FILE = FONTS_FOLDER / f"{SECOND_FONT_NAME}-Regular.ttf"
ALTERNATIVE_FONT = "arial.ttf"

# Размеры шрифтов
TITLE_FONT_SIZE = 80
AUTHOR_FONT_SIZE = 60
ANCHOR_FONT_SIZE = 40
VOLUME_FONT_SIZE = 50

# Цвета
BACKGROUND_COLOR = (108, 37, 36)  # Красный
TEXT_COLOR = (255, 255, 255)

# Колонки Excel (A=0, B=1, ..., I=8)
COLUMN_MAPPING = {
    "ISBN": 0,
    "Author": 1,
    "Title": 2,
    "Volume": 3,
    "File_Code": 7,
    "Ancor": 8
}

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("covers.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# === ФУНКЦИИ ===

def clean_text(text):
    """Очистка текста"""
    if pd.isna(text):
        return ""
    text = str(text)
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r'[^\w\s\-.,;:!?]', '', text)
    return text.strip()

def format_authors(authors):
    """Форматирование авторов"""
    if not authors or pd.isna(authors):
        return ["Неизвестный автор"]
    
    authors_list = [clean_text(a) for a in str(authors).split(";")]
    formatted_authors = []
    
    for author in authors_list:
        parts = [part.strip() for part in author.split(",")]
        if len(parts) == 2:
            formatted_authors.append(f"{parts[1]} {parts[0]}")
        else:
            formatted_authors.append(author)
    
    return formatted_authors if formatted_authors else ["Неизвестный автор"]

def split_volume(volume_text):
    """Разделяет номер тома и его название."""
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
    """Вычисляет ширину текста с использованием доступных методов."""
    try:
        return font.getlength(text)
    except AttributeError:
        try:
            bbox = font.getbbox(text)
            return bbox[2] - bbox[0]
        except AttributeError:
            dummy_img = Image.new('RGB', (1,1))
            draw = ImageDraw.Draw(dummy_img)
            text_width, _ = draw.textsize(text, font=font)
            return text_width

def wrap_text(text, font, max_width):
    """Перенос текста на несколько строк, если он превышает максимальную ширину."""
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
    """Наложение фонового изображения"""
    if BACKGROUND_IMAGE_PATH and BACKGROUND_IMAGE_PATH.exists():
        try:
            background = Image.open(BACKGROUND_IMAGE_PATH).convert("RGBA")
            background = background.resize((IMAGE_WIDTH, IMAGE_HEIGHT))
            img = Image.alpha_composite(img, background)
        except Exception as e:
            logging.error(f"Ошибка загрузки фона: {e}")
    return img

def apply_logo(img):
    """Добавление логотипа в нижнюю часть"""
    if LOGO_PATH and LOGO_PATH.exists():
        try:
            logo = Image.open(LOGO_PATH).convert("RGBA")
            logo = logo.resize(LOGO_SIZE)
            logo_x = (IMAGE_WIDTH - LOGO_SIZE[0]) // 2
            logo_y = IMAGE_HEIGHT - LOGO_SIZE[1] - 100
            img.paste(logo, (logo_x, logo_y), logo)
        except Exception as e:
            logging.error(f"Ошибка загрузки логотипа: {e}")
    return img

def load_font(size, primary=True):
    """Загрузка шрифта с указанным размером."""
    try:
        if primary:
            return ImageFont.truetype(str(FONT_FILE), size)
        else:
            return ImageFont.truetype(str(SECOND_FONT_FILE), size)
    except Exception as e:
        logging.warning(f"Не удалось загрузить шрифт, используется запасной: {e}")
        return ImageFont.truetype(ALTERNATIVE_FONT, size)

def create_image(data, output_path):
    """Создание обложки"""
    try:
        img = Image.new('RGBA', (IMAGE_WIDTH, IMAGE_HEIGHT), BACKGROUND_COLOR + (255,))
        img = apply_background(img)
        draw = ImageDraw.Draw(img)
        
        title_font = load_font(TITLE_FONT_SIZE, primary=True)
        author_font = load_font(AUTHOR_FONT_SIZE, primary=False)
        anchor_font = load_font(ANCHOR_FONT_SIZE, primary=False)
        volume_font = load_font(VOLUME_FONT_SIZE, primary=False)
        
        y_pos = IMAGE_HEIGHT * 0.10
        
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
        
        # Логотип (при необходимости можно включить)
        # img = apply_logo(img)
        
        img.convert('RGB').save(output_path, 'JPEG', quality=95, dpi=(RESOLUTION, RESOLUTION))
        return True
        
    except Exception as e:
        logging.error(f"Ошибка создания изображения: {e}")
        return False

def process_excel_file(file_path):
    """Обработка Excel-файла"""
    try:
        df = pd.read_excel(
            file_path,
            engine='openpyxl',
            header=None,
            usecols=list(COLUMN_MAPPING.values()),
            names=list(COLUMN_MAPPING.keys()),
            skiprows=0
        )
        logging.info(f"Прочитано строк: {len(df)}")
        
        for index, row in df.iterrows():
            try:
                data = {
                    "title": clean_text(row.get("Title", "Без названия")),
                    "authors": format_authors(row.get("Author", "")),
                    "anchor": clean_text(row.get("Ancor", "")),
                    "volume": clean_text(row.get("Volume", ""))
                }
                
                isbn = clean_text(row.get("ISBN", ""))
                file_code = clean_text(row.get("File_Code", ""))
                if isbn:
                    base_name = isbn
                elif file_code:
                    base_name = file_code
                else:
                    base_name = f"Без_названия_{index + 1}"
                
                base_name = re.sub(r'[^\w\-_.]', '_', base_name)
                file_name = f"{base_name}.jpg"
                output_path = OUTPUT_FOLDER / file_name
                
                counter = 1
                while output_path.exists():
                    file_name = f"{base_name}_{counter}.jpg"
                    output_path = OUTPUT_FOLDER / file_name
                    counter += 1
                
                if create_image(data, output_path):
                    logging.info(f"Создана обложка: {file_name}")
                else:
                    logging.error(f"Не удалось создать обложку для строки {index + 1}")
            
            except Exception as e:
                logging.error(f"Ошибка в строке {index + 1}: {e}")
    
    except Exception as e:
        logging.error(f"Ошибка чтения файла {file_path}: {e}")

# === Основной блок ===

if __name__ == "__main__":
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    excel_file = filedialog.askopenfilename(
        title="Выберите Excel файл для обработки",
        filetypes=[("Excel файлы", "*.xlsx")]
    )
    if not excel_file:
        logging.error("Файл не выбран. Выход.")
        exit(1)
    
    base_folder = Path(excel_file).parent
    BACKGROUND_IMAGE_PATH = base_folder / "background.png"
    LOGO_PATH = base_folder / "logo.png"
    OUTPUT_FOLDER = base_folder / "output"
    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
    
    process_excel_file(excel_file)
    logging.info(f"Обложки сохранены в {OUTPUT_FOLDER}")
