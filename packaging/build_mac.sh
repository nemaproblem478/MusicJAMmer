#!/bin/sh
# Builds dist/MusicJAMmer.app. Run from the project root:  sh packaging/build_mac.sh
set -e
cd "$(dirname "$0")/.."
PY=.venv/bin/python
$PY -m pip install -q pyinstaller
$PY packaging/make_icon.py
$PY -m PyInstaller --noconfirm --clean --windowed \
    --name MusicJAMmer \
    --icon "$PWD/packaging/icon.icns" \
    --osx-bundle-identifier com.nemaproblem478.musicjammer \
    --specpath build \
    --workpath build \
    --distpath dist \
    "$PWD/packaging/MusicJAMmer.py"
dist/MusicJAMmer.app/Contents/MacOS/MusicJAMmer --selftest
echo "Built dist/MusicJAMmer.app"
