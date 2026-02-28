"""Glassmorphism QSS: Dark Theme mit Lexend Font."""

GLASSMORPHISM_STYLE = """
/* === Global === */
* {
    font-family: 'Lexend', 'Segoe UI', sans-serif;
    color: #e0e0e0;
}

QMainWindow {
    background-color: #0f0f1e;
}

/* === Sidebar === */
#sidebar {
    background-color: rgba(26, 26, 46, 0.85);
    border-right: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 0px;
}

/* === Panels / Cards === */
QFrame#card, QGroupBox {
    background-color: rgba(30, 30, 55, 0.6);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
    padding: 16px;
}

QGroupBox {
    font-size: 13px;
    font-weight: 600;
    padding-top: 24px;
    margin-top: 8px;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 4px 12px;
    color: #b0b0d0;
}

/* === Buttons === */
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #6c5ce7, stop:1 #a855f7);
    color: white;
    border: none;
    border-radius: 8px;
    padding: 10px 20px;
    font-size: 13px;
    font-weight: 600;
    min-height: 20px;
}

QPushButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #7c6cf7, stop:1 #b865ff);
}

QPushButton:pressed {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #5c4cd7, stop:1 #9845e7);
}

QPushButton:disabled {
    background: rgba(100, 100, 130, 0.4);
    color: rgba(200, 200, 220, 0.4);
}

QPushButton#destructive {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #e74c3c, stop:1 #c0392b);
}

QPushButton#destructive:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #ff5c4c, stop:1 #d0493b);
}

QPushButton#secondary {
    background: rgba(60, 60, 90, 0.6);
    border: 1px solid rgba(255, 255, 255, 0.1);
}

QPushButton#secondary:hover {
    background: rgba(80, 80, 110, 0.7);
}

/* === Labels === */
QLabel {
    color: #c0c0e0;
    font-size: 13px;
}

QLabel#title {
    font-size: 22px;
    font-weight: 700;
    color: #ffffff;
}

QLabel#subtitle {
    font-size: 14px;
    color: #8888aa;
}

QLabel#stat-value {
    font-size: 20px;
    font-weight: 700;
    color: #a855f7;
}

QLabel#stat-label {
    font-size: 11px;
    color: #8888aa;
}

/* === Input === */
QLineEdit {
    background: rgba(20, 20, 40, 0.8);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 8px;
    padding: 8px 12px;
    color: #e0e0e0;
    font-size: 13px;
    selection-background-color: #6c5ce7;
}

QLineEdit:focus {
    border: 1px solid rgba(108, 92, 231, 0.6);
}

/* === Slider === */
QSlider::groove:horizontal {
    border: none;
    height: 6px;
    background: rgba(60, 60, 90, 0.8);
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #6c5ce7, stop:1 #a855f7);
    width: 18px;
    height: 18px;
    margin: -6px 0;
    border-radius: 9px;
}

QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #6c5ce7, stop:1 #a855f7);
    border-radius: 3px;
}

/* === SpinBox === */
QSpinBox, QDoubleSpinBox {
    background: rgba(20, 20, 40, 0.8);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 8px;
    padding: 6px 10px;
    color: #e0e0e0;
    font-size: 13px;
}

QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {
    background: rgba(60, 60, 90, 0.6);
    border: none;
    width: 20px;
}

/* === ComboBox === */
QComboBox {
    background: rgba(20, 20, 40, 0.8);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 8px;
    padding: 8px 12px;
    color: #e0e0e0;
    font-size: 13px;
    min-width: 100px;
}

QComboBox::drop-down {
    border: none;
    width: 24px;
}

QComboBox QAbstractItemView {
    background: #1a1a2e;
    border: 1px solid rgba(255, 255, 255, 0.1);
    selection-background-color: #6c5ce7;
    color: #e0e0e0;
}

/* === Progress Bar === */
QProgressBar {
    background: rgba(30, 30, 55, 0.6);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 8px;
    text-align: center;
    color: #e0e0e0;
    font-size: 12px;
    font-weight: 600;
    min-height: 24px;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #6c5ce7, stop:1 #a855f7);
    border-radius: 7px;
}

/* === CheckBox === */
QCheckBox {
    spacing: 8px;
    font-size: 13px;
}

QCheckBox::indicator {
    width: 20px;
    height: 20px;
    border-radius: 4px;
    border: 2px solid rgba(255, 255, 255, 0.2);
    background: rgba(20, 20, 40, 0.8);
}

QCheckBox::indicator:checked {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #6c5ce7, stop:1 #a855f7);
    border: 2px solid #6c5ce7;
}

/* === ScrollBar === */
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background: rgba(100, 100, 140, 0.4);
    border-radius: 4px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background: rgba(120, 120, 160, 0.6);
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
    border: none;
    height: 0;
}

/* === Tooltip === */
QToolTip {
    background: #1a1a2e;
    color: #e0e0e0;
    border: 1px solid rgba(108, 92, 231, 0.4);
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}

/* === ScrollArea === */
QScrollArea {
    border: none;
    background: transparent;
}

QScrollArea > QWidget > QWidget {
    background: transparent;
}
"""
