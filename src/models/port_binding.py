"""
Pose-level commodity-to-port-cell binding helpers.

This module turns an operation-level port profile plus a concrete pose into a
finite domain of legal commodity assignments on that pose's physical port cells.
It does not solve the global binding problem yet; it only exposes the exact
per-instance combinatorial domain for operations whose commodities are already
fixed.
"""

from __future__ import annotations

from itertools import combinations, product
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from src.preprocess.operation_profiles import get_operation_port_profile


def supports_exact_pose_level_binding(operation_type: str) -> bool:
    profile = get_operation_port_profile(operation_type)
    return profile.generic_input_slots == 0 and profile.generic_output_slots == 0


def enumerate_pose_level_port_bindings(
    operation_type: str,
    pose: Mapping[str, Any],
) -> List[Dict[str, List[Dict[str, Any]]]]:
    """Enumerate all legal commodity assignments for one placed pose."""
    profile = get_operation_port_profile(operation_type)
    if profile.generic_input_slots or profile.generic_output_slots:
        raise ValueError(
            f"{operation_type} still has generic hub slots; exact pose-level binding "
            "must be decided by a higher-level assignment model."
        )

    input_bindings = _enumerate_side_bindings(
        pose.get("input_port_cells", []),
        profile.input_slots,
        port_type="input",
    )
    output_bindings = _enumerate_side_bindings(
        pose.get("output_port_cells", []),
        profile.output_slots,
        port_type="output",
    )

    bindings: List[Dict[str, List[Dict[str, Any]]]] = []
    for in_ports, out_ports in product(input_bindings, output_bindings):
        bindings.append({
            "input_ports": in_ports,
            "output_ports": out_ports,
            "active_ports": in_ports + out_ports,
        })
    return bindings


def _enumerate_side_bindings(
    port_cells: Sequence[Mapping[str, Any]],
    slot_counts: Mapping[str, int],
    port_type: str,
) -> List[List[Dict[str, Any]]]:
    ordered_cells = [_normalize_port_cell(port) for port in port_cells]
    ordered_cells.sort(key=lambda item: (item["x"], item["y"], item["dir"]))

    required = [(commodity, count) for commodity, count in slot_counts.items() if count > 0]
    total_slots = sum(count for _, count in required)
    if total_slots > len(ordered_cells):
        raise ValueError(
            f"{port_type} ports are insufficient: need {total_slots}, have {len(ordered_cells)}"
        )
    if not required:
        return [[]]

    results: List[List[Dict[str, Any]]] = []

    def backtrack(
        req_idx: int,
        remaining_indices: Sequence[int],
        chosen: Dict[int, str],
    ) -> None:
        if req_idx >= len(required):
            binding = [
                {
                    "type": port_type,
                    "commodity": chosen[idx],
                    "x": ordered_cells[idx]["x"],
                    "y": ordered_cells[idx]["y"],
                    "dir": ordered_cells[idx]["dir"],
                }
                for idx in sorted(chosen)
            ]
            results.append(binding)
            return

        commodity, count = required[req_idx]
        for combo in combinations(remaining_indices, count):
            next_chosen = dict(chosen)
            for idx in combo:
                next_chosen[idx] = commodity
            next_remaining = [idx for idx in remaining_indices if idx not in combo]
            backtrack(req_idx + 1, next_remaining, next_chosen)

    backtrack(0, list(range(len(ordered_cells))), {})
    return results


def _normalize_port_cell(port: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "x": int(port["x"]),
        "y": int(port["y"]),
        "dir": str(port["dir"]),
    }
