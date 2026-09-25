#!/usr/bin/env python3
"""Bucket A face crop policy for identity prototypes (Package 4.12.3).

Bucket A only: deterministic crop / OpenCV Haar / PrepImageForClipVision
(or other verified permissive NON-InsightFace preprocessors).

Fail closed on InsightFace, FaceID, antelopev2, buffalo_l.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

BUCKET_A = "bucket_a"
BUCKET_A_POLICY_ID = "bucket_a_deterministic_opencv_or_prepimage"

ALLOWED_BUCKET_A_METHODS = frozenset(
    {
        "center_square_crop",
        "opencv_haar_frontalface",
        "prep_image_for_clip_vision",
        "passthrough_already_cropped",
    }
)

FORBIDDEN_CROP_BACKENDS = frozenset(
    {
        "insightface",
        "antelopev2",
        "buffalo_l",
        "buffalo",
        "faceid",
        "instantid_face_analysis",
        "retinaface_insightface",
    }
)


@dataclass
class FaceCropPolicyResult:
    ok: bool
    policy_id: str = BUCKET_A_POLICY_ID
    bucket: str = BUCKET_A
    method: str = ""
    backend: str = ""
    errors: list[str] | None = None
    messages: list[str] | None = None

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []
        if self.messages is None:
            self.messages = []

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_face_crop_policy(
    *,
    method: str,
    backend: str = "",
    allow_passthrough: bool = True,
) -> FaceCropPolicyResult:
    """Validate a proposed crop method against Bucket A + forbidden backends."""
    method_s = str(method or "").strip().lower()
    backend_s = str(backend or "").strip().lower()
    result = FaceCropPolicyResult(ok=False, method=method_s, backend=backend_s)

    if not method_s:
        result.errors.append("ERROR: Face crop method is required (Bucket A).")
        return result

    if method_s not in ALLOWED_BUCKET_A_METHODS:
        if method_s == "passthrough_already_cropped" and not allow_passthrough:
            result.errors.append("ERROR: Passthrough crop not allowed in this context.")
            return result
        result.errors.append(
            f"ERROR: Face crop method {method_s!r} is not Bucket A. "
            f"Allowed: {', '.join(sorted(ALLOWED_BUCKET_A_METHODS))}."
        )
        return result

    for token in FORBIDDEN_CROP_BACKENDS:
        if token in backend_s or token in method_s:
            result.errors.append(
                f"ERROR: Forbidden face-crop backend/method {token!r} "
                "(InsightFace/FaceID/antelope/buffalo fail closed)."
            )
            return result

    result.ok = True
    result.messages.append(
        f"Bucket A face crop accepted: method={method_s} backend={backend_s or 'n/a'}"
    )
    return result


def assert_no_insightface_crop_in_workflow(workflow_data: dict[str, Any]) -> list[str]:
    """Structural fail-closed: no InsightFace/FaceID crop nodes in graph."""
    errors: list[str] = []
    nodes = workflow_data.get("nodes") or []
    if not isinstance(nodes, list):
        return ["ERROR: Workflow nodes must be a list."]
    for node in nodes:
        if not isinstance(node, dict):
            continue
        ntype = str(node.get("type") or "")
        lowered = ntype.lower()
        for token in ("insightface", "faceid", "antelope", "buffalo", "instantidface"):
            if token in lowered:
                errors.append(
                    f"ERROR: Forbidden crop/analysis node type {ntype!r} "
                    "(Bucket A requires NON-InsightFace)."
                )
                break
    return errors


def deterministic_center_square_crop_box(
    width: int,
    height: int,
    *,
    face_fraction: float = 1.0,
) -> tuple[int, int, int, int]:
    """Pure-math center square crop (no ML). Returns (left, top, right, bottom)."""
    if width <= 0 or height <= 0:
        raise ValueError("width/height must be positive")
    side = int(min(width, height) * max(0.01, min(1.0, face_fraction)))
    left = max(0, (width - side) // 2)
    top = max(0, (height - side) // 2)
    return left, top, left + side, top + side


def crop_face_bucket_a(
    image_path: Path,
    dest_path: Path,
    *,
    method: str = "center_square_crop",
    backend: str = "stdlib_pil",
) -> FaceCropPolicyResult:
    """Apply Bucket A crop and write dest. Never imports InsightFace."""
    policy = validate_face_crop_policy(method=method, backend=backend)
    if not policy.ok:
        return policy

    src = Path(image_path)
    dst = Path(dest_path)
    if not src.is_file():
        policy.ok = False
        policy.errors.append(f"ERROR: Face image missing: {src}")
        return policy

    if method == "passthrough_already_cropped":
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        policy.messages.append(f"Passthrough staged face → {dst.name}")
        return policy

    if method == "prep_image_for_clip_vision":
        # Graph-side PrepImageForClipVision handles crop; stage original.
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        policy.messages.append(
            f"Staged face for PrepImageForClipVision → {dst.name}"
        )
        return policy

    try:
        from PIL import Image
    except ImportError as exc:
        policy.ok = False
        policy.errors.append(f"ERROR: PIL required for Bucket A crop: {exc}")
        return policy

    with Image.open(src) as im:
        im = im.convert("RGB")
        w, h = im.size
        if method == "opencv_haar_frontalface":
            box = _opencv_haar_box(im)
            if box is None:
                box = deterministic_center_square_crop_box(w, h)
                policy.messages.append(
                    "OpenCV Haar found no face; fell back to center_square_crop."
                )
        else:
            box = deterministic_center_square_crop_box(w, h)
        cropped = im.crop(box)
        dst.parent.mkdir(parents=True, exist_ok=True)
        cropped.save(dst)
    policy.messages.append(f"Bucket A crop wrote {dst.name} via {method}")
    return policy


def _opencv_haar_box(pil_image: Any) -> tuple[int, int, int, int] | None:
    """Optional OpenCV Haar; returns None if cv2/haar unavailable or no face."""
    try:
        import cv2  # type: ignore
        import numpy as np
    except ImportError:
        return None
    arr = np.array(pil_image)[:, :, ::-1]  # RGB→BGR
    gray = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(cascade_path)
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5)
    if faces is None or len(faces) == 0:
        return None
    # Largest face
    x, y, w, h = max(faces, key=lambda f: int(f[2]) * int(f[3]))
    # Expand slightly to square
    side = max(int(w), int(h))
    cx, cy = int(x + w / 2), int(y + h / 2)
    left = max(0, cx - side // 2)
    top = max(0, cy - side // 2)
    right = min(arr.shape[1], left + side)
    bottom = min(arr.shape[0], top + side)
    return left, top, right, bottom
