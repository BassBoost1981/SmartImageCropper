"""Smart Image Cropper — Entry Point."""

import os
import sys

# CUDA Lazy Loading: Verhindert, dass der gesamte CUDA-Treiber beim ersten
# torch-Import geladen wird. Reduziert die Startup-Freeze-Zeit erheblich.
# Prevents CUDA driver from loading all modules at first torch import.
os.environ["CUDA_MODULE_LOADING"] = "LAZY"


def main():
    # Sicherstellen, dass das Projekt-Root im Pfad ist
    project_root = os.path.dirname(os.path.abspath(__file__))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    import threading

    from PyQt6.QtWidgets import QApplication, QSplashScreen
    from PyQt6.QtGui import QColor, QFontDatabase, QFont, QIcon, QPainter, QPixmap
    from PyQt6.QtCore import Qt

    from src.ui.styles import GLASSMORPHISM_STYLE
    from src.utils.config import ConfigManager
    from src.utils.logger import setup_logging

    # Logging initialisieren
    setup_logging()

    # High-DPI Scaling
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

    app = QApplication(sys.argv)
    app.setApplicationName("Smart Image Cropper")
    app.setOrganizationName("SmartImageCropper")

    # Lexend Font laden
    font_path = os.path.join(project_root, "Font", "Lexend-VariableFont_wght.ttf")
    font_family = None
    if os.path.exists(font_path):
        font_id = QFontDatabase.addApplicationFont(font_path)
        if font_id >= 0:
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                font_family = families[0]
                app.setFont(QFont(font_family, 10))

    # App Icon
    icon_path = os.path.join(project_root, "logo no_bg-cropped.svg")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # Stylesheet anwenden
    app.setStyleSheet(GLASSMORPHISM_STYLE)

    # ===================================================================
    # Splash-Screen mit Logo erstellen
    # Create splash screen with logo, shown before heavy imports
    # ===================================================================
    splash_w, splash_h = 480, 260
    splash_pix = QPixmap(splash_w, splash_h)
    splash_pix.fill(QColor(30, 30, 40))

    painter = QPainter(splash_pix)

    # Logo zentriert oben / Logo centered at top
    if os.path.exists(icon_path):
        logo_icon = QIcon(icon_path)
        logo_pix = logo_icon.pixmap(72, 72)
        painter.drawPixmap((splash_w - 72) // 2, 20, logo_pix)

    # Titel / Title
    painter.setPen(QColor(168, 85, 247))  # Lila (#a855f7)
    title_font = QFont(font_family or "Segoe UI", 20)
    title_font.setBold(True)
    painter.setFont(title_font)
    painter.drawText(0, 100, splash_w, 40, Qt.AlignmentFlag.AlignCenter, "Smart Image Cropper")

    # Untertitel / Subtitle
    painter.setPen(QColor(140, 140, 160))
    sub_font = QFont(font_family or "Segoe UI", 10)
    painter.setFont(sub_font)
    painter.drawText(
        0, 138, splash_w, 25,
        Qt.AlignmentFlag.AlignCenter,
        "KI-basierte Bildverarbeitung",
    )

    painter.end()

    splash = QSplashScreen(splash_pix)
    splash.show()
    app.processEvents()

    # ===================================================================
    # Config laden (leichtgewichtig)
    # Load config (lightweight, no heavy imports)
    # ===================================================================
    config_path = os.path.join(project_root, "config", "settings.json")
    config = ConfigManager(config_path)

    # ===================================================================
    # Modelle im Hintergrund-Thread laden, Splash-Text wird aktualisiert
    # Load models in background thread, splash text updates with progress
    # ===================================================================
    _state = {
        "text": "KI-Bibliotheken werden geladen...",
        "person_detector": None,
        "wm_detector": None,
        "error": None,
    }
    load_done = threading.Event()

    def _load_models():
        try:
            # Phase 1: torch / CUDA importieren
            _state["text"] = "KI-Bibliotheken werden geladen..."
            import torch  # noqa: F401

            torch.cuda.is_available()

            from src.core.detector import PersonDetector
            from src.core.watermark import WatermarkDetector

            # Phase 2: Personenerkennung laden
            _state["text"] = "Lade Personenerkennung..."
            pd = PersonDetector(
                model_path="models/yolov8n.pt",
                confidence=config.get("confidence_threshold", 0.5),
                use_gpu=config.get("use_gpu", True),
            )
            if pd.load_model():
                _state["person_detector"] = pd

            # Phase 3: Wasserzeichen-Erkennung laden
            _state["text"] = "Lade Wasserzeichen-Erkennung..."
            wm_type_idx = config.get("watermark_type_index", 0)
            wm_type = ["logo", "text"][wm_type_idx] if isinstance(wm_type_idx, int) else config.get("watermark_type", "logo")
            wd = WatermarkDetector(
                model_path="models/best.pt",
                confidence=config.get("watermark_confidence", 0.30),
                use_gpu=config.get("use_gpu", True),
                strict_filter=config.get("watermark_strict_filter", True),
                enhanced_detection=config.get("watermark_enhanced_detection", False),
                watermark_type=wm_type,
            )
            if wd.load_model():
                _state["wm_detector"] = wd

            _state["text"] = "Modelle bereit"
        except Exception as e:
            _state["error"] = str(e)
            _state["text"] = f"Fehler: {e}"
        load_done.set()

    t = threading.Thread(target=_load_models, daemon=True)
    t.start()

    # Event-Loop pumpen, Splash-Text aktualisieren
    # Pump event loop and update splash text with loading progress
    msg_align = Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter
    msg_color = QColor(180, 180, 200)
    _last_text = ""
    while not load_done.is_set():
        if _state["text"] != _last_text:
            _last_text = _state["text"]
            splash.showMessage(_last_text, msg_align, msg_color)
        app.processEvents()
        load_done.wait(0.05)

    # Letzten Status kurz anzeigen / Show final status briefly
    splash.showMessage(_state["text"], msg_align, msg_color)
    app.processEvents()

    # ===================================================================
    # Hauptfenster erstellen (Modelle sind bereits geladen)
    # Create main window (models are already loaded)
    # ===================================================================
    splash.showMessage("Oberfläche wird geladen...", msg_align, msg_color)
    app.processEvents()

    from src.ui.main_window import MainWindow

    window = MainWindow(
        config,
        preloaded_detectors=(
            _state["person_detector"],
            _state["wm_detector"],
        ),
    )
    splash.finish(window)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
