@echo off
rem Builds dist\MusicJAMmer\MusicJAMmer.exe. Run from anywhere:  packaging\build_windows.bat
setlocal
cd /d "%~dp0.."
set PY=.venv\Scripts\python.exe
%PY% packaging\MusicJAMmer.py --selftest || goto :error
%PY% -m pip install -q pyinstaller pillow || goto :error
%PY% packaging\make_icon.py || goto :error
%PY% -m PyInstaller --noconfirm --clean --windowed --name MusicJAMmer --icon "%CD%\packaging\icon.png" --specpath build --workpath build --distpath dist "%CD%\packaging\MusicJAMmer.py" || goto :error
echo Built dist\MusicJAMmer\MusicJAMmer.exe
exit /b 0
:error
echo Build failed.
exit /b 1
