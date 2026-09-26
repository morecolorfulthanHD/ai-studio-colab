#!/usr/bin/env python3
"""Package 4.12.3 — IP-Adapter Plus Face prototype foundation simulations.

Deterministic CODE/SIM checks (no Colab / no downloads / no GPU):
  - InstantID remains BLOCKED_FOR_COMMERCIAL / promotion_allowed=false
  - ipadapter_plus_face_sdxl architecture resolves
  - no InsightFace on Plus Face path
  - FaceID rejected on Plus Face graph
  - asset fail-closed without local files (published SHA/revision pins)
  - license ACCEPTABLE for PATH C components; promotion_allowed always false
  - focused license-gate: REVIEW_REQUIRED / FaceID fail closed
  - InstantID independently blocked
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

    # --- Asset fail-closed (hashes pinned; files absent → not ready) ---
    assets = assess_ipadapter_plus_face_asset_readiness(
        drive_root=Path(tempfile.gettempdir()),
        bundle_models=list(bundle_all.models),
    )
    _assert_true("assets not ready without local files", not assets.get("ready"))
    err_blob = " ".join(assets.get("errors") or [])
    _assert_true(
        "missing/unverified assets fail closed",
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
    _assert_equal(
        "plus-face immutable revision",
        plus.get("revision"),
        "018e402774aeeddd60609b4ecdb7e298259dc729",
    )
    clip = by_name.get("clip_vision_vit_h_openclip") or {}
    _assert_equal(
        "clip sha published",
        clip.get("expected_sha256"),
        "6ca9667da1ca9e0b0f75e46bb030f7e011f44f86cbfb8d5a36590fcd7507b030",
    )
    _assert_equal(
        "clip immutable revision",
        clip.get("revision"),
        "018e402774aeeddd60609b4ecdb7e298259dc729",
    )
    sdxl = by_name.get("sdxl_base") or {}
    _assert_equal(
        "sdxl published LFS sha",
        sdxl.get("expected_sha256"),
        "31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b",
    )
    _assert_equal("sdxl size", sdxl.get("expected_size_bytes"), 6938078334)
    _assert_equal(
        "sdxl immutable revision",
        sdxl.get("revision"),
        "462165984030d82259a11f4367a4eed129e94a7b",
    )
    _assert_equal("sdxl pin_state", sdxl.get("pin_state"), "PUBLISHED_UPSTREAM_SHA")
    _pass(results, "asset fail-closed without files; published SHA/revision pins")

    # --- License gate: ACCEPTABLE components, promotion_allowed always false ---
    lic = assess_ipadapter_plus_face_license_gate(repo_root)
    _assert_equal("IP-Adapter promotion_allowed false", lic.get("promotion_allowed"), False)
    _assert_equal("license overall ACCEPTABLE", lic.get("overall_status"), "ACCEPTABLE")
    _assert_true("license_ready when all ACCEPTABLE", bool(lic.get("license_ready")))
    for cname in (
        "ComfyUI_IPAdapter_plus_node",
        "ipadapter_plus_face_sdxl_vit_h",
        "clip_vision_vit_h_openclip",
        "sdxl_base",
    ):
        crow = (lic.get("components") or {}).get(cname) or {}
        _assert_equal(f"{cname} ACCEPTABLE", crow.get("status"), "ACCEPTABLE")
        _assert_true(
            f"{cname} no paid license",
            crow.get("paid_license_required") in (False, None)
            or crow.get("paid_license_required") is False,
        )
    for forbidden_name in (
        "insightface_antelopev2",
        "ipadapter_faceid",
        "instantid",
        "pulid",
        "photomaker_v2",
        "flux_dev",
    ):
        frow = (lic.get("components") or {}).get(forbidden_name) or {}
        _assert_equal(f"{forbidden_name} FORBIDDEN", frow.get("status"), "FORBIDDEN")
    sdxl_lic = (lic.get("components") or {}).get("sdxl_base") or {}
    _assert_equal("SDXL commercial OK status", sdxl_lic.get("status"), "ACCEPTABLE")
    _assert_equal("SDXL paid license no", sdxl_lic.get("paid_license_required"), False)
    plus_lic = (lic.get("components") or {}).get("ipadapter_plus_face_sdxl_vit_h") or {}
    _assert_true("Plus Face not FaceID flag", plus_lic.get("not_faceid") is True)
    _pass(results, "license ACCEPTABLE; promotion_allowed false; zero paid")

    # --- Focused license-gate simulation (temp REVIEW / FORBIDDEN / FaceID) ---
    with tempfile.TemporaryDirectory() as lic_td:
        fake_root = Path(lic_td)
        lic_dir = fake_root / "configs" / "benchmarks"
        lic_dir.mkdir(parents=True)
        # REVIEW_REQUIRED blocks license_ready
        review_payload = {
            "architecture": "ipadapter_plus_face_sdxl",
            "promotion_allowed": False,
            "components": {
                "ComfyUI_IPAdapter_plus_node": {"status": "REVIEW_REQUIRED"},
                "ipadapter_plus_face_sdxl_vit_h": {"status": "ACCEPTABLE"},
                "clip_vision_vit_h_openclip": {"status": "ACCEPTABLE"},
                "sdxl_base": {"status": "ACCEPTABLE", "commercially_ok": True},
            },
        }
        (lic_dir / "identity_architecture_ipadapter_plus_face_licenses.json").write_text(
            json.dumps(review_payload), encoding="utf-8"
        )
        review_gate = assess_ipadapter_plus_face_license_gate(fake_root)
        _assert_equal(
            "REVIEW_REQUIRED overall", review_gate.get("overall_status"), "REVIEW_REQUIRED"
        )
        _assert_true("REVIEW not license_ready", not review_gate.get("license_ready"))
        _assert_equal("REVIEW promo false", review_gate.get("promotion_allowed"), False)

        # FaceID as active (non-FORBIDDEN) component → fail closed
        faceid_payload = {
            "architecture": "ipadapter_plus_face_sdxl",
            "promotion_allowed": True,
            "components": {
                "ComfyUI_IPAdapter_plus_node": {"status": "ACCEPTABLE"},
                "ipadapter_plus_face_sdxl_vit_h": {"status": "ACCEPTABLE"},
                "clip_vision_vit_h_openclip": {"status": "ACCEPTABLE"},
                "sdxl_base": {"status": "ACCEPTABLE"},
                "ipadapter_faceid_plus": {
                    "status": "ACCEPTABLE",
                    "source": "https://huggingface.co/h94/IP-Adapter-FaceID",
                },
            },
        }
        (lic_dir / "identity_architecture_ipadapter_plus_face_licenses.json").write_text(
            json.dumps(faceid_payload), encoding="utf-8"
        )
        faceid_gate = assess_ipadapter_plus_face_license_gate(fake_root)
        _assert_equal(
            "FaceID active → BLOCKED",
            faceid_gate.get("overall_status"),
            "BLOCKED_FOR_COMMERCIAL",
        )
        _assert_equal("FaceID promo false", faceid_gate.get("promotion_allowed"), False)
        _assert_true("FaceID errors present", bool(faceid_gate.get("errors")))
    _pass(results, "focused license-gate: REVIEW blocks; FaceID fail-closed")

    # --- Authoritative preflight: licenses ok; assets still fail closed ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "AI_Studio").mkdir(parents=True)
        (root / "ComfyUI" / "custom_nodes").mkdir(parents=True)
        (root / "runtime").mkdir(parents=True)
        fake = _Bundle(repo_root, list(bundle_all.models), list(bundle_all.nodes), root)
        pre = run_ipadapter_plus_face_preflight(
            repo_root, fake, require_live_comfy=False, workflow_data=wf
        )
        _assert_true("preflight fail closed without local assets", not pre.get("ok"))
        steps = {s["step"]: s for s in pre.get("steps") or []}
        _assert_true("architecture step ok", steps.get("architecture", {}).get("ok"))
        _assert_true("licenses step ok when ACCEPTABLE", steps.get("licenses", {}).get("ok"))
        _assert_true("no_forbidden_deps ok", steps.get("no_forbidden_deps", {}).get("ok"))
        _assert_true("sdxl_commercial_ok flag", pre.get("sdxl_commercial_ok") is True)
        _assert_equal(
            "preflight promotion_allowed false",
            (steps.get("licenses") or {}).get("promotion_allowed"),
            False,
        )
        _assert_true(
            "assets_hashes still fail",
            not (steps.get("assets_hashes") or {}).get("ok"),
        )
    _pass(results, "authoritative preflight: license-ready; assets fail closed")

    # --- Zero-paid forbidden dependency graph scan ---
    forbidden_tokens = (
        "insightface",
        "antelope",
        "buffalo",
        "faceid",
        "instantid",
        "pulid",
        "photomaker",
        "flux.dev",
        "flux_dev",
    )
    graph_blobs = []
    for name in REQUIRED_MODEL_NAMES:
        row = by_name.get(name) or {}
        graph_blobs.append(
            " ".join(
                str(row.get(k) or "")
                for k in (
                    "name",
                    "filename",
                    "source_url",
                    "source_path",
                    "runtime_path",
                    "intended_path",
                )
            ).lower()
        )
    graph_blobs.append(" ".join(ip.spec.required_assets).lower())
    graph_blobs.append(" ".join(ip.spec.required_custom_nodes).lower())
    wf_types = " ".join(
        str(n.get("type") or "") for n in wf.get("nodes") or [] if isinstance(n, dict)
    ).lower()
    graph_blobs.append(wf_types)
    joined = " ".join(graph_blobs)
    for excl in ("non-faceid", "non_faceid"):
        joined = joined.replace(excl, " ")
    hits = [t for t in forbidden_tokens if t in joined]
    _assert_equal("zero forbidden tokens on PATH C graph", hits, [])
    _pass(results, "zero-paid forbidden scan clean on PATH C dependency graph")

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
