"""WatermarkTemplateDialog: Rectangle-Selector fuer Watermark-Referenzbild.

Dialog zur manuellen Markierung eines Watermarks im ersten Bild.
Der markierte Bereich wird als Template fuer Template-Matching gespeichert.
"""

import cv2
import numpy as np
from PyQt6.QtCore import Qt, QPoint, QRect
from PyQt6.QtGui import (
    QColor,
    QFont,
    QImage,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.core.detector import BoundingBox


# --- Farben / Colors ---
SELECTION_COLOR = QColor(231, 76, 60, 200)  # Rot / Red
SELECTION_FILL = QColor(231, 76, 60, 40)    # Halbtransparent / Semi-transparent


def _numpy_to_qpixmap(image: np.ndarray, max_size: int = 800) -> QPixmap:
    """BGR NumPy -> QPixmap (skaliert). / BGR NumPy -> QPixmap (scaled)."""
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


class RectangleSelectorWidget(QWidget):
    """Widget zum Zeichnen eines Auswahlrechtecks auf einem Bild.

    Widget for drawing a selection rectangle on an image.
    User clicks and drags to select a region.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._original_shape: tuple[int, int] = (0, 0)  # (h, w)
        self._drawing = False
        self._start_point = QPoint()
        self._end_point = QPoint()
        self._selection: QRect | None = None
        self.setMinimumSize(400, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_image(self, image: np.ndarray, max_size: int = 800) -> None:
        """Setzt das Hintergrundbild. / Sets the background image."""
        self._original_shape = (image.shape[0], image.shape[1])
        self._pixmap = _numpy_to_qpixmap(image, max_size=max_size)
        self.setMinimumSize(self._pixmap.width(), self._pixmap.height())
        self.setMaximumSize(self._pixmap.width(), self._pixmap.height())
        self._selection = None
        self.update()

    def get_selection_box(self) -> BoundingBox | None:
        """Gibt die Auswahl als BoundingBox in Originalkoordinaten zurueck.

        Returns the selection rectangle mapped back to original image coordinates.
        """
        if self._selection is None or self._pixmap is None:
            return None

        rect = self._selection.normalized()
        if rect.width() < 5 or rect.height() < 5:
            return None

        orig_h, orig_w = self._original_shape
        sx = orig_w / self._pixmap.width()
        sy = orig_h / self._pixmap.height()

        x1 = max(0, int(rect.x() * sx))
        y1 = max(0, int(rect.y() * sy))
        x2 = min(orig_w, int((rect.x() + rect.width()) * sx))
        y2 = min(orig_h, int((rect.y() + rect.height()) * sy))

        return BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2, confidence=1.0)

    def paintEvent(self, event) -> None:
        if self._pixmap is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawPixmap(0, 0, self._pixmap)

        # Aktive Auswahl zeichnen / Draw active selection
        rect = None
        if self._drawing:
            rect = QRect(self._start_point, self._end_point).normalized()
        elif self._selection is not None:
            rect = self._selection.normalized()

        if rect and rect.width() > 2 and rect.height() > 2:
            pen = QPen(SELECTION_COLOR)
            pen.setWidth(2)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(SELECTION_FILL)
            painter.drawRect(rect)

            # Groessenanzeige / Size indicator
            font = QFont("Lexend", 9)
            painter.setFont(font)
            painter.setPen(QColor(255, 255, 255, 220))
            label = f"{rect.width()} x {rect.height()}"
            painter.drawText(rect.x() + 4, rect.y() - 6, label)

        painter.end()

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return
        if event.button() == Qt.MouseButton.LeftButton and self._pixmap:
            self._drawing = True
            self._start_point = event.pos()
            self._end_point = event.pos()
            self._selection = None
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return
        if self._drawing and self._pixmap:
            # Clamp innerhalb des Bildes / Clamp within image bounds
            x = max(0, min(event.pos().x(), self._pixmap.width() - 1))
            y = max(0, min(event.pos().y(), self._pixmap.height() - 1))
            self._end_point = QPoint(x, y)
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return
        if event.button() == Qt.MouseButton.LeftButton and self._drawing:
            self._drawing = False
            rect = QRect(self._start_point, self._end_point).normalized()
            if rect.width() > 5 and rect.height() > 5:
                self._selection = rect
            self.update()


class WatermarkTemplateDialog(QDialog):
    """Dialog zur manuellen Watermark-Markierung.

    Shows the first image and lets the user draw a rectangle around
    the watermark. Returns the selected region as BoundingBox.
    Used when YOLO fails to detect a watermark in the first batch image.
    """

    def __init__(self, image: np.ndarray, filename: str = "", parent=None):
        super().__init__(parent)
        self._image = image
        self._filename = filename
        self._accepted_box: BoundingBox | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle("Watermark markieren")
        self.setMinimumSize(600, 500)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Hinweistext / Instruction text
        hint = QLabel(
            "Kein Wasserzeichen automatisch erkannt.\n"
            "Ziehen Sie ein Rechteck um das Wasserzeichen, "
            "um es als Vorlage fuer die restlichen Bilder zu verwenden."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #e0e0e0; font-size: 13px; padding: 8px;")
        layout.addWidget(hint)

        if self._filename:
            file_label = QLabel(f"Datei: {self._filename}")
            file_label.setStyleSheet("color: #a0a0a0; font-size: 11px;")
            layout.addWidget(file_label)

        # Bild-Widget mit Auswahl / Image widget with selection
        self._selector = RectangleSelectorWidget()
        self._selector.set_image(self._image)
        layout.addWidget(self._selector, stretch=1)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        self._skip_btn = QPushButton("Ueberspringen")
        self._skip_btn.setToolTip("Kein Template verwenden, nur YOLO-Erkennung")
        self._skip_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self._skip_btn)

        btn_layout.addStretch()

        self._reset_btn = QPushButton("Zuruecksetzen")
        self._reset_btn.clicked.connect(self._on_reset)
        btn_layout.addWidget(self._reset_btn)

        self._apply_btn = QPushButton("Uebernehmen")
        self._apply_btn.setDefault(True)
        self._apply_btn.clicked.connect(self._on_apply)
        btn_layout.addWidget(self._apply_btn)

        layout.addLayout(btn_layout)

    def _on_reset(self) -> None:
        """Setzt die Auswahl zurueck. / Resets the selection."""
        self._selector._selection = None
        self._selector.update()

    def _on_apply(self) -> None:
        """Uebernimmt die Auswahl. / Applies the selection."""
        box = self._selector.get_selection_box()
        if box is None:
            return  # Keine gueltige Auswahl / No valid selection
        self._accepted_box = box
        self.accept()

    def get_selected_box(self) -> BoundingBox | None:
        """Gibt die gewaehlte BoundingBox zurueck (None bei Skip/Abbruch).

        Returns the selected bounding box, or None if the user skipped.
        """
        return self._accepted_box
