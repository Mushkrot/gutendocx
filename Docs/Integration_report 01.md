# GutenDocx: интеграция LibreOffice для пересчёта оглавлений

## 1. Исходное состояние проекта

### 1.1. Архитектура до начала работ по LibreOffice

- В корне проекта `gutendocx` есть каталоги:
  - `Simples/` — набор тестовых DOCX из Gutenberg.
  - `gutenberg/` — исходные тексты.
  - `gutendocx/` — основной Python‑код.
  - `output/` — результирующие файлы.
- Конфигурация: `config.yaml` + встроенный `gutendocx/configs/default_config.yaml`.
- Основные компоненты:
  - `gutendocx/core/toc.py::build_toc` — вставка поля оглавления (Word TOC) в DOCX на основе стилей Heading1/Heading2 и др.
  - `gutendocx/core/scan.py` — прескан стилей и структуры.
  - `gutendocx/core/cover.py` — генерация и нормализация титульного листа.
  - `gutendocx/web/server.py` — HTTP API (FastAPI), в т.ч. endpoint `/toc/apply`.
  - `gutendocx/app/cli.py` — CLI `gutendocx` (команда `libreoffice-toc` уже существовала, но без Docker‑интеграции).

### 1.2. Поведение до интеграции LibreOffice

- `build_toc`:
  - Загружает DOCX через абстракцию `Loader`.
  - При необходимости применяет эвристики по заголовкам.
  - Удаляет существующие TOC (`remove_existing_toc`).
  - Вставляет поле TOC (`insert_word_toc`).
  - Сохраняет документ в `output/` (с учётом версионирования, если включено).
- После этого документ **содержит поле TOC, но оглавление НЕ пересчитано**. Пересчёт ожидается в Word / LibreOffice на стороне пользователя.
- Endpoint `/toc/apply` выполняет только шаг `build_toc` и возвращает путь к DOCX с полем TOC. Пересчёт поля и экспорт PDF — вне сервера.

### 1.3. Рабочая система «до пересчёта оглавлений»

На этом уровне система уже была работоспособна:

- CLI и веб‑сервер могли:
  - принять DOCX;
  - просканировать стили;
  - сгенерировать титул;
  - вставить поле TOC;
  - отдать обновлённый DOCX.
- Но не было серверного шага, который:
  - обновляет все поля/оглавления (UpdateAllIndexes);
  - экспортирует PDF.

Именно на этой границе функционала мы «заморозили» исходную рабочую систему и начали эксперименты с LibreOffice.


## 2. Цель изменений

**Цель:** добавить в пайплайн шаг с LibreOffice, который на сервере:

1. Открывает результат `build_toc`.
2. Выполняет команду `UpdateAllIndexes` (пересчёт всех индексов, включая TOC).
3. Сохраняет DOCX.
4. Экспортирует PDF рядом с DOCX.

Требование: этот шаг должен работать либо:

- через установленный на сервере `soffice` (host‑mode), либо
- через Docker‑контейнер с LibreOffice (`linuxserver/libreoffice`) без необходимости установки LibreOffice в хостовой среде.


## 3. Базовая реализация без Docker

В модуле `gutendocx/core/libreoffice_toc.py` уже был реализован helper:

```python
def run_libreoffice_convert(
    input_path: str,
    soffice: str = "soffice",
    out_dir: Optional[str] = None,
    timeout: int = 120,
    use_docker: bool = False,
) -> Dict[str, Any]:
```

- При `use_docker = False` он вызывал:

  ```bash
  soffice --headless --convert-to docx --outdir <out_dir> <input_path>
  ```

- Это пересчитывало документ и сохраняло новый DOCX, но **не вставляло и не обновляло TOC** (так как сам TOC вставлялся в `build_toc`).
- Поддержка Docker в этом helper‑е была добавлена в рамках текущих работ.


## 4. Новый feature‑branch и общая идея Docker‑интеграции

Была создана отдельная ветка (feature‑ветка для интеграции LibreOffice через Docker; точное имя можно посмотреть в `git branch -a` на репозитории).

### 4.1. Планируемая архитектура

1. Использовать образ `lscr.io/linuxserver/libreoffice:latest`:
   - web/VNC‑доступ по портам `3000` и `3001` (HTTP‑интерфейс KasmVNC);
   - поддержка `soffice` внутри контейнера.
2. Смонтировать:
   - каталог проекта как `/data` (чтобы `soffice` видел DOCX);
   - отдельный каталог конфигурации LibreOffice как `/config` (персистентный профиль с макросами).
3. Внутри профиля (`/config`) разместить пользовательский Basic‑макрос `Standard.Module1.UpdateTocAndExport`, который:
   - принимает путь к DOCX (первоначальный дизайн: параметр `sDocPath`);
   - выполняет `UpdateAllIndexes`;
   - сохраняет DOCX;
   - экспортирует PDF рядом с DOCX.
4. Вызывать макрос из Python (через Docker) командой вида:

   ```bash
   docker run --rm \
     -v <project_root>:/data \
     -v <project_root>/.config-libreoffice:/config \
     -w /data \
     lscr.io/linuxserver/libreoffice:latest \
     soffice --headless --invisible \
       "macro:///Standard.Module1.UpdateTocAndExport(/data/relative/path/to.docx)"
   ```

5. Обернуть эту логику в `run_libreoffice_convert(..., use_docker=True)` и использовать из:
   - CLI‑команды `libreoffice-toc`;
   - HTTP‑endpoint `/toc/apply` (через конфиг `toc.libreoffice.use_docker = true`).


## 5. Настройка LibreOffice‑контейнера и профиля

### 5.1. Поднятие контейнера LibreOffice

- Запущен контейнер:

  ```bash
  docker run -d \
    --name=libreoffice \
    -e PUID=1000 -e PGID=1000 \
    -e TZ=Etc/UTC \
    -p 3000:3000 -p 3001:3001 \
    -v /ai/gutendocx/.config-libreoffice:/config \
    lscr.io/linuxserver/libreoffice:latest
  ```

- Подключение по VNC из браузера:
  - в VS Code порт `3000` проброшен на локальный `localhost:3000`;
  - доступ через `http://localhost:3000`.

### 5.2. Первый вариант макроса в LibreOffice (GUI)

Через VNC в LibreOffice Basic IDE был создан макрос `UpdateTocAndExport` в `My Macros → Standard → Module1` (файл `Module1.xba` в профиле):

- Сигнатура: `Sub UpdateTocAndExport(sDocPath As String)`.
- Логика:
  1. Если `sDocPath = ""` — `Exit Sub`.
  2. `StarDesktop.loadComponentFromURL(ConvertToURL(sDocPath), "_blank", 0, Array())`.
  3. Через `DispatchHelper` — `.uno:UpdateAllIndexes`.
  4. `oDocument.store()`.
  5. Экспорт PDF через `storeToURL`:

     ```basic
     GlobalScope.BasicLibraries.LoadLibrary("Tools")
     sPdfPath = GetFileNameWithoutExtension(sDocPath) & ".pdf"
     oDocument.storeToURL(ConvertToURL(sPdfPath), props())
     ```

Этот код был сохранён в профиле LibreOffice и работал **при ручном запуске из GUI**.

### 5.3. Связка `macro.bas` ↔ профиль

- На хосте был создан файл `Docs/macro.bas` с тем же кодом для удобного редактирования.
- Для переноса в профиль использовалась схема:
  1. Копировать `Docs/macro.bas` в `/config/macro.bas`.
  2. В GUI LibreOffice открывать `/config/macro.bas`, копировать содержимое в Module1 и сохранять.

Позже, для автоматизации, мы напрямую редактировали файл профиля
`/.config-libreoffice/.config/libreoffice/4/user/basic/Standard/Module1.xba`.


## 6. Попытка вызова макроса из Docker (первый раунд)

### 6.1. Вызов с параметром пути

Была реализована команда (как вручную, так и через `run_libreoffice_convert`):

```bash
docker run --rm \
  -v /ai/gutendocx:/data \
  -v /ai/gutendocx/.config-libreoffice:/config \
  -w /data \
  lscr.io/linuxserver/libreoffice:latest \
  soffice --headless --invisible \
    "macro:///Standard.Module1.UpdateTocAndExport(/data/Simples/test_LO.docx)"
```

Факты:

- `soffice` завершался с кодом `0` (ошибок в CLI не видно).
- В каталоге `Simples/` **не появлялся PDF**, DOCX не менялся.
- Вывода, указывающего на работу макроса, не было.

Предположение: при таком вызове параметр в скобках **не передаётся в Basic**, и вызов происходит как будто `UpdateTocAndExport()` без аргументов → `sDocPath = ""`, срабатывает `If sDocPath = "" Then Exit Sub` и макрос сразу завершается.


## 7. Переход к передаче пути через окружение / файл

### 7.1. Вариант с `Optional sDocPath` + `Environ("DOC_PATH")`

Мы изменили макрос:

- `Sub UpdateTocAndExport(Optional sDocPath As String)`.
- Если `sDocPath = ""`, то `sDocPath = Environ("DOC_PATH")`.
- В Docker‑команде стали передавать `-e DOC_PATH=/data/Simples/test_LO.docx` и вызывать макрос без параметров.

Результаты:

- `soffice` по‑прежнему возвращал `0`.
- Ни PDF, ни изменений в DOCX.

Через отдельный тест `docker run ... env | grep DOC_PATH` было установлено, что переменная окружения `DOC_PATH` **не доходит до процесса `soffice`** внутри образа linuxserver (судя по запуску через их init‑обвязку).

### 7.2. Логирование через `/config/macro.log`

Чтобы понять, вызывается ли макрос вообще, мы добавили в код:

```basic
nLog = FreeFile
On Error Resume Next
Open "/config/macro.log" For Append As #nLog
Print #nLog, "----"
Print #nLog, "DOC_PATH=" & Environ("DOC_PATH")
Print #nLog, "sDocPath=" & sDocPath
Close #nLog
On Error GoTo 0
```

Наблюдения:

- При **ручном запуске макроса через GUI** лог появлялся (для других вариантов кода).
- При запуске из Docker `macro.log` **не создавался вовсе**, что указывало: Basic‑код не исполняется.


## 8. Поиск реального местоположения макроса (Module1.xba)

Текущее редактирование через `/config/macro.bas` не гарантировало, что CLI‑`soffice` использует именно этот код. Поиск строк `UpdateTocAndExport` внутри профиля дал путь:

```text
.config/libreoffice/4/user/basic/Standard/Module1.xba
```

Файл `Module1.xba` содержал старую версию макроса (с параметром `sDocPath` и использованием библиотеки `Tools`).

Был выполнен прямой патч `Module1.xba`, чтобы его содержимое соответствовало новому варианту макроса (с фиксированным путём и логированием).

Тем не менее, при последующих CLI‑запусках через Docker `macro.log` всё равно не появлялся — т.е. **даже обновлённый `Module1.xba` не приводил к выполнению кода при headless‑вызове**.


## 9. Вариант с `doc_path.txt` и отказ от окружения

Мы попытались полностью уйти от окружения и параметров и читать путь к документу из файла:

- В макросе:

  ```basic
  sDocPath = ""
  On Error Resume Next
  nFile = FreeFile
  Open "/config/doc_path.txt" For Input As #nFile
  Line Input #nFile, sDocPath
  Close #nFile
  On Error GoTo 0
  ```

- На хосте создавался `/ai/gutendocx/.config-libreoffice/doc_path.txt` с путём `/data/Simples/test_LO.docx`.
- В контейнере `/config/doc_path.txt` был доступен.

Однако лог‑записи показывали, что `sDocPath` остаётся пустым (когда лог вообще появлялся), а чаще `macro.log` вообще не создавался.

Позже было обнаружено, что внутри linuxserver‑контейнера `/data` **не содержит директории `Simples/`**, а реальная рабочая директория с профилем — `/config`. Это ещё раз подтвердило, что наш дизайн с `/data/...` не соответствует реальному окружению headless‑процесса.


## 10. Финальный дизайн макроса: фиксированный `/config/input.docx`

Учитывая проблемы с окружением/путями, мы перешли к максимально простому варианту:

- Макрос не принимает аргументов и не читает окружение/файлы с путём.
- Всегда работает с фиксированным путём:

  ```basic
  Const INPUT_PATH As String = "/config/input.docx"
  ```

- Полный алгоритм:
  1. Записать в лог `INPUT_PATH` (в `/config/macro.log`).
  2. Открыть документ `INPUT_PATH`.
  3. `UpdateAllIndexes` через `DispatchHelper`.
  4. `store()` (сохранить DOCX).
  5. Посчитать `sPdfPath` как `INPUT_PATH` с заменой расширения на `.pdf`.
  6. Записать в лог `sPdfPath`.
  7. `storeToURL` в PDF.

Были синхронизированы три файла:

- `Docs/macro.bas` — эталонная версия.
- `/ai/gutendocx/.config-libreoffice/macro.bas` — файл для копирования в LO.
- `/ai/gutendocx/.config-libreoffice/.config/libreoffice/4/user/basic/Standard/Module1.xba` — реальный модуль профиля, отредактированный напрямую.


## 11. Тесты фиксированного пути и поведение образа linuxserver/libreoffice

### 11.1. Подготовка входного файла

- На хосте: `cp Simples/test_LO.docx .config-libreoffice/input.docx`.
- В контейнере через `docker run -v .config-libreoffice:/config` файл доступен как `/config/input.docx`.

### 11.2. Запуск макроса из Docker

Команды, которые мы пробовали:

1. Классический вариант:

   ```bash
   docker run --rm \
     -v /ai/gutendocx/.config-libreoffice:/config \
     lscr.io/linuxserver/libreoffice:latest \
     soffice --headless --invisible \
       "macro:///Standard.Module1.UpdateTocAndExport"
   ```

2. Альтернативный URL:

   ```bash
   docker run --rm \
     -v /ai/gutendocx/.config-libreoffice:/config \
     lscr.io/linuxserver/libreoffice:latest \
     soffice --headless \
       "vnd.sun.star.script:Standard.Module1.UpdateTocAndExport?language=Basic&location=application"
   ```

Факты:

- Во всех случаях процесс `soffice` завершался без ошибки (return code 0).
- В `/config` оставался только `input.docx` и `macro.bas` (PDF не появлялся).
- `macro.log` **не создавался**, несмотря на то что мы редактировали и `Module1.xba`.

Вывод: **headless‑вызов `soffice` в образе `lscr.io/linuxserver/libreoffice` не выполняет макросы из `My Macros/Standard.Module1` (по крайней мере, в контексте `location=application`)**, даже если профиль и код корректно развернуты.

При этом через GUI (VNC, ручной запуск макроса по открытому документу) макрос выполняется штатно.


## 12. Сопутствующие изменения в Python‑коде

### 12.1. `run_libreoffice_convert`

В процессе экспериментов функция `run_libreoffice_convert` расширялась/менялась:

- Добавлена ветка `use_docker=True` с построением команды Docker.
- Изначально туда закладывался вызов макроса с аргументом пути и передачей DOC_PATH через `-e`.
- В текущем состоянии (на момент фиксации) код `run_libreoffice_convert` всё ещё ориентирован на старый дизайн с `/data` и `DOC_PATH`, а не на финальный вариант с `/config/input.docx`. Это нужно будет аккуратно синхронизировать при выборе дальнейшей стратегии.

### 12.2. Endpoint `/toc/apply`

В `gutendocx/web/server.py` endpoint `/toc/apply`:

- После `build_toc` читает из конфигурации секцию `toc.libreoffice`:

  ```yaml
  toc:
    libreoffice:
      use_docker: true
      binary: soffice
      dir: output/lo_toc
      subdir: lo_toc
      timeout: 120
  ```

- В зависимости от настроек вызывает `run_libreoffice_convert` с `use_docker=True/False`.
- Также в ответе API предусмотрено поле `pdf_output_path` для PDF, возвращаемого LibreOffice.

На практике, из‑за описанных выше проблем с Docker‑макросом, **этот шаг пока не даёт PDF** и, при включённом Docker, фактически не выполняет пересчёт оглавлений.


## 13. Что получилось и что не получилось

### 13.1. Удалось

- **Стабильно работает базовый пайплайн GutenDocx до вставки поля TOC**:
  - `build_toc` формирует корректное поле оглавления (Word TOC field) на основе стилей.
  - `/toc/apply` даёт DOCX с полем TOC.
- Развернут и настроен контейнер `lscr.io/linuxserver/libreoffice`:
  - доступ по VNC;
  - сохранение пользовательского профиля в `.config-libreoffice`.
- Реализован и отлажен Basic‑макрос `UpdateTocAndExport` в GUI LibreOffice:
  - умеет обновлять индексы и экспортировать PDF для выбранного документа;
  - может быть привязан к фиксированному пути `/config/input.docx`.
- Понята структура профиля LibreOffice:
  - где лежат макросы (`.config/libreoffice/4/user/basic/Standard/Module1.xba`);
  - как переносить код из файлов хоста (`macro.bas`) в профиль.

### 13.2. Не удалось (на текущем этапе)

- **Надёжно запускать этот макрос из headless‑CLI внутри образа linuxserver/libreoffice**:
  - Вызывали и `macro:///Standard.Module1.UpdateTocAndExport`, и `vnd.sun.star.script:...location=application`.
  - Меняли сигнатуры, параметры, способ передачи пути (`arg`, `Environ`, `doc_path.txt`, константа `INPUT_PATH`).
  - Правили как `macro.bas`, так и `Module1.xba` и права на профиль.
  - Во всех вариантах CLI‑запуска `macro.log` не создаётся, PDF нет, код макроса явно не исполняется.

Основная гипотеза: документация/реализация linuxserver‑образа инициализирует LibreOffice в таком режиме, что вызовы макросов из `My Macros` (
`location=application`) либо запрещены политикой безопасности, либо происходят в другом профиле, отличном от `/config`.


## 14. Текущий статус системы

1. **Рабочая часть (старая):**
   - `build_toc` и все операции до вставки поля TOC.
   - HTTP‑endpoint `/toc/apply` как минимум гарантированно возвращает DOCX с полем оглавления.

2. **Новая часть (в ветке):**
   - Интеграция `run_libreoffice_convert` с Docker;
   - Поддержка конфигурации LibreOffice в `config.yaml`;
   - Макрос `UpdateTocAndExport` в профиле LibreOffice;
   - Набор скриптов и файлов в `.config-libreoffice`.

3. **Ограничение:**
   - Автоматический пересчёт оглавлений и экспорт PDF **не работают в headless‑режиме** через образ `lscr.io/linuxserver/libreoffice`.
   - Рабочий сценарий с макросом возможен только при ручном запуске через VNC.


## 15. Основная сложность на данный момент

Основная проблема — **несоответствие ожиданий по работе макросов в headless‑режиме конкретного Docker‑образа**:

- Мы можем:
  - управлять содержимым профиля (`/config` → `.config/libreoffice/...`),
  - запускать GUI LibreOffice и руками выполнять макрос,
  - видеть, что `Module1.xba` содержит нужный код.
- Но мы **не можем добиться**, чтобы `soffice --headless ...` внутри этого образа запускал Basic‑макрос из профиля, даже при прямом `vnd.sun.star.script`‑URL и обновлённом `Module1.xba`.

Это делает автоматизацию через данный образ ненадёжной. Продолжать обходными путями (через окружение, файлы, разные URL) не имеет смысла — потребуются либо:

- смена образа LibreOffice (на более «чистый» CLI‑ориентированный), либо
- иной механизм пересчёта оглавлений (UNO‑bridge, Office‑365 API, библиотеки уровня Aspose и т.п.), либо
- сознательное принятие ручного шага (оператор по VNC запускает макрос), если это допустимо бизнес‑процессом.


## 16. Варианты дальнейшего развития (для архитектурного решения)

1. **Оставить LibreOffice‑шаг ручным:**
   - Сервер по‑прежнему выполняет только `build_toc`.
   - Оператор (или отдельный сервис) по VNC открывает `/config/input.docx`, запускает макрос `UpdateTocAndExport`, а затем сохраняет результаты.
   - Подходит, если объёмы небольшие и допустим человек в контуре.

2. **Сменить Docker‑образ LibreOffice:**
   - Использовать более «чистый» образ, без тяжёлой KasmVNC‑обвязки, где можно гарантированно вызвать макросы из CLI.
   - Потребуется:
     - повторная настройка профиля;
     - проверка команд `soffice --headless "vnd.sun.star.script:..."`;
     - адаптация `run_libreoffice_convert` под новое расположение файлов (volume‑маппинг может отличаться).

3. **Отказаться от Basic‑макроса в пользу чистого `--convert-to`:**
   - Проверить, достаточно ли для нашего сценария запустить:

     ```bash
     soffice --headless --convert-to pdf:writer_pdf_Export <docx>
     ```

   - На практике, во многих случаях LibreOffice при конвертации обновляет поля; но это не стопроцентно гарантировано и требует тестирования на реальных документах.

4. **UNO‑клиент или внешние сервисы:**
   - Использовать UNO‑API LibreOffice через отдельный сервис или Python‑клиент.
   - Или рассмотреть коммерческие библиотеки (Aspose Words, Spire.Doc и др.), которые умеют пересчитывать поля/TOC без GUI.

5. **Разделить задачи:**
   - GutenDocx по‑прежнему отвечает за подготовку структуры и вставку TOC.
   - За пересчёт и финальное форматирование отвечает отдельный специализированный сервис (LibreOffice‑based или другой), интегрированный через асинхронный пайплайн.

---

Этот отчёт отражает полный путь работ: от исходной рабочей системы (вставка поля TOC без пересчёта) до попыток автоматизировать пересчёт оглавлений и экспорт PDF через Docker‑контейнер LibreOffice, включая все ключевые решения, эксперименты и текущие ограничения.


Status on Nov 27, 2025 @ 13:00

## Status

- **Macro**: `UpdateTocAndExport` is already hard‑coded to `/config/input.docx` and mirrored in:
  - [Docs/macro.bas](cci:7://file:///ai/gutendocx/Docs/macro.bas:0:0-0:0)
  - [.config-libreoffice/macro.bas](cci:7://file:///ai/gutendocx/.config-libreoffice/macro.bas:0:0-0:0)
  - [.config-libreoffice/.config/libreoffice/4/user/basic/Standard/Module1.xba](cci:7://file:///ai/gutendocx/.config-libreoffice/.config/libreoffice/4/user/basic/Standard/Module1.xba:0:0-0:0)
- **Python side**: I’ve just aligned [run_libreoffice_convert](cci:1://file:///ai/gutendocx/gutendocx/core/libreoffice_toc.py:8:0-154:5) with this fixed path and wired input/output copying around Docker.

Both high‑priority TODOs are now implemented:

- **✅ macro-fixed-input-docx**
- **✅ update-run-libreoffice-convert-for-fixed-input**

The remaining open point is still architectural: whether `lscr.io/linuxserver/libreoffice` can truly run macros headless.

---

## What I changed in [run_libreoffice_convert](cci:1://file:///ai/gutendocx/gutendocx/core/libreoffice_toc.py:8:0-154:5)

In Docker mode (`use_docker=True`):

1. **Prepare `/config/input.docx` inside the mounted profile**

   - Compute `config_dir = <project_root>/.config-libreoffice`
   - Ensure it exists.
   - Copy the user’s input DOCX to:

     - Host: `<project_root>/.config-libreoffice/input.docx`
     - Container (via mount): `/config/input.docx`

   - Remove any stale `<project_root>/.config-libreoffice/input.pdf` before running.

2. **Run the container with the fixed‑path macro**

   ```python
   cmd = [
       "docker", "run", "--rm",
       "-v", f"{project_root}:/data",
       "-v", f"{config_dir}:/config",
       "-w", "/data",
       "lscr.io/linuxserver/libreoffice:latest",
       soffice,
       "--headless",
       "--invisible",
       "macro:///Standard.Module1.UpdateTocAndExport",
   ]
   ```

   - No env vars, no macro parameters; the macro just opens `/config/input.docx`.

3. **Copy results back out of [.config-libreoffice](cci:7://file:///ai/gutendocx/.config-libreoffice:0:0-0:0)**

   After `subprocess.run`:

   - Source paths:

     - DOCX: `<project_root>/.config-libreoffice/input.docx`
     - PDF: `<project_root>/.config-libreoffice/input.pdf`

   - Target paths in your requested `out_dir`:

     - DOCX: `<out_dir>/<base_root>.docx`
     - PDF: `<out_dir>/<base_root>.pdf`

   - If copying fails, an extra line is appended to `stderr` for easier debugging:
     - `"[run_libreoffice_convert] Failed to copy results from ..."`

4. **Return format**

   Unchanged API:

   - `ok`
   - `output_path` → `<out_dir>/<base_root>.docx` if present
   - `pdf_output_path` → `<out_dir>/<base_root>.pdf` or `.PDF` if present
   - `stdout`, `stderr`, `command`, `returncode`

Host (non‑Docker) mode remains the old `--convert-to docx` behavior.

---

## How to test end‑to‑end

### 1. Preconditions

- Your **LibreOffice profile inside the container** must already contain the updated macro (you did that in the GUI earlier):

  - `Standard.Module1.UpdateTocAndExport` with `INPUT_PATH = "/config/input.docx"`.

- Project root: [/ai/gutendocx](cci:7://file:///ai/gutendocx:0:0-0:0) (as before).
- Docker image: `lscr.io/linuxserver/libreoffice:latest` pulled / accessible.

### 2. Via `/toc/apply` (web server)

1. Ensure `config.yaml` has something like:

   ```yaml
   libreoffice:
     use_docker: true
     soffice_bin: soffice
   ```

2. Run the web server (whatever you usually use, e.g. `poetry run gutendocx web`).

3. Call `/toc/apply` from the UI or HTTP client with your DOCX.

4. After the request:

   - Check the response JSON:
     - `output_path` (post‑LibreOffice DOCX with updated fields)
     - `pdf_output_path` (if the macro exported successfully)
   - Check on disk:
     - DOCX/PDF under the LO output directory (e.g. `output/lo_toc/...`, depending on your config).
   - Inspect macro log:
     - File: `<project_root>/.config-libreoffice/macro.log`
     - You should see entries like:
       - `----`
       - `INPUT_PATH=/config/input.docx`
       - `Export sPdfPath=/config/input.pdf`

   - If `macro.log` is updated and `input.pdf` appears under [.config-libreoffice](cci:7://file:///ai/gutendocx/.config-libreoffice:0:0-0:0) but no file gets copied into your `out_dir`, the issue is in the Python side (copying) – which we can debug from `stderr`.

   - If **neither** `macro.log` nor `input.pdf` appears after the run, the container likely **never executed the macro** in headless mode (the limitation we saw earlier).

### 3. Via CLI (optional)

If you want a minimal repro from CLI instead of the web layer, we can add a small test command or you can temporarily call [run_libreoffice_convert](cci:1://file:///ai/gutendocx/gutendocx/core/libreoffice_toc.py:8:0-154:5) from a scratch script that sets `use_docker=True`. If you’d like, I can add a dedicated CLI subcommand `libreoffice-toc-docker-test` that:

- Takes a DOCX path,
- Calls [run_libreoffice_convert(..., use_docker=True)](cci:1://file:///ai/gutendocx/gutendocx/core/libreoffice_toc.py:8:0-154:5),
- Dumps `stdout/stderr` and the resulting paths.

---

## Next steps / open issues

- **Key unknown**: whether `lscr.io/linuxserver/libreoffice` will actually run `Standard.Module1.UpdateTocAndExport` in pure headless mode.  
  - If you run a `/toc/apply` now and still see **no macro.log / no input.pdf**, that’s strong evidence macros are blocked / not initialised without GUI.

- **If headless macros truly don’t work in this image**, the remaining TODO is:
  - Evaluate an alternative:
    - A more “plain” LibreOffice image where macros are known to work headlessly.
    - Or a UNO‑driven Python/Java service in a long‑lived container.

If you run a test now and paste:

- The JSON response from `/toc/apply`,
- Contents of `<project_root>/.config-libreoffice/macro.log` (if any),
- `stderr` from [run_libreoffice_convert](cci:1://file:///ai/gutendocx/gutendocx/core/libreoffice_toc.py:8:0-154:5) (or server logs around the call),