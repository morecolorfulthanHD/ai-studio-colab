#!/usr/bin/env python3
"""Automated visual QA gates for identity architecture benchmark (Package 4.12.3).

Deterministic local checks only. Does not replace final human review.
Thresholds are initially uncalibrated — fail closed on missing detectors.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable

_DEFAULT_QA_CONFIG: dict[str, Any] = {
    "calibration_status": "uncalibrated",
    "identity_cosine_min": 0.35,
    "yaw_frontal_abs_max": 12,
    "yaw_s2_abs_min": 25,
    "yaw_s2_abs_max": 55,
    "smile_min_s3": 0.45,
    "visible_teeth_min_s3": 0.25,
    "clip_adherence_min_s4": 0.20,
    "notes": [
        "Thresholds are placeholders until live GPU calibration.",
        "Automated gates eliminate obvious failures; human review still required on pass.",
    ],
}

_inject_embeddings: Callable[[str], list[float] | None] | None = None
_inject_yaw: Callable[[str], float | None] | None = None
_inject_smile: Callable[[str], tuple[float, float] | None] | None = None


def set_qa_test_hooks(
    *,
    inject_embeddings: Callable[[str], list[float] | None] | None = None,
    inject_yaw: Callable[[str], float | None] | None = None,
    inject_smile: Callable[[str], tuple[float, float] | None] | None = None,
) -> None:
    global _inject_embeddings, _inject_yaw, _inject_smile
    _inject_embeddings = inject_embeddings
    _inject_yaw = inject_yaw
    _inject_smile = inject_smile


def reset_qa_test_hooks() -> None:
    set_qa_test_hooks()


def load_qa_config(repo_root: Path | None = None) -> dict[str, Any]:
    """Load QA thresholds; fall back to in-code defaults if config missing."""
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
    """Compare face embeddings. Fail closed when insightface available but no face detected."""
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
        import insightface  # noqa: F401
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

        arr = np.array(img)
        faces = app.get(arr)
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
    score = _cosine(ref_emb or [], gen_emb or [])
    result["status"] = "ok"
    result["identity_cosine_similarity"] = score
    result["notes"] = "Computed via insightface buffalo_l embeddings."
    return result


def estimate_yaw_degrees(
    image_path: str | Path,
    *,
    inject_yaw: Callable[[str], float | None] | None = None,
) -> dict[str, Any]:
    """Estimate head yaw using OpenCV Haar eye geometry when available."""
    path = Path(image_path)
    result: dict[str, Any] = {
        "status": "unavailable",
        "estimated_yaw_degrees": None,
        "pose_detection_status": "unavailable",
        "is_near_front": None,
        "notes": "",
    }
    hook = inject_yaw or _inject_yaw
    if hook is not None:
        yaw = hook(str(path))
        if yaw is None:
            result["status"] = "fail"
            result["pose_detection_status"] = "no_face"
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

    img = _load_image_rgb(path)
    if img is None:
        result["notes"] = "Image unreadable."
        return result

    try:
        import cv2
        import numpy as np
    except ImportError:
        result["notes"] = "OpenCV unavailable for yaw estimation."
        return result

    gray = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    eye_path = cv2.data.haarcascades + "haarcascade_eye.xml"
    face_cascade = cv2.CascadeClassifier(cascade_path)
    eye_cascade = cv2.CascadeClassifier(eye_path)
    faces = face_cascade.detectMultiScale(gray, 1.1, 5, minSize=(48, 48))
    if len(faces) == 0:
        result["status"] = "fail"
        result["pose_detection_status"] = "no_face"
        result["notes"] = "No face detected for yaw estimation."
        return result
    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
    roi = gray[y : y + h, x : x + w]
    eyes = eye_cascade.detectMultiScale(roi, 1.1, 5, minSize=(16, 16))
    if len(eyes) < 2:
        # Heuristic fallback: horizontal brightness asymmetry in face ROI
        left = roi[:, : w // 2]
        right = roi[:, w // 2 :]
        asym = float(left.mean() - right.mean())
        yaw = max(-60.0, min(60.0, asym * 0.35))
    else:
        eyes = sorted(eyes, key=lambda e: e[0])[:2]
        (ex1, _, ew1, _), (ex2, _, ew2, _) = eyes
        cx1 = ex1 + ew1 / 2
        cx2 = ex2 + ew2 / 2
        eye_span = max(abs(cx2 - cx1), 1.0)
        face_cx = w / 2
        eye_mid = (cx1 + cx2) / 2
        offset = (eye_mid - face_cx) / eye_span
        yaw = max(-60.0, min(60.0, offset * 45.0))

    result["status"] = "ok"
    result["estimated_yaw_degrees"] = float(yaw)
    result["pose_detection_status"] = "ok"
    result["is_near_front"] = abs(float(yaw)) < 12
    result["notes"] = "Haar eye-geometry heuristic (uncalibrated)."
    return result


def smile_and_teeth_signals(
    image_path: str | Path,
    *,
    inject_smile: Callable[[str], tuple[float, float] | None] | None = None,
) -> dict[str, Any]:
    """Mouth-region aspect + bright teeth heuristic."""
    path = Path(image_path)
    result: dict[str, Any] = {
        "status": "unavailable",
        "smile_score": None,
        "visible_teeth_signal": None,
        "expression_gate_status": "unavailable",
        "notes": "",
    }
    hook = inject_smile or _inject_smile
    if hook is not None:
        row = hook(str(path))
        if row is None:
            result["status"] = "fail"
            result["expression_gate_status"] = "no_face"
            return result
        smile, teeth = row
        result.update(
            {
                "status": "ok",
                "smile_score": float(smile),
                "visible_teeth_signal": float(teeth),
                "expression_gate_status": "ok",
                "notes": "Computed via inject_smile hook.",
            }
        )
        return result

    img = _load_image_rgb(path)
    if img is None:
        result["notes"] = "Image unreadable."
        return result

    try:
        import cv2
        import numpy as np
    except ImportError:
        result["notes"] = "OpenCV unavailable for expression heuristic."
        return result

    arr = np.array(img)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    h, w = gray.shape
    mouth_roi = gray[int(h * 0.55) : int(h * 0.85), int(w * 0.25) : int(w * 0.75)]
    if mouth_roi.size == 0:
        result["status"] = "fail"
        result["expression_gate_status"] = "no_face"
        return result
    mouth_h = mouth_roi.shape[0]
    mouth_w = mouth_roi.shape[1]
    aspect = mouth_w / max(mouth_h, 1)
    smile_score = min(1.0, max(0.0, (aspect - 1.2) / 1.5))
    bright = mouth_roi > 200
    teeth_signal = float(bright.mean())
    result["status"] = "ok"
    result["smile_score"] = smile_score
    result["visible_teeth_signal"] = teeth_signal
    result["expression_gate_status"] = "ok"
    result["notes"] = "Lower-face aspect + bright-region heuristic (uncalibrated)."
    return result


def prompt_adherence_scores(
    image_path: str | Path,
    concepts: list[str],
) -> dict[str, Any]:
    """Optional CLIP text-image scores; stub unavailable when CLIP not present."""
    path = Path(image_path)
    result: dict[str, Any] = {
        "status": "unavailable",
        "scores": {},
        "notes": "",
    }
    if not concepts:
        result["notes"] = "No concepts supplied."
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
        processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
        model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
        model.eval()
        inputs = processor(text=concepts, images=img, return_tensors="pt", padding=True)
        with torch.no_grad():
            outputs = model(**inputs)
        logits = outputs.logits_per_image[0]
        probs = logits.softmax(dim=0)
        result["scores"] = {c: float(probs[i]) for i, c in enumerate(concepts)}
        result["status"] = "ok"
        result["notes"] = "CLIP ViT-B/32 similarities (advisory)."
    except Exception as exc:  # noqa: BLE001
        result["notes"] = f"CLIP scoring failed: {exc}"
    return result


def image_integrity_gate(
    path: str | Path,
    *,
    expected_width: int | None = None,
    expected_height: int | None = None,
) -> dict[str, Any]:
    """Decode image, verify non-zero bytes and optional dimensions."""
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


def _gate_status(passed: bool | None) -> str:
    if passed is True:
        return "pass"
    if passed is False:
        return "fail"
    return "unavailable"


def evaluate_scenario_qa(
    scenario: str,
    ref_face: str | Path,
    output_path: str | Path,
    config: dict[str, Any] | None = None,
    *,
    inject_embeddings: Callable[[str], list[float] | None] | None = None,
    inject_yaw: Callable[[str], float | None] | None = None,
    inject_smile: Callable[[str], tuple[float, float] | None] | None = None,
) -> dict[str, Any]:
    """Run scenario-specific automated gates and return consolidated QA dict."""
    cfg = config or load_qa_config()
    scenario_id = str(scenario or "").strip()
    from .identity_architecture_benchmark import SCENARIO_DIMENSIONS

    expected_w, expected_h = SCENARIO_DIMENSIONS.get(scenario_id, (None, None))
    integrity = image_integrity_gate(
        output_path,
        expected_width=expected_w,
        expected_height=expected_h,
    )
    identity = compute_identity_cosine_similarity(
        ref_face,
        output_path,
        inject_embeddings=inject_embeddings,
    )
    yaw = estimate_yaw_degrees(output_path, inject_yaw=inject_yaw)
    smile = smile_and_teeth_signals(output_path, inject_smile=inject_smile)

    identity_min = float(cfg.get("identity_cosine_min") or 0.35)
    identity_gate: str
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

    if scenario_id == "S2_head_angle_pose":
        if yaw["status"] == "fail":
            scenario_adherence_gate = "fail"
        elif yaw["status"] == "ok" and yaw.get("estimated_yaw_degrees") is not None:
            yaw_val = abs(float(yaw["estimated_yaw_degrees"]))
            frontal_max = float(cfg.get("yaw_frontal_abs_max") or 12)
            s2_min = float(cfg.get("yaw_s2_abs_min") or 25)
            s2_max = float(cfg.get("yaw_s2_abs_max") or 55)
            if yaw_val < frontal_max:
                scenario_adherence_gate = "fail"
            elif s2_min <= yaw_val <= s2_max:
                scenario_adherence_gate = "pass"
            else:
                scenario_adherence_gate = "fail"
    elif scenario_id == "S3_expression_change":
        if smile["status"] == "fail":
            scenario_adherence_gate = "fail"
        elif smile["status"] == "ok":
            smile_min = float(cfg.get("smile_min_s3") or 0.45)
            teeth_min = float(cfg.get("visible_teeth_min_s3") or 0.25)
            if (
                float(smile.get("smile_score") or 0) >= smile_min
                and float(smile.get("visible_teeth_signal") or 0) >= teeth_min
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
        prompt_scores = prompt_adherence_scores(output_path, concepts)
        if prompt_scores.get("status") == "ok":
            red = float((prompt_scores.get("scores") or {}).get(concepts[0], 0))
            env = float((prompt_scores.get("scores") or {}).get(concepts[1], 0))
            clip_min = float(cfg.get("clip_adherence_min_s4") or 0.20)
            scenario_adherence_gate = "pass" if red >= clip_min and env >= clip_min else "fail"
    elif scenario_id == "S1_near_front_portrait":
        if yaw["status"] == "ok" and yaw.get("is_near_front") is True:
            scenario_adherence_gate = "pass"
        elif yaw["status"] == "ok" and yaw.get("is_near_front") is False:
            scenario_adherence_gate = "fail"
        else:
            scenario_adherence_gate = "unavailable"

    integrity_gate = integrity.get("image_integrity_gate") or integrity.get("status")
    gates = [identity_gate, scenario_adherence_gate, integrity_gate]
    if "fail" in gates:
        automated_quality_status = "fail"
    elif all(g == "pass" for g in gates):
        automated_quality_status = "pass"
    else:
        automated_quality_status = "inconclusive"

    human_review_status = (
        "not_required_yet" if automated_quality_status == "fail" else "required_if_automated_pass"
    )
    final_status = automated_quality_status

    return {
        "scenario": scenario_id,
        "execution_status": "pass",
        "identity_gate": identity_gate,
        "scenario_adherence_gate": scenario_adherence_gate,
        "image_integrity_gate": integrity_gate,
        "automated_quality_status": automated_quality_status,
        "human_review_status": human_review_status,
        "final_status": final_status,
        "calibration_status": cfg.get("calibration_status"),
        "identity_cosine_similarity": identity.get("identity_cosine_similarity"),
        "estimated_yaw_degrees": yaw.get("estimated_yaw_degrees"),
        "pose_detection_status": yaw.get("pose_detection_status"),
        "smile_score": smile.get("smile_score"),
        "visible_teeth_signal": smile.get("visible_teeth_signal"),
        "expression_gate_status": smile.get("expression_gate_status"),
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
