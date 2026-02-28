"""Runtime-Hook: Torch & CUDA DLL-Pfade für PyInstaller Folder-Mode korrekt setzen.

Dieses Skript wird VOR allen Imports ausgeführt und stellt sicher,
dass Windows die Torch/CUDA DLLs im _internal-Verzeichnis findet.
Ohne diesen Hook scheitert `import torch` mit "DLL load failed".

Kernproblem: PyInstallers Bootloader ruft SetDllDirectory() auf und überschreibt
damit die Windows DLL-Suchordnung. Das verhindert, dass torch/lib/c10.dll seine
Abhängigkeiten (CUDA, NVIDIA) findet. Lösung:
  1. SetDllDirectoryW(None) → Bootloader-Override zurücksetzen
  2. os.add_dll_directory() → alle relevanten Pfade registrieren
  3. PATH erweitern → Fallback für native Libraries
"""

import ctypes
import ctypes.wintypes
import os
import sys


def _setup_dll_paths():
    """Registriert alle relevanten DLL-Verzeichnisse im PyInstaller-Bundle."""
    if not getattr(sys, "frozen", False):
        return  # Nur im gepackten EXE nötig

    # sys._MEIPASS zeigt auf _internal/ im Folder-Mode
    internal_dir = getattr(sys, "_MEIPASS", os.path.join(os.path.dirname(sys.executable), "_internal"))

    # Primäre DLL-Verzeichnisse (Reihenfolge wichtig!)
    dll_dirs = [
        internal_dir,
        os.path.join(internal_dir, "torch", "lib"),
        os.path.join(internal_dir, "torch", "bin"),
    ]

    # NVIDIA / CUDA DLL-Verzeichnisse rekursiv suchen
    # (PyInstaller legt diese z.B. unter _internal/nvidia/cublas/lib/ ab)
    for vendor_dir in ("nvidia", "cuda", "cudnn", "tensorrt"):
        vendor_path = os.path.join(internal_dir, vendor_dir)
        if os.path.isdir(vendor_path):
            for root, _dirs, files in os.walk(vendor_path):
                if any(f.lower().endswith(".dll") for f in files):
                    dll_dirs.append(root)

    # ── Schritt 1: PyInstaller Bootloader-Override zurücksetzen ──
    # Der Bootloader ruft SetDllDirectory(app_dir) auf, was die normale
    # DLL-Suchordnung überschreibt. NULL setzt den Standard zurück.
    # Siehe: https://github.com/pyinstaller/pyinstaller/wiki/Recipe-subprocess
    try:
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    except Exception:
        pass

    # ── Schritt 2: os.add_dll_directory() für alle Pfade ──
    # Python 3.8+: Registriert zusätzliche DLL-Suchverzeichnisse
    for d in dll_dirs:
        if os.path.isdir(d):
            try:
                os.add_dll_directory(d)
            except OSError:
                pass

    # ── Schritt 3: PATH erweitern (Fallback) ──
    # Manche native Libs nutzen noch den klassischen PATH-Suchweg
    existing = set(os.environ.get("PATH", "").split(os.pathsep))
    new_entries = [d for d in dll_dirs if os.path.isdir(d) and d not in existing]
    if new_entries:
        os.environ["PATH"] = (
            os.pathsep.join(new_entries) + os.pathsep + os.environ.get("PATH", "")
        )


_setup_dll_paths()

