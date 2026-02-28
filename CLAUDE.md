# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Smart Image Cropper — a Python 3.11+ Windows desktop app (PyQt6) for batch image processing with AI-based person detection (YOLOv8) and optional watermark detection/removal. UI is in German.

## Commands

```bash
# Run
python main.py

# Test
pytest tests/ -v
pytest tests/test_cropper.py -v          # single test file
pytest tests/test_cropper.py::TestName -v # single test class

# Lint & Format
black src/ tests/
flake8 src/ tests/
mypy src/

# Generate EXE icon from SVG (run once or after logo changes)
python build/generate_icon.py

# Build Windows EXE (folder mode via PyInstaller)
build_exe.bat
# or: pyinstaller build\build.spec --clean --noconfirm
```

## Architecture

```
main.py → QApplication + ConfigManager init → MainWindow

src/ui/          — PyQt6 UI layer
src/core/        — AI detection + crop pipeline
src/utils/       — Config, logging, file management, stats
models/          — YOLO model weights (.pt files)
config/          — settings.json (runtime config, persisted between runs)
build/           — PyInstaller specs, runtime hooks, icon generator
```

### Processing Pipeline (per image)

1. `FileManager.scan_directory()` finds images (JPEG, PNG, BMP, WebP)
2. `ProcessingThread` (QThread) runs `ImageProcessor.process_batch()`
3. `PersonDetector.detect()` — YOLOv8 inference (thread-locked)
4. If auto watermark mode: `WatermarkDetector.detect()` via second YOLO model (thread-locked)
5. `CropEngine.calculate_crop_region()` — computes crop box with padding + watermark avoidance
6. `CropEngine.crop_image()` — slices the NumPy array
7. Image saved via `cv2.imencode()` + native Python file IO (avoids `cv2.imwrite()` reliability issues on Windows)

### Threading Model

- **ModelLoaderThread**: Background model preload at app startup, emits `model_ready` / `error_occurred`
- **ProcessingThread**: Batch loop in QThread. Uses `threading.Event` for pause/resume when user selection is needed (multi-person dialog). Emits `progress`, `preview_ready`, `batch_finished`, `selection_needed`
- **PreviewLoadThread**: Single-image full pipeline with step-by-step progress signals (load → detect → crop)
- YOLO models are **not thread-safe** — inference serialized via module-level `threading.Lock()` in `detector.py` (`_detection_lock`) and `watermark.py` (`_watermark_lock`)

### Pause/Resume for Interactive Selection

When multiple persons are detected during batch processing:
1. `ProcessingThread._pause_event.clear()` pauses the thread
2. `selection_needed` signal sent to MainWindow
3. MainWindow shows `DetectionSelectionDialog` (interactive bounding box selection)
4. User picks boxes → `set_selection_result()` → `_pause_event.set()` resumes thread

### Watermark Handling

Two modes: **Manual** (fixed bottom-percentage crop via slider, 0-30%) and **Auto** (second YOLO model `models/best.pt` detects watermark bounding boxes). Auto model loaded on demand and downloaded from HuggingFace (`corzent/yolo11x_watermark_detection`) if not present locally — download only works in dev mode, not inside the bundled EXE.

`WatermarkDetector` applies post-YOLO plausibility filtering: boxes rejected if >15% image area or not in edge region (bottom 30%, top 15%, or side 15%).

### Key Design Decisions

- **File loading**: `np.fromfile()` + `cv2.imdecode()` instead of `cv2.imread()` for Unicode/non-ASCII Windows paths
- **File saving**: `cv2.imencode()` + Python file IO instead of `cv2.imwrite()`, with post-write size verification
- **Path resolution**: `_get_model_path()` in `detector.py` resolves for dev mode, PyInstaller one-file (`sys._MEIPASS`), and folder mode (`_internal/`)
- **CropEngine** and **FileManager**: All `@staticmethod` — no instance state
- **GPU fallback**: Both detectors catch `RuntimeError` during CUDA inference and auto-retry on CPU
- **Deferred error reporting**: Detectors use `.last_error` property pattern
- **EXE build**: PyInstaller folder mode (COLLECT, not onefile). UPX disabled (prevents CUDA DLL corruption). Custom `runtime_hook_dll.py` fixes torch DLL path resolution. `build/build.spec` collects torch + nvidia CUDA packages
- **Logging**: `RotatingFileHandler` (5 MB, 3 backups) to `logs/smartimagecropper.log`. All modules use `get_logger(__name__)` creating child loggers under `SmartImageCropper.*`. Console only WARNING+
- **UI theme**: Single `GLASSMORPHISM_STYLE` QSS string in `styles.py` — dark theme with purple gradients (#6c5ce7 → #a855f7), applied globally via `app.setStyleSheet()`. Font: Lexend (loaded from `Font/`)

## Code Conventions

- Type hints: Python 3.10+ style (`list[Type]`, `Type | None`)
- `@dataclass` for data containers (`BoundingBox`, `SelectionResult`)
- Qt signals: snake_case (`model_ready`, `batch_finished`, `box_toggled`)
- Private methods: `_` prefix (`_setup_ui`, `_on_progress`)
- All loggers via `get_logger(__name__)`, never raw `logging.getLogger()`

## AI Models

| File | Size | Purpose |
|------|------|---------|
| `models/yolov8n.pt` | ~6.5 MB | Person detection (COCO class 0) |
| `models/best.pt` | ~109 MB | Watermark detection (auto mode) |

## Testing

`tests/test_detector.py` uses `@pytest.mark.skipif(not os.path.exists("models/yolov8n.pt"), ...)` to skip when model unavailable. `tests/test_cropper.py` tests crop logic with pure NumPy arrays (no model dependency).

## Config (`config/settings.json`)

Managed by `ConfigManager` (`get(key)`, `set(key, val)`, `save()`). Merges with `DEFAULTS` dict on load. Full defaults in `src/utils/config.py:DEFAULTS`:

Key defaults: `jpeg_quality=95`, `confidence_threshold=0.5`, `padding_percent=10`, `watermark_mode="manual"`, `watermark_percent=0`, `use_gpu=True`, `max_workers=4`, `output_format="original"`, `multi_detection_action="ask"`, `preserve_metadata=False`.
