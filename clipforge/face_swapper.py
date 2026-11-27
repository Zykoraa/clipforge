"""Pure-ONNX Offline 1-2 Friend Face Lock / Face Swapper (Zero C++ Build Dependencies).

Uses standard InsightFace ONNX models directly via `onnxruntime` + `cv2` + `numpy`:
  - `models/insightface/det_10g.onnx`    (SCRFD 10G 5-point landmark face detector)
  - `models/insightface/w600k_r50.onnx`  (ArcFace ResNet50 512-D identity embedder)
  - `models/insightface/inswapper_128.onnx` (128x128 face swapper with embedded 512x512 emap)
"""

from __future__ import annotations

import struct
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

# Standard 112x112 ArcFace 5-point reference landmarks (left_eye, right_eye, nose, left_mouth, right_mouth)
_ARCFACE_DST_112 = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float32,
)


@dataclass
class DetectedFace:
    bbox: np.ndarray  # [x1, y1, x2, y2]
    score: float
    kps: np.ndarray  # (5, 2) float32 landmarks

    @property
    def area(self) -> float:
        return float(max(0.0, self.bbox[2] - self.bbox[0]) * max(0.0, self.bbox[3] - self.bbox[1]))

    @property
    def center_x(self) -> float:
        return float((self.bbox[0] + self.bbox[2]) * 0.5)


# ---------------------------------------------------------------------------
# Minimal Pure-Python ONNX Protobuf Parser for `inswapper_128.onnx` emap (512x512)
# ---------------------------------------------------------------------------
def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    val = 0
    shift = 0
    n = len(buf)
    while pos < n:
        b = buf[pos]
        pos += 1
        val |= (b & 0x7F) << shift
        if not (b & 0x80):
            return val, pos
        shift += 7
    raise ValueError("Truncated varint in ONNX protobuf")


def _skip_proto_field(buf: bytes, pos: int, wire_type: int) -> int:
    if wire_type == 0:
        _, pos = _read_varint(buf, pos)
        return pos
    if wire_type == 1:
        return pos + 8
    if wire_type == 2:
        length, pos = _read_varint(buf, pos)
        return pos + length
    if wire_type == 5:
        return pos + 4
    raise ValueError(f"Unsupported protobuf wire type {wire_type}")


def _parse_tensor_proto_if_512x512(buf: bytes) -> np.ndarray | None:
    """Parse an ONNX TensorProto message; return float32 (512, 512) matrix if dims == [512, 512]."""
    pos = 0
    end = len(buf)
    dims: list[int] = []
    data_type = 0
    raw_data: bytes | None = None
    float_data: list[float] = []

    while pos < end:
        tag, pos = _read_varint(buf, pos)
        field_num = tag >> 3
        wire_type = tag & 0x07
        if field_num == 1:  # dims (repeated int64, packed or unpacked)
            if wire_type == 0:
                v, pos = _read_varint(buf, pos)
                dims.append(v)
            elif wire_type == 2:
                ln, pos = _read_varint(buf, pos)
                sub_end = pos + ln
                while pos < sub_end:
                    v, pos = _read_varint(buf, pos)
                    dims.append(v)
            else:
                pos = _skip_proto_field(buf, pos, wire_type)
        elif field_num == 2 and wire_type == 0:  # data_type (1 = FLOAT)
            data_type, pos = _read_varint(buf, pos)
        elif field_num == 4:  # float_data
            if wire_type == 5:
                float_data.append(struct.unpack_from("<f", buf, pos)[0])
                pos += 4
            elif wire_type == 2:
                ln, pos = _read_varint(buf, pos)
                if dims == [512, 512] and ln == 512 * 512 * 4:
                    return np.frombuffer(buf, dtype="<f4", count=512 * 512, offset=pos).reshape(512, 512).copy()
                pos += ln
            else:
                pos = _skip_proto_field(buf, pos, wire_type)
        elif field_num == 9 and wire_type == 2:  # raw_data
            ln, pos = _read_varint(buf, pos)
            if dims == [512, 512] and data_type in (0, 1) and ln == 512 * 512 * 4:
                raw_data = buf[pos : pos + ln]
            pos += ln
        else:
            pos = _skip_proto_field(buf, pos, wire_type)

    if dims == [512, 512] and data_type in (0, 1):
        if raw_data is not None:
            return np.frombuffer(raw_data, dtype="<f4").reshape(512, 512).copy()
        if len(float_data) == 512 * 512:
            return np.asarray(float_data, dtype=np.float32).reshape(512, 512)
    return None


def extract_inswapper_emap(onnx_path: Path) -> np.ndarray:
    """Extract the (512, 512) float32 emap initializer from inswapper_128.onnx without needing the `onnx` library."""
    data = onnx_path.read_bytes()
    pos = 0
    end = len(data)
    graph_slice: tuple[int, int] | None = None

    # ModelProto: field 7 is GraphProto
    while pos < end:
        tag, pos = _read_varint(data, pos)
        field_num = tag >> 3
        wire_type = tag & 0x07
        if field_num == 7 and wire_type == 2:
            ln, pos = _read_varint(data, pos)
            graph_slice = (pos, pos + ln)
            break
        pos = _skip_proto_field(data, pos, wire_type)

    if graph_slice is None:
        raise RuntimeError(f"Invalid ONNX model (no GraphProto found): {onnx_path}")

    # GraphProto: field 5 is repeated TensorProto `initializer`
    g_pos, g_end = graph_slice
    emap_last: np.ndarray | None = None
    while g_pos < g_end:
        tag, g_pos = _read_varint(data, g_pos)
        field_num = tag >> 3
        wire_type = tag & 0x07
        if field_num == 5 and wire_type == 2:
            ln, g_pos = _read_varint(data, g_pos)
            if ln >= 512 * 512 * 4:
                parsed = _parse_tensor_proto_if_512x512(data[g_pos : g_pos + ln])
                if parsed is not None:
                    emap_last = parsed
            g_pos += ln
        else:
            g_pos = _skip_proto_field(data, g_pos, wire_type)

    if emap_last is None:
        raise RuntimeError(f"Could not locate 512x512 emap initializer inside {onnx_path.name}")
    return emap_last


# ---------------------------------------------------------------------------
# Similarity Alignment & SCRFD / ArcFace / InSwapper Inference
# ---------------------------------------------------------------------------
def _estimate_norm_affine(kps: np.ndarray, image_size: int = 112) -> np.ndarray:
    import cv2

    dst = _ARCFACE_DST_112.copy()
    if image_size != 112:
        if image_size % 112 == 0:
            ratio = float(image_size) / 112.0
            diff_x = 0.0
        else:
            ratio = float(image_size) / 128.0
            diff_x = 8.0 * ratio
        dst[:, 0] = dst[:, 0] * ratio + diff_x
        dst[:, 1] = dst[:, 1] * ratio

    M, _ = cv2.estimateAffinePartial2D(kps.astype(np.float32), dst, method=cv2.LMEDS)
    if M is None:
        M, _ = cv2.estimateAffinePartial2D(kps.astype(np.float32), dst)
    if M is None:
        raise RuntimeError("Failed to compute facial similarity alignment matrix.")
    return M


def _nms(dets: np.ndarray, thresh: float = 0.4) -> list[int]:
    x1, y1, x2, y2, scores = dets[:, 0], dets[:, 1], dets[:, 2], dets[:, 3], dets[:, 4]
    areas = (x2 - x1 + 1.0) * (y2 - y1 + 1.0)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        i = int(order[0])
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        w = np.maximum(0.0, xx2 - xx1 + 1.0)
        h = np.maximum(0.0, yy2 - yy1 + 1.0)
        inter = w * h
        ovr = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)
        inds = np.where(ovr <= thresh)[0]
        order = order[inds + 1]
    return keep


def _make_ort_session(model_path: Path):
    import onnxruntime as ort

    avail = ort.get_available_providers()
    providers = [p for p in ("CUDAExecutionProvider", "DmlExecutionProvider", "CPUExecutionProvider") if p in avail]
    if not providers:
        providers = ["CPUExecutionProvider"]
    opts = ort.SessionOptions()
    opts.log_severity_level = 3
    return ort.InferenceSession(str(model_path), sess_options=opts, providers=providers)


class PureOnnxFaceSwapper:
    """Thread-safe cached pure-ONNX face detector + embedder + inswapper_128 engine."""

    def __init__(self, models_dir: Path) -> None:
        self.models_dir = models_dir
        self._lock = threading.Lock()
        self._det_sess = None
        self._rec_sess = None
        self._swap_sess = None
        self._emap: np.ndarray | None = None

    def _model_paths(self) -> tuple[Path, Path, Path]:
        det = self.models_dir / "det_10g.onnx"
        rec = self.models_dir / "w600k_r50.onnx"
        swap = self.models_dir / "inswapper_128.onnx"
        return det, rec, swap

    def is_ready(self) -> bool:
        return all(p.exists() and p.stat().st_size > 1024 * 1024 for p in self._model_paths())

    def _ensure_loaded(self) -> None:
        if self._det_sess is not None and self._rec_sess is not None and self._swap_sess is not None:
            return
        det_p, rec_p, swap_p = self._model_paths()
        missing = [p.name for p in (det_p, rec_p, swap_p) if not (p.exists() and p.stat().st_size > 1024 * 1024)]
        if missing:
            raise RuntimeError(
                f"Face Lock models missing ({', '.join(missing)}). "
                "Download 'Friend Face Lock (inswapper)' in Setup & Packs first."
            )
        self._det_sess = _make_ort_session(det_p)
        self._rec_sess = _make_ort_session(rec_p)
        self._swap_sess = _make_ort_session(swap_p)
        self._emap = extract_inswapper_emap(swap_p)

    def detect_faces(self, img_bgr: np.ndarray, det_thresh: float = 0.45, input_size: int = 640) -> list[DetectedFace]:
        import cv2

        self._ensure_loaded()
        assert self._det_sess is not None

        h, w = img_bgr.shape[:2]
        im_ratio = float(h) / max(1.0, float(w))
        if im_ratio > 1.0:
            new_h = input_size
            new_w = max(1, int(new_h / im_ratio))
        else:
            new_w = input_size
            new_h = max(1, int(new_w * im_ratio))
        det_scale = float(new_h) / max(1.0, float(h))
        resized = cv2.resize(img_bgr, (new_w, new_h))
        det_img = np.zeros((input_size, input_size, 3), dtype=np.uint8)
        det_img[:new_h, :new_w, :] = resized

        blob = cv2.dnn.blobFromImage(
            det_img,
            1.0 / 128.0,
            (input_size, input_size),
            (127.5, 127.5, 127.5),
            swapRB=True,
        )
        in_name = self._det_sess.get_inputs()[0].name
        outs = self._det_sess.run(None, {in_name: blob})

        # SCRFD det_10g outputs 9 tensors: 3 scores, 3 bboxes, 3 kps for strides [8, 16, 32] with 2 anchors/cell
        fmc = 3
        strides = [8, 16, 32]
        num_anchors = 2

        scores_list: list[np.ndarray] = []
        bboxes_list: list[np.ndarray] = []
        kpss_list: list[np.ndarray] = []

        for idx, stride in enumerate(strides):
            scores = outs[idx].reshape(-1)
            bbox_preds = outs[idx + fmc].reshape(-1, 4) * stride
            kps_preds = outs[idx + fmc * 2].reshape(-1, 10) * stride

            fh = input_size // stride
            fw = input_size // stride
            anchor_centers = np.stack(np.mgrid[:fh, :fw][::-1], axis=-1).astype(np.float32)
            anchor_centers = (anchor_centers * stride).reshape((-1, 2))
            anchor_centers = np.stack([anchor_centers] * num_anchors, axis=1).reshape((-1, 2))

            pos_inds = np.where(scores >= det_thresh)[0]
            if pos_inds.size == 0:
                continue

            ac = anchor_centers[pos_inds]
            bp = bbox_preds[pos_inds]
            x1 = ac[:, 0] - bp[:, 0]
            y1 = ac[:, 1] - bp[:, 1]
            x2 = ac[:, 0] + bp[:, 2]
            y2 = ac[:, 1] + bp[:, 3]
            bboxes = np.stack([x1, y1, x2, y2], axis=-1)

            kp = kps_preds[pos_inds].reshape(-1, 5, 2)
            kps = kp + ac[:, None, :]

            scores_list.append(scores[pos_inds])
            bboxes_list.append(bboxes)
            kpss_list.append(kps)

        if not scores_list:
            return []

        all_scores = np.concatenate(scores_list)
        all_bboxes = np.concatenate(bboxes_list, axis=0) / det_scale
        all_kps = np.concatenate(kpss_list, axis=0) / det_scale

        order = all_scores.argsort()[::-1]
        pre_det = np.hstack((all_bboxes, all_scores[:, None])).astype(np.float32)[order]
        all_kps = all_kps[order]
        keep = _nms(pre_det, thresh=0.4)

        faces: list[DetectedFace] = []
        for idx in keep:
            faces.append(
                DetectedFace(
                    bbox=pre_det[idx, :4].copy(),
                    score=float(pre_det[idx, 4]),
                    kps=all_kps[idx].copy(),
                )
            )
        return faces

    def get_embedding(self, img_bgr: np.ndarray, face: DetectedFace) -> np.ndarray:
        import cv2

        self._ensure_loaded()
        assert self._rec_sess is not None
        M = _estimate_norm_affine(face.kps, image_size=112)
        aligned = cv2.warpAffine(img_bgr, M, (112, 112), borderValue=0.0)
        blob = cv2.dnn.blobFromImage(
            aligned,
            1.0 / 127.5,
            (112, 112),
            (127.5, 127.5, 127.5),
            swapRB=True,
        )
        in_name = self._rec_sess.get_inputs()[0].name
        emb = self._rec_sess.run(None, {in_name: blob})[0].reshape(-1).astype(np.float32)
        norm = float(np.linalg.norm(emb))
        if norm > 1e-6:
            emb = emb / norm
        return emb

    def swap_single_face(self, target_bgr: np.ndarray, target_face: DetectedFace, source_emb: np.ndarray) -> np.ndarray:
        import cv2

        self._ensure_loaded()
        assert self._swap_sess is not None and self._emap is not None

        M = _estimate_norm_affine(target_face.kps, image_size=128)
        aimg = cv2.warpAffine(target_bgr, M, (128, 128), borderValue=0.0)

        blob = cv2.dnn.blobFromImage(aimg, 1.0 / 255.0, (128, 128), (0.0, 0.0, 0.0), swapRB=True)
        latent = source_emb.reshape(1, -1).astype(np.float32)
        latent = np.dot(latent, self._emap)
        l_norm = float(np.linalg.norm(latent))
        if l_norm > 1e-6:
            latent = latent / l_norm

        inputs = self._swap_sess.get_inputs()
        feed = {inputs[0].name: blob, inputs[1].name: latent}
        pred = self._swap_sess.run(None, feed)[0]
        img_fake = pred.transpose((0, 2, 3, 1))[0]
        bgr_fake = np.clip(255.0 * img_fake, 0, 255).astype(np.uint8)[:, :, ::-1]

        # Subtle LAB luminance/chroma match inside the face oval to harmonize scene lighting
        try:
            src_lab = cv2.cvtColor(bgr_fake, cv2.COLOR_BGR2LAB).astype(np.float32)
            ref_lab = cv2.cvtColor(aimg, cv2.COLOR_BGR2LAB).astype(np.float32)
            center_slice = (slice(24, 108), slice(24, 108))
            for ch, strength in ((0, 0.45), (1, 0.35), (2, 0.35)):
                s_mean, s_std = float(src_lab[center_slice + (ch,)].mean()), float(src_lab[center_slice + (ch,)].std()) + 1e-5
                r_mean, r_std = float(ref_lab[center_slice + (ch,)].mean()), float(ref_lab[center_slice + (ch,)].std()) + 1e-5
                matched = (src_lab[:, :, ch] - s_mean) * (r_std / s_std) + r_mean
                src_lab[:, :, ch] = src_lab[:, :, ch] * (1.0 - strength) + matched * strength
            bgr_fake = cv2.cvtColor(np.clip(src_lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)
        except Exception:
            pass

        # Soft elliptical mask inside 128x128 face space -> warp back smoothly into full-res target
        mask = np.zeros((128, 128), dtype=np.float32)
        cv2.ellipse(mask, (64, 66), (50, 56), 0, 0, 360, 1.0, -1)
        mask = cv2.GaussianBlur(mask, (21, 21), 8.0)

        IM = cv2.invertAffineTransform(M)
        th, tw = target_bgr.shape[:2]
        warped_fake = cv2.warpAffine(bgr_fake, IM, (tw, th), borderValue=0.0)
        warped_mask = cv2.warpAffine(mask, IM, (tw, th), borderValue=0.0)
        warped_mask = np.clip(warped_mask, 0.0, 1.0)[:, :, None]

        out = warped_mask * warped_fake.astype(np.float32) + (1.0 - warped_mask) * target_bgr.astype(np.float32)
        return np.clip(out, 0, 255).astype(np.uint8)

    def swap_faces_in_image(
        self,
        target_image_path: str | Path,
        source_face_paths: list[str | Path],
        output_path: str | Path,
    ) -> dict[str, Any]:
        """Lock 1 or 2 real friend faces onto the generated scene image and save to `output_path`."""
        import cv2

        t_path = Path(target_image_path).resolve()
        if not t_path.exists():
            raise FileNotFoundError(f"Target image not found: {t_path}")
        valid_sources = [Path(p).resolve() for p in source_face_paths if p and Path(p).exists()]
        if not valid_sources:
            raise ValueError("Provide at least one friend reference photo for Face Lock.")

        with self._lock:
            target_bgr = cv2.imread(str(t_path), cv2.IMREAD_COLOR)
            if target_bgr is None:
                raise RuntimeError(f"Could not decode target image: {t_path}")

            target_faces = self.detect_faces(target_bgr, det_thresh=0.40)
            if not target_faces:
                # Retry slightly looser threshold for stylized/distant faces
                target_faces = self.detect_faces(target_bgr, det_thresh=0.28)
            if not target_faces:
                raise RuntimeError("No face detected in the generated image to swap onto.")

            # Extract source friend embeddings (largest face in each reference photo)
            src_embeddings: list[np.ndarray] = []
            for sp in valid_sources[:2]:
                src_bgr = cv2.imread(str(sp), cv2.IMREAD_COLOR)
                if src_bgr is None:
                    continue
                s_faces = self.detect_faces(src_bgr, det_thresh=0.35)
                if not s_faces:
                    s_faces = self.detect_faces(src_bgr, det_thresh=0.20)
                if not s_faces:
                    raise RuntimeError(f"No face detected in friend photo '{sp.name}'. Use a clearer front-facing photo.")
                best_src = max(s_faces, key=lambda f: f.area)
                src_embeddings.append(self.get_embedding(src_bgr, best_src))

            if not src_embeddings:
                raise RuntimeError("Could not extract any friend face embeddings.")

            # Match faces: 1 friend -> largest face in scene; 2 friends -> top 2 largest faces ordered left-to-right
            result_bgr = target_bgr.copy()
            swapped_count = 0
            if len(src_embeddings) == 1:
                primary = max(target_faces, key=lambda f: f.area)
                result_bgr = self.swap_single_face(result_bgr, primary, src_embeddings[0])
                swapped_count = 1
            else:
                top_targets = sorted(target_faces, key=lambda f: f.area, reverse=True)[: len(src_embeddings)]
                top_targets.sort(key=lambda f: f.center_x)
                for tf, emb in zip(top_targets, src_embeddings):
                    result_bgr = self.swap_single_face(result_bgr, tf, emb)
                    swapped_count += 1

            out_p = Path(output_path).resolve()
            out_p.parent.mkdir(parents=True, exist_ok=True)
            if not cv2.imwrite(str(out_p), result_bgr):
                raise RuntimeError(f"Failed to write face-swapped image: {out_p}")

        return {
            "image_path": str(out_p),
            "filename": out_p.name,
            "faces_swapped": swapped_count,
            "faces_detected": len(target_faces),
            "engine": "inswapper_128_onnx",
            "file_size_bytes": out_p.stat().st_size,
        }


_SWAPPER_CACHE: dict[str, PureOnnxFaceSwapper] = {}
_CACHE_LOCK = threading.Lock()


def get_face_swapper(comfy_dir: Path) -> PureOnnxFaceSwapper:
    models_dir = (comfy_dir / "models" / "insightface").resolve()
    key = str(models_dir)
    with _CACHE_LOCK:
        inst = _SWAPPER_CACHE.get(key)
        if inst is None:
            inst = PureOnnxFaceSwapper(models_dir)
            _SWAPPER_CACHE[key] = inst
        return inst


def swap_faces_in_image(
    target_image_path: str | Path,
    source_face_paths: list[str | Path],
    output_dir: Path,
    comfy_dir: Path,
    overwrite_output: Path | None = None,
) -> dict[str, Any]:
    """Convenience entry point that saves a new face-locked PNG (or overwrites `overwrite_output`)."""
    swapper = get_face_swapper(comfy_dir)
    src_t = Path(target_image_path).resolve()
    if overwrite_output is not None:
        out_p = Path(overwrite_output).resolve()
    else:
        out_p = (output_dir / f"{src_t.stem[:42]}_facelock_{uuid.uuid4().hex[:6]}.png").resolve()
    return swapper.swap_faces_in_image(src_t, source_face_paths, out_p)
