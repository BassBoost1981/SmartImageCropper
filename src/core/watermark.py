"""WatermarkDetector + TemplateWatermarkMatcher: YOLO + Template-Matching, thread-safe.

Zweistufige Wasserzeichen-Erkennung: YOLO-Modell (mit TTA und Preprocessing)
als Primaererkennung, OpenCV-Template-Matching als Fallback fuer bekannte Logos.
"""

import os
import threading

import cv2
import numpy as np

from src.core.detector import BoundingBox, _get_model_path
from src.utils.logger import get_logger

logger = get_logger(__name__)

_watermark_lock = threading.Lock()


def _compute_iou(a: BoundingBox, b: BoundingBox) -> float:
    """Berechnet Intersection-over-Union zweier Bounding Boxes.

    Computes IoU to merge/deduplicate overlapping detections.
    """
    ix1 = max(a.x1, b.x1)
    iy1 = max(a.y1, b.y1)
    ix2 = min(a.x2, b.x2)
    iy2 = min(a.y2, b.y2)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    if inter == 0:
        return 0.0
    union = a.area + b.area - inter
    return inter / union if union > 0 else 0.0


def _is_contained(a: BoundingBox, b: BoundingBox, threshold: float = 0.6) -> bool:
    """Prueft ob eine Box weitgehend in der anderen enthalten ist.

    Returns True if the intersection covers more than `threshold` of the
    smaller box's area. Catches cases where IoU is low but one box
    is fully inside another (e.g. small template match inside large YOLO box).
    """
    ix1 = max(a.x1, b.x1)
    iy1 = max(a.y1, b.y1)
    ix2 = min(a.x2, b.x2)
    iy2 = min(a.y2, b.y2)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    if inter == 0:
        return False
    smaller_area = min(a.area, b.area)
    return (inter / smaller_area) >= threshold if smaller_area > 0 else False


def _deduplicate_boxes(
    boxes: list[BoundingBox], iou_threshold: float = 0.5
) -> list[BoundingBox]:
    """Entfernt Duplikate per NMS + Containment-Check (hoechste Confidence gewinnt).

    Removes duplicate/overlapping detections by keeping the highest-confidence
    box when either:
    - IoU exceeds the threshold (standard NMS), OR
    - One box is largely contained within another (>60% of smaller box area)
    This prevents multiple watermarks stacking on top of each other.
    """
    if len(boxes) <= 1:
        return boxes
    sorted_boxes = sorted(boxes, key=lambda b: b.confidence, reverse=True)
    keep: list[BoundingBox] = []
    for box in sorted_boxes:
        is_duplicate = False
        for kept in keep:
            if _compute_iou(box, kept) >= iou_threshold:
                is_duplicate = True
                break
            # Containment-Check: kleine Box in grosser → Duplikat
            # Containment check: small box inside large one → duplicate
            if _is_contained(box, kept, threshold=0.6):
                is_duplicate = True
                break
        if not is_duplicate:
            keep.append(box)
    return keep


class TemplateWatermarkMatcher:
    """OpenCV-basiertes Template-Matching fuer bekannte Logo-Watermarks.

    Sucht ein Referenz-Template auf mehreren Skalierungen im Bild.
    Drei Paesse: Grayscale, Edge-basiert und CLAHE-normalisiert fuer
    Robustheit bei unterschiedlicher Belichtung/Kompression.
    """

    # Feinere Skalierungsfaktoren — weniger Luecken, bessere Trefferquote
    # Finer scale factors — fewer gaps, better hit rate
    SCALES = (0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0)
    DEFAULT_MATCH_THRESHOLD = 0.55
    EDGE_MATCH_THRESHOLD = 0.42
    CLAHE_MATCH_THRESHOLD = 0.50

    # Randbereich-Filter: Logos erscheinen am Bildrand, nicht in der Mitte
    # Edge region filter: logos appear at image edges, not in the center
    EDGE_MARGIN_BOTTOM = 0.40  # Untere 40%
    EDGE_MARGIN_TOP = 0.15     # Obere 15%
    EDGE_MARGIN_SIDE = 0.20    # Seitlich 20%

    def __init__(self, match_threshold: float = DEFAULT_MATCH_THRESHOLD):
        self._template: np.ndarray | None = None
        self._template_gray: np.ndarray | None = None
        self._template_edges: np.ndarray | None = None
        self._template_clahe: np.ndarray | None = None
        self._match_threshold = match_threshold
        # CLAHE fuer Belichtungs-Normalisierung / CLAHE for exposure normalization
        self._clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

    @property
    def has_template(self) -> bool:
        return self._template is not None

    def set_template(self, template_image: np.ndarray) -> None:
        """Setzt das Referenz-Template (BGR-Bild oder Ausschnitt).

        Stores template in color, grayscale, edge and CLAHE representations
        for robust matching against varying lighting and compression.
        """
        self._template = template_image.copy()
        gray = cv2.cvtColor(template_image, cv2.COLOR_BGR2GRAY)
        self._template_gray = gray
        self._template_edges = cv2.Canny(gray, 50, 150)
        # CLAHE-normalisiert fuer Robustheit bei Belichtungsunterschieden
        # CLAHE-normalized for robustness against exposure differences
        self._template_clahe = self._clahe.apply(gray)
        logger.info(
            "Watermark-Template gesetzt: %dx%d",
            template_image.shape[1],
            template_image.shape[0],
        )

    def set_template_from_box(
        self, image: np.ndarray, box: BoundingBox, padding: int = 5
    ) -> None:
        """Extrahiert ein Template aus einem Bild anhand einer BoundingBox.

        Extracts template region from image with small padding for better matching.
        """
        h, w = image.shape[:2]
        x1 = max(0, box.x1 - padding)
        y1 = max(0, box.y1 - padding)
        x2 = min(w, box.x2 + padding)
        y2 = min(h, box.y2 + padding)
        region = image[y1:y2, x1:x2]
        if region.size > 0:
            self.set_template(region)

    def match(self, image: np.ndarray) -> list[BoundingBox]:
        """Sucht das Template im Bild auf mehreren Skalierungen.

        Three-pass matching for maximum robustness:
        1. Grayscale — standard opaque watermarks
        2. Edge-based — semi-transparent watermarks
        3. CLAHE-normalized — handles different lighting/exposure
        Results are deduplicated across all passes.
        """
        if self._template_gray is None or self._template_edges is None:
            return []

        img_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        img_edges = cv2.Canny(img_gray, 50, 150)
        img_h, img_w = image.shape[:2]

        boxes: list[BoundingBox] = []

        # Pass 1: Grayscale-Template-Matching (fuer opake Watermarks)
        boxes.extend(
            self._match_at_scales(
                img_gray,
                self._template_gray,
                img_h,
                img_w,
                self._match_threshold,
            )
        )

        # Pass 2: Edge-basiertes Matching (fuer semi-transparente Watermarks)
        boxes.extend(
            self._match_at_scales(
                img_edges,
                self._template_edges,
                img_h,
                img_w,
                self.EDGE_MATCH_THRESHOLD,
            )
        )

        # Pass 3: CLAHE-normalisiertes Matching (fuer unterschiedliche Belichtung)
        # CLAHE-normalized matching for varying exposure/lighting conditions
        if self._template_clahe is not None:
            img_clahe = self._clahe.apply(img_gray)
            boxes.extend(
                self._match_at_scales(
                    img_clahe,
                    self._template_clahe,
                    img_h,
                    img_w,
                    self.CLAHE_MATCH_THRESHOLD,
                )
            )

        # Randbereich-Filter: nur Matches am Bildrand behalten
        # Edge region filter: keep only matches near image edges
        boxes = self._filter_edge_region(boxes, img_h, img_w)

        return _deduplicate_boxes(boxes, iou_threshold=0.4)

    def _filter_edge_region(
        self, boxes: list[BoundingBox], img_h: int, img_w: int
    ) -> list[BoundingBox]:
        """Filtert Template-Matches die nicht im Randbereich liegen.

        Watermark logos appear at image edges (corners, bottom, sides).
        Matches in the center of the image are almost always false positives.
        """
        if not boxes:
            return boxes

        kept: list[BoundingBox] = []
        for box in boxes:
            # Box-Kanten pruefen (nicht Mittelpunkt) / Check box edges
            in_bottom = box.y2 > img_h * (1 - self.EDGE_MARGIN_BOTTOM)
            in_top = box.y1 < img_h * self.EDGE_MARGIN_TOP
            in_left = box.x1 < img_w * self.EDGE_MARGIN_SIDE
            in_right = box.x2 > img_w * (1 - self.EDGE_MARGIN_SIDE)

            if in_bottom or in_top or in_left or in_right:
                kept.append(box)

        filtered_count = len(boxes) - len(kept)
        if filtered_count > 0:
            logger.debug(
                "Template-Matching: %d Match(es) im Bildzentrum gefiltert",
                filtered_count,
            )

        return kept

    def _match_at_scales(
        self,
        image: np.ndarray,
        template: np.ndarray,
        img_h: int,
        img_w: int,
        threshold: float,
    ) -> list[BoundingBox]:
        """Multi-Scale-Matching einer Repraesentierung (Gray oder Edges).

        Runs cv2.matchTemplate at multiple scales and returns boxes above threshold.
        """
        t_h, t_w = template.shape[:2]
        boxes: list[BoundingBox] = []

        for scale in self.SCALES:
            new_w = int(t_w * scale)
            new_h = int(t_h * scale)

            # Template muss kleiner als Bild sein / Template must fit in image
            if new_w >= img_w or new_h >= img_h or new_w < 10 or new_h < 10:
                continue

            scaled = cv2.resize(template, (new_w, new_h), interpolation=cv2.INTER_AREA)

            # Konstante Bilder/Templates erzeugen NaN bei TM_CCOEFF_NORMED
            # Constant images/templates produce NaN with TM_CCOEFF_NORMED
            if np.std(scaled) < 1.0 or np.std(image) < 1.0:
                continue

            result = cv2.matchTemplate(image, scaled, cv2.TM_CCOEFF_NORMED)

            # NaN-Werte filtern / Filter NaN values
            result = np.nan_to_num(result, nan=0.0)

            locations = np.where(result >= threshold)
            for pt_y, pt_x in zip(*locations):
                conf = float(result[pt_y, pt_x])
                boxes.append(
                    BoundingBox(
                        x1=int(pt_x),
                        y1=int(pt_y),
                        x2=int(pt_x + new_w),
                        y2=int(pt_y + new_h),
                        confidence=conf,
                    )
                )

        return boxes


class WatermarkDetector:
    """YOLO-basierte Wasserzeichen-Erkennung mit TTA, Preprocessing und Template-Fallback.

    Zweistufig: YOLO (mit optionaler Test-Time-Augmentation und Kontrastverstaerkung)
    als Primaererkennung, TemplateWatermarkMatcher als Fallback.
    """

    DEFAULT_MODEL_PATH = "models/best.pt"
    HF_REPO = "corzent/yolo11x_watermark_detection"
    HF_FILENAME = "best.pt"

    # Typ-abhaengige Filterparameter / Type-specific filter parameters
    _TYPE_PARAMS: dict[str, dict] = {
        "logo": {
            "max_area_ratio": 0.15,       # Logos sind klein (max 15% Bildflaeche)
            "edge_margin_bottom": 0.40,    # Untere 40%
            "edge_margin_top": 0.15,       # Obere 15%
            "edge_margin_side": 0.20,      # Seitlich 20%
            "min_aspect_ratio": 0.3,       # Kompakt (quadratisch)
            "max_aspect_ratio": 3.0,
        },
        "text": {
            "max_area_ratio": 0.35,       # Text kann breiter sein (max 35%)
            "edge_margin_bottom": 0.50,    # Untere 50% (Text oft tiefer)
            "edge_margin_top": 0.20,       # Obere 20%
            "edge_margin_side": 0.10,      # Text selten seitlich
            "min_aspect_ratio": 0.0,       # Kein Form-Filter (flache Boxen ok)
            "max_aspect_ratio": 999.0,
        },
    }

    def __init__(
        self,
        model_path: str = DEFAULT_MODEL_PATH,
        confidence: float = 0.35,
        use_gpu: bool = True,
        strict_filter: bool = True,
        enhanced_detection: bool = True,
        watermark_type: str = "logo",
    ):
        self._model_path = model_path
        self._confidence = confidence
        self._use_gpu = use_gpu
        self._model = None
        self._last_error: str | None = None
        # Konfigurierbare Filter / Configurable filter settings
        self._strict_filter = strict_filter
        self._enhanced_detection = enhanced_detection
        # Wasserzeichen-Typ: "logo" oder "text" / Watermark type
        self._watermark_type = watermark_type if watermark_type in self._TYPE_PARAMS else "logo"
        self._params = self._TYPE_PARAMS[self._watermark_type]
        logger.info("WatermarkDetector Typ: %s", self._watermark_type)
        # Template-Matcher (optional, wird von aussen gesetzt)
        # Template matcher (optional, set externally by processor)
        self._template_matcher: TemplateWatermarkMatcher | None = None

    @property
    def template_matcher(self) -> TemplateWatermarkMatcher | None:
        return self._template_matcher

    @template_matcher.setter
    def template_matcher(self, matcher: TemplateWatermarkMatcher | None) -> None:
        self._template_matcher = matcher

    def _download_model(self) -> bool:
        """Laedt das Watermark-Model von HuggingFace herunter."""
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
        """Laedt das Watermark-Model (mit Auto-Download)."""
        if self._model is not None:
            return True

        self._last_error = None

        # Pfad fuer EXE/Development aufloesen
        model_path = _get_model_path(self._model_path)

        if not os.path.exists(model_path):
            # Im EXE-Modus: versuche im models-Ordner im _MEIPASS
            if hasattr(__import__("sys"), "_MEIPASS"):
                self._last_error = f"Watermark-Model nicht im Bundle: {model_path}"
                logger.error(
                    "Watermark-Model nicht im Bundle gefunden: %s", model_path
                )
                return False
            # Im Development-Modus: versuche Download
            if not self._download_model():
                self._last_error = "Watermark-Model Download fehlgeschlagen"
                return False
            # Nach Download neu aufloesen
            model_path = _get_model_path(self._model_path)

        try:
            from ultralytics import YOLO

            self._model = YOLO(model_path)
            logger.info("Watermark-Model geladen: %s", model_path)
            return True
        except Exception as e:
            self._last_error = str(e)
            logger.error(
                "Fehler beim Laden des Watermark-Models: %s", e, exc_info=True
            )
            return False

    @property
    def last_error(self) -> str | None:
        """Gibt die letzte Fehlermeldung beim Model-Laden zurueck."""
        return self._last_error

    def _is_edge_region(self, box: BoundingBox, img_h: int, img_w: int) -> bool:
        """Prueft ob die Box in einer typischen Watermark-Region liegt (Bildrand).

        Uses type-specific margins: logos need strict edge proximity,
        text watermarks have wider bottom margin but tighter side margins.
        """
        p = self._params
        # Unterer Rand / Bottom edge
        if box.y2 > img_h * (1 - p["edge_margin_bottom"]):
            return True
        # Oberer Rand / Top edge
        if box.y1 < img_h * p["edge_margin_top"]:
            return True
        # Linker Rand / Left edge
        if box.x1 < img_w * p["edge_margin_side"]:
            return True
        # Rechter Rand / Right edge
        if box.x2 > img_w * (1 - p["edge_margin_side"]):
            return True
        return False

    def _is_plausible_watermark(
        self, box: BoundingBox, img_h: int, img_w: int
    ) -> bool:
        """Filtert False Positives anhand Groesse, Position und Seitenverhaeltnis.

        Uses type-specific parameters for area, edge and aspect ratio checks.
        Logo: compact shapes at image edges. Text: wider shapes, relaxed form filter.
        """
        p = self._params
        img_area = img_h * img_w
        box_area = box.area

        # Zu grosse Boxen sind keine Watermarks / Too large = not a watermark
        if box_area > img_area * p["max_area_ratio"]:
            logger.debug(
                "WM-Box gefiltert (zu gross: %.1f%%, max=%.0f%%, typ=%s): %s",
                box_area / img_area * 100,
                p["max_area_ratio"] * 100,
                self._watermark_type,
                box,
            )
            return False

        # Seitenverhaeltnis-Filter (Logo: quadratisch, Text: kein Filter)
        # Aspect ratio filter (Logo: compact, Text: no filter)
        box_w = max(box.x2 - box.x1, 1)
        box_h = max(box.y2 - box.y1, 1)
        aspect = box_w / box_h
        if aspect < p["min_aspect_ratio"] or aspect > p["max_aspect_ratio"]:
            logger.debug(
                "WM-Box gefiltert (Seitenverhaeltnis %.2f, erlaubt=%.1f-%.1f, typ=%s): %s",
                aspect,
                p["min_aspect_ratio"],
                p["max_aspect_ratio"],
                self._watermark_type,
                box,
            )
            return False

        # Im strikten Modus: muss am Bildrand liegen
        # In strict mode: must be at image edge
        if self._strict_filter and not self._is_edge_region(box, img_h, img_w):
            logger.debug(
                "WM-Box gefiltert (nicht am Rand, strict=True, typ=%s): %s",
                self._watermark_type,
                box,
            )
            return False

        return True

    @staticmethod
    def _preprocess_for_detection(image: np.ndarray) -> np.ndarray:
        """Kontrastverstaerkung fuer semi-transparente Watermarks.

        Applies CLAHE (Contrast Limited Adaptive Histogram Equalization) to
        make faint or semi-transparent watermarks more visible to YOLO.
        """
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        l_channel, a_channel, b_channel = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        l_enhanced = clahe.apply(l_channel)
        enhanced_lab = cv2.merge([l_enhanced, a_channel, b_channel])
        return cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2BGR)

    def _run_yolo_inference(
        self, image: np.ndarray, conf: float, use_tta: bool = False
    ) -> list[BoundingBox]:
        """Fuehrt YOLO-Inferenz aus (optional mit TTA). Thread-safe.

        Runs YOLO inference with optional Test-Time Augmentation (augment=True)
        for improved detection of small or rotated watermarks.
        """
        if self._model is None:
            return []

        device = "cuda" if self._use_gpu else "cpu"

        with _watermark_lock:
            try:
                results = self._model(
                    image,
                    conf=conf,
                    device=device,
                    verbose=False,
                    augment=use_tta,
                )
            except RuntimeError:
                logger.warning("GPU-Fehler bei Watermark-Detection, Fallback CPU")
                results = self._model(
                    image,
                    conf=conf,
                    device="cpu",
                    verbose=False,
                    augment=use_tta,
                )

        boxes: list[BoundingBox] = []
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
        return boxes

    def detect(
        self,
        image: np.ndarray,
        confidence: float | None = None,
    ) -> list[BoundingBox]:
        """Erkennt Wasserzeichen im Bild. Thread-safe, zweistufig.

        Ablauf / Pipeline:
        1. YOLO-Inferenz auf Original (mit TTA falls enhanced_detection aktiv)
        2. Falls enhanced: zweiter Pass auf kontrastverstaerktem Bild
        3. Plausibilitaetsfilter auf alle YOLO-Detections
        4. Falls keine YOLO-Treffer: Template-Matching als Fallback
        5. Ergebnisse deduplizieren und zurueckgeben
        """
        if self._model is None:
            if not self.load_model():
                return []

        conf = confidence or self._confidence
        use_tta = self._enhanced_detection

        # Pass 1: YOLO auf Original-Bild (mit TTA wenn enhanced)
        raw_boxes = self._run_yolo_inference(image, conf, use_tta=use_tta)
        logger.debug("YOLO Pass 1: %d raw detections", len(raw_boxes))

        # Pass 2: YOLO auf kontrastverstaerktem Bild (nur bei enhanced)
        if self._enhanced_detection:
            enhanced_img = self._preprocess_for_detection(image)
            extra_boxes = self._run_yolo_inference(enhanced_img, conf, use_tta=False)
            logger.debug("YOLO Pass 2 (enhanced): %d extra detections", len(extra_boxes))
            raw_boxes.extend(extra_boxes)
            raw_boxes = _deduplicate_boxes(raw_boxes, iou_threshold=0.5)

        # Plausibilitaetsfilter anwenden
        img_h, img_w = image.shape[:2]
        filtered_boxes = [
            b for b in raw_boxes if self._is_plausible_watermark(b, img_h, img_w)
        ]

        if len(raw_boxes) != len(filtered_boxes):
            logger.info(
                "Watermark-Filter: %d von %d Detections als False Positive entfernt",
                len(raw_boxes) - len(filtered_boxes),
                len(raw_boxes),
            )

        # Template-Matching IMMER parallel zu YOLO ausfuehren (nicht nur Fallback)
        # Template matching always runs alongside YOLO for better detection
        if self._template_matcher and self._template_matcher.has_template:
            template_boxes = self._template_matcher.match(image)
            if template_boxes:
                logger.info(
                    "Template-Matching: %d Watermarks gefunden",
                    len(template_boxes),
                )
                filtered_boxes.extend(template_boxes)
                filtered_boxes = _deduplicate_boxes(filtered_boxes, iou_threshold=0.4)

        logger.info(
            "%d Wasserzeichen erkannt (conf >= %.2f, enhanced=%s)",
            len(filtered_boxes),
            conf,
            self._enhanced_detection,
        )
        return filtered_boxes

    def set_confidence(self, confidence: float) -> None:
        self._confidence = confidence

    def set_gpu(self, use_gpu: bool) -> None:
        self._use_gpu = use_gpu

    def set_strict_filter(self, strict: bool) -> None:
        self._strict_filter = strict

    def set_enhanced_detection(self, enhanced: bool) -> None:
        self._enhanced_detection = enhanced
