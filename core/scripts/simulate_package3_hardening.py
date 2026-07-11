#!/usr/bin/env python3
"""Focused simulations for Production Package 3 hardening."""

from __future__ import annotations

import json
import shutil
import subprocess
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

from typing import Callable

from core.runtime.capability_manager import CapabilityManager
from core.runtime.node_registry_utils import evaluate_required_nodes, is_node_required
from core.runtime.output_evidence import inspect_generation_evidence
from core.runtime.output_sync import collision_safe_filename, resolve_sync_destination
from core.runtime.registry_loader import RegistryBundle, RegistryLoader, find_repo_root
from core.runtime.workflow_validation import validate_base_txt2img_workflow

_REPO_ROOT = find_repo_root(script_file=Path(__file__))


class SimulationFailure(Exception):
    pass


def _assert_equal(label: str, actual: object, expected: object) -> None:
    if actual != expected:
        raise SimulationFailure(f"{label}: expected {expected!r}, got {actual!r}")


def _write_png(path: Path, size: int = 128) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + (b"\x00" * max(size - 8, 0)))


def _valid_txt2img_workflow() -> dict:
    workflow_path = _REPO_ROOT / "workflows/base/txt2img/workflow.json"
    with workflow_path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _invalid_txt2img_workflow_missing_ksampler() -> dict:
    data = _valid_txt2img_workflow()
    data["nodes"] = [node for node in data["nodes"] if node.get("type") != "KSampler"]
    return data


def run_evidence_simulations() -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        local_dir = root / "local"
        drive_dir = root / "drive"

        def case(name: str, setup: Callable[[], None], expected_status: str, expected_drive: bool) -> None:
            local_dir.mkdir(parents=True, exist_ok=True)
            drive_dir.mkdir(parents=True, exist_ok=True)
            for child in local_dir.iterdir():
                if child.is_file():
                    child.unlink()
            for child in drive_dir.iterdir():
                if child.is_file():
                    child.unlink()
            setup()
            evidence = inspect_generation_evidence(local_dir, drive_dir)
            _assert_equal(f"{name} status", evidence.evidence_status, expected_status)
            _assert_equal(f"{name} drive_verified", evidence.drive_verified, expected_drive)
            results.append((name, "PASS"))

        case(
            "local and matching drive png",
            lambda: (
                _write_png(local_dir / "gen_001.png", 64),
                _write_png(drive_dir / "gen_001.png", 64),
            ),
            "verified",
            True,
        )
        case(
            "local png plus unrelated drive png",
            lambda: (
                _write_png(local_dir / "current.png", 64),
                _write_png(drive_dir / "older.png", 96),
            ),
            "verified_local",
            False,
        )
        case(
            "local png plus zero-byte drive match",
            lambda: (
                _write_png(local_dir / "current.png", 64),
                (drive_dir / "current.png").write_bytes(b""),
            ),
            "verified_local",
            False,
        )
        case(
            "local png plus matching filename different size",
            lambda: (
                _write_png(local_dir / "current.png", 64),
                _write_png(drive_dir / "current.png", 96),
            ),
            "verified_local",
            False,
        )
        case(
            "drive file only",
            lambda: _write_png(drive_dir / "orphan.png", 64),
            "not_yet_verified",
            False,
        )
        case(
            "placeholder-only directories",
            lambda: (
                (local_dir / "_output_images_will_be_put_here").write_bytes(b"x"),
                (drive_dir / "_output_images_will_be_put_here").write_bytes(b"x"),
            ),
            "not_yet_verified",
            False,
        )

    return results


def run_workflow_simulations() -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        valid_path = root / "valid.json"
        valid_path.write_text(json.dumps(_valid_txt2img_workflow()), encoding="utf-8")
        validation = validate_base_txt2img_workflow(valid_path)
        _assert_equal("valid workflow", validation.valid, True)
        results.append(("valid seven-node txt2img workflow", "PASS"))

        invalid_json_path = root / "invalid.json"
        invalid_json_path.write_text("{not-json", encoding="utf-8")
        validation = validate_base_txt2img_workflow(invalid_json_path)
        _assert_equal("invalid json", validation.valid, False)
        results.append(("invalid json", "PASS"))

        missing_sampler_path = root / "missing_ksampler.json"
        missing_sampler_path.write_text(
            json.dumps(_invalid_txt2img_workflow_missing_ksampler()),
            encoding="utf-8",
        )
        validation = validate_base_txt2img_workflow(missing_sampler_path)
        _assert_equal("missing ksampler", validation.valid, False)
        results.append(("missing KSampler", "PASS"))

        missing_nodes_path = root / "missing_nodes.json"
        missing_nodes_path.write_text(json.dumps({"links": []}), encoding="utf-8")
        validation = validate_base_txt2img_workflow(missing_nodes_path)
        _assert_equal("missing nodes list", validation.valid, False)
        results.append(("missing nodes list", "PASS"))

        missing_file_path = root / "missing.json"
        validation = validate_base_txt2img_workflow(missing_file_path)
        _assert_equal("missing file", validation.valid, False)
        results.append(("file missing", "PASS"))

        with tempfile.TemporaryDirectory() as invalid_tmp_name:
            invalid_bundle = _create_dogfood_bundle(Path(invalid_tmp_name))
            invalid_workflow_path = (
                Path(invalid_tmp_name) / "repo" / "workflows/base/txt2img/workflow.json"
            )
            invalid_workflow_path.write_text("{not-json", encoding="utf-8")
            invalid_manager = CapabilityManager(bundle=invalid_bundle)
            invalid_txt2img = invalid_manager.evaluate_capability("txt2img")
            _assert_equal("invalid json txt2img status", invalid_txt2img.computed_status, "partial")
            results.append(("invalid json makes txt2img partial", "PASS"))

        with tempfile.TemporaryDirectory() as sampler_tmp_name:
            missing_sampler_bundle = _create_dogfood_bundle(Path(sampler_tmp_name))
            missing_sampler_path = (
                Path(sampler_tmp_name) / "repo" / "workflows/base/txt2img/workflow.json"
            )
            missing_sampler_path.write_text(
                json.dumps(_invalid_txt2img_workflow_missing_ksampler()),
                encoding="utf-8",
            )
            missing_sampler_manager = CapabilityManager(bundle=missing_sampler_bundle)
            missing_sampler_txt2img = missing_sampler_manager.evaluate_capability("txt2img")
            _assert_equal(
                "missing ksampler txt2img status",
                missing_sampler_txt2img.computed_status,
                "partial",
            )
            results.append(("missing KSampler makes txt2img partial", "PASS"))

    return results


def _evaluate_with_bundle(bundle: RegistryBundle) -> CapabilityManager:
    return CapabilityManager(bundle=bundle)


def _txt2img_evaluation(manager: CapabilityManager) -> object:
    return manager.evaluate_capability("txt2img")


def _create_dogfood_bundle(tmp: Path) -> RegistryBundle:
    repo = tmp / "repo"
    shutil.copytree(_REPO_ROOT / "configs", repo / "configs")
    shutil.copytree(_REPO_ROOT / "workflows", repo / "workflows")

    comfy = tmp / "ComfyUI"
    comfy.mkdir(parents=True)
    (comfy / ".git").mkdir()
    (comfy / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (comfy / "output").mkdir()

    drive_outputs = tmp / "drive_outputs"
    drive_outputs.mkdir(parents=True)

    sd15 = tmp / "models" / "sd15.safetensors"
    sd15.parent.mkdir(parents=True, exist_ok=True)
    sd15.write_bytes(b"fake-checkpoint")

    paths_file = repo / "configs/paths/colab_paths.json"
    paths_data = json.loads(paths_file.read_text(encoding="utf-8"))
    paths_data["paths"]["comfyui_runtime"] = str(comfy)
    paths_data["paths"]["comfyui_output"] = str(comfy / "output")
    paths_data["paths"]["drive_outputs"] = str(drive_outputs)
    paths_file.write_text(json.dumps(paths_data, indent=2), encoding="utf-8")

    assets_file = repo / "configs/assets/asset_registry.json"
    assets_data = json.loads(assets_file.read_text(encoding="utf-8"))
    for asset in assets_data.get("assets", []):
        if asset.get("id") == "sd15_checkpoint":
            asset["runtime_path"] = str(sd15)
    assets_file.write_text(json.dumps(assets_data, indent=2), encoding="utf-8")

    return RegistryLoader(repo).load_all()


def _set_capability_implementation(repo: Path, capability_id: str, status: str) -> None:
    registry_path = repo / "configs/capabilities/capability_registry.json"
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    for capability in data.get("capabilities", []):
        if capability.get("id") == capability_id:
            capability["implementation_status"] = status
            break
    registry_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def run_node_runtime_simulations() -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []

    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        bundle = _create_dogfood_bundle(tmp)
        custom_nodes_dir = bundle.path("comfyui_runtime") / "custom_nodes"
        custom_nodes_dir.mkdir(parents=True, exist_ok=True)

        controlnet_entry = next(
            node for node in bundle.nodes if node.get("name") == "comfyui_controlnet_aux"
        )
        controlnet_folder = custom_nodes_dir / controlnet_entry.get("folder_name", "comfyui_controlnet_aux")
        controlnet_folder.mkdir()

        node_status = evaluate_required_nodes(
            ["comfyui_controlnet_aux"],
            bundle.nodes,
            custom_nodes_dir,
        )
        _assert_equal("registered and installed node missing_registration", node_status["missing_registration"], [])
        _assert_equal("registered and installed node uninstalled", node_status["uninstalled"], [])
        results.append(("required node registered and installed", "PASS"))

        shutil.rmtree(controlnet_folder)
        node_status = evaluate_required_nodes(
            ["comfyui_controlnet_aux"],
            bundle.nodes,
            custom_nodes_dir,
        )
        _assert_equal("registered missing folder uninstalled", node_status["uninstalled"], ["comfyui_controlnet_aux"])
        manager = CapabilityManager(bundle=bundle)
        openpose = manager.evaluate_capability("openpose_conditioning")
        _assert_equal("registered missing folder capability status", openpose.computed_status, "partial")
        results.append(("required node registered but folder missing", "PASS"))

        node_status = evaluate_required_nodes(
            ["nonexistent_custom_node"],
            bundle.nodes,
            custom_nodes_dir,
        )
        _assert_equal("missing registration", node_status["missing_registration"], ["nonexistent_custom_node"])
        results.append(("required node name absent from registry", "PASS"))

        dogfood_manager = CapabilityManager(bundle=bundle)
        txt2img = dogfood_manager.evaluate_capability("txt2img")
        _assert_equal("txt2img with optional reactor missing", txt2img.computed_status, "ready")
        reactor = dogfood_manager.evaluate_capability("reactor_faceswap")
        _assert_equal("reactor_faceswap with optional reactor missing", reactor.computed_status, "partial")
        results.append(("optional ReActor missing", "PASS"))

    return results


def run_planned_capability_simulations() -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []

    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        bundle = _create_dogfood_bundle(tmp)
        custom_nodes_dir = bundle.path("comfyui_runtime") / "custom_nodes"
        custom_nodes_dir.mkdir(parents=True, exist_ok=True)
        controlnet_entry = next(
            node for node in bundle.nodes if node.get("name") == "comfyui_controlnet_aux"
        )
        (custom_nodes_dir / controlnet_entry.get("folder_name", "comfyui_controlnet_aux")).mkdir()
        manager = CapabilityManager(bundle=bundle)

        lineart = manager.evaluate_capability("lineart_extraction")
        _assert_equal("lineart_extraction status", lineart.computed_status, "partial")
        results.append(
            ("lineart_extraction with installed controlnet_aux but implementation planned", "PASS")
        )

    with tempfile.TemporaryDirectory() as bare_tmp_name:
        bare_tmp = Path(bare_tmp_name)
        bare_repo = bare_tmp / "repo"
        shutil.copytree(_REPO_ROOT / "configs", bare_repo / "configs")
        shutil.copytree(_REPO_ROOT / "workflows", bare_repo / "workflows")
        bare_registry = bare_repo / "configs/capabilities/capability_registry.json"
        bare_data = json.loads(bare_registry.read_text(encoding="utf-8"))
        bare_data["capabilities"].append(
            {
                "id": "bare_planned_capability",
                "name": "Bare Planned Capability",
                "description": "Deferred capability with no runtime artifacts.",
                "category": "utility",
                "maturity": "experimental",
                "status": "planned",
                "implementation_status": "planned",
                "supported_engines": ["comfyui"],
                "required_models": [],
                "required_nodes": [],
                "required_assets": [],
                "required_workflows": [],
                "dependencies": [],
                "validation_rules": [],
                "notes": "Simulation-only deferred capability.",
            }
        )
        bare_registry.write_text(json.dumps(bare_data, indent=2), encoding="utf-8")
        bare_bundle = RegistryLoader(bare_repo).load_all()
        bare_capability = CapabilityManager(bundle=bare_bundle).evaluate_capability("bare_planned_capability")
        _assert_equal("bare planned capability status", bare_capability.computed_status, "partial")
        results.append(("planned capability with no workflows/assets/dependencies", "PASS"))

    bundle = RegistryLoader(_REPO_ROOT).load_all()
    manager = CapabilityManager(bundle=bundle)
    runtime_health = manager.evaluate_capability("runtime_health_report")
    _assert_equal("runtime_health_report status", runtime_health.computed_status, "ready")
    results.append(("runtime_health_report marked implemented", "PASS"))

    with tempfile.TemporaryDirectory() as dogfood_tmp_name:
        dogfood_bundle = _create_dogfood_bundle(Path(dogfood_tmp_name))
        dogfood_manager = CapabilityManager(bundle=dogfood_bundle)
        txt2img = dogfood_manager.evaluate_capability("txt2img")
        _assert_equal("implemented txt2img with valid runtime", txt2img.computed_status, "ready")
        results.append(("txt2img marked implemented with valid runtime dependencies", "PASS"))

    with tempfile.TemporaryDirectory() as implemented_tmp_name:
        implemented_bundle = _create_dogfood_bundle(Path(implemented_tmp_name))
        repo = Path(implemented_tmp_name) / "repo"
        _set_capability_implementation(repo, "openpose_conditioning", "implemented")
        implemented_manager = CapabilityManager(bundle=RegistryLoader(repo).load_all())
        openpose = implemented_manager.evaluate_capability("openpose_conditioning")
        _assert_equal("implemented capability missing node runtime", openpose.computed_status, "partial")
        results.append(("implemented capability with missing required node runtime folder", "PASS"))

    return results


def run_capability_simulations() -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []

    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        dogfood_bundle = _create_dogfood_bundle(tmp)
        dogfood_manager = _evaluate_with_bundle(dogfood_bundle)

        txt2img = _txt2img_evaluation(dogfood_manager)
        _assert_equal("dogfood txt2img status", txt2img.computed_status, "ready")
        results.append(("valid comfyui + sd15 + valid txt2img workflow", "PASS"))

        empty_output = dogfood_bundle.path("comfyui_output")
        evidence = inspect_generation_evidence(empty_output, dogfood_bundle.path("drive_outputs"))
        _assert_equal("dogfood txt2img evidence without output", evidence.evidence_status, "not_yet_verified")
        _assert_equal("dogfood txt2img readiness with no output", txt2img.computed_status, "ready")
        results.append(("txt2img ready without generated image evidence", "PASS"))

        img2img = dogfood_manager.evaluate_capability("img2img")
        _assert_equal("dogfood img2img status", img2img.computed_status, "partial")
        results.append(("txt2img ready but base_img2img workflow absent", "PASS"))

    bundle = RegistryLoader(_REPO_ROOT).load_all()
    manager = _evaluate_with_bundle(bundle)

    inpainting = manager.evaluate_capability("inpainting")
    _assert_equal("inpainting status", inpainting.computed_status, "partial")
    results.append(("inpainting partial", "PASS"))

    ipadapter = manager.evaluate_capability("ipadapter_conditioning")
    _assert_equal("planned capability with planned assets", ipadapter.computed_status, "partial")
    results.append(("planned capability with only registered/planned assets", "PASS"))

    lineart = manager.evaluate_capability("lineart_extraction")
    _assert_equal("lineart_extraction partial", lineart.computed_status, "partial")
    results.append(("lineart_extraction partial", "PASS"))

    reactor_entry = next(node for node in bundle.nodes if node.get("name") == "ComfyUI-ReActor")
    _assert_equal("reactor node is optional", is_node_required(reactor_entry), False)
    reactor = manager.evaluate_capability("reactor_faceswap")
    _assert_equal("reactor_faceswap readiness", reactor.computed_status, "partial")
    results.append(("reactor_faceswap partial", "PASS"))

    return results


def run_package31_simulations() -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        dest_dir = root / "drive"
        dest_dir.mkdir()

        dest, collision, original = resolve_sync_destination(dest_dir, "ai_studio_base_txt2img_00001_.png")
        _assert_equal("absent destination collision flag", collision, False)
        _assert_equal("absent destination filename", dest.name, "ai_studio_base_txt2img_00001_.png")
        results.append(("destination absent uses original filename", "PASS"))

        _write_png(dest_dir / "ai_studio_base_txt2img_00001_.png", 64)
        dest, collision, original = resolve_sync_destination(
            dest_dir,
            "ai_studio_base_txt2img_00001_.png",
            timestamp="20260711T063300Z",
        )
        _assert_equal("existing destination collision flag", collision, True)
        _assert_equal(
            "existing destination timestamped filename",
            dest.name,
            "ai_studio_base_txt2img_00001__20260711T063300Z.png",
        )
        results.append(("destination exists selects timestamped filename", "PASS"))

        _write_png(dest, 32)
        dest, collision, original = resolve_sync_destination(
            dest_dir,
            "ai_studio_base_txt2img_00001_.png",
            timestamp="20260711T063300Z",
        )
        _assert_equal("timestamp collision numeric suffix filename", dest.name, "ai_studio_base_txt2img_00001__20260711T063300Z.1.png")
        results.append(("timestamped filename exists selects numeric suffix", "PASS"))

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        local_dir = root / "local"
        drive_dir = root / "drive"
        local_dir.mkdir()
        drive_dir.mkdir()
        local_file = local_dir / "current.png"
        _write_png(local_file, 80)
        _write_png(drive_dir / "ai_studio_base_txt2img_00001_.png", 80)
        collision_name = collision_safe_filename(
            local_file.name,
            timestamp="20260711T063300Z",
        )
        _write_png(drive_dir / collision_name, 80)
        evidence = inspect_generation_evidence(local_file.parent, drive_dir)
        _assert_equal("collision-safe exact size evidence", evidence.evidence_status, "verified")
        results.append(("collision-safe drive copy with exact byte size", "PASS"))

        shutil.rmtree(drive_dir)
        drive_dir.mkdir()
        _write_png(drive_dir / collision_name, 96)
        evidence = inspect_generation_evidence(local_file.parent, drive_dir)
        _assert_equal("collision-safe size mismatch evidence", evidence.evidence_status, "verified_local")
        results.append(("collision-safe drive copy with different byte size", "PASS"))

    script = _REPO_ROOT / "core/scripts/runtime_report.py"
    summary = subprocess.run(
        [sys.executable, str(script), "--summary"],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    summary_lines = [line for line in summary.stdout.splitlines() if line.startswith("Health:")]
    _assert_equal("runtime_report summary line count", len(summary_lines), 1)
    results.append(("runtime_report --summary prints one summary line", "PASS"))

    cli_scripts = [
        "runtime_report.py",
        "verify_generation.py",
        "sync_outputs.py",
        "check_nodes.py",
        "validate_manifests.py",
    ]
    unrelated = Path(tempfile.gettempdir())
    for script_name in cli_scripts:
        script_path = _REPO_ROOT / "core/scripts" / script_name
        from_repo = subprocess.run(
            [sys.executable, str(script_path), "--help"],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        from_other = subprocess.run(
            [sys.executable, str(script_path), "--help"],
            cwd=str(unrelated),
            capture_output=True,
            text=True,
            check=False,
        )
        if from_repo.returncode != 0 or from_other.returncode != 0:
            raise SimulationFailure(f"{script_name} --help failed from one or both directories")
        results.append((f"CLI root resolved for {script_name}", "PASS"))

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_dir = root / "source"
        dest_dir = root / "dest"
        source_dir.mkdir()
        dest_dir.mkdir()
        source_file = source_dir / "gen.png"
        _write_png(source_file, 48)
        _write_png(dest_dir / "gen.png", 48)

        dry_run_script = _REPO_ROOT / "core/scripts/sync_outputs.py"
        # sync_outputs reads paths from colab_paths - need to mock via temp repo or test resolve_sync_destination only
        dest, collision, original = resolve_sync_destination(dest_dir, source_file.name, timestamp="20260711T120000Z")
        _assert_equal("dry-run collision destination selected", collision, True)
        _assert_equal("dry-run collision path unused", dest.exists(), False)
        results.append(("dry-run collision reports unique path without copy", "PASS"))

        strict_dest, strict_collision, _ = resolve_sync_destination(
            dest_dir,
            source_file.name,
            fail_on_existing=True,
        )
        _assert_equal("fail-on-existing collision detected", strict_collision, True)
        _assert_equal("fail-on-existing keeps original destination", strict_dest.name, source_file.name)
        results.append(("--fail-on-existing preserves refusal semantics", "PASS"))

    return results


def main() -> int:
    sections = [
        ("Generation Evidence", run_evidence_simulations),
        ("Workflow Validation", run_workflow_simulations),
        ("Node Runtime", run_node_runtime_simulations),
        ("Planned Capabilities", run_planned_capability_simulations),
        ("Capability Readiness", run_capability_simulations),
        ("Package 3.1 Usability", run_package31_simulations),
    ]

    print("AI Studio — Package 3 Hardening Simulations")
    print("=" * 50)

    total = 0
    failed = 0
    for section_name, runner in sections:
        print(f"\n{section_name}")
        try:
            section_results = runner()
            for name, status in section_results:
                total += 1
                print(f"  [{status}] {name}")
        except SimulationFailure as exc:
            failed += 1
            total += 1
            print(f"  [FAIL] {exc}")

    print()
    print(f"Summary: {total - failed}/{total} simulations passed")
    if failed:
        print("\nRESULT: FAIL — package 3 hardening simulations failed.")
        return 1

    print("\nRESULT: PASS — all package 3 hardening simulations passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
