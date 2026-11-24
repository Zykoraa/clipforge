"""Cross-platform Face Detection & Feathered Paste-Back Worker (runs in ComfyUI venv with OpenCV + Pillow)."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

os.environ.setdefault("PYTHONUTF8", "1")


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax1, ay1, aw, ah = a
    bx1, by1, bw, bh = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax1 + aw, bx1 + bw), min(ay1 + ah, by1 + bh)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    union = aw * ah + bw * bh - inter
    return inter / max(1, union)


def _detect_faces(image_path: Path, crops_dir: Path, max_faces: int = 4, crop_size: int = 512) -> dict[str, Any]:
    import cv2
    from PIL import Image

    img_bgr = cv2.imread(str(image_path))
    if img_bgr is None:
        raise RuntimeError(f"Could not read image: {image_path}")
    h, w = img_bgr.shape[:2]
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)

    cascade_dir = Path(cv2.data.haarcascades)
    detectors = [
        cascade_dir / "haarcascade_frontalface_default.xml",
        cascade_dir / "haarcascade_frontalface_alt2.xml",
        cascade_dir / "haarcascade_profileface.xml",
    ]

    raw_boxes: list[tuple[int, int, int, int]] = []
    min_face = max(24, int(min(w, h) * 0.04))
    for det_path in detectors:
        if not det_path.exists():
            continue
        clf = cv2.CascadeClassifier(str(det_path))
        found = clf.detectMultiScale(
            gray,
            scaleFactor=1.12,
            minNeighbors=4,
            minSize=(min_face, min_face),
        )
        if len(found) > 0:
            for fx, fy, fw, fh in found:
                raw_boxes.append((int(fx), int(fy), int(fw), int(fh)))

    # NMS deduplication sorted largest-first
    raw_boxes.sort(key=lambda b: b[2] * b[3], reverse=True)
    kept: list[tuple[int, int, int, int]] = []
    for box in raw_boxes:
        if all(_iou(box, prev) < 0.35 for prev in kept):
            kept.append(box)
        if len(kept) >= max_faces:
            break

    pil_img = Image.open(image_path).convert("RGB")
    crops_dir.mkdir(parents=True, exist_ok=True)
    faces_out: list[dict[str, Any]] = []

    for idx, (fx, fy, fw, fh) in enumerate(kept):
        cx = fx + fw / 2.0
        cy = fy + fh / 2.0
        side = int(round(max(fw, fh) * 2.25))
        side = max(128, min(side, min(w, h)))
        x1 = int(round(cx - side / 2.0))
        y1 = int(round(cy - side / 2.0))
        x1 = max(0, min(w - side, x1))
        y1 = max(0, min(h - side, y1))
        x2 = min(w, x1 + side)
        y2 = min(h, y1 + side)

        crop = pil_img.crop((x1, y1, x2, y2)).resize((crop_size, crop_size), Image.Resampling.LANCZOS)
        crop_path = (crops_dir / f"face_{idx}.png").resolve()
        crop.save(crop_path)
        faces_out.append(
            {
                "index": idx,
                "bbox": [fx, fy, fw, fh],
                "crop_box": [x1, y1, x2, y2],
                "crop_path": str(crop_path),
            }
        )

    return {"width": w, "height": h, "faces": faces_out}


def _paste_faces(base_image: Path, patches_json: Path, out_image: Path) -> dict[str, Any]:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter

    base = Image.open(base_image).convert("RGB")
    patches = json.loads(patches_json.read_text(encoding="utf-8"))

    for item in patches:
        x1, y1, x2, y2 = [int(v) for v in item["crop_box"]]
        ref_path = Path(item["refined_path"])
        if not ref_path.exists():
            continue
        cw, ch = max(1, x2 - x1), max(1, y2 - y1)
        refined = Image.open(ref_path).convert("RGB").resize((cw, ch), Image.Resampling.LANCZOS)

        # Elliptical feathered mask so boundaries blend seamlessly with zero hard rectangle edges
        mask = Image.new("L", (cw, ch), 0)
        draw = ImageDraw.Draw(mask)
        pad_x = max(4, int(cw * 0.12))
        pad_y = max(4, int(ch * 0.12))
        draw.ellipse((pad_x, pad_y, cw - pad_x, ch - pad_y), fill=255)
        blur_r = max(4, int(min(cw, ch) * 0.10))
        mask = mask.filter(ImageFilter.GaussianBlur(radius=blur_r))

        # Slight color/luma consistency clamp against original crop edge
        orig_arr = np.asarray(base.crop((x1, y1, x2, y2)), dtype=np.float32)
        ref_arr = np.asarray(refined, dtype=np.float32)
        alpha = (np.asarray(mask, dtype=np.float32) / 255.0)[..., None]
        blended = np.clip(ref_arr * alpha + orig_arr * (1.0 - alpha), 0, 255).astype(np.uint8)
        base.paste(Image.fromarray(blended, mode="RGB"), (x1, y1))

    out_image.parent.mkdir(parents=True, exist_ok=True)
    base.save(out_image)
    return {"out_image": str(out_image.resolve()), "width": base.width, "height": base.height, "count": len(patches)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["detect", "paste"], required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--crops-dir", default="")
    parser.add_argument("--max-faces", type=int, default=4)
    parser.add_argument("--crop-size", type=int, default=512)
    parser.add_argument("--patches-json", default="")
    parser.add_argument("--out-image", default="")
    args = parser.parse_args()

    if args.mode == "detect":
        res = _detect_faces(Path(args.image), Path(args.crops_dir), max_faces=args.max_faces, crop_size=args.crop_size)
    else:
        res = _paste_faces(Path(args.image), Path(args.patches_json), Path(args.out_image))

    print("RESULT_JSON:" + json.dumps(res), flush=True)


if __name__ == "__main__":
    main()
