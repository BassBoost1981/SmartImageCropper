"""ProcessingThread + ImageProcessor: Orchestriert die Batch-Verarbeitungspipeline."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from src.core.cropper import CropEngine
from src.core.detector import BoundingBox, PersonDetector
from src.core.watermark import WatermarkDetector
from src.utils.file_manager import FileManager
from src.utils.logger import get_logger
from src.utils.stats import StatsCollector

logger = get_logger(__name__)


class ModelLoaderThread(QThread):
    """Lädt YOLO-Modelle im Hintergrund beim App-Start (kein UI-Freeze).

    Loads both PersonDetector and WatermarkDetector models asynchronously.
    """

    # (PersonDetector, WatermarkDetector | None)
    model_ready = pyqtSignal(object, object)
    # Status-Text für UI / Status text for UI feedback
    progress_text = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        person_model: str = "models/yolov8n.pt",
        watermark_model: str = "models/best.pt",
        confidence: float = 0.5,
        wm_confidence: float = 0.30,
        use_gpu: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self._person_model = person_model
        self._watermark_model = watermark_model
        self._confidence = confidence
        self._wm_confidence = wm_confidence
        self._use_gpu = use_gpu

    def run(self) -> None:
        # Personen-Modell laden / Load person detection model
        self.progress_text.emit("Lade Personenerkennung...")
        person_detector = PersonDetector(
            model_path=self._person_model,
            confidence=self._confidence,
            use_gpu=self._use_gpu,
        )
        if not person_detector.load_model():
            detail = person_detector.last_error or "Unbekannter Fehler"
            self.error_occurred.emit(
                f"Person-Model konnte nicht geladen werden: {detail}"
            )
            return

        # Watermark-Modell laden / Load watermark detection model
        self.progress_text.emit("Lade Wasserzeichen-Erkennung...")
        wm_detector = WatermarkDetector(
            model_path=self._watermark_model,
            confidence=self._wm_confidence,
            use_gpu=self._use_gpu,
        )
        if not wm_detector.load_model():
            # Kein kritischer Fehler — Watermark ist optional
            # Not critical — watermark detection is optional
            logger.warning(
                "Watermark-Model konnte nicht geladen werden: %s",
                wm_detector.last_error,
            )
            wm_detector = None

        self.progress_text.emit("Modelle bereit")
        self.model_ready.emit(person_detector, wm_detector)
        logger.info("Modelle im Hintergrund geladen")


class ImageProcessor:
    """Verarbeitet einzelne Bilder: detect → watermark → crop → save."""

    def __init__(
        self,
        person_detector: PersonDetector,
        watermark_detector: WatermarkDetector | None,
        crop_engine: CropEngine,
        file_manager: FileManager,
        output_dir: str,
        jpeg_quality: int = 95,
        padding_percent: float = 10.0,
        watermark_mode: str = "manual",
        watermark_percent: float = 0.0,
    ):
        self.person_detector = person_detector
        self.watermark_detector = watermark_detector
        self.crop_engine = crop_engine
        self.file_manager = file_manager
        self.output_dir = output_dir
        self.jpeg_quality = jpeg_quality
        self.padding_percent = padding_percent
        self.watermark_mode = watermark_mode
        self.watermark_percent = watermark_percent

    def process_single(self, image_path: str) -> dict:
        """Verarbeitet ein einzelnes Bild. Gibt Ergebnis-Dict zurück."""
        result = {
            "path": image_path,
            "success": False,
            "persons": 0,
            "watermarks": 0,
            "error": None,
        }

        # Bild laden
        image = self.file_manager.load_image(image_path)
        if image is None:
            result["error"] = "Konnte nicht geladen werden"
            return result

        # Personenerkennung
        person_boxes = self.person_detector.detect(image)
        result["persons"] = len(person_boxes)

        if not person_boxes:
            result["error"] = "Keine Person erkannt"
            return result

        # Watermark-Erkennung
        watermark_boxes: list[BoundingBox] = []
        wm_percent = 0.0

        if self.watermark_mode == "manual":
            wm_percent = self.watermark_percent
        elif self.watermark_mode == "auto" and self.watermark_detector:
            watermark_boxes = self.watermark_detector.detect(image)
            result["watermarks"] = len(watermark_boxes)

        # Crop berechnen
        crop_region = self.crop_engine.calculate_crop_region(
            image_shape=image.shape,
            person_boxes=person_boxes,
            padding_percent=self.padding_percent,
            watermark_boxes=watermark_boxes if self.watermark_mode == "auto" else None,
            watermark_percent=wm_percent if self.watermark_mode == "manual" else 0,
        )

        if crop_region is None:
            result["error"] = "Crop-Region konnte nicht berechnet werden"
            return result

        # Bild zuschneiden
        cropped = self.crop_engine.crop_image(image, crop_region)

        # Speichern
        filename = Path(image_path).name
        output_path = os.path.join(self.output_dir, filename)

        if self.file_manager.save_image(cropped, output_path, self.jpeg_quality):
            result["success"] = True
        else:
            result["error"] = "Speichern fehlgeschlagen"

        return result


class ProcessingThread(QThread):
    """QThread für die Batch-Bildverarbeitung mit optionaler Auswahl-Pausierung.

    QThread for batch image processing with optional selection pause mechanism.
    """

    progress = pyqtSignal(int, int, str)  # current, total, filename
    image_processed = pyqtSignal(dict)  # result dict
    preview_ready = pyqtSignal(str, object, object, list, list)  # path, original, cropped, person_boxes, watermark_boxes
    batch_finished = pyqtSignal(dict)  # summary stats
    error_occurred = pyqtSignal(str)  # error message
    # Signal für Auswahl-Dialog / Signal for selection dialog
    # (path, image_ndarray, person_boxes, watermark_boxes)
    selection_needed = pyqtSignal(str, object, list, list)

    def __init__(
        self,
        image_paths: list[str],
        output_dir: str,
        config: dict,
        parent=None,
    ):
        super().__init__(parent)
        self._image_paths = image_paths
        self._output_dir = output_dir
        self._config = config
        self._cancelled = False
        self.stats = StatsCollector()

        # Pause-Mechanismus für Auswahl-Dialog / Pause mechanism for selection dialog
        self._pause_event = threading.Event()
        self._pause_event.set()  # initial: nicht pausiert / not paused
        self._selection_persons: list[BoundingBox] | None = None
        self._selection_watermarks: list[BoundingBox] | None = None
        self._selection_skip = False
        # Auto-Regel: None = nachfragen, "all"/"largest"/"highest_conf"
        # Auto rule: None = ask, otherwise apply automatically
        self._auto_rule: str | None = None

    def cancel(self) -> None:
        self._cancelled = True
        self._pause_event.set()  # Pause aufheben falls aktiv / Unblock if paused

    def set_selection_result(
        self,
        persons: list[BoundingBox] | None,
        watermarks: list[BoundingBox] | None,
        skip: bool = False,
        rule: str | None = None,
    ) -> None:
        """Wird vom UI-Thread aufgerufen um die Auswahl zu setzen.

        Called by UI thread to set the selection result and resume processing.
        """
        self._selection_persons = persons
        self._selection_watermarks = watermarks
        self._selection_skip = skip
        if rule is not None:
            self._auto_rule = rule
        self._pause_event.set()

    def _apply_auto_rule(
        self, person_boxes: list[BoundingBox]
    ) -> list[BoundingBox]:
        """Wendet die Auto-Regel auf Personen-Boxen an.

        Applies the auto rule to filter person boxes.
        """
        if self._auto_rule == "all" or not person_boxes:
            return person_boxes
        if self._auto_rule == "largest":
            return [max(person_boxes, key=lambda b: b.area)]
        if self._auto_rule == "highest_conf":
            return [max(person_boxes, key=lambda b: b.confidence)]
        return person_boxes

    def run(self) -> None:
        """Hauptverarbeitungsschleife. / Main processing loop."""
        self.stats.reset()
        self.stats.total = len(self._image_paths)
        self.stats.start()

        multi_action = self._config.get("multi_detection_action", "ask")
        if multi_action != "ask":
            self._auto_rule = multi_action

        # Detektoren initialisieren / Initialize detectors
        person_detector = PersonDetector(
            model_path=self._config.get("person_model", "models/yolov8n.pt"),
            confidence=self._config.get("confidence_threshold", 0.5),
            use_gpu=self._config.get("use_gpu", True),
        )

        if not person_detector.load_model():
            detail = person_detector.last_error or "Unbekannter Fehler"
            self.error_occurred.emit(
                f"Person-Detection-Model konnte nicht geladen werden:\n{detail}"
            )
            return

        watermark_detector = None
        if self._config.get("watermark_mode") == "auto":
            watermark_detector = WatermarkDetector(
                model_path=self._config.get("watermark_model", "models/best.pt"),
                confidence=self._config.get("watermark_confidence", 0.30),
                use_gpu=self._config.get("use_gpu", True),
            )
            if not watermark_detector.load_model():
                detail = watermark_detector.last_error or "Unbekannter Fehler"
                self.error_occurred.emit(
                    f"Watermark-Model konnte nicht geladen werden:\n{detail}"
                )
                return

        FileManager.ensure_output_dir(self._output_dir)

        processor = ImageProcessor(
            person_detector=person_detector,
            watermark_detector=watermark_detector,
            crop_engine=CropEngine(),
            file_manager=FileManager(),
            output_dir=self._output_dir,
            jpeg_quality=self._config.get("jpeg_quality", 95),
            padding_percent=self._config.get("padding_percent", 10.0),
            watermark_mode=self._config.get("watermark_mode", "manual"),
            watermark_percent=self._config.get("watermark_percent", 0.0),
        )

        # Sequentielle Verarbeitung für Auswahl-Dialog-Support
        # Sequential processing to support selection dialog pause
        for i, path in enumerate(self._image_paths):
            if self._cancelled:
                break

            filename = Path(path).name
            self.progress.emit(i + 1, self.stats.total, filename)

            try:
                result = self._process_with_selection(
                    path, processor, person_detector, watermark_detector
                )
            except Exception as e:
                result = {
                    "path": path,
                    "success": False,
                    "persons": 0,
                    "watermarks": 0,
                    "error": str(e),
                }

            if self._cancelled:
                break

            # Stats aktualisieren / Update stats
            if result["success"]:
                self.stats.processed += 1
                self.stats.persons_found += result["persons"]
                self.stats.watermarks_found += result.get("watermarks", 0)
            elif result.get("error") == "Keine Person erkannt":
                self.stats.skipped += 1
            elif result.get("error") == "Bild übersprungen":
                self.stats.skipped += 1
            else:
                self.stats.errors += 1

            self.image_processed.emit(result)

            # Preview für das erste und jedes 10. Bild
            # Preview for first and every 10th image
            if i == 0 or (i + 1) % 10 == 0:
                self._emit_preview(path, processor)

        self.stats.stop()
        self.batch_finished.emit(self.stats.summary())

    def _process_with_selection(
        self,
        image_path: str,
        processor: ImageProcessor,
        person_detector: PersonDetector,
        watermark_detector: WatermarkDetector | None,
    ) -> dict:
        """Verarbeitet ein Bild mit optionaler Auswahl-Pausierung.

        Processes a single image, pausing for user selection if multiple
        detections are found and no auto rule is set.
        """
        result = {
            "path": image_path,
            "success": False,
            "persons": 0,
            "watermarks": 0,
            "error": None,
        }

        # Bild laden / Load image
        image = FileManager.load_image(image_path)
        if image is None:
            result["error"] = "Konnte nicht geladen werden"
            return result

        # Erkennung / Detection
        person_boxes = person_detector.detect(image)
        result["persons"] = len(person_boxes)

        if not person_boxes:
            result["error"] = "Keine Person erkannt"
            return result

        watermark_boxes: list[BoundingBox] = []
        wm_percent = 0.0
        if processor.watermark_mode == "manual":
            wm_percent = processor.watermark_percent
        elif processor.watermark_mode == "auto" and watermark_detector:
            watermark_boxes = watermark_detector.detect(image)
            result["watermarks"] = len(watermark_boxes)

        # Mehrfach-Erkennung → Auswahl / Multi-detection → selection
        needs_selection = len(person_boxes) > 1 or len(watermark_boxes) > 1
        if needs_selection and self._auto_rule and self._auto_rule != "ask":
            # Auto-Regel anwenden / Apply auto rule
            person_boxes = self._apply_auto_rule(person_boxes)
        elif needs_selection and (self._auto_rule is None or self._auto_rule == "ask"):
            # Pausieren und UI fragen / Pause and ask UI
            self._selection_persons = None
            self._selection_watermarks = None
            self._selection_skip = False
            self._pause_event.clear()
            self.selection_needed.emit(
                image_path, image, person_boxes, watermark_boxes
            )
            self._pause_event.wait()  # Wartet auf UI-Antwort / Waits for UI response

            if self._cancelled:
                return result

            if self._selection_skip:
                result["error"] = "Bild übersprungen"
                return result

            if self._selection_persons is not None:
                person_boxes = self._selection_persons
            if self._selection_watermarks is not None:
                watermark_boxes = self._selection_watermarks

            if not person_boxes:
                result["error"] = "Keine Person ausgewählt"
                return result

        # Crop berechnen / Calculate crop
        crop_region = CropEngine.calculate_crop_region(
            image_shape=image.shape,
            person_boxes=person_boxes,
            padding_percent=processor.padding_percent,
            watermark_boxes=watermark_boxes if processor.watermark_mode == "auto" else None,
            watermark_percent=wm_percent if processor.watermark_mode == "manual" else 0,
        )

        if crop_region is None:
            result["error"] = "Crop-Region konnte nicht berechnet werden"
            return result

        # Zuschneiden und speichern / Crop and save
        cropped = CropEngine.crop_image(image, crop_region)
        output_filename = Path(image_path).name
        output_path = os.path.join(processor.output_dir, output_filename)

        if FileManager.save_image(cropped, output_path, processor.jpeg_quality):
            result["success"] = True
        else:
            result["error"] = "Speichern fehlgeschlagen"

        return result

    def _emit_preview(self, path: str, processor: ImageProcessor) -> None:
        """Sendet ein Preview-Signal mit Original und Crop."""
        try:
            original = FileManager.load_image(path)
            if original is None:
                return
            boxes = processor.person_detector.detect(original)

            # Watermark-Erkennung für Preview
            wm_boxes: list[BoundingBox] = []
            wm_percent = 0.0
            if processor.watermark_mode == "auto" and processor.watermark_detector:
                wm_boxes = processor.watermark_detector.detect(original)
            elif processor.watermark_mode == "manual":
                wm_percent = processor.watermark_percent

            if boxes:
                region = processor.crop_engine.calculate_crop_region(
                    image_shape=original.shape,
                    person_boxes=boxes,
                    padding_percent=processor.padding_percent,
                    watermark_boxes=wm_boxes if processor.watermark_mode == "auto" else None,
                    watermark_percent=wm_percent if processor.watermark_mode == "manual" else 0,
                )
                if region:
                    cropped = processor.crop_engine.crop_image(original, region)
                    self.preview_ready.emit(path, original, cropped, boxes, wm_boxes)
        except Exception as e:
            logger.debug("Preview-Fehler: %s", e)


class DetectionPreviewThread(QThread):
    """Thread für Preview-Only Detection (ohne Speichern)."""

    detection_done = pyqtSignal(str, object, list)  # path, image, boxes

    def __init__(self, image_path: str, detector: PersonDetector, parent=None):
        super().__init__(parent)
        self._image_path = image_path
        self._detector = detector

    def run(self) -> None:
        image = FileManager.load_image(self._image_path)
        if image is None:
            return
        boxes = self._detector.detect(image)
        self.detection_done.emit(self._image_path, image, boxes)


class PreviewLoadThread(QThread):
    """Thread für vollständiges Preview-Laden mit Fortschrittsanzeige.

    Führt asynchron aus: Bild laden → Personen erkennen → Wasserzeichen erkennen → Zuschneiden.
    Emittiert Fortschritt nach jedem Schritt.
    """

    # step, total_steps, description
    progress = pyqtSignal(int, int, str)
    # index, original, cropped, person_boxes, wm_boxes, filename
    preview_done = pyqtSignal(int, object, object, list, list, str)
    error_occurred = pyqtSignal(str)  # error message

    def __init__(
        self,
        image_path: str,
        index: int,
        person_detector: PersonDetector,
        wm_detector: WatermarkDetector | None,
        wm_mode: str,
        padding_percent: float,
        wm_percent: float,
        parent=None,
    ):
        super().__init__(parent)
        self._image_path = image_path
        self._index = index
        self._person_detector = person_detector
        self._wm_detector = wm_detector
        self._wm_mode = wm_mode
        self._padding_percent = padding_percent
        self._wm_percent = wm_percent

    def run(self) -> None:
        try:
            filename = Path(self._image_path).name
            total_steps = 4 if (self._wm_mode == "auto" and self._wm_detector) else 3

            # Schritt 1: Bild laden
            self.progress.emit(1, total_steps, f"Lade {filename}...")
            image = FileManager.load_image(self._image_path)
            if image is None:
                self.error_occurred.emit(
                    f"{filename} konnte nicht geladen werden"
                )
                return

            # Schritt 2: Personen erkennen
            self.progress.emit(2, total_steps, f"Personen erkennen: {filename}...")
            person_boxes = self._person_detector.detect(image)

            # Schritt 3: Wasserzeichen erkennen (falls Auto)
            wm_boxes = []
            step = 3
            if self._wm_mode == "auto" and self._wm_detector:
                self.progress.emit(step, total_steps, f"Wasserzeichen erkennen: {filename}...")
                wm_boxes = self._wm_detector.detect(image)
                step = 4

            # Letzter Schritt: Zuschneiden
            self.progress.emit(step, total_steps, f"Zuschneiden: {filename}...")
            crop_region = None
            cropped = None
            if person_boxes:
                crop_region = CropEngine.calculate_crop_region(
                    image_shape=image.shape,
                    person_boxes=person_boxes,
                    padding_percent=self._padding_percent,
                    watermark_boxes=wm_boxes if self._wm_mode == "auto" else None,
                    watermark_percent=self._wm_percent if self._wm_mode == "manual" else 0,
                )
                if crop_region:
                    cropped = CropEngine.crop_image(image, crop_region)

            self.preview_done.emit(
                self._index, image, cropped, person_boxes, wm_boxes, filename
            )

        except Exception as e:
            logger.error("Preview-Thread Fehler: %s", e, exc_info=True)
            self.error_occurred.emit(str(e))
