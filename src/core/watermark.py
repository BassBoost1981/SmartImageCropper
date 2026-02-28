"""WatermarkDetector: Zweites YOLO-Model für Watermark-Erkennung, thread-safe."""

import os
import threading

import numpy as np

from src.core.detector import BoundingBox, _get_model_path
from src.utils.logger import get_logger

logger = get_logger(__name__)

_watermark_lock = threading.Lock()


class WatermarkDetector:
    """YOLO-basierte Wasserzeichen-Erkennung mit Auto-Download."""

    DEFAULT_MODEL_PATH = "models/best.pt"
    HF_REPO = "corzent/yolo11x_watermark_detection"
    HF_FILENAME = "best.pt"

    # Filterparameter: Watermarks sind typischerweise klein und am Bildrand
    MAX_AREA_RATIO = 0.15  # Max. 15% der Bildfläche
    EDGE_MARGIN_BOTTOM = 0.30  # Untere 30% des Bildes
    EDGE_MARGIN_TOP = 0.15  # Obere 15%
    EDGE_MARGIN_SIDE = 0.15  # Seitlich 15%

    def __init__(
        self,
        model_path: str = DEFAULT_MODEL_PATH,
        confidence: float = 0.30,
        use_gpu: bool = True,
    ):
        self._model_path = model_path
        self._confidence = confidence
        self._use_gpu = use_gpu
        self._model = None
        self._last_error: str | None = None

    def _download_model(self) -> bool:
        """Lädt das Watermark-Model von HuggingFace herunter."""
        try:
            from huggingface_hub import hf_hub_download

            logger.info("Lade Watermark-Model von HuggingFace: %s", self.HF_REPO)
            downloaded_path = hf_hub_download(
                repo_id=self.HF_REPO,
                filename=self.HF_FILENAME,
                local_dir="models",
            )
            logger.info("Watermark-Model heruntergeladen: %s", downloaded_path)
            return True
        except Exception as e:
            logger.error("Download fehlgeschlagen: %s", e)
            return False

    def load_model(self) -> bool:
        """Lädt das Watermark-Model (mit Auto-Download)."""
        if self._model is not None:
            return True

        self._last_error = None

        # Pfad für EXE/Development auflösen
        model_path = _get_model_path(self._model_path)

        if not os.path.exists(model_path):
            # Im EXE-Modus: versuche im models-Ordner im _MEIPASS
            if hasattr(__import__("sys"), "_MEIPASS"):
                self._last_error = f"Watermark-Model nicht im Bundle: {model_path}"
                logger.error("Watermark-Model nicht im Bundle gefunden: %s", model_path)
                return False
            # Im Development-Modus: versuche Download
            if not self._download_model():
                self._last_error = "Watermark-Model Download fehlgeschlagen"
                return False
            # Nach Download neu auflösen
            model_path = _get_model_path(self._model_path)

        try:
            from ultralytics import YOLO

            self._model = YOLO(model_path)
            logger.info("Watermark-Model geladen: %s", model_path)
            return True
        except Exception as e:
            self._last_error = str(e)
            logger.error("Fehler beim Laden des Watermark-Models: %s", e, exc_info=True)
            return False

    @property
    def last_error(self) -> str | None:
        """Gibt die letzte Fehlermeldung beim Model-Laden zurück."""
        return self._last_error

    def _is_edge_region(self, box: BoundingBox, img_h: int, img_w: int) -> bool:
        """Prüft ob die Box in einer typischen Watermark-Region liegt (Bildrand).

        Echte Watermarks sind fast immer Text-Overlays an den Rändern:
        unten, oben, Ecken oder seitlich.
        """
        cx = (box.x1 + box.x2) / 2
        cy = (box.y1 + box.y2) / 2

        # Unterer Rand (häufigste Position)
        if cy > img_h * (1 - self.EDGE_MARGIN_BOTTOM):
            return True
        # Oberer Rand
        if cy < img_h * self.EDGE_MARGIN_TOP:
            return True
        # Linker/rechter Rand
        if cx < img_w * self.EDGE_MARGIN_SIDE or cx > img_w * (1 - self.EDGE_MARGIN_SIDE):
            return True
        return False

    def _is_plausible_watermark(
        self, box: BoundingBox, img_h: int, img_w: int
    ) -> bool:
        """Filtert False Positives: Prüft ob eine Detection ein plausibles Watermark ist.

        Kriterien:
        - Muss in einer Randregion des Bildes liegen
        - Darf nicht zu groß sein (max. 15% der Bildfläche)
        """
        img_area = img_h * img_w
        box_area = box.area

        # Zu große Boxen sind keine Watermarks (z.B. Möbel, Bücher)
        if box_area > img_area * self.MAX_AREA_RATIO:
            logger.debug(
                "Watermark-Box gefiltert (zu groß: %.1f%% der Bildfläche): %s",
                box_area / img_area * 100, box,
            )
            return False

        # Muss am Bildrand liegen
        if not self._is_edge_region(box, img_h, img_w):
            logger.debug(
                "Watermark-Box gefiltert (nicht am Rand): %s", box,
            )
            return False

        return True

    def detect(
        self, image: np.ndarray, confidence: float | None = None
    ) -> list[BoundingBox]:
        """Erkennt Wasserzeichen im Bild. Thread-safe.

        Wendet nach der YOLO-Erkennung Plausibilitätsfilter an,
        um False Positives (z.B. Bücher, Möbel) auszuschließen.
        """
        if self._model is None:
            if not self.load_model():
                return []

        conf = confidence or self._confidence
        device = "cuda" if self._use_gpu else "cpu"

        with _watermark_lock:
            try:
                results = self._model(image, conf=conf, device=device, verbose=False)
            except RuntimeError:
                logger.warning("GPU-Fehler bei Watermark-Detection, Fallback CPU")
                results = self._model(image, conf=conf, device="cpu", verbose=False)

        img_h, img_w = image.shape[:2]
        raw_boxes = []
        for result in results:
            for box in result.boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                conf_val = float(box.conf[0].cpu().numpy())
                raw_boxes.append(
                    BoundingBox(
                        x1=int(x1),
                        y1=int(y1),
                        x2=int(x2),
                        y2=int(y2),
                        confidence=conf_val,
                    )
                )

        # Plausibilitätsfilter anwenden
        boxes = [b for b in raw_boxes if self._is_plausible_watermark(b, img_h, img_w)]

        if len(raw_boxes) != len(boxes):
            logger.info(
                "Watermark-Filter: %d von %d Detections als False Positive entfernt",
                len(raw_boxes) - len(boxes), len(raw_boxes),
            )

        logger.info("%d Wasserzeichen erkannt (conf >= %.2f)", len(boxes), conf)
        return boxes

    def set_confidence(self, confidence: float) -> None:
        self._confidence = confidence

    def set_gpu(self, use_gpu: bool) -> None:
        self._use_gpu = use_gpu
