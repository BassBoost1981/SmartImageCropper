"""CropEngine: Berechnet und führt Crop-Operationen durch."""

import numpy as np

from src.core.detector import BoundingBox
from src.utils.logger import get_logger

logger = get_logger(__name__)


class CropRegion:
    """Definiert einen Crop-Bereich."""

    def __init__(self, x1: int, y1: int, x2: int, y2: int):
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1

    def __repr__(self) -> str:
        return f"CropRegion({self.x1}, {self.y1}, {self.x2}, {self.y2})"


class CropEngine:
    """Berechnet Crop-Regionen und schneidet Bilder zu."""

    @staticmethod
    def calculate_crop_region(
        image_shape: tuple[int, ...],
        person_boxes: list[BoundingBox],
        padding_percent: float = 10.0,
        watermark_boxes: list[BoundingBox] | None = None,
        watermark_percent: float = 0.0,
    ) -> CropRegion | None:
        """Berechnet die optimale Crop-Region.

        Berücksichtigt Person-BBoxen, Padding und Watermark-Vermeidung.
        Watermarks außerhalb des ursprünglichen Crop-Bereichs werden ignoriert.
        """
        if not person_boxes:
            return None

        img_h, img_w = image_shape[:2]

        # Vereinige alle Person-BBoxen
        min_x = min(b.x1 for b in person_boxes)
        min_y = min(b.y1 for b in person_boxes)
        max_x = max(b.x2 for b in person_boxes)
        max_y = max(b.y2 for b in person_boxes)

        # Padding hinzufügen
        pad_x = int((max_x - min_x) * padding_percent / 100)
        pad_y = int((max_y - min_y) * padding_percent / 100)

        crop_x1 = max(0, min_x - pad_x)
        crop_y1 = max(0, min_y - pad_y)
        crop_x2 = min(img_w, max_x + pad_x)
        crop_y2 = min(img_h, max_y + pad_y)

        # Watermark-Vermeidung: manueller Modus (Prozent vom unteren Rand)
        if watermark_percent > 0:
            wm_top = int(img_h * (1 - watermark_percent / 100))
            if crop_y2 > wm_top:
                crop_y2 = wm_top

        # Watermark-Vermeidung: Auto-Modus (erkannte Watermark-Boxen)
        # Nur Watermarks berücksichtigen, die den ursprünglichen Crop-Bereich schneiden
        if watermark_boxes:
            for wb in watermark_boxes:
                # Prüfe ob Watermark den Crop-Bereich schneidet
                # (nicht nur ob es nahe ist, sondern echte Überschneidung)
                overlaps_x = wb.x1 < crop_x2 and wb.x2 > crop_x1
                overlaps_y = wb.y1 < crop_y2 and wb.y2 > crop_y1

                if overlaps_x and overlaps_y:
                    # Watermark schneidet den Crop-Bereich -> anpassen
                    if wb.y1 > (crop_y1 + crop_y2) / 2:
                        # Watermark ist im unteren Bereich -> Crop nach oben begrenzen
                        crop_y2 = min(crop_y2, wb.y1)
                    else:
                        # Watermark ist im oberen Bereich -> Crop nach unten begrenzen
                        crop_y1 = max(crop_y1, wb.y2)

        # Sicherstellen, dass der Crop-Bereich gültig ist
        if crop_x2 <= crop_x1 or crop_y2 <= crop_y1:
            logger.warning("Ungültiger Crop-Bereich, verwende gesamtes Bild")
            return CropRegion(0, 0, img_w, img_h)

        # Mindestgröße sicherstellen (min 50x50)
        if (crop_x2 - crop_x1) < 50 or (crop_y2 - crop_y1) < 50:
            logger.warning("Crop-Bereich zu klein, verwende gesamtes Bild")
            return CropRegion(0, 0, img_w, img_h)

        return CropRegion(crop_x1, crop_y1, crop_x2, crop_y2)

    @staticmethod
    def crop_image(image: np.ndarray, region: CropRegion) -> np.ndarray:
        """Schneidet das Bild anhand der CropRegion zu."""
        return image[region.y1 : region.y2, region.x1 : region.x2].copy()
