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
        Wenn keine Person erkannt wird, wird das gesamte Bild als Basis
        genommen und nur das Watermark entfernt.

        If no persons are detected, uses the full image as base and only
        removes watermarks.
        """
        img_h, img_w = image_shape[:2]

        if person_boxes:
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
        else:
            # Keine Person erkannt → gesamtes Bild als Basis, nur WM entfernen
            # No person detected → use full image as base, only remove WM
            has_wm = (watermark_boxes and len(watermark_boxes) > 0) or watermark_percent > 0
            if not has_wm:
                return None
            crop_x1, crop_y1, crop_x2, crop_y2 = 0, 0, img_w, img_h

        # Watermark-Vermeidung: manueller Modus (Prozent vom unteren Rand)
        if watermark_percent > 0:
            wm_top = int(img_h * (1 - watermark_percent / 100))
            if crop_y2 > wm_top:
                crop_y2 = wm_top

        # Watermark-Vermeidung: Auto-Modus (erkannte Watermark-Boxen)
        # Bestimmt ob WM eher oben/unten oder links/rechts liegt und
        # passt nur die dominante Achse an. Verhindert, dass Text-WMs
        # am unteren Rand auch seitlich abgeschnitten werden.
        #
        # Determines if WM is primarily top/bottom or left/right and
        # only adjusts the dominant axis. Prevents bottom text watermarks
        # from also cropping the sides.
        if watermark_boxes:
            for wb in watermark_boxes:
                # Prüfe ob Watermark den Crop-Bereich schneidet oder darin liegt
                overlaps_x = wb.x1 < crop_x2 and wb.x2 > crop_x1
                overlaps_y = wb.y1 < crop_y2 and wb.y2 > crop_y1

                if overlaps_x and overlaps_y:
                    wm_center_y = (wb.y1 + wb.y2) / 2
                    wm_center_x = (wb.x1 + wb.x2) / 2
                    crop_mid_y = (crop_y1 + crop_y2) / 2
                    crop_mid_x = (crop_x1 + crop_x2) / 2
                    crop_h = max(crop_y2 - crop_y1, 1)
                    crop_w = max(crop_x2 - crop_x1, 1)

                    # Normalisierte Distanz vom Crop-Zentrum bestimmt dominante Achse
                    # Normalized distance from crop center determines dominant axis
                    dist_y = abs(wm_center_y - crop_mid_y) / crop_h
                    dist_x = abs(wm_center_x - crop_mid_x) / crop_w

                    if dist_y >= dist_x:
                        # WM ist primaer oben/unten → nur Y anpassen
                        # WM is primarily top/bottom → only adjust Y
                        if wm_center_y > crop_mid_y:
                            crop_y2 = min(crop_y2, wb.y1)
                        else:
                            crop_y1 = max(crop_y1, wb.y2)
                    else:
                        # WM ist primaer links/rechts → nur X anpassen
                        # WM is primarily left/right → only adjust X
                        if wm_center_x > crop_mid_x:
                            crop_x2 = min(crop_x2, wb.x1)
                        else:
                            crop_x1 = max(crop_x1, wb.x2)

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
