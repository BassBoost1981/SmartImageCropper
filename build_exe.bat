@echo off
echo === Building Smart Image Cropper EXE ===
pyinstaller build\build.spec --clean --noconfirm
echo === Build complete ===
pause
