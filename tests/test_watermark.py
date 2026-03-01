"""Unit Tests fuer WatermarkDetector und TemplateWatermarkMatcher."""

import cv2
import numpy as np
import pytest

from src.core.detector import BoundingBox
from src.core.watermark import (
    TemplateWatermarkMatcher,
    WatermarkDetector,
    _compute_iou,
    _deduplicate_boxes,
)


class TestComputeIoU:
    """Tests fuer die IoU-Berechnung."""

    def test_identical_boxes(self):
        a = BoundingBox(0, 0, 100, 100, 0.9)
        b = BoundingBox(0, 0, 100, 100, 0.8)
        assert _compute_iou(a, b) == pytest.approx(1.0)

    def test_no_overlap(self):
        a = BoundingBox(0, 0, 50, 50, 0.9)
        b = BoundingBox(100, 100, 200, 200, 0.8)
        assert _compute_iou(a, b) == 0.0

    def test_partial_overlap(self):
        a = BoundingBox(0, 0, 100, 100, 0.9)
        b = BoundingBox(50, 50, 150, 150, 0.8)
        # Overlap: 50x50 = 2500, Union: 10000 + 10000 - 2500 = 17500
        assert _compute_iou(a, b) == pytest.approx(2500 / 17500, abs=0.01)

    def test_contained_box(self):
        a = BoundingBox(0, 0, 200, 200, 0.9)
        b = BoundingBox(50, 50, 100, 100, 0.8)
        # Overlap = area of b = 2500, Union = 40000 + 2500 - 2500 = 40000
        assert _compute_iou(a, b) == pytest.approx(2500 / 40000, abs=0.01)


class TestDeduplicateBoxes:
    """Tests fuer die Deduplizierung von Bounding Boxes."""

    def test_empty(self):
        assert _deduplicate_boxes([]) == []

    def test_single_box(self):
        boxes = [BoundingBox(0, 0, 100, 100, 0.9)]
        result = _deduplicate_boxes(boxes)
        assert len(result) == 1

    def test_no_overlap(self):
        boxes = [
            BoundingBox(0, 0, 50, 50, 0.9),
            BoundingBox(200, 200, 300, 300, 0.8),
        ]
        result = _deduplicate_boxes(boxes)
        assert len(result) == 2

    def test_duplicate_removed(self):
        """Hoechste Confidence wird behalten bei hohem Overlap."""
        boxes = [
            BoundingBox(0, 0, 100, 100, 0.7),
            BoundingBox(5, 5, 105, 105, 0.9),
        ]
        result = _deduplicate_boxes(boxes, iou_threshold=0.5)
        assert len(result) == 1
        assert result[0].confidence == 0.9

    def test_three_boxes_two_overlap(self):
        boxes = [
            BoundingBox(0, 0, 100, 100, 0.9),
            BoundingBox(10, 10, 110, 110, 0.7),  # overlaps with first
            BoundingBox(500, 500, 600, 600, 0.8),  # no overlap
        ]
        result = _deduplicate_boxes(boxes, iou_threshold=0.5)
        assert len(result) == 2


class TestWatermarkDetectorFilters:
    """Tests fuer die Plausibilitaetsfilter des WatermarkDetectors."""

    def setup_method(self):
        self.detector = WatermarkDetector(
            model_path="nonexistent.pt",
            confidence=0.3,
            use_gpu=False,
        )

    def test_edge_region_bottom(self):
        """Box am unteren Rand wird als Edge erkannt."""
        box = BoundingBox(100, 900, 300, 980, 0.8)
        assert self.detector._is_edge_region(box, img_h=1000, img_w=1000) is True

    def test_edge_region_top(self):
        """Box am oberen Rand wird als Edge erkannt."""
        box = BoundingBox(100, 10, 300, 80, 0.8)
        assert self.detector._is_edge_region(box, img_h=1000, img_w=1000) is True

    def test_edge_region_left(self):
        """Box am linken Rand wird als Edge erkannt."""
        box = BoundingBox(10, 400, 80, 600, 0.8)
        assert self.detector._is_edge_region(box, img_h=1000, img_w=1000) is True

    def test_edge_region_right(self):
        """Box am rechten Rand wird als Edge erkannt."""
        box = BoundingBox(900, 400, 990, 600, 0.8)
        assert self.detector._is_edge_region(box, img_h=1000, img_w=1000) is True

    def test_center_not_edge(self):
        """Box in der Mitte wird nicht als Edge erkannt."""
        box = BoundingBox(400, 400, 600, 600, 0.8)
        assert self.detector._is_edge_region(box, img_h=1000, img_w=1000) is False

    def test_plausible_small_at_edge(self):
        """Kleine Box am Rand = plausibles Watermark."""
        box = BoundingBox(800, 900, 950, 980, 0.8)
        assert self.detector._is_plausible_watermark(box, 1000, 1000) is True

    def test_too_large_rejected(self):
        """Zu grosse Box wird abgelehnt (>25% der Bildflaeche)."""
        box = BoundingBox(0, 0, 600, 600, 0.8)  # 360000 / 1000000 = 36%
        assert self.detector._is_plausible_watermark(box, 1000, 1000) is False

    def test_strict_filter_center_rejected(self):
        """Im strict-Modus: kleine Box in der Mitte wird abgelehnt."""
        self.detector._strict_filter = True
        box = BoundingBox(400, 400, 450, 450, 0.8)
        assert self.detector._is_plausible_watermark(box, 1000, 1000) is False

    def test_relaxed_filter_center_accepted(self):
        """Im relaxed-Modus: kleine Box in der Mitte wird akzeptiert."""
        self.detector._strict_filter = False
        box = BoundingBox(400, 400, 450, 450, 0.8)
        assert self.detector._is_plausible_watermark(box, 1000, 1000) is True

    def test_max_area_ratio_increased(self):
        """MAX_AREA_RATIO ist jetzt 0.25 (nicht mehr 0.15)."""
        assert WatermarkDetector.MAX_AREA_RATIO == 0.25
        # 20% Flaeche: bei 0.15 waere das abgelehnt, bei 0.25 akzeptiert
        box = BoundingBox(0, 900, 500, 1000, 0.8)  # 50000 / 1000000 = 5%
        assert self.detector._is_plausible_watermark(box, 1000, 1000) is True

    def test_detect_without_model_returns_empty(self):
        """Detect ohne geladenes Model bei fehlendem Pfad gibt leere Liste."""
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        result = self.detector.detect(img)
        assert result == []


class TestPreprocessForDetection:
    """Tests fuer die CLAHE-Vorverarbeitung."""

    def test_output_shape_unchanged(self):
        """Output hat gleiche Shape wie Input."""
        img = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        result = WatermarkDetector._preprocess_for_detection(img)
        assert result.shape == img.shape

    def test_output_dtype_unchanged(self):
        """Output hat gleichen dtype wie Input."""
        img = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        result = WatermarkDetector._preprocess_for_detection(img)
        assert result.dtype == np.uint8

    def test_low_contrast_enhanced(self):
        """Bild mit niedrigem Kontrast bekommt hoehere Varianz."""
        # Bild mit sehr niedrigem Kontrast (alles um Wert 120)
        img = np.full((200, 200, 3), 120, dtype=np.uint8)
        img[50:150, 50:150] = 130  # leicht hellerer Block
        result = WatermarkDetector._preprocess_for_detection(img)
        # CLAHE sollte den Kontrast erhoehen
        orig_std = np.std(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(float))
        result_std = np.std(cv2.cvtColor(result, cv2.COLOR_BGR2GRAY).astype(float))
        assert result_std >= orig_std


class TestTemplateWatermarkMatcher:
    """Tests fuer den Template-Matcher."""

    def setup_method(self):
        self.matcher = TemplateWatermarkMatcher()

    def test_no_template_returns_empty(self):
        """Ohne Template gibt match() leere Liste zurueck."""
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        assert self.matcher.match(img) == []

    def test_has_template_false_initially(self):
        assert self.matcher.has_template is False

    def test_set_template(self):
        template = np.zeros((50, 80, 3), dtype=np.uint8)
        self.matcher.set_template(template)
        assert self.matcher.has_template is True

    def test_set_template_from_box(self):
        """Template-Extraktion aus Bild per BoundingBox."""
        img = np.zeros((200, 300, 3), dtype=np.uint8)
        img[50:100, 100:200] = 255  # weisser Block
        box = BoundingBox(100, 50, 200, 100, 0.9)
        self.matcher.set_template_from_box(img, box)
        assert self.matcher.has_template is True

    def test_exact_match_found(self):
        """Exaktes Template wird im Bild gefunden."""
        # Erstelle ein Bild mit einem markanten Block
        img = np.zeros((400, 600, 3), dtype=np.uint8)
        # Fuege ein "Logo" unten rechts ein
        logo = np.random.randint(100, 255, (40, 80, 3), dtype=np.uint8)
        img[350:390, 500:580] = logo

        # Setze das Logo als Template
        self.matcher.set_template(logo)
        self.matcher._match_threshold = 0.8

        boxes = self.matcher.match(img)
        assert len(boxes) >= 1
        # Mindestens ein Treffer sollte nahe der Logo-Position sein
        found_near = any(
            abs(b.x1 - 500) < 20 and abs(b.y1 - 350) < 20
            for b in boxes
        )
        assert found_near, f"Logo nicht an erwarteter Position gefunden: {boxes}"

    def test_no_match_on_blank(self):
        """Kein Match auf komplett schwarzem Bild mit weissem Template."""
        img = np.zeros((400, 600, 3), dtype=np.uint8)
        template = np.full((40, 80, 3), 255, dtype=np.uint8)
        self.matcher.set_template(template)
        self.matcher._match_threshold = 0.9
        boxes = self.matcher.match(img)
        assert len(boxes) == 0


class TestWatermarkDetectorInit:
    """Tests fuer die neuen Initialisierungsparameter."""

    def test_default_strict_filter(self):
        d = WatermarkDetector(model_path="x.pt", use_gpu=False)
        assert d._strict_filter is True

    def test_custom_strict_filter(self):
        d = WatermarkDetector(model_path="x.pt", use_gpu=False, strict_filter=False)
        assert d._strict_filter is False

    def test_default_enhanced_detection(self):
        d = WatermarkDetector(model_path="x.pt", use_gpu=False)
        assert d._enhanced_detection is False

    def test_custom_enhanced_detection(self):
        d = WatermarkDetector(
            model_path="x.pt", use_gpu=False, enhanced_detection=True
        )
        assert d._enhanced_detection is True

    def test_set_strict_filter(self):
        d = WatermarkDetector(model_path="x.pt", use_gpu=False)
        d.set_strict_filter(False)
        assert d._strict_filter is False

    def test_set_enhanced_detection(self):
        d = WatermarkDetector(model_path="x.pt", use_gpu=False)
        d.set_enhanced_detection(True)
        assert d._enhanced_detection is True

    def test_template_matcher_property(self):
        d = WatermarkDetector(model_path="x.pt", use_gpu=False)
        assert d.template_matcher is None
        matcher = TemplateWatermarkMatcher()
        d.template_matcher = matcher
        assert d.template_matcher is matcher
