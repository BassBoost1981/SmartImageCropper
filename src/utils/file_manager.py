"""Datei-Scanning & IO mit cv2.imencode für zuverlässiges Speichern."""

import os
from pathlib import Path

import cv2
import numpy as np

from src.utils.logger import get_logger

logger = get_logger(__name__)

SUPPORTED_FORMATS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


class FileManager:
    """Verwaltet Datei-Scanning und Bild-IO."""

    @staticmethod
    def scan_directory(directory: str, formats: set[str] | None = None) -> list[str]:
        """Scannt ein Verzeichnis nach unterstützten Bilddateien."""
        if not os.path.isdir(directory):
            logger.warning("Verzeichnis nicht gefunden: %s", directory)
            return []

        fmt = formats or SUPPORTED_FORMATS
        files = []
        for entry in sorted(os.scandir(directory), key=lambda e: e.name.lower()):
            if entry.is_file() and Path(entry.name).suffix.lower() in fmt:
                files.append(entry.path)

        logger.info("%d Bilder gefunden in: %s", len(files), directory)
        return files

    @staticmethod
    def load_image(path: str) -> np.ndarray | None:
        """Lädt ein Bild als BGR NumPy-Array."""
        try:
            data = np.fromfile(path, dtype=np.uint8)
            img = cv2.imdecode(data, cv2.IMREAD_COLOR)
            if img is None:
                logger.warning("Bild konnte nicht dekodiert werden: %s", path)
            return img
        except Exception as e:
            logger.error("Fehler beim Laden: %s — %s", path, e)
            return None

    @staticmethod
    def save_image(
        image: np.ndarray,
        output_path: str,
        quality: int = 95,
    ) -> bool:
        """Speichert ein Bild mit cv2.imencode + nativer File-IO."""
        ext = Path(output_path).suffix.lower()
        try:
            if ext in (".jpg", ".jpeg"):
                params = [cv2.IMWRITE_JPEG_QUALITY, quality]
                success, buf = cv2.imencode(".jpg", image, params)
            elif ext == ".png":
                params = [cv2.IMWRITE_PNG_COMPRESSION, 6]
                success, buf = cv2.imencode(".png", image, params)
            elif ext == ".webp":
                params = [cv2.IMWRITE_WEBP_QUALITY, quality]
                success, buf = cv2.imencode(".webp", image, params)
            else:
                success, buf = cv2.imencode(ext, image)

            if not success:
                logger.error("imencode fehlgeschlagen: %s", output_path)
                return False

            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(buf.tobytes())

            file_size = os.path.getsize(output_path)
            if file_size == 0:
                logger.error("Leere Datei geschrieben: %s", output_path)
                return False

            logger.debug("Gespeichert: %s (%d bytes)", output_path, file_size)
            return True

        except Exception as e:
            logger.error("Fehler beim Speichern: %s — %s", output_path, e)
            return False

    @staticmethod
    def ensure_output_dir(directory: str) -> bool:
        """Erstellt das Output-Verzeichnis falls nötig."""
        try:
            os.makedirs(directory, exist_ok=True)
            return True
        except OSError as e:
            logger.error("Kann Verzeichnis nicht erstellen: %s — %s", directory, e)
            return False
