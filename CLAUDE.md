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

# Build Windows installer (requires NSIS, run after build_exe.bat)
build_installer.bat
```

## Architecture

```
main.py → QApplication + ConfigManager init → MainWindow

src/ui/          — PyQt6 UI layer
src/core/        — AI detection + crop pipeline
src/utils/       — Config, logging, file management, stats
models/          — YOLO model weights (.pt files)
config/          — settings.json (runtime config, persisted between runs)
build/           — PyInstaller specs, NSIS installer script, runtime hooks
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

- Heavy processing runs in `ProcessingThread` (QThread), which uses `ThreadPoolExecutor` for parallel workers
- YOLO models are **not thread-safe** — inference is serialized via module-level `threading.Lock()` in `detector.py` (`_detection_lock`) and `watermark.py` (`_watermark_lock`)
- Three distinct preview mechanisms: `DetectionPreviewThread` (quick detection-only scans), `PreviewLoadThread` (full pipeline with step progress signals), and `ProcessingThread._emit_preview()` (inline preview during batch, every 10 images)

### Watermark Handling

Two modes: **Manual** (fixed bottom-percentage crop via slider, 0-30%) and **Auto** (second YOLO model `models/best.pt` detects watermark bounding boxes). Auto model is loaded on demand and downloaded from HuggingFace (`corzent/yolo11x_watermark_detection`) if not present locally — download only works in dev mode, not inside the bundled EXE.

`WatermarkDetector` applies post-YOLO plausibility filtering to reduce false positives: boxes are rejected if they exceed 15% of the image area or are not in an edge region (bottom 30%, top 15%, or side 15%).

### Key Design Decisions

- **File loading**: Uses `np.fromfile()` + `cv2.imdecode()` instead of `cv2.imread()` to handle Unicode/non-ASCII Windows paths reliably
- **File saving**: Uses `cv2.imencode()` + raw Python file IO instead of `cv2.imwrite()`, with post-write size verification
- **Path resolution**: `_get_model_path()` in `detector.py` resolves model paths for both dev mode and PyInstaller EXE (`sys._MEIPASS` / `_internal/` folder)
- **CropEngine** and **FileManager**: All methods are `@staticmethod` — no instance state
- **GPU fallback**: Both `PersonDetector` and `WatermarkDetector` catch `RuntimeError` during CUDA inference and automatically retry on CPU
- **EXE icon**: `build/generate_icon.py` converts `logo no_bg-cropped.svg` → `build/app.ico` (multi-resolution: 16–256px). Run it before building. The spec references `build/app.ico` via the `icon=` parameter in EXE()
- **EXE build**: PyInstaller folder mode (COLLECT, not onefile) for faster startup. UPX disabled to prevent CUDA DLL corruption. Custom `runtime_hook_dll.py` fixes torch DLL path resolution
- **Logging**: `RotatingFileHandler` (5 MB, 3 backups) to `logs/smartimagecropper.log`. Console handler only shows WARNING+. All modules use child loggers under `SmartImageCropper.*`

## AI Models

| File | Size | Purpose |
|------|------|---------|
| `models/yolov8n.pt` | ~6.5 MB | Person detection (COCO class 0) |
| `models/best.pt` | ~109 MB | Watermark detection (auto mode) |

## Testing

Tests in `tests/test_detector.py` that require the real YOLO model file use `@pytest.mark.skipif(not os.path.exists("models/yolov8n.pt"), ...)` to skip gracefully when the model isn't available. `tests/test_cropper.py` tests crop logic with pure NumPy arrays (no model dependency).

## Config Keys (`config/settings.json`)

Key defaults: `jpeg_quality=95`, `confidence_threshold=0.5`, `padding_percent=10`, `watermark_mode="manual"`, `watermark_percent=0`, `use_gpu=True`, `max_workers=4`, `output_format="original"`. Full defaults defined in `src/utils/config.py:DEFAULTS`.
