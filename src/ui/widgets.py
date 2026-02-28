"""Wiederverwendbare UI-Komponenten für die Smart Image Cropper App."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QDoubleSpinBox,
    QVBoxLayout,
    QWidget,
)


class StyledButton(QPushButton):
    """Button mit vordefiniertem Styling."""

    def __init__(self, text: str, icon_text: str = "", variant: str = "primary", parent=None):
        super().__init__(parent)
        display = f"{icon_text}  {text}" if icon_text else text
        self.setText(display)
        if variant == "secondary":
            self.setObjectName("secondary")
        elif variant == "destructive":
            self.setObjectName("destructive")
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class StyledSlider(QWidget):
    """Slider mit Label und Wert-Anzeige."""

    valueChanged = pyqtSignal(int)

    def __init__(
        self,
        label: str,
        min_val: int = 0,
        max_val: int = 100,
        default: int = 50,
        suffix: str = "%",
        parent=None,
    ):
        super().__init__(parent)
        self._suffix = suffix

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Header mit Label und Wert
        header = QHBoxLayout()
        self._label = QLabel(label)
        self._value_label = QLabel(f"{default}{suffix}")
        self._value_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        header.addWidget(self._label)
        header.addWidget(self._value_label)
        layout.addLayout(header)

        # Slider
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setMinimum(min_val)
        self._slider.setMaximum(max_val)
        self._slider.setValue(default)
        self._slider.valueChanged.connect(self._on_change)
        layout.addWidget(self._slider)

    def _on_change(self, value: int) -> None:
        self._value_label.setText(f"{value}{self._suffix}")
        self.valueChanged.emit(value)

    def value(self) -> int:
        return self._slider.value()

    def setValue(self, val: int) -> None:
        self._slider.setValue(val)


class StyledSpinBox(QWidget):
    """SpinBox mit Label."""

    valueChanged = pyqtSignal(int)

    def __init__(
        self,
        label: str,
        min_val: int = 0,
        max_val: int = 100,
        default: int = 50,
        suffix: str = "",
        parent=None,
    ):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._label = QLabel(label)
        layout.addWidget(self._label)
        layout.addStretch()

        self._spinbox = QSpinBox()
        self._spinbox.setMinimum(min_val)
        self._spinbox.setMaximum(max_val)
        self._spinbox.setValue(default)
        if suffix:
            self._spinbox.setSuffix(f" {suffix}")
        self._spinbox.valueChanged.connect(self.valueChanged.emit)
        layout.addWidget(self._spinbox)

    def value(self) -> int:
        return self._spinbox.value()

    def setValue(self, val: int) -> None:
        self._spinbox.setValue(val)


class StyledDoubleSpinBox(QWidget):
    """DoubleSpinBox mit Label."""

    valueChanged = pyqtSignal(float)

    def __init__(
        self,
        label: str,
        min_val: float = 0.0,
        max_val: float = 1.0,
        default: float = 0.5,
        step: float = 0.05,
        decimals: int = 2,
        parent=None,
    ):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._label = QLabel(label)
        layout.addWidget(self._label)
        layout.addStretch()

        self._spinbox = QDoubleSpinBox()
        self._spinbox.setMinimum(min_val)
        self._spinbox.setMaximum(max_val)
        self._spinbox.setValue(default)
        self._spinbox.setSingleStep(step)
        self._spinbox.setDecimals(decimals)
        self._spinbox.valueChanged.connect(self.valueChanged.emit)
        layout.addWidget(self._spinbox)

    def value(self) -> float:
        return self._spinbox.value()

    def setValue(self, val: float) -> None:
        self._spinbox.setValue(val)


class ProgressCard(QFrame):
    """Karte mit Fortschrittsanzeige und Statistiken."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Fortschritts-Info
        self._status_label = QLabel("Bereit")
        self._status_label.setObjectName("subtitle")
        layout.addWidget(self._status_label)

        # Fortschrittsbalken (als einfacher Frame)
        self._progress_bar = QFrame()
        self._progress_bar.setFixedHeight(6)
        self._progress_bar.setStyleSheet(
            "background: rgba(60, 60, 90, 0.8); border-radius: 3px;"
        )
        self._progress_fill = QFrame(self._progress_bar)
        self._progress_fill.setFixedHeight(6)
        self._progress_fill.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            "stop:0 #6c5ce7, stop:1 #a855f7); border-radius: 3px;"
        )
        self._progress_fill.setFixedWidth(0)
        layout.addWidget(self._progress_bar)

        # Stats-Zeile
        stats_row = QHBoxLayout()
        self._stats_labels = {}
        for key, label in [
            ("processed", "Verarbeitet"),
            ("skipped", "Übersprungen"),
            ("errors", "Fehler"),
            ("watermarks", "Watermarks"),
            ("speed", "Geschw."),
        ]:
            stat_widget = QVBoxLayout()
            val = QLabel("0")
            val.setObjectName("stat-value")
            val.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl = QLabel(label)
            lbl.setObjectName("stat-label")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            stat_widget.addWidget(val)
            stat_widget.addWidget(lbl)
            stats_row.addLayout(stat_widget)
            self._stats_labels[key] = val

        layout.addLayout(stats_row)

    def set_progress(self, current: int, total: int, filename: str = "") -> None:
        if total > 0:
            pct = int(current / total * 100)
            bar_width = int(self._progress_bar.width() * current / total)
            self._progress_fill.setFixedWidth(max(0, bar_width))
            self._status_label.setText(
                f"{current}/{total} ({pct}%) — {filename}"
            )

    def set_stats(self, stats: dict) -> None:
        if "processed" in stats:
            self._stats_labels["processed"].setText(str(stats["processed"]))
        if "skipped" in stats:
            self._stats_labels["skipped"].setText(str(stats["skipped"]))
        if "errors" in stats:
            self._stats_labels["errors"].setText(str(stats["errors"]))
        if "watermarks" in stats or "watermarks_found" in stats:
            val = stats.get("watermarks", stats.get("watermarks_found", 0))
            self._stats_labels["watermarks"].setText(str(val))
        if "speed" in stats:
            self._stats_labels["speed"].setText(f"{stats['speed']:.1f}/s")

    def reset(self) -> None:
        self._status_label.setText("Bereit")
        self._progress_fill.setFixedWidth(0)
        for lbl in self._stats_labels.values():
            lbl.setText("0")


class StatCard(QFrame):
    """Einzelne Statistik-Karte."""

    def __init__(self, label: str, value: str = "0", parent=None):
        super().__init__(parent)
        self.setObjectName("card")

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._value = QLabel(value)
        self._value.setObjectName("stat-value")
        self._value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._value)

        self._label = QLabel(label)
        self._label.setObjectName("stat-label")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._label)

    def set_value(self, value: str) -> None:
        self._value.setText(value)
