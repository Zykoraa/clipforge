"""Compile ClipForge into a standalone native executable bundle (Windows, Linux, or macOS).

Outputs:
  - Windows: dist/ClipForge/ClipForge.exe
  - Linux:   dist/ClipForge/ClipForge
  - macOS:   dist/ClipForge/ClipForge

Pass `--archive` to also package a release archive (`.zip` on Windows, `.tar.gz` on Linux/macOS).
"""

from __future__ import annotations

import argparse
import compileall
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORK_DIR = Path(os.environ.get("CLIPFORGE_BUILD_DIR", str(ROOT / "build" / "pyinstaller")))
DIST_DIR = Path(os.environ.get("CLIPFORGE_DIST_DIR", str(ROOT / "dist")))
SPEC_DIR = WORK_DIR / "spec"


def _platform_tag() -> str:
    if sys.platform == "win32":
        os_name = "windows"
    elif sys.platform == "darwin":
        os_name = "macos"
    else:
        os_name = "linux"
    arch = platform.machine().lower()
    arch_map = {"amd64": "x86_64", "x64": "x86_64", "arm64": "aarch64"}
    arch = arch_map.get(arch, arch or "unknown")
    return f"{os_name}-{arch}"


def _resolve_pyinstaller_cmd() -> list[str]:
    is_win = sys.platform == "win32"
    bin_dir = "Scripts" if is_win else "bin"
    exe_name = "pyinstaller.exe" if is_win else "pyinstaller"

    candidates = [
        Path(sys.executable).resolve().parent / exe_name,
        ROOT / ".venv" / bin_dir / exe_name,
    ]
    for cand in candidates:
        if cand.exists():
            return [str(cand)]

    which_pi = shutil.which("pyinstaller")
    if which_pi:
        return [which_pi]

    return [sys.executable, "-m", "PyInstaller"]


def _package_archive(bundle_dir: Path, tag: str) -> Path:
    if sys.platform == "win32":
        archive_path = DIST_DIR / f"ClipForge-{tag}.zip"
        if archive_path.exists():
            archive_path.unlink()
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(bundle_dir.rglob("*")):
                if p.is_file():
                    zf.write(p, arcname=p.relative_to(DIST_DIR))
        return archive_path

    archive_path = DIST_DIR / f"ClipForge-{tag}.tar.gz"
    if archive_path.exists():
        archive_path.unlink()
    with tarfile.open(archive_path, "w:gz") as tf:
        tf.add(bundle_dir, arcname=bundle_dir.name)
    return archive_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build standalone ClipForge bundle for the current OS.")
    parser.add_argument(
        "--archive",
        action="store_true",
        help="Also package dist/ClipForge into a platform release archive (.zip / .tar.gz).",
    )
    parser.add_argument(
        "--build-native",
        action="store_true",
        help="Compile clipforge-native (Rust egui/wgpu desktop app) before packaging.",
    )
    args = parser.parse_args()

    is_win = sys.platform == "win32"
    exe_name = "ClipForge.exe" if is_win else "ClipForge"
    native_name = "ClipForgeNative.exe" if is_win else "ClipForgeNative"

    # Preserve an existing prebuilt ClipForgeNative binary if PyInstaller --clean wipes dist/ClipForge
    native_backup: Path | None = None
    existing_native = DIST_DIR / "ClipForge" / native_name
    if existing_native.exists():
        WORK_DIR.mkdir(parents=True, exist_ok=True)
        native_backup = WORK_DIR / native_name
        shutil.copy2(existing_native, native_backup)

    print("[1/2] Byte-compiling all ClipForge modules...", flush=True)
    ok = compileall.compile_dir(str(ROOT / "clipforge"), quiet=1, force=True)
    if not ok:
        raise SystemExit("Byte-compilation failed.")

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    SPEC_DIR.mkdir(parents=True, exist_ok=True)

    pyinstaller_cmd = _resolve_pyinstaller_cmd()
    hidden_imports = [
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.loops.asyncio",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.http.httptools_impl",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.protocols.websockets.websockets_impl",
        "uvicorn.lifespan.on",
        "websockets.sync.client",
        "clipforge.web_server",
        "clipforge.mcp_server",
        "clipforge.platform_utils",
        "clipforge.cast",
        "clipforge.civitai",
        "clipforge.director",
        "clipforge.generator",
        "clipforge.renderer",
        "clipforge.sfx",
        "clipforge.subtitles",
        "clipforge.voice",
    ]
    if not is_win:
        hidden_imports.append("uvicorn.loops.uvloop")

    cmd = [
        *pyinstaller_cmd,
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
        f"{ROOT / 'clipforge' / 'static'}{os.pathsep}clipforge/static",
        "--add-data",
        f"{ROOT / 'clipforge' / 'voice_worker.py'}{os.pathsep}clipforge",
        "--add-data",
        f"{ROOT / 'clipforge' / 'face_worker.py'}{os.pathsep}clipforge",
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
    ]
    for hi in hidden_imports:
        cmd.extend(["--hidden-import", hi])
    cmd.append(str(ROOT / "main.py"))

    print(f"[2/2] Compiling standalone {exe_name} with PyInstaller ({_platform_tag()})...", flush=True)
    env = {
        **os.environ,
        "TMP": str(WORK_DIR),
        "TEMP": str(WORK_DIR),
        "TMPDIR": str(WORK_DIR),
    }
    res = subprocess.run(cmd, cwd=str(ROOT), env=env)
    if res.returncode != 0:
        raise SystemExit(res.returncode)

    bundle_dir = DIST_DIR / "ClipForge"
    exe = bundle_dir / exe_name
    if not exe.exists():
        raise SystemExit(f"Expected compiled binary not found: {exe}")
    print(f"SUCCESS: Compiled {exe} ({exe.stat().st_size / (1024*1024):.2f} MB)", flush=True)

    # Optionally build or bundle the true Native Rust egui/wgpu desktop app right alongside ClipForge(.exe)
    native_dir = ROOT / "clipforge-native"
    if args.build_native and native_dir.is_dir():
        print(f"[2b] Building native Rust desktop UI ({native_name})...", flush=True)
        r_cargo = subprocess.run(["cargo", "build", "--release"], cwd=str(native_dir))
        if r_cargo.returncode != 0:
            raise SystemExit(r_cargo.returncode)

    native_candidates: list[Path] = []
    cargo_target = os.environ.get("CARGO_TARGET_DIR", "").strip()
    if cargo_target:
        native_candidates.append(Path(cargo_target) / "release" / native_name)
    native_candidates.append(native_dir / "target" / "release" / native_name)
    if native_backup is not None:
        native_candidates.append(native_backup)

    for cand in native_candidates:
        if cand.exists() and cand.is_file():
            dst_native = bundle_dir / native_name
            shutil.copy2(cand, dst_native)
            print(
                f"BUNDLED NATIVE UI: {dst_native} ({dst_native.stat().st_size / (1024*1024):.2f} MB)",
                flush=True,
            )
            break

    if args.archive:
        tag = _platform_tag()
        archive = _package_archive(bundle_dir, tag)
        print(f"ARCHIVED: {archive} ({archive.stat().st_size / (1024*1024):.2f} MB)", flush=True)


if __name__ == "__main__":
    main()
