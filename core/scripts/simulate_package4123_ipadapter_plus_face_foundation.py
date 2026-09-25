#!/usr/bin/env python3
"""Package 4.12.3 — IP-Adapter Plus Face prototype foundation simulations.

Deterministic CODE/SIM checks (no Colab / no downloads / no GPU):
  - InstantID remains BLOCKED_FOR_COMMERCIAL / promotion_allowed=false
  - ipadapter_plus_face_sdxl architecture resolves
  - no InsightFace on Plus Face path
  - FaceID rejected on Plus Face graph
  - asset fail-closed pre-pin (sdxl_base PENDING)
  - license fail-closed while REVIEW_REQUIRED
  - evidence metadata architecture tag
  - S1–S4 QA thresholds unchanged
  - no InstantID/FaceID evidence contamination into Plus Face tag
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
import importlib.util

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.identity_architecture_benchmark import (
    ARCHITECTURE_SCENARIO_PROMPTS,
    SCENARIO_DIMENSIONS,
    assess_instantid_license_gate,
)
from core.runtime.identity_architecture_ipadapter_plus_face import (
    REQUIRED_MODEL_NAMES,
    assert_ipadapter_plus_face_graph,
    assess_ipadapter_plus_face_asset_readiness,
    assess_ipadapter_plus_face_license_gate,
    assess_ipadapter_plus_face_structural_readiness,
    run_ipadapter_plus_face_preflight,
)
from core.runtime.identity_architecture_plugin import (
    ARCHITECTURE_INSTANTID,
    ARCHITECTURE_IPADAPTER_PLUS_FACE,
    evidence_metadata_for,
    get_architecture,
    is_instantid_production_blocked,
    list_architecture_ids,
    reject_forbidden_dependencies,
)
from core.runtime.identity_face_crop_policy import (
    validate_face_crop_policy,
)
from core.runtime.identity_visual_qa import load_qa_config
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def _pass(results: list[tuple[str, str]], label: str) -> None:
    results.append(("PASS", label))
    print(f"  [PASS] {label}")


def _assert_true(label: str, cond: bool) -> None:
    if not cond:
        raise AssertionError(f"FAIL: {label}")


def _assert_equal(label: str, a: object, b: object) -> None:
    if a != b:
        raise AssertionError(f"FAIL: {label} ({a!r} != {b!r})")


class _Bundle:
    def __init__(self, repo_root: Path, models: list, nodes: list, root: Path):
        self.models = models
        self.nodes = nodes
        self._root = root
        self._repo = repo_root

    def path(self, key: str) -> Path:
        mapping = {
            "drive_root": self._root / "AI_Studio",
            "comfyui_runtime": self._root / "ComfyUI",
            "runtime_root": self._root / "runtime",
            "drive_workflows": self._root / "AI_Studio" / "workflows",
        }
        return mapping[key]


def main() -> int:
    results: list[tuple[str, str]] = []
    repo_root = find_repo_root(Path(__file__))
    loader = RegistryLoader(repo_root)
    bundle_all = loader.load_all()

    # --- InstantID blocked unchanged ---
    gate = assess_instantid_license_gate(repo_root)
    _assert_equal(
        "InstantID overall BLOCKED_FOR_COMMERCIAL",
        gate.get("overall_status"),
        "BLOCKED_FOR_COMMERCIAL",
    )
    _assert_equal("InstantID promotion_allowed false", gate.get("promotion_allowed"), False)
    antelope = (gate.get("components") or {}).get("insightface_antelopev2") or {}
    _assert_equal(
        "antelopev2 still BLOCKED_FOR_COMMERCIAL",
        antelope.get("status"),
        "BLOCKED_FOR_COMMERCIAL",
    )
    blocked, _ = is_instantid_production_blocked(repo_root)
    _assert_true("is_instantid_production_blocked", blocked)
    _pass(results, "InstantID blocked unchanged (BLOCKED_FOR_COMMERCIAL)")

    # --- Architecture plugin resolves both ---
    ids = list_architecture_ids()
    _assert_true("instantid_sdxl registered", ARCHITECTURE_INSTANTID in ids)
    _assert_true(
        "ipadapter_plus_face_sdxl registered", ARCHITECTURE_IPADAPTER_PLUS_FACE in ids
    )
    _assert_true("no photomaker registered", "photomaker" not in "".join(ids))
    ip = get_architecture(ARCHITECTURE_IPADAPTER_PLUS_FACE)
    _assert_equal("architecture_id", ip.spec.architecture_id, ARCHITECTURE_IPADAPTER_PLUS_FACE)
    _assert_equal("status PROTOTYPE", ip.spec.status, "PROTOTYPE")
    _assert_true("required assets present", "ipadapter_plus_face_sdxl_vit_h" in ip.spec.required_assets)
    _assert_true(
        "clip vision required", "clip_vision_vit_h_openclip" in ip.spec.required_assets
    )
    _pass(results, "IP-Adapter Plus Face architecture resolves")

    # --- Workflow structural / no InsightFace / FaceID rejected ---
    wf_path = (
        repo_root
        / "workflows/reference/identity_ipadapter_plus_face_sdxl_benchmark/workflow.json"
    )
    wf = json.loads(wf_path.read_text(encoding="utf-8"))
    # Bind face filename for structural assert
    for node in wf["nodes"]:
        if node.get("type") == "LoadImage" and str(node.get("id")) == "13":
            node["widgets_values"] = ["face.png", "image"]
    errs = assert_ipadapter_plus_face_graph(wf)
    _assert_equal("clean graph no errors", errs, [])

    bad_faceid = json.loads(json.dumps(wf))
    bad_faceid["nodes"].append(
        {
            "id": 99,
            "type": "IPAdapterFaceID",
            "inputs": [],
            "outputs": [],
            "widgets_values": ["FACEID PLUS V2"],
        }
    )
    faceid_errs = assert_ipadapter_plus_face_graph(bad_faceid)
    _assert_true("FaceID node rejected", any("FaceID" in e or "Forbidden" in e for e in faceid_errs))

    bad_insight = json.loads(json.dumps(wf))
    bad_insight["nodes"].append(
        {
            "id": 98,
            "type": "InstantIDFaceAnalysis",
            "inputs": [],
            "outputs": [],
            "widgets_values": ["CPU"],
        }
    )
    insight_errs = assert_ipadapter_plus_face_graph(bad_insight)
    _assert_true(
        "InsightFace/InstantID node rejected",
        any("Forbidden" in e or "InstantID" in e for e in insight_errs),
    )
    dep = reject_forbidden_dependencies(
        architecture_id=ARCHITECTURE_IPADAPTER_PLUS_FACE,
        model_names=["insightface_antelopev2", "ipadapter_faceid_plusv2_sd15"],
    )
    _assert_true("forbidden models detected", not dep["ok"])
    _pass(results, "no InsightFace; FaceID rejected on Plus Face path")

    # --- Bucket A crop policy ---
    ok_crop = validate_face_crop_policy(
        method="prep_image_for_clip_vision", backend="comfyui_ipadapter_plus"
    )
    _assert_true("Bucket A prepimage ok", ok_crop.ok)
    bad_crop = validate_face_crop_policy(method="insightface_antelope", backend="insightface")
    _assert_true("InsightFace crop fail closed", not bad_crop.ok)
    _pass(results, "Bucket A face crop policy fail-closed on InsightFace")

    # --- Asset fail-closed pre-pin (sdxl_base PENDING) ---
    assets = assess_ipadapter_plus_face_asset_readiness(
        drive_root=Path(tempfile.gettempdir()),
        bundle_models=list(bundle_all.models),
    )
    _assert_true("assets not ready pre-pin/missing files", not assets.get("ready"))
    err_blob = " ".join(assets.get("errors") or [])
    _assert_true(
        "sdxl pending or missing fails closed",
        "sdxl_base" in err_blob
        or "PENDING_FIRST_DOWNLOAD_PIN" in err_blob
        or "UNVERIFIED" in err_blob
        or "integrity" in err_blob.lower(),
    )
    # Published SHA present for plus-face adapter in registry
    by_name = {m.get("name"): m for m in bundle_all.models}
    plus = by_name.get("ipadapter_plus_face_sdxl_vit_h") or {}
    _assert_equal(
        "plus-face published sha",
        plus.get("expected_sha256"),
        "677ad8860204f7d0bfba12d29e6c31ded9beefdf3e4bbd102518357d31a292c1",
    )
    _assert_equal("plus-face size", plus.get("expected_size_bytes"), 847517512)
    clip = by_name.get("clip_vision_vit_h_openclip") or {}
    _assert_true("clip sha published", bool(clip.get("expected_sha256")))
    sdxl = by_name.get("sdxl_base") or {}
    _assert_true(
        "sdxl hash not invented",
        sdxl.get("expected_sha256") in (None, "", "null")
        or sdxl.get("pin_state") == "PENDING_FIRST_DOWNLOAD_PIN",
    )
    _pass(results, "asset fail-closed pre-pin; published Plus Face SHA pinned")

    # --- License fail-closed (REVIEW_REQUIRED) ---
    lic = assess_ipadapter_plus_face_license_gate(repo_root)
    _assert_equal("IP-Adapter license not ACCEPTABLE yet", lic.get("promotion_allowed"), False)
    _assert_true(
        "license REVIEW or blocked",
        str(lic.get("overall_status")) in {"REVIEW_REQUIRED", "BLOCKED_FOR_COMMERCIAL"},
    )
    sdxl_lic = (lic.get("components") or {}).get("sdxl_base") or {}
    _assert_equal("SDXL commercial OK status", sdxl_lic.get("status"), "ACCEPTABLE")
    _pass(results, "license fail-closed; SDXL commercial OK on PATH C")

    # --- Authoritative preflight fails closed when unresolved ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "AI_Studio").mkdir(parents=True)
        (root / "ComfyUI" / "custom_nodes").mkdir(parents=True)
        (root / "runtime").mkdir(parents=True)
        fake = _Bundle(repo_root, list(bundle_all.models), list(bundle_all.nodes), root)
        pre = run_ipadapter_plus_face_preflight(
            repo_root, fake, require_live_comfy=False, workflow_data=wf
        )
        _assert_true("preflight fail closed unresolved", not pre.get("ok"))
        steps = {s["step"]: s for s in pre.get("steps") or []}
        _assert_true("architecture step ok", steps.get("architecture", {}).get("ok"))
        _assert_true("no_forbidden_deps ok", steps.get("no_forbidden_deps", {}).get("ok"))
        _assert_true("sdxl_commercial_ok flag", pre.get("sdxl_commercial_ok") is True)
    _pass(results, "authoritative IP-Adapter preflight fail-closed if unresolved")

    # --- Evidence metadata architecture tag ---
    meta = evidence_metadata_for(ARCHITECTURE_IPADAPTER_PLUS_FACE, scenario="S1_near_front_portrait")
    _assert_equal("evidence architecture tag", meta.get("architecture"), ARCHITECTURE_IPADAPTER_PLUS_FACE)
    _assert_equal(
        "evidence tag field",
        meta.get("evidence_architecture_tag"),
        ARCHITECTURE_IPADAPTER_PLUS_FACE,
    )
    _assert_true(
        "not InstantID contaminated",
        meta.get("architecture") != ARCHITECTURE_INSTANTID,
    )
    instant_meta = evidence_metadata_for(ARCHITECTURE_INSTANTID)
    _assert_equal("InstantID tag preserved", instant_meta.get("architecture"), ARCHITECTURE_INSTANTID)
    _pass(results, "durable evidence architecture metadata (no contamination)")

    # --- S1–S4 semantics / thresholds unchanged ---
    qa = load_qa_config(repo_root)
    _assert_equal("identity_cosine_min", qa.get("identity_cosine_min"), 0.35)
    _assert_equal("yaw_s2_abs_min", qa.get("yaw_s2_abs_min"), 25)
    _assert_equal("smile_min_s3", qa.get("smile_min_s3"), 0.45)
    _assert_equal("clip_adherence_min_s4", qa.get("clip_adherence_min_s4"), 0.20)
    for sid in (
        "S1_near_front_portrait",
        "S2_head_angle_pose",
        "S3_expression_change",
        "S4_wardrobe_environment",
    ):
        _assert_true(f"prompt {sid}", sid in ARCHITECTURE_SCENARIO_PROMPTS)
        _assert_true(f"dims {sid}", sid in SCENARIO_DIMENSIONS)
    _assert_equal("S4 dims", SCENARIO_DIMENSIONS["S4_wardrobe_environment"], (1024, 768))
    _pass(results, "S1–S4 semantics and QA thresholds unchanged")

    # --- Structural readiness callable ---
    structural = assess_ipadapter_plus_face_structural_readiness(
        bundle_models=list(bundle_all.models),
        bundle_nodes=list(bundle_all.nodes),
        comfyui_custom_nodes=None,
    )
    _assert_equal(
        "structural architecture tag",
        structural.get("architecture"),
        ARCHITECTURE_IPADAPTER_PLUS_FACE,
    )
    _assert_equal("required model list", tuple(REQUIRED_MODEL_NAMES), REQUIRED_MODEL_NAMES)
    _pass(results, "structural readiness API for ipadapter_plus_face_sdxl")

    # --- Package marker ---
    arch_cfg = json.loads(
        (repo_root / "configs/benchmarks/identity_architecture_benchmark.json").read_text(
            encoding="utf-8"
        )
    )
    _assert_equal("package 4.12.3", arch_cfg.get("package"), "4.12.3")
    _assert_equal(
        "InstantID status in manifest",
        (arch_cfg.get("architecture_status") or {}).get("instantid_sdxl_benchmark"),
        "BLOCKED_FOR_COMMERCIAL",
    )
    _pass(results, "Package 4.12.3 architecture manifest updated")

    print()
    passed = sum(1 for s, _ in results if s == "PASS")
    print(f"RESULT: {passed}/{len(results)} IP-Adapter Plus Face foundation simulations passed.")
    failed = [label for s, label in results if s != "PASS"]
    if failed:
        print("FAILED:", "; ".join(failed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
