"""Smart Image Cropper — Entry Point."""

import os
import sys


def main():
    # Sicherstellen, dass das Projekt-Root im Pfad ist
    project_root = os.path.dirname(os.path.abspath(__file__))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QFontDatabase, QFont, QIcon
    from PyQt6.QtCore import Qt

    from src.ui.main_window import MainWindow
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
    if os.path.exists(font_path):
        font_id = QFontDatabase.addApplicationFont(font_path)
        if font_id >= 0:
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                app.setFont(QFont(families[0], 10))

    # App Icon
    icon_path = os.path.join(project_root, "logo no_bg-cropped.svg")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # Stylesheet anwenden
    app.setStyleSheet(GLASSMORPHISM_STYLE)

    # Config laden
    config_path = os.path.join(project_root, "config", "settings.json")
    config = ConfigManager(config_path)

    # Hauptfenster
    window = MainWindow(config)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
