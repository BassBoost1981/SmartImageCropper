"""Unit Tests für PersonDetector."""

import os

import numpy as np
import pytest

from src.core.detector import BoundingBox, PersonDetector


class TestBoundingBox:
    def test_properties(self):
        box = BoundingBox(10, 20, 110, 220, 0.95)
        assert box.width == 100
        assert box.height == 200
        assert box.center == (60, 120)
        assert box.area == 20000

    def test_confidence(self):
        box = BoundingBox(0, 0, 50, 50, 0.73)
        assert box.confidence == 0.73


class TestPersonDetector:
    def test_init(self):
        detector = PersonDetector(
            model_path="models/yolov8n.pt",
            confidence=0.6,
            use_gpu=False,
        )
        assert detector._confidence == 0.6
        assert detector._use_gpu is False

    def test_set_confidence(self):
        detector = PersonDetector()
        detector.set_confidence(0.8)
        assert detector._confidence == 0.8

    def test_set_gpu(self):
        detector = PersonDetector()
        detector.set_gpu(False)
        assert detector._use_gpu is False

    def test_load_model_missing(self):
        detector = PersonDetector(model_path="nonexistent/model.pt")
        assert detector.load_model() is False

    @pytest.mark.skipif(
        not os.path.exists("models/yolov8n.pt"),
        reason="YOLO model nicht vorhanden",
    )
    def test_detect_with_real_model(self):
        """Integrationtest mit echtem Model (nur wenn vorhanden)."""
        detector = PersonDetector(
            model_path="models/yolov8n.pt",
            confidence=0.3,
            use_gpu=False,
        )
        assert detector.load_model() is True

        # Dummy-Bild (keine Person erwartet)
        img = np.zeros((640, 480, 3), dtype=np.uint8)
        boxes = detector.detect(img)
        assert isinstance(boxes, list)

    def test_detect_without_model(self):
        """Detect ohne geladenes Model bei fehlendem Pfad gibt leere Liste."""
        detector = PersonDetector(model_path="nonexistent.pt")
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        result = detector.detect(img)
        assert result == []
