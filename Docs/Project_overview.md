# GutenDocx: Обзор проекта и архитектуры

**Версия:** 2025‑12‑01  
**Назначение:** внутренний технический обзор для разработчиков

Этот документ даёт целостную картину проекта **GutenDocx**:

- что именно делает система;
- как она эволюционировала от чистого OpenXML‑пайплайна до текущей архитектуры с LibreOffice и Web‑интерфейсом;
- как устроены основные модули (`core`, `web`, интеграция с LibreOffice, конфигурация `config.yaml`).

Для детальной истории и low‑level деталей см. также:

- `Docs/PRD.md` — изначальный Product Requirements Document (DOCX‑нормализатор, без LibreOffice и PDF).
- `Docs/Integration_report 01.md` — исторический отчёт о первой попытке интеграции LibreOffice через Basic‑макрос.
- `Docs/Integration_report 02.md` — актуальный дизайн интеграции LibreOffice через PyUNO и Docker.

---

## 1. Цель и общая идея проекта

GutenDocx — это модульный **DOCX‑пайплайн** для книг/манускриптов (в т.ч. из Project Gutenberg), который:

- выполняет **Pre‑Scan** стилей и структуры документа;
- нормализует стили и разметку (Body, Heading1/2/3, специальные inline‑стили);
- строит стандартный **layout**: титульная страница, пустая страница, тело документа с нумерацией;
- вставляет и обновляет поле **Table of Contents (TOC)**;
- в текущей архитектуре — серверно пересчитывает оглавление и экспортирует **PDF** через LibreOffice.

Основные принципы:

- ядро — чистый **OpenXML** (через `python-docx` и `lxml`), без COM‑автоматизации MS Word;
- конфигурация через YAML (`config.yaml` + встроенный `gutendocx/configs/default_config.yaml`);
- возможность как **CLI**, так и **Web‑UI** поверх одного и того же ядра;
- переносимость между macOS/Windows (ядро) и серверной Linux‑инфраструктурой (LibreOffice Docker).

---

## 2. Эволюция проекта (краткая история)

### 2.1. Старт: чистый DOCX→DOCX без LibreOffice

Начальный дизайн (описан в `Docs/PRD.md`):

- только OpenXML‑манипуляции:
  - генерация титульной страницы и пустой второй страницы;
  - секции A/B/C (cover / blank / body);
  - нумерация страниц, вставка полей `{ PAGE }` и при необходимости `{ NUMPAGES }`;
  - нормализация стилей через конфигурацию.
- никакой зависимости от LibreOffice / Word automation;
- целевой формат — только **DOCX**, без гарантированного серверного PDF.

### 2.2. Веб‑сервер и Web‑UI

Затем поверх ядра появился **FastAPI‑сервер** и статический Web‑клиент:

- `gutendocx/web/server.py` — HTTP‑API (анализ/применение обложки, всего документа, TOC, стили, шрифты и т.п.).
- `gutendocx/web/static/index.html` — одностраничное Web‑приложение:
  - загрузка файлов и batch‑обработка;
  - настройка стилей через UI;
  - отдельные шаги Cover / Whole / TOC.

### 2.3. Первая попытка LO‑интеграции (Basic‑макрос, устарело)

Историческая ветка, подробно описана в `Docs/Integration_report 01.md`:

- использовался Docker‑образ `lscr.io/linuxserver/libreoffice:latest`;
- был написан Basic‑макрос `UpdateTocAndExport` в `Standard.Module1`, который должен был:
  - открыть документ, обновить индексы (включая TOC), сохранить DOCX, экспортировать PDF;
- пробовали разные варианты передачи пути к документу (аргумент макроса, переменная окружения, файл `doc_path.txt`, константа `/config/input.docx`).

Вывод: макрос работал из GUI (через VNC), но **не запускался надёжно в headless‑режиме** при вызове `soffice --headless ...` в этом образе. В итоге подход признан ненадёжным и заменён.

### 2.4. Текущая архитектура LO‑интеграции (PyUNO + Docker)

Актуальный дизайн (см. `Docs/Integration_report 02.md`):

- отдельный PyUNO‑скрипт `gutendocx/scripts/lo_convert.py` внутри контейнера LibreOffice;
- вспомогательная функция `gutendocx/core/libreoffice_toc.py::run_libreoffice_convert`:
  - готовит входной DOCX;
  - запускает headless‑LibreOffice + PyUNO‑скрипт;
  - получает обратно обновлённый DOCX и PDF;
- кастомный Docker‑образ `gutendocx/libreoffice:latest`:
  - основан на `lscr.io/linuxserver/libreoffice:latest`;
  - доустанавливает системные шрифты;
  - копирует пользовательские шрифты из `fonts/` и перестраивает font‑cache.

Таким образом, текущий пайплайн умеет **серверно пересчитывать TOC и экспортировать PDF**, обходясь без Basic‑макросов.

---

## 3. Структура репозитория (high‑level)

Основные директории (по состоянию на 2025‑12‑01):

- `Simples/` — примерные DOCX из Project Gutenberg и прочие тестовые файлы.
- `gutendocx/` — основной Python‑код:
  - `gutendocx/core/` — ядро пайплайна:
    - `toc.py` — вставка TOC‑поля (`build_toc`).
    - `layout.py` / `whole.py` — секции, нумерация, тело документа, футеры.
    - `libreoffice_toc.py` — интеграция с LibreOffice (`run_libreoffice_convert`).
    - другие модули (`scan`, `cover`, и т.д.).
  - `gutendocx/web/` — Web‑сервер и статика:
    - `server.py` — FastAPI‑приложение, основные endpoint’ы.
    - `static/index.html` — SPA‑клиент (HTML + JS).
  - `gutendocx/scripts/lo_convert.py` — PyUNO‑скрипт для обновления TOC и экспорта PDF.
- `docker/libreoffice/` — Dockerfile и вспомогательные файлы для кастомного LO‑образа.
- `fonts/` — пользовательские шрифты (Algerian, Cambria, Castellar, Times New Roman, Calibri и т.д.).
- `output/` — результирующие файлы (DOCX/PDF/ZIP).
- `Docs/` — документация (`PRD.md`, `Integration_report 01/02.md`, `macro.bas`, `Project_overview.md` и др.).
- `config.yaml` — основной пользовательский конфиг проекта.

---

## 4. Пайплайны обработки документов (end‑to‑end)

Высокоуровневый сценарий (через Web‑UI):

1. Пользователь загружает один или несколько DOCX через `index.html`.
2. Сервер сохраняет файлы в рабочий каталог (`/files/upload`) и выставляет `inputPath`.
3. В зависимости от сценария, UI вызывает:
   - `/cover/analyze` → `/cover/apply` — работа только с обложкой.
   - `/whole/analyze` → `/whole/apply` — работа с телом документа.
   - `/toc/apply` — вставка TOC‑поля и, при опции auto‑update, запуск LibreOffice.
4. В результате пользователь получает:
   - обновлённый DOCX (нормализованный layout, стили, TOC);
   - и/или PDF, пересчитанный через LibreOffice.

CLI‑сценарии концептуально аналогичны (см. идеи в `Docs/PRD.md`), но в текущем репозитории фокус смещён на Web‑режим и серверную интеграцию.

---

## 5. Интеграция LibreOffice (актуальный дизайн)

Ключевые элементы:

- `gutendocx/core/libreoffice_toc.py::run_libreoffice_convert`:
  - принимает `input_path`, `out_dir`, флаги `use_docker`, `docker_image` и т.п.;
  - выполняет предварительную правку theme‑шрифтов через `fix_theme_fonts(...)` (Cambria вместо Calibri и др.);
  - в Docker‑режиме:
    - поднимает временный контейнер LibreOffice (образ `gutendocx/libreoffice:latest`);
    - пробрасывает во внутрь PyUNO‑скрипт `lo_convert.py` и входной DOCX (`/tmp/input.docx`);
    - запускает headless‑LibreOffice с UNO‑сокетом и вызывает `lo_convert.py`;
    - забирает обратно обновлённый DOCX и PDF в `out_dir`;
  - в host‑режиме использует `soffice --headless --convert-to ...` как fallback.

- `gutendocx/scripts/lo_convert.py` (выполняется внутри контейнера):
  - подключается к UNO‑сокету LibreOffice;
  - скрыто открывает `/tmp/input.docx`;
  - обновляет все DocumentIndexes (включая TOC);
  - сохраняет DOCX и экспортирует `/tmp/output.pdf`.

- Конфигурация в `config.yaml` (раздел `toc.libreoffice`):

  ```yaml
  toc:
    levels: 1-2
    libreoffice:
      use_docker: true
      docker_image: gutendocx/libreoffice:latest
      timeout: 120
  ```

- Результат `run_libreoffice_convert` возвращается в виде словаря с полями `ok`, `output_path`, `pdf_output_path`, `stdout`, `stderr`, `returncode` и т.п.

---

## 6. Layout, нумерация страниц и футеры

Цель: обеспечить **стабильную структуру страниц** до передачи документа в LibreOffice, чтобы TOC и PDF строились на уже нормализованном DOCX.

Основные принципы (см. `Integration_report 02.md` и код `layout.py` / `whole.py`):

- Страница 1 — обложка (Title/Subtitle/Author), **без номера**.
- Страница 2 — пустая страница, по умолчанию **без номера** (но номер можно показывать по конфигу).
- Страница 3+ — основное тело документа, с номерами страниц, начиная с заданного `body_start_number` (обычно 3).

Ключевые функции:

- `ensure_blank_page_after_cover` — гарантирует ровно одну пустую страницу после обложки.
- `ensure_body_section_with_numbering` — приводит структуру секций к ожидаемому виду для верной нумерации.
- `apply_sections_and_numbering` (в `cover`‑пайплайне) — создаёт секции A/B/C и настраивает `w:pgNumType`.
- `apply_footer_styles` — очищает существующие футеры, применяет стиль Footer (номер страницы) к секции тела и вставляет поле PAGE.

Опции в `config.yaml` (упрощённый пример):

```yaml
layout:
  numbering:
    page2_start_value: 1       # исторический параметр, сейчас заменён более явным body_start_number
    print_on_page2: false      # печатать ли номер на второй (пустой) странице
  headers:
    show_numpages: false
  blank_page_after_cover: true
```

---

## 7. Web‑приложение и UI управления стилями

Фронтенд — `gutendocx/web/static/index.html` (plain HTML + JS). Основные блоки:

### 7.1. Загрузка файлов

- Скрытый `<input id="fileUpload" type="file" multiple>` + кнопка `Upload files…`:
  - ранее использовался `webkitdirectory`, что ломало UX на Windows; сейчас убрано, пользователь выбирает файлы напрямую;
  - в JS фильтруются только `.docx`, не‑DOCX пропускаются с информационным toast‑сообщением.

### 7.2. Управление областью применения и опциями

- `scopeCover` / `scopeBody` — какие части документа обрабатываются.
- Блок **Options**:
  - `vision` — включает AI Vision для детекции стилей обложки/тела.
  - `noLayout` — режим без layout‑изменений (safe‑mode).
  - `autoUpdateToc` — флаг **Update TOC after applying styles** (интеграция с LO в одном шаге Apply).

### 7.3. Cover styles

- Блок `Cover styles` с тремя `<details>`:
  - Title (`cardTitle`) — оверрайды для заголовка (шрифт, размер, bold, ALL CAPS, align).
  - Subtitle (`cardSubtitle`).
  - Author (`cardAuthor`).

### 7.4. Whole document (Body, Headings, Footer, Specials)

Внутри `Whole document`:

- **Body Text** (`cardBody` → `<details id="bodyDetails">`):
  - поля для `bodyFamily`, `bodySize`, `bodyLineSpacing`, `bodyAlign`, `bodyBold`, `bodyItalic`;
  - summary показывает Word‑style, выученный из документа (через `populateLearnedBodyStyles`).

- **Headings** (`cardHeadings` → `<details id="headingsDetails">`):
  - общий контейнер `headingsContainer`;
  - статически присутствует секция **Heading 1 (Chapters)** с полями `heading1Family`, `heading1Size`, `heading1Bold`, `heading1Italic`, `heading1AllCaps`;
  - динамически добавляются секции для Heading 2/3/4 на основе ответа `Learn Body Styles`:
    - показывается Word‑style‑имя, шрифт и размер;
    - для каждого уровня — чекбоксы `Bold`, `Italic`, `ALL CAPS`;
  - сбор оверрайдов выполняется функцией `collectHeadingStyles()`.

- **Footer / Page Number** (`cardFooter`):
  - оверрайды для стиля номера страницы в футере: `footerFamily`, `footerSize`, `footerBold`, `footerItalic`.

- **Specials** (`cardSpecials`):
  - список inline‑стилей (bold/italic и др.), найденных в теле;
  - позволяет задавать отдельные оверрайды для специфических стилей.

### 7.5. Learn Cover Styles / Learn Body Styles

- Кнопки `Learn Cover Styles` и `Learn Body Styles` вызывают:
  - `/config/learn_cover_styles` и `/config/learn_body_styles` в `web/server.py`;
  - результатom является набор стилей + обновлённый `config.yaml`;
  - UI обновляет placeholders и динамические секции (особенно для Headings/Body) через `populateLearnedBodyStyles` и `loadConfigDefaults`.

---

## 8. Конфигурация `config.yaml`

`config.yaml` — центральная точка настройки пайплайна. Основные секции (упрощённо):

- `layout` — секции, нумерация, пустая страница, опции футеров/хедеров.
- `roles` — мэппинг логических ролей (`Body`, `Heading1`, `Heading2`, `Title` и т.п.) на реальные styleId’ы в DOCX.
- `style_overrides` — оверрайды стилистики для ролей:
  - `Title`, `Subtitle`, `Author` (cover).
  - `Body` — основной текст.
  - `Headings` — общий стиль заголовков (применяется ко всем HeadingN через ядро).
  - `Footer` — стиль номера страницы в футере (шрифт, размер, bold/italic).
- `remap_rules` — правила глобального remap’а стилей (список «синонимов» для Body/Heading1/Heading2 с fallback‑стилем).
- `options` — флаги уровня нормализации/backup и т.п.
- `output` — директория для результатов, versioning.
- `toc.libreoffice` — параметры интеграции с LibreOffice (см. выше).

Взаимодействие с UI:

- Web‑клиент при `Apply` собирает объект `styles` (через `collectStyles()`), который содержит только **явно заданные пользователем** оверрайды.
- `web/server.py` аккуратно сливает эти оверрайды в `cfg["style_overrides"]` и сохраняет `config.yaml`;
- ядро (`whole.apply_whole_document`, `cover.run_cover_pipeline`) читает этот конфиг и применяет оверрайды к DOCX.

---

## 9. Текущий статус и ограничения

Сводно (по мотивам `Integration_report 02.md` и последних изменений):

**Реализовано:**

- Полный DOCX→DOCX пайплайн с нормализацией layout’а, секций и нумерации.
- Вставка и обновление TOC‑поля (`build_toc`).
- Интеграция с LibreOffice через PyUNO + Docker:
  - обновление индексов (включая TOC);
  - экспорт PDF.
- Кастомный LO‑образ с дополнительными шрифтами и поддержкой шрифтов из `fonts/`.
- Web‑UI с детальным управлением стилями Body/Headings/Footer и динамическим отображением выученных стилей.
- Опция **Update TOC after applying styles** в блоке Options, объединяющая применение стилей и LO‑шаг.
- Улучшенная UX загрузки файлов, в т.ч. на Windows (убран `webkitdirectory`, фильтрация происходит уже на стороне JS).

**Ограничения / моменты внимания:**

- Небольшие различия в верстке и количестве страниц между Word и LibreOffice возможны даже при совпадении шрифтов (разные алгоритмы переноса, кернинг и т.д.). В архитектуре принято считать **PDF итоговым эталоном** по TOC и нумерации.
- Пакетирование для финального Windows‑приложения (GUI/CLI‑бандл) описано на уровне PRD, но в данном репозитории основной фокус — сервер + Web‑UI.

---

## 10. Связанные документы

Для углубления по отдельным темам:

- **Общее видение и требования:**
  - `Docs/PRD.md`
- **Исторический отчёт по первой LO‑интеграции (Basic‑макрос, устарело):**
  - `Docs/Integration_report 01.md`
- **Текущая архитектура LO‑интеграции и layout’а:**
  - `Docs/Integration_report 02.md`
- **Артефакты LibreOffice‑макроса (история):**
  - `Docs/macro.bas`
- **Данный обзор:**
  - `Docs/Project_overview.md` — точка входа для разработчиков, дающая целостную картину проекта.
