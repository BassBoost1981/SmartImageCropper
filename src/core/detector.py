"""PersonDetector: YOLOv8-Wrapper für Personenerkennung, thread-safe."""

import os
import sys
import threading
from dataclasses import dataclass
from typing import Any

import numpy as np

from src.utils.logger import get_logger

logger = get_logger(__name__)

_detection_lock = threading.Lock()


def _get_model_path(relative_path: str) -> str:
    """Gibt den absoluten Pfad zu einer Ressource zurück.
    Funktioniert sowohl im Development-Modus als auch in PyInstaller-EXE."""
    if hasattr(sys, "_MEIPASS"):
        # PyInstaller One-File Bundle
        return os.path.join(sys._MEIPASS, relative_path)
    elif getattr(sys, "frozen", False):
        # PyInstaller COLLECT/Ordner-Modus - Dateien sind in _internal/
        exe_dir = os.path.dirname(sys.executable)
        internal_path = os.path.join(exe_dir, "_internal", relative_path)
        if os.path.exists(internal_path):
            return internal_path
        # Fallback: direkt im exe_dir (alte Version)
        return os.path.join(exe_dir, relative_path)
    # Development-Modus
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), relative_path
    )


@dataclass
class BoundingBox:
    """Bounding Box mit Confidence."""

    x1: int
    y1: int
    x2: int
    y2: int
    confidence: float

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1

    @property
    def center(self) -> tuple[int, int]:
        return ((self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2)

    @property
    def area(self) -> int:
        return self.width * self.height


class PersonDetector:
    """YOLOv8-basierte Personenerkennung."""

    PERSON_CLASS_ID = 0  # COCO Klasse 0 = Person

    def __init__(
        self,
        model_path: str = "models/yolov8n.pt",
        confidence: float = 0.5,
        use_gpu: bool = True,
    ):
        self._model_path = model_path
        self._confidence = confidence
        self._use_gpu = use_gpu
        self._model: Any | None = None
        self._last_error: str | None = None

    def load_model(self) -> bool:
        """Lädt das YOLO-Model."""
        if self._model is not None:
            return True

        self._last_error = None

        # Pfad für EXE/Development auflösen
        model_path = _get_model_path(self._model_path)

        if not os.path.exists(model_path):
            self._last_error = f"Model-Datei nicht gefunden: {model_path}"
            logger.error(
                "Model nicht gefunden: %s (resolved: %s)", self._model_path, model_path
            )
            return False

        try:
            from ultralytics import YOLO

            self._model = YOLO(model_path)
            device = "cuda" if self._use_gpu else "cpu"
            # Warm-up-Inference um GPU-Init zu triggern
            logger.info("Model geladen: %s (device: %s)", model_path, device)
            return True
        except Exception as e:
            self._last_error = str(e)
            logger.error("Fehler beim Laden des Models: %s", e, exc_info=True)
            return False

    @property
    def last_error(self) -> str | None:
        """Gibt die letzte Fehlermeldung beim Model-Laden zurück."""
        return self._last_error

    def detect(
        self, image: np.ndarray, confidence: float | None = None
    ) -> list[BoundingBox]:
        """Erkennt Personen im Bild. Thread-safe durch Lock."""
        if self._model is None:
            if not self.load_model():
                return []
        if self._model is None:
            return []

        conf = confidence or self._confidence
        device = "cuda" if self._use_gpu else "cpu"
        model = self._model

        with _detection_lock:
            try:
                results = model(
                    image,
                    conf=conf,
                    device=device,
                    classes=[self.PERSON_CLASS_ID],
                    verbose=False,
                )
            except RuntimeError:
                # GPU-Fallback auf CPU
                logger.warning("GPU-Fehler, Fallback auf CPU")
                results = model(
                    image,
                    conf=conf,
                    device="cpu",
                    classes=[self.PERSON_CLASS_ID],
                    verbose=False,
                )

        boxes = []
        for result in results:
            for box in result.boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                conf_val = float(box.conf[0].cpu().numpy())
                boxes.append(
                    BoundingBox(
                        x1=int(x1),
                        y1=int(y1),
                        x2=int(x2),
                        y2=int(y2),
                        confidence=conf_val,
                    )
                )

        logger.debug("%d Personen erkannt (conf >= %.2f)", len(boxes), conf)
        return boxes

    def set_confidence(self, confidence: float) -> None:
        self._confidence = confidence

    def set_gpu(self, use_gpu: bool) -> None:
        self._use_gpu = use_gpu
