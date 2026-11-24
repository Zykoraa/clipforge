"""Saved Cast / Friend Profiles Manager (photos + optional voice samples + @Name prompt resolution)."""

from __future__ import annotations

import json
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from filelock import FileLock

from .media import IMAGE_EXTENSIONS

VOICE_SOURCE_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac", ".mp4", ".mov", ".webm", ".mkv"}
_NAME_CLEAN_RE = re.compile(r"[^A-Za-z0-9 _-]+")
_MENTION_RE = re.compile(r"@([A-Za-z0-9_-]{2,32})")


class CastManager:
    """Persists named friend profiles (reference photo + optional voice clip) inside workspace/cast/."""

    def __init__(self, workspace_dir: Path) -> None:
        self.workspace_dir = workspace_dir.resolve()
        self.cast_dir = self.workspace_dir / "cast"
        self.photos_dir = self.cast_dir / "photos"
        self.voices_dir = self.cast_dir / "voices"
        self.cast_file = self.cast_dir / "cast.json"
        self.lock_file = self.cast_dir / "cast.json.lock"
        self.cast_dir.mkdir(parents=True, exist_ok=True)
        self.photos_dir.mkdir(parents=True, exist_ok=True)
        self.voices_dir.mkdir(parents=True, exist_ok=True)
        self._lock = FileLock(str(self.lock_file), timeout=15)

    def _read_unlocked(self) -> list[dict[str, Any]]:
        if not self.cast_file.exists():
            return []
        try:
            data = json.loads(self.cast_file.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception:
            pass
        return []

    def _write_unlocked(self, members: list[dict[str, Any]]) -> None:
        tmp = self.cast_file.with_name(f"cast.{uuid.uuid4().hex[:8]}.tmp")
        tmp.write_text(json.dumps(members, indent=2), encoding="utf-8")
        tmp.replace(self.cast_file)

    def _decorate(self, m: dict[str, Any]) -> dict[str, Any]:
        cid = m["id"]
        has_voice = bool(m.get("voice_path") and Path(m["voice_path"]).exists())
        return {
            **m,
            "handle": "@" + re.sub(r"\s+", "", m["name"]),
            "photo_url": f"/api/cast/{cid}/photo",
            "has_voice": has_voice,
            "voice_url": f"/api/cast/{cid}/voice" if has_voice else None,
        }

    def list_members(self) -> list[dict[str, Any]]:
        with self._lock:
            members = self._read_unlocked()
        return [self._decorate(m) for m in members if Path(m.get("photo_path", "")).exists()]

    def get_member(self, cast_id: str) -> dict[str, Any] | None:
        with self._lock:
            for m in self._read_unlocked():
                if m.get("id") == cast_id:
                    return self._decorate(m)
        return None

    def _extract_clean_voice_wav(self, raw_src: Path, dest_wav: Path) -> None:
        """Convert any uploaded voice memo or video clip into a crisp <=12s 24kHz mono WAV for F5-TTS."""
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-i",
            str(raw_src),
            "-vn",
            "-t",
            "12.0",
            "-ar",
            "24000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(dest_wav),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode != 0 or not dest_wav.exists() or dest_wav.stat().st_size < 2048:
            raise RuntimeError(f"Could not extract voice audio from '{raw_src.name}': {(res.stderr or '')[-300:]}")

    def save_member(
        self,
        name: str,
        photo_bytes: bytes | None = None,
        photo_filename: str | None = None,
        photo_path: str | None = None,
        voice_bytes: bytes | None = None,
        voice_filename: str | None = None,
        voice_path: str | None = None,
        voice_ref_text: str = "",
    ) -> dict[str, Any]:
        clean_name = _NAME_CLEAN_RE.sub("", (name or "").strip()).strip()[:32]
        if not clean_name:
            raise ValueError("Friend / cast name cannot be empty.")

        cast_id = f"cast_{uuid.uuid4().hex[:8]}"

        # Save reference photo cleanly inside workspace/cast/photos
        if photo_bytes is not None:
            ext = Path(photo_filename or "photo.png").suffix.lower() or ".png"
            if ext not in IMAGE_EXTENSIONS:
                raise ValueError(f"Unsupported photo extension '{ext}'.")
            dest_photo = (self.photos_dir / f"{cast_id}{ext}").resolve()
            dest_photo.write_bytes(photo_bytes)
        elif photo_path:
            src_p = Path(photo_path).expanduser().resolve()
            if not src_p.exists() or not src_p.is_file():
                raise FileNotFoundError(f"Photo not found: {src_p}")
            ext = src_p.suffix.lower()
            if ext not in IMAGE_EXTENSIONS:
                raise ValueError(f"Unsupported photo extension '{ext}'.")
            dest_photo = (self.photos_dir / f"{cast_id}{ext}").resolve()
            dest_photo.write_bytes(src_p.read_bytes())
        else:
            raise ValueError("A reference photo is required to create a cast profile.")

        # Optional voice sample -> normalized 24kHz mono WAV
        dest_voice: Path | None = None
        if voice_bytes is not None and len(voice_bytes) > 0:
            vext = Path(voice_filename or "voice.wav").suffix.lower() or ".wav"
            if vext not in VOICE_SOURCE_EXTENSIONS:
                raise ValueError(f"Unsupported voice file extension '{vext}'.")
            raw_tmp = self.voices_dir / f"{cast_id}_raw{vext}"
            dest_voice = (self.voices_dir / f"{cast_id}.wav").resolve()
            try:
                raw_tmp.write_bytes(voice_bytes)
                self._extract_clean_voice_wav(raw_tmp, dest_voice)
            finally:
                raw_tmp.unlink(missing_ok=True)
        elif voice_path:
            src_v = Path(voice_path).expanduser().resolve()
            if not src_v.exists() or not src_v.is_file():
                raise FileNotFoundError(f"Voice file not found: {src_v}")
            dest_voice = (self.voices_dir / f"{cast_id}.wav").resolve()
            self._extract_clean_voice_wav(src_v, dest_voice)

        entry = {
            "id": cast_id,
            "name": clean_name,
            "photo_path": str(dest_photo),
            "voice_path": str(dest_voice) if dest_voice else None,
            "voice_ref_text": (voice_ref_text or "").strip()[:300],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            members = self._read_unlocked()
            # Replace existing profile with same case-insensitive name cleanly
            members = [m for m in members if m.get("name", "").lower() != clean_name.lower()]
            members.insert(0, entry)
            self._write_unlocked(members)
        return self._decorate(entry)

    def attach_voice(
        self,
        cast_id: str,
        voice_bytes: bytes,
        voice_filename: str,
        voice_ref_text: str = "",
    ) -> dict[str, Any]:
        vext = Path(voice_filename or "voice.wav").suffix.lower() or ".wav"
        if vext not in VOICE_SOURCE_EXTENSIONS:
            raise ValueError(f"Unsupported voice file extension '{vext}'.")
        raw_tmp = self.voices_dir / f"{cast_id}_raw{vext}"
        dest_voice = (self.voices_dir / f"{cast_id}.wav").resolve()
        try:
            raw_tmp.write_bytes(voice_bytes)
            self._extract_clean_voice_wav(raw_tmp, dest_voice)
        finally:
            raw_tmp.unlink(missing_ok=True)

        with self._lock:
            members = self._read_unlocked()
            target = next((m for m in members if m.get("id") == cast_id), None)
            if not target:
                raise ValueError(f"Cast member '{cast_id}' not found.")
            target["voice_path"] = str(dest_voice)
            if voice_ref_text.strip():
                target["voice_ref_text"] = voice_ref_text.strip()[:300]
            self._write_unlocked(members)
            return self._decorate(target)

    def delete_member(self, cast_id: str) -> bool:
        removed = None
        with self._lock:
            members = self._read_unlocked()
            kept: list[dict[str, Any]] = []
            for m in members:
                if m.get("id") == cast_id:
                    removed = m
                else:
                    kept.append(m)
            self._write_unlocked(kept)
        if removed:
            for key in ("photo_path", "voice_path"):
                fp = removed.get(key)
                if fp:
                    try:
                        Path(fp).unlink(missing_ok=True)
                    except Exception:
                        pass
            return True
        return False

    def resolve_prompt_mentions(
        self,
        prompt: str,
        image_path: str | None = None,
        image_path_2: str | None = None,
    ) -> tuple[str, str | None, str | None, list[dict[str, Any]]]:
        """Resolve `@Name` tokens in prompt against saved Cast profiles and auto-attach their photos."""
        members = self.list_members()
        if not members or "@" not in (prompt or ""):
            return prompt, image_path, image_path_2, []

        by_key: dict[str, dict[str, Any]] = {}
        for m in members:
            by_key[re.sub(r"\s+", "", m["name"]).lower()] = m
            by_key[m["name"].lower()] = m

        matched: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for tok in _MENTION_RE.findall(prompt):
            m = by_key.get(tok.lower())
            if m and m["id"] not in seen_ids:
                seen_ids.add(m["id"])
                matched.append(m)

        if not matched:
            return prompt, image_path, image_path_2, []

        out_img1 = image_path
        out_img2 = image_path_2
        slot_for_member: dict[str, int] = {}

        for m in matched:
            if not out_img1:
                out_img1 = m["photo_path"]
                slot_for_member[m["id"]] = 1
            elif out_img1 == m["photo_path"]:
                slot_for_member[m["id"]] = 1
            elif not out_img2:
                out_img2 = m["photo_path"]
                slot_for_member[m["id"]] = 2
            elif out_img2 == m["photo_path"]:
                slot_for_member[m["id"]] = 2

        multi = bool(out_img1 and out_img2)

        def _repl(match: re.Match[str]) -> str:
            tok = match.group(1).lower()
            m = by_key.get(tok)
            if not m:
                return match.group(0)
            slot = slot_for_member.get(m["id"], 1)
            if multi:
                return f"the person from image {slot}"
            return "this person"

        resolved_prompt = _MENTION_RE.sub(_repl, prompt)
        return resolved_prompt, out_img1, out_img2, matched
