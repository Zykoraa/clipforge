"""Compile ClipForge into a standalone Windows executable bundle (dist/ClipForge/ClipForge.exe)."""

from __future__ import annotations

import compileall
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORK_DIR = Path(os.environ.get("CLIPFORGE_BUILD_DIR", str(ROOT / "build" / "pyinstaller")))
DIST_DIR = ROOT / "dist"
SPEC_DIR = WORK_DIR / "spec"


def main() -> None:
    print("[1/2] Byte-compiling all ClipForge modules...", flush=True)
    ok = compileall.compile_dir(str(ROOT / "clipforge"), quiet=1, force=True)
    if not ok:
        raise SystemExit("Byte-compilation failed.")

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    SPEC_DIR.mkdir(parents=True, exist_ok=True)

    pyinstaller = ROOT / ".venv" / "Scripts" / "pyinstaller.exe"
    cmd = [
        str(pyinstaller),
        "--onedir",
        "--name",
        "ClipForge",
        "--noconfirm",
        "--clean",
        "--workpath",
        str(WORK_DIR),
        "--specpath",
        str(SPEC_DIR),
        "--distpath",
        str(DIST_DIR),
        "--add-data",
        f"{ROOT / 'clipforge' / 'static'};clipforge\\static",
        "--collect-all",
        "faster_whisper",
        "--collect-all",
        "ctranslate2",
        "--collect-all",
        "onnxruntime",
        "--collect-all",
        "tokenizers",
        "--collect-all",
        "av",
        "--collect-all",
        "mcp",
        "--hidden-import",
        "uvicorn.logging",
        "--hidden-import",
        "uvicorn.loops.auto",
        "--hidden-import",
        "uvicorn.protocols.http.auto",
        "--hidden-import",
        "uvicorn.protocols.http.h11_impl",
        "--hidden-import",
        "uvicorn.protocols.http.httptools_impl",
        "--hidden-import",
        "uvicorn.protocols.websockets.auto",
        "--hidden-import",
        "uvicorn.protocols.websockets.websockets_impl",
        "--hidden-import",
        "uvicorn.lifespan.on",
        "--hidden-import",
        "websockets.sync.client",
        "--hidden-import",
        "clipforge.web_server",
        "--hidden-import",
        "clipforge.mcp_server",
        str(ROOT / "main.py"),
    ]
    print("[2/2] Compiling standalone ClipForge.exe with PyInstaller...", flush=True)
    env = {**os.environ, "TMP": str(WORK_DIR), "TEMP": str(WORK_DIR)}
    res = subprocess.run(cmd, cwd=str(ROOT), env=env)
    if res.returncode != 0:
        raise SystemExit(res.returncode)

    exe = DIST_DIR / "ClipForge" / "ClipForge.exe"
    if not exe.exists():
        raise SystemExit(f"Expected compiled binary not found: {exe}")
    print(f"SUCCESS: Compiled {exe} ({exe.stat().st_size / (1024*1024):.2f} MB)", flush=True)


if __name__ == "__main__":
    main()
