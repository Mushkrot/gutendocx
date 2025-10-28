conda run -p ./gutenberg python -m gutendocx cover Simples/pg69971.docx --vision --no-layout --report output/vision/pg69971_vision_g5.json

Заруск сервера:

eval 'conda run -p ./gutenberg uvicorn gutendocx.web.server:app --reload --port 8000'
