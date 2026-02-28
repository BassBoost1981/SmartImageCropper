"""Logging-Setup mit Rotation."""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler


def setup_logging(log_dir: str = "logs", level: int = logging.INFO) -> logging.Logger:
    """Konfiguriert und gibt den App-Logger zurück."""
    # Log-Dir relativ zur EXE wenn frozen
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        log_dir = os.path.join(exe_dir, "logs")

    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "smartimagecropper.log")

    logger = logging.getLogger("SmartImageCropper")
    logger.setLevel(level)

    if logger.handlers:
        return logger

    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(level)
    file_fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s.%(funcName)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_fmt)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_fmt = logging.Formatter("[%(levelname)s] %(message)s")
    console_handler.setFormatter(console_fmt)
    logger.addHandler(console_handler)

    return logger


def get_logger(name: str = "SmartImageCropper") -> logging.Logger:
    """Gibt einen Child-Logger zurück.

    Stellt sicher, dass alle Logger als Children von 'SmartImageCropper' registriert
    werden, damit sie die konfigurierten Handler (File + Console) erben.
    """
    if name == "SmartImageCropper":
        return logging.getLogger(name)
    # Child-Logger: SmartImageCropper.src.core.detector etc.
    return logging.getLogger(f"SmartImageCropper.{name}")
