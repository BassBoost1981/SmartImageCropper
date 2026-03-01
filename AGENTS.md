# AGENTS.md

Guidelines for AI coding agents working in the SmartImageCropper repository.

## Project Summary

Python 3.11+ Windows desktop app (PyQt6) for batch image cropping with YOLOv8 person detection and optional watermark detection. UI language is German; code comments are bilingual (German + English).

## Commands

```bash
# Run the app
python main.py

# Run all tests
pytest tests/ -v

# Run a single test file
pytest tests/test_cropper.py -v

# Run a single test class
pytest tests/test_cropper.py::TestCropEngine -v

# Run a single test method
pytest tests/test_cropper.py::TestCropEngine::test_single_person -v

# Lint and format
black src/ tests/
flake8 src/ tests/
mypy src/

# Build Windows EXE (PyInstaller folder mode)
build_exe.bat
```

There is no pyproject.toml or setup.cfg. Black, flake8, and mypy use their defaults. Black line length is 88 (default).

## Architecture

```
main.py                  Entry point (QApplication + ConfigManager + MainWindow)
src/core/detector.py     PersonDetector (YOLOv8, thread-locked via _detection_lock)
src/core/watermark.py    WatermarkDetector (second YOLO model, _watermark_lock)
src/core/cropper.py      CropEngine (static methods, pure NumPy)
src/core/processor.py    ProcessingThread, ModelLoaderThread, PreviewLoadThread (QThread)
src/ui/main_window.py    MainWindow (QMainWindow, sidebar + preview)
src/ui/preview_widget.py PreviewWidget
src/ui/selection_dialog.py  DetectionSelectionDialog + SelectionResult dataclass
src/ui/widgets.py        Custom styled widgets (StyledButton, StyledSlider, etc.)
src/ui/styles.py         GLASSMORPHISM_STYLE QSS string
src/utils/config.py      ConfigManager (settings.json persistence)
src/utils/logger.py      setup_logging() + get_logger()
src/utils/file_manager.py  FileManager (static methods for scan/load/save)
src/utils/stats.py       StatsCollector (batch timing/counters)
```

## Code Style

### Formatting
- Formatter: **Black** with default settings (line length 88)
- No trailing semicolons, no star imports

### Imports
Organize imports in three groups separated by blank lines:
1. Standard library (`os`, `sys`, `threading`, `json`, `time`, `pathlib`)
2. Third-party (`numpy`, `cv2`, `PyQt6`, `ultralytics`)
3. Local (`from src.core.detector import ...`, `from src.utils.logger import ...`)

```python
import os
import threading
from dataclasses import dataclass

import numpy as np

from src.core.detector import BoundingBox
from src.utils.logger import get_logger
```

### Type Hints
- Use Python 3.10+ syntax everywhere: `list[str]`, `dict[str, Any]`, `tuple[int, int]`, `X | None`
- Do NOT use `typing.List`, `typing.Optional`, `typing.Dict`, etc.
- Exception: `typing.Any` is acceptable (imported in config.py)
- Annotate all function signatures (parameters and return types)

### Naming Conventions
- Classes: `PascalCase` (`PersonDetector`, `CropEngine`, `MainWindow`)
- Functions/methods: `snake_case` (`calculate_crop_region`, `load_model`)
- Private members: single `_` prefix (`_model`, `_last_error`, `_setup_ui`)
- Constants: `UPPER_SNAKE_CASE` (`PERSON_CLASS_ID`, `SUPPORTED_FORMATS`, `DEFAULTS`)
- Qt signals: `snake_case` (`model_ready`, `batch_finished`, `selection_needed`, `box_toggled`)
- Class constants on the class body, not module-level (e.g., `WatermarkDetector.MAX_AREA_RATIO`)

### Docstrings
- Every module starts with a one-line `"""..."""` docstring (German, describing purpose)
- Classes get a one-line docstring
- Public methods get a brief docstring; private methods may omit them
- No specific docstring format (Google/NumPy) is enforced; keep them short

```python
"""PersonDetector: YOLOv8-Wrapper fuer Personenerkennung, thread-safe."""
```

### Data Containers
- Use `@dataclass` for pure data objects (`BoundingBox`, `SelectionResult`)
- Use `field(default_factory=list)` for mutable defaults in dataclasses
- Use `@property` for computed attributes on dataclasses and regular classes

### Error Handling
- Detectors use the `.last_error` property pattern: store error as `str | None`, check after calling
- `load_model()` returns `bool` (True = success); errors stored in `_last_error`
- `detect()` returns empty `list` on failure (no exceptions raised to caller)
- GPU errors: catch `RuntimeError` and auto-fallback to CPU
- File I/O: catch `(json.JSONDecodeError, OSError)` or `Exception`, log with `logger.error()`/`logger.warning()`
- Never silently swallow exceptions; always log them

### Logging
- Always use `get_logger(__name__)` at module level — never `logging.getLogger()` directly
- Logger hierarchy: `SmartImageCropper.<module>` (child loggers inherit file + console handlers)
- Use `%s`-style formatting in log calls (not f-strings): `logger.info("Found %d items", count)`
- Use `exc_info=True` for unexpected exceptions: `logger.error("Failure: %s", e, exc_info=True)`

### File I/O (Windows-safe)
- Load images: `np.fromfile(path, dtype=np.uint8)` + `cv2.imdecode()` (handles Unicode paths)
- Save images: `cv2.imencode()` + Python `open(..., "wb")` (not `cv2.imwrite()`)
- Never use `cv2.imread()` or `cv2.imwrite()` directly — they fail on non-ASCII Windows paths

### Threading
- YOLO models are not thread-safe. Inference must be wrapped in the module-level `threading.Lock()`
- `_detection_lock` for PersonDetector, `_watermark_lock` for WatermarkDetector
- Background work uses `QThread` subclasses; communicate via `pyqtSignal`
- Use `threading.Event` for pause/resume (interactive selection during batch processing)

### Static vs Instance Methods
- `CropEngine` and `FileManager`: all `@staticmethod` — no instance state
- Detectors (`PersonDetector`, `WatermarkDetector`): instance-based with mutable state

### Testing Patterns
- Test files: `tests/test_*.py`, grouped by test class (`class TestCropEngine`, `class TestBoundingBox`)
- Use `setup_method(self)` for per-test setup (not `setUp` or fixtures)
- Use `@pytest.mark.skipif` for tests requiring model files:
  ```python
  @pytest.mark.skipif(
      not os.path.exists("models/yolov8n.pt"),
      reason="YOLO model nicht vorhanden",
  )
  ```
- Test crop logic with pure NumPy arrays (no model dependency)
- Test detector behavior with missing model paths (expect graceful failure)
- Assert on return values and properties; access private attrs (`_confidence`) in tests when needed

### UI Conventions
- UI text is in **German**
- Method pattern: `_setup_ui()` builds layout, `_on_<event>()` handles signals
- Custom widgets inherit from PyQt6 base classes and live in `src/ui/widgets.py`
- Global stylesheet in `src/ui/styles.py` (`GLASSMORPHISM_STYLE`), applied via `app.setStyleSheet()`

### Path Resolution
- `_get_model_path()` in `detector.py` resolves paths for dev mode, PyInstaller one-file (`sys._MEIPASS`), and folder mode (`_internal/`). Reuse it for any bundled resource.

## Dependencies

Runtime: PyQt6, opencv-python, numpy, Pillow, ultralytics, torch, huggingface-hub
Dev: pytest, black, flake8, mypy, pyinstaller

## Config

`config/settings.json` managed by `ConfigManager`. Key defaults:
`jpeg_quality=95`, `confidence_threshold=0.5`, `padding_percent=10`,
`watermark_mode="manual"`, `use_gpu=True`, `output_format="original"`,
`multi_detection_action="ask"`.
