"""Split-View Vorschau (Vorher/Nachher) mit Detection-Overlay und Navigation."""

import cv2
import numpy as np
from PyQt6.QtCore import Qt, QPoint, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap, QPainter, QPen, QColor, QFont, QBrush
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from src.core.cropper import CropRegion
from src.core.detector import BoundingBox
from src.ui.widgets import StyledButton


def numpy_to_qpixmap(image: np.ndarray, max_size: int = 800) -> QPixmap:
    """Konvertiert ein BGR NumPy-Array in ein QPixmap."""
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb.shape

    if max(h, w) > max_size:
        scale = max_size / max(h, w)
        new_w, new_h = int(w * scale), int(h * scale)
        rgb = cv2.resize(rgb, (new_w, new_h), interpolation=cv2.INTER_AREA)
        h, w = new_h, new_w

    bytes_per_line = ch * w
    qimage = QImage(rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimage.copy())


def draw_all_overlays(
    pixmap: QPixmap,
    image_shape: tuple[int, ...],
    person_boxes: list[BoundingBox] | None = None,
    watermark_boxes: list[BoundingBox] | None = None,
    crop_region: CropRegion | None = None,
) -> QPixmap:
    """Zeichnet alle Overlays auf ein QPixmap: Personen, Watermarks, Crop-Region."""
    result = pixmap.copy()
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    orig_h, orig_w = image_shape[:2]
    scale_x = result.width() / orig_w
    scale_y = result.height() / orig_h

    font = QFont("Lexend", 10, QFont.Weight.Bold)
    painter.setFont(font)

    # --- Crop-Region: halbtransparente Abdunklung außerhalb ---
    if crop_region:
        cx1 = int(crop_region.x1 * scale_x)
        cy1 = int(crop_region.y1 * scale_y)
        cx2 = int(crop_region.x2 * scale_x)
        cy2 = int(crop_region.y2 * scale_y)

        # Dunkle Bereiche außerhalb des Crops
        dim = QColor(0, 0, 0, 120)
        painter.fillRect(0, 0, result.width(), cy1, dim)                          # oben
        painter.fillRect(0, cy2, result.width(), result.height() - cy2, dim)      # unten
        painter.fillRect(0, cy1, cx1, cy2 - cy1, dim)                             # links
        painter.fillRect(cx2, cy1, result.width() - cx2, cy2 - cy1, dim)          # rechts

        # Crop-Rahmen (grün, gestrichelt)
        crop_pen = QPen(QColor(46, 204, 113, 230))
        crop_pen.setWidth(2)
        crop_pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(crop_pen)
        painter.drawRect(cx1, cy1, cx2 - cx1, cy2 - cy1)

        # Label
        painter.setPen(QColor(46, 204, 113, 255))
        crop_w = crop_region.x2 - crop_region.x1
        crop_h = crop_region.y2 - crop_region.y1
        painter.drawText(QPoint(cx1 + 4, cy1 - 6), f"Zuschnitt {crop_w}x{crop_h}")

    # --- Person-Boxen (lila) ---
    if person_boxes:
        pen = QPen(QColor(168, 85, 247, 200))
        pen.setWidth(2)
        painter.setPen(pen)

        for box in person_boxes:
            x1 = int(box.x1 * scale_x)
            y1 = int(box.y1 * scale_y)
            x2 = int(box.x2 * scale_x)
            y2 = int(box.y2 * scale_y)
            painter.drawRect(x1, y1, x2 - x1, y2 - y1)

            painter.setPen(QColor(255, 255, 255, 220))
            painter.drawText(QPoint(x1 + 4, y1 - 6), f"Person {box.confidence:.0%}")
            painter.setPen(pen)

    # --- Watermark-Boxen (rot, gestrichelt) ---
    if watermark_boxes:
        pen = QPen(QColor(231, 76, 60, 220))
        pen.setWidth(2)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)

        for box in watermark_boxes:
            x1 = int(box.x1 * scale_x)
            y1 = int(box.y1 * scale_y)
            x2 = int(box.x2 * scale_x)
            y2 = int(box.y2 * scale_y)
            painter.drawRect(x1, y1, x2 - x1, y2 - y1)

            painter.setPen(QColor(231, 76, 60, 255))
            painter.drawText(QPoint(x1 + 4, y1 - 6), f"Watermark {box.confidence:.0%}")
            painter.setPen(pen)

    painter.end()
    return result


class PreviewWidget(QWidget):
    """Vorher/Nachher Preview-Widget mit Detection-Overlay und Bild-Navigation."""

    # Signal: User will Bild X sehen (index)
    preview_requested = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_index = 0
        self._total_images = 0
        self._original_image = None
        self._original_shape = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # === Navigation Bar ===
        nav_bar = QHBoxLayout()
        nav_bar.setSpacing(8)

        self._prev_btn = StyledButton("◀  Zurück", variant="secondary")
        self._prev_btn.setFixedWidth(120)
        self._prev_btn.clicked.connect(self._go_prev)
        nav_bar.addWidget(self._prev_btn)

        self._nav_label = QLabel("Kein Bild")
        self._nav_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._nav_label.setObjectName("subtitle")
        nav_bar.addWidget(self._nav_label, 1)

        self._next_btn = StyledButton("Weiter  ▶", variant="secondary")
        self._next_btn.setFixedWidth(120)
        self._next_btn.clicked.connect(self._go_next)
        nav_bar.addWidget(self._next_btn)

        layout.addLayout(nav_bar)

        # === Dateiname / Info ===
        self._info = QLabel("")
        self._info.setObjectName("stat-label")
        self._info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._info)

        # === Vorher/Nachher Container ===
        preview_container = QHBoxLayout()
        preview_container.setSpacing(12)

        # Vorher (Original mit Overlays)
        self._before_frame = QFrame()
        self._before_frame.setObjectName("card")
        before_layout = QVBoxLayout(self._before_frame)
        self._before_label = QLabel("Original")
        self._before_label.setObjectName("stat-label")
        self._before_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._before_image = QLabel()
        self._before_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._before_image.setMinimumSize(200, 200)
        self._before_image.setStyleSheet("background: rgba(15, 15, 30, 0.5); border-radius: 8px;")
        before_layout.addWidget(self._before_label)
        before_layout.addWidget(self._before_image, 1)
        preview_container.addWidget(self._before_frame, 1)

        # Nachher (Cropped)
        self._after_frame = QFrame()
        self._after_frame.setObjectName("card")
        after_layout = QVBoxLayout(self._after_frame)
        self._after_label = QLabel("Zugeschnitten")
        self._after_label.setObjectName("stat-label")
        self._after_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._after_image = QLabel()
        self._after_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._after_image.setMinimumSize(200, 200)
        self._after_image.setStyleSheet("background: rgba(15, 15, 30, 0.5); border-radius: 8px;")
        after_layout.addWidget(self._after_label)
        after_layout.addWidget(self._after_image, 1)
        preview_container.addWidget(self._after_frame, 1)

        layout.addLayout(preview_container, 1)

        # === Legende ===
        legend = QHBoxLayout()
        legend.setSpacing(16)
        legend.addStretch()
        for color, label in [
            ("#a855f7", "Person"),
            ("#e74c3c", "Watermark"),
            ("#2ecc71", "Zuschnitt"),
        ]:
            dot = QLabel(f"● {label}")
            dot.setStyleSheet(f"color: {color}; font-size: 11px;")
            legend.addWidget(dot)
        legend.addStretch()
        layout.addLayout(legend)

        self._show_placeholder()
        self._update_nav_buttons()

    def _show_placeholder(self) -> None:
        for img_label in (self._before_image, self._after_image):
            img_label.setText("Kein Bild geladen")
            img_label.setPixmap(QPixmap())

    def set_image_count(self, count: int) -> None:
        """Setzt die Gesamtzahl der Bilder für die Navigation."""
        self._total_images = count
        if count == 0:
            self._current_index = 0
            self._nav_label.setText("Kein Bild")
        else:
            self._current_index = 0
            self._nav_label.setText(f"Bild 1 / {count}")
        self._update_nav_buttons()

    def set_current_index(self, index: int) -> None:
        """Setzt den aktuellen Bild-Index."""
        self._current_index = index
        self._nav_label.setText(f"Bild {index + 1} / {self._total_images}")
        self._update_nav_buttons()

    def _update_nav_buttons(self) -> None:
        self._prev_btn.setEnabled(self._current_index > 0)
        self._next_btn.setEnabled(
            self._total_images > 0 and self._current_index < self._total_images - 1
        )

    def _go_prev(self) -> None:
        if self._current_index > 0:
            self._current_index -= 1
            self._nav_label.setText(
                f"Bild {self._current_index + 1} / {self._total_images}"
            )
            self._update_nav_buttons()
            self.preview_requested.emit(self._current_index)

    def _go_next(self) -> None:
        if self._current_index < self._total_images - 1:
            self._current_index += 1
            self._nav_label.setText(
                f"Bild {self._current_index + 1} / {self._total_images}"
            )
            self._update_nav_buttons()
            self.preview_requested.emit(self._current_index)

    def set_preview(
        self,
        original: np.ndarray,
        cropped: np.ndarray | None = None,
        boxes: list[BoundingBox] | None = None,
        filename: str = "",
        watermark_boxes: list[BoundingBox] | None = None,
        crop_region: CropRegion | None = None,
    ) -> None:
        """Setzt das Vorher/Nachher-Preview mit allen Overlays."""
        self._original_image = original
        self._original_shape = original.shape

        if filename:
            self._info.setText(filename)

        # Original mit allen Overlays
        max_w = max(200, self._before_image.width() - 20)
        orig_pixmap = numpy_to_qpixmap(original, max_size=max_w)
        orig_pixmap = draw_all_overlays(
            orig_pixmap, original.shape,
            person_boxes=boxes,
            watermark_boxes=watermark_boxes,
            crop_region=crop_region,
        )
        self._before_image.setPixmap(orig_pixmap)
        self._before_image.setText("")

        # Info-Label
        parts = [f"Original ({original.shape[1]}x{original.shape[0]})"]
        if boxes:
            parts.append(f"{len(boxes)} Person(en)")
        if watermark_boxes:
            parts.append(f"{len(watermark_boxes)} WM")
        self._before_label.setText(" | ".join(parts))

        # Cropped
        if cropped is not None:
            crop_pixmap = numpy_to_qpixmap(cropped, max_size=max_w)
            self._after_image.setPixmap(crop_pixmap)
            self._after_image.setText("")
            self._after_label.setText(
                f"Zugeschnitten ({cropped.shape[1]}x{cropped.shape[0]})"
            )
        else:
            self._after_image.setText("Keine Person erkannt")
            self._after_image.setPixmap(QPixmap())
            self._after_label.setText("Zugeschnitten")

    def clear(self) -> None:
        self._show_placeholder()
        self._info.setText("")
        self._original_image = None
        self._total_images = 0
        self._current_index = 0
        self._nav_label.setText("Kein Bild")
        self._update_nav_buttons()
