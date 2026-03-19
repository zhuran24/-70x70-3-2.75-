"""
Benders loop entrypoint（Benders 循环入口）.

职责：
1. certified_exact（严格认证精确）与 exploratory（探索）模式切换。
2. exploratory 路径继续沿用 flow-driven 协同求解。
3. certified_exact 路径改为 flow 仅作诊断，binding/routing 给正式证据。
4. exact 路径只使用 safe static occupied-area lower bound。
"""

from __future__ import annotations

import copy
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from ortools.sat.python import cp_model

from src.models.binding_subproblem import PortBindingModel
from src.models.cut_manager import (
    BendersCut,
    CutManager,
    RUN_STATUS_CERTIFIED,
    RUN_STATUS_INFEASIBLE,
    RUN_STATUS_UNKNOWN,
    RUN_STATUS_UNPROVEN,
)
from src.models.flow_subproblem import FlowSubproblem, build_flow_network
from src.models.master_model import (
    ExactMasterCore,
    MasterPlacementModel,
    infer_certified_optional_lower_bounds,
    load_generic_io_requirements_artifact,
    load_project_data,
)
from src.models.routing_subproblem import (
    RoutingGrid,
    RoutingPlacementCore,
    RoutingSubproblem,
    run_exact_routing_precheck,
)
from src.search.exact_campaign import ExactCampaign, compute_exact_artifact_hashes, now_iso

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
EXACT_REQUIRED_ARTIFACTS = {
    "mandatory_exact_instances": "data/preprocessed/mandatory_exact_instances.json",
    "candidate_placements": "data/preprocessed/candidate_placements.json",
    "generic_io_requirements": "data/preprocessed/generic_io_requirements.json",
    "canonical_rules": "rules/canonical_rules.json",
}

_EXACT_INTERNAL_STATUS_MASTER_CUT_ADDED_CONTINUE = "master_cut_added_continue"
_CERTIFIED_SOLVE_MODES = {"certified_exact", "exploratory"}


def _normalize_solve_mode(
    solve_mode: Optional[str] = None,
    certification_mode: Optional[bool] = None,
) -> str:
    if certification_mode is not None:
        return "certified_exact" if certification_mode else "exploratory"
    if solve_mode is None:
        return "certified_exact"
    if solve_mode not in {"certified_exact", "exploratory"}:
        raise ValueError(f"Unsupported solve mode: {solve_mode}")
    return solve_mode


def _normalize_solve_mode_values(raw_value: Any) -> Tuple[Set[str], Optional[str]]:
    if raw_value is None:
        return set(), "missing"
    if isinstance(raw_value, str):
        raw_items = [raw_value]
    elif isinstance(raw_value, (list, tuple, set)):
        raw_items = list(raw_value)
    else:
        return set(), f"malformed_type:{type(raw_value).__name__}"

    normalized: Set[str] = set()
    for raw_item in raw_items:
        if not isinstance(raw_item, str):
            return set(), f"malformed_member_type:{type(raw_item).__name__}"
        token = str(raw_item).strip()
        if not token:
            continue
        if token not in _CERTIFIED_SOLVE_MODES:
            return set(), f"unknown_mode:{token}"
        normalized.add(token)
    if not normalized:
        return set(), "missing"
    return normalized, None


def _normalize_instance_solve_modes(instance: Mapping[str, Any]) -> Tuple[Set[str], Optional[str]]:
    has_solve_mode = "solve_mode" in instance
    has_solve_modes = "solve_modes" in instance
    if not has_solve_mode and not has_solve_modes:
        return set(), "missing"

    normalized_solve_mode: Optional[Set[str]] = None
    normalized_solve_modes: Optional[Set[str]] = None
    issues: List[str] = []

    if has_solve_mode:
        modes, issue = _normalize_solve_mode_values(instance.get("solve_mode"))
        if issue is not None:
            issues.append(f"solve_mode:{issue}")
        else:
            normalized_solve_mode = modes

    if has_solve_modes:
        modes, issue = _normalize_solve_mode_values(instance.get("solve_modes"))
        if issue is not None:
            issues.append(f"solve_modes:{issue}")
        else:
            normalized_solve_modes = modes

    if issues:
        return set(), ";".join(issues)
    if normalized_solve_mode is not None and normalized_solve_modes is not None:
        if normalized_solve_mode != normalized_solve_modes:
            return set(), (
                "conflicting_mode_metadata:"
                f"solve_mode={sorted(normalized_solve_mode)};"
                f"solve_modes={sorted(normalized_solve_modes)}"
            )
        return set(normalized_solve_mode), None
    if normalized_solve_mode is not None:
        return set(normalized_solve_mode), None
    if normalized_solve_modes is not None:
        return set(normalized_solve_modes), None
    return set(), "missing"


def _reset_last_run_metadata() -> None:
    _publish_last_run_metadata({}, [], loaded_exact_safe_cut_count=0, generated_exact_safe_cut_count=0)


def _publish_last_run_metadata(
    proof_summary: Mapping[str, Any],
    exact_safe_cuts: Sequence[BendersCut],
    *,
    loaded_exact_safe_cut_count: int = 0,
    generated_exact_safe_cut_count: int = 0,
) -> None:
    normalized_proof_summary = dict(proof_summary)
    run_benders_for_ghost_rect.last_run_metadata = {
        "proof_summary": normalized_proof_summary,
        "exact_safe_cuts": [cut.to_dict() for cut in exact_safe_cuts],
        "loaded_exact_safe_cut_count": int(loaded_exact_safe_cut_count),
        "generated_exact_safe_cut_count": int(generated_exact_safe_cut_count),
        "fine_grained_exact_safe_cut_count": int(
            normalized_proof_summary.get("fine_grained_exact_safe_cut_count", 0)
        ),
        "binding_domain_empty_cut_count": int(
            normalized_proof_summary.get("binding_domain_empty_cut_count", 0)
        ),
        "routing_front_blocked_cut_count": int(
            normalized_proof_summary.get("routing_front_blocked_cut_count", 0)
        ),
        "routing_precheck_rejections": int(
            normalized_proof_summary.get("routing_precheck_rejections", 0)
        ),
        "routing_precheck_statuses": list(
            normalized_proof_summary.get("routing_precheck_statuses", [])
        ),
        "routing_domain_cells": int(
            normalized_proof_summary.get("routing_domain_cells", 0)
        ),
        "routing_terminal_core_cells": int(
            normalized_proof_summary.get("routing_terminal_core_cells", 0)
        ),
        "routing_state_space_vars": int(
            normalized_proof_summary.get("routing_state_space_vars", 0)
        ),
        "routing_local_pattern_pruned_states": int(
            normalized_proof_summary.get("routing_local_pattern_pruned_states", 0)
        ),
        "used_routing_core_reuse": bool(
            normalized_proof_summary.get("used_routing_core_reuse", False)
        ),
        "routing_core_build_seconds": float(
            normalized_proof_summary.get("routing_core_build_seconds", 0.0)
        ),
        "routing_overlay_build_seconds": float(
            normalized_proof_summary.get("routing_overlay_build_seconds", 0.0)
        ),
        "binding_domain_cache_hits": int(
            normalized_proof_summary.get("binding_domain_cache_hits", 0)
        ),
        "binding_domain_cache_misses": int(
            normalized_proof_summary.get("binding_domain_cache_misses", 0)
        ),
        "binding_domain_reused_instances": list(
            normalized_proof_summary.get("binding_domain_reused_instances", [])
        ),
        "master_search_profile": str(
            normalized_proof_summary.get("master_search_profile", "default_automatic")
        ),
        "power_pole_family_order": list(
            normalized_proof_summary.get("power_pole_family_order", [])
        ),
        "power_pole_family_count_literals": int(
            normalized_proof_summary.get("power_pole_family_count_literals", 0)
        ),
        "residual_optional_family_guided": bool(
            normalized_proof_summary.get("residual_optional_family_guided", False)
        ),
        "binding_search_profile": str(
            normalized_proof_summary.get("binding_search_profile", "exact_binding_guided_branching_v1")
        ),
        "diagnostic_flow_status": str(
            normalized_proof_summary.get("diagnostic_flow_status", "NOT_RUN")
        ),
        "master_status": normalized_proof_summary.get("master_status"),
        "binding_status": normalized_proof_summary.get("binding_status"),
        "routing_status": normalized_proof_summary.get("routing_status"),
        "mode": normalized_proof_summary.get("mode"),
        "used_exact_core_reuse": bool(normalized_proof_summary.get("used_exact_core_reuse", False)),
        "core_build_seconds": float(normalized_proof_summary.get("core_build_seconds", 0.0)),
        "overlay_build_seconds": float(normalized_proof_summary.get("overlay_build_seconds", 0.0)),
        "ghost_constraint_seconds": float(
            normalized_proof_summary.get("ghost_constraint_seconds", 0.0)
        ),
        "cut_replay_seconds": float(normalized_proof_summary.get("cut_replay_seconds", 0.0)),
        "master_representation": str(
            normalized_proof_summary.get("master_representation", "pose_bool_v1")
        ),
        "master_slot_counts": dict(
            normalized_proof_summary.get("master_slot_counts", {})
        ),
        "master_mode_literals": int(
            normalized_proof_summary.get("master_mode_literals", 0)
        ),
        "master_interval_count": int(
            normalized_proof_summary.get("master_interval_count", 0)
        ),
        "master_pose_bool_literals": int(
            normalized_proof_summary.get("master_pose_bool_literals", 0)
        ),
        "master_domain_encoding": str(
            normalized_proof_summary.get("master_domain_encoding", "")
        ),
        "master_domain_table_rows": int(
            normalized_proof_summary.get("master_domain_table_rows", 0)
        ),
        "master_mode_rect_domains": copy.deepcopy(
            normalized_proof_summary.get("master_mode_rect_domains", {})
        ),
        "power_pole_shell_lookup_pairs": copy.deepcopy(
            normalized_proof_summary.get("power_pole_shell_lookup_pairs", {})
        ),
        "power_coverage_representation": str(
            normalized_proof_summary.get("power_coverage_representation", "")
        ),
        "power_coverage_encoding": str(
            normalized_proof_summary.get("power_coverage_encoding", "")
        ),
        "power_coverage_powered_slots": int(
            normalized_proof_summary.get("power_coverage_powered_slots", 0)
        ),
        "power_coverage_pole_slots": int(
            normalized_proof_summary.get("power_coverage_pole_slots", 0)
        ),
        "power_coverage_cover_literals": int(
            normalized_proof_summary.get("power_coverage_cover_literals", 0)
        ),
        "power_coverage_witness_indices": int(
            normalized_proof_summary.get("power_coverage_witness_indices", 0)
        ),
        "power_coverage_element_constraints": int(
            normalized_proof_summary.get("power_coverage_element_constraints", 0)
        ),
        "power_coverage_radius": int(
            normalized_proof_summary.get("power_coverage_radius", 0)
        ),
        "power_capacity_shell_pairs": int(
            normalized_proof_summary.get("power_capacity_shell_pairs", 0)
        ),
        "power_capacity_shell_pair_evaluations": int(
            normalized_proof_summary.get("power_capacity_shell_pair_evaluations", 0)
        ),
        "power_capacity_signature_classes": int(
            normalized_proof_summary.get("power_capacity_signature_classes", 0)
        ),
        "power_capacity_signature_class_evaluations": int(
            normalized_proof_summary.get("power_capacity_signature_class_evaluations", 0)
        ),
        "power_capacity_compact_signature_classes": int(
            normalized_proof_summary.get("power_capacity_compact_signature_classes", 0)
        ),
        "power_capacity_compact_signature_evaluations": int(
            normalized_proof_summary.get(
                "power_capacity_compact_signature_evaluations",
                0,
            )
        ),
        "power_capacity_compact_signature_cache_hits": int(
            normalized_proof_summary.get(
                "power_capacity_compact_signature_cache_hits",
                0,
            )
        ),
        "power_capacity_compact_signature_cache_misses": int(
            normalized_proof_summary.get(
                "power_capacity_compact_signature_cache_misses",
                0,
            )
        ),
        "power_capacity_rect_dp_evaluations": int(
            normalized_proof_summary.get("power_capacity_rect_dp_evaluations", 0)
        ),
        "power_capacity_rect_dp_cache_hits": int(
            normalized_proof_summary.get("power_capacity_rect_dp_cache_hits", 0)
        ),
        "power_capacity_rect_dp_cache_misses": int(
            normalized_proof_summary.get("power_capacity_rect_dp_cache_misses", 0)
        ),
        "power_capacity_rect_dp_state_merges": int(
            normalized_proof_summary.get("power_capacity_rect_dp_state_merges", 0)
        ),
        "power_capacity_rect_dp_peak_line_states": int(
            normalized_proof_summary.get("power_capacity_rect_dp_peak_line_states", 0)
        ),
        "power_capacity_rect_dp_peak_pos_states": int(
            normalized_proof_summary.get("power_capacity_rect_dp_peak_pos_states", 0)
        ),
        "power_capacity_rect_dp_compiled_signatures": int(
            normalized_proof_summary.get("power_capacity_rect_dp_compiled_signatures", 0)
        ),
        "power_capacity_rect_dp_compiled_start_options": int(
            normalized_proof_summary.get("power_capacity_rect_dp_compiled_start_options", 0)
        ),
        "power_capacity_rect_dp_deduped_start_options": int(
            normalized_proof_summary.get("power_capacity_rect_dp_deduped_start_options", 0)
        ),
        "power_capacity_rect_dp_compiled_line_subsets": int(
            normalized_proof_summary.get("power_capacity_rect_dp_compiled_line_subsets", 0)
        ),
        "power_capacity_rect_dp_peak_line_subset_options": int(
            normalized_proof_summary.get("power_capacity_rect_dp_peak_line_subset_options", 0)
        ),
        "power_capacity_rect_dp_v3_fallbacks": int(
            normalized_proof_summary.get("power_capacity_rect_dp_v3_fallbacks", 0)
        ),
        "power_capacity_m6x4_mixed_cpsat_evaluations": int(
            normalized_proof_summary.get("power_capacity_m6x4_mixed_cpsat_evaluations", 0)
        ),
        "power_capacity_m6x4_mixed_cpsat_cache_hits": int(
            normalized_proof_summary.get("power_capacity_m6x4_mixed_cpsat_cache_hits", 0)
        ),
        "power_capacity_m6x4_mixed_cpsat_selected_cases": int(
            normalized_proof_summary.get("power_capacity_m6x4_mixed_cpsat_selected_cases", 0)
        ),
        "power_capacity_m6x4_mixed_cpsat_v3_fallbacks": int(
            normalized_proof_summary.get("power_capacity_m6x4_mixed_cpsat_v3_fallbacks", 0)
        ),
        "power_capacity_bitset_oracle_evaluations": int(
            normalized_proof_summary.get("power_capacity_bitset_oracle_evaluations", 0)
        ),
        "power_capacity_bitset_fallbacks": int(
            normalized_proof_summary.get("power_capacity_bitset_fallbacks", 0)
        ),
        "power_capacity_cpsat_fallbacks": int(
            normalized_proof_summary.get("power_capacity_cpsat_fallbacks", 0)
        ),
        "power_capacity_oracle": str(
            normalized_proof_summary.get("power_capacity_oracle", "")
        ),
        "power_capacity_raw_pole_evaluations": int(
            normalized_proof_summary.get("power_capacity_raw_pole_evaluations", 0)
        ),
        "signature_bucket_cache_hits": int(
            normalized_proof_summary.get("signature_bucket_cache_hits", 0)
        ),
        "signature_bucket_cache_misses": int(
            normalized_proof_summary.get("signature_bucket_cache_misses", 0)
        ),
        "signature_bucket_distinct_keys": int(
            normalized_proof_summary.get("signature_bucket_distinct_keys", 0)
        ),
        "geometry_cache_templates": int(
            normalized_proof_summary.get("geometry_cache_templates", 0)
        ),
    }


def compute_mandatory_area_lower_bound(
    instances: Sequence[Mapping[str, Any]],
    rules: Mapping[str, Any],
) -> int:
    """Compute the exact-safe static occupied-area lower bound from mandatory exact instances."""

    templates = dict(rules.get("facility_templates", {}))
    total = 0
    for instance in instances:
        if not bool(instance.get("is_mandatory")):
            continue
        if str(instance.get("bound_type", "exact")) != "exact":
            continue

        facility_type = str(instance["facility_type"])
        template = templates[facility_type]
        dims = dict(template["dimensions"])
        total += int(dims["w"]) * int(dims["h"])
    return total


def compute_exact_static_area_lower_bound(
    instances: Sequence[Mapping[str, Any]],
    rules: Mapping[str, Any],
    generic_io_requirements: Optional[Mapping[str, Any]] = None,
) -> int:
    total = compute_mandatory_area_lower_bound(instances, rules)
    templates = dict(rules.get("facility_templates", {}))
    optional_lower_bounds = infer_certified_optional_lower_bounds(
        rules,
        generic_io_requirements,
    )
    for facility_type, count in optional_lower_bounds.items():
        template = dict(templates[str(facility_type)])
        dims = dict(template["dimensions"])
        total += int(count) * int(dims["w"]) * int(dims["h"])
    return total


def collect_certification_blockers(
    *,
    instances: Optional[Sequence[Mapping[str, Any]]] = None,
    solve_mode: str = "certified_exact",
    loaded_cuts: Optional[Sequence[BendersCut]] = None,
    current_hashes: Optional[Mapping[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Collect exact-contract blockers without mutating the current solve flow."""

    if solve_mode != "certified_exact":
        return []

    blockers: List[Dict[str, Any]] = []
    for instance in instances or []:
        instance_id = str(instance.get("instance_id", "<unknown>"))
        bound_type = str(instance.get("bound_type", ""))
        if bound_type == "provisional":
            blockers.append(
                {
                    "code": "provisional_instance_forbidden",
                    "instance_id": instance_id,
                    "detail": "provisional instance cannot enter certified_exact",
                }
            )
        if not bool(instance.get("is_mandatory", False)):
            blockers.append(
                {
                    "code": "non_mandatory_instance_forbidden",
                    "instance_id": instance_id,
                    "detail": "non-mandatory instance cannot enter certified_exact",
                }
            )
        instance_modes, mode_issue = _normalize_instance_solve_modes(instance)
        if mode_issue is not None:
            blockers.append(
                {
                    "code": "instance_mode_pollution",
                    "instance_id": instance_id,
                    "detail": (
                        "instance solve-mode metadata is missing or ambiguous for certified_exact: "
                        f"{mode_issue}"
                    ),
                }
            )
            continue
        if "certified_exact" not in instance_modes:
            blockers.append(
                {
                    "code": "instance_mode_pollution",
                    "instance_id": instance_id,
                    "detail": (
                        "instance does not declare certified_exact support: "
                        f"solve_modes={sorted(instance_modes)}"
                    ),
                }
            )

    normalized_hashes = (
        {str(k): str(v) for k, v in current_hashes.items()}
        if current_hashes is not None
        else None
    )
    for cut in loaded_cuts or []:
        if normalized_hashes is not None and dict(cut.artifact_hashes) != normalized_hashes:
            blockers.append(
                {
                    "code": "cut_hash_mismatch",
                    "detail": "loaded cut artifact hashes do not match current artifacts",
                    "cut_type": cut.cut_type,
                }
            )
        if not cut.exact_safe:
            blockers.append(
                {
                    "code": "cut_not_exact_safe",
                    "detail": "loaded cut is not marked exact_safe",
                    "cut_type": cut.cut_type,
                }
            )
        if cut.source_mode != "certified_exact":
            blockers.append(
                {
                    "code": "cut_mode_pollution",
                    "detail": f"loaded cut source_mode={cut.source_mode}",
                    "cut_type": cut.cut_type,
                }
            )

    return blockers


@dataclass
class ExactSearchSession:
    """Reusable exact-search session carrying one static master core per process."""

    project_root: Path
    solve_mode: str
    instances: List[Dict[str, Any]]
    facility_pools: Dict[str, List[Dict[str, Any]]]
    rules: Dict[str, Any]
    artifact_hashes: Dict[str, str]
    core: ExactMasterCore
    core_build_seconds: float

    @classmethod
    def create(
        cls,
        project_root: Path,
        *,
        solve_mode: str = "certified_exact",
    ) -> "ExactSearchSession":
        if solve_mode != "certified_exact":
            raise ValueError("ExactSearchSession only supports certified_exact")

        instances, facility_pools, rules = load_project_data(project_root, solve_mode=solve_mode)
        generic_io_requirements = load_generic_io_requirements_artifact(project_root)
        artifact_hashes = compute_exact_artifact_hashes(project_root)
        core_started = time.perf_counter()
        core = MasterPlacementModel.build_exact_core(
            instances,
            facility_pools,
            rules,
            generic_io_requirements=generic_io_requirements,
        )
        return cls(
            project_root=project_root,
            solve_mode=solve_mode,
            instances=instances,
            facility_pools=facility_pools,
            rules=rules,
            artifact_hashes=artifact_hashes,
            core=core,
            core_build_seconds=time.perf_counter() - core_started,
        )


def _merge_reuse_metadata(
    proof_summary: Mapping[str, Any],
    *,
    used_exact_core_reuse: bool,
    core_build_seconds: float,
    overlay_build_seconds: float,
    ghost_constraint_seconds: float,
    cut_replay_seconds: float,
) -> Dict[str, Any]:
    return {
        **dict(proof_summary),
        "used_exact_core_reuse": bool(used_exact_core_reuse),
        "core_build_seconds": float(core_build_seconds),
        "overlay_build_seconds": float(overlay_build_seconds),
        "ghost_constraint_seconds": float(ghost_constraint_seconds),
        "cut_replay_seconds": float(cut_replay_seconds),
    }


class LBBDController:
    """Orchestrator connecting the master model to exploratory or exact subproblems."""

    def __init__(
        self,
        master: MasterPlacementModel,
        cut_manager: CutManager,
        project_root: Path,
        solve_mode: str,
        *,
        max_iterations: int = 30,
        master_seconds: float = 600.0,
        binding_seconds: float = 600.0,
        routing_seconds: float = 600.0,
        flow_seconds: float = 60.0,
        artifact_hashes: Optional[Mapping[str, str]] = None,
        loaded_exact_safe_cuts: Optional[Sequence[BendersCut]] = None,
    ):
        self.master = master
        self.cut_manager = cut_manager
        self.project_root = project_root
        self.solve_mode = solve_mode
        self.max_iterations = max_iterations
        self.master_seconds = master_seconds
        self.binding_seconds = binding_seconds
        self.routing_seconds = routing_seconds
        self.flow_seconds = flow_seconds
        self.artifact_hashes = (
            {str(k): str(v) for k, v in artifact_hashes.items()}
            if artifact_hashes is not None
            else {}
        )
        self.loaded_exact_safe_cuts: List[BendersCut] = list(loaded_exact_safe_cuts or [])
        self.generated_exact_safe_cuts: List[BendersCut] = []
        self.last_proof_summary: Dict[str, Any] = {}
        self._greedy_hint: Dict[str, int] = {}
        self._greedy_hint_instances = 0
        self._used_greedy_hint = False
        self._master_hinted_literals = 0
        self._fine_grained_exact_safe_cut_count = 0
        self._binding_domain_empty_cut_count = 0
        self._routing_front_blocked_cut_count = 0
        self._routing_precheck_rejections = 0
        self._routing_precheck_statuses: List[str] = []
        self._routing_domain_cells = 0
        self._routing_terminal_core_cells = 0
        self._routing_state_space_vars = 0
        self._routing_local_pattern_pruned_states = 0
        self._used_routing_core_reuse = False
        self._routing_core_build_seconds = 0.0
        self._routing_overlay_build_seconds = 0.0
        self._binding_domain_cache_hits = 0
        self._binding_domain_cache_misses = 0
        self._binding_domain_reused_instances: List[str] = []

        demands_path = self.project_root / "data" / "preprocessed" / "commodity_demands.json"
        if demands_path.exists():
            with demands_path.open("r", encoding="utf-8") as handle:
                self.commodity_demands = json.load(handle)
        else:
            self.commodity_demands = {}

    def _exact_warm_start_summary(self) -> Dict[str, Any]:
        return {
            "used_greedy_hint": bool(self._used_greedy_hint),
            "greedy_hint_instances": int(self._greedy_hint_instances),
            "master_hinted_literals": int(self._master_hinted_literals),
        }

    def _master_search_summary(self) -> Dict[str, Any]:
        last_solve = dict(self.master.build_stats.get("last_solve", {}))
        search_guidance = dict(self.master.build_stats.get("search_guidance", {}))
        power_coverage = dict(self.master.build_stats.get("power_coverage", {}))
        exact_precompute_profile = dict(
            self.master.build_stats.get("exact_precompute_profile", {})
        )
        return {
            "master_search_profile": str(
                last_solve.get(
                    "search_profile",
                    search_guidance.get("profile", "default_automatic"),
                )
            ),
            "master_search_guidance_applied": bool(search_guidance.get("applied", False)),
            "power_pole_family_order": list(
                search_guidance.get("power_pole_family_order", [])
            ),
            "power_pole_family_count_literals": int(
                search_guidance.get("power_pole_family_count_literals", 0)
            ),
            "residual_optional_family_guided": bool(
                search_guidance.get("residual_optional_family_guided", False)
            ),
            "master_representation": str(
                self.master.build_stats.get("master_representation", "pose_bool_v1")
            ),
            "master_slot_counts": copy.deepcopy(
                self.master.build_stats.get("master_slot_counts", {})
            ),
            "master_mode_literals": int(
                self.master.build_stats.get("master_mode_literals", 0)
            ),
            "master_interval_count": int(
                self.master.build_stats.get("master_interval_count", 0)
            ),
            "master_pose_bool_literals": int(
                self.master.build_stats.get("master_pose_bool_literals", 0)
            ),
            "master_domain_encoding": str(
                self.master.build_stats.get("master_domain_encoding", "")
            ),
            "master_domain_table_rows": int(
                self.master.build_stats.get("master_domain_table_rows", 0)
            ),
            "master_mode_rect_domains": copy.deepcopy(
                self.master.build_stats.get("master_mode_rect_domains", {})
            ),
            "power_pole_shell_lookup_pairs": copy.deepcopy(
                self.master.build_stats.get("power_pole_shell_lookup_pairs", {})
            ),
            "power_coverage_representation": str(
                power_coverage.get("representation", "")
            ),
            "power_coverage_encoding": str(power_coverage.get("encoding", "")),
            "power_coverage_powered_slots": int(
                power_coverage.get("powered_slots", 0)
            ),
            "power_coverage_pole_slots": int(power_coverage.get("pole_slots", 0)),
            "power_coverage_cover_literals": int(
                power_coverage.get("cover_literals", 0)
            ),
            "power_coverage_witness_indices": int(
                power_coverage.get("witness_indices", 0)
            ),
            "power_coverage_element_constraints": int(
                power_coverage.get("element_constraints", 0)
            ),
            "power_coverage_radius": int(power_coverage.get("radius", 0)),
            "power_capacity_shell_pairs": int(
                exact_precompute_profile.get("power_capacity_shell_pairs", 0)
            ),
            "power_capacity_shell_pair_evaluations": int(
                exact_precompute_profile.get("power_capacity_shell_pair_evaluations", 0)
            ),
            "power_capacity_signature_classes": int(
                exact_precompute_profile.get("power_capacity_signature_classes", 0)
            ),
            "power_capacity_signature_class_evaluations": int(
                exact_precompute_profile.get("power_capacity_signature_class_evaluations", 0)
            ),
            "power_capacity_compact_signature_classes": int(
                exact_precompute_profile.get("power_capacity_compact_signature_classes", 0)
            ),
            "power_capacity_compact_signature_evaluations": int(
                exact_precompute_profile.get(
                    "power_capacity_compact_signature_evaluations",
                    0,
                )
            ),
            "power_capacity_compact_signature_cache_hits": int(
                exact_precompute_profile.get(
                    "power_capacity_compact_signature_cache_hits",
                    0,
                )
            ),
            "power_capacity_compact_signature_cache_misses": int(
                exact_precompute_profile.get(
                    "power_capacity_compact_signature_cache_misses",
                    0,
                )
            ),
            "power_capacity_rect_dp_evaluations": int(
                exact_precompute_profile.get("power_capacity_rect_dp_evaluations", 0)
            ),
            "power_capacity_rect_dp_cache_hits": int(
                exact_precompute_profile.get("power_capacity_rect_dp_cache_hits", 0)
            ),
            "power_capacity_rect_dp_cache_misses": int(
                exact_precompute_profile.get("power_capacity_rect_dp_cache_misses", 0)
            ),
            "power_capacity_rect_dp_state_merges": int(
                exact_precompute_profile.get("power_capacity_rect_dp_state_merges", 0)
            ),
            "power_capacity_rect_dp_peak_line_states": int(
                exact_precompute_profile.get("power_capacity_rect_dp_peak_line_states", 0)
            ),
            "power_capacity_rect_dp_peak_pos_states": int(
                exact_precompute_profile.get("power_capacity_rect_dp_peak_pos_states", 0)
            ),
            "power_capacity_rect_dp_compiled_signatures": int(
                exact_precompute_profile.get("power_capacity_rect_dp_compiled_signatures", 0)
            ),
            "power_capacity_rect_dp_compiled_start_options": int(
                exact_precompute_profile.get("power_capacity_rect_dp_compiled_start_options", 0)
            ),
            "power_capacity_rect_dp_deduped_start_options": int(
                exact_precompute_profile.get("power_capacity_rect_dp_deduped_start_options", 0)
            ),
            "power_capacity_rect_dp_compiled_line_subsets": int(
                exact_precompute_profile.get("power_capacity_rect_dp_compiled_line_subsets", 0)
            ),
            "power_capacity_rect_dp_peak_line_subset_options": int(
                exact_precompute_profile.get("power_capacity_rect_dp_peak_line_subset_options", 0)
            ),
            "power_capacity_rect_dp_v3_fallbacks": int(
                exact_precompute_profile.get("power_capacity_rect_dp_v3_fallbacks", 0)
            ),
            "power_capacity_m6x4_mixed_cpsat_evaluations": int(
                exact_precompute_profile.get("power_capacity_m6x4_mixed_cpsat_evaluations", 0)
            ),
            "power_capacity_m6x4_mixed_cpsat_cache_hits": int(
                exact_precompute_profile.get("power_capacity_m6x4_mixed_cpsat_cache_hits", 0)
            ),
            "power_capacity_m6x4_mixed_cpsat_selected_cases": int(
                exact_precompute_profile.get("power_capacity_m6x4_mixed_cpsat_selected_cases", 0)
            ),
            "power_capacity_m6x4_mixed_cpsat_v3_fallbacks": int(
                exact_precompute_profile.get("power_capacity_m6x4_mixed_cpsat_v3_fallbacks", 0)
            ),
            "power_capacity_bitset_oracle_evaluations": int(
                exact_precompute_profile.get("power_capacity_bitset_oracle_evaluations", 0)
            ),
            "power_capacity_bitset_fallbacks": int(
                exact_precompute_profile.get("power_capacity_bitset_fallbacks", 0)
            ),
            "power_capacity_cpsat_fallbacks": int(
                exact_precompute_profile.get("power_capacity_cpsat_fallbacks", 0)
            ),
            "power_capacity_oracle": str(
                exact_precompute_profile.get("power_capacity_oracle", "")
            ),
            "power_capacity_raw_pole_evaluations": int(
                exact_precompute_profile.get("power_capacity_raw_pole_evaluations", 0)
            ),
            "signature_bucket_cache_hits": int(
                exact_precompute_profile.get("signature_bucket_cache_hits", 0)
            ),
            "signature_bucket_cache_misses": int(
                exact_precompute_profile.get("signature_bucket_cache_misses", 0)
            ),
            "signature_bucket_distinct_keys": int(
                exact_precompute_profile.get("signature_bucket_distinct_keys", 0)
            ),
            "geometry_cache_templates": int(
                exact_precompute_profile.get("geometry_cache_templates", 0)
            ),
        }

    def _exact_cut_ladder_summary(self) -> Dict[str, Any]:
        return {
            "fine_grained_exact_safe_cut_count": int(self._fine_grained_exact_safe_cut_count),
            "binding_domain_empty_cut_count": int(self._binding_domain_empty_cut_count),
            "routing_front_blocked_cut_count": int(self._routing_front_blocked_cut_count),
            "routing_precheck_rejections": int(self._routing_precheck_rejections),
            "routing_precheck_statuses": list(self._routing_precheck_statuses),
        }

    def _routing_shrink_summary(self) -> Dict[str, Any]:
        return {
            "routing_domain_cells": int(self._routing_domain_cells),
            "routing_terminal_core_cells": int(self._routing_terminal_core_cells),
            "routing_state_space_vars": int(self._routing_state_space_vars),
            "routing_local_pattern_pruned_states": int(
                self._routing_local_pattern_pruned_states
            ),
        }

    def _routing_reuse_summary(self) -> Dict[str, Any]:
        return {
            "used_routing_core_reuse": bool(self._used_routing_core_reuse),
            "routing_core_build_seconds": float(self._routing_core_build_seconds),
            "routing_overlay_build_seconds": float(self._routing_overlay_build_seconds),
        }

    def _binding_domain_cache_summary(self) -> Dict[str, Any]:
        return {
            "binding_domain_cache_hits": int(self._binding_domain_cache_hits),
            "binding_domain_cache_misses": int(self._binding_domain_cache_misses),
            "binding_domain_reused_instances": list(self._binding_domain_reused_instances),
        }

    def _subproblem_reuse_summary(self) -> Dict[str, Any]:
        return {
            **self._routing_reuse_summary(),
            **self._binding_domain_cache_summary(),
        }

    def _update_routing_shrink_from_domain_stats(
        self,
        domain_stats: Optional[Mapping[str, Any]],
    ) -> None:
        stats = dict(domain_stats or {})
        if "domain_cells" in stats:
            self._routing_domain_cells = int(stats["domain_cells"])
        if "terminal_core_cells" in stats:
            self._routing_terminal_core_cells = int(stats["terminal_core_cells"])

    def _update_routing_shrink_from_build_stats(
        self,
        build_stats: Optional[Mapping[str, Any]],
    ) -> None:
        state_space = dict((build_stats or {}).get("state_space", {}))
        self._update_routing_shrink_from_domain_stats(state_space)
        if "vars" in state_space:
            self._routing_state_space_vars = int(state_space["vars"])
        if "local_pattern_pruned_states" in state_space:
            self._routing_local_pattern_pruned_states = int(
                state_space["local_pattern_pruned_states"]
            )

    def _update_binding_cache_from_summary(
        self,
        binding_summary: Optional[Mapping[str, Any]],
    ) -> None:
        summary = dict(binding_summary or {})
        self._binding_domain_cache_hits = int(summary.get("binding_domain_cache_hits", 0))
        self._binding_domain_cache_misses = int(summary.get("binding_domain_cache_misses", 0))
        self._binding_domain_reused_instances = [
            str(instance_id)
            for instance_id in list(summary.get("binding_domain_reused_instances", []))
        ]

    def _exact_cut_ladder_summary_with_deltas(
        self,
        *,
        fine_grained_delta: int = 0,
        binding_domain_empty_delta: int = 0,
        routing_front_blocked_delta: int = 0,
        routing_precheck_rejections_delta: int = 0,
    ) -> Dict[str, Any]:
        return {
            "fine_grained_exact_safe_cut_count": int(
                self._fine_grained_exact_safe_cut_count + fine_grained_delta
            ),
            "binding_domain_empty_cut_count": int(
                self._binding_domain_empty_cut_count + binding_domain_empty_delta
            ),
            "routing_front_blocked_cut_count": int(
                self._routing_front_blocked_cut_count + routing_front_blocked_delta
            ),
            "routing_precheck_rejections": int(
                self._routing_precheck_rejections + routing_precheck_rejections_delta
            ),
            "routing_precheck_statuses": list(self._routing_precheck_statuses),
        }

    def run_with_status(self) -> Tuple[str, Optional[Dict[str, Any]]]:
        if self.solve_mode == "certified_exact":
            return self._run_certified_exact()
        return self._run_exploratory()

    def _run_exploratory(self) -> Tuple[str, Optional[Dict[str, Any]]]:
        iteration = 0
        while iteration < self.max_iterations:
            print(f"\n--- [LBBD Loop] Iteration {iteration + 1}/{self.max_iterations} ---")
            print("  > Solving Master Problem...")

            master_status = self.master.solve(time_limit_seconds=self.master_seconds)
            if master_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                pass
            elif master_status == cp_model.INFEASIBLE:
                print("  > Master problem is provably infeasible.")
                self.last_proof_summary = {
                    "mode": "exploratory",
                    "benders_iterations": iteration + 1,
                    "master_status": "INFEASIBLE",
                }
                return RUN_STATUS_INFEASIBLE, None
            else:
                print("  > Master problem returned UNKNOWN / timeout.")
                self.last_proof_summary = {
                    "mode": "exploratory",
                    "benders_iterations": iteration + 1,
                    "master_status": "UNKNOWN",
                }
                return RUN_STATUS_UNKNOWN, None

            solution = self.master.extract_solution()
            if not solution:
                self.last_proof_summary = {
                    "mode": "exploratory",
                    "benders_iterations": iteration + 1,
                    "master_status": "EMPTY_SOLUTION",
                }
                return RUN_STATUS_UNKNOWN, None

            print("  > Master solved successfully. Validating with Flow Subproblem...")
            flow_status, bottlenecks = self._run_flow_diagnostic(solution)
            self.last_proof_summary = {
                "mode": "exploratory",
                "benders_iterations": iteration + 1,
                "diagnostic_flow_status": flow_status,
                "bottleneck_count": len(bottlenecks),
            }

            if flow_status == "FEASIBLE":
                print("  > Flow Subproblem FEASIBLE! Layout is validated.")
                return RUN_STATUS_CERTIFIED, solution

            if flow_status == "TIMEOUT":
                print("  > Flow Subproblem timed out.")
                return RUN_STATUS_UNKNOWN, None

            print("  > Flow Subproblem INFEASIBLE. Extracting Bottleneck Cuts...")
            if not bottlenecks:
                print("  > No bottlenecks could be extracted. Terminating.")
                return RUN_STATUS_UNKNOWN, None

            conflict_set: List[Dict[str, str]] = []
            conflict_map_for_master: Dict[str, int] = {}
            for instance_id in bottlenecks:
                if instance_id not in solution:
                    continue
                pose_idx = int(solution[instance_id]["pose_idx"])
                pose_id = str(solution[instance_id]["pose_id"])
                conflict_set.append({"instance_id": instance_id, "pose_id": pose_id})
                conflict_map_for_master[instance_id] = pose_idx

            if not conflict_set:
                return RUN_STATUS_UNKNOWN, None

            is_new = self.cut_manager.add_cut(
                conflict_set,
                reason="macro_flow_bottleneck",
                source="LBBD_Flow",
            )
            if not is_new:
                print("  > Extracted cut already exists! Loop stalling.")
                return RUN_STATUS_UNKNOWN, None

            print(f"  > Added new cut covering {len(conflict_set)} instances. Retrying...")
            self.master.add_benders_cut(conflict_map_for_master)
            iteration += 1

        print("--- [LBBD Loop] Max iterations reached ---")
        self.last_proof_summary = {
            "mode": "exploratory",
            "benders_iterations": self.max_iterations,
            "master_status": "MAX_ITERATIONS",
        }
        return RUN_STATUS_UNPROVEN, None

    def _run_certified_exact(self) -> Tuple[str, Optional[Dict[str, Any]]]:
        diagnostic_flow_status = "NOT_RUN"
        self._greedy_hint = self.master.build_greedy_solution_hint()
        self._greedy_hint_instances = len(self._greedy_hint)
        self._used_greedy_hint = False
        self._master_hinted_literals = 0
        for iteration in range(1, self.max_iterations + 1):
            print(f"\n--- [LBBD Exact Loop] Iteration {iteration}/{self.max_iterations} ---")
            print("  > Solving Master Problem...")

            solve_hint: Optional[Mapping[str, int]] = None
            if iteration == 1 and self._greedy_hint:
                solve_hint = self._greedy_hint
                self._used_greedy_hint = True

            master_status = self.master.solve(
                time_limit_seconds=self.master_seconds,
                solution_hint=solve_hint,
                known_feasible_hint=False,
            )
            if iteration == 1:
                self._master_hinted_literals = int(
                    self.master.build_stats.get("last_solve", {}).get("hinted_literals", 0)
                )
            if master_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                pass
            elif master_status == cp_model.INFEASIBLE:
                self.last_proof_summary = {
                    "mode": "certified_exact",
                    "benders_iterations": iteration,
                    "master_status": "INFEASIBLE",
                    "diagnostic_flow_status": diagnostic_flow_status,
                    "enumerated_bindings": 0,
                    "routing_attempts": 0,
                    "exact_safe_cut_count": len(self.loaded_exact_safe_cuts) + len(self.generated_exact_safe_cuts),
                    **self._exact_warm_start_summary(),
                    **self._master_search_summary(),
                    **self._subproblem_reuse_summary(),
                    **self._exact_cut_ladder_summary(),
                }
                return RUN_STATUS_INFEASIBLE, None
            else:
                self.last_proof_summary = {
                    "mode": "certified_exact",
                    "benders_iterations": iteration,
                    "master_status": "UNKNOWN",
                    "diagnostic_flow_status": diagnostic_flow_status,
                    "enumerated_bindings": 0,
                    "routing_attempts": 0,
                    **self._exact_warm_start_summary(),
                    **self._master_search_summary(),
                    **self._subproblem_reuse_summary(),
                    **self._exact_cut_ladder_summary(),
                }
                return RUN_STATUS_UNKNOWN, None

            solution = self.master.extract_solution()
            if not solution:
                self.last_proof_summary = {
                    "mode": "certified_exact",
                    "benders_iterations": iteration,
                    "master_status": "EMPTY_SOLUTION",
                    "diagnostic_flow_status": diagnostic_flow_status,
                    "enumerated_bindings": 0,
                    "routing_attempts": 0,
                    **self._exact_warm_start_summary(),
                    **self._master_search_summary(),
                    **self._subproblem_reuse_summary(),
                    **self._exact_cut_ladder_summary(),
                }
                return RUN_STATUS_UNKNOWN, None

            flow_status, _bottlenecks = self._run_flow_diagnostic(solution)
            diagnostic_flow_status = flow_status

            result_status, certified_solution = self._run_exact_binding_and_routing(
                iteration=iteration,
                solution=solution,
                diagnostic_flow_status=diagnostic_flow_status,
            )
            if result_status == _EXACT_INTERNAL_STATUS_MASTER_CUT_ADDED_CONTINUE:
                continue
            if result_status == RUN_STATUS_CERTIFIED:
                return RUN_STATUS_CERTIFIED, certified_solution
            if result_status == RUN_STATUS_INFEASIBLE:
                return RUN_STATUS_INFEASIBLE, None
            if result_status == RUN_STATUS_UNKNOWN:
                return RUN_STATUS_UNKNOWN, None

        self.last_proof_summary = {
            "mode": "certified_exact",
            "benders_iterations": self.max_iterations,
            "master_status": "MAX_ITERATIONS",
            "diagnostic_flow_status": diagnostic_flow_status,
            "enumerated_bindings": 0,
            "routing_attempts": 0,
            "exact_safe_cut_count": len(self.loaded_exact_safe_cuts) + len(self.generated_exact_safe_cuts),
            **self._exact_warm_start_summary(),
            **self._subproblem_reuse_summary(),
            **self._exact_cut_ladder_summary(),
        }
        return RUN_STATUS_UNPROVEN, None

    def _run_flow_diagnostic(
        self,
        solution: Mapping[str, Mapping[str, Any]],
    ) -> Tuple[str, Set[str]]:
        occupied_cells: Set[Tuple[int, int]] = set()
        port_dict: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

        for instance_id, solution_entry in solution.items():
            pose_idx = int(solution_entry["pose_idx"])
            facility_type = str(solution_entry["facility_type"])
            pose = self.master.facility_pools[facility_type][pose_idx]

            for cell in pose.get("occupied_cells", []):
                occupied_cells.add((int(cell[0]), int(cell[1])))

            for port in pose.get("input_port_cells", []):
                payload = dict(port)
                payload["instance_id"] = instance_id
                payload["type"] = "in"
                port_dict["dummy_commodity"].append(payload)

            for port in pose.get("output_port_cells", []):
                payload = dict(port)
                payload["instance_id"] = instance_id
                payload["type"] = "out"
                port_dict["dummy_commodity"].append(payload)

        flow_network = build_flow_network(occupied_cells, port_dict, self.commodity_demands)
        flow_subproblem = FlowSubproblem(
            flow_network,
            self.commodity_demands,
            solve_mode=self.solve_mode,
        )
        flow_status = flow_subproblem.build_and_solve(time_limit_ms=int(self.flow_seconds * 1000))
        return flow_status, set(flow_subproblem.extract_bottleneck_instances())

    def _run_exact_binding_and_routing(
        self,
        *,
        iteration: int,
        solution: Dict[str, Any],
        diagnostic_flow_status: str,
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        binding_model = PortBindingModel(
            solution,
            self.master.facility_pools,
            self.master.source_instances,
            project_root=self.project_root,
        )
        binding_model.build()
        self._used_routing_core_reuse = False
        self._routing_core_build_seconds = 0.0
        self._routing_overlay_build_seconds = 0.0
        self._routing_domain_cells = 0
        self._routing_terminal_core_cells = 0
        self._routing_state_space_vars = 0
        self._routing_local_pattern_pruned_states = 0
        self._update_binding_cache_from_summary(binding_model.extract_conflict_summary())

        enumerated_bindings = 0
        routing_attempts = 0
        occupied_cells = self._extract_occupied_cells(solution)
        occupied_owner_by_cell = self._extract_occupied_owner_by_cell(solution)
        routing_placement_core: Optional[RoutingPlacementCore] = None
        empty_binding_domain_instances = list(
            getattr(binding_model, "extract_empty_binding_domain_instances", lambda: [])()
        )
        if empty_binding_domain_instances:
            cut_added = False
            for empty_domain in empty_binding_domain_instances:
                conflict_set = self._build_conflict_from_instance_ids(
                    solution,
                    [str(empty_domain["instance_id"])],
                )
                if not conflict_set:
                    continue
                cut_summary = {
                    "mode": "certified_exact",
                    "benders_iterations": iteration,
                    "master_status": "FEASIBLE",
                    "binding_status": "EMPTY_DOMAIN",
                    "diagnostic_flow_status": diagnostic_flow_status,
                    "enumerated_bindings": enumerated_bindings,
                    "routing_attempts": routing_attempts,
                    "binding_summary": binding_model.extract_conflict_summary(),
                    "empty_binding_domain_instance": dict(empty_domain),
                    **self._exact_warm_start_summary(),
                    **self._subproblem_reuse_summary(),
                    **self._exact_cut_ladder_summary_with_deltas(
                        fine_grained_delta=1,
                        binding_domain_empty_delta=1,
                    ),
                }
                was_added = self._add_exact_persisted_nogood(
                    conflict_set=conflict_set,
                    iteration=iteration,
                    cut_type="binding_pose_domain_empty_nogood",
                    proof_stage="binding",
                    proof_summary=cut_summary,
                    metadata={"kind": "placement_local_nogood"},
                )
                if was_added:
                    self._fine_grained_exact_safe_cut_count += 1
                    self._binding_domain_empty_cut_count += 1
                    cut_added = True

            self.last_proof_summary = {
                "mode": "certified_exact",
                "benders_iterations": iteration,
                "master_status": "FEASIBLE",
                "binding_status": "EMPTY_DOMAIN",
                "diagnostic_flow_status": diagnostic_flow_status,
                "enumerated_bindings": enumerated_bindings,
                "routing_attempts": routing_attempts,
                "binding_summary": binding_model.extract_conflict_summary(),
                "master_follow_up": (
                    _EXACT_INTERNAL_STATUS_MASTER_CUT_ADDED_CONTINUE if cut_added else "cut_stall"
                ),
                **self._exact_warm_start_summary(),
                **self._subproblem_reuse_summary(),
                **self._exact_cut_ladder_summary(),
            }
            if cut_added:
                return _EXACT_INTERNAL_STATUS_MASTER_CUT_ADDED_CONTINUE, None
            return RUN_STATUS_UNKNOWN, None

        binding_status = binding_model.solve(time_limit_seconds=self.binding_seconds)
        if binding_status == "TIMEOUT":
            self.last_proof_summary = {
                "mode": "certified_exact",
                "benders_iterations": iteration,
                "master_status": "FEASIBLE",
                "binding_status": "TIMEOUT",
                "diagnostic_flow_status": diagnostic_flow_status,
                "enumerated_bindings": enumerated_bindings,
                "routing_attempts": routing_attempts,
                "binding_summary": binding_model.extract_conflict_summary(),
                **self._exact_warm_start_summary(),
                **self._subproblem_reuse_summary(),
                **self._exact_cut_ladder_summary(),
            }
            return RUN_STATUS_UNKNOWN, None

        if binding_status == "INFEASIBLE":
            proof_summary = {
                "mode": "certified_exact",
                "benders_iterations": iteration,
                "master_status": "FEASIBLE",
                "binding_status": "INFEASIBLE",
                "diagnostic_flow_status": diagnostic_flow_status,
                "enumerated_bindings": enumerated_bindings,
                "routing_attempts": routing_attempts,
                "binding_summary": binding_model.extract_conflict_summary(),
                **self._exact_warm_start_summary(),
                **self._subproblem_reuse_summary(),
                **self._exact_cut_ladder_summary(),
            }
            self._add_exact_whole_layout_nogood(
                solution=solution,
                iteration=iteration,
                cut_type="binding_infeasible_nogood",
                proof_stage="binding",
                binding_exhausted=True,
                routing_exhausted=False,
                proof_summary=proof_summary,
            )
            self.last_proof_summary = dict(proof_summary)
            return RUN_STATUS_INFEASIBLE, None

        routing_core_started = time.perf_counter()
        routing_placement_core = RoutingPlacementCore.from_occupied_cells(
            occupied_cells,
            occupied_owner_by_cell=occupied_owner_by_cell,
        )
        self._used_routing_core_reuse = True
        self._routing_core_build_seconds = time.perf_counter() - routing_core_started

        while binding_status == "FEASIBLE":
            selection = binding_model.extract_selection()
            port_specs = binding_model.extract_port_specs()
            enumerated_bindings += 1

            routing_grid = None
            if routing_placement_core is not None and hasattr(RoutingGrid, "from_placement_core"):
                try:
                    routing_grid = RoutingGrid.from_placement_core(routing_placement_core, port_specs)
                except TypeError:
                    routing_grid = None
            if routing_grid is None:
                try:
                    routing_grid = RoutingGrid(
                        occupied_cells,
                        port_specs,
                        occupied_owner_by_cell=occupied_owner_by_cell,
                    )
                except TypeError:
                    routing_grid = RoutingGrid(occupied_cells, port_specs)

            routing_domain_analysis = None
            routing_precheck = None
            if routing_placement_core is not None and hasattr(RoutingGrid, "from_placement_core"):
                try:
                    routing_precheck = run_exact_routing_precheck(
                        placement_core=routing_placement_core,
                        port_specs=port_specs,
                        occupied_owner_by_cell=occupied_owner_by_cell,
                    )
                except TypeError:
                    routing_precheck = None
            if routing_precheck is None and hasattr(routing_grid, "free_cells") and hasattr(routing_grid, "port_specs"):
                try:
                    routing_precheck = run_exact_routing_precheck(
                        routing_grid,
                        occupied_owner_by_cell=occupied_owner_by_cell,
                    )
                except TypeError:
                    routing_precheck = run_exact_routing_precheck(routing_grid)
            if routing_precheck is None:
                routing_precheck = {
                    "status": "feasible",
                    "binding_selection_safe_reject": False,
                    "placement_level_conflict_set": [],
                    "blocked_ports": [],
                    "disconnected_commodities": [],
                }
            routing_domain_analysis = routing_precheck.get("_analysis")
            routing_precheck_summary = {
                str(key): value
                for key, value in routing_precheck.items()
                if str(key) != "_analysis"
            }
            self._update_routing_shrink_from_domain_stats(
                routing_precheck_summary.get("domain_stats")
            )
            precheck_status = str(routing_precheck_summary.get("status", "feasible"))
            self._routing_precheck_statuses.append(precheck_status)

            if precheck_status == "front_blocked":
                self._routing_precheck_rejections += 1
                cut_added = False
                for blocked_port in routing_precheck_summary.get("blocked_ports", []):
                    conflict_set = self._build_conflict_from_instance_ids(
                        solution,
                        list(blocked_port.get("placement_level_conflict_set", [])),
                    )
                    if not conflict_set:
                        continue
                    cut_summary = {
                        "mode": "certified_exact",
                        "benders_iterations": iteration,
                        "master_status": "FEASIBLE",
                        "binding_status": "FEASIBLE",
                        "routing_status": "PRECHECK_FRONT_BLOCKED",
                        "diagnostic_flow_status": diagnostic_flow_status,
                        "enumerated_bindings": enumerated_bindings,
                        "routing_attempts": routing_attempts,
                        "binding_summary": binding_model.extract_conflict_summary(),
                        "routing_precheck": dict(routing_precheck_summary),
                        "blocked_port": dict(blocked_port),
                        **self._exact_warm_start_summary(),
                        **self._subproblem_reuse_summary(),
                        **self._routing_shrink_summary(),
                        **self._exact_cut_ladder_summary_with_deltas(
                            fine_grained_delta=1,
                            routing_front_blocked_delta=1,
                        ),
                    }
                    was_added = self._add_exact_persisted_nogood(
                        conflict_set=conflict_set,
                        iteration=iteration,
                        cut_type="routing_front_blocked_nogood",
                        proof_stage="routing",
                        proof_summary=cut_summary,
                        metadata={"kind": "placement_local_nogood"},
                    )
                    if was_added:
                        self._fine_grained_exact_safe_cut_count += 1
                        self._routing_front_blocked_cut_count += 1
                        cut_added = True

                self.last_proof_summary = {
                    "mode": "certified_exact",
                    "benders_iterations": iteration,
                    "master_status": "FEASIBLE",
                    "binding_status": "FEASIBLE",
                    "routing_status": "PRECHECK_FRONT_BLOCKED",
                    "diagnostic_flow_status": diagnostic_flow_status,
                    "enumerated_bindings": enumerated_bindings,
                    "routing_attempts": routing_attempts,
                    "binding_summary": binding_model.extract_conflict_summary(),
                    "routing_precheck": dict(routing_precheck_summary),
                    "master_follow_up": (
                        _EXACT_INTERNAL_STATUS_MASTER_CUT_ADDED_CONTINUE if cut_added else "cut_stall"
                    ),
                    **self._exact_warm_start_summary(),
                    **self._subproblem_reuse_summary(),
                    **self._routing_shrink_summary(),
                    **self._exact_cut_ladder_summary(),
                }
                if cut_added:
                    return _EXACT_INTERNAL_STATUS_MASTER_CUT_ADDED_CONTINUE, None
                return RUN_STATUS_UNKNOWN, None

            if precheck_status == "relaxed_disconnected":
                self._routing_precheck_rejections += 1
                if self._binding_has_alternatives(binding_model):
                    binding_model.add_nogood_cut(selection)
                    binding_status = binding_model.solve(time_limit_seconds=self.binding_seconds)
                    if binding_status == "TIMEOUT":
                        self.last_proof_summary = {
                            "mode": "certified_exact",
                            "benders_iterations": iteration,
                            "master_status": "FEASIBLE",
                            "binding_status": "TIMEOUT",
                            "routing_status": "PRECHECK_RELAXED_DISCONNECTED",
                            "diagnostic_flow_status": diagnostic_flow_status,
                            "enumerated_bindings": enumerated_bindings,
                            "routing_attempts": routing_attempts,
                            "binding_summary": binding_model.extract_conflict_summary(),
                            "routing_precheck": dict(routing_precheck_summary),
                            **self._exact_warm_start_summary(),
                            **self._subproblem_reuse_summary(),
                            **self._routing_shrink_summary(),
                            **self._exact_cut_ladder_summary(),
                        }
                        return RUN_STATUS_UNKNOWN, None
                    continue
                break

            commodities = sorted({str(port["commodity"]) for port in port_specs})
            routing_overlay_started = time.perf_counter()
            routing_model = None
            if (
                routing_placement_core is not None
                and hasattr(RoutingGrid, "from_placement_core")
                and hasattr(RoutingSubproblem, "from_placement_core")
            ):
                try:
                    routing_model = RoutingSubproblem.from_placement_core(
                        routing_placement_core,
                        port_specs,
                        commodities,
                        domain_analysis=routing_domain_analysis,
                    )
                except TypeError:
                    routing_model = None
            if routing_model is None:
                if routing_domain_analysis is None:
                    routing_model = RoutingSubproblem(routing_grid, commodities)
                else:
                    try:
                        routing_model = RoutingSubproblem(
                            routing_grid,
                            commodities,
                            domain_analysis=routing_domain_analysis,
                        )
                    except TypeError:
                        routing_model = RoutingSubproblem(routing_grid, commodities)
            routing_model.build()
            self._routing_overlay_build_seconds = time.perf_counter() - routing_overlay_started
            self._update_routing_shrink_from_build_stats(routing_model.build_stats)
            routing_attempts += 1
            routing_status = routing_model.solve(time_limit=self.routing_seconds)

            if routing_status == "FEASIBLE":
                self.last_proof_summary = {
                    "mode": "certified_exact",
                    "benders_iterations": iteration,
                    "master_status": "FEASIBLE",
                    "binding_status": "FEASIBLE",
                    "routing_status": "FEASIBLE",
                    "diagnostic_flow_status": diagnostic_flow_status,
                    "enumerated_bindings": enumerated_bindings,
                    "routing_attempts": routing_attempts,
                    "binding_summary": binding_model.extract_conflict_summary(),
                    "routing_summary": dict(routing_model.build_stats),
                    **self._exact_warm_start_summary(),
                    **self._subproblem_reuse_summary(),
                    **self._routing_shrink_summary(),
                    **self._exact_cut_ladder_summary(),
                }
                return RUN_STATUS_CERTIFIED, solution

            if routing_status == "TIMEOUT":
                self.last_proof_summary = {
                    "mode": "certified_exact",
                    "benders_iterations": iteration,
                    "master_status": "FEASIBLE",
                    "binding_status": "FEASIBLE",
                    "routing_status": "TIMEOUT",
                    "diagnostic_flow_status": diagnostic_flow_status,
                    "enumerated_bindings": enumerated_bindings,
                    "routing_attempts": routing_attempts,
                    "binding_summary": binding_model.extract_conflict_summary(),
                    "routing_summary": dict(routing_model.build_stats),
                    **self._exact_warm_start_summary(),
                    **self._subproblem_reuse_summary(),
                    **self._routing_shrink_summary(),
                    **self._exact_cut_ladder_summary(),
                }
                return RUN_STATUS_UNKNOWN, None

            if self._binding_has_alternatives(binding_model):
                binding_model.add_nogood_cut(selection)
                binding_status = binding_model.solve(time_limit_seconds=self.binding_seconds)
                if binding_status == "TIMEOUT":
                    self.last_proof_summary = {
                        "mode": "certified_exact",
                        "benders_iterations": iteration,
                        "master_status": "FEASIBLE",
                        "binding_status": "TIMEOUT",
                        "routing_status": "INFEASIBLE",
                        "diagnostic_flow_status": diagnostic_flow_status,
                        "enumerated_bindings": enumerated_bindings,
                        "routing_attempts": routing_attempts,
                        "binding_summary": binding_model.extract_conflict_summary(),
                        "routing_summary": dict(routing_model.build_stats),
                        **self._exact_warm_start_summary(),
                        **self._subproblem_reuse_summary(),
                        **self._routing_shrink_summary(),
                        **self._exact_cut_ladder_summary(),
                    }
                    return RUN_STATUS_UNKNOWN, None
                continue

            break

        proof_summary = {
            "mode": "certified_exact",
            "benders_iterations": iteration,
            "master_status": "FEASIBLE",
            "binding_status": "EXHAUSTED",
            "routing_status": "ALL_INFEASIBLE",
            "diagnostic_flow_status": diagnostic_flow_status,
            "enumerated_bindings": enumerated_bindings,
            "routing_attempts": routing_attempts,
            "binding_summary": binding_model.extract_conflict_summary(),
            **self._exact_warm_start_summary(),
            **self._subproblem_reuse_summary(),
            **self._routing_shrink_summary(),
            **self._exact_cut_ladder_summary(),
        }
        self._add_exact_whole_layout_nogood(
            solution=solution,
            iteration=iteration,
            cut_type="routing_exhausted_nogood",
            proof_stage="routing",
            binding_exhausted=True,
            routing_exhausted=True,
            proof_summary=proof_summary,
        )
        self.last_proof_summary = dict(proof_summary)
        return RUN_STATUS_INFEASIBLE, None

    def _extract_occupied_owner_by_cell(
        self,
        solution: Mapping[str, Mapping[str, Any]],
    ) -> Dict[Tuple[int, int], str]:
        owner_by_cell: Dict[Tuple[int, int], str] = {}
        for instance_id, solution_entry in solution.items():
            pose_idx = int(solution_entry["pose_idx"])
            facility_type = str(solution_entry["facility_type"])
            pose = self.master.facility_pools[facility_type][pose_idx]
            for cell in pose.get("occupied_cells", []):
                owner_by_cell[(int(cell[0]), int(cell[1]))] = str(instance_id)
        return owner_by_cell

    def _extract_occupied_cells(
        self,
        solution: Mapping[str, Mapping[str, Any]],
    ) -> Set[Tuple[int, int]]:
        occupied_cells: Set[Tuple[int, int]] = set()
        for solution_entry in solution.values():
            pose_idx = int(solution_entry["pose_idx"])
            facility_type = str(solution_entry["facility_type"])
            pose = self.master.facility_pools[facility_type][pose_idx]
            for cell in pose.get("occupied_cells", []):
                occupied_cells.add((int(cell[0]), int(cell[1])))
        return occupied_cells

    def _binding_has_alternatives(self, binding_model: PortBindingModel) -> bool:
        return bool(
            binding_model.binding_vars
            or binding_model.generic_input_vars
            or binding_model.generic_output_vars
        )

    def _build_whole_layout_conflict(
        self,
        solution: Mapping[str, Mapping[str, Any]],
    ) -> Dict[str, int]:
        return {
            str(instance_id): int(solution_entry["pose_idx"])
            for instance_id, solution_entry in solution.items()
        }

    def _build_conflict_from_instance_ids(
        self,
        solution: Mapping[str, Mapping[str, Any]],
        instance_ids: Sequence[str],
    ) -> Dict[str, int]:
        conflict_set: Dict[str, int] = {}
        for instance_id in instance_ids:
            if instance_id not in solution:
                continue
            conflict_set[str(instance_id)] = int(solution[instance_id]["pose_idx"])
        return conflict_set

    def _add_exact_persisted_nogood(
        self,
        *,
        conflict_set: Mapping[str, int],
        iteration: int,
        cut_type: str,
        proof_stage: str,
        proof_summary: Mapping[str, Any],
        metadata: Optional[Mapping[str, Any]] = None,
        binding_exhausted: bool = False,
        routing_exhausted: bool = False,
    ) -> bool:
        cut = BendersCut(
            schema_version=2,
            cut_type=cut_type,
            conflict_set={str(k): int(v) for k, v in conflict_set.items()},
            iteration=iteration,
            metadata=dict(metadata or {}),
            source_mode="certified_exact",
            exact_safe=True,
            artifact_hashes=dict(self.artifact_hashes),
            proof_stage=proof_stage,
            binding_exhausted=binding_exhausted,
            routing_exhausted=routing_exhausted,
            proof_summary=dict(proof_summary),
            created_at=now_iso(),
        )
        if not self.cut_manager.register_structured_cut(cut):
            return False
        self.generated_exact_safe_cuts.append(cut)
        self.master.add_benders_cut(conflict_set)
        return True

    def _add_exact_whole_layout_nogood(
        self,
        *,
        solution: Mapping[str, Mapping[str, Any]],
        iteration: int,
        cut_type: str,
        proof_stage: str,
        binding_exhausted: bool,
        routing_exhausted: bool,
        proof_summary: Mapping[str, Any],
    ) -> None:
        conflict_set = self._build_whole_layout_conflict(solution)
        self._add_exact_persisted_nogood(
            conflict_set=conflict_set,
            iteration=iteration,
            cut_type=cut_type,
            proof_stage=proof_stage,
            proof_summary=proof_summary,
            metadata={"kind": "whole_layout_nogood"},
            binding_exhausted=binding_exhausted,
            routing_exhausted=routing_exhausted,
        )


def run_benders_for_ghost_rect(
    *,
    ghost_w: int,
    ghost_h: int,
    max_iterations: int = 30,
    project_root: Optional[Path] = None,
    solve_mode: Optional[str] = None,
    certification_mode: Optional[bool] = None,
    master_seconds: float = 600.0,
    binding_seconds: float = 600.0,
    routing_seconds: float = 600.0,
    flow_seconds: float = 60.0,
    campaign: Optional[Any] = None,
    session: Optional[ExactSearchSession] = None,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Run the current Benders loop for one ghost rectangle size."""

    _reset_last_run_metadata()

    solve_mode = _normalize_solve_mode(solve_mode, certification_mode)
    project_root = project_root or PROJECT_ROOT

    instances: List[Dict[str, Any]]
    facility_pools: Dict[str, List[Dict[str, Any]]]
    rules: Dict[str, Any]
    artifact_hashes: Dict[str, str] = {}
    used_exact_core_reuse = False
    core_build_seconds = 0.0
    overlay_build_seconds = 0.0
    ghost_constraint_seconds = 0.0
    cut_replay_seconds = 0.0
    exact_session: Optional[ExactSearchSession] = None
    if solve_mode == "certified_exact":
        exact_session = session
        if exact_session is None:
            exact_session = ExactSearchSession.create(project_root, solve_mode=solve_mode)
        elif exact_session.project_root != project_root or exact_session.solve_mode != solve_mode:
            raise ValueError("ExactSearchSession does not match the requested project_root/solve_mode")

        instances = list(exact_session.instances)
        facility_pools = dict(exact_session.facility_pools)
        rules = dict(exact_session.rules)
        artifact_hashes = dict(exact_session.artifact_hashes)
        core_build_seconds = float(exact_session.core_build_seconds)
        blockers = collect_certification_blockers(instances=instances, solve_mode=solve_mode)
        if blockers:
            _publish_last_run_metadata(
                _merge_reuse_metadata(
                    {
                        "mode": "certified_exact",
                        "master_status": "BLOCKED",
                        "blockers": blockers,
                        "enumerated_bindings": 0,
                        "routing_attempts": 0,
                        "diagnostic_flow_status": "NOT_RUN",
                        "used_greedy_hint": False,
                        "greedy_hint_instances": 0,
                        "master_hinted_literals": 0,
                    },
                    used_exact_core_reuse=True,
                    core_build_seconds=core_build_seconds,
                    overlay_build_seconds=0.0,
                    ghost_constraint_seconds=0.0,
                    cut_replay_seconds=0.0,
                ),
                [],
                loaded_exact_safe_cut_count=0,
                generated_exact_safe_cut_count=0,
            )
            return RUN_STATUS_UNPROVEN, None
    else:
        instances, facility_pools, rules = load_project_data(project_root, solve_mode=solve_mode)

    grid = dict(rules["globals"]["grid"])
    grid_area = int(grid["width"]) * int(grid["height"])
    static_area_lower_bound = compute_mandatory_area_lower_bound(instances, rules)
    if solve_mode == "certified_exact" and exact_session is not None:
        static_area_lower_bound = compute_exact_static_area_lower_bound(
            instances,
            rules,
            exact_session.core.generic_io_requirements,
        )
    if static_area_lower_bound + int(ghost_w) * int(ghost_h) > grid_area:
        _publish_last_run_metadata(
            _merge_reuse_metadata(
                {
                    "mode": solve_mode,
                    "master_status": "AREA_PRECHECK_FAILED",
                    "enumerated_bindings": 0,
                    "routing_attempts": 0,
                    "diagnostic_flow_status": "NOT_RUN",
                    "used_greedy_hint": False,
                    "greedy_hint_instances": 0,
                    "master_hinted_literals": 0,
                },
                used_exact_core_reuse=bool(solve_mode == "certified_exact"),
                core_build_seconds=core_build_seconds,
                overlay_build_seconds=0.0,
                ghost_constraint_seconds=0.0,
                cut_replay_seconds=0.0,
            ),
            [],
            loaded_exact_safe_cut_count=0,
            generated_exact_safe_cut_count=0,
        )
        return RUN_STATUS_INFEASIBLE, None

    cut_manager = CutManager(
        checkpoint_dir=project_root / "data" / "checkpoints",
        solve_mode=solve_mode,
        current_hashes=artifact_hashes,
    )
    if solve_mode == "certified_exact":
        if exact_session is None:
            raise RuntimeError("Exact exact_session should have been initialized")
        overlay_started = time.perf_counter()
        master = MasterPlacementModel.from_exact_core(
            exact_session.core,
            ghost_rect=(int(ghost_w), int(ghost_h)),
        )
        reuse_stats = dict(master.build_stats.get("exact_core_reuse", {}))
        overlay_build_seconds = float(
            reuse_stats.get("overlay_build_seconds", time.perf_counter() - overlay_started)
        )
        ghost_constraint_seconds = float(reuse_stats.get("ghost_constraint_seconds", 0.0))
        used_exact_core_reuse = True
    else:
        master = MasterPlacementModel(
            instances,
            facility_pools,
            rules,
            ghost_rect=(int(ghost_w), int(ghost_h)),
            solve_mode=solve_mode,
        )
        master.build()

    loaded_exact_safe_cuts: List[BendersCut] = []
    cut_replay_started = time.perf_counter()
    if solve_mode == "certified_exact" and isinstance(campaign, ExactCampaign):
        for raw_cut in campaign.get_candidate_cuts(int(ghost_w), int(ghost_h)):
            try:
                cut = BendersCut.from_dict(raw_cut)
            except Exception:
                continue
            blockers = collect_certification_blockers(
                solve_mode=solve_mode,
                loaded_cuts=[cut],
                current_hashes=artifact_hashes,
            )
            if blockers:
                continue
            if cut_manager.register_structured_cut(cut):
                loaded_exact_safe_cuts.append(cut)
                master.add_benders_cut({str(k): int(v) for k, v in cut.conflict_set.items()})
    cut_replay_seconds = time.perf_counter() - cut_replay_started

    controller = LBBDController(
        master,
        cut_manager,
        project_root=project_root,
        solve_mode=solve_mode,
        max_iterations=max_iterations,
        master_seconds=master_seconds,
        binding_seconds=binding_seconds,
        routing_seconds=routing_seconds,
        flow_seconds=flow_seconds,
        artifact_hashes=artifact_hashes,
        loaded_exact_safe_cuts=loaded_exact_safe_cuts,
    )
    status, solution = controller.run_with_status()
    binding_summary = dict(controller.last_proof_summary.get("binding_summary", {}))
    proof_summary = _merge_reuse_metadata(
        {
            **dict(controller.last_proof_summary),
            **controller._master_search_summary(),
            "binding_search_profile": str(
                binding_summary.get(
                    "search_profile",
                    dict(binding_summary.get("search_guidance", {})).get(
                        "profile",
                        "exact_binding_guided_branching_v1",
                    ),
                )
            ),
            **controller._routing_shrink_summary(),
        },
        used_exact_core_reuse=used_exact_core_reuse,
        core_build_seconds=core_build_seconds,
        overlay_build_seconds=overlay_build_seconds,
        ghost_constraint_seconds=ghost_constraint_seconds,
        cut_replay_seconds=cut_replay_seconds,
    )
    _publish_last_run_metadata(
        proof_summary,
        [*loaded_exact_safe_cuts, *controller.generated_exact_safe_cuts],
        loaded_exact_safe_cut_count=len(loaded_exact_safe_cuts),
        generated_exact_safe_cut_count=len(controller.generated_exact_safe_cuts),
    )
    return status, solution


run_benders_for_ghost_rect.last_run_metadata = {
    "proof_summary": {},
    "exact_safe_cuts": [],
    "loaded_exact_safe_cut_count": 0,
    "generated_exact_safe_cut_count": 0,
    "fine_grained_exact_safe_cut_count": 0,
    "binding_domain_empty_cut_count": 0,
    "routing_front_blocked_cut_count": 0,
    "routing_precheck_rejections": 0,
    "routing_precheck_statuses": [],
    "routing_domain_cells": 0,
    "routing_terminal_core_cells": 0,
    "routing_state_space_vars": 0,
    "routing_local_pattern_pruned_states": 0,
    "used_routing_core_reuse": False,
    "routing_core_build_seconds": 0.0,
    "routing_overlay_build_seconds": 0.0,
    "binding_domain_cache_hits": 0,
    "binding_domain_cache_misses": 0,
    "binding_domain_reused_instances": [],
    "master_search_profile": "default_automatic",
    "power_pole_family_order": [],
    "power_pole_family_count_literals": 0,
    "residual_optional_family_guided": False,
    "binding_search_profile": "exact_binding_guided_branching_v1",
    "diagnostic_flow_status": "NOT_RUN",
    "master_status": None,
    "binding_status": None,
    "routing_status": None,
    "mode": None,
    "used_exact_core_reuse": False,
    "core_build_seconds": 0.0,
    "overlay_build_seconds": 0.0,
    "ghost_constraint_seconds": 0.0,
    "cut_replay_seconds": 0.0,
    "master_representation": "pose_bool_v1",
    "master_slot_counts": {},
    "master_mode_literals": 0,
    "master_interval_count": 0,
    "master_pose_bool_literals": 0,
    "master_domain_encoding": "",
    "master_domain_table_rows": 0,
    "master_mode_rect_domains": {},
    "power_pole_shell_lookup_pairs": {},
    "power_coverage_representation": "",
    "power_coverage_encoding": "",
    "power_coverage_powered_slots": 0,
    "power_coverage_pole_slots": 0,
    "power_coverage_cover_literals": 0,
    "power_coverage_witness_indices": 0,
    "power_coverage_element_constraints": 0,
    "power_coverage_radius": 0,
    "power_capacity_shell_pairs": 0,
    "power_capacity_shell_pair_evaluations": 0,
    "power_capacity_signature_classes": 0,
    "power_capacity_signature_class_evaluations": 0,
    "power_capacity_raw_pole_evaluations": 0,
    "signature_bucket_cache_hits": 0,
    "signature_bucket_cache_misses": 0,
    "signature_bucket_distinct_keys": 0,
    "geometry_cache_templates": 0,
}
