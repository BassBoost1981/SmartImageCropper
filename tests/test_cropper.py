"""Unit Tests für CropEngine."""

import numpy as np
import pytest

from src.core.cropper import CropEngine, CropRegion
from src.core.detector import BoundingBox


class TestCropRegion:
    def test_dimensions(self):
        r = CropRegion(10, 20, 110, 220)
        assert r.width == 100
        assert r.height == 200

    def test_repr(self):
        r = CropRegion(0, 0, 50, 50)
        assert "CropRegion" in repr(r)


class TestCropEngine:
    def setup_method(self):
        self.engine = CropEngine()
        # 1000x800 Testbild (h, w, c)
        self.image_shape = (800, 1000, 3)

    def test_no_persons(self):
        """Ohne Personen soll None zurückgegeben werden."""
        result = self.engine.calculate_crop_region(
            self.image_shape, person_boxes=[]
        )
        assert result is None

    def test_single_person(self):
        """Crop um eine einzelne Person."""
        boxes = [BoundingBox(200, 100, 400, 600, 0.9)]
        result = self.engine.calculate_crop_region(
            self.image_shape, boxes, padding_percent=10
        )
        assert result is not None
        # Crop muss Person enthalten
        assert result.x1 <= 200
        assert result.y1 <= 100
        assert result.x2 >= 400
        assert result.y2 >= 600

    def test_multiple_persons(self):
        """Crop soll alle Personen umfassen."""
        boxes = [
            BoundingBox(100, 100, 300, 500, 0.9),
            BoundingBox(500, 150, 700, 550, 0.8),
        ]
        result = self.engine.calculate_crop_region(
            self.image_shape, boxes, padding_percent=5
        )
        assert result is not None
        assert result.x1 <= 100
        assert result.x2 >= 700

    def test_padding(self):
        """Padding vergrößert den Crop-Bereich."""
        boxes = [BoundingBox(300, 200, 500, 600, 0.9)]
        no_pad = self.engine.calculate_crop_region(
            self.image_shape, boxes, padding_percent=0
        )
        with_pad = self.engine.calculate_crop_region(
            self.image_shape, boxes, padding_percent=20
        )
        assert with_pad.x1 <= no_pad.x1
        assert with_pad.y1 <= no_pad.y1
        assert with_pad.x2 >= no_pad.x2
        assert with_pad.y2 >= no_pad.y2

    def test_watermark_manual(self):
        """Manueller Watermark-Schnitt am unteren Rand."""
        boxes = [BoundingBox(200, 100, 400, 700, 0.9)]
        result = self.engine.calculate_crop_region(
            self.image_shape, boxes,
            padding_percent=0, watermark_percent=20
        )
        assert result is not None
        # Crop darf nicht in die unteren 20% reichen
        max_y = int(800 * 0.8)
        assert result.y2 <= max_y

    def test_watermark_auto(self):
        """Auto-Watermark-Erkennung verkürzt den Crop."""
        boxes = [BoundingBox(200, 100, 400, 500, 0.9)]
        wm_boxes = [BoundingBox(100, 700, 900, 790, 0.8)]
        result = self.engine.calculate_crop_region(
            self.image_shape, boxes,
            padding_percent=5, watermark_boxes=wm_boxes
        )
        assert result is not None
        # Crop soll über dem Watermark enden
        assert result.y2 <= 700

    def test_crop_clamps_to_image(self):
        """Crop-Region darf nicht über Bildgrenzen hinausgehen."""
        boxes = [BoundingBox(0, 0, 1000, 800, 0.9)]
        result = self.engine.calculate_crop_region(
            self.image_shape, boxes, padding_percent=50
        )
        assert result.x1 >= 0
        assert result.y1 >= 0
        assert result.x2 <= 1000
        assert result.y2 <= 800

    def test_crop_image(self):
        """Tatsächliches Zuschneiden eines Arrays."""
        img = np.zeros((800, 1000, 3), dtype=np.uint8)
        img[100:600, 200:400] = 255  # Weißer Bereich

        region = CropRegion(200, 100, 400, 600)
        cropped = self.engine.crop_image(img, region)
        assert cropped.shape == (500, 200, 3)
        assert np.all(cropped == 255)
