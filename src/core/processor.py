"""ProcessingThread + ImageProcessor: Orchestriert die Batch-Verarbeitungspipeline."""

import os
import threading
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from src.core.cropper import CropEngine
from src.core.detector import BoundingBox, PersonDetector
from src.core.watermark import TemplateWatermarkMatcher, WatermarkDetector
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
        wm_strict_filter: bool = True,
        wm_enhanced_detection: bool = False,
        wm_type: str = "logo",
        parent=None,
    ):
        super().__init__(parent)
        self._person_model = person_model
        self._watermark_model = watermark_model
        self._confidence = confidence
        self._wm_confidence = wm_confidence
        self._use_gpu = use_gpu
        self._wm_strict_filter = wm_strict_filter
        self._wm_enhanced_detection = wm_enhanced_detection
        self._wm_type = wm_type

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
        wm_detector: WatermarkDetector | None = WatermarkDetector(
            model_path=self._watermark_model,
            confidence=self._wm_confidence,
            use_gpu=self._use_gpu,
            strict_filter=self._wm_strict_filter,
            enhanced_detection=self._wm_enhanced_detection,
            watermark_type=self._wm_type,
        )
        if wm_detector is not None and not wm_detector.load_model():
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

        # Watermark-Erkennung
        watermark_boxes: list[BoundingBox] = []
        wm_percent = 0.0

        if self.watermark_mode == "manual":
            wm_percent = self.watermark_percent
        elif self.watermark_mode == "auto" and self.watermark_detector:
            watermark_boxes = self.watermark_detector.detect(image)
            result["watermarks"] = len(watermark_boxes)

        # Keine Person UND kein Watermark → ueberspringen
        # No person AND no watermark → skip this image
        if not person_boxes and not watermark_boxes and wm_percent <= 0:
            result["error"] = "Keine Person erkannt"
            return result

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
    # Signal fuer Auswahl-Dialog / Signal for selection dialog
    # (path, image_ndarray, person_boxes, watermark_boxes)
    selection_needed = pyqtSignal(str, object, list, list)
    # Signal fuer Template-Markierung / Signal for template marking dialog
    # (path, image_ndarray) — emitted when YOLO finds no watermark on first image
    template_needed = pyqtSignal(str, object)

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

        # Pause-Mechanismus fuer Auswahl-Dialog / Pause mechanism for selection dialog
        self._pause_event = threading.Event()
        self._pause_event.set()  # initial: nicht pausiert / not paused
        self._selection_persons: list[BoundingBox] | None = None
        self._selection_watermarks: list[BoundingBox] | None = None
        self._selection_skip = False
        # Auto-Regel: None = nachfragen, "all"/"largest"/"highest_conf"
        # Auto rule: None = ask, otherwise apply automatically
        self._auto_rule: str | None = None
        # Template-Matching: Pause-Event + Ergebnis vom UI
        # Template matching: pause event + result from UI thread
        self._template_event = threading.Event()
        self._template_event.set()  # initial: nicht pausiert
        self._template_matcher: TemplateWatermarkMatcher | None = None
        self._template_box: BoundingBox | None = None  # von UI gesetzt / set by UI

    def cancel(self) -> None:
        self._cancelled = True
        self._pause_event.set()  # Pause aufheben falls aktiv / Unblock if paused
        self._template_event.set()  # Template-Dialog-Wait aufheben / Unblock template wait

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

    def set_template_result(self, box: BoundingBox | None) -> None:
        """Wird vom UI-Thread aufgerufen um das Template-Ergebnis zu setzen.

        Called by UI thread to set the template selection and resume processing.
        box=None means user skipped template marking.
        """
        self._template_box = box
        self._template_event.set()

    @staticmethod
    def _filter_relevant_watermarks(
        person_boxes: list[BoundingBox],
        watermark_boxes: list[BoundingBox],
        padding_percent: float,
    ) -> list[BoundingBox]:
        """Entfernt Watermarks die ausserhalb des Personen-Schnittbereichs liegen.

        Filters out watermark boxes that don't overlap with the person crop
        region (including padding). This prevents irrelevant detections from
        affecting the crop or confusing the user.
        """
        if not watermark_boxes or not person_boxes:
            return watermark_boxes

        # Personen-Bereich berechnen (mit Padding) / Calculate person area
        p_min_x = min(b.x1 for b in person_boxes)
        p_min_y = min(b.y1 for b in person_boxes)
        p_max_x = max(b.x2 for b in person_boxes)
        p_max_y = max(b.y2 for b in person_boxes)
        pad_x = int((p_max_x - p_min_x) * padding_percent / 100)
        pad_y = int((p_max_y - p_min_y) * padding_percent / 100)
        crop_x1 = p_min_x - pad_x
        crop_y1 = p_min_y - pad_y
        crop_x2 = p_max_x + pad_x
        crop_y2 = p_max_y + pad_y

        # Nur Watermarks behalten die den Schnittbereich ueberschneiden
        # Keep only watermarks that overlap the crop region
        relevant = [
            wb for wb in watermark_boxes
            if wb.x1 < crop_x2 and wb.x2 > crop_x1
            and wb.y1 < crop_y2 and wb.y2 > crop_y1
        ]

        filtered_count = len(watermark_boxes) - len(relevant)
        if filtered_count > 0:
            logger.info(
                "%d Watermark(s) ausserhalb des Schnittbereichs ignoriert",
                filtered_count,
            )

        return relevant

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

    def _init_template(
        self, watermark_detector: WatermarkDetector, first_image_path: str
    ) -> None:
        """Zeigt den Template-Dialog fuer das erste Bild.

        When watermark_template_enabled is True, always show the dialog
        so the user can mark the watermark manually. YOLO is skipped here —
        the user decides what the watermark looks like.
        """
        image = FileManager.load_image(first_image_path)
        if image is None:
            return

        # Immer Dialog zeigen — User markiert das Watermark manuell
        # Always show dialog — user marks the watermark manually
        matcher = TemplateWatermarkMatcher()
        self._template_box = None
        self._template_event.clear()
        self.template_needed.emit(first_image_path, image)

        # Keine endlose Blockade: wenn UI-Signal ausbleibt, nach Timeout weiterlaufen.
        # Avoid endless blocking: continue after timeout if UI signal is missing.
        if not self._template_event.wait(timeout=30.0):
            logger.warning(
                "Template-Dialog Timeout nach 30s fuer %s; fahre ohne Template fort",
                first_image_path,
            )
            return

        if self._cancelled:
            return

        if self._template_box is not None:
            matcher.set_template_from_box(image, self._template_box)
            watermark_detector.template_matcher = matcher
            logger.info(
                "Template manuell markiert fuer: %s", first_image_path
            )
        else:
            logger.info("Kein Template markiert, nur YOLO-Erkennung aktiv")

    def run(self) -> None:
        """Hauptverarbeitungsschleife. / Main processing loop."""
        self.stats.reset()
        self.stats.total = len(self._image_paths)
        self.stats.start()

        multi_action = self._config.get("multi_detection_action", "ask")
        if multi_action != "ask":
            self._auto_rule = multi_action

        # Detektoren initialisieren / Initialize detectors
        person_enabled = self._config.get("person_detection_enabled", True)
        if not person_enabled:
            self.error_occurred.emit(
                "Personenerkennung darf nicht deaktiviert werden (Crop benoetigt Person-Boxen)."
            )
            return

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
                strict_filter=self._config.get("watermark_strict_filter", True),
                enhanced_detection=self._config.get(
                    "watermark_enhanced_detection", False
                ),
                watermark_type=self._config.get("watermark_type", "logo"),
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

        # Template-Matching: nur wenn Checkbox aktiviert / Only when template checkbox enabled
        if (
            watermark_detector
            and self._image_paths
            and self._config.get("watermark_template_enabled", False)
        ):
            self._init_template(watermark_detector, self._image_paths[0])

        # Sequentielle Verarbeitung fuer Auswahl-Dialog-Support
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
        person_boxes = person_detector.detect(image) if person_detector else []
        result["persons"] = len(person_boxes)

        watermark_boxes: list[BoundingBox] = []
        wm_percent = 0.0
        if processor.watermark_mode == "manual":
            wm_percent = processor.watermark_percent
        elif processor.watermark_mode == "auto" and watermark_detector:
            watermark_boxes = watermark_detector.detect(image)

            # Watermarks ausserhalb des Schnittbereichs nur filtern wenn Personen da sind
            # Only filter irrelevant watermarks when persons were detected
            if person_boxes:
                watermark_boxes = self._filter_relevant_watermarks(
                    person_boxes, watermark_boxes, processor.padding_percent
                )
            result["watermarks"] = len(watermark_boxes)

        # Keine Person UND kein Watermark → ueberspringen
        # No person AND no watermark → skip this image
        if not person_boxes and not watermark_boxes and wm_percent <= 0:
            result["error"] = "Keine Person erkannt"
            return result

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

            if not person_boxes and not watermark_boxes and wm_percent <= 0:
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
            boxes = processor.person_detector.detect(original) if processor.person_detector else []

            # Watermark-Erkennung für Preview
            wm_boxes: list[BoundingBox] = []
            wm_percent = 0.0
            if processor.watermark_mode == "auto" and processor.watermark_detector:
                wm_boxes = processor.watermark_detector.detect(original)
                # Irrelevante Watermarks filtern / Filter irrelevant watermarks
                if boxes:
                    wm_boxes = self._filter_relevant_watermarks(
                        boxes, wm_boxes, processor.padding_percent
                    )
            elif processor.watermark_mode == "manual":
                wm_percent = processor.watermark_percent

            # Preview auch ohne Personen wenn Watermarks vorhanden
            # Show preview even without persons when watermarks are present
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
        person_detection_enabled: bool = True,
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
        self._person_enabled = person_detection_enabled

    def run(self) -> None:
        try:
            filename = Path(self._image_path).name
            total_steps = 4 if (self._wm_mode == "auto" and self._wm_detector) else 3
            if not self._person_enabled:
                total_steps -= 1  # Personen-Schritt faellt weg

            # Schritt 1: Bild laden
            step = 1
            self.progress.emit(step, total_steps, f"Lade {filename}...")
            image = FileManager.load_image(self._image_path)
            if image is None:
                self.error_occurred.emit(
                    f"{filename} konnte nicht geladen werden"
                )
                return

            # Schritt 2: Personen erkennen (falls aktiviert)
            # Step 2: Detect persons (if enabled)
            person_boxes = []
            if self._person_enabled:
                step += 1
                self.progress.emit(step, total_steps, f"Personen erkennen: {filename}...")
                person_boxes = self._person_detector.detect(image)

            # Wasserzeichen erkennen (falls Auto)
            wm_boxes = []
            if self._wm_mode == "auto" and self._wm_detector:
                step += 1
                self.progress.emit(step, total_steps, f"Wasserzeichen erkennen: {filename}...")
                wm_boxes = self._wm_detector.detect(image)

            # Letzter Schritt: Zuschneiden
            # Crop auch ohne Person wenn Watermark vorhanden (ganzes Bild minus WM)
            # Crop even without person when watermark present (full image minus WM)
            step += 1
            self.progress.emit(step, total_steps, f"Zuschneiden: {filename}...")
            crop_region = None
            cropped = None
            wm_pct = self._wm_percent if self._wm_mode == "manual" else 0
            has_content = person_boxes or wm_boxes or wm_pct > 0
            if has_content:
                crop_region = CropEngine.calculate_crop_region(
                    image_shape=image.shape,
                    person_boxes=person_boxes,
                    padding_percent=self._padding_percent,
                    watermark_boxes=wm_boxes if self._wm_mode == "auto" else None,
                    watermark_percent=wm_pct,
                )
                if crop_region:
                    cropped = CropEngine.crop_image(image, crop_region)

            self.preview_done.emit(
                self._index, image, cropped, person_boxes, wm_boxes, filename
            )

        except Exception as e:
            logger.error("Preview-Thread Fehler: %s", e, exc_info=True)
            self.error_occurred.emit(str(e))
