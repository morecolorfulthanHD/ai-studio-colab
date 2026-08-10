#!/usr/bin/env python3
"""Graph integrity and structured workflow comparison (Package 4.8.3).

These checks go beyond shallow schema presence and catch cross-reference
errors that can make loadGraphData / graph.configure fail even when
node/link *counts* look correct.

Does not mutate workflows. Does not call /prompt. Does not automate browsers.
"""

from __future__ import annotations

from typing import Any


def _link_tuple(link: Any) -> tuple[Any, Any, Any, Any, Any, Any] | None:
    if isinstance(link, list) and len(link) >= 5:
        link_type = link[5] if len(link) >= 6 else None
        return link[0], link[1], link[2], link[3], link[4], link_type
    if isinstance(link, dict):
        return (
            link.get("id"),
            link.get("origin_id"),
            link.get("origin_slot"),
            link.get("target_id"),
            link.get("target_slot"),
            link.get("type"),
        )
    return None


def validate_graph_integrity(data: Any) -> list[str]:
    """Validate node/link cross-references and ID counters.

    Returns a list of human-readable errors (empty => OK).
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["workflow root must be an object"]

    nodes = data.get("nodes")
    links = data.get("links")
    if not isinstance(nodes, list):
        errors.append("nodes must be a list")
        nodes = []
    if not isinstance(links, list):
        errors.append("links must be a list")
        links = []

    node_ids: set[Any] = set()
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            errors.append(f"nodes[{index}] must be an object")
            continue
        node_id = node.get("id")
        if node_id is None:
            errors.append(f"nodes[{index}] missing id")
            continue
        if node_id in node_ids:
            errors.append(f"duplicate node id: {node_id}")
        node_ids.add(node_id)
        if not str(node.get("type") or "").strip():
            errors.append(f"nodes[{index}] (id={node_id}) missing type")

    link_ids: set[Any] = set()
    parsed_links: list[tuple[Any, Any, Any, Any, Any, Any]] = []
    for index, link in enumerate(links):
        parsed = _link_tuple(link)
        if parsed is None:
            errors.append(f"links[{index}] invalid structure")
            continue
        link_id, origin_id, origin_slot, target_id, target_slot, _link_type = parsed
        if link_id is None:
            errors.append(f"links[{index}] missing id")
            continue
        if link_id in link_ids:
            errors.append(f"duplicate link id: {link_id}")
        link_ids.add(link_id)
        if origin_id not in node_ids:
            errors.append(f"link {link_id} origin node {origin_id} does not exist")
        if target_id not in node_ids:
            errors.append(f"link {link_id} target node {target_id} does not exist")
        for label, slot in (("origin_slot", origin_slot), ("target_slot", target_slot)):
            if slot is None:
                errors.append(f"link {link_id} missing {label}")
            else:
                try:
                    slot_int = int(slot)
                except (TypeError, ValueError):
                    errors.append(f"link {link_id} {label} not an int: {slot!r}")
                else:
                    if slot_int < 0:
                        errors.append(f"link {link_id} {label} negative: {slot_int}")
        parsed_links.append(parsed)

    # Per-node input/output link references must resolve.
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = node.get("id")
        outputs = node.get("outputs") or []
        if isinstance(outputs, list):
            for out_index, output in enumerate(outputs):
                if not isinstance(output, dict):
                    continue
                out_links = output.get("links")
                if out_links is None:
                    continue
                if not isinstance(out_links, list):
                    errors.append(f"node {node_id} outputs[{out_index}].links must be list or null")
                    continue
                for link_id in out_links:
                    if link_id not in link_ids:
                        errors.append(
                            f"node {node_id} outputs[{out_index}] references missing link {link_id}"
                        )
        inputs = node.get("inputs") or []
        if isinstance(inputs, list):
            for in_index, inp in enumerate(inputs):
                if not isinstance(inp, dict):
                    continue
                link_id = inp.get("link")
                if link_id is None:
                    continue
                if link_id not in link_ids:
                    errors.append(
                        f"node {node_id} inputs[{in_index}] references missing link {link_id}"
                    )

    # Slot index bounds against referenced nodes where possible.
    nodes_by_id = {n.get("id"): n for n in nodes if isinstance(n, dict)}
    for link_id, origin_id, origin_slot, target_id, target_slot, _ in parsed_links:
        origin = nodes_by_id.get(origin_id)
        target = nodes_by_id.get(target_id)
        try:
            origin_slot_i = int(origin_slot)
            target_slot_i = int(target_slot)
        except (TypeError, ValueError):
            continue
        if isinstance(origin, dict):
            outs = origin.get("outputs") or []
            if isinstance(outs, list) and origin_slot_i >= len(outs):
                errors.append(
                    f"link {link_id} origin_slot {origin_slot_i} out of range "
                    f"for node {origin_id} ({len(outs)} outputs)"
                )
        if isinstance(target, dict):
            ins = target.get("inputs") or []
            if isinstance(ins, list) and target_slot_i >= len(ins):
                errors.append(
                    f"link {link_id} target_slot {target_slot_i} out of range "
                    f"for node {target_id} ({len(ins)} inputs)"
                )

    if "last_node_id" in data and node_ids:
        try:
            last_node = int(data["last_node_id"])
            max_node = max(int(n) for n in node_ids if str(n).lstrip("-").isdigit() or isinstance(n, int))
            if last_node < max_node:
                errors.append(f"last_node_id {last_node} < max node id {max_node}")
        except (TypeError, ValueError):
            errors.append(f"last_node_id not comparable: {data.get('last_node_id')!r}")
    if "last_link_id" in data and link_ids:
        try:
            last_link = int(data["last_link_id"])
            max_link = max(int(n) for n in link_ids if str(n).lstrip("-").isdigit() or isinstance(n, int))
            if last_link < max_link:
                errors.append(f"last_link_id {last_link} < max link id {max_link}")
        except (TypeError, ValueError):
            errors.append(f"last_link_id not comparable: {data.get('last_link_id')!r}")

    return errors


def summarize_workflow_structure(data: Any) -> dict[str, Any]:
    """Compact structural summary for comparison reports."""
    if not isinstance(data, dict):
        return {"root_type": type(data).__name__, "error": "not an object"}
    nodes = data.get("nodes") if isinstance(data.get("nodes"), list) else []
    links = data.get("links") if isinstance(data.get("links"), list) else []
    node_summaries = []
    for node in nodes:
        if not isinstance(node, dict):
            node_summaries.append({"invalid": True})
            continue
        widgets = node.get("widgets_values")
        node_summaries.append(
            {
                "id": node.get("id"),
                "type": node.get("type"),
                "order": node.get("order"),
                "mode": node.get("mode"),
                "flags": node.get("flags"),
                "has_pos": isinstance(node.get("pos"), (list, dict)),
                "has_size": isinstance(node.get("size"), (list, dict)),
                "input_count": len(node.get("inputs") or []) if isinstance(node.get("inputs"), list) else None,
                "output_count": len(node.get("outputs") or []) if isinstance(node.get("outputs"), list) else None,
                "widgets_values_type": type(widgets).__name__ if widgets is not None else None,
                "widgets_values_len": len(widgets) if isinstance(widgets, (list, dict)) else None,
                "widgets_values": widgets,
                "properties_keys": sorted((node.get("properties") or {}).keys())
                if isinstance(node.get("properties"), dict)
                else None,
            }
        )
    link_summaries = []
    for link in links:
        parsed = _link_tuple(link)
        if parsed is None:
            link_summaries.append({"invalid": True, "raw_type": type(link).__name__})
        else:
            link_summaries.append(
                {
                    "id": parsed[0],
                    "origin_id": parsed[1],
                    "origin_slot": parsed[2],
                    "target_id": parsed[3],
                    "target_slot": parsed[4],
                    "type": parsed[5],
                    "representation": "list" if isinstance(link, list) else "object",
                }
            )
    top_keys = sorted(data.keys())
    extra = data.get("extra")
    return {
        "top_level_keys": top_keys,
        "version": data.get("version"),
        "id": data.get("id"),
        "last_node_id": data.get("last_node_id"),
        "last_link_id": data.get("last_link_id"),
        "has_state": "state" in data,
        "state": data.get("state") if isinstance(data.get("state"), dict) else None,
        "has_groups": "groups" in data,
        "groups_len": len(data.get("groups") or []) if isinstance(data.get("groups"), list) else None,
        "has_config": "config" in data,
        "config": data.get("config"),
        "has_extra": "extra" in data,
        "extra_keys": sorted(extra.keys()) if isinstance(extra, dict) else None,
        "extra_frontend_version": extra.get("frontendVersion") if isinstance(extra, dict) else None,
        "extra_ai_studio_keys": sorted((extra.get("ai_studio") or {}).keys())
        if isinstance(extra, dict) and isinstance(extra.get("ai_studio"), dict)
        else None,
        "node_count": len(nodes),
        "link_count": len(links),
        "nodes": node_summaries,
        "links": link_summaries,
        "unknown_top_level_keys": [
            key
            for key in top_keys
            if key
            not in {
                "id",
                "revision",
                "last_node_id",
                "last_link_id",
                "nodes",
                "links",
                "groups",
                "config",
                "extra",
                "version",
                "models",
                "definitions",
                "floatingLinks",
                "reroutes",
                "state",
                "subgraphs",
            }
        ],
    }


def compare_workflow_structures(known_good: Any, candidate: Any) -> dict[str, Any]:
    """Structural diff between a frontend-saved control and an AI Studio load copy."""
    left = summarize_workflow_structure(known_good)
    right = summarize_workflow_structure(candidate)
    differences: list[dict[str, Any]] = []

    def note(field: str, a: Any, b: Any) -> None:
        if a != b:
            differences.append({"field": field, "known_good": a, "candidate": b})

    for field in (
        "version",
        "last_node_id",
        "last_link_id",
        "node_count",
        "link_count",
        "has_state",
        "has_groups",
        "has_config",
        "has_extra",
        "extra_frontend_version",
    ):
        note(field, left.get(field), right.get(field))

    note("top_level_keys", left.get("top_level_keys"), right.get("top_level_keys"))
    note("extra_keys", left.get("extra_keys"), right.get("extra_keys"))
    note("unknown_top_level_keys", left.get("unknown_top_level_keys"), right.get("unknown_top_level_keys"))

    # Node type multiset by order of appearance.
    left_types = [(n.get("id"), n.get("type")) for n in left.get("nodes") or [] if isinstance(n, dict)]
    right_types = [(n.get("id"), n.get("type")) for n in right.get("nodes") or [] if isinstance(n, dict)]
    note("node_id_type_pairs", left_types, right_types)

    left_by_type: dict[str, list[dict[str, Any]]] = {}
    right_by_type: dict[str, list[dict[str, Any]]] = {}
    for node in left.get("nodes") or []:
        if isinstance(node, dict) and node.get("type"):
            left_by_type.setdefault(str(node["type"]), []).append(node)
    for node in right.get("nodes") or []:
        if isinstance(node, dict) and node.get("type"):
            right_by_type.setdefault(str(node["type"]), []).append(node)

    widget_diffs: list[dict[str, Any]] = []
    for node_type in sorted(set(left_by_type) | set(right_by_type)):
        left_nodes = left_by_type.get(node_type, [])
        right_nodes = right_by_type.get(node_type, [])
        if len(left_nodes) != len(right_nodes):
            widget_diffs.append(
                {
                    "type": node_type,
                    "known_good_count": len(left_nodes),
                    "candidate_count": len(right_nodes),
                }
            )
            continue
        for index, (ln, rn) in enumerate(zip(left_nodes, right_nodes)):
            if ln.get("widgets_values_len") != rn.get("widgets_values_len") or type(
                ln.get("widgets_values")
            ).__name__ != type(rn.get("widgets_values")).__name__:
                widget_diffs.append(
                    {
                        "type": node_type,
                        "index": index,
                        "known_good_widgets_len": ln.get("widgets_values_len"),
                        "candidate_widgets_len": rn.get("widgets_values_len"),
                        "known_good_widgets": ln.get("widgets_values"),
                        "candidate_widgets": rn.get("widgets_values"),
                    }
                )
            # Value-type sequence comparison (ignore textual prompt content).
            lw = ln.get("widgets_values")
            rw = rn.get("widgets_values")
            if isinstance(lw, list) and isinstance(rw, list) and len(lw) == len(rw):
                type_seq_l = [type(v).__name__ for v in lw]
                type_seq_r = [type(v).__name__ for v in rw]
                if type_seq_l != type_seq_r:
                    widget_diffs.append(
                        {
                            "type": node_type,
                            "index": index,
                            "widgets_value_types_known_good": type_seq_l,
                            "widgets_value_types_candidate": type_seq_r,
                        }
                    )

    link_left = [(x.get("origin_id"), x.get("origin_slot"), x.get("target_id"), x.get("target_slot"), x.get("type"))
                 for x in left.get("links") or []]
    link_right = [(x.get("origin_id"), x.get("origin_slot"), x.get("target_id"), x.get("target_slot"), x.get("type"))
                  for x in right.get("links") or []]
    note("link_endpoint_signatures", sorted(link_left, key=str), sorted(link_right, key=str))

    return {
        "known_good_summary": left,
        "candidate_summary": right,
        "differences": differences,
        "widget_differences": widget_diffs,
        "integrity_known_good": validate_graph_integrity(known_good),
        "integrity_candidate": validate_graph_integrity(candidate),
        "difference_count": len(differences) + len(widget_diffs),
    }


def check_nodes_against_object_info(
    workflow: dict[str, Any],
    object_info: dict[str, Any] | None,
) -> dict[str, Any]:
    """Confirm every node type exists in live object_info."""
    if object_info is None:
        return {
            "checked": False,
            "missing_types": [],
            "present_types": [],
            "error": "object_info unavailable",
        }
    present: list[str] = []
    missing: list[str] = []
    for node in workflow.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        node_type = str(node.get("type") or "")
        if not node_type:
            continue
        if node_type in object_info:
            present.append(node_type)
        else:
            missing.append(node_type)
    return {
        "checked": True,
        "present_types": sorted(set(present)),
        "missing_types": sorted(set(missing)),
        "error": None,
    }
