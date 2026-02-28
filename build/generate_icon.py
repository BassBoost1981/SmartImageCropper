"""Hilfsskript: Konvertiert das SVG-Logo in eine .ico-Datei für den EXE-Build.

Verwendung:
    python build/generate_icon.py

Benötigt PyQt6 (bereits als Abhängigkeit installiert).
Erzeugt build/app.ico mit mehreren Auflösungen (16, 32, 48, 64, 128, 256).
"""

import os
import sys

# Projekt-Root in den Pfad aufnehmen
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)


def main():
    from PyQt6.QtCore import QSize, Qt
    from PyQt6.QtGui import QImage, QPainter, QPixmap
    from PyQt6.QtSvg import QSvgRenderer
    from PyQt6.QtWidgets import QApplication

    # QApplication wird für QPixmap benötigt
    app = QApplication(sys.argv)  # noqa: F841

    svg_path = os.path.join(project_root, "logo no_bg-cropped.svg")
    ico_path = os.path.join(project_root, "build", "app.ico")

    if not os.path.exists(svg_path):
        print(f"FEHLER: SVG nicht gefunden: {svg_path}")
        sys.exit(1)

    renderer = QSvgRenderer(svg_path)
    if not renderer.isValid():
        print(f"FEHLER: SVG ungültig: {svg_path}")
        sys.exit(1)

    # Mehrere Auflösungen für .ico
    sizes = [16, 32, 48, 64, 128, 256]
    images = []

    for size in sizes:
        image = QImage(QSize(size, size), QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        images.append((size, image))

    # ICO-Datei schreiben (ICO-Format manuell zusammenbauen)
    _write_ico(ico_path, images)
    print(f"Icon erstellt: {ico_path}")
    print(f"  Auflösungen: {', '.join(f'{s}x{s}' for s in sizes)}")


def _write_ico(path, images):
    """Schreibt eine .ico-Datei mit mehreren Auflösungen."""
    import struct

    # PNG-Daten für jede Größe erzeugen
    from PyQt6.QtCore import QBuffer, QIODevice

    png_data_list = []
    for size, image in images:
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buf, "PNG")
        png_data_list.append(bytes(buf.data()))
        buf.close()

    num_images = len(images)
    # ICONDIR: 3 x WORD (reserved=0, type=1, count)
    header = struct.pack("<HHH", 0, 1, num_images)

    # Offsets berechnen: Header + N * ICONDIRENTRY (je 16 Bytes)
    data_offset = 6 + num_images * 16

    entries = b""
    for i, ((size, _image), png_data) in enumerate(zip(images, png_data_list)):
        w = 0 if size >= 256 else size  # 0 bedeutet 256
        h = 0 if size >= 256 else size
        # ICONDIRENTRY: bWidth, bHeight, bColorCount, bReserved,
        #               wPlanes, wBitCount, dwBytesInRes, dwImageOffset
        entries += struct.pack(
            "<BBBBHHII", w, h, 0, 0, 1, 32, len(png_data), data_offset
        )
        data_offset += len(png_data)

    with open(path, "wb") as f:
        f.write(header)
        f.write(entries)
        for png_data in png_data_list:
            f.write(png_data)


if __name__ == "__main__":
    main()

