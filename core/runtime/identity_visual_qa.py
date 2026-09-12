#!/usr/bin/env python3
"""Automated visual QA gates for identity architecture benchmark (Package 4.12.3).

Landmark/PnP yaw with documented sign convention.
Face-local smile/teeth.
No network CLIP downloads.
Uncalibrated metrics never produce plain automated PASS.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Callable

# Sign convention (documented):
#   positive yaw_degrees = subject turns toward THEIR right (three-quarter right).
#   negative yaw_degrees = subject turns toward THEIR left.
# Estimator maps OpenCV solvePnP yaw so that rightward head turn is positive.
YAW_SIGN_CONVENTION = (
    "positive = subject turns to subject's right; "
    "negative = subject turns to subject's left"
)

_DEFAULT_QA_CONFIG: dict[str, Any] = {
    "calibration_status": "uncalibrated",
    "identity_cosine_min": 0.35,
    "yaw_frontal_abs_max": 12,
    "yaw_s2_abs_min": 25,
    "yaw_s2_abs_max": 55,
    "yaw_requested_direction": "right",
    "smile_min_s3": 0.45,
    "mouth_open_min_s3": 0.20,
    "visible_teeth_min_s3": 0.25,
    "clip_adherence_min_s4": 0.20,
    "notes": [
        "Thresholds are placeholders until live GPU calibration.",
        "Clear objective failures still FAIL. Uncalibrated success is provisional_pass only.",
    ],
}

_inject_embeddings: Callable[[str], list[float] | None] | None = None
_inject_yaw: Callable[[str], float | None] | None = None
_inject_smile: Callable[[str], tuple[float, float, float] | None] | None = None
_inject_landmarks: Callable[[str], Any] | None = None


def set_qa_test_hooks(
    *,
    inject_embeddings: Callable[[str], list[float] | None] | None = None,
    inject_yaw: Callable[[str], float | None] | None = None,
    inject_smile: Callable[[str], tuple[float, float, float] | None] | None = None,
    inject_landmarks: Callable[[str], Any] | None = None,
) -> None:
    global _inject_embeddings, _inject_yaw, _inject_smile, _inject_landmarks
    _inject_embeddings = inject_embeddings
    _inject_yaw = inject_yaw
    _inject_smile = inject_smile
    _inject_landmarks = inject_landmarks


def reset_qa_test_hooks() -> None:
    set_qa_test_hooks()


def load_qa_config(repo_root: Path | None = None) -> dict[str, Any]:
    if repo_root is not None:
        config_path = Path(repo_root) / "configs/benchmarks/identity_architecture_qa.json"
        if config_path.is_file():
            try:
                data = json.loads(config_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    merged = dict(_DEFAULT_QA_CONFIG)
                    merged.update(data)
                    return merged
            except (OSError, json.JSONDecodeError):
                pass
    return dict(_DEFAULT_QA_CONFIG)


def _load_image_rgb(path: Path) -> Any | None:
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(path) as img:
            return img.convert("RGB")
    except OSError:
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def compute_identity_cosine_similarity(
    ref_path: str | Path,
    gen_path: str | Path,
    *,
    inject_embeddings: Callable[[str], list[float] | None] | None = None,
) -> dict[str, Any]:
    ref = Path(ref_path)
    gen = Path(gen_path)
    result: dict[str, Any] = {
        "status": "unavailable",
        "identity_cosine_similarity": None,
        "face_detected_ref": False,
        "face_detected_gen": False,
        "notes": "",
    }
    hook = inject_embeddings or _inject_embeddings
    if hook is not None:
        ref_emb = hook(str(ref))
        gen_emb = hook(str(gen))
        if ref_emb is None or gen_emb is None:
            result["status"] = "fail"
            result["notes"] = "Test hook: face detection failed."
            return result
        score = _cosine(ref_emb, gen_emb)
        result.update(
            {
                "status": "ok",
                "identity_cosine_similarity": score,
                "face_detected_ref": True,
                "face_detected_gen": True,
                "notes": "Computed via inject_embeddings hook.",
            }
        )
        return result

    try:
        from insightface.app import FaceAnalysis
    except ImportError:
        result["notes"] = "insightface not importable; identity cosine unavailable."
        return result

    try:
        app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        app.prepare(ctx_id=0, det_size=(640, 640))
    except Exception as exc:  # noqa: BLE001
        result["notes"] = f"insightface init failed: {exc}"
        return result

    def _embed(path: Path) -> tuple[list[float] | None, bool]:
        img = _load_image_rgb(path)
        if img is None:
            return None, False
        import numpy as np

        faces = app.get(np.array(img))
        if not faces:
            return None, False
        emb = getattr(faces[0], "embedding", None)
        if emb is None:
            return None, False
        return [float(x) for x in emb], True

    ref_emb, ref_ok = _embed(ref)
    gen_emb, gen_ok = _embed(gen)
    result["face_detected_ref"] = ref_ok
    result["face_detected_gen"] = gen_ok
    if not ref_ok or not gen_ok:
        result["status"] = "fail"
        result["notes"] = "Face detection failed (fail closed when insightface available)."
        return result
    result["status"] = "ok"
    result["identity_cosine_similarity"] = _cosine(ref_emb or [], gen_emb or [])
    result["notes"] = "Computed via insightface buffalo_l embeddings."
    return result


def _generic_3d_face_model() -> Any:
    """Canonical 3D face points (mm-ish) for solvePnP: nose, chin, L/R eye, L/R mouth."""
    import numpy as np

    return np.array(
        [
            (0.0, 0.0, 0.0),  # nose tip
            (0.0, -63.6, -12.5),  # chin
            (-43.3, 32.7, -26.0),  # left eye outer
            (43.3, 32.7, -26.0),  # right eye outer
            (-28.9, -28.9, -24.1),  # left mouth
            (28.9, -28.9, -24.1),  # right mouth
        ],
        dtype=np.float64,
    )


def _extract_face_landmarks(image_path: Path) -> dict[str, Any]:
    """Return 2D landmarks + confidence using InsightFace when available."""
    out: dict[str, Any] = {
        "status": "unavailable",
        "points": None,
        "kps": None,
        "det_score": None,
        "notes": "",
    }
    if _inject_landmarks is not None:
        hooked = _inject_landmarks(str(image_path))
        if hooked is None:
            out["status"] = "unavailable"
            out["notes"] = "Test hook: landmarks unavailable."
            return out
        out.update(hooked if isinstance(hooked, dict) else {"status": "ok", "points": hooked})
        return out

    img = _load_image_rgb(image_path)
    if img is None:
        out["notes"] = "Image unreadable."
        return out
    try:
        import numpy as np
        from insightface.app import FaceAnalysis
    except ImportError:
        out["notes"] = "insightface unavailable for landmarks; yaw/smile inconclusive."
        return out

    try:
        app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        app.prepare(ctx_id=0, det_size=(640, 640))
        faces = app.get(np.array(img))
    except Exception as exc:  # noqa: BLE001
        out["notes"] = f"insightface landmark init/get failed: {exc}"
        return out
    if not faces:
        out["status"] = "fail"
        out["notes"] = "No face detected for landmarks."
        return out
    face = max(faces, key=lambda f: float(getattr(f, "det_score", 0) or 0))
    kps = getattr(face, "kps", None)
    if kps is None:
        out["status"] = "unavailable"
        out["notes"] = "Face detected but no landmarks."
        return out
    # InsightFace 5-point: left_eye, right_eye, nose, left_mouth, right_mouth
    pts = np.asarray(kps, dtype=np.float64)
    if pts.shape[0] < 5:
        out["status"] = "unavailable"
        out["notes"] = "Insufficient landmark points."
        return out
    # Map to solvePnP order: nose, chin(approx), L eye, R eye, L mouth, R mouth
    # Chin approx: extend nose→mid-mouth downward.
    left_eye, right_eye, nose, left_mouth, right_mouth = pts[:5]
    mouth_mid = (left_mouth + right_mouth) / 2.0
    chin = mouth_mid + (mouth_mid - nose) * 0.85
    ordered = np.array([nose, chin, left_eye, right_eye, left_mouth, right_mouth], dtype=np.float64)
    out.update(
        {
            "status": "ok",
            "points": ordered,
            "kps": pts,
            "det_score": float(getattr(face, "det_score", 0) or 0),
            "notes": "InsightFace 5-point landmarks (+chin approx).",
        }
    )
    return out


def estimate_yaw_degrees(
    image_path: str | Path,
    *,
    inject_yaw: Callable[[str], float | None] | None = None,
) -> dict[str, Any]:
    """Estimate yaw via landmark solvePnP. No brightness-asymmetry production fallback."""
    path = Path(image_path)
    result: dict[str, Any] = {
        "status": "unavailable",
        "estimated_yaw_degrees": None,
        "estimated_pitch_degrees": None,
        "estimated_roll_degrees": None,
        "pose_detection_status": "unavailable",
        "detector_confidence": None,
        "is_near_front": None,
        "yaw_sign_convention": YAW_SIGN_CONVENTION,
        "notes": "",
    }
    hook = inject_yaw or _inject_yaw
    if hook is not None:
        yaw = hook(str(path))
        if yaw is None:
            result["status"] = "unavailable"
            result["pose_detection_status"] = "unavailable"
            result["notes"] = "Test hook: yaw unavailable."
            return result
        result.update(
            {
                "status": "ok",
                "estimated_yaw_degrees": float(yaw),
                "pose_detection_status": "ok",
                "is_near_front": abs(float(yaw)) < 12,
                "notes": "Computed via inject_yaw hook.",
            }
        )
        return result

    lm = _extract_face_landmarks(path)
    if lm.get("status") == "fail":
        result["status"] = "fail"
        result["pose_detection_status"] = "no_face"
        result["notes"] = lm.get("notes") or "No face."
        return result
    if lm.get("status") != "ok" or lm.get("points") is None:
        result["status"] = "unavailable"
        result["pose_detection_status"] = "unavailable"
        result["notes"] = lm.get("notes") or "Landmarks unavailable; yaw inconclusive."
        return result

    try:
        import cv2
        import numpy as np
    except ImportError:
        result["notes"] = "OpenCV unavailable for solvePnP."
        return result

    img = _load_image_rgb(path)
    if img is None:
        result["notes"] = "Image unreadable."
        return result
    w, h = img.size
    image_points = np.asarray(lm["points"], dtype=np.float64)
    model_points = _generic_3d_face_model()
    focal = float(w)
    center = (w / 2.0, h / 2.0)
    camera_matrix = np.array(
        [[focal, 0, center[0]], [0, focal, center[1]], [0, 0, 1]],
        dtype=np.float64,
    )
    dist = np.zeros((4, 1), dtype=np.float64)
    ok, rvec, tvec = cv2.solvePnP(
        model_points,
        image_points,
        camera_matrix,
        dist,
        flags=cv2.SOLVEPNP_ITERATIVE,
    )
    if not ok:
        result["status"] = "unavailable"
        result["pose_detection_status"] = "unavailable"
        result["notes"] = "solvePnP failed."
        return result
    rot, _ = cv2.Rodrigues(rvec)
    # yaw from rotation matrix (Y-axis); flip sign so subject's right is positive
    sy = math.sqrt(rot[0, 0] ** 2 + rot[1, 0] ** 2)
    yaw = math.degrees(math.atan2(-rot[2, 0], sy))
    pitch = math.degrees(math.atan2(rot[2, 1], rot[2, 2]))
    roll = math.degrees(math.atan2(rot[1, 0], rot[0, 0]))
    # InsightFace/OpenCV camera convention often yields inverted left/right vs subject-right.
    # Documented flip: multiply by -1 so positive = subject turns right.
    yaw = -float(yaw)
    result.update(
        {
            "status": "ok",
            "estimated_yaw_degrees": yaw,
            "estimated_pitch_degrees": float(pitch),
            "estimated_roll_degrees": float(roll),
            "pose_detection_status": "ok",
            "detector_confidence": lm.get("det_score"),
            "is_near_front": abs(yaw) < 12,
            "notes": "Landmark solvePnP yaw; sign flipped to subject-right positive.",
        }
    )
    return result


def smile_and_teeth_signals(
    image_path: str | Path,
    *,
    inject_smile: Callable[[str], tuple[float, float, float] | None] | None = None,
) -> dict[str, Any]:
    """Face-local mouth geometry + teeth region inside mouth landmarks."""
    path = Path(image_path)
    result: dict[str, Any] = {
        "status": "unavailable",
        "smile_score": None,
        "mouth_open_score": None,
        "visible_teeth_signal": None,
        "expression_gate_status": "unavailable",
        "landmark_status": "unavailable",
        "notes": "",
    }
    hook = inject_smile or _inject_smile
    if hook is not None:
        row = hook(str(path))
        if row is None:
            result["status"] = "unavailable"
            result["expression_gate_status"] = "unavailable"
            result["landmark_status"] = "unavailable"
            return result
        if len(row) == 2:
            smile, teeth = row
            mouth_open = smile
        else:
            smile, mouth_open, teeth = row
        result.update(
            {
                "status": "ok",
                "smile_score": float(smile),
                "mouth_open_score": float(mouth_open),
                "visible_teeth_signal": float(teeth),
                "expression_gate_status": "ok",
                "landmark_status": "ok",
                "notes": "Computed via inject_smile hook.",
            }
        )
        return result

    lm = _extract_face_landmarks(path)
    result["landmark_status"] = lm.get("status") or "unavailable"
    if lm.get("status") == "fail":
        result["status"] = "fail"
        result["expression_gate_status"] = "no_face"
        result["notes"] = lm.get("notes") or "No face."
        return result
    if lm.get("status") != "ok" or lm.get("kps") is None:
        result["status"] = "unavailable"
        result["expression_gate_status"] = "unavailable"
        result["notes"] = lm.get("notes") or "Mouth landmarks unavailable; expression inconclusive."
        return result

    img = _load_image_rgb(path)
    if img is None:
        result["notes"] = "Image unreadable."
        return result
    try:
        import numpy as np
    except ImportError:
        result["notes"] = "numpy unavailable."
        return result

    kps = np.asarray(lm["kps"], dtype=np.float64)
    left_eye, right_eye, nose, left_mouth, right_mouth = kps[:5]
    mouth_width = float(np.linalg.norm(right_mouth - left_mouth))
    eye_span = float(np.linalg.norm(right_eye - left_eye)) or 1.0
    mouth_mid = (left_mouth + right_mouth) / 2.0
    # Vertical separation nose→mouth relative to eye span approximates openness/smile stretch.
    vertical = float(np.linalg.norm(mouth_mid - nose))
    smile_score = min(1.0, max(0.0, (mouth_width / eye_span - 0.55) / 0.55))
    mouth_open_score = min(1.0, max(0.0, (vertical / eye_span - 0.45) / 0.55))

    # Teeth region: small band between mouth corners, interior of lower face.
    arr = np.array(img)
    x0 = int(min(left_mouth[0], right_mouth[0]))
    x1 = int(max(left_mouth[0], right_mouth[0]))
    y_mid = int(mouth_mid[1])
    band = max(2, int(0.12 * mouth_width))
    y0 = max(0, y_mid - band // 2)
    y1 = min(arr.shape[0], y_mid + band)
    x0 = max(0, x0)
    x1 = min(arr.shape[1], max(x0 + 1, x1))
    roi = arr[y0:y1, x0:x1]
    if roi.size == 0:
        teeth = 0.0
    else:
        # Bright + low-saturation-ish proxy in RGB: high min channel
        bright = (roi.min(axis=2) > 170) & (roi.max(axis=2) > 200)
        teeth = float(bright.mean())

    result.update(
        {
            "status": "ok",
            "smile_score": smile_score,
            "mouth_open_score": mouth_open_score,
            "visible_teeth_signal": teeth,
            "expression_gate_status": "ok",
            "landmark_status": "ok",
            "notes": "Face-local mouth width/openness + mouth-band teeth heuristic (uncalibrated).",
        }
    )
    return result


def _local_clip_model_dir(repo_root: Path | None = None) -> Path | None:
    env = str(os.environ.get("AI_STUDIO_CLIP_MODEL_DIR") or "").strip()
    if env:
        p = Path(env)
        return p if p.is_dir() else None
    if repo_root is not None:
        candidate = Path(repo_root) / "assets" / "clip" / "openai-clip-vit-base-patch32"
        if candidate.is_dir():
            return candidate
    drive = Path("/content/drive/MyDrive/AI_Studio/models/shared/clip/openai-clip-vit-base-patch32")
    if drive.is_dir():
        return drive
    return None


def prompt_adherence_scores(
    image_path: str | Path,
    concepts: list[str],
    *,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Local CLIP only. Never downloads from Hugging Face."""
    path = Path(image_path)
    result: dict[str, Any] = {
        "status": "unavailable",
        "scores": {},
        "notes": "",
        "network_attempted": False,
    }
    if not concepts:
        result["notes"] = "No concepts supplied."
        return result
    model_dir = _local_clip_model_dir(repo_root)
    if model_dir is None:
        result["notes"] = (
            "Local CLIP model not present; S4 prompt adherence UNAVAILABLE "
            "(no Hugging Face download)."
        )
        return result
    try:
        import torch
        from transformers import CLIPModel, CLIPProcessor
    except ImportError:
        result["notes"] = "CLIP/transformers unavailable; prompt adherence stubbed."
        return result

    img = _load_image_rgb(path)
    if img is None:
        result["status"] = "fail"
        result["notes"] = "Image unreadable."
        return result

    try:
        processor = CLIPProcessor.from_pretrained(str(model_dir), local_files_only=True)
        model = CLIPModel.from_pretrained(str(model_dir), local_files_only=True)
        model.eval()
        inputs = processor(text=concepts, images=img, return_tensors="pt", padding=True)
        with torch.no_grad():
            outputs = model(**inputs)
        logits = outputs.logits_per_image[0]
        probs = logits.softmax(dim=0)
        result["scores"] = {c: float(probs[i]) for i, c in enumerate(concepts)}
        result["status"] = "ok"
        result["notes"] = f"Local CLIP only ({model_dir}); local_files_only=True."
    except Exception as exc:  # noqa: BLE001
        result["notes"] = f"Local CLIP scoring failed (no network fallback): {exc}"
        result["status"] = "unavailable"
    return result


def image_integrity_gate(
    path: str | Path,
    *,
    expected_width: int | None = None,
    expected_height: int | None = None,
) -> dict[str, Any]:
    p = Path(path)
    result: dict[str, Any] = {
        "status": "fail",
        "image_integrity_gate": "fail",
        "width": None,
        "height": None,
        "notes": "",
    }
    if not p.is_file() or p.stat().st_size == 0:
        result["notes"] = "Missing or zero-byte file."
        return result
    img = _load_image_rgb(p)
    if img is None:
        result["notes"] = "Image decode failed."
        return result
    w, h = img.size
    result["width"] = w
    result["height"] = h
    if expected_width is not None and w != expected_width:
        result["notes"] = f"Width mismatch: expected {expected_width}, got {w}."
        return result
    if expected_height is not None and h != expected_height:
        result["notes"] = f"Height mismatch: expected {expected_height}, got {h}."
        return result
    result["status"] = "pass"
    result["image_integrity_gate"] = "pass"
    result["notes"] = "Image integrity OK."
    return result


def _direction_match(yaw: float, requested: str) -> bool:
    req = str(requested or "right").strip().lower()
    if req == "right":
        return yaw > 0
    if req == "left":
        return yaw < 0
    return False


def _finalize_automated_status(
    *,
    calibration_status: str,
    identity_gate: str,
    scenario_adherence_gate: str,
    integrity_gate: str,
) -> tuple[str, str]:
    """Return (automated_quality_status, human_review_status).

    Uncalibrated metrics never yield plain 'pass'.
    """
    gates = [identity_gate, scenario_adherence_gate, integrity_gate]
    if "fail" in gates:
        return "fail", "not_required_yet"
    if any(g in {"unavailable", "inconclusive"} for g in gates):
        return "inconclusive", "HUMAN_REVIEW_REQUIRED"
    if all(g == "pass" for g in gates):
        if str(calibration_status) != "calibrated":
            return "provisional_pass", "HUMAN_REVIEW_REQUIRED"
        return "pass", "HUMAN_REVIEW_REQUIRED"
    return "inconclusive", "HUMAN_REVIEW_REQUIRED"


def evaluate_scenario_qa(
    scenario: str,
    ref_face: str | Path,
    output_path: str | Path,
    config: dict[str, Any] | None = None,
    *,
    requested_yaw_direction: str = "right",
    repo_root: Path | None = None,
    expected_width: int | None = None,
    expected_height: int | None = None,
    inject_embeddings: Callable[[str], list[float] | None] | None = None,
    inject_yaw: Callable[[str], float | None] | None = None,
    inject_smile: Callable[[str], tuple[float, float, float] | None] | None = None,
) -> dict[str, Any]:
    cfg = config or load_qa_config(repo_root)
    scenario_id = str(scenario or "").strip()
    from .identity_architecture_benchmark import SCENARIO_DIMENSIONS

    dims = SCENARIO_DIMENSIONS.get(scenario_id, (None, None))
    exp_w = expected_width if expected_width is not None else dims[0]
    exp_h = expected_height if expected_height is not None else dims[1]
    # Test hooks: when inject_* are active and caller passes 0, skip dimension binding.
    if expected_width == 0 and expected_height == 0:
        exp_w, exp_h = None, None
    integrity = image_integrity_gate(
        output_path,
        expected_width=exp_w,
        expected_height=exp_h,
    )
    identity = compute_identity_cosine_similarity(
        ref_face,
        output_path,
        inject_embeddings=inject_embeddings,
    )
    yaw = estimate_yaw_degrees(output_path, inject_yaw=inject_yaw)
    smile = smile_and_teeth_signals(output_path, inject_smile=inject_smile)

    identity_min = float(cfg.get("identity_cosine_min") or 0.35)
    if identity["status"] == "fail":
        identity_gate = "fail"
    elif identity["status"] == "ok" and identity.get("identity_cosine_similarity") is not None:
        identity_gate = (
            "pass" if float(identity["identity_cosine_similarity"]) >= identity_min else "fail"
        )
    else:
        identity_gate = "unavailable"

    scenario_adherence_gate = "unavailable"
    prompt_scores: dict[str, Any] = {"status": "unavailable", "scores": {}}
    direction_match = None
    req_dir = str(cfg.get("yaw_requested_direction") or requested_yaw_direction or "right")

    if scenario_id == "S2_head_angle_pose":
        if yaw["status"] == "fail":
            scenario_adherence_gate = "fail"
        elif yaw["status"] != "ok" or yaw.get("estimated_yaw_degrees") is None:
            scenario_adherence_gate = "unavailable"
        else:
            yaw_val = float(yaw["estimated_yaw_degrees"])
            abs_yaw = abs(yaw_val)
            frontal_max = float(cfg.get("yaw_frontal_abs_max") or 12)
            s2_min = float(cfg.get("yaw_s2_abs_min") or 25)
            s2_max = float(cfg.get("yaw_s2_abs_max") or 55)
            direction_match = _direction_match(yaw_val, req_dir)
            if abs_yaw < frontal_max:
                scenario_adherence_gate = "fail"
            elif abs_yaw > s2_max:
                scenario_adherence_gate = "fail"  # excessive profile
            elif not direction_match:
                scenario_adherence_gate = "fail"
            elif s2_min <= abs_yaw <= s2_max and direction_match:
                scenario_adherence_gate = "pass"
            else:
                scenario_adherence_gate = "fail"
    elif scenario_id == "S3_expression_change":
        if smile["status"] == "fail":
            scenario_adherence_gate = "fail"
        elif smile["status"] != "ok":
            scenario_adherence_gate = "unavailable"
        else:
            smile_min = float(cfg.get("smile_min_s3") or 0.45)
            teeth_min = float(cfg.get("visible_teeth_min_s3") or 0.25)
            mouth_min = float(cfg.get("mouth_open_min_s3") or 0.20)
            if (
                float(smile.get("smile_score") or 0) >= smile_min
                and float(smile.get("visible_teeth_signal") or 0) >= teeth_min
                and float(smile.get("mouth_open_score") or 0) >= mouth_min
            ):
                scenario_adherence_gate = "pass"
            else:
                scenario_adherence_gate = "fail"
    elif scenario_id == "S4_wardrobe_environment":
        concepts = [
            "person wearing a red jacket",
            "outdoor city street",
            "full body environmental photograph",
            "studio portrait close-up",
        ]
        prompt_scores = prompt_adherence_scores(output_path, concepts, repo_root=repo_root)
        if prompt_scores.get("status") == "ok":
            red = float((prompt_scores.get("scores") or {}).get(concepts[0], 0))
            env = float((prompt_scores.get("scores") or {}).get(concepts[1], 0))
            clip_min = float(cfg.get("clip_adherence_min_s4") or 0.20)
            scenario_adherence_gate = "pass" if red >= clip_min and env >= clip_min else "fail"
        else:
            scenario_adherence_gate = "unavailable"
    elif scenario_id == "S1_near_front_portrait":
        if yaw["status"] == "ok" and yaw.get("is_near_front") is True:
            scenario_adherence_gate = "pass"
        elif yaw["status"] == "ok" and yaw.get("is_near_front") is False:
            scenario_adherence_gate = "fail"
        else:
            scenario_adherence_gate = "unavailable"

    integrity_gate = integrity.get("image_integrity_gate") or integrity.get("status")
    automated_quality_status, human_review_status = _finalize_automated_status(
        calibration_status=str(cfg.get("calibration_status") or "uncalibrated"),
        identity_gate=identity_gate,
        scenario_adherence_gate=scenario_adherence_gate,
        integrity_gate=str(integrity_gate),
    )

    return {
        "scenario": scenario_id,
        "execution_status": "pass",
        "identity_gate": identity_gate,
        "scenario_adherence_gate": scenario_adherence_gate,
        "image_integrity_gate": integrity_gate,
        "automated_quality_status": automated_quality_status,
        "human_review_status": human_review_status,
        "final_status": automated_quality_status,
        "calibration_status": cfg.get("calibration_status"),
        "identity_cosine_similarity": identity.get("identity_cosine_similarity"),
        "estimated_yaw_degrees": yaw.get("estimated_yaw_degrees"),
        "requested_yaw_direction": req_dir,
        "direction_match": direction_match,
        "yaw_sign_convention": YAW_SIGN_CONVENTION,
        "pose_detection_status": yaw.get("pose_detection_status"),
        "smile_score": smile.get("smile_score"),
        "mouth_open_score": smile.get("mouth_open_score"),
        "visible_teeth_signal": smile.get("visible_teeth_signal"),
        "expression_gate_status": smile.get("expression_gate_status"),
        "landmark_status": smile.get("landmark_status"),
        "prompt_adherence_scores": prompt_scores.get("scores") or {},
        "prompt_adherence_status": prompt_scores.get("status"),
        "details": {
            "identity": identity,
            "yaw": yaw,
            "smile": smile,
            "integrity": integrity,
            "prompt_adherence": prompt_scores,
        },
    }
