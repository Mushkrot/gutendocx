from docx import Document

from gutendocx.core.config import save_config
from gutendocx.web import server


def test_partial_body_ui_override_preserves_saved_body_size_only():
    cfg = {
        "style_overrides": {
            "Body": {
                "font": "Cambria",
                "size_pt": 12.0,
                "align": "left",
                "line_spacing": 1.08,
                "bold": False,
                "italic": False,
            }
        }
    }

    server._merge_ui_style_overrides(cfg, {"body": {"align": "justify"}})

    assert cfg["style_overrides"]["Body"] == {"size_pt": 12.0, "align": "justify"}


def test_body_ui_override_replaces_only_explicit_fields():
    cfg = {
        "style_overrides": {
            "Body": {
                "font": "Cambria",
                "size_pt": 18.0,
                "align": "left",
            }
        }
    }

    server._merge_ui_style_overrides(
        cfg,
        {
            "body": {
                "family": "Times New Roman",
                "size_pt": 12,
            }
        },
    )

    assert cfg["style_overrides"]["Body"] == {"font": "Times New Roman", "size_pt": 12.0}


def test_whole_apply_partial_body_payload_preserves_saved_size(tmp_path):
    doc_path = tmp_path / "sample.docx"
    doc = Document()
    doc.add_paragraph("Body text")
    doc.save(str(doc_path))

    config_path = tmp_path / "config.yaml"
    save_config(
        {
            "style_overrides": {
                "Body": {
                    "font": "Cambria",
                    "size_pt": 12.0,
                    "align": "left",
                    "line_spacing": 1.08,
                }
            },
            "body_style_normalization": {"enabled": False},
            "word_cleanup": {"enabled": False, "patterns": [], "replacement": "^p"},
            "output": {"dir": str(tmp_path / "out"), "versioning": False},
        },
        str(config_path),
    )

    result = server.whole_apply(
        server.ApplyRequest(
            input=str(doc_path),
            config_path=str(config_path),
            styles={"body": {"align": "justify"}},
            update_toc=False,
            apply_body=True,
            apply_cover=False,
        ),
        None,
    )

    assert result["whole"]["body_overrides"]["changes"] == {
        "size_pt": 12.0,
        "alignment": "justify",
    }
