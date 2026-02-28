"""ConfigManager: Lädt/speichert settings.json mit Default-Werten."""

import json
import os
from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULTS = {
    "input_directory": "",
    "output_directory": "",
    "jpeg_quality": 95,
    "confidence_threshold": 0.5,
    "padding_percent": 10,
    "watermark_mode": "manual",
    "watermark_percent": 0,
    "use_gpu": True,
    "max_workers": 4,
    "supported_formats": [".jpg", ".jpeg", ".png", ".bmp", ".webp"],
    "output_format": "original",
    "multi_detection_action": "ask",  # "ask" | "all" | "largest" | "highest_conf"
    "preserve_metadata": False,
    "window_width": 1200,
    "window_height": 800,
}


class ConfigManager:
    """Verwaltet die App-Konfiguration mit Persistenz in settings.json."""

    def __init__(self, config_path: str = "config/settings.json"):
        self._config_path = config_path
        self._config: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """Lädt die Konfiguration aus der JSON-Datei."""
        self._config = dict(DEFAULTS)
        if os.path.exists(self._config_path):
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self._config.update(saved)
                logger.info("Konfiguration geladen: %s", self._config_path)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Fehler beim Laden der Konfiguration: %s", e)
        else:
            self.save()
            logger.info("Default-Konfiguration erstellt: %s", self._config_path)

    def save(self) -> None:
        """Speichert die aktuelle Konfiguration."""
        os.makedirs(os.path.dirname(self._config_path), exist_ok=True)
        try:
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=4, ensure_ascii=False)
        except OSError as e:
            logger.error("Fehler beim Speichern der Konfiguration: %s", e)

    def get(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._config[key] = value

    def get_all(self) -> dict[str, Any]:
        return dict(self._config)
