#!/bin/bash
# GutenDocx - режим разработки (с hot reload)

cd /ai/gutendocx

# Активируем conda окружение
source /root/miniforge3/etc/profile.d/conda.sh
conda activate /ai/gutendocx/gutenberg

# Запуск с hot reload
GUTENDOCX_FONTS_DIR=/ai/gutendocx/fonts \
  python -m uvicorn gutendocx.web.server:app \
    --reload \
    --host 0.0.0.0 \
    --port 8000
