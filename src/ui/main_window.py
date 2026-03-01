"""Hauptfenster der Smart Image Cropper App."""

import os
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QIcon, QKeySequence, QShortcut
from PyQt6.QtSvgWidgets import QSvgWidget
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.core.cropper import CropEngine
from src.core.detector import PersonDetector
from src.core.processor import ModelLoaderThread, PreviewLoadThread, ProcessingThread
from src.core.watermark import WatermarkDetector
from src.ui.preview_widget import PreviewWidget
from src.ui.selection_dialog import DetectionSelectionDialog, SelectionResult
from src.ui.template_dialog import WatermarkTemplateDialog
from src.ui.widgets import (
    ProgressCard,
    StyledButton,
    StyledDoubleSpinBox,
    StyledSlider,
    StyledSpinBox,
)
from src.utils.config import ConfigManager
from src.utils.file_manager import FileManager
from src.utils.logger import get_logger

logger = get_logger(__name__)


class MainWindow(QMainWindow):
    """Hauptfenster: Sidebar mit Settings + Content mit Preview."""

    def __init__(self, config: ConfigManager, parent=None):
        super().__init__(parent)
        self._config = config
        self._processing_thread: ProcessingThread | None = None
        self._preview_thread: PreviewLoadThread | None = None
        self._image_paths: list[str] = []
        self._preview_detector: PersonDetector | None = None
        self._preview_wm_detector: WatermarkDetector | None = None
        self._models_loaded = False
        self._model_loader: ModelLoaderThread | None = None

        self._setup_window()
        self._setup_ui()
        self._setup_shortcuts()
        self._load_settings()
        self._start_model_preload()

    def _setup_window(self) -> None:
        self.setWindowTitle("Smart Image Cropper")
        self.setMinimumSize(1000, 700)
        self.resize(
            self._config.get("window_width", 1200),
            self._config.get("window_height", 800),
        )

        # App Icon
        icon_path = self._find_resource("logo no_bg-cropped.svg")
        if icon_path:
            self.setWindowIcon(QIcon(icon_path))

    def _find_resource(self, filename: str) -> str | None:
        """Sucht eine Ressource-Datei relativ zum Projekt-Root."""
        for base in [os.path.dirname(os.path.abspath(__file__)), ".", ".."]:
            for root, dirs, files in os.walk(base):
                if filename in files:
                    return os.path.join(root, filename)
        # Direkt im Projektordner suchen
        candidates = [
            filename,
            os.path.join("..", "..", filename),
        ]
        for c in candidates:
            if os.path.exists(c):
                return os.path.abspath(c)
        return None

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # === Sidebar ===
        self._setup_sidebar(main_layout)

        # === Content Area ===
        self._setup_content(main_layout)

    def _setup_sidebar(self, parent_layout: QHBoxLayout) -> None:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(380)

        scroll = QScrollArea()
        scroll.setWidget(sidebar)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFixedWidth(400)
        parent_layout.addWidget(scroll)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # --- Header ---
        header = QHBoxLayout()
        logo_path = self._find_resource("logo no_bg-cropped.svg")
        if logo_path:
            logo = QSvgWidget(logo_path)
            logo.setFixedSize(40, 40)
            header.addWidget(logo)

        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        title = QLabel("Smart Image Cropper")
        title.setObjectName("title")
        subtitle = QLabel("KI-basierte Bildverarbeitung")
        subtitle.setObjectName("subtitle")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header.addLayout(title_col)
        header.addStretch()
        layout.addLayout(header)

        # --- Separator ---
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background: rgba(255,255,255,0.08); max-height: 1px;")
        layout.addWidget(sep)

        # --- Ordner-Auswahl ---
        folder_group = QGroupBox("Ordner")
        folder_layout = QVBoxLayout(folder_group)

        # Input
        input_row = QHBoxLayout()
        self._input_edit = QLineEdit()
        self._input_edit.setPlaceholderText("Quellordner wählen...")
        self._input_edit.setReadOnly(True)
        input_btn = StyledButton("...", variant="secondary")
        input_btn.setFixedWidth(40)
        input_btn.clicked.connect(self._select_input_dir)
        input_row.addWidget(self._input_edit, 1)
        input_row.addWidget(input_btn)
        folder_layout.addWidget(QLabel("Quellordner"))
        folder_layout.addLayout(input_row)

        # Output (automatisch: <Quellordner>/cropped)
        self._output_edit = QLineEdit()
        self._output_edit.setPlaceholderText("Wird automatisch gesetzt...")
        self._output_edit.setReadOnly(True)
        folder_layout.addWidget(QLabel("Ausgabeordner (automatisch: Quellordner/cropped)"))
        folder_layout.addWidget(self._output_edit)

        # Bilder-Info
        self._image_count_label = QLabel("Keine Bilder gefunden")
        self._image_count_label.setObjectName("stat-label")
        folder_layout.addWidget(self._image_count_label)

        layout.addWidget(folder_group)

        # --- Einstellungen ---
        settings_group = QGroupBox("Einstellungen")
        settings_layout = QVBoxLayout(settings_group)

        # Confidence
        self._confidence_spin = StyledDoubleSpinBox(
            "Erkennungs-Schwelle", 0.1, 1.0, 0.5, 0.05
        )
        settings_layout.addWidget(self._confidence_spin)

        # Padding
        self._padding_slider = StyledSlider("Padding", 0, 50, 10, "%")
        settings_layout.addWidget(self._padding_slider)

        # JPEG Qualität
        self._quality_spin = StyledSpinBox("JPEG-Qualität", 50, 100, 95, "%")
        settings_layout.addWidget(self._quality_spin)

        # Max Workers
        self._workers_spin = StyledSpinBox("Parallele Threads", 1, 16, 4)
        settings_layout.addWidget(self._workers_spin)

        # GPU Toggle
        self._gpu_check = QCheckBox("GPU verwenden (CUDA)")
        self._gpu_check.setChecked(True)
        settings_layout.addWidget(self._gpu_check)

        layout.addWidget(settings_group)

        # --- Watermark ---
        watermark_group = QGroupBox("Wasserzeichen")
        wm_layout = QVBoxLayout(watermark_group)

        self._wm_mode = QComboBox()
        self._wm_mode.addItems(["Manuell", "Automatisch (KI)", "Deaktiviert"])
        self._wm_mode.currentIndexChanged.connect(self._on_wm_mode_changed)
        wm_layout.addWidget(QLabel("Modus"))
        wm_layout.addWidget(self._wm_mode)

        self._wm_slider = StyledSlider("Unterer Bereich entfernen", 0, 30, 0, "%")
        wm_layout.addWidget(self._wm_slider)

        # Wasserzeichen-Typ: Logo oder Text / Watermark type: logo or text
        self._wm_type_label = QLabel("Wasserzeichen-Typ")
        self._wm_type_label.setVisible(False)
        wm_layout.addWidget(self._wm_type_label)

        self._wm_type_combo = QComboBox()
        self._wm_type_combo.addItems(["Logo", "Text"])
        self._wm_type_combo.setToolTip(
            "Logo: Kompakte Grafiken in Bildecken (z.B. Firmenlogos)\n"
            "Text: Breite Schriftzuege am Bildrand (z.B. © Fotograf)"
        )
        self._wm_type_combo.setVisible(False)  # Nur bei Auto sichtbar
        wm_layout.addWidget(self._wm_type_combo)

        self._wm_confidence_spin = StyledDoubleSpinBox(
            "WM-Erkennungs-Schwelle", 0.10, 1.0, 0.30, 0.05
        )
        self._wm_confidence_spin.setVisible(False)  # Nur bei Auto sichtbar
        wm_layout.addWidget(self._wm_confidence_spin)

        # Erweiterte Erkennung: TTA + Preprocessing + Template-Matching
        # Enhanced detection: TTA + preprocessing + template matching fallback
        self._wm_enhanced_check = QCheckBox("Erweiterte Logo-Erkennung")
        self._wm_enhanced_check.setToolTip(
            "Aktiviert Multi-Scale-Erkennung (TTA), Kontrastverstaerkung\n"
            "und Template-Matching als Fallback fuer schwer erkennbare Logos."
        )
        self._wm_enhanced_check.setVisible(False)  # Nur bei Auto sichtbar
        wm_layout.addWidget(self._wm_enhanced_check)

        # Strikter Filter: Watermarks muessen am Bildrand liegen
        # Strict filter: watermarks must be at image edges
        self._wm_strict_check = QCheckBox("Strenger Rand-Filter")
        self._wm_strict_check.setToolTip(
            "Wenn aktiv, werden nur Watermarks am Bildrand akzeptiert.\n"
            "Deaktivieren fuer Logos, die nicht am Rand liegen."
        )
        self._wm_strict_check.setChecked(True)
        self._wm_strict_check.setVisible(False)  # Nur bei Auto sichtbar
        wm_layout.addWidget(self._wm_strict_check)

        # Vorlage markieren: User markiert beim 1. Bild das Logo manuell
        # Template marking: user marks the logo on the first image
        self._wm_template_check = QCheckBox("Vorlage markieren (erstes Bild)")
        self._wm_template_check.setToolTip(
            "Beim ersten Bild das Wasserzeichen manuell markieren.\n"
            "Wird dann per Template-Matching in allen Bildern gesucht.\n"
            "Ideal fuer Logos, die die KI nicht automatisch erkennt."
        )
        self._wm_template_check.setChecked(False)
        self._wm_template_check.setVisible(False)  # Nur bei Auto sichtbar
        wm_layout.addWidget(self._wm_template_check)

        layout.addWidget(watermark_group)

        # --- Aktionen ---
        action_layout = QVBoxLayout()
        action_layout.setSpacing(8)

        self._preview_btn = StyledButton("Vorschau laden", "👁", "secondary")
        self._preview_btn.clicked.connect(self._load_preview_for_current)
        action_layout.addWidget(self._preview_btn)

        self._start_btn = StyledButton("Verarbeitung starten", "▶")
        self._start_btn.clicked.connect(self._start_processing)
        action_layout.addWidget(self._start_btn)

        self._stop_btn = StyledButton("Abbrechen", "■", "destructive")
        self._stop_btn.clicked.connect(self._stop_processing)
        self._stop_btn.setEnabled(False)
        action_layout.addWidget(self._stop_btn)

        layout.addLayout(action_layout)

        # --- Fortschritt ---
        self._progress_card = ProgressCard()
        layout.addWidget(self._progress_card)

        layout.addStretch()

    def _setup_content(self, parent_layout: QHBoxLayout) -> None:
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 20, 20, 20)
        content_layout.setSpacing(16)

        # Fortschrittsbalken
        self._progress_bar = QProgressBar()
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setFormat("%p% — %v/%m Bilder")
        self._progress_bar.setValue(0)
        content_layout.addWidget(self._progress_bar)

        # ETA / Speed Info
        self._eta_label = QLabel("")
        self._eta_label.setObjectName("stat-label")
        self._eta_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        content_layout.addWidget(self._eta_label)

        # Preview
        self._preview = PreviewWidget()
        self._preview.preview_requested.connect(self._on_preview_requested)
        content_layout.addWidget(self._preview, 1)

        parent_layout.addWidget(content, 1)

    def _setup_shortcuts(self) -> None:
        # Ctrl+O — Quellordner
        QShortcut(QKeySequence("Ctrl+O"), self, self._select_input_dir)
        # Space — Start/Stop
        QShortcut(QKeySequence("Space"), self, self._toggle_processing)
        # Escape — Stop
        QShortcut(QKeySequence("Escape"), self, self._stop_processing)
        # Left/Right — Bild-Navigation
        QShortcut(QKeySequence("Left"), self, self._preview._go_prev)
        QShortcut(QKeySequence("Right"), self, self._preview._go_next)
        # P — Vorschau laden
        QShortcut(QKeySequence("P"), self, self._load_preview_for_current)

    def _load_settings(self) -> None:
        """Lädt gespeicherte Einstellungen in die UI."""
        input_dir = self._config.get("input_directory", "")
        if input_dir and os.path.isdir(input_dir):
            self._input_edit.setText(input_dir)
            self._scan_images(input_dir)
            # Ausgabeordner immer automatisch aus Quellordner ableiten
            self._output_edit.setText(os.path.join(input_dir, "cropped"))

        self._confidence_spin.setValue(self._config.get("confidence_threshold", 0.5))
        self._padding_slider.setValue(self._config.get("padding_percent", 10))
        self._quality_spin.setValue(self._config.get("jpeg_quality", 95))
        self._workers_spin.setValue(self._config.get("max_workers", 4))
        self._gpu_check.setChecked(self._config.get("use_gpu", True))

        wm_mode = self._config.get("watermark_mode", "manual")
        if wm_mode == "manual":
            self._wm_mode.setCurrentIndex(0)
        elif wm_mode == "auto":
            self._wm_mode.setCurrentIndex(1)
        else:
            self._wm_mode.setCurrentIndex(2)

        self._wm_slider.setValue(self._config.get("watermark_percent", 0))
        self._wm_confidence_spin.setValue(
            self._config.get("watermark_confidence", 0.35)
        )
        self._wm_enhanced_check.setChecked(
            self._config.get("watermark_enhanced_detection", True)
        )
        self._wm_strict_check.setChecked(
            self._config.get("watermark_strict_filter", True)
        )
        self._wm_template_check.setChecked(
            self._config.get("watermark_template_enabled", False)
        )

        wm_type = self._config.get("watermark_type", "logo")
        self._wm_type_combo.setCurrentIndex(0 if wm_type == "logo" else 1)

    def _save_settings(self) -> None:
        """Speichert aktuelle UI-Einstellungen."""
        self._config.set("input_directory", self._input_edit.text())
        self._config.set("output_directory", self._output_edit.text())
        self._config.set("confidence_threshold", self._confidence_spin.value())
        self._config.set("padding_percent", self._padding_slider.value())
        self._config.set("jpeg_quality", self._quality_spin.value())
        self._config.set("max_workers", self._workers_spin.value())
        self._config.set("use_gpu", self._gpu_check.isChecked())
        self._config.set("watermark_percent", self._wm_slider.value())
        self._config.set("watermark_confidence", self._wm_confidence_spin.value())
        self._config.set(
            "watermark_enhanced_detection", self._wm_enhanced_check.isChecked()
        )
        self._config.set(
            "watermark_strict_filter", self._wm_strict_check.isChecked()
        )
        self._config.set(
            "watermark_template_enabled", self._wm_template_check.isChecked()
        )

        idx = self._wm_mode.currentIndex()
        self._config.set("watermark_mode", ["manual", "auto", "disabled"][idx])
        self._config.set(
            "watermark_type", ["logo", "text"][self._wm_type_combo.currentIndex()]
        )

        self._config.set("window_width", self.width())
        self._config.set("window_height", self.height())
        self._config.save()

    # === Model Preload ===

    def _start_model_preload(self) -> None:
        """Startet das Laden beider YOLO-Modelle im Hintergrund.

        Starts loading both YOLO models in background thread on app startup.
        """
        self._eta_label.setText("⏳ KI-Modelle werden geladen...")
        self._preview_btn.setEnabled(False)
        self._preview_btn.setText("⏳ Modell laden...")

        # Progressbar pulsieren lassen / Pulse progress bar during loading
        self._progress_bar.setRange(0, 0)  # Indeterminate / pulsing mode
        self._progress_bar.setFormat("KI-Modelle werden geladen...")

        self._model_loader = ModelLoaderThread(
            person_model="models/yolov8n.pt",
            watermark_model="models/best.pt",
            confidence=self._confidence_spin.value(),
            wm_confidence=self._wm_confidence_spin.value(),
            use_gpu=self._gpu_check.isChecked(),
            wm_strict_filter=self._wm_strict_check.isChecked(),
            wm_enhanced_detection=self._wm_enhanced_check.isChecked(),
            wm_type=["logo", "text"][self._wm_type_combo.currentIndex()],
            parent=self,
        )
        self._model_loader.progress_text.connect(self._on_model_load_progress)
        self._model_loader.model_ready.connect(self._on_models_loaded)
        self._model_loader.error_occurred.connect(self._on_model_load_error)
        self._model_loader.start()

    def _on_model_load_progress(self, text: str) -> None:
        self._eta_label.setText(f"⏳ {text}")
        self._progress_bar.setFormat(text)

    def _on_models_loaded(self, person_detector, wm_detector) -> None:
        """Wird aufgerufen wenn Modelle im Hintergrund fertig geladen sind.

        Called when background model loading is complete.
        """
        self._preview_detector = person_detector
        self._preview_wm_detector = wm_detector
        self._models_loaded = True
        self._model_loader = None

        self._preview_btn.setEnabled(True)
        self._preview_btn.setText("👁  Vorschau laden")
        self._eta_label.setText("✅ Modelle bereit")

        # Progressbar zuruecksetzen / Reset progress bar to normal mode
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setFormat("%p% — %v/%m Bilder")

        logger.info("Modelle im Hintergrund geladen und bereit")

    def _on_model_load_error(self, message: str) -> None:
        logger.error("Fehler beim Modell-Preload: %s", message)
        self._model_loader = None
        # Preview-Button trotzdem aktivieren — Lazy-Load als Fallback
        # Enable preview button anyway — lazy loading as fallback
        self._preview_btn.setEnabled(True)
        self._preview_btn.setText("👁  Vorschau laden")
        self._eta_label.setText(f"❌ Modell-Fehler: {message}")

        # Progressbar zuruecksetzen / Reset progress bar
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setFormat("%p% — %v/%m Bilder")

    # === Slots ===

    def _select_input_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "Quellordner wählen", self._input_edit.text()
        )
        if directory:
            self._input_edit.setText(directory)
            self._scan_images(directory)

            # Ausgabeordner immer auf <Quellordner>/cropped setzen
            output = os.path.join(directory, "cropped")
            self._output_edit.setText(output)


    def _scan_images(self, directory: str) -> None:
        self._image_paths = FileManager.scan_directory(directory)
        count = len(self._image_paths)
        self._image_count_label.setText(
            f"{count} Bilder gefunden" if count > 0 else "Keine Bilder gefunden"
        )
        self._progress_bar.setMaximum(count)
        self._progress_bar.setValue(0)
        self._preview.set_image_count(count)

    def _on_wm_mode_changed(self, index: int) -> None:
        # Slider nur bei manuellem Modus, Auto-Optionen nur bei Auto
        # Slider only in manual mode, auto options only in auto mode
        is_manual = index == 0
        is_auto = index == 1
        self._wm_slider.setVisible(is_manual)
        self._wm_type_label.setVisible(is_auto)
        self._wm_type_combo.setVisible(is_auto)
        self._wm_confidence_spin.setVisible(is_auto)
        self._wm_enhanced_check.setVisible(is_auto)
        self._wm_strict_check.setVisible(is_auto)
        self._wm_template_check.setVisible(is_auto)

    def _toggle_processing(self) -> None:
        if self._processing_thread and self._processing_thread.isRunning():
            self._stop_processing()
        else:
            self._start_processing()

    def _start_processing(self) -> None:
        if not self._image_paths:
            QMessageBox.warning(
                self, "Fehler", "Bitte zuerst einen Quellordner mit Bildern wählen."
            )
            return

        output_dir = self._output_edit.text()
        if not output_dir:
            QMessageBox.warning(self, "Fehler", "Bitte einen Ausgabeordner wählen.")
            return

        self._save_settings()

        wm_idx = self._wm_mode.currentIndex()
        wm_mode = ["manual", "auto", "disabled"][wm_idx]

        config = {
            "confidence_threshold": self._confidence_spin.value(),
            "padding_percent": self._padding_slider.value(),
            "jpeg_quality": self._quality_spin.value(),
            "max_workers": self._workers_spin.value(),
            "use_gpu": self._gpu_check.isChecked(),
            "watermark_mode": wm_mode,
            "watermark_percent": self._wm_slider.value(),
            "watermark_confidence": self._wm_confidence_spin.value(),
            "watermark_strict_filter": self._wm_strict_check.isChecked(),
            "watermark_enhanced_detection": self._wm_enhanced_check.isChecked(),
            "watermark_template_enabled": self._wm_template_check.isChecked(),
            "watermark_type": ["logo", "text"][self._wm_type_combo.currentIndex()],
            "person_model": "models/yolov8n.pt",
            "watermark_model": "models/best.pt",
            "multi_detection_action": self._config.get("multi_detection_action", "ask"),
        }

        self._processing_thread = ProcessingThread(
            image_paths=self._image_paths,
            output_dir=output_dir,
            config=config,
        )
        self._processing_thread.progress.connect(self._on_progress)
        self._processing_thread.image_processed.connect(self._on_image_processed)
        self._processing_thread.preview_ready.connect(self._on_preview_ready)
        self._processing_thread.batch_finished.connect(self._on_batch_finished)
        self._processing_thread.error_occurred.connect(self._on_error)
        self._processing_thread.selection_needed.connect(self._on_selection_needed)
        self._processing_thread.template_needed.connect(self._on_template_needed)
        self._processing_thread.start()

        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._progress_bar.setValue(0)
        self._progress_card.reset()
        self._eta_label.setText("Verarbeitung gestartet...")

    def _stop_processing(self) -> None:
        if self._processing_thread and self._processing_thread.isRunning():
            self._processing_thread.cancel()
            self._eta_label.setText("Abbruch angefordert...")

    def _on_progress(self, current: int, total: int, filename: str) -> None:
        self._progress_bar.setMaximum(total)
        self._progress_bar.setValue(current)
        self._progress_card.set_progress(current, total, filename)

        # ETA berechnen
        if self._processing_thread:
            stats = self._processing_thread.stats
            eta = stats.eta_seconds()
            speed = stats.speed
            if speed > 0:
                eta_min = int(eta // 60)
                eta_sec = int(eta % 60)
                self._eta_label.setText(
                    f"{speed:.1f} Bilder/s — ETA: {eta_min}:{eta_sec:02d}"
                )

    def _on_image_processed(self, result: dict) -> None:
        if self._processing_thread:
            self._progress_card.set_stats(
                {
                    "processed": self._processing_thread.stats.processed,
                    "skipped": self._processing_thread.stats.skipped,
                    "errors": self._processing_thread.stats.errors,
                    "watermarks": self._processing_thread.stats.watermarks_found,
                    "speed": self._processing_thread.stats.speed,
                }
            )

    def _on_preview_ready(
        self, path, original, cropped, boxes, watermark_boxes
    ) -> None:
        filename = Path(path).name
        # Crop-Region berechnen für Overlay
        crop_region = None
        if boxes:
            wm_idx = self._wm_mode.currentIndex()
            wm_mode = ["manual", "auto", "disabled"][wm_idx]
            crop_region = CropEngine.calculate_crop_region(
                image_shape=original.shape,
                person_boxes=boxes,
                padding_percent=self._padding_slider.value(),
                watermark_boxes=watermark_boxes if wm_mode == "auto" else None,
                watermark_percent=self._wm_slider.value() if wm_mode == "manual" else 0,
            )
        self._preview.set_preview(
            original, cropped, boxes, filename, watermark_boxes, crop_region
        )

    def _on_batch_finished(self, summary: dict) -> None:
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._progress_card.set_stats(summary)

        elapsed = summary.get("elapsed", 0)
        minutes = int(elapsed // 60)
        seconds = int(elapsed % 60)
        self._eta_label.setText(
            f"Fertig! {summary['processed']}/{summary['total']} verarbeitet "
            f"in {minutes}:{seconds:02d} ({summary['speed']:.1f} Bilder/s)"
        )

        self._save_settings()

    def _on_error(self, message: str) -> None:
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        QMessageBox.critical(self, "Fehler", message)
        self._eta_label.setText(f"Fehler: {message}")

    def _get_preview_detectors(self) -> tuple[PersonDetector, WatermarkDetector | None]:
        """Gibt vorgeladene Detektoren zurück (oder Lazy-Init als Fallback).

        Returns preloaded detectors, or falls back to lazy init if preload failed.
        """
        # Warten falls Preload noch läuft / Wait if preload is still running
        if self._model_loader and self._model_loader.isRunning():
            self._eta_label.setText("Warte auf Modell...")
            self._model_loader.wait(10000)  # max 10s

        # Preloaded Detektoren nutzen / Use preloaded detectors
        if self._preview_detector is not None:
            self._preview_detector.set_confidence(self._confidence_spin.value())
            self._preview_detector.set_gpu(self._gpu_check.isChecked())
        else:
            # Fallback: Lazy-Init falls Preload fehlgeschlagen
            # Fallback: lazy init if preload failed
            self._preview_detector = PersonDetector(
                model_path="models/yolov8n.pt",
                confidence=self._confidence_spin.value(),
                use_gpu=self._gpu_check.isChecked(),
            )
            if not self._preview_detector.load_model():
                detail = self._preview_detector.last_error or "Unbekannter Fehler"
                logger.error("Preview-Detector konnte nicht geladen werden: %s", detail)

        wm_idx = self._wm_mode.currentIndex()
        wm_detector = None
        if wm_idx == 1:  # Auto
            if self._preview_wm_detector is not None:
                self._preview_wm_detector.set_confidence(self._wm_confidence_spin.value())
                self._preview_wm_detector.set_gpu(self._gpu_check.isChecked())
            else:
                # Fallback: Lazy-Init
                self._preview_wm_detector = WatermarkDetector(
                    model_path="models/best.pt",
                    confidence=self._wm_confidence_spin.value(),
                    use_gpu=self._gpu_check.isChecked(),
                )
                if not self._preview_wm_detector.load_model():
                    detail = self._preview_wm_detector.last_error or "Unbekannter Fehler"
                    logger.error("Preview-WM-Detector konnte nicht geladen werden: %s", detail)
            wm_detector = self._preview_wm_detector

        return self._preview_detector, wm_detector

    def _load_preview_for_index(self, index: int) -> None:
        """Lädt die Vorschau für ein bestimmtes Bild (asynchron mit Fortschritt)."""
        if not self._image_paths or index < 0 or index >= len(self._image_paths):
            return

        # Falls bereits ein Preview-Thread läuft, abbrechen
        if self._preview_thread and self._preview_thread.isRunning():
            self._preview_thread.wait(2000)

        path = self._image_paths[index]
        filename = Path(path).name
        self._eta_label.setText(f"Lade Vorschau: {filename}...")

        # UI für Ladevorgang vorbereiten
        self._preview_btn.setEnabled(False)
        self._preview_btn.setText("⏳ Lade...")
        self._progress_bar.setMaximum(0)  # Indeterminate / pulsierend
        self._progress_bar.setFormat("Vorschau wird geladen...")

        # Detektoren vorbereiten (Lazy-Init, synchron — nur beim ersten Mal langsam)
        person_detector, wm_detector = self._get_preview_detectors()

        wm_idx = self._wm_mode.currentIndex()
        wm_mode = ["manual", "auto", "disabled"][wm_idx]

        self._preview_thread = PreviewLoadThread(
            image_path=path,
            index=index,
            person_detector=person_detector,
            wm_detector=wm_detector,
            wm_mode=wm_mode,
            padding_percent=self._padding_slider.value(),
            wm_percent=self._wm_slider.value(),
            parent=self,
        )
        self._preview_thread.progress.connect(self._on_preview_progress)
        self._preview_thread.preview_done.connect(self._on_preview_load_done)
        self._preview_thread.error_occurred.connect(self._on_preview_load_error)
        self._preview_thread.start()

    def _on_preview_progress(self, step: int, total: int, description: str) -> None:
        """Aktualisiert Fortschrittsbalken während Preview-Laden."""
        self._progress_bar.setMaximum(total)
        self._progress_bar.setValue(step)
        self._progress_bar.setFormat(f"Vorschau: %v/%m — {description}")
        self._eta_label.setText(description)

    def _on_preview_load_done(
        self, index: int, original, cropped, person_boxes: list, wm_boxes: list, filename: str
    ) -> None:
        """Wird aufgerufen wenn der Preview-Thread fertig ist.

        Called when preview thread finishes. Shows selection dialog if
        multiple detections found.
        """
        # Crop-Region berechnen für Overlay
        crop_region = None
        if person_boxes:
            wm_idx = self._wm_mode.currentIndex()
            wm_mode = ["manual", "auto", "disabled"][wm_idx]
            crop_region = CropEngine.calculate_crop_region(
                image_shape=original.shape,
                person_boxes=person_boxes,
                padding_percent=self._padding_slider.value(),
                watermark_boxes=wm_boxes if wm_mode == "auto" else None,
                watermark_percent=self._wm_slider.value() if wm_mode == "manual" else 0,
            )

        self._preview.set_current_index(index)
        self._preview.set_preview(
            original, cropped, person_boxes, filename, wm_boxes, crop_region
        )

        # Status-Info
        info_parts = [f"{len(person_boxes)} Person(en)"]
        if wm_boxes:
            info_parts.append(f"{len(wm_boxes)} Watermark(s)")
        if not person_boxes:
            info_parts = ["Keine Person erkannt"]
        self._eta_label.setText(f"{filename}: {', '.join(info_parts)}")

        # UI wiederherstellen / Restore UI
        self._preview_btn.setEnabled(True)
        self._preview_btn.setText("👁  Vorschau laden")
        self._progress_bar.setMaximum(len(self._image_paths))
        self._progress_bar.setValue(0)
        self._progress_bar.setFormat("%p% — %v/%m Bilder")

        # Bei Mehrfach-Erkennung → Auswahl-Dialog öffnen
        # Multi-detection → open selection dialog
        if len(person_boxes) > 1 or len(wm_boxes) > 1:
            QTimer.singleShot(
                200,
                lambda: self._show_selection_for_preview(
                    original, person_boxes, wm_boxes, filename
                ),
            )

    def _on_preview_load_error(self, message: str) -> None:
        """Wird aufgerufen wenn der Preview-Thread einen Fehler hat."""
        logger.error("Preview-Fehler: %s", message)
        self._eta_label.setText(f"Fehler: {message}")

        # UI wiederherstellen
        self._preview_btn.setEnabled(True)
        self._preview_btn.setText("👁  Vorschau laden")
        self._progress_bar.setMaximum(len(self._image_paths))
        self._progress_bar.setValue(0)
        self._progress_bar.setFormat("%p% — %v/%m Bilder")

    def _load_preview_for_current(self) -> None:
        """Lädt die Vorschau für das aktuelle Bild."""
        if not self._image_paths:
            QMessageBox.information(
                self, "Hinweis", "Bitte zuerst einen Quellordner wählen."
            )
            return
        self._load_preview_for_index(self._preview._current_index)

    def _on_preview_requested(self, index: int) -> None:
        """Wird aufgerufen wenn der User über Prev/Next navigiert."""
        self._load_preview_for_index(index)

    # === Selection Dialog (Multi-Detection) ===

    def _on_template_needed(self, path: str, image) -> None:
        """Batch-Thread braucht Watermark-Template vom User.

        Processing thread found no watermark in the first image via YOLO.
        Opens template marking dialog so user can manually select a region.
        """
        filename = Path(path).name
        dialog = WatermarkTemplateDialog(
            image=image, filename=filename, parent=self
        )
        if dialog.exec():
            box = dialog.get_selected_box()
            self._processing_thread.set_template_result(box)
        else:
            # User hat uebersprungen / User skipped
            self._processing_thread.set_template_result(None)

    def _on_selection_needed(
        self, path: str, image, person_boxes: list, wm_boxes: list
    ) -> None:
        """Batch-Thread benötigt Benutzer-Auswahl bei Mehrfach-Erkennung.

        Batch thread needs user selection for multi-detection.
        Opens modal dialog, then resumes thread with result.
        """
        filename = Path(path).name
        dialog = DetectionSelectionDialog(
            image=image,
            person_boxes=person_boxes,
            wm_boxes=wm_boxes,
            filename=filename,
            parent=self,
        )

        if dialog.exec():
            result = dialog.result
            self._processing_thread.set_selection_result(
                persons=result.selected_persons,
                watermarks=result.selected_watermarks,
                skip=result.skip_image,
                rule=result.apply_rule,
            )
        else:
            # Dialog geschlossen (X) → Bild überspringen
            # Dialog closed (X) → skip image
            self._processing_thread.set_selection_result(
                persons=None, watermarks=None, skip=True
            )

    def _show_selection_for_preview(
        self,
        image,
        person_boxes: list,
        wm_boxes: list,
        filename: str,
    ) -> None:
        """Zeigt Auswahl-Dialog im Preview-Modus und aktualisiert die Vorschau.

        Shows selection dialog in preview mode and updates preview with result.
        """
        dialog = DetectionSelectionDialog(
            image=image,
            person_boxes=person_boxes,
            wm_boxes=wm_boxes,
            filename=filename,
            parent=self,
        )

        if dialog.exec():
            result = dialog.result
            if result.skip_image or not result.selected_persons:
                return

            # Crop-Region mit ausgewählten Boxen neu berechnen
            # Recalculate crop region with selected boxes only
            wm_idx = self._wm_mode.currentIndex()
            wm_mode = ["manual", "auto", "disabled"][wm_idx]
            crop_region = CropEngine.calculate_crop_region(
                image_shape=image.shape,
                person_boxes=result.selected_persons,
                padding_percent=self._padding_slider.value(),
                watermark_boxes=result.selected_watermarks if wm_mode == "auto" else None,
                watermark_percent=self._wm_slider.value() if wm_mode == "manual" else 0,
            )

            cropped = None
            if crop_region:
                cropped = CropEngine.crop_image(image, crop_region)

            self._preview.set_preview(
                image, cropped, result.selected_persons,
                filename, result.selected_watermarks, crop_region,
            )

    def closeEvent(self, event) -> None:
        self._save_settings()
        if self._model_loader and self._model_loader.isRunning():
            self._model_loader.wait(3000)
        if self._preview_thread and self._preview_thread.isRunning():
            self._preview_thread.wait(2000)
        if self._processing_thread and self._processing_thread.isRunning():
            self._processing_thread.cancel()
            self._processing_thread.wait(3000)
        super().closeEvent(event)
