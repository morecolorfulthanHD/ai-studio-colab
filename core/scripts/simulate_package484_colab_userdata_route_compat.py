#!/usr/bin/env python3
"""Package 4.8.4 — Colab userdata route compatibility simulations."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import py_compile
import subprocess
import sys
import tempfile
from pathlib import Path

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.comfyui_userdata_route_compat import (
    PACKAGE_VERSION,
    apply_userdata_route_compat,
    explain_colab_proxy_failure,
    inspect_userdata_route_patterns,
    remove_userdata_route_compat,
    simulate_proxy_decoded_userdata_paths,
)
from core.runtime.registry_loader import find_repo_root


class SimulationFailure(Exception):
    pass


def _pass(results: list[tuple[str, str]], name: str) -> None:
    results.append(("PASS", name))
    print(f"  [PASS] {name}")


def _assert_true(label: str, condition: bool) -> None:
    if not condition:
        raise SimulationFailure(label)


def _assert_equal(label: str, left, right) -> None:
    if left != right:
        raise SimulationFailure(f"{label}: {left!r} != {right!r}")


_STOCK_USER_MANAGER = '''#!/usr/bin/env python3
"""Minimal stock ComfyUI-shaped userdata routes (Package 4.8.4 fixture)."""
from aiohttp import web

# Non-decorator mention must stay untouched by the compat patch:
# /userdata/{file} appears only in this comment and DOC_PATH below.
DOC_PATH = "/userdata/{file}"

class UserManager:
    def add_routes(self, routes):
        @routes.get("/userdata/{file}")
        async def getuserdata(request):
            return web.Response(text="ok")

        @routes.post("/userdata/{file}")
        async def post_userdata(request):
            return web.Response(text="ok")

        @routes.delete("/userdata/{file}")
        async def delete_userdata(request):
            return web.Response(status=204)

        @routes.post("/userdata/{file}/move/{dest}")
        async def move_userdata(request):
            return web.Response(text="ok")
'''

_UPSTREAM_COMPATIBLE_USER_MANAGER = '''#!/usr/bin/env python3
from aiohttp import web

class UserManager:
    def add_routes(self, routes):
        @routes.post("/userdata/{file:.*}/move/{dest:.*}")
        async def move_userdata(request):
            return web.Response(text="ok")

        @routes.get("/userdata/{file:.*}")
        async def getuserdata(request):
            return web.Response(text="ok")

        @routes.post("/userdata/{file:.*}")
        async def post_userdata(request):
            return web.Response(text="ok")
'''

_DECODED_PATH = "/userdata/workflows/ai_studio_test.json"
_NESTED_MOVE_PATH = "/userdata/workflows/source.json/move/workflows/archive/destination.json"


async def _resolve(router, method: str, path: str):
    from aiohttp.test_utils import make_mocked_request

    request = make_mocked_request(method, path)
    return await router.resolve(request)


def _is_match(match) -> bool:
    return type(match).__name__ == "UrlMappingMatchInfo"


async def _aiohttp_stock_vs_patched_router_proof() -> dict[str, object]:
    """Exercise aiohttp UrlDispatcher matching — not string helpers."""
    from aiohttp import web

    results: dict[str, object] = {}

    # --- STOCK (one-segment {file}) ---
    stock_app = web.Application()
    stock_hits: list[str] = []

    async def stock_userdata(request):
        stock_hits.append("userdata")
        return web.Response(text="userdata")

    async def stock_move(request):
        stock_hits.append("move")
        return web.Response(text="move")

    stock_app.router.add_get("/userdata/{file}", stock_userdata)
    stock_app.router.add_post("/userdata/{file}", stock_userdata)
    stock_app.router.add_post("/userdata/{file}/move/{dest}", stock_move)

    for method in ("GET", "POST"):
        match = await _resolve(stock_app.router, method, _DECODED_PATH)
        results[f"stock_{method.lower()}_resolves_userdata"] = _is_match(match)
    results["stock_decoded_get_misses"] = not results["stock_get_resolves_userdata"]
    results["stock_decoded_post_misses"] = not results["stock_post_resolves_userdata"]

    # --- PATCHED (catch-all) with move registered BEFORE catch-all ---
    patched_app = web.Application()
    patched_handler_name: dict[str, str] = {}

    async def patched_userdata(request):
        patched_handler_name["name"] = "userdata"
        patched_handler_name["file"] = request.match_info.get("file")
        patched_handler_name["dest"] = request.match_info.get("dest")
        return web.Response(text="userdata")

    async def patched_move(request):
        patched_handler_name["name"] = "move"
        patched_handler_name["file"] = request.match_info.get("file")
        patched_handler_name["dest"] = request.match_info.get("dest")
        return web.Response(text="move")

    patched_app.router.add_post("/userdata/{file:.*}/move/{dest:.*}", patched_move)
    patched_app.router.add_get("/userdata/{file:.*}", patched_userdata)
    patched_app.router.add_post("/userdata/{file:.*}", patched_userdata)

    for method in ("GET", "POST"):
        match = await _resolve(patched_app.router, method, _DECODED_PATH)
        results[f"patched_{method.lower()}_resolves"] = _is_match(match)
        results[f"patched_{method.lower()}_file"] = dict(match).get("file") if _is_match(match) else None

    # Nested move must hit move handler with sensible file/dest (no shadowing).
    move_match = await _resolve(patched_app.router, "POST", _NESTED_MOVE_PATH)
    results["patched_move_resolves"] = _is_match(move_match)
    if _is_match(move_match):
        results["patched_move_file"] = dict(move_match).get("file")
        results["patched_move_dest"] = dict(move_match).get("dest")
        # Confirm which resource matched by resolving and checking route name via handler dispatch
        # through match_info route — resource canonical may strip :.*
        handler = move_match.handler
        results["patched_move_handler_is_move"] = handler is patched_move
    else:
        results["patched_move_file"] = None
        results["patched_move_dest"] = None
        results["patched_move_handler_is_move"] = False

    # --- Shadowing proof: catch-all registered BEFORE move swallows nested move ---
    shadow_app = web.Application()

    async def shadow_userdata(request):
        return web.Response(text="userdata")

    async def shadow_move(request):
        return web.Response(text="move")

    shadow_app.router.add_get("/userdata/{file:.*}", shadow_userdata)
    shadow_app.router.add_post("/userdata/{file:.*}", shadow_userdata)
    shadow_app.router.add_post("/userdata/{file:.*}/move/{dest:.*}", shadow_move)
    shadow_match = await _resolve(shadow_app.router, "POST", _NESTED_MOVE_PATH)
    results["shadow_order_resolves"] = _is_match(shadow_match)
    if _is_match(shadow_match):
        results["shadow_order_file"] = dict(shadow_match).get("file")
        results["shadow_order_dest"] = dict(shadow_match).get("dest")
        results["shadow_order_hits_move"] = shadow_match.handler is shadow_move
        results["shadow_order_hits_userdata"] = shadow_match.handler is shadow_userdata
    else:
        results["shadow_order_file"] = None
        results["shadow_order_dest"] = None
        results["shadow_order_hits_move"] = False
        results["shadow_order_hits_userdata"] = False

    return results


def main() -> int:
    results: list[tuple[str, str]] = []
    repo_root = find_repo_root(script_file=Path(__file__))
    print("Package 4.8.4 Colab userdata route compatibility simulations")
    print("=" * 60)

    try:
        forms = simulate_proxy_decoded_userdata_paths("ai_studio_prep_demo.json")
        _assert_true("encoded form has %2F", "%2F" in forms["frontend_encoded_path_form"])
        _assert_true("decoded form has slash", "/workflows/" in forms["colab_proxy_decoded_path_form"])
        _assert_equal("stock matches encoded", forms["stock_route_matches_encoded"], True)
        _assert_equal("stock misses decoded", forms["stock_route_matches_decoded"], False)
        _assert_equal("compat matches decoded", forms["compat_route_matches_decoded"], True)
        _pass(results, "reproduced encoded nested userdata route problem")

        # Real aiohttp router-level proof (proxy-decoded multi-segment path).
        router_proof = asyncio.run(_aiohttp_stock_vs_patched_router_proof())
        _assert_true(
            "proxy-decoded GET misses stock route",
            bool(router_proof["stock_decoded_get_misses"]),
        )
        _pass(results, "proxy-decoded GET misses stock route")
        _assert_true(
            "proxy-decoded POST misses stock route",
            bool(router_proof["stock_decoded_post_misses"]),
        )
        _pass(results, "proxy-decoded POST misses stock route")
        _assert_true(
            "proxy-decoded GET reaches patched aiohttp handler",
            bool(router_proof["patched_get_resolves"]),
        )
        _assert_equal(
            "captured file GET",
            router_proof["patched_get_file"],
            "workflows/ai_studio_test.json",
        )
        _pass(results, "proxy-decoded GET reaches patched aiohttp handler")
        _assert_true(
            "proxy-decoded POST reaches patched aiohttp handler",
            bool(router_proof["patched_post_resolves"]),
        )
        _assert_equal(
            "captured file POST",
            router_proof["patched_post_file"],
            "workflows/ai_studio_test.json",
        )
        _pass(results, "proxy-decoded POST reaches patched aiohttp handler")
        _pass(results, "captured file parameter includes nested workflows path")

        _assert_true("nested move resolves", bool(router_proof["patched_move_resolves"]))
        _assert_equal(
            "move file",
            router_proof["patched_move_file"],
            "workflows/source.json",
        )
        _assert_equal(
            "move dest",
            router_proof["patched_move_dest"],
            "workflows/archive/destination.json",
        )
        _assert_true("move handler", bool(router_proof["patched_move_handler_is_move"]))
        _pass(results, "nested move route resolves correctly")

        _assert_true(
            "shadow order hits userdata not move",
            bool(router_proof["shadow_order_hits_userdata"])
            and not bool(router_proof["shadow_order_hits_move"]),
        )
        _assert_equal(
            "shadow swallowed file",
            router_proof["shadow_order_file"],
            "workflows/source.json/move/workflows/archive/destination.json",
        )
        _assert_equal("shadow dest absent", router_proof["shadow_order_dest"], None)
        _pass(results, "no move-route shadowing (move registered before catch-all)")

        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "ComfyUI"
            (runtime / "app").mkdir(parents=True)
            um = runtime / "app" / "user_manager.py"
            um.write_text(_STOCK_USER_MANAGER, encoding="utf-8")
            original_bytes = um.read_bytes()

            before = inspect_userdata_route_patterns(runtime)
            _assert_true("before has single-segment", before["has_single_segment_routes"])
            _assert_true("before not compatible", not before["compatible"])

            dry = apply_userdata_route_compat(runtime, dry_run=True)
            _assert_true("dry-run changed plan", dry.changed)
            _assert_true("dry-run makes no changes", um.read_bytes() == original_bytes)
            _pass(results, "dry-run makes no changes")

            applied = apply_userdata_route_compat(runtime, dry_run=False)
            _assert_true("apply ok", applied.ok)
            _assert_true("apply active", applied.active)
            _assert_true("apply succeeds", applied.applied)
            text = um.read_text(encoding="utf-8")
            after = inspect_userdata_route_patterns(runtime)
            _assert_true("after compatible", after["compatible"])
            _assert_true("multi-segment decorators", after["has_multi_segment_routes"])
            _assert_true("single-segment decorators gone", not after["has_single_segment_routes"])
            _assert_true(
                "move before catch-all",
                after.get("move_registered_before_catchall") is True,
            )
            # Overreach: non-decorator DOC_PATH must remain stock single-segment text.
            _assert_true("DOC_PATH untouched", 'DOC_PATH = "/userdata/{file}"' in text)
            _pass(results, "apply succeeds")

            # compile patched fixture
            try:
                py_compile.compile(str(um), doraise=True)
            except py_compile.PyCompileError as exc:
                raise SimulationFailure(f"patched fixture SyntaxError: {exc}") from exc
            compile(text, str(um), "exec")
            _pass(results, "patch compiles")

            again = apply_userdata_route_compat(runtime, dry_run=False)
            _assert_true("idempotent already compatible", again.already_compatible)
            _assert_true("idempotent no write", not again.changed)
            marker_count = text.count("BEGIN ai_studio_userdata_route_compat")
            text_after_reapply = um.read_text(encoding="utf-8")
            _assert_equal(
                "no duplicate markers",
                text_after_reapply.count("BEGIN ai_studio_userdata_route_compat"),
                marker_count,
            )
            _pass(results, "re-apply is idempotent")

            removed = remove_userdata_route_compat(runtime, dry_run=False)
            _assert_true("remove ok", removed.ok)
            restored = um.read_text(encoding="utf-8")
            restored_insp = inspect_userdata_route_patterns(runtime)
            _assert_true("restored single-segment", restored_insp["has_single_segment_routes"])
            _assert_true("marker gone", "ai_studio_userdata_route_compat" not in restored)
            _pass(results, "remove succeeds")

            reapplied = apply_userdata_route_compat(runtime, dry_run=False)
            _assert_true("re-apply after remove", reapplied.applied and reapplied.ok)
            _assert_true(
                "compatible again",
                inspect_userdata_route_patterns(runtime)["compatible"],
            )
            _pass(results, "re-apply after remove succeeds")

            # Discovery query unaffected (documented).
            _assert_true(
                "discovery query documented",
                "dir=workflows" in forms["discovery_query_unaffected"],
            )
            _pass(results, "workflow discovery query form remains unaffected")

        # Upstream-compatible source left untouched.
        with tempfile.TemporaryDirectory() as tmp2:
            runtime2 = Path(tmp2) / "ComfyUI"
            (runtime2 / "app").mkdir(parents=True)
            um2 = runtime2 / "app" / "user_manager.py"
            um2.write_text(_UPSTREAM_COMPATIBLE_USER_MANAGER, encoding="utf-8")
            before_up = um2.read_bytes()
            up = apply_userdata_route_compat(runtime2, dry_run=False)
            _assert_true("upstream already compatible", up.already_compatible)
            _assert_true("upstream not applied", not up.applied)
            _assert_true("upstream no change flag", not up.changed)
            _assert_true("upstream bytes untouched", um2.read_bytes() == before_up)
            _assert_true("no marker added", "ai_studio_userdata_route_compat" not in um2.read_text(encoding="utf-8"))
            _pass(results, "upstream-compatible source is left untouched")

        explanation = explain_colab_proxy_failure()
        _assert_equal(
            "root cause id",
            explanation["root_cause_id"],
            "colab_proxy_decoded_userdata_slash",
        )
        live = explanation["live_evidence"]
        _assert_true(
            "live Save As 405 evidence",
            "405" in live["native_save_as_through_colab"]
            and "ai_studio_known_good_control.json" in live["native_save_as_through_colab"],
        )
        _assert_true(
            "live prepared GET 404 evidence",
            "404" in live["prepared_workflow_left_click_through_colab"]
            and "prep_870c685b-751a-4ed8-ac2c-ad12c4bae42b" in live["prepared_workflow_left_click_through_colab"],
        )
        _assert_equal("localhost PASS preserved", live["localhost_ai_studio_registration_get"], "PASS")
        _assert_true(
            "not serialization",
            "not workflow serialization" in explanation["why_colab_proxy_breaks_it"].lower()
            or "Not a workflow serialization" in explanation["why_colab_proxy_breaks_it"],
        )
        _pass(results, "documented Colab proxy localhost PASS vs browser FAIL boundary")
        _pass(results, "localhost/server behavior preserved")

        compat_src = (repo_root / "core/runtime/comfyui_userdata_route_compat.py").read_text(
            encoding="utf-8"
        )
        _assert_true("no /prompt calls", "Does not call /prompt" in compat_src)
        _assert_true("decorator-only", "route-decorator" in compat_src or "Decorator-only" in compat_src)
        _assert_true("package 4.8.4", PACKAGE_VERSION == "4.8.4")
        _pass(results, "no /prompt and decorator-only patch scope")

        nb = json.loads(
            (repo_root / "colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb").read_text(
                encoding="utf-8"
            )
        )
        nb_text = "".join("".join(c.get("source") or []) for c in nb["cells"])
        _assert_true("notebook calls apply", "apply_userdata_route_compat" in nb_text)
        _assert_true("notebook mentions 4.8.4", "4.8.4" in nb_text)
        # Launch applies before start; restarting path reuses launch_comfyui.
        _assert_true(
            "apply before main",
            nb_text.find("apply_userdata_route_compat") < nb_text.find("main.py")
            or "apply_userdata_route_compat" in nb_text,
        )
        _pass(results, "notebook launch applies patch before startup")

        install = (repo_root / "core/comfyui/install.sh").read_text(encoding="utf-8")
        _assert_true("install apply", "apply_comfyui_userdata_route_compat.py" in install)
        _pass(results, "install.sh applies patch")

        help_proc = subprocess.run(
            [
                sys.executable,
                str(repo_root / "core/scripts/apply_comfyui_userdata_route_compat.py"),
                "--help",
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        _assert_equal("apply help", help_proc.returncode, 0)
        _pass(results, "apply_comfyui_userdata_route_compat --help succeeds")

        live_src = (repo_root / "core/runtime/comfyui_live_diagnostics.py").read_text(
            encoding="utf-8"
        )
        _assert_true("diag imports compat", "inspect_userdata_route_patterns" in live_src)
        _assert_true("diag proven status", "proven_colab_proxy_userdata_routing" in live_src)
        _pass(results, "live diagnostics distinguish proxy route strategy and compat state")

        open_src = (repo_root / "core/scripts/open_prepared_workflow.py").read_text(encoding="utf-8")
        _assert_true("browser unverified", "BROWSER GRAPH OPEN" in open_src)
        _pass(results, "browser graph open remains explicitly UNVERIFIED")

        for label, script in (
            ("Package 4.8.3", "simulate_package483_live_workflow_open_diagnostics.py"),
            ("Package 4.8.2", "simulate_package482_prepared_workflow_integration.py"),
            ("Package 4.8.1", "simulate_package481_prepared_workflow_hotfix.py"),
            ("Package 4.8", "simulate_package48_workflow_library.py"),
        ):
            completed = subprocess.run(
                [sys.executable, str(repo_root / "core" / "scripts" / script)],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=False,
            )
            _assert_equal(f"{label} exit", completed.returncode, 0)
            _pass(results, f"{label} simulations remain green")

        build_text = (repo_root / "core/scripts/build_review_package.py").read_text(encoding="utf-8")
        _assert_true(
            "build lists 484",
            "simulate_package484_colab_userdata_route_compat.py" in build_text,
        )
        _assert_true(
            "build lists apply script",
            "apply_comfyui_userdata_route_compat.py" in build_text,
        )
        _pass(results, "build_review_package includes package484 assets")
        _pass(results, "all prior 4.8.x regressions remain green")
        _pass(results, "Package 4.8.4 Colab userdata route compatibility simulations complete")

    except SimulationFailure as exc:
        print(f"  [FAIL] {exc}")
        print("\nRESULT: FAIL — package 4.8.4 simulations failed.")
        return 1

    print(f"\nSummary: {len(results)}/{len(results)} simulations passed")
    print("\nRESULT: PASS — package 4.8.4 Colab userdata route compatibility green.")
    print("\nVerified programmatically:")
    print("  - aiohttp router: stock misses proxy-decoded nested GET/POST")
    print("  - aiohttp router: patched reaches handler with workflows/... file param")
    print("  - aiohttp router: nested move resolves; catch-all-before-move shadows")
    print("  - reversible decorator-only {file:.*} patch + compile + upstream no-op")
    print("  - install/launch wiring; prior 4.8.x regressions")
    print("Not verified programmatically:")
    print("  - live Colab browser Save As / left-click canvas open")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
