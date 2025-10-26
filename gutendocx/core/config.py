import os
from typing import Any, Dict

try:
    import yaml  # type: ignore
except Exception as e:  # pragma: no cover
    # yaml is required for configuration handling
    raise RuntimeError("PyYAML is required to run gutendocx. Please install 'pyyaml'.") from e

try:
    from importlib import resources as importlib_resources  # Python 3.9+
except Exception:  # pragma: no cover
    import importlib_resources  # type: ignore


CONFIG_HEADER = (
    "# GutenDocx Configuration (project-level)\n"
    "# This file stores your current processing defaults for this project.\n"
    "# It was created automatically on first run from embedded defaults.\n"
    "# You may edit it manually or via the application UI; any changes here\n"
    "# become the defaults for subsequent runs.\n"
    "# Location: project root (same level as 'Simples' and 'reports').\n\n"
)


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = dict(base)
    for k, v in (override or {}).items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _read_default_yaml_text() -> str:
    pkg = "gutendocx.configs"
    name = "default_config.yaml"
    with importlib_resources.files(pkg).joinpath(name).open("r", encoding="utf-8") as f:
        return f.read()


def _read_default_config_dict() -> Dict[str, Any]:
    text = _read_default_yaml_text()
    return yaml.safe_load(text) or {}


def write_default_config(path: str) -> str:
    """Create a project-level config.yaml with header and defaults if missing.

    Returns the absolute path to the config file.
    """
    abs_path = os.path.abspath(path)
    if not os.path.exists(abs_path):
        os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
        default_text = _read_default_yaml_text()
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(CONFIG_HEADER)
            f.write(default_text)
    return abs_path


def load_config(path: str | None = None) -> Dict[str, Any]:
    """Load configuration with merge order: project > embedded defaults.

    If project config does not exist, it will be created from defaults
    (with an explanatory header) and then loaded.
    """
    defaults = _read_default_config_dict()

    cfg_path = os.path.abspath(path or os.path.join(os.getcwd(), "config.yaml"))
    if not os.path.exists(cfg_path):
        write_default_config(cfg_path)

    with open(cfg_path, "r", encoding="utf-8") as f:
        project_cfg = yaml.safe_load(f) or {}

    merged = _deep_merge(defaults, project_cfg)
    return merged
