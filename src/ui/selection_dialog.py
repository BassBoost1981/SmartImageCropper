"""Auswahl-Dialog bei Mehrfach-Erkennung (Personen / Watermarks).

Selection dialog for multi-detection: lets the user pick which persons
and watermarks to keep, with interactive clickable bounding boxes and
a synchronized checkbox list.
"""

from dataclasses import dataclass, field

import cv2
import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.core.detector import BoundingBox


@dataclass
class SelectionResult:
    """Ergebnis der Benutzer-Auswahl im Dialog.

    Result of user selection in the detection dialog.
    """

    selected_persons: list[BoundingBox] = field(default_factory=list)
    selected_watermarks: list[BoundingBox] = field(default_factory=list)
    # None = weiter fragen, "all"/"largest"/"highest_conf" = Regel anwenden
    # None = keep asking, otherwise apply rule for remaining images
    apply_rule: str | None = None
    skip_image: bool = False


# --- Farben / Colors ---
PERSON_COLOR = QColor(168, 85, 247, 200)     # lila / purple
PERSON_COLOR_DIM = QColor(168, 85, 247, 60)  # halbtransparent / dimmed
WM_COLOR = QColor(231, 76, 60, 220)          # rot / red
WM_COLOR_DIM = QColor(231, 76, 60, 60)       # halbtransparent / dimmed
SELECTED_BG = QColor(168, 85, 247, 30)       # Checkbox-Hintergrund / bg


def _numpy_to_qpixmap(image: np.ndarray, max_size: int = 700) -> QPixmap:
    """BGR NumPy → QPixmap (skaliert). / BGR NumPy → QPixmap (scaled)."""
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


class InteractiveDetectionWidget(QWidget):
    """Zeigt ein Bild mit klickbaren Bounding-Boxen.

    Displays an image with clickable, numbered bounding boxes.
    Clicking a box toggles its selected state.
    """

    # (box_index, is_person, new_state)
    box_toggled = pyqtSignal(int, bool, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._image_shape: tuple[int, ...] = (0, 0, 3)
        self._person_boxes: list[BoundingBox] = []
        self._wm_boxes: list[BoundingBox] = []
        self._person_selected: list[bool] = []
        self._wm_selected: list[bool] = []
        self.setMinimumSize(400, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_data(
        self,
        image: np.ndarray,
        person_boxes: list[BoundingBox],
        wm_boxes: list[BoundingBox],
    ) -> None:
        self._image_shape = image.shape
        self._person_boxes = person_boxes
        self._wm_boxes = wm_boxes
        self._person_selected = [True] * len(person_boxes)
        self._wm_selected = [True] * len(wm_boxes)

        max_size = min(700, self.width() - 20) if self.width() > 220 else 700
        self._pixmap = _numpy_to_qpixmap(image, max_size=max_size)
        self.setMinimumSize(self._pixmap.width(), self._pixmap.height())
        self.update()

    def set_person_selected(self, index: int, selected: bool) -> None:
        if 0 <= index < len(self._person_selected):
            self._person_selected[index] = selected
            self.update()

    def set_wm_selected(self, index: int, selected: bool) -> None:
        if 0 <= index < len(self._wm_selected):
            self._wm_selected[index] = selected
            self.update()

    def paintEvent(self, event) -> None:
        if self._pixmap is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawPixmap(0, 0, self._pixmap)

        orig_h, orig_w = self._image_shape[:2]
        sx = self._pixmap.width() / orig_w
        sy = self._pixmap.height() / orig_h
        font = QFont("Lexend", 11, QFont.Weight.Bold)
        painter.setFont(font)

        # Personen zeichnen / Draw person boxes
        for i, box in enumerate(self._person_boxes):
            selected = self._person_selected[i]
            color = PERSON_COLOR if selected else PERSON_COLOR_DIM
            pen = QPen(color)
            pen.setWidth(3 if selected else 1)
            painter.setPen(pen)
            x1, y1 = int(box.x1 * sx), int(box.y1 * sy)
            x2, y2 = int(box.x2 * sx), int(box.y2 * sy)
            painter.drawRect(x1, y1, x2 - x1, y2 - y1)

            # Nummer + Konfidenz / Number + confidence
            label = f"P{i + 1} {box.confidence:.0%}"
            painter.setPen(QColor(255, 255, 255, 230 if selected else 80))
            bg_rect = painter.fontMetrics().boundingRect(label)
            bg_rect.moveTopLeft(painter.fontMetrics().boundingRect(label).topLeft())
            bg_x = x1 + 4
            bg_y = y1 - 4 - bg_rect.height()
            if bg_y < 0:
                bg_y = y1 + 4
            painter.fillRect(
                bg_x - 2, bg_y, bg_rect.width() + 8, bg_rect.height() + 4,
                QColor(0, 0, 0, 160 if selected else 60),
            )
            painter.drawText(bg_x + 2, bg_y + bg_rect.height(), label)

        # Watermarks zeichnen / Draw watermark boxes
        for i, box in enumerate(self._wm_boxes):
            selected = self._wm_selected[i]
            color = WM_COLOR if selected else WM_COLOR_DIM
            pen = QPen(color)
            pen.setWidth(3 if selected else 1)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            x1, y1 = int(box.x1 * sx), int(box.y1 * sy)
            x2, y2 = int(box.x2 * sx), int(box.y2 * sy)
            painter.drawRect(x1, y1, x2 - x1, y2 - y1)

            label = f"W{i + 1} {box.confidence:.0%}"
            painter.setPen(QColor(255, 255, 255, 230 if selected else 80))
            bg_y = y1 - 4 - painter.fontMetrics().height()
            if bg_y < 0:
                bg_y = y1 + 4
            fm_rect = painter.fontMetrics().boundingRect(label)
            painter.fillRect(
                x1 + 2, bg_y, fm_rect.width() + 8, fm_rect.height() + 4,
                QColor(0, 0, 0, 160 if selected else 60),
            )
            painter.drawText(x1 + 6, bg_y + fm_rect.height(), label)

        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._pixmap is None or event.button() != Qt.MouseButton.LeftButton:
            return

        pos = event.position()
        mx, my = pos.x(), pos.y()

        orig_h, orig_w = self._image_shape[:2]
        sx = self._pixmap.width() / orig_w
        sy = self._pixmap.height() / orig_h

        # Prüfe Personen-Boxen (umgekehrt: obere zuerst)
        # Check person boxes (reverse: front-most first)
        for i in range(len(self._person_boxes) - 1, -1, -1):
            box = self._person_boxes[i]
            x1, y1 = int(box.x1 * sx), int(box.y1 * sy)
            x2, y2 = int(box.x2 * sx), int(box.y2 * sy)
            if x1 <= mx <= x2 and y1 <= my <= y2:
                self._person_selected[i] = not self._person_selected[i]
                self.box_toggled.emit(i, True, self._person_selected[i])
                self.update()
                return

        # Prüfe Watermark-Boxen / Check watermark boxes
        for i in range(len(self._wm_boxes) - 1, -1, -1):
            box = self._wm_boxes[i]
            x1, y1 = int(box.x1 * sx), int(box.y1 * sy)
            x2, y2 = int(box.x2 * sx), int(box.y2 * sy)
            if x1 <= mx <= x2 and y1 <= my <= y2:
                self._wm_selected[i] = not self._wm_selected[i]
                self.box_toggled.emit(i, False, self._wm_selected[i])
                self.update()
                return


class DetectionSelectionDialog(QDialog):
    """Dialog zur Auswahl relevanter Erkennungen bei Mehrfach-Detection.

    Dialog for selecting relevant detections when multiple persons
    or watermarks are found. Shows interactive image + checkbox list.
    """

    def __init__(
        self,
        image: np.ndarray,
        person_boxes: list[BoundingBox],
        wm_boxes: list[BoundingBox],
        filename: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._person_boxes = person_boxes
        self._wm_boxes = wm_boxes
        self._result = SelectionResult()
        self._person_checks: list[QCheckBox] = []
        self._wm_checks: list[QCheckBox] = []

        self.setWindowTitle(f"Erkennung auswählen — {filename}" if filename else "Erkennung auswählen")
        self.setMinimumSize(900, 600)
        self.setStyleSheet(self._dialog_style())

        self._setup_ui(image, person_boxes, wm_boxes, filename)

    def _dialog_style(self) -> str:
        return """
        QDialog {
            background-color: #0f0f1e;
        }
        QLabel {
            color: #c0c0e0;
            font-family: 'Lexend', 'Segoe UI', sans-serif;
            font-size: 13px;
        }
        QLabel#dialog-title {
            font-size: 16px;
            font-weight: 700;
            color: #ffffff;
        }
        QLabel#dialog-subtitle {
            font-size: 12px;
            color: #8888aa;
        }
        QCheckBox {
            color: #e0e0e0;
            font-family: 'Lexend', 'Segoe UI', sans-serif;
            font-size: 13px;
            spacing: 8px;
            padding: 6px 8px;
            border-radius: 6px;
        }
        QCheckBox:hover {
            background: rgba(168, 85, 247, 0.1);
        }
        QCheckBox::indicator {
            width: 20px; height: 20px;
            border-radius: 4px;
            border: 2px solid rgba(255, 255, 255, 0.2);
            background: rgba(20, 20, 40, 0.8);
        }
        QCheckBox::indicator:checked {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 #6c5ce7, stop:1 #a855f7);
            border: 2px solid #6c5ce7;
        }
        QPushButton {
            font-family: 'Lexend', 'Segoe UI', sans-serif;
            font-size: 13px;
            font-weight: 600;
            border: none;
            border-radius: 8px;
            padding: 10px 20px;
            color: white;
            min-height: 20px;
        }
        QPushButton#primary {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 #6c5ce7, stop:1 #a855f7);
        }
        QPushButton#primary:hover {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 #7c6cf7, stop:1 #b865ff);
        }
        QPushButton#secondary {
            background: rgba(60, 60, 90, 0.6);
            border: 1px solid rgba(255, 255, 255, 0.1);
        }
        QPushButton#secondary:hover {
            background: rgba(80, 80, 110, 0.7);
        }
        QPushButton#skip {
            background: rgba(231, 76, 60, 0.3);
            border: 1px solid rgba(231, 76, 60, 0.4);
        }
        QPushButton#skip:hover {
            background: rgba(231, 76, 60, 0.5);
        }
        QGroupBox {
            background-color: rgba(30, 30, 55, 0.6);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 12px;
            padding: 16px;
            padding-top: 28px;
            margin-top: 8px;
            font-family: 'Lexend', 'Segoe UI', sans-serif;
            font-size: 13px;
            font-weight: 600;
            color: #b0b0d0;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 4px 12px;
        }
        QComboBox {
            background: rgba(20, 20, 40, 0.8);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 8px;
            padding: 8px 12px;
            color: #e0e0e0;
            font-size: 13px;
            min-width: 100px;
        }
        QComboBox QAbstractItemView {
            background: #1a1a2e;
            border: 1px solid rgba(255, 255, 255, 0.1);
            selection-background-color: #6c5ce7;
            color: #e0e0e0;
        }
        QScrollArea { border: none; background: transparent; }
        """

    def _setup_ui(
        self,
        image: np.ndarray,
        person_boxes: list[BoundingBox],
        wm_boxes: list[BoundingBox],
        filename: str,
    ) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # Header
        title = QLabel("Mehrere Erkennungen gefunden")
        title.setObjectName("dialog-title")
        main_layout.addWidget(title)

        subtitle_text = f"{filename} — " if filename else ""
        subtitle_text += f"{len(person_boxes)} Person(en), {len(wm_boxes)} Watermark(s)"
        subtitle = QLabel(subtitle_text)
        subtitle.setObjectName("dialog-subtitle")
        main_layout.addWidget(subtitle)

        hint = QLabel("Klicke auf die Boxen im Bild oder nutze die Checkboxen um Erkennungen an/abzuwählen.")
        hint.setWordWrap(True)
        main_layout.addWidget(hint)

        # Content: Bild links, Liste rechts / Image left, list right
        content = QHBoxLayout()
        content.setSpacing(16)

        # Interaktives Bild / Interactive image
        self._detection_widget = InteractiveDetectionWidget()
        self._detection_widget.set_data(image, person_boxes, wm_boxes)
        self._detection_widget.box_toggled.connect(self._on_box_toggled_from_image)

        img_scroll = QScrollArea()
        img_scroll.setWidget(self._detection_widget)
        img_scroll.setWidgetResizable(False)
        img_scroll.setMinimumWidth(450)
        content.addWidget(img_scroll, 3)

        # Checkbox-Liste / Checkbox list
        list_widget = QWidget()
        list_layout = QVBoxLayout(list_widget)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(8)

        # Personen-Gruppe / Person group
        if person_boxes:
            person_group = QGroupBox(f"Personen ({len(person_boxes)})")
            pg_layout = QVBoxLayout(person_group)
            for i, box in enumerate(person_boxes):
                cb = QCheckBox(f"Person {i + 1}  —  {box.confidence:.0%}  ({box.width}x{box.height}px)")
                cb.setChecked(True)
                cb.stateChanged.connect(lambda state, idx=i: self._on_person_check_changed(idx, state))
                self._person_checks.append(cb)
                pg_layout.addWidget(cb)
            list_layout.addWidget(person_group)

        # Watermark-Gruppe / Watermark group
        if wm_boxes:
            wm_group = QGroupBox(f"Wasserzeichen ({len(wm_boxes)})")
            wg_layout = QVBoxLayout(wm_group)
            for i, box in enumerate(wm_boxes):
                cb = QCheckBox(f"Watermark {i + 1}  —  {box.confidence:.0%}  ({box.width}x{box.height}px)")
                cb.setChecked(True)
                cb.stateChanged.connect(lambda state, idx=i: self._on_wm_check_changed(idx, state))
                self._wm_checks.append(cb)
                wg_layout.addWidget(cb)
            list_layout.addWidget(wm_group)

        # Regel-Option / Rule option
        rule_group = QGroupBox("Regel für weitere Bilder")
        rule_layout = QVBoxLayout(rule_group)
        self._rule_check = QCheckBox("Regel für alle weiteren Bilder anwenden")
        self._rule_check.setChecked(False)
        rule_layout.addWidget(self._rule_check)

        self._rule_combo = QComboBox()
        self._rule_combo.addItems([
            "Immer alle behalten",
            "Nur größte Person",
            "Nur Person mit höchster Konfidenz",
        ])
        self._rule_combo.setEnabled(False)
        self._rule_check.toggled.connect(self._rule_combo.setEnabled)
        rule_layout.addWidget(self._rule_combo)
        list_layout.addWidget(rule_group)

        list_layout.addStretch()

        list_scroll = QScrollArea()
        list_scroll.setWidget(list_widget)
        list_scroll.setWidgetResizable(True)
        list_scroll.setMinimumWidth(280)
        content.addWidget(list_scroll, 2)

        main_layout.addLayout(content, 1)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        skip_btn = QPushButton("Bild überspringen")
        skip_btn.setObjectName("skip")
        skip_btn.clicked.connect(self._on_skip)
        btn_layout.addWidget(skip_btn)

        btn_layout.addStretch()

        all_btn = QPushButton("Alle behalten")
        all_btn.setObjectName("secondary")
        all_btn.clicked.connect(self._on_keep_all)
        btn_layout.addWidget(all_btn)

        apply_btn = QPushButton("Auswahl übernehmen")
        apply_btn.setObjectName("primary")
        apply_btn.clicked.connect(self._on_apply)
        btn_layout.addWidget(apply_btn)

        main_layout.addLayout(btn_layout)

    # --- Signal-Handler ---

    def _on_box_toggled_from_image(self, index: int, is_person: bool, state: bool) -> None:
        """Box im Bild geklickt → Checkbox synchronisieren.

        Box clicked in image → sync checkbox.
        """
        if is_person and index < len(self._person_checks):
            self._person_checks[index].setChecked(state)
        elif not is_person and index < len(self._wm_checks):
            self._wm_checks[index].setChecked(state)

    def _on_person_check_changed(self, index: int, state: int) -> None:
        """Checkbox geändert → Bild synchronisieren.

        Checkbox changed → sync image overlay.
        """
        checked = state == Qt.CheckState.Checked.value
        self._detection_widget.set_person_selected(index, checked)

    def _on_wm_check_changed(self, index: int, state: int) -> None:
        checked = state == Qt.CheckState.Checked.value
        self._detection_widget.set_wm_selected(index, checked)

    def _get_rule(self) -> str | None:
        """Gibt die gewählte Regel zurück (oder None).

        Returns the selected rule, or None if no rule was chosen.
        """
        if not self._rule_check.isChecked():
            return None
        rule_map = {0: "all", 1: "largest", 2: "highest_conf"}
        return rule_map.get(self._rule_combo.currentIndex())

    def _on_skip(self) -> None:
        self._result = SelectionResult(
            skip_image=True,
            apply_rule=self._get_rule(),
        )
        self.accept()

    def _on_keep_all(self) -> None:
        self._result = SelectionResult(
            selected_persons=list(self._person_boxes),
            selected_watermarks=list(self._wm_boxes),
            apply_rule=self._get_rule(),
        )
        self.accept()

    def _on_apply(self) -> None:
        sel_persons = [
            box for box, cb in zip(self._person_boxes, self._person_checks)
            if cb.isChecked()
        ]
        sel_wm = [
            box for box, cb in zip(self._wm_boxes, self._wm_checks)
            if cb.isChecked()
        ]
        self._result = SelectionResult(
            selected_persons=sel_persons,
            selected_watermarks=sel_wm,
            apply_rule=self._get_rule(),
        )
        self.accept()

    @property
    def result(self) -> SelectionResult:
        return self._result
