@echo off
title ClipForge AI Video & Meme Studio
cd /d "%~dp0"
if exist "dist\ClipForge\ClipForge.exe" (
    "dist\ClipForge\ClipForge.exe" --port 8765
) else (
    ".venv\Scripts\python.exe" main.py --port 8765
)
pause
