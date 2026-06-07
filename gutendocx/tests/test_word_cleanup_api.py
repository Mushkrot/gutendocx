from gutendocx.web import server


def test_config_returns_word_cleanup_defaults(tmp_path):
    config_path = tmp_path / "config.yaml"

    data = server.get_config(config_path=str(config_path))

    assert data["ok"] is True
    assert data["word_cleanup"] == {
        "enabled": False,
        "patterns": [],
        "replacement": "^p",
    }
