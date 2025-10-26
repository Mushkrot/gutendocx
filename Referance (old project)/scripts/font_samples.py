import os
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics

# Определяем текущую директорию скрипта
script_dir = os.path.dirname(os.path.abspath(__file__))

# Папка, где лежат шрифты
fonts_dir = os.path.join(script_dir, "fonts")

# Выходной PDF-файл (в той же папке, где скрипт)
output_file = os.path.join(script_dir, "fonts_preview.pdf")

# Получаем список всех файлов .ttf в папке "fonts"
font_files = [f for f in os.listdir(fonts_dir) if f.lower().endswith(".ttf")]

if not font_files:
    print("❌ В папке 'fonts' не найдено шрифтов!")
    exit()

# Создаём PDF-документ
c = canvas.Canvas(output_file, pagesize=A4)
width, height = A4
y_position = height - 50  # Начальная позиция текста
font_size = 30  # Размер шрифта, чтобы текст влезал в строку

# Функция для очистки имени шрифта
def clean_font_name(font_file):
    name = os.path.splitext(font_file)[0]  # Убираем .ttf
    name = name.replace("-", " ")  # Заменяем "-" на пробелы
    # Убираем стандартные слова (Regular, Bold, Italic и т. д.)
    words_to_remove = ["Regular", "Bold", "Italic", "Medium", "Light", "Extra", "VariableFont", "wght"]
    for word in words_to_remove:
        name = name.replace(word, "").strip()
    return name

for font_file in font_files:
    font_path = os.path.join(fonts_dir, font_file)
    font_name = clean_font_name(font_file)  # Очищенное имя шрифта

    try:
        # Регистрируем шрифт в PDF
        pdfmetrics.registerFont(TTFont(font_name, font_path))
        c.setFont(font_name, font_size)  # Размер шрифта

        # Формируем строку: "Rare Books (FontName)"
        text = f"Rare Books ({font_name})"
        c.drawString(50, y_position, text)
        y_position -= 60  # Смещаемся вниз

        print(f"✅ Добавлен шрифт: {font_file}")

        # Перенос на новую страницу при нехватке места
        if y_position < 50:
            c.showPage()
            y_position = height - 50

    except Exception as e:
        print(f"⚠️ Ошибка с шрифтом {font_file}: {e}")

# Сохраняем PDF
c.save()
print(f"📄 Превью шрифтов сохранено: {output_file}")
