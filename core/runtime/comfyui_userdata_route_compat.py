#!/usr/bin/env python3
"""Colab / reverse-proxy compatibility for ComfyUI nested userdata routes (Package 4.8.4).

Proven live root cause (Package 4.8.3 evidence):
  Frontend builds:
    GET/POST /api/userdata/{encodeURIComponent('workflows/<file>.json')}
    → path segment workflows%2F<file>.json
  Colab prod.colab.dev (Via: 1.1 google) decodes %2F to a literal slash before
  aiohttp sees the request:
    /api/userdata/workflows/<file>.json
  Stock ComfyUI registers:
    /userdata/{file}   # aiohttp {file} matches ONE path segment only
  After decoding, the nested path no longer matches the userdata route and falls
  through to web.static('/', web_root) which allows only GET/HEAD:
    GET  → 404 Not Found (empty body)
    POST → 405 Method Not Allowed (Allow: GET,HEAD)

  Live evidence preserved:
    Native Save As through Colab:
      POST /api/userdata/workflows%2Fai_studio_known_good_control.json?overwrite=false&full_info=true
      → 405 Method Not Allowed (Allow: GET,HEAD)
    AI Studio prepared left-click through Colab:
      GET /api/userdata/workflows%2Fai_studio_prep_870c685b-751a-4ed8-ac2c-ad12c4bae42b.json
      → 404 Not Found
    Localhost AI Studio userdata registration/GET: PASS

  This is not workflow serialization.

Compatibility strategy (narrow, reversible, matches upstream ComfyUI #12468):
  1. Rewrite installed app/user_manager.py userdata *route decorator* paths:
       /userdata/{file}              → /userdata/{file:.*}
       /userdata/{file}/move/{dest}  → /userdata/{file:.*}/move/{dest:.*}
  2. Reorder so the move route is registered *before* catch-all GET/POST/DELETE
     `{file:.*}` routes (otherwise aiohttp greedily shadows move).

Does not fork ComfyUI. Does not pin versions. Does not call /prompt.
Restart ComfyUI after apply for routes to take effect.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


PACKAGE_VERSION = "4.8.4"
COMPAT_ID = "ai_studio_userdata_route_compat_4_8_4"
MARKER_BEGIN = f"# BEGIN {COMPAT_ID}"
MARKER_END = f"# END {COMPAT_ID}"

# Only match route-decorator string literals (quoted path argument).
_DECORATOR_REPLACEMENTS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (
        re.compile(
            r"""(@routes\.(?:get|post|delete|put|patch)\(\s*)(['"])/userdata/\{file\}/move/\{dest\}\2"""
        ),
        r"\1\2/userdata/{file:.*}/move/{dest:.*}\2",
        "/userdata/{file}/move/{dest} → /userdata/{file:.*}/move/{dest:.*} (decorator)",
    ),
    (
        re.compile(
            r"""(@routes\.(?:get|post|delete|put|patch)\(\s*)(['"])/userdata/\{file\}\2"""
        ),
        r"\1\2/userdata/{file:.*}\2",
        "/userdata/{file} → /userdata/{file:.*} (decorator)",
    ),
)

_MOVE_DECORATOR_RE = re.compile(
    r"""^[ \t]*@routes\.post\(\s*['\"]/userdata/\{file:\.\*\}/move/\{dest:\.\*\}['\"]\s*\)\s*$""",
    re.MULTILINE,
)

_FIRST_CATCHALL_RE = re.compile(
    r"""^[ \t]*@routes\.(?:get|post|delete)\(\s*['\"]/userdata/\{file:\.\*\}['\"]\s*\)""",
    re.MULTILINE,
)


@dataclass
class UserdataRouteCompatResult:
    comfyui_runtime: str
    user_manager_path: str = ""
    available: bool = False
    already_compatible: bool = False
    applied: bool = False
    changed: bool = False
    dry_run: bool = False
    replacements: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    package_version: str = PACKAGE_VERSION

    @property
    def ok(self) -> bool:
        return not self.errors and (self.already_compatible or self.applied or self.dry_run)

    @property
    def active(self) -> bool:
        return self.already_compatible or self.applied

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ok"] = self.ok
        payload["active"] = self.active
        return payload


def user_manager_path(comfyui_runtime: Path) -> Path:
    return Path(comfyui_runtime) / "app" / "user_manager.py"


def inspect_userdata_route_patterns(comfyui_runtime: Path) -> dict[str, Any]:
    path = user_manager_path(comfyui_runtime)
    if not path.is_file():
        return {
            "available": False,
            "path": str(path),
            "error": "app/user_manager.py not found",
            "has_single_segment_routes": False,
            "has_multi_segment_routes": False,
            "compat_marker_present": False,
            "compatible": False,
            "move_registered_before_catchall": None,
        }
    text = path.read_text(encoding="utf-8")
    # Decorator-only: `{file}` is a substring of `{file:.*}` — use (?!:) and @routes.*.
    has_single = bool(
        re.search(
            r"""@routes\.(?:get|post|delete|put|patch)\(\s*['\"]/userdata/\{file\}(?!:)""",
            text,
        )
    )
    has_multi = bool(
        re.search(
            r"""@routes\.(?:get|post|delete|put|patch)\(\s*['\"]/userdata/\{file:\.\*\}""",
            text,
        )
    )
    marker = MARKER_BEGIN in text and MARKER_END in text
    move_before = _move_registered_before_catchall(text)
    return {
        "available": True,
        "path": str(path),
        "error": None,
        "has_single_segment_routes": has_single,
        "has_multi_segment_routes": has_multi,
        "compat_marker_present": marker,
        "compatible": has_multi and not has_single,
        "move_registered_before_catchall": move_before,
        "source_sha256_prefix": _sha256_prefix(text),
    }


def _move_registered_before_catchall(text: str) -> bool | None:
    move_m = _MOVE_DECORATOR_RE.search(text)
    catch_m = _FIRST_CATCHALL_RE.search(text)
    if move_m is None or catch_m is None:
        return None
    return move_m.start() < catch_m.start()


def _sha256_prefix(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _patch_decorator_routes(text: str) -> tuple[str, list[str]]:
    updated = text
    replacements: list[str] = []
    for pattern, repl, label in _DECORATOR_REPLACEMENTS:
        new_text, count = pattern.subn(repl, updated)
        if count:
            updated = new_text
            replacements.append(f"{label} x{count}")
    return updated, replacements


def _extract_indented_handler_block(lines: list[str], decorator_idx: int) -> tuple[int, int]:
    """Return [start, end) line indices for a @routes decorator + async def body."""
    start = decorator_idx
    # Include blank lines immediately above the decorator that belong to spacing
    # only when we cut — keep start at the decorator line itself.
    i = decorator_idx
    if i >= len(lines) or "@routes.post" not in lines[i]:
        return decorator_idx, decorator_idx
    i += 1
    # async def line
    while i < len(lines) and not lines[i].lstrip().startswith("async def "):
        # Allow blank / comment lines between decorator and def (unusual).
        if lines[i].strip() and not lines[i].lstrip().startswith("#"):
            break
        i += 1
    if i >= len(lines) or not lines[i].lstrip().startswith("async def "):
        return decorator_idx, decorator_idx + 1
    def_indent = len(lines[i]) - len(lines[i].lstrip(" \t"))
    i += 1
    while i < len(lines):
        raw = lines[i]
        if raw.strip() == "":
            # Stop before a blank line that precedes another @routes at same indent,
            # but include trailing blank after body when next non-blank is @routes.
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines):
                nxt = lines[j].lstrip(" \t")
                nxt_indent = len(lines[j]) - len(nxt)
                if nxt.startswith("@routes.") and nxt_indent <= def_indent:
                    break
                if nxt.startswith("def ") and nxt_indent <= def_indent:
                    break
            i += 1
            continue
        indent = len(raw) - len(raw.lstrip(" \t"))
        stripped = raw.lstrip(" \t")
        if indent <= def_indent and (
            stripped.startswith("@routes.")
            or stripped.startswith("def ")
            or stripped.startswith("async def ")
            or stripped.startswith("class ")
        ):
            break
        i += 1
    return start, i


def _reorder_move_before_catchall(text: str) -> tuple[str, bool]:
    """Ensure multi-segment move route is defined before catch-all {file:.*} routes."""
    if _move_registered_before_catchall(text) is True:
        return text, False
    move_m = _MOVE_DECORATOR_RE.search(text)
    catch_m = _FIRST_CATCHALL_RE.search(text)
    if move_m is None or catch_m is None:
        return text, False
    if move_m.start() < catch_m.start():
        return text, False

    lines = text.splitlines(keepends=True)
    # Map character offset to line index.
    move_line = text[: move_m.start()].count("\n")
    start, end = _extract_indented_handler_block(lines, move_line)
    if end <= start:
        return text, False
    block = lines[start:end]
    without = lines[:start] + lines[end:]
    # Recompute catch-all line in the shortened list.
    without_text = "".join(without)
    catch2 = _FIRST_CATCHALL_RE.search(without_text)
    if catch2 is None:
        return text, False
    insert_line = without_text[: catch2.start()].count("\n")
    reordered_lines = without[:insert_line] + block + without[insert_line:]
    return "".join(reordered_lines), True


def apply_userdata_route_compat(
    comfyui_runtime: Path,
    *,
    dry_run: bool = False,
) -> UserdataRouteCompatResult:
    """Apply reversible multi-segment userdata route patterns to installed ComfyUI."""
    runtime = Path(comfyui_runtime)
    result = UserdataRouteCompatResult(comfyui_runtime=str(runtime), dry_run=dry_run)
    path = user_manager_path(runtime)
    result.user_manager_path = str(path)
    if not path.is_file():
        result.errors.append(f"Missing ComfyUI user_manager.py: {path}")
        return result
    result.available = True

    original = path.read_text(encoding="utf-8")
    inspection = inspect_userdata_route_patterns(runtime)
    if inspection.get("compatible"):
        # Upstream-compatible: do not modify, even if move order is suboptimal.
        result.already_compatible = True
        result.messages.append(
            "ComfyUI userdata routes already accept multi-segment paths ({file:.*}); "
            "no source modification."
        )
        if inspection.get("move_registered_before_catchall") is False:
            result.messages.append(
                "NOTE: move route appears after catch-all {file:.*}; upstream layout left untouched."
            )
        return result

    if not inspection.get("has_single_segment_routes") and not inspection.get("has_multi_segment_routes"):
        result.errors.append(
            "Could not locate stock /userdata/{file} route patterns to patch."
        )
        return result

    if not inspection.get("has_single_segment_routes"):
        result.errors.append(
            "Unexpected userdata route state: no single-segment patterns and not marked compatible."
        )
        return result

    updated, replacements = _patch_decorator_routes(original)
    result.replacements.extend(replacements)
    updated, reordered = _reorder_move_before_catchall(updated)
    if reordered:
        result.replacements.append("reorder move route before catch-all {file:.*}")

    if updated == original:
        result.errors.append("No userdata route substitutions applied.")
        return result

    if MARKER_BEGIN not in updated:
        banner = (
            f"{MARKER_BEGIN}\n"
            f"# AI Studio Package {PACKAGE_VERSION}: multi-segment userdata routes for\n"
            f"# Colab/Google reverse-proxy compatibility (encoded %2F may be decoded to /).\n"
            f"# Mirrors upstream Comfy-Org/ComfyUI#12468. Move route registered before catch-all.\n"
            f"# Reversible via remove_userdata_route_compat(). Restart ComfyUI after apply.\n"
            f"{MARKER_END}\n"
        )
        anchor = "class UserManager"
        if anchor in updated:
            updated = updated.replace(anchor, banner + anchor, 1)
        else:
            updated = banner + updated

    result.changed = True
    if dry_run:
        result.messages.append("Dry run — userdata route compat not written.")
        result.applied = False
        return result

    path.write_text(updated, encoding="utf-8")
    result.applied = True
    result.already_compatible = True
    result.messages.append(
        f"Applied multi-segment userdata route compat to {path} "
        f"({len(result.replacements)} change(s)). Restart ComfyUI to activate."
    )
    return result


def remove_userdata_route_compat(comfyui_runtime: Path, *, dry_run: bool = False) -> UserdataRouteCompatResult:
    """Revert AI Studio multi-segment route substitutions when marker is present."""
    runtime = Path(comfyui_runtime)
    result = UserdataRouteCompatResult(comfyui_runtime=str(runtime), dry_run=dry_run)
    path = user_manager_path(runtime)
    result.user_manager_path = str(path)
    if not path.is_file():
        result.errors.append(f"Missing ComfyUI user_manager.py: {path}")
        return result
    result.available = True
    original = path.read_text(encoding="utf-8")
    if MARKER_BEGIN not in original:
        result.messages.append("No AI Studio userdata route compat marker present; nothing to remove.")
        result.already_compatible = inspect_userdata_route_patterns(runtime).get("compatible", False)
        return result

    updated = re.sub(
        re.escape(MARKER_BEGIN) + r".*?" + re.escape(MARKER_END) + r"\n?",
        "",
        original,
        count=1,
        flags=re.DOTALL,
    )
    reverse_patterns: tuple[tuple[re.Pattern[str], str, str], ...] = (
        (
            re.compile(
                r"""(@routes\.(?:get|post|delete|put|patch)\(\s*)(['"])/userdata/\{file:\.\*\}/move/\{dest:\.\*\}\2"""
            ),
            r"\1\2/userdata/{file}/move/{dest}\2",
            "restore move decorator",
        ),
        (
            re.compile(
                r"""(@routes\.(?:get|post|delete|put|patch)\(\s*)(['"])/userdata/\{file:\.\*\}\2"""
            ),
            r"\1\2/userdata/{file}\2",
            "restore file decorator",
        ),
    )
    for pattern, repl, label in reverse_patterns:
        new_text, count = pattern.subn(repl, updated)
        if count:
            updated = new_text
            result.replacements.append(f"{label} x{count}")

    result.changed = updated != original
    if dry_run:
        result.messages.append("Dry run — compat removal not written.")
        return result
    if result.changed:
        path.write_text(updated, encoding="utf-8")
        result.applied = True
        result.messages.append(f"Removed AI Studio userdata route compat from {path}.")
    return result


def explain_colab_proxy_failure() -> dict[str, Any]:
    return {
        "root_cause_id": "colab_proxy_decoded_userdata_slash",
        "package_version": PACKAGE_VERSION,
        "live_evidence": {
            "native_save_as_through_colab": (
                "POST /api/userdata/workflows%2Fai_studio_known_good_control.json"
                "?overwrite=false&full_info=true → 405 Method Not Allowed (Allow: GET,HEAD)"
            ),
            "prepared_workflow_left_click_through_colab": (
                "GET /api/userdata/workflows%2Fai_studio_prep_870c685b-751a-4ed8-ac2c-ad12c4bae42b.json"
                " → 404 Not Found"
            ),
            "localhost_ai_studio_registration_get": "PASS",
        },
        "frontend_url_construction": (
            "api.getUserData/storeUserData → "
            "`/api/userdata/${encodeURIComponent('workflows/<file>.json')}` "
            "producing workflows%2F<file>.json"
        ),
        "backend_route_declaration": (
            "app/user_manager.py registers GET/POST/DELETE `/userdata/{file}` "
            "and POST `/userdata/{file}/move/{dest}`; server.py also mounts `/api` duplicates"
        ),
        "why_colab_proxy_breaks_it": (
            "Google Colab reverse proxy (Via: 1.1 google) decodes %2F to '/' before aiohttp. "
            "aiohttp `{file}` matches one segment, so `/api/userdata/workflows/<file>.json` "
            "misses the userdata handler and falls through to web.static('/', web_root) "
            "(GET/HEAD only): GET→404, POST→405 Allow:GET,HEAD. "
            "Localhost clients that preserve %2F still match `{file}` after unquote. "
            "Not a workflow serialization failure."
        ),
        "compatibility_design": (
            "Reversible decorator-only rewrite of installed user_manager.py routes to "
            "`{file:.*}` / `{dest:.*}` (Comfy-Org/ComfyUI#12468), with move registered before "
            "catch-all to avoid aiohttp shadowing. No serialization change. No /prompt."
        ),
        "localhost_vs_browser": {
            "localhost_registration": "PASS (encoded %2F preserved)",
            "browser_through_colab_proxy_native_save_as_post": "FAIL 405",
            "browser_through_colab_proxy_prepared_get": "FAIL 404",
        },
    }


def simulate_proxy_decoded_userdata_paths(filename: str = "ai_studio_prep_demo.json") -> dict[str, Any]:
    """Pure helper documenting encoded vs proxy-decoded URL forms (no network)."""
    rel = f"workflows/{filename}"
    encoded = "workflows%2F" + filename
    return {
        "relative_path": rel,
        "frontend_encoded_path_form": f"/api/userdata/{encoded}",
        "colab_proxy_decoded_path_form": f"/api/userdata/{rel}",
        "stock_route_matches_encoded": True,
        "stock_route_matches_decoded": False,
        "compat_route_matches_encoded": True,
        "compat_route_matches_decoded": True,
        "discovery_query_unaffected": (
            "/api/userdata?dir=workflows&recurse=true&split=false&full_info=true"
        ),
    }
