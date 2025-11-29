# GutenDocx: интеграция LibreOffice, выравнивание нумерации и шрифтов (актуальный дизайн)

## 0. Назначение документа

Этот отчёт описывает **текущую** архитектуру интеграции LibreOffice в GutenDocx:

- серверный пересчёт оглавления (TOC) и экспорт PDF;
- согласование нумерации страниц между DOCX и PDF;
- использование пользовательских шрифтов (в т.ч. Algerian, Cambria, Castellar, Times New Roman, Calibri) внутри LibreOffice Docker‑образа;
- управление стилями Body / Chapter Headings / Page Number через Web‑UI и `config.yaml`.

Исторические эксперименты с Basic‑макросом `UpdateTocAndExport` и фиксированным путём `/config/input.docx` описаны в **`Integration_report 01.md`** и считаются **устаревшими**. Текущая реализация полностью базируется на **PyUNO‑скрипте** и отдельном Docker‑контейнере, без использования Basic‑макросов.

---

## 1. Текущее состояние проекта

### 1.1. Структура репозитория

Основные каталоги:

- `Simples/` — тестовые DOCX (исходники Gutenberg).
- `gutendocx/` — основной Python‑код:
  - `gutendocx/core/` — ядро (layout, whole, toc, libreoffice_toc и т.д.).
  - `gutendocx/web/` — FastAPI‑сервер и Web‑UI (HTML/JS).
  - `gutendocx/scripts/lo_convert.py` — PyUNO‑скрипт для обновления TOC и экспорта PDF.
- `docker/libreoffice/` — Dockerfile и вспомогательные файлы для кастомного образа LibreOffice с шрифтами.
- `fonts/` — каталог пользовательских шрифтов (копируется внутрь Docker‑образа).
- `output/` — директория для результатов (DOCX/PDF/ZIP).
- `Docs/` — документация (`Integration_report 01/02.md`, `macro.bas` и др.).

### 1.2. Конфигурация `config.yaml` (актуальные фрагменты)

Ключевые секции, связанные с нашей интеграцией:

```yaml
layout:
  numbering:
    page2_start_value: 1        # исторический параметр (используется в cover‑пайплайне)
    print_on_page2: false       # печатать ли номер на второй (пустой) странице
  headers:
    show_numpages: false
  blank_page_after_cover: true  # обязательно добавлять пустую страницу после обложки

roles:
  Body: GD Body                 # отдельный стиль для основного текста

style_overrides:
  Title: ...
  Body:
    size_pt: 8.0
    bold: true
    italic: true
  Headings:
    size_pt: 20.0
    all_caps: true
  Footer:                       # стиль номера страницы (footer)
    size_pt: 6.0
    italic: true

output:
  dir: output
  versioning: false

toc:
  levels: 1-2
  libreoffice:
    use_docker: true
    docker_image: gutendocx/libreoffice:latest
    timeout: 120
```

Замечания:

- Стиль `Footer` используется для оформления **номера страницы в нижнем колонтитуле**.
- Настройки `toc.libreoffice` управляют поведением `run_libreoffice_convert` (см. ниже).

---

## 2. Цели изменений

### 2.1. LibreOffice‑шаг

1. После вставки поля TOC (Word TOC field) на сервере **обновить оглавление** и другие индексы.
2. Сохранить обновлённый DOCX.
3. Экспортировать PDF c тем же содержимым и максимально близкой вёрсткой.
4. Делать это либо:
   - через установленный `soffice` на хосте (host‑mode), либо
   - через **кастомный Docker‑образ** с LibreOffice и полным набором шрифтов.

### 2.2. Совпадение нумерации и структуры

- Гарантировать структуру страниц:
  - Стр. 1 — обложка, **без номера**.
  - Стр. 2 — пустая страница, **без номера**.
  - Стр. 3+ — основное тело документа, **с номерами**, начиная с **3**.
- Добиться максимально возможного совпадения количества страниц и номеров TOC между Word и LibreOffice:
  - синхронизировать шрифты (включая Calibri и декоративные шрифты);
  - скорректировать **theme fonts** (major/minor) там, где это необходимо.

### 2.3. Управление стилями из Web‑UI

- Позволить пользователю через интерфейс управлять стилями:
  - **Body** (основной текст);
  - **Chapter Headings** (заголовки глав);
  - **Page Number** (цифра в footer);
- При этом:
  - применять только **явно указанные** оверрайды;
  - не ломать оригинальные стили документа, если пользователь ничего не трогал.

---

## 3. Текущий дизайн LibreOffice‑интеграции

### 3.1. Общая схема

Ключевые компоненты:

- `gutendocx/core/toc.py::build_toc` — вставка TOC‑поля в DOCX.
- `gutendocx/core/libreoffice_toc.py::run_libreoffice_convert` — общий helper для работы с LibreOffice.
- `gutendocx/scripts/lo_convert.py` — **PyUNO‑скрипт** внутри контейнера, который:
  - подключается к запущенному headless‑LibreOffice по UNO‑сокету;
  - загружает документ скрыто;
  - обновляет все индексы (`getDocumentIndexes().update()` / fallback `doc.refresh()`);
  - сохраняет DOCX;
  - экспортирует PDF.

### 3.2. `run_libreoffice_convert` (актуальная реализация)

Сигнатура:

```python
def run_libreoffice_convert(
    input_path: str,
    soffice: str = "soffice",
    out_dir: Optional[str] = None,
    timeout: int = 120,
    use_docker: bool = False,
    docker_image: Optional[str] = None,
) -> Dict[str, Any]:
```

Общие шаги (общие для host/Docker):

1. Проверка наличия входного DOCX (`abs_input`).
2. Вызов `fix_theme_fonts(abs_input, major_font="Cambria", minor_font="Cambria")`:
   - правит `word/theme/theme1.xml` у документа, заменяя **theme fonts** major/minor на Cambria;
   - это уменьшает различия в разметке между Word и LibreOffice, особенно когда исходный документ использует тему Calibri, а на стороне LO нет идентичного набора метрик.
3. Подготовка выходного каталога `abs_out_dir` и имён:
   - `docx_output_path = <out_dir>/<base_root>.docx`;
   - `pdf_output_path = <out_dir>/<base_root>.pdf`.

#### 3.2.1. Режим Docker (`use_docker=True`)

1. Определение PyUNO‑скрипта:
   - `script_path = <project_root>/gutendocx/scripts/lo_convert.py`.
2. Старт временного контейнера:
   
   - контейнер с именем `lo_worker_<uuid>`, образом `docker_image or DEFAULT_DOCKER_IMAGE`.
   - `DEFAULT_DOCKER_IMAGE = "lscr.io/linuxserver/libreoffice:latest"`, но в `config.yaml` указываем **`gutendocx/libreoffice:latest`** (наш кастомный образ с шрифтами).
3. Заливка файлов внутрь контейнера через `docker exec -i ... tee`:
   - PyUNO‑скрипт: `/tmp/lo_convert.py`;
   - входной DOCX: `/tmp/input.docx`.
4. Внутри контейнера выполняется команда:

   ```bash
   soffice --headless --accept='socket,host=localhost,port=2002;urp;' >/dev/null 2>&1 & \
   sleep 5 && \
   python3 /tmp/lo_convert.py /tmp/input.docx /tmp/output.pdf
   ```

   Скрипт `lo_convert.py`:

   - ждёт подключения к UNO‑сокету (`wait_for_socket("localhost", 2002)`);
   - открывает документ скрыто (`Hidden=True`);
   - обновляет все `DocumentIndexes` (оглавление, индексы и т.п.);
   - `doc.store()` — перезаписывает входной DOCX внутри контейнера;
   - `doc.storeToURL` в PDF (`writer_pdf_Export`) по пути `/tmp/output.pdf`.

5. Если команда завершилась успешно (код `0`):
   - DOCX считывается обратно на хост:
     - `docker exec CONTAINER cat /tmp/input.docx > <out_dir>/<base_root>.docx`;
   - PDF считывается обратно на хост:
     - `docker exec CONTAINER cat /tmp/output.pdf > <out_dir>/<base_root>.pdf`.
6. Контейнер гарантированно гасится через `docker kill`, даже при ошибках/тайм‑ауте.
7. Результат:
   - `ok`: успех с учётом наличия обоих файлов (DOCX+PDF);
   - `output_path`: путь к обновлённому DOCX;
   - `pdf_output_path`: путь к PDF;
   - `stdout`/`stderr`: лог работы PyUNO и `soffice`.

#### 3.2.2. Host‑mode (`use_docker=False`)

- Классический вызов `soffice --headless --convert-to docx` плюс проверка наличия PDF.
- Используется как fallback, когда Docker недоступен или специально выключен.

### 3.3. Использование из server.py

- В `/toc/apply` и цепочке после `/whole/apply` переходим к `run_libreoffice_convert` **с учётом настроек**:
  - `toc.libreoffice.use_docker` — включить Docker‑режим;
  - `toc.libreoffice.docker_image` — `gutendocx/libreoffice:latest`.
- API‑ответы включают:
  - `output_path` — обновлённый DOCX с пересчитанным TOC;
  - `pdf_output_path` — путь к PDF.

---

## 4. Layout и нумерация страниц

### 4.1. Общая цель

Обеспечить консистентную структуру документа **до** передачи его LibreOffice, чтобы пересчёт TOC и экспорт PDF работали на хорошо структурированном DOCX.

Основные требования:

- После титула всегда должна быть **ровно одна** пустая страница.
- Нумерация страниц для тела документа начинается с 3 (первая напечатанная цифра — «3»).
- Номера страниц **не отображаются** на обложке и пустой странице.

### 4.2. Ключевые функции layout.py

#### 4.2.1. `ensure_blank_page_after_cover`

- Анализирует документ, находит переход обложка → тело по page break’ам.
- При необходимости вставляет **дополнительный параграф с разрывом страницы**, чтобы гарантировать:
  - Стр. 1 — обложка.
  - Стр. 2 — пустая.

#### 4.2.2. `ensure_body_section_with_numbering`

- Обеспечивает корректную структуру секций для тела документа перед LibreOffice:
  - конвертирует нужный page break в section break;
  - разделяет обложку+пустую страницу и основное тело на разные секции;
  - на уровне `sectPr` последней секции выставляет параметры нумерации так, чтобы LibreOffice корректно считал номера страниц в TOC.
- Ранее использовался строгий `pgNumType start=1`; в ходе доработок логика была скорректирована, чтобы **не сбрасывать физическую нумерацию** и позволить нашей схеме «обложка/пустая/тело».

#### 4.2.3. `apply_sections_and_numbering`

- Используется в cover‑пайплайне (`run_cover_pipeline`) для явного построения трёх секций:
  - Section A — обложка (страница 1, без номера);
  - Section B — пустая страница (страница 2, по умолчанию без номера);
  - Section C — тело (страница 3+).
- Развилка по конфигу:
  - `layout.numbering.print_on_page2 = false` — на пустой странице номер не печатается;
  - дополнительно есть параметр `body_start_number` (по умолчанию **3**), определяющий, с какого значения нумерации начинается Section C.

#### 4.2.4. `apply_footer_styles`

Новая обобщающая функция для футеров:

- Очищает все footer’ы во всех секциях.
- Применяет **стиль номера страницы** (из `style_overrides.Footer` или переданный явно) только к **последней** секции (тело).
- Добавляет поле PAGE в центр футера тела, используя `_add_page_field(paragraph, style_overrides)`:
  - `font_family` (из UI или `config.yaml`),
  - `size_pt`,
  - `bold` / `italic`.
- При необходимости выставляет `pgNumType` для последней секции так, чтобы числовое значение на первой странице тела было равно `body_start_number` (по умолчанию 3).

### 4.3. Интеграция в пайплайн

#### 4.3.1. `cover.run_cover_pipeline`

- Детектирует элементы обложки (Title/Subtitle/Author).
- Применяет к ним стили из `cover.styles` и `style_overrides.Title` и др.
- Определяет границу cover/body.
- Вызывает `apply_sections_and_numbering`, передавая `footer_style_overrides` при необходимости.

#### 4.3.2. `whole.apply_whole_document`

- Определяет `body_start` (первый параграф тела).
- Применяет оверрайды:
  - Body — `_apply_body_style_overrides`;
  - Headings — `_apply_headings_style_overrides` (новый функционал);
  - Specials — `_apply_special_style_overrides`.
- Гарантирует наличие пустой страницы после обложки: `ensure_blank_page_after_cover`.
- Вызывает `ensure_body_section_with_numbering` для корректной работы LO/TOC.
- Вызывает `apply_footer_styles`, чтобы задать финальный вид и нумерацию футера.
- Сохраняет документ в `output/` с учётом версионирования.

---

## 5. Шрифты и Docker‑образ LibreOffice

### 5.1. Каталог `fonts/` и сканирование DOCX

Мы просканировали все DOCX в `Simples/` на предмет используемых шрифтов, в т.ч. в таблицах и сложных структурах. В результате были обнаружены, в частности:

- **Algerian**,
- **Cambria**, **Cambria Math**,
- **Castellar**,
- **Times New Roman**,
- `minorHAnsi` / `majorHAnsi` (theme fonts → Calibri / Calibri Light).

Каталог `fonts/` был заполнен соответствующими TTF/OTF‑файлами (включая Calibri, предоставленный пользователем).

### 5.2. Dockerfile для LibreOffice

Файл: `docker/libreoffice/Dockerfile`.

Основные шаги:

```Dockerfile
FROM lscr.io/linuxserver/libreoffice:latest

# Установка дополнительных пакетов шрифтов (Alpine)
RUN apk add --no-cache \
    font-liberation \
    font-noto \
    font-dejavu \
    font-freefont \
    font-croscore \
    font-carlito

# Копирование пользовательских шрифтов
COPY fonts/ /usr/share/fonts/custom/

# Перестроение кэша шрифтов
RUN fc-cache -f -v
```

Сборка образа (с учётом ограничений Docker‑контекста во внешней среде) выполняется через передачу архива контекста на stdin `docker build`.

В результате в контейнере доступны:

- системные шрифты (Noto, DejaVu, Liberation и др.);
- пользовательские шрифты из `/usr/share/fonts/custom/`;
- по команде `fc-list : family` видны:
  - **Algerian**, **Cambria**, **Castellar**, **Times New Roman**, **Calibri** и др.

### 5.3. Theme fonts и `fix_theme_fonts`

Многие DOCX используют **theme fonts** (`minorHAnsi` / `majorHAnsi`), которые по умолчанию мапятся на Calibri / Calibri Light. Чтобы уменьшить различия в переносах и количестве страниц между Word и LO:

- В `layout.fix_theme_fonts(docx_path, major_font="Cambria", minor_font="Cambria")` мы:
  - открываем `word/theme/theme1.xml` внутри DOCX;
  - меняем `fontScheme/majorFont/latin/@typeface` и `minorFont/latin/@typeface` на `Cambria`;
  - сохраняем DOCX (через временный каталог и перепаковку ZIP).

Этот шаг выполняется **перед** запуском LibreOffice в `run_libreoffice_convert`, чтобы:

- гарантировать, что заголовки и основной текст, завязанные на тему, используют шрифт, который уверенно доступен и в Word, и в нашем Docker‑образе;
- уменьшить рассинхронизацию по количеству страниц между DOCX и PDF.

При этом у пользователя всё ещё есть возможность явно задавать шрифты для Body/Headings/Footer через UI.

---

## 6. Web‑приложение и API

### 6.1. Основные endpoint’ы

- `/cover/analyze` / `/cover/apply` — детекция и применение стилей обложки.
- `/whole/analyze` / `/whole/apply` — анализ и нормализация всего документа (тело, стили, секции, нумерация, футеры).
- `/toc/apply` — вставка TOC‑поля и, при включённой интеграции, пересчёт TOC через LibreOffice.
- `/fonts/list` — отдаёт список доступных шрифтов (семейства) на основе содержимого директории `fonts/`.

### 6.2. UI: управление стилями

В `gutendocx/web/static/index.html` реализованы блоки:

- **Override Body style** — задаёт оверрайды для основного текста:
  - family, size, line spacing, bold/italic, alignment и т.п.;
  - в `collectStyles()` отправляются только **заданные** пользователем свойства.
- **Override Chapter Headings style** — отдельный блок для заголовков (Heading1/Heading2), синхронизирован с `style_overrides.Headings`.
- **Override Page Number style** — новый блок:
  - `Family` + выпадающий список шрифтов (данные `/fonts/list`);
  - `Size (pt)` + пресеты размеров;
  - чекбоксы **Bold** / **Italic**.

Функция `collectStyles()` формирует JSON вида:

```json
{
  "body": { ... },
  "headings": { ... },
  "footer": {
    "font_family": "Times New Roman",
    "size_pt": 6.0,
    "italic": true
  },
  "specials": { ... }
}
```

Отправляемые поля зависят только от реально включённых переключателей `Override ...` и заполненных значений.

### 6.3. Обработка стилей на сервере (`web/server.py`)

В `whole_apply` и `cover_apply`:

- Из `req.styles` забираются блоки `body`, `headings`, `footer`, `specials`.
- Для каждого собирается новый словарь оверрайдов, **заполняющий только явные поля** (family, size_pt, bold, italic, all_caps и т.п.).
- Эти оверрайды сливаются в `cfg["style_overrides"]` и `cfg["special_overrides"]` и сохраняются через `save_config`.
- В частности, для Footer:

  ```python
  footer_ov = req.styles.get("footer")
  ...
  so["Footer"] = new_footer
  cfg["style_overrides"] = so
  ```

Далее `style_overrides.Footer` используется в `layout.apply_footer_styles` и/или `apply_sections_and_numbering` для оформления номера страницы.

### 6.4. Цепочка `whole.apply` → TOC → LibreOffice

При вызове `/whole/apply` с флагом обновления TOC:

1. `apply_whole_document`:
   - нормализует тело (Body/Headings/Specials);
   - гарантирует структуру обложка → пустая → тело;
   - настраивает секции и футеры (номера страниц).
2. `build_toc` вставляет/обновляет TOC‑поле в уже отнормированном документе.
3. `run_libreoffice_convert` в Docker‑режиме:
   - обновляет все индексы (включая TOC) через PyUNO;
   - сохраняет финальный DOCX и экспортирует PDF.
4. Для одиночных файлов и батча ZIP‑файл на скачивание включает **и DOCX, и PDF**.

Таким образом, пользователь может получить **полностью готовый DOCX + PDF с корректным оглавлением и нумерацией страниц** одним нажатием «Apply» (при включённой опции обновления TOC).

---

## 7. Нюансы совпадения страниц между Word и PDF

Даже при полном совпадении шрифтов возможны небольшие различия между версткой Word и LibreOffice:

- разные алгоритмы переноса строк и распределения абзацев;
- различия в кернинге и межсимвольных расстояниях;
- особенности реализации `lineRule="auto"` и других параметров интерлиньяжа;
- отличия в настройках widow/orphan control.

На практике:

- После синхронизации шрифтов (включая Calibri) и правки theme fonts количество страниц в DOCX и PDF стало **почти совпадать**, но возможна остаточная разница в пределах 1–2 страниц.
- Для целей **публикации** считается, что **PDF является каноничным источником истины** по нумерации страниц и TOC.
- DOCX остаётся редактируемой версией; при необходимости пользователь может вручную обновить поля TOC в Word.

---

## 8. Статус на 28 Nov 2025

### 8.1. Что реализовано

- **LibreOffice PyUNO‑пайплайн**:
  - `run_libreoffice_convert` в Docker‑режиме c PyUNO‑скриптом `lo_convert.py`.
  - Автоматический пересчёт TOC и экспорт PDF.
- **Кастомный Docker‑образ** `gutendocx/libreoffice:latest`:
  - базируется на `lscr.io/linuxserver/libreoffice:latest`;
  - устанавливает дополнительные системные шрифты;
  - копирует все шрифты из `fonts/` в `/usr/share/fonts/custom/` и обновляет кэш.
- **Синхронизация шрифтов**:
  - Algerian, Cambria, Castellar, Times New Roman, Calibri и др. доступны внутри контейнера;
  - `fix_theme_fonts` выравнивает theme fonts на Cambria.
- **Layout и нумерация**:
  - гарантированная пустая страница после обложки;
  - нумерация страниц тела с 3‑й страницы;
  - отсутствие номеров на обложке и пустой странице;
  - единый механизм применения стиля футера (Page Number style).
- **Web‑UI и API**:
  - оверрайды Body / Chapter Headings / Page Number + Special styles;
  - динамическая загрузка списка шрифтов через `/fonts/list`;
  - цепочка `/whole/apply` → `build_toc` → `run_libreoffice_convert` с выдачей DOCX+PDF в ZIP.

### 8.2. Что признано нерелевантным / устаревшим

- Подход с Basic‑макросом `UpdateTocAndExport` и фиксированным путём `/config/input.docx` **больше не используется** в рабочем пайплайне.
- Проверка headless‑запуска макросов в образе `lscr.io/linuxserver/libreoffice` показала ненадёжность/непредсказуемость; вместо этого используется **PyUNO‑скрипт** в отдельном контейнере.
- Детали по старому макрос‑ориентированному дизайну сохранены в `Integration_report 01.md` как исторический контекст.

---

## 9. Рекомендации по дальнейшему развитию

1. **Дополнительное тестирование на реальных документах**:
   - оценить статистику расхождений по количеству страниц между DOCX и PDF;
   - при необходимости подстроить `fix_theme_fonts` или дефолтные значения интерлиньяжа.
2. **UI‑подсказки**:
   - явно указывать пользователю, что TOC и нумерация в PDF считаются эталоном, а Word может показывать немного отличную разметку.
3. **Расширение настроек нумерации**:
   - вынести `body_start_number` в `config.yaml` явно (например, `layout.numbering.body_start_number: 3`) и отразить его в UI.
4. **Monitoring/Logging**:
   - при массовой обработке документов сохранять агрегированную статистику по:
     - количеству страниц в Word vs PDF;
     - времени работы PyUNO/LibreOffice;
     - ошибкам обновления индексов.

Этот отчёт заменяет собой `Integration_report 01.md` в части описания **актуальной** архитектуры и реализации. Для глубокой истории экспериментов с Basic‑макросами и профилем LibreOffice следует обращаться к версии 01.
