"""
Master Placement Model（主摆放模型）.

设计目标：
1. certified_exact（严格认证精确）与 exploratory（探索）两条路径严格分离。
2. 严格精确路径只读取 mandatory exact（必选精确）实例，
   可选设施通过 pose-level optional variables（位姿级可选变量）直接建模；
   不再把 50 / 10 之类经验上限写成正式约束。
3. exploratory（探索）路径可以继续对位姿级可选设施施加经验上限。
4. extract_solution()（提取解）为位姿级可选设施生成可持久化识别的完整实例条目。
5. 集成 Benders 切平面反馈（Cuts），支持外部的 conflict set 并打回重摆。
"""

from __future__ import annotations

import copy
import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, DefaultDict, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from ortools.sat.python import cp_model

from src.models.exact_coordinate_master import CoordinateExactMasterDelegate
from src.preprocess.operation_profiles import get_operation_port_profile

ModeToken = Tuple[str, str]
POSE_LEVEL_OPTIONAL_TEMPLATES = {"power_pole", "protocol_storage_box"}
POSE_LEVEL_OPTIONAL_OPERATIONS = {
    "power_pole": "power_supply",
    "protocol_storage_box": "wireless_sink",
}
DIR_DELTA = {"N": (0, 1), "S": (0, -1), "E": (1, 0), "W": (-1, 0)}
LocalPoseShape = Tuple[Tuple[int, int], ...]
PoseLocalSignature = Tuple[LocalPoseShape, LocalPoseShape, LocalPoseShape, int]
LocalCapacitySignature = Tuple[LocalPoseShape, ...]
CompactLocalCapacityItem = Tuple[int, int, int]
CompactLocalCapacitySignature = Tuple[CompactLocalCapacityItem, ...]
ShellPair = Tuple[int, int]
PackedRectTransition = Tuple[int, int, int]
_LOCAL_POWER_CAPACITY_CACHE: Dict[Tuple[str, LocalCapacitySignature], int] = {}
_LOCAL_POWER_CAPACITY_COMPACT_CACHE: Dict[
    Tuple[str, CompactLocalCapacitySignature],
    int,
] = {}
_LOCAL_POWER_CAPACITY_RECT_DP_CACHE: Dict[
    Tuple[str, CompactLocalCapacitySignature],
    int,
] = {}
_LOCAL_POWER_CAPACITY_RECT_DP_COMPILED_CACHE: Dict[
    Tuple[str, CompactLocalCapacitySignature, str],
    "_CompiledRectangleFrontierDP",
] = {}
_LOCAL_POWER_CAPACITY_M6X4_MIXED_CPSAT_DATA_CACHE: Dict[
    Tuple[str, CompactLocalCapacitySignature],
    "_CompiledManufacturing6x4MixedCpSatData",
] = {}


class _BitsetLocalCapacityFallback(RuntimeError):
    """Internal exact-safe signal to fall back to the legacy CP-SAT oracle."""


class _RectangleFrontierDPFallback(RuntimeError):
    """Internal exact-safe signal to fall back to the bitset local-capacity oracle."""


class _Manufacturing6x4MixedCpSatFallback(RuntimeError):
    """Internal exact-safe signal to fall back to rect-DP v3 explicitly."""


@dataclass(frozen=True)
class _LocalRectangleVariant:
    min_x: int
    min_y: int
    max_x: int
    max_y: int
    width: int
    height: int


@dataclass(frozen=True)
class _CompiledRectangleFrontierDP:
    scan_axis: str
    line_count: int
    line_width: int
    frontier_bits: int
    horizon: int
    line_end_shift: int
    current_bit_masks: Tuple[int, ...]
    placements_by_line_and_pos: Tuple[
        Tuple[Tuple[Tuple[int, int, Tuple[int, ...]], ...], ...],
        ...,
    ]
    start_options_by_line_and_pos: Tuple[
        Tuple[Tuple[PackedRectTransition, ...], ...],
        ...,
    ]
    line_subset_transitions_by_line: Tuple[Tuple[PackedRectTransition, ...], ...]
    compiled_start_options: int
    deduped_start_options: int
    compiled_line_subsets: int
    peak_line_subset_options: int


@dataclass(frozen=True)
class _CompiledManufacturing6x4MixedCpSatData:
    window_w: int
    window_h: int
    placements: Tuple[Tuple[int, int, int, int], ...]
    cell_to_placement_indices: Dict[Tuple[int, int], Tuple[int, ...]]


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _normalize_generic_io_requirements_payload(
    payload: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Dict[str, int]]:
    payload = dict(payload or {})
    return {
        "required_generic_outputs": {
            str(k): int(v)
            for k, v in dict(payload.get("required_generic_outputs", {})).items()
        },
        "required_generic_inputs": {
            str(k): int(v)
            for k, v in dict(payload.get("required_generic_inputs", {})).items()
        },
    }


def load_generic_io_requirements_artifact(project_root: Path) -> Dict[str, Dict[str, int]]:
    data_dir = project_root / "data" / "preprocessed"
    return _normalize_generic_io_requirements_payload(
        _load_json(data_dir / "generic_io_requirements.json")
    )


def infer_certified_optional_lower_bounds(
    rules: Mapping[str, Any],
    generic_io_requirements: Optional[Mapping[str, Any]] = None,
) -> Dict[str, int]:
    normalized_requirements = _normalize_generic_io_requirements_payload(
        generic_io_requirements
    )
    templates = dict(rules.get("facility_templates", {}))
    required_counts: Dict[str, int] = {}

    if "protocol_storage_box" in templates:
        slots_per_box = int(
            get_operation_port_profile(
                POSE_LEVEL_OPTIONAL_OPERATIONS["protocol_storage_box"]
            ).generic_input_slots
        )
        required_slots = sum(
            int(v)
            for v in normalized_requirements.get("required_generic_inputs", {}).values()
        )
        if slots_per_box > 0:
            required_box_count = (required_slots + slots_per_box - 1) // slots_per_box
            if required_box_count > 0:
                required_counts["protocol_storage_box"] = int(required_box_count)

    return required_counts


def infer_exact_required_pose_optional_counts(
    rules: Mapping[str, Any],
    generic_io_requirements: Optional[Mapping[str, Any]] = None,
) -> Dict[str, int]:
    """Backward-compatible alias for certified-exact lower-bound inference."""

    return infer_certified_optional_lower_bounds(
        rules,
        generic_io_requirements,
    )


def _clone_model_proto(proto: Any) -> Any:
    cloned = proto.__class__()
    if hasattr(cloned, "CopyFrom"):
        cloned.CopyFrom(proto)
    else:
        cloned.copy_from(proto)
    return cloned


def _normalize_solve_mode(
    solve_mode: Optional[str] = None,
    exact_mode: Optional[bool] = None,
) -> str:
    if exact_mode is not None:
        return "certified_exact" if exact_mode else "exploratory"
    if solve_mode is None:
        return "certified_exact"
    if solve_mode not in {"certified_exact", "exploratory"}:
        raise ValueError(f"Unsupported solve_mode（不支持的求解模式）: {solve_mode}")
    return solve_mode


def _load_mandatory_exact_instances(data_dir: Path) -> List[Dict[str, Any]]:
    exact_path = data_dir / "mandatory_exact_instances.json"
    if exact_path.exists():
        payload = _load_json(exact_path)
        if isinstance(payload, dict) and "instances" in payload:
            return list(payload["instances"])
        return list(payload)

    all_path = data_dir / "all_facility_instances.json"
    payload = _load_json(all_path)
    return [
        dict(inst)
        for inst in payload
        if bool(inst.get("is_mandatory")) and inst.get("bound_type") == "exact"
    ]


def _load_all_facility_instances(data_dir: Path) -> List[Dict[str, Any]]:
    all_path = data_dir / "all_facility_instances.json"
    if all_path.exists():
        payload = _load_json(all_path)
        if isinstance(payload, dict) and "instances" in payload:
            return list(payload["instances"])
        return list(payload)

    mandatory = _load_mandatory_exact_instances(data_dir)
    caps_path = data_dir / "exploratory_optional_caps.json"
    if not caps_path.exists():
        return mandatory
    caps = _load_json(caps_path)
    optional_instances: List[Dict[str, Any]] = []
    for facility_type, spec in dict(caps).items():
        cap = int(spec.get("cap", 0))
        prefix = "power_pole" if facility_type == "power_pole" else "protocol_box"
        for index in range(1, cap + 1):
            optional_instances.append(
                {
                    "instance_id": f"{prefix}_{index:03d}",
                    "facility_type": facility_type,
                    "operation_type": spec.get("operation_type", POSE_LEVEL_OPTIONAL_OPERATIONS.get(facility_type, facility_type)),
                    "is_mandatory": False,
                    "bound_type": spec.get("bound_type", "provisional"),
                }
            )
    return mandatory + optional_instances


def load_project_data(
    project_root: Path,
    solve_mode: str = "certified_exact",
) -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]], Dict[str, Any]]:
    """Load canonical project data（加载项目工件）.

    certified_exact（严格认证精确）默认只读取 mandatory_exact_instances.json。
    exploratory（探索）读取 all_facility_instances.json。
    """

    solve_mode = _normalize_solve_mode(solve_mode)
    data_dir = project_root / "data" / "preprocessed"

    if solve_mode == "certified_exact":
        instances = _load_mandatory_exact_instances(data_dir)
    else:
        instances = _load_all_facility_instances(data_dir)

    placements_payload = _load_json(data_dir / "candidate_placements.json")
    facility_pools = dict(placements_payload["facility_pools"])
    rules = dict(_load_json(project_root / "rules" / "canonical_rules.json"))
    return instances, facility_pools, rules


@dataclass
class ExactMasterCore:
    """Candidate-independent exact master core that can be cloned per ghost rectangle."""

    proto: Any
    source_instances: List[Dict[str, Any]]
    facility_pools: Dict[str, List[Dict[str, Any]]]
    rules: Dict[str, Any]
    generic_io_requirements: Dict[str, Dict[str, int]]
    build_stats: Dict[str, Any]
    z_var_indices: Dict[str, Dict[int, int]]
    optional_pose_var_indices: Dict[str, Dict[int, int]]
    mandatory_groups: List[Dict[str, Any]]
    group_id_by_instance: Dict[str, str]
    skip_power_coverage: bool
    enable_symmetry_breaking: bool
    master_representation: str = "pose_bool_v1"
    coordinate_binding: Dict[str, Any] = field(default_factory=dict)


class MasterPlacementModel:
    """CP-SAT feasibility model（可行性模型） for placement（摆放）."""

    def __init__(
        self,
        instances: Sequence[Mapping[str, Any]],
        facility_pools: Mapping[str, List[Dict[str, Any]]],
        rules: Mapping[str, Any],
        ghost_rect: Optional[Tuple[int, int]] = None,
        skip_power_coverage: bool = False,
        enable_symmetry_breaking: bool = True,
        generic_io_requirements: Optional[Mapping[str, Any]] = None,
        exact_mode: Optional[bool] = None,
        solve_mode: Optional[str] = None,
    ):
        self.solve_mode = _normalize_solve_mode(solve_mode, exact_mode)
        self.exact_mode = self.solve_mode == "certified_exact"

        self.source_instances: List[Dict[str, Any]] = [dict(item) for item in instances]
        self.instances: List[Dict[str, Any]] = [
            item for item in self.source_instances if bool(item.get("is_mandatory"))
        ]
        self.facility_pools = {tpl: list(pool) for tpl, pool in facility_pools.items()}
        self.rules = dict(rules)
        self.templates = dict(self.rules["facility_templates"])
        self.generic_io_requirements = _normalize_generic_io_requirements_payload(
            generic_io_requirements
        )
        self._exact_required_pose_optional_counts = {}
        self._certified_optional_lower_bounds = (
            infer_certified_optional_lower_bounds(
                self.rules,
                self.generic_io_requirements,
            )
            if self.exact_mode
            else {}
        )
        self.ghost_rect = ghost_rect
        self.skip_power_coverage = skip_power_coverage
        self.enable_symmetry_breaking = enable_symmetry_breaking

        grid = self.rules["globals"]["grid"]
        self.grid_w = int(grid["width"])
        self.grid_h = int(grid["height"])

        self.model = cp_model.CpModel()
        self._solver: Optional[cp_model.CpSolver] = None
        self._status: Optional[int] = None
        self._built = False

        self.z_vars: Dict[str, Dict[int, cp_model.IntVar]] = {}
        self.optional_pose_vars: Dict[str, Dict[int, cp_model.IntVar]] = {}
        self.u_vars: Dict[int, cp_model.IntVar] = {}
        self._mandatory_signature_count_vars: Dict[str, Dict[str, cp_model.IntVar]] = {}
        self._required_optional_signature_count_vars: Dict[str, Dict[str, cp_model.IntVar]] = {}
        self._power_pole_family_count_vars: Dict[str, cp_model.IntVar] = {}

        self._mandatory_groups: List[Dict[str, Any]] = []
        self._group_id_by_instance: Dict[str, str] = {}
        self._optional_cap_by_template = self._infer_optional_caps()
        self._powered_templates = {
            tpl for tpl, spec in self.templates.items() if bool(spec.get("needs_power", False))
        }

        self._covering_pose_indices: Dict[str, Dict[Tuple[int, int], List[int]]] = {}
        self._heuristic_port_fronts: Dict[str, Dict[int, Optional[List[Tuple[int, int]]]]] = {}
        self._power_coverers_by_template_pose: Dict[str, Dict[int, List[int]]] = {}
        self._pose_cells_by_template_pose: Dict[str, Dict[int, FrozenSet[Tuple[int, int]]]] = {}
        self._pose_anchor_by_template_pose: Dict[str, Dict[int, Tuple[int, int]]] = {}
        self._pose_local_cells_by_template_pose: Dict[str, Dict[int, LocalPoseShape]] = {}
        self._pose_local_fronts_by_template_pose: Dict[str, Dict[int, Optional[LocalPoseShape]]] = {}
        self._pose_local_power_coverage_by_template_pose: Dict[str, Dict[int, LocalPoseShape]] = {}
        self._pose_local_signature_by_template_pose: Dict[str, Dict[int, PoseLocalSignature]] = {}
        self._pose_local_shape_token_by_template_pose: Dict[str, Dict[int, int]] = {}
        self._local_shape_token_by_template_shape: Dict[str, Dict[LocalPoseShape, int]] = {}
        self._local_shape_by_template_token: Dict[str, Dict[int, LocalPoseShape]] = {}
        self._local_rectangle_variant_by_template_token: Dict[
            str,
            Dict[int, Optional[_LocalRectangleVariant]],
        ] = {}
        self._power_supported_pose_indices_by_template_pole: Dict[str, Dict[int, List[int]]] = {}
        self._power_pole_shell_pair_by_pose_idx: Dict[int, ShellPair] = {}
        self._power_pole_pose_indices_by_shell_pair: Dict[ShellPair, List[int]] = {}
        self._local_power_capacity_signature_by_template_pole: Dict[str, Dict[int, LocalCapacitySignature]] = {}
        self._compact_local_power_capacity_signature_by_template_pole: Dict[
            str,
            Dict[int, CompactLocalCapacitySignature],
        ] = {}
        self._power_pole_pose_indices_by_template_capacity_signature: Dict[
            str,
            Dict[LocalCapacitySignature, List[int]],
        ] = {}
        self._power_pole_pose_indices_by_template_compact_capacity_signature: Dict[
            str,
            Dict[CompactLocalCapacitySignature, List[int]],
        ] = {}
        self._legacy_local_power_capacity_signature_by_template_compact_signature: Dict[
            str,
            Dict[CompactLocalCapacitySignature, LocalCapacitySignature],
        ] = {}
        self._mandatory_signature_buckets: Dict[str, List[Dict[str, Any]]] = {}
        self._required_optional_signature_buckets: Dict[str, List[Dict[str, Any]]] = {}
        self._signature_bucket_payload_cache: Dict[Tuple[str, FrozenSet[int]], List[Dict[str, Any]]] = {}
        self._signature_domain_payload_cache: Dict[Tuple[str, FrozenSet[int]], Dict[str, Any]] = {}
        self._candidate_pose_indices_by_template: Dict[str, List[int]] = {}
        self._ghost_domains: List[Dict[str, Any]] = []
        self._cell_occupancy_terms: DefaultDict[Tuple[int, int], List[cp_model.IntVar]] = defaultdict(list)
        self._last_solution: Optional[Dict[str, Any]] = None
        self._local_power_capacity_bitset_max_iterations = 200_000
        self._local_power_capacity_rect_dp_max_states = 50_000_000
        self._local_power_capacity_rect_dp_max_line_subsets = 200_000
        self._local_power_capacity_rect_dp_v4_max_peak_line_subset_options = 160
        self._local_power_capacity_rect_dp_v4_max_compiled_line_subsets = 2_000

        self.build_stats: Dict[str, Any] = {
            "solve_mode": self.solve_mode,
            "optional_caps": dict(self._optional_cap_by_template),
            "generic_io_requirements": copy.deepcopy(self.generic_io_requirements),
            "exact_required_optionals": dict(self._exact_required_pose_optional_counts),
            "exact_optional_lower_bounds": dict(self._certified_optional_lower_bounds),
        }
        self._exact_precompute_profile: Dict[str, Any] = {
            "power_capacity_shell_pairs": 0,
            "power_capacity_shell_pair_evaluations": 0,
            "power_capacity_signature_classes": 0,
            "power_capacity_signature_class_evaluations": 0,
            "power_capacity_compact_signature_classes": 0,
            "power_capacity_compact_signature_evaluations": 0,
            "power_capacity_compact_signature_cache_hits": 0,
            "power_capacity_compact_signature_cache_misses": 0,
            "power_capacity_rect_dp_evaluations": 0,
            "power_capacity_rect_dp_cache_hits": 0,
            "power_capacity_rect_dp_cache_misses": 0,
            "power_capacity_rect_dp_state_merges": 0,
            "power_capacity_rect_dp_peak_line_states": 0,
            "power_capacity_rect_dp_peak_pos_states": 0,
            "power_capacity_rect_dp_compiled_signatures": 0,
            "power_capacity_rect_dp_compiled_start_options": 0,
            "power_capacity_rect_dp_deduped_start_options": 0,
            "power_capacity_rect_dp_compiled_line_subsets": 0,
            "power_capacity_rect_dp_peak_line_subset_options": 0,
            "power_capacity_rect_dp_v3_fallbacks": 0,
            "power_capacity_m6x4_mixed_cpsat_evaluations": 0,
            "power_capacity_m6x4_mixed_cpsat_cache_hits": 0,
            "power_capacity_m6x4_mixed_cpsat_selected_cases": 0,
            "power_capacity_m6x4_mixed_cpsat_v3_fallbacks": 0,
            "power_capacity_bitset_oracle_evaluations": 0,
            "power_capacity_bitset_fallbacks": 0,
            "power_capacity_cpsat_fallbacks": 0,
            "power_capacity_oracle": "rectangle_frontier_dp_v4",
            "power_capacity_raw_pole_evaluations": 0,
            "signature_bucket_cache_hits": 0,
            "signature_bucket_cache_misses": 0,
            "signature_bucket_distinct_keys": 0,
            "geometry_cache_templates": 0,
        }
        self.build_stats["exact_precompute_profile"] = dict(self._exact_precompute_profile)

        self._build_mandatory_groups()
        self._index_pools()
        self._build_signature_buckets()
        self._coordinate_delegate: Optional[CoordinateExactMasterDelegate] = (
            CoordinateExactMasterDelegate(self) if self.exact_mode else None
        )

    @classmethod
    def build_exact_core(
        cls,
        instances: Sequence[Mapping[str, Any]],
        facility_pools: Mapping[str, List[Dict[str, Any]]],
        rules: Mapping[str, Any],
        *,
        skip_power_coverage: bool = False,
        enable_symmetry_breaking: bool = True,
        generic_io_requirements: Optional[Mapping[str, Any]] = None,
    ) -> ExactMasterCore:
        model = cls(
            instances,
            facility_pools,
            rules,
            ghost_rect=None,
            skip_power_coverage=skip_power_coverage,
            enable_symmetry_breaking=enable_symmetry_breaking,
            generic_io_requirements=generic_io_requirements,
            solve_mode="certified_exact",
        )
        model.build()
        return ExactMasterCore(
            proto=_clone_model_proto(model.model.Proto()),
            source_instances=copy.deepcopy(model.source_instances),
            facility_pools=copy.deepcopy(model.facility_pools),
            rules=copy.deepcopy(model.rules),
            generic_io_requirements=copy.deepcopy(model.generic_io_requirements),
            build_stats=copy.deepcopy(model.build_stats),
            z_var_indices=model._current_z_var_indices(),
            optional_pose_var_indices=model._current_optional_pose_var_indices(),
            mandatory_groups=copy.deepcopy(model._mandatory_groups),
            group_id_by_instance=dict(model._group_id_by_instance),
            skip_power_coverage=bool(model.skip_power_coverage),
            enable_symmetry_breaking=bool(model.enable_symmetry_breaking),
            master_representation=str(model.build_stats.get("master_representation", "pose_bool_v1")),
            coordinate_binding=(
                model._coordinate_delegate.export_core_binding()
                if model._coordinate_delegate is not None and model.exact_mode
                else {}
            ),
        )

    @classmethod
    def from_exact_core(
        cls,
        core: ExactMasterCore,
        ghost_rect: Optional[Tuple[int, int]],
    ) -> "MasterPlacementModel":
        overlay_started = time.perf_counter()
        model = cls(
            core.source_instances,
            core.facility_pools,
            core.rules,
            ghost_rect=ghost_rect,
            skip_power_coverage=core.skip_power_coverage,
            enable_symmetry_breaking=core.enable_symmetry_breaking,
            generic_io_requirements=core.generic_io_requirements,
            solve_mode="certified_exact",
        )
        model.model = cp_model.CpModel(model_proto=_clone_model_proto(core.proto))
        model._solver = None
        model._status = None
        model._last_solution = None
        model._built = False
        model.build_stats = copy.deepcopy(core.build_stats)
        model._mandatory_groups = copy.deepcopy(core.mandatory_groups)
        model._group_id_by_instance = dict(core.group_id_by_instance)
        model.build_stats.setdefault("global_valid_inequalities", {}).setdefault(
            "ghost_aware_via_pole_feasibility",
            {},
        )["enabled"] = bool(ghost_rect)
        ghost_started = time.perf_counter()
        if str(core.master_representation).startswith("coordinate_exact_v"):
            if model._coordinate_delegate is None:
                raise RuntimeError("coordinate exact core requires a coordinate delegate")
            model._coordinate_delegate.model = model.model
            model._coordinate_delegate.bind_from_core(core.coordinate_binding)
            model._coordinate_delegate._add_ghost_constraints()
            model._coordinate_delegate._finalize_build_stats()
            model._mandatory_signature_count_vars = model._coordinate_delegate.mandatory_signature_count_vars
            model._required_optional_signature_count_vars = model._coordinate_delegate.required_optional_signature_count_vars
            model._power_pole_family_count_vars = model._coordinate_delegate.power_pole_family_count_vars
        else:
            model._bind_vars_from_exact_core(core)
            model._populate_cell_occupancy_terms()
            model._ghost_domains.clear()
            model.u_vars.clear()
            model._add_ghost_rect_constraints()
        model.build_stats["exact_core_reuse"] = {
            "used": True,
            "core_proto_variables": len(core.proto.variables),
            "core_proto_constraints": len(core.proto.constraints),
            "overlay_build_seconds": time.perf_counter() - overlay_started,
            "ghost_constraint_seconds": time.perf_counter() - ghost_started,
        }
        model._built = True
        return model

    def _infer_optional_caps(self) -> Dict[str, int]:
        counts: Dict[str, int] = defaultdict(int)
        for inst in self.source_instances:
            if bool(inst.get("is_mandatory")):
                continue
            tpl = str(inst.get("facility_type", ""))
            if tpl in POSE_LEVEL_OPTIONAL_TEMPLATES:
                counts[tpl] += 1
        return dict(counts)

    def _build_mandatory_groups(self) -> None:
        grouped: DefaultDict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
        for inst in self.instances:
            tpl = str(inst["facility_type"])
            operation_type = str(inst.get("operation_type", ""))
            grouped[(tpl, operation_type)].append(inst)

        self._mandatory_groups.clear()
        self._group_id_by_instance.clear()
        for group_index, ((tpl, operation_type), members) in enumerate(sorted(grouped.items())):
            members = sorted(members, key=lambda item: str(item["instance_id"]))
            group_id = f"group::{tpl}::{operation_type}::{group_index}"
            group = {
                "group_id": group_id,
                "facility_type": tpl,
                "operation_type": operation_type,
                "count": len(members),
                "instance_ids": [str(item["instance_id"]) for item in members],
            }
            self._mandatory_groups.append(group)
            for instance_id in group["instance_ids"]:
                self._group_id_by_instance[instance_id] = group_id

        self.build_stats["grouped_encoding"] = {
            "mandatory_instances": len(self.instances),
            "mandatory_groups": len(self._mandatory_groups),
        }

    def _pose_mode_token(self, pose: Mapping[str, Any]) -> ModeToken:
        params = dict(pose.get("pose_params", {}))
        return (str(params.get("orientation", "")), str(params.get("port_mode", "")))

    def _update_exact_precompute_profile(self, **updates: Any) -> None:
        self._exact_precompute_profile.update(updates)
        self.build_stats["exact_precompute_profile"] = dict(self._exact_precompute_profile)

    def _intern_local_shape_token(self, tpl: str, local_shape: LocalPoseShape) -> int:
        tpl = str(tpl)
        token_by_shape = self._local_shape_token_by_template_shape.setdefault(tpl, {})
        cached = token_by_shape.get(local_shape)
        if cached is not None:
            return int(cached)

        token = int(len(token_by_shape))
        token_by_shape[local_shape] = token
        self._local_shape_by_template_token.setdefault(tpl, {})[token] = local_shape
        return token

    def _rectangle_variant_for_local_shape(
        self,
        local_shape: LocalPoseShape,
    ) -> Optional[_LocalRectangleVariant]:
        if not local_shape:
            return None
        xs = sorted({int(cell_x) for cell_x, _ in local_shape})
        ys = sorted({int(cell_y) for _, cell_y in local_shape})
        if not xs or not ys:
            return None
        min_x = int(min(xs))
        max_x = int(max(xs))
        min_y = int(min(ys))
        max_y = int(max(ys))
        expected = {
            (int(cell_x), int(cell_y))
            for cell_x in range(min_x, max_x + 1)
            for cell_y in range(min_y, max_y + 1)
        }
        if expected != set(local_shape):
            return None
        return _LocalRectangleVariant(
            min_x=min_x,
            min_y=min_y,
            max_x=max_x,
            max_y=max_y,
            width=int(max_x - min_x + 1),
            height=int(max_y - min_y + 1),
        )

    def _ensure_local_rectangle_variants(
        self,
        tpl: str,
    ) -> Dict[int, Optional[_LocalRectangleVariant]]:
        tpl = str(tpl)
        cached = self._local_rectangle_variant_by_template_token.get(tpl)
        if cached is not None:
            return cached
        variants: Dict[int, Optional[_LocalRectangleVariant]] = {}
        for token, local_shape in sorted(self._local_shape_by_template_token.get(tpl, {}).items()):
            variants[int(token)] = self._rectangle_variant_for_local_shape(local_shape)
        self._local_rectangle_variant_by_template_token[tpl] = variants
        return variants

    def _clone_signature_bucket_payload(
        self,
        payload: Sequence[Mapping[str, Any]],
    ) -> List[Dict[str, Any]]:
        return [
            {
                "bucket_id": str(bucket["bucket_id"]),
                "signature": bucket["signature"],
                "pose_indices": list(bucket.get("pose_indices", [])),
            }
            for bucket in payload
        ]

    def _power_pole_shell_pair(self, pose_idx: int) -> Optional[ShellPair]:
        return self._power_pole_shell_pair_by_pose_idx.get(int(pose_idx))

    def _index_pools(self) -> None:
        """Build indices（构建索引） for occupancy, power and exploratory port heuristics."""

        self._covering_pose_indices = {}
        self._heuristic_port_fronts = {}
        self._power_coverers_by_template_pose = {}
        self._pose_cells_by_template_pose = {}
        self._pose_anchor_by_template_pose = {}
        self._pose_local_cells_by_template_pose = {}
        self._pose_local_fronts_by_template_pose = {}
        self._pose_local_power_coverage_by_template_pose = {}
        self._pose_local_signature_by_template_pose = {}
        self._power_supported_pose_indices_by_template_pole = {}
        self._power_pole_shell_pair_by_pose_idx = {}
        self._power_pole_pose_indices_by_shell_pair = {}
        self._local_power_capacity_signature_by_template_pole = {}
        self._power_pole_pose_indices_by_template_capacity_signature = {}
        self._candidate_pose_indices_by_template = {}

        cell_to_poles: DefaultDict[Tuple[int, int], Set[int]] = defaultdict(set)
        power_pole_cells: Dict[int, FrozenSet[Tuple[int, int]]] = {}
        power_pole_anchors: Dict[int, Tuple[int, int]] = {}
        for pole_idx, pose in enumerate(self.facility_pools.get("power_pole", [])):
            anchor = dict(pose.get("anchor", {}))
            anchor_xy = (int(anchor.get("x", 0)), int(anchor.get("y", 0)))
            pole_cells = frozenset((int(cell[0]), int(cell[1])) for cell in pose.get("occupied_cells", []))
            local_cells = tuple(
                sorted((cell_x - anchor_xy[0], cell_y - anchor_xy[1]) for cell_x, cell_y in pole_cells)
            )
            local_coverage = tuple(
                sorted(
                    (
                        int(cell[0]) - anchor_xy[0],
                        int(cell[1]) - anchor_xy[1],
                    )
                    for cell in pose.get("power_coverage_cells", []) or []
                )
            )
            power_pole_cells[pole_idx] = pole_cells
            power_pole_anchors[pole_idx] = anchor_xy
            self._pose_anchor_by_template_pose.setdefault("power_pole", {})[int(pole_idx)] = anchor_xy
            self._pose_cells_by_template_pose.setdefault("power_pole", {})[int(pole_idx)] = pole_cells
            self._pose_local_cells_by_template_pose.setdefault("power_pole", {})[int(pole_idx)] = local_cells
            self._pose_local_fronts_by_template_pose.setdefault("power_pole", {})[int(pole_idx)] = tuple()
            self._pose_local_power_coverage_by_template_pose.setdefault("power_pole", {})[int(pole_idx)] = local_coverage
            self._pose_local_shape_token_by_template_pose.setdefault("power_pole", {})[
                int(pole_idx)
            ] = self._intern_local_shape_token("power_pole", local_cells)
            self._pose_local_signature_by_template_pose.setdefault("power_pole", {})[int(pole_idx)] = (
                local_cells,
                tuple(),
                local_coverage,
                0,
            )
            for cell in pose.get("power_coverage_cells", []) or []:
                cell_to_poles[(int(cell[0]), int(cell[1]))].add(pole_idx)

        if power_pole_anchors:
            x_values = [coords[0] for coords in power_pole_anchors.values()]
            y_values = [coords[1] for coords in power_pole_anchors.values()]
            x_min, x_max = min(x_values), max(x_values)
            y_min, y_max = min(y_values), max(y_values)
            for pole_idx, (anchor_x, anchor_y) in power_pole_anchors.items():
                dx = min(int(anchor_x - x_min), int(x_max - anchor_x))
                dy = min(int(anchor_y - y_min), int(y_max - anchor_y))
                shell_pair = tuple(sorted((int(dx), int(dy))))
                self._power_pole_shell_pair_by_pose_idx[int(pole_idx)] = shell_pair
                self._power_pole_pose_indices_by_shell_pair.setdefault(shell_pair, []).append(int(pole_idx))
            for shell_pair, pose_indices in list(self._power_pole_pose_indices_by_shell_pair.items()):
                self._power_pole_pose_indices_by_shell_pair[shell_pair] = sorted(
                    pose_indices,
                    key=lambda idx: self._pose_sort_key("power_pole", int(idx)),
                )

        for tpl, pool in self.facility_pools.items():
            cover_index: DefaultDict[Tuple[int, int], List[int]] = defaultdict(list)
            front_index: Dict[int, Optional[List[Tuple[int, int]]]] = {}
            power_index: Dict[int, List[int]] = {}
            pose_cells_index: Dict[int, FrozenSet[Tuple[int, int]]] = {}
            supported_by_pole: DefaultDict[int, List[int]] = defaultdict(list)

            for pose_idx, pose in enumerate(pool):
                anchor = dict(pose.get("anchor", {}))
                anchor_xy = (int(anchor.get("x", 0)), int(anchor.get("y", 0)))
                pose_cells = frozenset((int(cell[0]), int(cell[1])) for cell in pose.get("occupied_cells", []))
                local_cells = tuple(
                    sorted((cell_x - anchor_xy[0], cell_y - anchor_xy[1]) for cell_x, cell_y in pose_cells)
                )
                pose_cells_index[pose_idx] = pose_cells
                self._pose_anchor_by_template_pose.setdefault(str(tpl), {})[int(pose_idx)] = anchor_xy
                self._pose_local_cells_by_template_pose.setdefault(str(tpl), {})[int(pose_idx)] = local_cells
                self._pose_local_shape_token_by_template_pose.setdefault(str(tpl), {})[
                    int(pose_idx)
                ] = self._intern_local_shape_token(str(tpl), local_cells)
                for cell in pose_cells:
                    cover_index[cell].append(pose_idx)

                unique_fronts: List[Tuple[int, int]] = []
                seen_fronts: Set[Tuple[int, int]] = set()
                invalid_front = False
                for port in list(pose.get("input_port_cells", [])) + list(pose.get("output_port_cells", [])):
                    px = int(port["x"])
                    py = int(port["y"])
                    direction = str(port["dir"])
                    if direction not in DIR_DELTA:
                        continue
                    dx, dy = DIR_DELTA[direction]
                    fx, fy = px + dx, py + dy
                    if not (0 <= fx < self.grid_w and 0 <= fy < self.grid_h):
                        invalid_front = True
                        break
                    if (fx, fy) not in seen_fronts:
                        seen_fronts.add((fx, fy))
                        unique_fronts.append((fx, fy))
                front_index[pose_idx] = None if invalid_front else unique_fronts
                local_fronts = tuple(
                    sorted(
                        (cell_x - anchor_xy[0], cell_y - anchor_xy[1])
                        for cell_x, cell_y in (unique_fronts if not invalid_front else [])
                    )
                )
                local_coverage = tuple(
                    sorted(
                        (
                            int(cell[0]) - anchor_xy[0],
                            int(cell[1]) - anchor_xy[1],
                        )
                        for cell in pose.get("power_coverage_cells", []) or []
                    )
                )
                self._pose_local_fronts_by_template_pose.setdefault(str(tpl), {})[int(pose_idx)] = local_fronts
                self._pose_local_power_coverage_by_template_pose.setdefault(str(tpl), {})[int(pose_idx)] = local_coverage
                self._pose_local_signature_by_template_pose.setdefault(str(tpl), {})[int(pose_idx)] = (
                    local_cells,
                    local_fronts,
                    local_coverage,
                    1 if invalid_front else 0,
                )

                if tpl in self._powered_templates and tpl != "power_pole":
                    coverers: Set[int] = set()
                    for cell in pose_cells:
                        coverers.update(cell_to_poles.get(cell, set()))
                    filtered_coverers = sorted(
                        pole_idx
                        for pole_idx in coverers
                        if pose_cells.isdisjoint(power_pole_cells.get(pole_idx, frozenset()))
                    )
                    power_index[pose_idx] = filtered_coverers
                    for pole_idx in filtered_coverers:
                        supported_by_pole[pole_idx].append(pose_idx)

            self._covering_pose_indices[tpl] = dict(cover_index)
            self._heuristic_port_fronts[tpl] = front_index
            self._power_coverers_by_template_pose[tpl] = power_index
            self._pose_cells_by_template_pose[tpl] = pose_cells_index
            self._power_supported_pose_indices_by_template_pole[tpl] = {
                pole_idx: sorted(indices)
                for pole_idx, indices in supported_by_pole.items()
            }
        self._update_exact_precompute_profile(
            power_capacity_shell_pairs=int(len(self._power_pole_pose_indices_by_shell_pair)),
            geometry_cache_templates=int(len(self._pose_local_signature_by_template_pose)),
        )

    def _pose_local_signature(self, tpl: str, pose_idx: int) -> PoseLocalSignature:
        return self._pose_local_signature_by_template_pose.get(str(tpl), {}).get(
            int(pose_idx),
            (tuple(), tuple(), tuple(), 0),
        )

    def _build_signature_bucket_payload(
        self,
        tpl: str,
        pose_indices: Iterable[int],
    ) -> List[Dict[str, Any]]:
        cache_key = (
            str(tpl),
            frozenset(int(pose_idx) for pose_idx in pose_indices),
        )
        cached = self._signature_bucket_payload_cache.get(cache_key)
        if cached is not None:
            self._update_exact_precompute_profile(
                signature_bucket_cache_hits=int(self._exact_precompute_profile["signature_bucket_cache_hits"]) + 1,
                signature_bucket_distinct_keys=int(len(self._signature_bucket_payload_cache)),
            )
            return self._clone_signature_bucket_payload(cached)

        self._update_exact_precompute_profile(
            signature_bucket_cache_misses=int(self._exact_precompute_profile["signature_bucket_cache_misses"]) + 1,
        )
        buckets_by_signature: DefaultDict[PoseLocalSignature, List[int]] = defaultdict(list)
        for pose_idx in sorted(cache_key[1]):
            buckets_by_signature[self._pose_local_signature(tpl, int(pose_idx))].append(int(pose_idx))

        ordered_buckets: List[Dict[str, Any]] = []
        for bucket_index, signature in enumerate(sorted(buckets_by_signature)):
            ordered_pose_indices = sorted(
                buckets_by_signature[signature],
                key=lambda idx: self._pose_sort_key(tpl, int(idx)),
            )
            ordered_buckets.append(
                {
                    "bucket_id": f"sig_{bucket_index:03d}",
                    "signature": signature,
                    "pose_indices": ordered_pose_indices,
                }
            )
        self._signature_bucket_payload_cache[cache_key] = self._clone_signature_bucket_payload(
            ordered_buckets
        )
        self._update_exact_precompute_profile(
            signature_bucket_distinct_keys=int(len(self._signature_bucket_payload_cache)),
        )
        return self._clone_signature_bucket_payload(ordered_buckets)

    def _bucket_stats_payload(self, buckets: Mapping[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        for bucket_owner, bucket_defs in sorted(buckets.items()):
            payload[str(bucket_owner)] = {
                "bucket_count": len(bucket_defs),
                "pose_count": sum(len(bucket["pose_indices"]) for bucket in bucket_defs),
                "bucket_sizes": [len(bucket["pose_indices"]) for bucket in bucket_defs],
            }
        return payload

    def _build_signature_buckets(self) -> None:
        self._mandatory_signature_buckets = {}
        for group in self._mandatory_groups:
            group_id = str(group["group_id"])
            tpl = str(group["facility_type"])
            self._mandatory_signature_buckets[group_id] = self._build_signature_bucket_payload(
                tpl,
                range(len(self.facility_pools.get(tpl, []))),
            )

        self._required_optional_signature_buckets = {}
        for tpl, required_count in sorted(self._exact_required_pose_optional_counts.items()):
            if int(required_count) <= 0:
                continue
            self._required_optional_signature_buckets[str(tpl)] = self._build_signature_bucket_payload(
                str(tpl),
                range(len(self.facility_pools.get(str(tpl), []))),
            )

        self.build_stats["signature_buckets"] = {
            "mandatory_groups": self._bucket_stats_payload(self._mandatory_signature_buckets),
            "required_optionals": self._bucket_stats_payload(self._required_optional_signature_buckets),
        }

    def _current_z_var_indices(self) -> Dict[str, Dict[int, int]]:
        return {
            group_id: {
                int(pose_idx): int(var.Index())
                for pose_idx, var in vars_by_pose.items()
            }
            for group_id, vars_by_pose in self.z_vars.items()
        }

    def _current_optional_pose_var_indices(self) -> Dict[str, Dict[int, int]]:
        return {
            tpl: {
                int(pose_idx): int(var.Index())
                for pose_idx, var in vars_by_pose.items()
            }
            for tpl, vars_by_pose in self.optional_pose_vars.items()
        }

    def _bind_vars_from_exact_core(self, core: ExactMasterCore) -> None:
        self.z_vars = {}
        for group_id, indices_by_pose in core.z_var_indices.items():
            self.z_vars[group_id] = {
                int(pose_idx): self.model.GetBoolVarFromProtoIndex(int(proto_idx))
                for pose_idx, proto_idx in indices_by_pose.items()
            }

        self.optional_pose_vars = {}
        for tpl, indices_by_pose in core.optional_pose_var_indices.items():
            self.optional_pose_vars[tpl] = {
                int(pose_idx): self.model.GetBoolVarFromProtoIndex(int(proto_idx))
                for pose_idx, proto_idx in indices_by_pose.items()
            }

    def _populate_cell_occupancy_terms(self) -> None:
        self._cell_occupancy_terms = defaultdict(list)

        for group in self._mandatory_groups:
            group_id = group["group_id"]
            tpl = group["facility_type"]
            cover_index = self._covering_pose_indices.get(tpl, {})
            for cell, pose_indices in cover_index.items():
                self._cell_occupancy_terms[cell].extend(
                    self.z_vars[group_id][pose_idx] for pose_idx in pose_indices
                )

        for tpl, vars_by_pose in self.optional_pose_vars.items():
            cover_index = self._covering_pose_indices.get(tpl, {})
            for cell, pose_indices in cover_index.items():
                self._cell_occupancy_terms[cell].extend(
                    vars_by_pose[pose_idx] for pose_idx in pose_indices
                )

    def build(self) -> None:
        if self._built:
            return
        if self.exact_mode and self._coordinate_delegate is not None:
            self._coordinate_delegate.model = self.model
            self._coordinate_delegate.build()
            self._mandatory_signature_count_vars = self._coordinate_delegate.mandatory_signature_count_vars
            self._required_optional_signature_count_vars = self._coordinate_delegate.required_optional_signature_count_vars
            self._power_pole_family_count_vars = self._coordinate_delegate.power_pole_family_count_vars
            self._built = True
            return
        self._create_variables()
        self._add_assignment_constraints()
        self._add_signature_count_constraints()
        self._add_set_packing_constraints()
        self._add_ghost_rect_constraints()
        self._add_port_clearance_constraints()
        if not self.skip_power_coverage:
            self._add_power_coverage_constraints()
        if self.enable_symmetry_breaking:
            self._add_symmetry_breaking_constraints()
        self._add_global_valid_inequalities()
        self._add_search_guidance()
        self._built = True

    def _create_variables(self) -> None:
        for group in self._mandatory_groups:
            group_id = group["group_id"]
            tpl = group["facility_type"]
            pool = self.facility_pools[tpl]
            self.z_vars[group_id] = {
                pose_idx: self.model.NewBoolVar(f"z__{group_id}__{pose_idx}")
                for pose_idx in range(len(pool))
            }

        for tpl in sorted(POSE_LEVEL_OPTIONAL_TEMPLATES):
            pool = self.facility_pools.get(tpl, [])
            self.optional_pose_vars[tpl] = {
                pose_idx: self.model.NewBoolVar(f"opt__{tpl}__{pose_idx}")
                for pose_idx in range(len(pool))
            }

        self._mandatory_signature_count_vars = {}
        for group in self._mandatory_groups:
            group_id = str(group["group_id"])
            required_count = int(group["count"])
            self._mandatory_signature_count_vars[group_id] = {}
            for bucket in self._mandatory_signature_buckets.get(group_id, []):
                bucket_id = str(bucket["bucket_id"])
                upper_bound = min(required_count, len(bucket["pose_indices"]))
                self._mandatory_signature_count_vars[group_id][bucket_id] = self.model.NewIntVar(
                    0,
                    int(upper_bound),
                    f"sig_count__{group_id}__{bucket_id}",
                )

        self._required_optional_signature_count_vars = {}
        for tpl, bucket_defs in sorted(self._required_optional_signature_buckets.items()):
            required_count = int(self._exact_required_pose_optional_counts.get(str(tpl), 0))
            self._required_optional_signature_count_vars[str(tpl)] = {}
            for bucket in bucket_defs:
                bucket_id = str(bucket["bucket_id"])
                upper_bound = min(required_count, len(bucket["pose_indices"]))
                self._required_optional_signature_count_vars[str(tpl)][bucket_id] = self.model.NewIntVar(
                    0,
                    int(upper_bound),
                    f"req_opt_sig_count__{tpl}__{bucket_id}",
                )

    def _add_assignment_constraints(self) -> None:
        for group in self._mandatory_groups:
            group_id = group["group_id"]
            self.model.Add(sum(self.z_vars[group_id].values()) == int(group["count"]))

        for tpl, vars_by_pose in self.optional_pose_vars.items():
            if self.solve_mode == "exploratory":
                cap = int(self._optional_cap_by_template.get(tpl, 0))
                self.model.Add(sum(vars_by_pose.values()) <= cap)
            else:
                # certified_exact（严格认证精确）不加经验上限。
                pass

    def _add_signature_count_constraints(self) -> None:
        for group in self._mandatory_groups:
            group_id = str(group["group_id"])
            bucket_vars = self._mandatory_signature_count_vars.get(group_id, {})
            for bucket in self._mandatory_signature_buckets.get(group_id, []):
                bucket_id = str(bucket["bucket_id"])
                pose_terms = [
                    self.z_vars[group_id][int(pose_idx)]
                    for pose_idx in bucket["pose_indices"]
                    if int(pose_idx) in self.z_vars.get(group_id, {})
                ]
                self.model.Add(bucket_vars[bucket_id] == sum(pose_terms))
            if bucket_vars:
                self.model.Add(sum(bucket_vars.values()) == int(group["count"]))

        for tpl, bucket_defs in sorted(self._required_optional_signature_buckets.items()):
            bucket_vars = self._required_optional_signature_count_vars.get(str(tpl), {})
            for bucket in bucket_defs:
                bucket_id = str(bucket["bucket_id"])
                pose_terms = [
                    self.optional_pose_vars[str(tpl)][int(pose_idx)]
                    for pose_idx in bucket["pose_indices"]
                    if int(pose_idx) in self.optional_pose_vars.get(str(tpl), {})
                ]
                self.model.Add(bucket_vars[bucket_id] == sum(pose_terms))
            if bucket_vars:
                self.model.Add(
                    sum(bucket_vars.values())
                    == int(self._exact_required_pose_optional_counts.get(str(tpl), 0))
                )

    def _add_set_packing_constraints(self) -> None:
        self._populate_cell_occupancy_terms()

        for terms in self._cell_occupancy_terms.values():
            if terms:
                self.model.Add(sum(terms) <= 1)

    def _add_ghost_rect_constraints(self) -> None:
        if not self.ghost_rect:
            self.build_stats["ghost_rect"] = {"enabled": False}
            return

        ghost_w, ghost_h = self.ghost_rect
        rect_cover_terms: DefaultDict[Tuple[int, int], List[cp_model.IntVar]] = defaultdict(list)
        self._ghost_domains.clear()
        self.u_vars.clear()

        for anchor_x in range(self.grid_w - ghost_w + 1):
            for anchor_y in range(self.grid_h - ghost_h + 1):
                rect_idx = len(self._ghost_domains)
                cells = [
                    (anchor_x + dx, anchor_y + dy)
                    for dx in range(ghost_w)
                    for dy in range(ghost_h)
                ]
                var = self.model.NewBoolVar(f"ghost__{anchor_x}_{anchor_y}_{ghost_w}_{ghost_h}")
                self.u_vars[rect_idx] = var
                self._ghost_domains.append(
                    {
                        "anchor": {"x": anchor_x, "y": anchor_y},
                        "cells": cells,
                    }
                )
                for cell in cells:
                    rect_cover_terms[cell].append(var)

        if not self.u_vars:
            self.model.Add(0 == 1)
            self.build_stats["ghost_rect"] = {
                "enabled": True,
                "placements": 0,
                "reason": "rectangle larger than grid",
            }
            return

        self.model.AddExactlyOne(list(self.u_vars.values()))
        for cell, rect_terms in rect_cover_terms.items():
            occupancy_terms = self._cell_occupancy_terms.get(cell, [])
            self.model.Add(sum(occupancy_terms) + sum(rect_terms) <= 1)

        self.build_stats["ghost_rect"] = {
            "enabled": True,
            "placements": len(self._ghost_domains),
            "size": {"w": ghost_w, "h": ghost_h},
        }

    def _add_port_clearance_constraints(self) -> None:
        """Exploratory heuristic（探索启发式） only.

        严格精确路径不允许把“所有端口前方都必须畅通”这种近似假设
        当成正式剪枝，因此 exact 模式跳过。
        """

        if self.exact_mode:
            self.build_stats["port_clearance"] = {"skipped_in_exact_mode": True}
            return

        constraints = 0
        for group in self._mandatory_groups:
            group_id = group["group_id"]
            tpl = group["facility_type"]
            for pose_idx, z_var in self.z_vars[group_id].items():
                fronts = self._heuristic_port_fronts.get(tpl, {}).get(pose_idx)
                if fronts is None:
                    self.model.Add(z_var == 0)
                    constraints += 1
                    continue
                for cell in fronts:
                    occupancy_terms = [term for term in self._cell_occupancy_terms.get(cell, []) if term is not z_var]
                    if occupancy_terms:
                        self.model.Add(sum(occupancy_terms) + z_var <= 1)
                        constraints += 1

        for tpl, vars_by_pose in self.optional_pose_vars.items():
            for pose_idx, z_var in vars_by_pose.items():
                fronts = self._heuristic_port_fronts.get(tpl, {}).get(pose_idx)
                if fronts is None:
                    self.model.Add(z_var == 0)
                    constraints += 1
                    continue
                for cell in fronts:
                    occupancy_terms = [term for term in self._cell_occupancy_terms.get(cell, []) if term is not z_var]
                    if occupancy_terms:
                        self.model.Add(sum(occupancy_terms) + z_var <= 1)
                        constraints += 1

        self.build_stats["port_clearance"] = {
            "heuristic_constraints": constraints,
            "mode": "exploratory",
        }

    def _add_power_coverage_constraints(self) -> None:
        pole_vars = self.optional_pose_vars.get("power_pole", {})
        constraints = 0

        for group in self._mandatory_groups:
            tpl = group["facility_type"]
            if tpl not in self._powered_templates or tpl == "power_pole":
                continue
            group_id = group["group_id"]
            pose_coverers = self._power_coverers_by_template_pose.get(tpl, {})
            for pose_idx, z_var in self.z_vars[group_id].items():
                coverers = pose_coverers.get(pose_idx, [])
                if not coverers:
                    self.model.Add(z_var == 0)
                    constraints += 1
                    continue
                self.model.Add(sum(pole_vars[idx] for idx in coverers) >= z_var)
                constraints += 1

        for tpl, vars_by_pose in self.optional_pose_vars.items():
            if tpl not in self._powered_templates or tpl == "power_pole":
                continue
            pose_coverers = self._power_coverers_by_template_pose.get(tpl, {})
            for pose_idx, z_var in vars_by_pose.items():
                coverers = pose_coverers.get(pose_idx, [])
                if not coverers:
                    self.model.Add(z_var == 0)
                    constraints += 1
                    continue
                self.model.Add(sum(pole_vars[idx] for idx in coverers) >= z_var)
                constraints += 1

        self.build_stats["power_coverage"] = {
            "constraints": constraints,
            "pole_cap": None if self.exact_mode else self._optional_cap_by_template.get("power_pole", 0),
        }

    def _add_symmetry_breaking_constraints(self) -> None:
        # Grouped encoding（分组编码） already removes clone permutations（克隆置换）.
        self.build_stats["symmetry_breaking"] = {"grouped_encoding_only": True}

    def _ordered_groups_for_exact_search(self) -> List[Dict[str, Any]]:
        if not self.exact_mode:
            return list(self._mandatory_groups)

        candidate_counts: Dict[str, int] = {}
        for group in self._mandatory_groups:
            group_id = str(group["group_id"])
            candidate_counts[group_id] = len(self._candidate_pose_indices_for_group(group))

        return sorted(
            self._mandatory_groups,
            key=lambda group: (
                int(candidate_counts.get(str(group["group_id"]), 0)),
                str(group["facility_type"]),
                str(group["group_id"]),
            ),
        )

    def _ordered_optional_pose_indices(self, tpl: str) -> List[int]:
        return sorted(
            self.optional_pose_vars.get(tpl, {}),
            key=lambda pose_idx: self._pose_sort_key(tpl, int(pose_idx)),
        )

    def _ordered_ghost_anchor_indices(self) -> List[int]:
        return sorted(
            self.u_vars,
            key=lambda rect_idx: (
                int(self._ghost_domains[int(rect_idx)]["anchor"]["x"]),
                int(self._ghost_domains[int(rect_idx)]["anchor"]["y"]),
                int(rect_idx),
            ),
        )

    def _add_search_guidance(self) -> None:
        if not self.exact_mode:
            self.build_stats["search_guidance"] = {
                "applied": False,
                "profile": "default_automatic",
                "reason": "exact-guided branching only runs in certified_exact mode",
            }
            return

        mandatory_literals = 0
        ghost_literals = 0
        optional_literals: Dict[str, int] = {}
        required_optional_literals: Dict[str, int] = {}
        residual_optional_literals: Dict[str, int] = {}
        mandatory_signature_counts: Dict[str, int] = {}
        required_optional_signature_counts: Dict[str, int] = {}
        mandatory_signature_count_literals = 0
        required_optional_signature_count_literals = 0
        required_optional_templates = [
            tpl
            for tpl in sorted(POSE_LEVEL_OPTIONAL_TEMPLATES)
            if int(self._exact_required_pose_optional_counts.get(tpl, 0)) > 0
        ]
        required_optional_template_set = set(required_optional_templates)
        ordered_groups = self._ordered_groups_for_exact_search()
        for group in ordered_groups:
            group_id = str(group["group_id"])
            ordered_signature_count_vars = [
                self._mandatory_signature_count_vars[group_id][str(bucket["bucket_id"])]
                for bucket in self._mandatory_signature_buckets.get(group_id, [])
                if str(bucket["bucket_id"]) in self._mandatory_signature_count_vars.get(group_id, {})
            ]
            if ordered_signature_count_vars:
                self.model.AddDecisionStrategy(
                    ordered_signature_count_vars,
                    cp_model.CHOOSE_FIRST,
                    cp_model.SELECT_MAX_VALUE,
                )
            mandatory_signature_counts[group_id] = len(ordered_signature_count_vars)
            mandatory_signature_count_literals += len(ordered_signature_count_vars)
            candidate_pose_set = {
                int(pose_idx) for pose_idx in self._candidate_pose_indices_for_group(group)
            }
            ordered_pose_indices: List[int] = []
            for bucket in self._mandatory_signature_buckets.get(group_id, []):
                ordered_pose_indices.extend(
                    int(pose_idx)
                    for pose_idx in bucket["pose_indices"]
                    if int(pose_idx) in candidate_pose_set
                )
            ordered_vars = [
                self.z_vars[group_id][pose_idx]
                for pose_idx in ordered_pose_indices
                if pose_idx in self.z_vars.get(group_id, {})
            ]
            if not ordered_vars:
                continue
            self.model.AddDecisionStrategy(
                ordered_vars,
                cp_model.CHOOSE_FIRST,
                cp_model.SELECT_MAX_VALUE,
            )
            mandatory_literals += len(ordered_vars)

        ordered_ghost_indices = self._ordered_ghost_anchor_indices()
        ghost_vars = [
            self.u_vars[rect_idx]
            for rect_idx in ordered_ghost_indices
            if rect_idx in self.u_vars
        ]
        if ghost_vars:
            self.model.AddDecisionStrategy(
                ghost_vars,
                cp_model.CHOOSE_FIRST,
                cp_model.SELECT_MAX_VALUE,
            )
            ghost_literals = len(ghost_vars)

        for tpl in required_optional_templates:
            ordered_signature_count_vars = [
                self._required_optional_signature_count_vars[tpl][str(bucket["bucket_id"])]
                for bucket in self._required_optional_signature_buckets.get(tpl, [])
                if str(bucket["bucket_id"])
                in self._required_optional_signature_count_vars.get(tpl, {})
            ]
            if ordered_signature_count_vars:
                self.model.AddDecisionStrategy(
                    ordered_signature_count_vars,
                    cp_model.CHOOSE_FIRST,
                    cp_model.SELECT_MAX_VALUE,
                )
            required_optional_signature_counts[tpl] = len(ordered_signature_count_vars)
            required_optional_signature_count_literals += len(ordered_signature_count_vars)
            ordered_pose_indices: List[int] = []
            for bucket in self._required_optional_signature_buckets.get(tpl, []):
                ordered_pose_indices.extend(int(pose_idx) for pose_idx in bucket["pose_indices"])
            ordered_vars = [
                self.optional_pose_vars[tpl][pose_idx]
                for pose_idx in ordered_pose_indices
                if pose_idx in self.optional_pose_vars.get(tpl, {})
            ]
            if not ordered_vars:
                required_optional_literals[tpl] = 0
                optional_literals[tpl] = 0
                continue
            self.model.AddDecisionStrategy(
                ordered_vars,
                cp_model.CHOOSE_FIRST,
                cp_model.SELECT_MAX_VALUE,
            )
            required_optional_literals[tpl] = len(ordered_vars)
            optional_literals[tpl] = len(ordered_vars)

        for tpl in sorted(POSE_LEVEL_OPTIONAL_TEMPLATES):
            if tpl in required_optional_template_set:
                continue
            ordered_pose_indices = self._ordered_optional_pose_indices(tpl)
            ordered_vars = [
                self.optional_pose_vars[tpl][pose_idx]
                for pose_idx in ordered_pose_indices
                if pose_idx in self.optional_pose_vars.get(tpl, {})
            ]
            if not ordered_vars:
                residual_optional_literals[tpl] = 0
                optional_literals[tpl] = 0
                continue
            self.model.AddDecisionStrategy(
                ordered_vars,
                cp_model.CHOOSE_FIRST,
                cp_model.SELECT_MIN_VALUE,
            )
            residual_optional_literals[tpl] = len(ordered_vars)
            optional_literals[tpl] = len(ordered_vars)

        self.build_stats["search_guidance"] = {
            "applied": True,
            "profile": "exact_signature_guided_branching_v2",
            "search_branching": "FIXED_SEARCH",
            "mandatory_group_order": [str(group["group_id"]) for group in ordered_groups],
            "mandatory_signature_counts": {
                str(k): int(v) for k, v in mandatory_signature_counts.items()
            },
            "mandatory_signature_count_literals": int(mandatory_signature_count_literals),
            "mandatory_literals": int(mandatory_literals),
            "ghost_literals": int(ghost_literals),
            "required_optional_templates": [str(tpl) for tpl in required_optional_templates],
            "required_optional_signature_counts": {
                str(k): int(v) for k, v in required_optional_signature_counts.items()
            },
            "required_optional_signature_count_literals": int(
                required_optional_signature_count_literals
            ),
            "required_optional_literals": {
                str(k): int(v) for k, v in required_optional_literals.items()
            },
            "required_optional_default": "SELECT_MAX_VALUE",
            "residual_optional_literals": {
                str(k): int(v) for k, v in residual_optional_literals.items()
            },
            "residual_optional_default": "SELECT_MIN_VALUE",
            "optional_literals": {str(k): int(v) for k, v in optional_literals.items()},
            "optional_default": "SELECT_MIN_VALUE",
        }

    def _add_global_valid_inequalities(self) -> None:
        stats: Dict[str, Any] = {
            "exact_safe_only": True,
            "applied": [],
            "optional_cardinality_bounds": {},
            "fixed_required_optional_demands": {},
            "lower_bound_optional_powered_demands": {},
            "powered_template_demands": {},
            "capacity_cache": {
                "scope": "process_memory",
                "signature_hits": 0,
                "signature_misses": 0,
                "signature_count": len(_LOCAL_POWER_CAPACITY_COMPACT_CACHE),
                "pole_template_evaluations": 0,
                "signature_class_count": 0,
                "signature_class_evaluations": 0,
                "compact_signature_class_count": 0,
                "compact_signature_class_evaluations": 0,
                "compact_signature_hits": 0,
                "compact_signature_misses": 0,
                "rect_dp_evaluations": 0,
                "rect_dp_cache_hits": 0,
                "rect_dp_cache_misses": 0,
                "rect_dp_state_merges": 0,
                "rect_dp_peak_line_states": 0,
                "rect_dp_peak_pos_states": 0,
                "rect_dp_compiled_signatures": 0,
                "rect_dp_compiled_start_options": 0,
                "rect_dp_deduped_start_options": 0,
                "rect_dp_compiled_line_subsets": 0,
                "rect_dp_peak_line_subset_options": 0,
                "rect_dp_v3_fallbacks": 0,
                "bitset_oracle_evaluations": 0,
                "bitset_fallbacks": 0,
                "cpsat_fallbacks": 0,
                "oracle": "rectangle_frontier_dp_v4",
                "raw_pole_evaluations": 0,
                "coefficient_source": "exact_rect_dp_cache_v7",
                "shell_pair_count": 0,
            },
            "capacity_coeff_stats": {},
            "power_capacity_families": {
                "applied": False,
                "family_count": 0,
                "raw_pole_count": 0,
                "coefficient_source": "exact_rect_dp_cache_v7",
                "shell_pair_count": 0,
                "compact_signature_class_count": 0,
                "families": [],
            },
            "aggregated_power_capacity_terms": {
                "applied": False,
                "raw_nonzero_terms": 0,
                "aggregated_nonzero_terms": 0,
            },
            "ghost_aware_via_pole_feasibility": {
                "enabled": bool(self.ghost_rect),
                "explicit_u_conditioning": False,
            },
            "notes": [
                "No power-pole area lower bound is injected into certified exact mode.",
                "Exploratory mode only keeps optional pose caps through assignment constraints.",
            ],
        }
        self.build_stats["global_valid_inequalities"] = stats
        if not self.exact_mode:
            return

        self._add_exact_optional_cardinality_bounds(stats)
        stats["fixed_required_optional_demands"] = self._exact_fixed_required_optional_powered_demands()
        stats["lower_bound_optional_powered_demands"] = self._lower_bound_optional_powered_demands()
        self._power_pole_family_count_vars = {}
        if self.skip_power_coverage:
            stats["notes"].append(
                "Exact local power-capacity lower bounds are skipped when power coverage is disabled."
            )
            stats["power_capacity_families"]["reason"] = "power_coverage_skipped"
            stats["aggregated_power_capacity_terms"]["reason"] = "power_coverage_skipped"
            return

        powered_template_demands = self._exact_powered_template_demands()
        stats["powered_template_demands"] = dict(powered_template_demands)
        if not powered_template_demands:
            stats["power_capacity_families"]["reason"] = "no_powered_template_demands"
            stats["aggregated_power_capacity_terms"]["reason"] = "no_powered_template_demands"
            return

        pole_vars = self.optional_pose_vars.get("power_pole", {})
        coeff_stats: Dict[str, Any] = {}
        cache_stats = dict(stats["capacity_cache"])
        coeff_by_template_and_pole: Dict[str, Dict[int, int]] = {}
        for tpl, demand in sorted(powered_template_demands.items()):
            coeff_by_pole: Dict[int, int] = {}
            for pole_idx in sorted(pole_vars):
                coeff = self._exact_local_power_capacity_coefficient(tpl, int(pole_idx), cache_stats)
                coeff_by_pole[int(pole_idx)] = coeff
            positive_coeffs = [value for value in coeff_by_pole.values() if value > 0]
            coeff_by_template_and_pole[tpl] = coeff_by_pole
            coeff_stats[tpl] = {
                "demand": demand,
                "total_poles": len(coeff_by_pole),
                "nonzero_poles": len(positive_coeffs),
                "max_coeff": max(positive_coeffs) if positive_coeffs else 0,
                "min_nonzero_coeff": min(positive_coeffs) if positive_coeffs else None,
            }
            stats["applied"].append(
                {
                    "type": "power_capacity_lower_bound",
                    "template": tpl,
                    "demand": demand,
                    "nonzero_poles": coeff_stats[tpl]["nonzero_poles"],
                }
            )

        family_members: DefaultDict[Tuple[Tuple[str, int], ...], List[int]] = defaultdict(list)
        template_order = sorted(powered_template_demands)
        for pole_idx in sorted(pole_vars):
            family_key = tuple(
                (tpl, int(coeff_by_template_and_pole.get(tpl, {}).get(int(pole_idx), 0)))
                for tpl in template_order
            )
            family_members[family_key].append(int(pole_idx))

        family_coefficients: Dict[str, Dict[str, int]] = {}
        family_sizes: Dict[str, int] = {}
        family_terms: Dict[str, cp_model.IntVar] = {}
        for family_index, family_key in enumerate(sorted(family_members)):
            family_id = f"family_{family_index:03d}"
            members = sorted(family_members[family_key])
            family_var = self.model.NewIntVar(
                0,
                len(members),
                f"power_pole_family_count__{family_id}",
            )
            self.model.Add(sum(pole_vars[pole_idx] for pole_idx in members) == family_var)
            self._power_pole_family_count_vars[family_id] = family_var
            family_terms[family_id] = family_var
            family_sizes[family_id] = len(members)
            family_coefficients[family_id] = {
                str(tpl): int(coeff)
                for tpl, coeff in family_key
            }

        aggregated_nonzero_terms = 0
        raw_nonzero_terms = sum(
            int(template_stats["nonzero_poles"])
            for template_stats in coeff_stats.values()
        )
        for tpl, demand in sorted(powered_template_demands.items()):
            terms: List[cp_model.LinearExpr] = []
            for family_id, family_var in family_terms.items():
                coeff = int(family_coefficients[family_id].get(tpl, 0))
                if coeff <= 0:
                    continue
                aggregated_nonzero_terms += 1
                terms.append(coeff * family_var)

            if terms:
                self.model.Add(sum(terms) >= demand)
            else:
                self.model.Add(0 >= demand)

        cache_stats["signature_count"] = len(_LOCAL_POWER_CAPACITY_COMPACT_CACHE)
        stats["capacity_cache"] = cache_stats
        stats["capacity_coeff_stats"] = coeff_stats
        stats["power_capacity_families"] = {
            "applied": True,
            "family_count": len(family_members),
            "raw_pole_count": len(pole_vars),
            "coefficient_source": str(
                cache_stats.get("coefficient_source", "exact_rect_dp_cache_v7")
            ),
            "shell_pair_count": int(cache_stats.get("shell_pair_count", 0)),
            "compact_signature_class_count": int(
                cache_stats.get("compact_signature_class_count", 0)
            ),
            "families": [
                {
                    "family_id": family_id,
                    "size": int(family_sizes[family_id]),
                    "coefficients": {
                        str(tpl): int(coefficients[tpl])
                        for tpl in template_order
                    },
                }
                for family_id, coefficients in sorted(family_coefficients.items())
            ],
        }
        stats["aggregated_power_capacity_terms"] = {
            "applied": True,
            "raw_nonzero_terms": int(raw_nonzero_terms),
            "aggregated_nonzero_terms": int(aggregated_nonzero_terms),
        }

    def _required_generic_input_slot_total(self) -> int:
        return sum(
            int(v)
            for v in self.generic_io_requirements.get("required_generic_inputs", {}).values()
        )

    def _mandatory_powered_nonpole_count(self) -> int:
        return sum(
            int(group["count"])
            for group in self._mandatory_groups
            if str(group["facility_type"]) in self._powered_templates
            and str(group["facility_type"]) != "power_pole"
        )

    def _required_protocol_storage_box_lower_bound(self) -> int:
        return int(self._certified_optional_lower_bounds.get("protocol_storage_box", 0))

    def _certified_optional_slot_upper_bound(self, tpl: str) -> int:
        tpl = str(tpl)
        if tpl == "power_pole":
            return 0
        pool = list(self.facility_pools.get(tpl, []))
        if not pool:
            return 0
        template = dict(self.templates.get(tpl, {}))
        dims = dict(template.get("dimensions", {}))
        width = int(dims.get("w", 0))
        height = int(dims.get("h", 0))
        area = int(width) * int(height)
        if area <= 0:
            return 0
        candidate_pose_count = int(len(pool))
        grid_area = int(self.grid_w) * int(self.grid_h)
        geometric_upper_bound = int(grid_area // area)
        return int(min(candidate_pose_count, geometric_upper_bound))

    def _certified_optional_slot_upper_bounds(self) -> Dict[str, int]:
        return {
            str(tpl): int(self._certified_optional_slot_upper_bound(str(tpl)))
            for tpl in sorted(POSE_LEVEL_OPTIONAL_TEMPLATES)
            if str(tpl) != "power_pole"
            and int(self._certified_optional_slot_upper_bound(str(tpl))) > 0
        }

    def _residual_optional_powered_slot_upper_bounds(self) -> Dict[str, int]:
        return {
            str(tpl): int(upper_bound)
            for tpl, upper_bound in sorted(self._certified_optional_slot_upper_bounds().items())
            if str(tpl) in self._powered_templates
            and str(tpl) != "power_pole"
            and int(self._exact_required_pose_optional_counts.get(str(tpl), 0)) <= 0
        }

    def _add_exact_optional_cardinality_bounds(self, stats: Dict[str, Any]) -> None:
        optional_bounds: Dict[str, Any] = {}

        protocol_box_vars = self.optional_pose_vars.get("protocol_storage_box", {})
        required_generic_input_slots = self._required_generic_input_slot_total()
        protocol_storage_box_count = self._required_protocol_storage_box_lower_bound()
        protocol_box_terms = list(protocol_box_vars.values())
        self.model.Add(sum(protocol_box_terms) >= int(protocol_storage_box_count))
        optional_bounds["protocol_storage_box"] = {
            "mode": "required_lower_bound",
            "required_generic_input_slots": int(required_generic_input_slots),
            "slots_per_pose": int(
                get_operation_port_profile(
                    POSE_LEVEL_OPTIONAL_OPERATIONS["protocol_storage_box"]
                ).generic_input_slots
            ),
            "lower": int(protocol_storage_box_count),
            "upper": None,
            "candidate_pose_count": len(protocol_box_terms),
        }
        stats["applied"].append(
            {
                "type": "optional_cardinality_bound",
                "template": "protocol_storage_box",
                "mode": "required_lower_bound",
                "lower": int(protocol_storage_box_count),
                "upper": None,
            }
        )

        power_pole_vars = self.optional_pose_vars.get("power_pole", {})
        mandatory_powered_nonpole = self._mandatory_powered_nonpole_count()
        optional_powered_templates = sorted(
            tpl
            for tpl in self.optional_pose_vars
            if tpl != "power_pole" and tpl in self._powered_templates
        )
        optional_powered_terms = [
            var
            for tpl in optional_powered_templates
            for var in self.optional_pose_vars.get(tpl, {}).values()
        ]
        self.model.Add(
            sum(power_pole_vars.values())
            <= int(mandatory_powered_nonpole) + sum(optional_powered_terms)
        )
        optional_bounds["power_pole"] = {
            "mode": "selected_powered_upper_bound",
            "lower": 0,
            "candidate_pose_count": len(power_pole_vars),
            "mandatory_powered_nonpole": int(mandatory_powered_nonpole),
            "optional_powered_templates": optional_powered_templates,
        }
        stats["applied"].append(
            {
                "type": "optional_cardinality_bound",
                "template": "power_pole",
                "mode": "selected_powered_upper_bound",
                "mandatory_powered_nonpole": int(mandatory_powered_nonpole),
                "optional_powered_templates": optional_powered_templates,
            }
        )
        stats["optional_cardinality_bounds"] = optional_bounds

    def _pose_sort_key(self, tpl: str, pose_idx: int) -> Tuple[int, int, str, int]:
        pose = self.facility_pools[tpl][pose_idx]
        anchor = dict(pose.get("anchor", {}))
        return (
            int(anchor.get("x", 0)),
            int(anchor.get("y", 0)),
            str(pose.get("pose_id", "")),
            int(pose_idx),
        )

    def _pose_cells(self, tpl: str, pose_idx: int) -> Set[Tuple[int, int]]:
        return set(self._pose_cells_by_template_pose.get(tpl, {}).get(pose_idx, frozenset()))

    def _exact_powered_template_demands(self) -> Dict[str, int]:
        counts: Dict[str, int] = defaultdict(int)
        for group in self._mandatory_groups:
            tpl = str(group["facility_type"])
            if tpl in self._powered_templates and tpl != "power_pole":
                counts[tpl] += int(group["count"])
        for tpl, count in self._lower_bound_optional_powered_demands().items():
            counts[str(tpl)] += int(count)
        return dict(sorted(counts.items()))

    def _lower_bound_optional_powered_demands(self) -> Dict[str, int]:
        return {
            str(tpl): int(count)
            for tpl, count in sorted(self._certified_optional_lower_bounds.items())
            if int(count) > 0 and str(tpl) in self._powered_templates and str(tpl) != "power_pole"
        }

    def _exact_fixed_required_optional_powered_demands(self) -> Dict[str, int]:
        return {
            str(tpl): int(count)
            for tpl, count in sorted(self._exact_required_pose_optional_counts.items())
            if int(count) > 0 and str(tpl) in self._powered_templates and str(tpl) != "power_pole"
        }

    def _materialize_local_power_capacity_signature_for_pole(
        self,
        tpl: str,
        pole_idx: int,
    ) -> LocalCapacitySignature:
        tpl = str(tpl)
        origin_x, origin_y = self._pose_anchor_by_template_pose.get("power_pole", {}).get(
            int(pole_idx),
            (0, 0),
        )
        pose_anchors = self._pose_anchor_by_template_pose.get(tpl, {})
        pose_local_cells = self._pose_local_cells_by_template_pose.get(tpl, {})
        supported_by_pole = self._power_supported_pose_indices_by_template_pole.get(tpl, {})

        relative_shapes: List[LocalPoseShape] = []
        for pose_idx in supported_by_pole.get(int(pole_idx), []):
            anchor_x, anchor_y = pose_anchors.get(int(pose_idx), (0, 0))
            delta_x = int(anchor_x) - int(origin_x)
            delta_y = int(anchor_y) - int(origin_y)
            local_cells = pose_local_cells.get(int(pose_idx), tuple())
            relative_shapes.append(
                tuple(
                    (int(cell_x) + delta_x, int(cell_y) + delta_y)
                    for cell_x, cell_y in local_cells
                )
            )
        return tuple(sorted(relative_shapes))

    def _materialize_local_power_capacity_signature_from_compact(
        self,
        tpl: str,
        compact_signature: CompactLocalCapacitySignature,
    ) -> LocalCapacitySignature:
        tpl = str(tpl)
        local_shapes = self._local_shape_by_template_token.get(tpl, {})
        relative_shapes: List[LocalPoseShape] = []
        for delta_x, delta_y, shape_token in compact_signature:
            local_shape = local_shapes.get(int(shape_token))
            if local_shape is None:
                raise RuntimeError(
                    f"Missing local shape token {shape_token} for template {tpl}"
                )
            relative_shapes.append(
                tuple(
                    (int(cell_x) + int(delta_x), int(cell_y) + int(delta_y))
                    for cell_x, cell_y in local_shape
                )
            )
        return tuple(sorted(relative_shapes))

    def _compact_local_power_capacity_signature(
        self,
        tpl: str,
        pole_idx: int,
    ) -> CompactLocalCapacitySignature:
        tpl = str(tpl)
        cached = self._compact_local_power_capacity_signature_by_template_pole.get(
            tpl,
            {},
        ).get(int(pole_idx))
        if cached is not None:
            return cached
        self._build_local_power_capacity_signature_classes(tpl)
        return self._compact_local_power_capacity_signature_by_template_pole.get(
            tpl,
            {},
        ).get(int(pole_idx), tuple())

    def _local_power_capacity_signature(self, tpl: str, pole_idx: int) -> LocalCapacitySignature:
        tpl = str(tpl)
        cached = self._local_power_capacity_signature_by_template_pole.get(tpl, {}).get(
            int(pole_idx)
        )
        if cached is not None:
            return cached
        self._build_local_power_capacity_signature_classes(tpl)
        return self._local_power_capacity_signature_by_template_pole.get(tpl, {}).get(
            int(pole_idx),
            tuple(),
        )

    def _build_local_power_capacity_signature_classes(
        self,
        tpl: str,
    ) -> Dict[LocalCapacitySignature, List[int]]:
        tpl = str(tpl)
        cached = self._power_pole_pose_indices_by_template_capacity_signature.get(tpl)
        if cached is not None:
            return cached

        pole_count = int(len(self.facility_pools.get("power_pole", [])))
        power_pole_anchors = self._pose_anchor_by_template_pose.get("power_pole", {})
        pose_anchors = self._pose_anchor_by_template_pose.get(tpl, {})
        pose_shape_tokens = self._pose_local_shape_token_by_template_pose.get(tpl, {})
        supported_by_pole = self._power_supported_pose_indices_by_template_pole.get(tpl, {})

        signature_by_pole: Dict[int, LocalCapacitySignature] = {}
        compact_signature_by_pole: Dict[int, CompactLocalCapacitySignature] = {}
        grouped_pose_indices_by_compact: DefaultDict[
            CompactLocalCapacitySignature,
            List[int],
        ] = defaultdict(list)
        for pole_idx in range(pole_count):
            origin_x, origin_y = power_pole_anchors.get(int(pole_idx), (0, 0))
            compact_items: List[CompactLocalCapacityItem] = []
            for pose_idx in supported_by_pole.get(int(pole_idx), []):
                anchor_x, anchor_y = pose_anchors.get(int(pose_idx), (0, 0))
                delta_x = int(anchor_x) - int(origin_x)
                delta_y = int(anchor_y) - int(origin_y)
                shape_token = pose_shape_tokens.get(int(pose_idx))
                if shape_token is None:
                    raise RuntimeError(
                        f"Missing local shape token for template {tpl} pose {pose_idx}"
                    )
                compact_items.append(
                    (int(delta_x), int(delta_y), int(shape_token))
                )
            compact_signature = tuple(sorted(compact_items))
            compact_signature_by_pole[int(pole_idx)] = compact_signature
            grouped_pose_indices_by_compact[compact_signature].append(int(pole_idx))

        grouped_pose_indices: DefaultDict[LocalCapacitySignature, List[int]] = defaultdict(list)
        legacy_by_compact: Dict[CompactLocalCapacitySignature, LocalCapacitySignature] = {}
        compact_by_legacy: Dict[LocalCapacitySignature, CompactLocalCapacitySignature] = {}
        for compact_signature, pose_indices in sorted(grouped_pose_indices_by_compact.items()):
            legacy_signature = self._materialize_local_power_capacity_signature_from_compact(
                tpl,
                compact_signature,
            )
            representative_signature = self._materialize_local_power_capacity_signature_for_pole(
                tpl,
                int(pose_indices[0]),
            )
            if legacy_signature != representative_signature:
                raise RuntimeError(
                    f"Compact local-capacity signature mismatch for template {tpl}"
                )
            existing_compact = compact_by_legacy.get(legacy_signature)
            if existing_compact is not None and existing_compact != compact_signature:
                raise RuntimeError(
                    f"Distinct compact local-capacity signatures map to the same legacy signature for template {tpl}"
                )
            compact_by_legacy[legacy_signature] = compact_signature
            legacy_by_compact[compact_signature] = legacy_signature
            ordered_pose_indices = sorted(
                pose_indices,
                key=lambda idx: self._pose_sort_key("power_pole", int(idx)),
            )
            grouped_pose_indices[legacy_signature].extend(ordered_pose_indices)
            for pole_idx in ordered_pose_indices:
                signature_by_pole[int(pole_idx)] = legacy_signature

        self._local_power_capacity_signature_by_template_pole[tpl] = signature_by_pole
        self._compact_local_power_capacity_signature_by_template_pole[tpl] = (
            compact_signature_by_pole
        )
        self._power_pole_pose_indices_by_template_capacity_signature[tpl] = {
            signature: sorted(
                pose_indices,
                key=lambda idx: self._pose_sort_key("power_pole", int(idx)),
            )
            for signature, pose_indices in sorted(grouped_pose_indices.items())
        }
        self._power_pole_pose_indices_by_template_compact_capacity_signature[tpl] = {
            compact_signature: sorted(
                pose_indices,
                key=lambda idx: self._pose_sort_key("power_pole", int(idx)),
            )
            for compact_signature, pose_indices in sorted(grouped_pose_indices_by_compact.items())
        }
        self._legacy_local_power_capacity_signature_by_template_compact_signature[tpl] = (
            legacy_by_compact
        )
        return self._power_pole_pose_indices_by_template_capacity_signature[tpl]

    def _solve_exact_local_power_capacity_cpsat(
        self,
        tpl: str,
        signature: LocalCapacitySignature,
    ) -> int:
        if not signature:
            return 0

        cache_key = (str(tpl), signature)
        cached = _LOCAL_POWER_CAPACITY_CACHE.get(cache_key)
        if cached is not None:
            return cached

        local_model = cp_model.CpModel()
        local_vars = [
            local_model.NewBoolVar(f"local_power_cap__{tpl}__{idx}")
            for idx in range(len(signature))
        ]
        cell_terms: DefaultDict[Tuple[int, int], List[cp_model.IntVar]] = defaultdict(list)
        for idx, relative_cells in enumerate(signature):
            for cell in relative_cells:
                cell_terms[cell].append(local_vars[idx])
        for terms in cell_terms.values():
            if len(terms) > 1:
                local_model.Add(sum(terms) <= 1)
        local_model.Maximize(sum(local_vars))

        solver = cp_model.CpSolver()
        solver.parameters.num_search_workers = 8
        status = solver.Solve(local_model)
        if status != cp_model.OPTIMAL:
            raise RuntimeError(
                f"Failed to compute exact local power capacity for template {tpl}: {solver.StatusName(status)}"
            )
        capacity = int(round(solver.ObjectiveValue()))
        _LOCAL_POWER_CAPACITY_CACHE[cache_key] = capacity
        return capacity

    def _solve_exact_local_power_capacity_bitset_mis(
        self,
        tpl: str,
        signature: LocalCapacitySignature,
    ) -> int:
        if not signature:
            return 0

        unique_shapes = list(dict.fromkeys(signature))
        if len(unique_shapes) <= 1:
            return int(len(unique_shapes))

        try:
            min_x = min(cell_x for shape in unique_shapes for cell_x, _ in shape)
            min_y = min(cell_y for shape in unique_shapes for _, cell_y in shape)
            max_x = max(cell_x for shape in unique_shapes for cell_x, _ in shape)
        except ValueError as exc:
            raise _BitsetLocalCapacityFallback(
                f"Unsupported empty local-capacity shape for template {tpl}"
            ) from exc

        width = int(max_x - min_x + 1)
        if width <= 0:
            raise _BitsetLocalCapacityFallback(
                f"Invalid local-capacity bitset width for template {tpl}"
            )

        bitsets: List[int] = []
        seen_bitsets: Set[int] = set()
        for shape in unique_shapes:
            bitset = 0
            for cell_x, cell_y in shape:
                bit_index = (int(cell_y) - int(min_y)) * width + (int(cell_x) - int(min_x))
                bitset |= 1 << int(bit_index)
            if bitset <= 0:
                raise _BitsetLocalCapacityFallback(
                    f"Unsupported zero-bit local-capacity shape for template {tpl}"
                )
            if bitset not in seen_bitsets:
                seen_bitsets.add(bitset)
                bitsets.append(bitset)

        vertex_count = len(bitsets)
        if vertex_count <= 1:
            return int(vertex_count)

        adjacency = [0] * vertex_count
        for left in range(vertex_count):
            left_bits = bitsets[left]
            for right in range(left + 1, vertex_count):
                if left_bits & bitsets[right]:
                    adjacency[left] |= 1 << right
                    adjacency[right] |= 1 << left

        max_iterations = int(self._local_power_capacity_bitset_max_iterations)
        iteration_count = 0
        memo: Dict[int, int] = {}

        def split_components(mask: int) -> List[int]:
            components: List[int] = []
            remaining = int(mask)
            while remaining:
                seed = remaining & -remaining
                component = 0
                frontier = seed
                while frontier:
                    bit = frontier & -frontier
                    frontier &= ~bit
                    if component & bit:
                        continue
                    component |= bit
                    idx = bit.bit_length() - 1
                    frontier |= adjacency[idx] & remaining & ~component
                components.append(component)
                remaining &= ~component
            return components

        def solve_component(mask: int) -> int:
            nonlocal iteration_count
            iteration_count += 1
            if iteration_count > max_iterations:
                raise _BitsetLocalCapacityFallback(
                    f"Bitset MIS iteration limit exceeded for template {tpl}"
                )
            if mask == 0:
                return 0
            cached = memo.get(mask)
            if cached is not None:
                return cached

            forced = 0
            reduced = int(mask)
            while reduced:
                isolated = 0
                remaining = int(reduced)
                while remaining:
                    bit = remaining & -remaining
                    remaining &= ~bit
                    idx = bit.bit_length() - 1
                    if (adjacency[idx] & reduced) == 0:
                        isolated |= bit
                if isolated == 0:
                    break
                forced += isolated.bit_count()
                reduced &= ~isolated
            if reduced == 0:
                memo[mask] = forced
                return forced

            components = split_components(reduced)
            if len(components) > 1:
                total = forced + sum(solve_component(component) for component in components)
                memo[mask] = total
                return total

            branch_vertex = -1
            branch_degree = -1
            remaining = int(reduced)
            while remaining:
                bit = remaining & -remaining
                remaining &= ~bit
                idx = bit.bit_length() - 1
                degree = int((adjacency[idx] & reduced).bit_count())
                if degree > branch_degree:
                    branch_degree = degree
                    branch_vertex = idx
            if branch_vertex < 0:
                memo[mask] = forced + reduced.bit_count()
                return memo[mask]
            if branch_degree <= 0:
                memo[mask] = forced + reduced.bit_count()
                return memo[mask]

            branch_bit = 1 << branch_vertex
            include_value = forced + 1 + solve_component(
                reduced & ~adjacency[branch_vertex] & ~branch_bit
            )
            exclude_mask = reduced & ~branch_bit
            if exclude_mask.bit_count() <= include_value - forced:
                memo[mask] = include_value
                return include_value
            exclude_value = forced + solve_component(exclude_mask)
            best = max(include_value, exclude_value)
            memo[mask] = best
            return best

        return int(solve_component((1 << vertex_count) - 1))

    def _normalize_rectangle_frontier_signature(
        self,
        tpl: str,
        compact_signature: CompactLocalCapacitySignature,
    ) -> Tuple[Tuple[int, int, int, int], ...]:
        if not compact_signature:
            return tuple()
        rect_variants = self._ensure_local_rectangle_variants(tpl)
        placements: Set[Tuple[int, int, int, int]] = set()
        for delta_x, delta_y, shape_token in compact_signature:
            variant = rect_variants.get(int(shape_token))
            if variant is None:
                raise _RectangleFrontierDPFallback(
                    f"Non-rectangular local shape token {shape_token} for template {tpl}"
                )
            placements.add(
                (
                    int(delta_x) + int(variant.min_x),
                    int(delta_y) + int(variant.min_y),
                    int(variant.width),
                    int(variant.height),
                )
            )
        if not placements:
            return tuple()
        min_x = min(int(x_val) for x_val, _, _, _ in placements)
        min_y = min(int(y_val) for _, y_val, _, _ in placements)
        normalized = {
            (
                int(x_val) - int(min_x),
                int(y_val) - int(min_y),
                int(width),
                int(height),
            )
            for x_val, y_val, width, height in placements
        }
        return tuple(sorted(normalized))

    def _rectangle_frontier_scan_stats(
        self,
        normalized: Sequence[Tuple[int, int, int, int]],
    ) -> Tuple[int, int]:
        if not normalized:
            return 0, 0
        window_w = max(int(x_val) + int(width) for x_val, _, width, _ in normalized)
        window_h = max(int(y_val) + int(height) for _, y_val, _, height in normalized)
        max_rect_w = max(int(width) for _, _, width, _ in normalized)
        max_rect_h = max(int(height) for _, _, _, height in normalized)
        row_frontier_bits = int(window_w) * max(0, int(max_rect_h) - 1)
        col_frontier_bits = int(window_h) * max(0, int(max_rect_w) - 1)
        return int(row_frontier_bits), int(col_frontier_bits)

    def _should_use_rectangle_frontier_dp_v4(
        self,
        compiled: _CompiledRectangleFrontierDP,
    ) -> bool:
        return (
            int(compiled.peak_line_subset_options)
            <= int(self._local_power_capacity_rect_dp_v4_max_peak_line_subset_options)
            and int(compiled.compiled_line_subsets)
            <= int(self._local_power_capacity_rect_dp_v4_max_compiled_line_subsets)
        )

    def _is_manufacturing_6x4_mixed_signature(
        self,
        tpl: str,
        compact_signature: CompactLocalCapacitySignature,
    ) -> bool:
        if str(tpl) != "manufacturing_6x4":
            return False
        normalized = self._normalize_rectangle_frontier_signature(str(tpl), compact_signature)
        if not normalized:
            return False
        variants = {(int(width), int(height)) for _, _, width, height in normalized}
        return variants == {(6, 4), (4, 6)}

    def _compile_manufacturing_6x4_mixed_cpsat_data(
        self,
        tpl: str,
        compact_signature: CompactLocalCapacitySignature,
    ) -> _CompiledManufacturing6x4MixedCpSatData:
        cache_key = (str(tpl), compact_signature)
        cached = _LOCAL_POWER_CAPACITY_M6X4_MIXED_CPSAT_DATA_CACHE.get(cache_key)
        if cached is not None:
            return cached

        normalized = self._normalize_rectangle_frontier_signature(str(tpl), compact_signature)
        if not normalized:
            compiled = _CompiledManufacturing6x4MixedCpSatData(
                window_w=0,
                window_h=0,
                placements=tuple(),
                cell_to_placement_indices={},
            )
            _LOCAL_POWER_CAPACITY_M6X4_MIXED_CPSAT_DATA_CACHE[cache_key] = compiled
            return compiled

        placements = tuple(
            sorted(
                {
                    (
                        int(x_val),
                        int(y_val),
                        int(width),
                        int(height),
                    )
                    for x_val, y_val, width, height in normalized
                }
            )
        )
        window_w = max(int(x_val) + int(width) for x_val, _, width, _ in placements)
        window_h = max(int(y_val) + int(height) for _, y_val, _, height in placements)
        cell_to_indices: DefaultDict[Tuple[int, int], List[int]] = defaultdict(list)
        for placement_idx, (x_val, y_val, width, height) in enumerate(placements):
            for dx in range(int(width)):
                for dy in range(int(height)):
                    cell_to_indices[(int(x_val) + dx, int(y_val) + dy)].append(
                        int(placement_idx)
                    )
        compiled = _CompiledManufacturing6x4MixedCpSatData(
            window_w=int(window_w),
            window_h=int(window_h),
            placements=placements,
            cell_to_placement_indices={
                cell: tuple(indices) for cell, indices in cell_to_indices.items()
            },
        )
        _LOCAL_POWER_CAPACITY_M6X4_MIXED_CPSAT_DATA_CACHE[cache_key] = compiled
        return compiled

    def _compile_rectangle_frontier_dp(
        self,
        tpl: str,
        compact_signature: CompactLocalCapacitySignature,
        *,
        scan_axis: str,
    ) -> _CompiledRectangleFrontierDP:
        cache_key = (str(tpl), compact_signature, str(scan_axis))
        cached = _LOCAL_POWER_CAPACITY_RECT_DP_COMPILED_CACHE.get(cache_key)
        if cached is not None:
            return cached

        normalized = self._normalize_rectangle_frontier_signature(str(tpl), compact_signature)
        if not normalized:
            compiled = _CompiledRectangleFrontierDP(
                scan_axis=str(scan_axis),
                line_count=0,
                line_width=0,
                frontier_bits=0,
                horizon=0,
                line_end_shift=0,
                current_bit_masks=tuple(),
                placements_by_line_and_pos=tuple(),
                start_options_by_line_and_pos=tuple(),
                line_subset_transitions_by_line=tuple(),
                compiled_start_options=0,
                deduped_start_options=0,
                compiled_line_subsets=0,
                peak_line_subset_options=0,
            )
            _LOCAL_POWER_CAPACITY_RECT_DP_COMPILED_CACHE[cache_key] = compiled
            return compiled

        placements = list(normalized)
        window_w = max(int(x_val) + int(width) for x_val, _, width, _ in placements)
        window_h = max(int(y_val) + int(height) for _, y_val, _, height in placements)
        max_rect_w = max(int(width) for _, _, width, _ in placements)
        max_rect_h = max(int(height) for _, _, _, height in placements)
        if window_w <= 0 or window_h <= 0 or max_rect_w <= 0 or max_rect_h <= 0:
            raise _RectangleFrontierDPFallback(
                f"Invalid rectangle frontier domain for template {tpl}"
            )

        if scan_axis == "row":
            line_count = int(window_h)
            line_width = int(window_w)
            max_span = int(max_rect_h)
            frontier_bits = int(window_w) * max(0, int(max_rect_h) - 1)
            encoded = [
                (int(y_val), int(x_val), int(height), int(width))
                for x_val, y_val, width, height in placements
            ]
        elif scan_axis == "column":
            line_count = int(window_w)
            line_width = int(window_h)
            max_span = int(max_rect_w)
            frontier_bits = int(window_h) * max(0, int(max_rect_w) - 1)
            encoded = [
                (int(x_val), int(y_val), int(width), int(height))
                for x_val, y_val, width, height in placements
            ]
        else:
            raise ValueError(f"Unsupported rectangle frontier scan_axis: {scan_axis}")

        if line_count <= 0 or line_width <= 0 or max_span <= 0:
            raise _RectangleFrontierDPFallback(
                f"Invalid rectangle frontier geometry for template {tpl}"
            )

        horizon = max(0, int(max_span) - 1)
        placements_by_line_and_pos: List[List[List[Tuple[int, int, Tuple[int, ...]]]]] = [
            [[] for _ in range(int(line_width))]
            for _ in range(int(line_count))
        ]
        start_options_by_line_and_pos: List[List[List[PackedRectTransition]]] = [
            [[] for _ in range(int(line_width))]
            for _ in range(int(line_count))
        ]
        line_level_options_by_line: List[List[PackedRectTransition]] = [
            [] for _ in range(int(line_count))
        ]
        compiled_start_options = 0
        for start_line, start_pos, span_lines, span_pos in encoded:
            if (
                int(start_line) < 0
                or int(start_pos) < 0
                or int(span_lines) <= 0
                or int(span_pos) <= 0
                or int(start_line) + int(span_lines) > int(line_count)
                or int(start_pos) + int(span_pos) > int(line_width)
            ):
                raise _RectangleFrontierDPFallback(
                    f"Out-of-bounds rectangle frontier placement for template {tpl}"
                )
            interval_mask = ((1 << int(span_pos)) - 1) << int(start_pos)
            placements_by_line_and_pos[int(start_line)][int(start_pos)].append(
                (
                    int(span_lines),
                    int(span_pos),
                    tuple(int(interval_mask) for _ in range(int(span_lines))),
                )
            )
            conflict_mask = 0
            future_write_mask = 0
            for line_offset in range(int(span_lines)):
                placed_mask = int(interval_mask) << (int(line_offset) * int(line_width))
                conflict_mask |= int(placed_mask)
                if int(line_offset) == 0:
                    future_write_mask |= int(interval_mask) & ~(
                        (1 << (int(start_pos) + 1)) - 1
                    )
                else:
                    future_write_mask |= int(placed_mask)
            start_options_by_line_and_pos[int(start_line)][int(start_pos)].append(
                (int(conflict_mask), int(future_write_mask), 1)
            )
            next_line_write_mask = 0
            for line_offset in range(1, int(span_lines)):
                next_line_write_mask |= int(interval_mask) << (
                    (int(line_offset) - 1) * int(line_width)
                )
            line_level_options_by_line[int(start_line)].append(
                (int(conflict_mask), int(next_line_write_mask), 1)
            )
            compiled_start_options += 1

        deduped_start_options = 0
        deduped_start_options_by_line_and_pos: List[List[Tuple[PackedRectTransition, ...]]] = []
        for line_row in start_options_by_line_and_pos:
            deduped_line: List[Tuple[PackedRectTransition, ...]] = []
            for placements_at_pos in line_row:
                deduped = tuple(
                    sorted(
                        set(placements_at_pos),
                        key=lambda item: (
                            int(item[0]),
                            int(item[1]),
                            int(item[2]),
                        ),
                    )
                )
                deduped_start_options += int(len(deduped))
                deduped_line.append(deduped)
            deduped_start_options_by_line_and_pos.append(deduped_line)

        max_line_subsets = int(self._local_power_capacity_rect_dp_max_line_subsets)
        compiled_line_subsets = 0
        peak_line_subset_options = 0
        line_subset_transitions_by_line: List[Tuple[PackedRectTransition, ...]] = []
        for line_options in line_level_options_by_line:
            unique_line_options = tuple(
                sorted(
                    set(line_options),
                    key=lambda item: (
                        int(item[0]),
                        int(item[1]),
                        int(item[2]),
                    ),
                )
            )
            subset_best: Dict[Tuple[int, int], int] = {}
            subset_visits = 0

            def enumerate_subsets(
                option_idx: int,
                combined_conflict: int,
                combined_next_write: int,
                gain: int,
            ) -> None:
                nonlocal subset_visits
                subset_visits += 1
                if subset_visits > max_line_subsets:
                    raise _RectangleFrontierDPFallback(
                        f"Rectangle frontier DP line-subset limit exceeded for template {tpl}"
                    )
                if gain > 0:
                    subset_key = (int(combined_conflict), int(combined_next_write))
                    previous_gain = subset_best.get(subset_key)
                    if previous_gain is None or int(gain) > int(previous_gain):
                        subset_best[subset_key] = int(gain)
                for next_idx in range(int(option_idx), len(unique_line_options)):
                    conflict_mask, next_write_mask, option_gain = unique_line_options[int(next_idx)]
                    if int(combined_conflict) & int(conflict_mask):
                        continue
                    enumerate_subsets(
                        int(next_idx) + 1,
                        int(combined_conflict) | int(conflict_mask),
                        int(combined_next_write) | int(next_write_mask),
                        int(gain) + int(option_gain),
                    )

            enumerate_subsets(0, 0, 0, 0)
            line_subset_transitions = tuple(
                sorted(
                    (
                        (int(conflict_mask), int(next_write_mask), int(gain))
                        for (conflict_mask, next_write_mask), gain in subset_best.items()
                    ),
                    key=lambda item: (
                        int(item[0]),
                        int(item[1]),
                        int(item[2]),
                    ),
                )
            )
            compiled_line_subsets += int(len(line_subset_transitions))
            peak_line_subset_options = max(
                int(peak_line_subset_options),
                int(len(line_subset_transitions)),
            )
            line_subset_transitions_by_line.append(line_subset_transitions)

        compiled = _CompiledRectangleFrontierDP(
            scan_axis=str(scan_axis),
            line_count=int(line_count),
            line_width=int(line_width),
            frontier_bits=int(frontier_bits),
            horizon=int(horizon),
            line_end_shift=int(line_width),
            current_bit_masks=tuple(1 << int(pos) for pos in range(int(line_width))),
            placements_by_line_and_pos=tuple(
                tuple(
                    tuple(
                        sorted(
                            placements_at_pos,
                            key=lambda item: (
                                int(item[0]),
                                int(item[1]),
                                tuple(int(mask) for mask in item[2]),
                            ),
                        )
                    )
                    for placements_at_pos in line_row
                )
                for line_row in placements_by_line_and_pos
            ),
            start_options_by_line_and_pos=tuple(
                tuple(line_row) for line_row in deduped_start_options_by_line_and_pos
            ),
            line_subset_transitions_by_line=tuple(line_subset_transitions_by_line),
            compiled_start_options=int(compiled_start_options),
            deduped_start_options=int(deduped_start_options),
            compiled_line_subsets=int(compiled_line_subsets),
            peak_line_subset_options=int(peak_line_subset_options),
        )
        _LOCAL_POWER_CAPACITY_RECT_DP_COMPILED_CACHE[cache_key] = compiled
        return compiled

    def _solve_exact_local_power_capacity_rectangle_frontier_dp_v1(
        self,
        tpl: str,
        compact_signature: CompactLocalCapacitySignature,
        *,
        scan_axis: Optional[str] = None,
    ) -> int:
        normalized = self._normalize_rectangle_frontier_signature(str(tpl), compact_signature)
        if not normalized:
            return 0
        if len(normalized) <= 1:
            return int(len(normalized))

        placements = list(normalized)
        window_w = max(int(x_val) + int(width) for x_val, _, width, _ in placements)
        window_h = max(int(y_val) + int(height) for _, y_val, _, height in placements)
        max_rect_w = max(int(width) for _, _, width, _ in placements)
        max_rect_h = max(int(height) for _, _, _, height in placements)
        if window_w <= 0 or window_h <= 0 or max_rect_w <= 0 or max_rect_h <= 0:
            raise _RectangleFrontierDPFallback(
                f"Invalid rectangle frontier domain for template {tpl}"
            )

        row_frontier_bits = int(window_w) * max(0, int(max_rect_h) - 1)
        col_frontier_bits = int(window_h) * max(0, int(max_rect_w) - 1)
        if scan_axis is None:
            scan_axis = "row" if row_frontier_bits <= col_frontier_bits else "column"
        if scan_axis not in {"row", "column"}:
            raise ValueError(f"Unsupported rectangle frontier scan_axis: {scan_axis}")

        if scan_axis == "row":
            line_count = int(window_h)
            line_width = int(window_w)
            encoded = [
                (int(y_val), int(x_val), int(height), int(width))
                for x_val, y_val, width, height in placements
            ]
        else:
            line_count = int(window_w)
            line_width = int(window_h)
            encoded = [
                (int(x_val), int(y_val), int(width), int(height))
                for x_val, y_val, width, height in placements
            ]

        max_span = max(int(span_lines) for _, _, span_lines, _ in encoded)
        if line_count <= 0 or line_width <= 0 or max_span <= 0:
            raise _RectangleFrontierDPFallback(
                f"Invalid rectangle frontier geometry for template {tpl}"
            )

        placements_by_line: Dict[int, Dict[int, List[Tuple[int, int, Tuple[int, ...]]]]] = {}
        for start_line, start_pos, span_lines, span_pos in encoded:
            if (
                int(start_line) < 0
                or int(start_pos) < 0
                or int(span_lines) <= 0
                or int(span_pos) <= 0
                or int(start_line) + int(span_lines) > int(line_count)
                or int(start_pos) + int(span_pos) > int(line_width)
            ):
                raise _RectangleFrontierDPFallback(
                    f"Out-of-bounds rectangle frontier placement for template {tpl}"
                )
            interval_mask = ((1 << int(span_pos)) - 1) << int(start_pos)
            placements_by_line.setdefault(int(start_line), {}).setdefault(int(start_pos), []).append(
                (
                    int(span_lines),
                    int(span_pos),
                    tuple(int(interval_mask) for _ in range(int(span_lines))),
                )
            )

        max_states = int(self._local_power_capacity_rect_dp_max_states)
        state_visits = 0
        line_cache: Dict[Tuple[int, int], int] = {}

        def solve_line(line_idx: int, packed_state: int) -> int:
            nonlocal state_visits
            if line_idx >= line_count:
                return 0 if packed_state == 0 else -10**9
            cache_key = (int(line_idx), int(packed_state))
            cached = line_cache.get(cache_key)
            if cached is not None:
                return int(cached)
            state_visits += 1
            if state_visits > max_states:
                raise _RectangleFrontierDPFallback(
                    f"Rectangle frontier DP state limit exceeded for template {tpl}"
                )

            placements_by_pos = placements_by_line.get(int(line_idx), {})
            pos_cache: Dict[Tuple[int, int], int] = {}

            def solve_pos(pos: int, working_state: int) -> int:
                nonlocal state_visits
                while pos < line_width and ((int(working_state) >> int(pos)) & 1):
                    pos += 1
                if pos >= line_width:
                    return solve_line(int(line_idx) + 1, int(working_state) >> int(line_width))
                pos_key = (int(pos), int(working_state))
                cached_pos = pos_cache.get(pos_key)
                if cached_pos is not None:
                    return int(cached_pos)
                state_visits += 1
                if state_visits > max_states:
                    raise _RectangleFrontierDPFallback(
                        f"Rectangle frontier DP state limit exceeded for template {tpl}"
                    )

                best = int(solve_pos(int(pos) + 1, int(working_state)))
                for span_lines, span_pos, line_masks in placements_by_pos.get(int(pos), []):
                    conflict = False
                    for line_offset, line_mask in enumerate(line_masks):
                        if (int(working_state) >> (int(line_offset) * int(line_width))) & int(line_mask):
                            conflict = True
                            break
                    if conflict:
                        continue
                    next_state = int(working_state)
                    for line_offset, line_mask in enumerate(line_masks):
                        next_state |= int(line_mask) << (int(line_offset) * int(line_width))
                    best = max(
                        int(best),
                        1 + int(solve_pos(int(pos) + int(span_pos), int(next_state))),
                    )
                pos_cache[pos_key] = int(best)
                return int(best)

            result = int(solve_pos(0, int(packed_state)))
            line_cache[cache_key] = int(result)
            return int(result)

        return int(solve_line(0, 0))

    def _solve_exact_local_power_capacity_rectangle_frontier_dp_v2(
        self,
        tpl: str,
        compact_signature: CompactLocalCapacitySignature,
        *,
        scan_axis: Optional[str] = None,
        cache_stats: Optional[Dict[str, Any]] = None,
    ) -> int:
        normalized = self._normalize_rectangle_frontier_signature(str(tpl), compact_signature)
        if not normalized:
            return 0
        if len(normalized) <= 1:
            return int(len(normalized))

        row_frontier_bits, col_frontier_bits = self._rectangle_frontier_scan_stats(normalized)
        if scan_axis is None:
            scan_axis = "row" if row_frontier_bits <= col_frontier_bits else "column"
        if scan_axis not in {"row", "column"}:
            raise ValueError(f"Unsupported rectangle frontier scan_axis: {scan_axis}")

        compiled = self._compile_rectangle_frontier_dp(
            str(tpl),
            compact_signature,
            scan_axis=str(scan_axis),
        )
        if compiled.line_count <= 0 or compiled.line_width <= 0:
            return 0

        max_states = int(self._local_power_capacity_rect_dp_max_states)
        line_states: Dict[int, int] = {0: 0}
        state_counter = 1
        state_merges = 0
        peak_line_states = 1
        peak_pos_states = 0

        def merge_state(
            state_map: Dict[int, int],
            packed_state: int,
            best_count: int,
        ) -> None:
            nonlocal state_counter, state_merges
            existing = state_map.get(int(packed_state))
            if existing is None:
                state_map[int(packed_state)] = int(best_count)
                state_counter += 1
                if state_counter > max_states:
                    raise _RectangleFrontierDPFallback(
                        f"Rectangle frontier DP state limit exceeded for template {tpl}"
                    )
                return
            state_merges += 1
            if int(best_count) > int(existing):
                state_map[int(packed_state)] = int(best_count)

        line_width = int(compiled.line_width)
        for line_idx in range(int(compiled.line_count)):
            placements_by_pos = compiled.placements_by_line_and_pos[int(line_idx)]
            pos_states = dict(line_states)
            peak_pos_states = max(int(peak_pos_states), int(len(pos_states)))
            for pos in range(int(line_width)):
                next_pos_states: Dict[int, int] = {}
                bit_mask = 1 << int(pos)
                for packed_state, current_count in pos_states.items():
                    if int(packed_state) & int(bit_mask):
                        merge_state(next_pos_states, int(packed_state), int(current_count))
                        continue
                    merge_state(next_pos_states, int(packed_state), int(current_count))
                    for span_lines, span_pos, line_masks in placements_by_pos[int(pos)]:
                        conflict = False
                        for line_offset, line_mask in enumerate(line_masks):
                            chunk_bits = int(packed_state) >> (int(line_offset) * int(line_width))
                            if int(chunk_bits) & int(line_mask):
                                conflict = True
                                break
                        if conflict:
                            continue
                        next_state = int(packed_state)
                        for line_offset, line_mask in enumerate(line_masks):
                            next_state |= int(line_mask) << (int(line_offset) * int(line_width))
                        merge_state(
                            next_pos_states,
                            int(next_state),
                            int(current_count) + 1,
                        )
                pos_states = next_pos_states
                peak_pos_states = max(int(peak_pos_states), int(len(pos_states)))
            line_states = {}
            for packed_state, current_count in pos_states.items():
                merge_state(line_states, int(packed_state) >> int(line_width), int(current_count))
            peak_line_states = max(int(peak_line_states), int(len(line_states)))

        result = int(line_states.get(0, -10**9))
        if result < 0:
            raise _RectangleFrontierDPFallback(
                f"Rectangle frontier DP terminated with residual frontier for template {tpl}"
            )

        if cache_stats is not None:
            cache_stats["rect_dp_state_merges"] = int(
                cache_stats.get("rect_dp_state_merges", 0)
            ) + int(state_merges)
            cache_stats["rect_dp_peak_line_states"] = max(
                int(cache_stats.get("rect_dp_peak_line_states", 0)),
                int(peak_line_states),
            )
            cache_stats["rect_dp_peak_pos_states"] = max(
                int(cache_stats.get("rect_dp_peak_pos_states", 0)),
                int(peak_pos_states),
            )
            cache_stats["rect_dp_compiled_signatures"] = int(
                len(_LOCAL_POWER_CAPACITY_RECT_DP_COMPILED_CACHE)
            )
        return int(result)

    def _solve_exact_local_power_capacity_rectangle_frontier_dp_v3(
        self,
        tpl: str,
        compact_signature: CompactLocalCapacitySignature,
        *,
        scan_axis: Optional[str] = None,
        compiled: Optional[_CompiledRectangleFrontierDP] = None,
        cache_stats: Optional[Dict[str, Any]] = None,
    ) -> int:
        normalized = self._normalize_rectangle_frontier_signature(str(tpl), compact_signature)
        if not normalized:
            return 0
        if len(normalized) <= 1:
            return int(len(normalized))

        row_frontier_bits, col_frontier_bits = self._rectangle_frontier_scan_stats(normalized)
        if scan_axis is None:
            scan_axis = "row" if row_frontier_bits <= col_frontier_bits else "column"
        if scan_axis not in {"row", "column"}:
            raise ValueError(f"Unsupported rectangle frontier scan_axis: {scan_axis}")

        if compiled is None:
            compiled = self._compile_rectangle_frontier_dp(
                str(tpl),
                compact_signature,
                scan_axis=str(scan_axis),
            )
        if compiled.line_count <= 0 or compiled.line_width <= 0:
            return 0

        max_states = int(self._local_power_capacity_rect_dp_max_states)
        line_states: Dict[int, int] = {0: 0}
        state_counter = 1
        state_merges = 0
        peak_line_states = 1
        peak_pos_states = 1

        current_bit_masks = compiled.current_bit_masks
        line_end_shift = int(compiled.line_end_shift)
        for line_idx in range(int(compiled.line_count)):
            pos_states = line_states
            placements_by_pos = compiled.start_options_by_line_and_pos[int(line_idx)]
            peak_pos_states = max(int(peak_pos_states), int(len(pos_states)))
            for pos in range(int(compiled.line_width)):
                next_pos_states: Dict[int, int] = {}
                current_bit_mask = int(current_bit_masks[int(pos)])
                start_options = placements_by_pos[int(pos)]
                for packed_state, current_count in pos_states.items():
                    advance_state = int(packed_state) & ~int(current_bit_mask)
                    existing_advance = next_pos_states.get(int(advance_state))
                    if existing_advance is None:
                        next_pos_states[int(advance_state)] = int(current_count)
                        state_counter += 1
                        if state_counter > max_states:
                            raise _RectangleFrontierDPFallback(
                                f"Rectangle frontier DP state limit exceeded for template {tpl}"
                            )
                    else:
                        state_merges += 1
                        if int(current_count) > int(existing_advance):
                            next_pos_states[int(advance_state)] = int(current_count)

                    if int(packed_state) & int(current_bit_mask):
                        continue
                    for conflict_mask, future_write_mask, gain in start_options:
                        if int(packed_state) & int(conflict_mask):
                            continue
                        next_state = int(packed_state) | int(future_write_mask)
                        next_count = int(current_count) + int(gain)
                        existing_next = next_pos_states.get(int(next_state))
                        if existing_next is None:
                            next_pos_states[int(next_state)] = int(next_count)
                            state_counter += 1
                            if state_counter > max_states:
                                raise _RectangleFrontierDPFallback(
                                    f"Rectangle frontier DP state limit exceeded for template {tpl}"
                                )
                        else:
                            state_merges += 1
                            if int(next_count) > int(existing_next):
                                next_pos_states[int(next_state)] = int(next_count)
                pos_states = next_pos_states
                peak_pos_states = max(int(peak_pos_states), int(len(pos_states)))

            line_states = {}
            for packed_state, current_count in pos_states.items():
                shifted_state = int(packed_state) >> int(line_end_shift)
                existing_shifted = line_states.get(int(shifted_state))
                if existing_shifted is None:
                    line_states[int(shifted_state)] = int(current_count)
                    state_counter += 1
                    if state_counter > max_states:
                        raise _RectangleFrontierDPFallback(
                            f"Rectangle frontier DP state limit exceeded for template {tpl}"
                        )
                else:
                    state_merges += 1
                    if int(current_count) > int(existing_shifted):
                        line_states[int(shifted_state)] = int(current_count)
            peak_line_states = max(int(peak_line_states), int(len(line_states)))

        result = int(line_states.get(0, -10**9))
        if result < 0:
            raise _RectangleFrontierDPFallback(
                f"Rectangle frontier DP terminated with residual frontier for template {tpl}"
            )

        if cache_stats is not None:
            cache_stats["rect_dp_state_merges"] = int(
                cache_stats.get("rect_dp_state_merges", 0)
            ) + int(state_merges)
            cache_stats["rect_dp_peak_line_states"] = max(
                int(cache_stats.get("rect_dp_peak_line_states", 0)),
                int(peak_line_states),
            )
            cache_stats["rect_dp_peak_pos_states"] = max(
                int(cache_stats.get("rect_dp_peak_pos_states", 0)),
                int(peak_pos_states),
            )
            cache_stats["rect_dp_compiled_signatures"] = int(
                len(_LOCAL_POWER_CAPACITY_RECT_DP_COMPILED_CACHE)
            )
            cache_stats["rect_dp_compiled_start_options"] = int(
                sum(
                    int(item.compiled_start_options)
                    for item in _LOCAL_POWER_CAPACITY_RECT_DP_COMPILED_CACHE.values()
                )
            )
            cache_stats["rect_dp_deduped_start_options"] = int(
                sum(
                    int(item.deduped_start_options)
                    for item in _LOCAL_POWER_CAPACITY_RECT_DP_COMPILED_CACHE.values()
                )
            )
        return int(result)

    def _solve_exact_local_power_capacity_rectangle_frontier_dp_v4(
        self,
        tpl: str,
        compact_signature: CompactLocalCapacitySignature,
        *,
        scan_axis: Optional[str] = None,
        compiled: Optional[_CompiledRectangleFrontierDP] = None,
        cache_stats: Optional[Dict[str, Any]] = None,
    ) -> int:
        normalized = self._normalize_rectangle_frontier_signature(str(tpl), compact_signature)
        if not normalized:
            return 0
        if len(normalized) <= 1:
            return int(len(normalized))

        row_frontier_bits, col_frontier_bits = self._rectangle_frontier_scan_stats(normalized)
        if scan_axis is None:
            scan_axis = "row" if row_frontier_bits <= col_frontier_bits else "column"
        if scan_axis not in {"row", "column"}:
            raise ValueError(f"Unsupported rectangle frontier scan_axis: {scan_axis}")

        if compiled is None:
            compiled = self._compile_rectangle_frontier_dp(
                str(tpl),
                compact_signature,
                scan_axis=str(scan_axis),
            )
        if compiled.line_count <= 0 or compiled.line_width <= 0:
            return 0

        max_states = int(self._local_power_capacity_rect_dp_max_states)
        line_states: Dict[int, int] = {0: 0}
        state_counter = 1
        state_merges = 0
        peak_line_states = 1
        peak_pos_states = 1
        peak_line_subset_options = 0

        def merge_state(
            state_map: Dict[int, int],
            packed_state: int,
            best_count: int,
        ) -> None:
            nonlocal state_counter, state_merges
            existing = state_map.get(int(packed_state))
            if existing is None:
                state_map[int(packed_state)] = int(best_count)
                state_counter += 1
                if state_counter > max_states:
                    raise _RectangleFrontierDPFallback(
                        f"Rectangle frontier DP state limit exceeded for template {tpl}"
                    )
                return
            state_merges += 1
            if int(best_count) > int(existing):
                state_map[int(packed_state)] = int(best_count)

        line_end_shift = int(compiled.line_end_shift)
        for line_transitions in compiled.line_subset_transitions_by_line:
            peak_pos_states = max(int(peak_pos_states), int(len(line_states)))
            peak_line_subset_options = max(
                int(peak_line_subset_options),
                int(len(line_transitions)),
            )
            next_line_states: Dict[int, int] = {}
            for packed_state, current_count in line_states.items():
                shifted_state = int(packed_state) >> int(line_end_shift)
                merge_state(next_line_states, int(shifted_state), int(current_count))
                for conflict_mask, next_write_mask, gain in line_transitions:
                    if int(packed_state) & int(conflict_mask):
                        continue
                    merge_state(
                        next_line_states,
                        int(shifted_state) | int(next_write_mask),
                        int(current_count) + int(gain),
                    )
            line_states = next_line_states
            peak_line_states = max(int(peak_line_states), int(len(line_states)))

        result = int(line_states.get(0, -10**9))
        if result < 0:
            raise _RectangleFrontierDPFallback(
                f"Rectangle frontier DP terminated with residual frontier for template {tpl}"
            )

        if cache_stats is not None:
            cache_stats["rect_dp_state_merges"] = int(
                cache_stats.get("rect_dp_state_merges", 0)
            ) + int(state_merges)
            cache_stats["rect_dp_peak_line_states"] = max(
                int(cache_stats.get("rect_dp_peak_line_states", 0)),
                int(peak_line_states),
            )
            cache_stats["rect_dp_peak_pos_states"] = max(
                int(cache_stats.get("rect_dp_peak_pos_states", 0)),
                int(peak_pos_states),
            )
            cache_stats["rect_dp_peak_line_subset_options"] = max(
                int(cache_stats.get("rect_dp_peak_line_subset_options", 0)),
                int(peak_line_subset_options),
            )
            cache_stats["rect_dp_compiled_signatures"] = int(
                len(_LOCAL_POWER_CAPACITY_RECT_DP_COMPILED_CACHE)
            )
            cache_stats["rect_dp_compiled_start_options"] = int(
                sum(
                    int(item.compiled_start_options)
                    for item in _LOCAL_POWER_CAPACITY_RECT_DP_COMPILED_CACHE.values()
                )
            )
            cache_stats["rect_dp_deduped_start_options"] = int(
                sum(
                    int(item.deduped_start_options)
                    for item in _LOCAL_POWER_CAPACITY_RECT_DP_COMPILED_CACHE.values()
                )
            )
            cache_stats["rect_dp_compiled_line_subsets"] = int(
                sum(
                    int(item.compiled_line_subsets)
                    for item in _LOCAL_POWER_CAPACITY_RECT_DP_COMPILED_CACHE.values()
                )
            )
        return int(result)

    def _solve_exact_local_power_capacity_manufacturing_6x4_mixed_cpsat(
        self,
        tpl: str,
        compact_signature: CompactLocalCapacitySignature,
        *,
        cache_stats: Optional[Dict[str, Any]] = None,
    ) -> int:
        if cache_stats is not None:
            cache_stats["m6x4_mixed_cpsat_evaluations"] = int(
                cache_stats.get("m6x4_mixed_cpsat_evaluations", 0)
            ) + 1
            cache_key = (str(tpl), compact_signature)
            if cache_key in _LOCAL_POWER_CAPACITY_M6X4_MIXED_CPSAT_DATA_CACHE:
                cache_stats["m6x4_mixed_cpsat_cache_hits"] = int(
                    cache_stats.get("m6x4_mixed_cpsat_cache_hits", 0)
                ) + 1

        if not self._is_manufacturing_6x4_mixed_signature(str(tpl), compact_signature):
            raise _Manufacturing6x4MixedCpSatFallback(
                f"Template-specialized manufacturing_6x4 mixed CP-SAT is unsupported for {tpl}"
            )

        compiled = self._compile_manufacturing_6x4_mixed_cpsat_data(
            str(tpl),
            compact_signature,
        )
        if not compiled.placements:
            return 0

        local_model = cp_model.CpModel()
        local_vars = [
            local_model.NewBoolVar(f"m6x4_mixed_cap__{tpl}__{idx}")
            for idx in range(len(compiled.placements))
        ]
        for terms in compiled.cell_to_placement_indices.values():
            if len(terms) > 1:
                local_model.Add(sum(local_vars[idx] for idx in terms) <= 1)
        local_model.Maximize(sum(local_vars))

        solver = cp_model.CpSolver()
        solver.parameters.num_search_workers = 8
        status = solver.Solve(local_model)
        if status != cp_model.OPTIMAL:
            raise _Manufacturing6x4MixedCpSatFallback(
                "manufacturing_6x4 mixed CP-SAT did not prove optimal: "
                f"{solver.StatusName(status)}"
            )
        return int(round(solver.ObjectiveValue()))

    def _solve_exact_local_power_capacity_rectangle_frontier_dp(
        self,
        tpl: str,
        compact_signature: CompactLocalCapacitySignature,
        *,
        scan_axis: Optional[str] = None,
        cache_stats: Optional[Dict[str, Any]] = None,
    ) -> int:
        normalized = self._normalize_rectangle_frontier_signature(str(tpl), compact_signature)
        if not normalized:
            return 0
        if len(normalized) <= 1:
            return int(len(normalized))

        row_frontier_bits, col_frontier_bits = self._rectangle_frontier_scan_stats(normalized)
        if scan_axis is None:
            scan_axis = "row" if row_frontier_bits <= col_frontier_bits else "column"
        if scan_axis not in {"row", "column"}:
            raise ValueError(f"Unsupported rectangle frontier scan_axis: {scan_axis}")

        compiled = self._compile_rectangle_frontier_dp(
            str(tpl),
            compact_signature,
            scan_axis=str(scan_axis),
        )
        if self._should_use_rectangle_frontier_dp_v4(compiled):
            return self._solve_exact_local_power_capacity_rectangle_frontier_dp_v4(
                str(tpl),
                compact_signature,
                scan_axis=scan_axis,
                compiled=compiled,
                cache_stats=cache_stats,
            )
        if self._is_manufacturing_6x4_mixed_signature(str(tpl), compact_signature):
            if cache_stats is not None:
                cache_stats["m6x4_mixed_cpsat_selected_cases"] = int(
                    cache_stats.get("m6x4_mixed_cpsat_selected_cases", 0)
                ) + 1
            try:
                return self._solve_exact_local_power_capacity_manufacturing_6x4_mixed_cpsat(
                    str(tpl),
                    compact_signature,
                    cache_stats=cache_stats,
                )
            except _Manufacturing6x4MixedCpSatFallback:
                if cache_stats is not None:
                    cache_stats["m6x4_mixed_cpsat_v3_fallbacks"] = int(
                        cache_stats.get("m6x4_mixed_cpsat_v3_fallbacks", 0)
                    ) + 1
        if cache_stats is not None:
            cache_stats["rect_dp_v3_fallbacks"] = int(
                cache_stats.get("rect_dp_v3_fallbacks", 0)
            ) + 1
        return self._solve_exact_local_power_capacity_rectangle_frontier_dp_v3(
            str(tpl),
            compact_signature,
            scan_axis=scan_axis,
            compiled=compiled,
            cache_stats=cache_stats,
        )

    def _solve_exact_local_power_capacity(
        self,
        tpl: str,
        signature: LocalCapacitySignature,
        *,
        compact_signature: Optional[CompactLocalCapacitySignature] = None,
        cache_stats: Optional[Dict[str, Any]] = None,
    ) -> int:
        if not signature:
            return 0

        legacy_key = (str(tpl), signature)
        cached = _LOCAL_POWER_CAPACITY_CACHE.get(legacy_key)
        if cached is not None:
            return int(cached)

        capacity: Optional[int] = None
        compact_key: Optional[Tuple[str, CompactLocalCapacitySignature]] = None
        if compact_signature is not None:
            compact_key = (str(tpl), compact_signature)
            rect_cached = _LOCAL_POWER_CAPACITY_RECT_DP_CACHE.get(compact_key)
            if rect_cached is not None:
                if cache_stats is not None:
                    cache_stats["rect_dp_cache_hits"] = int(
                        cache_stats.get("rect_dp_cache_hits", 0)
                    ) + 1
                _LOCAL_POWER_CAPACITY_CACHE[legacy_key] = int(rect_cached)
                return int(rect_cached)
            if cache_stats is not None:
                cache_stats["rect_dp_cache_misses"] = int(
                    cache_stats.get("rect_dp_cache_misses", 0)
                ) + 1
                cache_stats["rect_dp_evaluations"] = int(
                    cache_stats.get("rect_dp_evaluations", 0)
                ) + 1
            try:
                capacity = self._solve_exact_local_power_capacity_rectangle_frontier_dp(
                    str(tpl),
                    compact_signature,
                    cache_stats=cache_stats,
                )
                _LOCAL_POWER_CAPACITY_RECT_DP_CACHE[compact_key] = int(capacity)
            except _RectangleFrontierDPFallback:
                if cache_stats is not None:
                    cache_stats["bitset_fallbacks"] = int(
                        cache_stats.get("bitset_fallbacks", 0)
                    ) + 1

        if capacity is None:
            if cache_stats is not None:
                cache_stats["bitset_oracle_evaluations"] = int(
                    cache_stats.get("bitset_oracle_evaluations", 0)
                ) + 1
            try:
                capacity = self._solve_exact_local_power_capacity_bitset_mis(str(tpl), signature)
            except _BitsetLocalCapacityFallback:
                if cache_stats is not None:
                    cache_stats["cpsat_fallbacks"] = int(
                        cache_stats.get("cpsat_fallbacks", 0)
                    ) + 1
                capacity = self._solve_exact_local_power_capacity_cpsat(str(tpl), signature)

        if capacity is None:
            if cache_stats is not None:
                cache_stats["cpsat_fallbacks"] = int(
                    cache_stats.get("cpsat_fallbacks", 0)
                ) + 1
            capacity = self._solve_exact_local_power_capacity_cpsat(str(tpl), signature)

        _LOCAL_POWER_CAPACITY_CACHE[legacy_key] = int(capacity)
        return int(capacity)

    def _exact_local_power_capacity_coefficients(
        self,
        powered_template_demands: Mapping[str, int],
        cache_stats: Dict[str, Any],
    ) -> Dict[str, Dict[int, int]]:
        coeff_by_template_and_pole: Dict[str, Dict[int, int]] = {}
        shell_pair_items = sorted(self._power_pole_pose_indices_by_shell_pair.items())
        template_order = sorted(str(tpl) for tpl in powered_template_demands)

        cache_stats.setdefault("raw_pole_evaluations", 0)
        cache_stats.setdefault("coefficient_source", "exact_rect_dp_cache_v7")
        cache_stats.setdefault("shell_pair_count", len(shell_pair_items))
        cache_stats.setdefault("signature_class_count", 0)
        cache_stats.setdefault("signature_class_evaluations", 0)
        cache_stats.setdefault("compact_signature_class_count", 0)
        cache_stats.setdefault("compact_signature_class_evaluations", 0)
        cache_stats.setdefault("compact_signature_hits", 0)
        cache_stats.setdefault("compact_signature_misses", 0)
        cache_stats.setdefault("rect_dp_evaluations", 0)
        cache_stats.setdefault("rect_dp_cache_hits", 0)
        cache_stats.setdefault("rect_dp_cache_misses", 0)
        cache_stats.setdefault("rect_dp_state_merges", 0)
        cache_stats.setdefault("rect_dp_peak_line_states", 0)
        cache_stats.setdefault("rect_dp_peak_pos_states", 0)
        cache_stats.setdefault("rect_dp_compiled_signatures", 0)
        cache_stats.setdefault("rect_dp_compiled_start_options", 0)
        cache_stats.setdefault("rect_dp_deduped_start_options", 0)
        cache_stats.setdefault("rect_dp_compiled_line_subsets", 0)
        cache_stats.setdefault("rect_dp_peak_line_subset_options", 0)
        cache_stats.setdefault("rect_dp_v3_fallbacks", 0)
        cache_stats.setdefault("m6x4_mixed_cpsat_evaluations", 0)
        cache_stats.setdefault("m6x4_mixed_cpsat_cache_hits", 0)
        cache_stats.setdefault("m6x4_mixed_cpsat_selected_cases", 0)
        cache_stats.setdefault("m6x4_mixed_cpsat_v3_fallbacks", 0)
        cache_stats.setdefault("bitset_oracle_evaluations", 0)
        cache_stats.setdefault("bitset_fallbacks", 0)
        cache_stats.setdefault("cpsat_fallbacks", 0)
        cache_stats.setdefault("oracle", "rectangle_frontier_dp_v4")
        shell_pair_evaluations = 0
        for tpl in template_order:
            coeff_by_template_and_pole[str(tpl)] = {}
            signature_classes = self._build_local_power_capacity_signature_classes(str(tpl))
            compact_signature_classes = (
                self._power_pole_pose_indices_by_template_compact_capacity_signature.get(
                    str(tpl),
                    {},
                )
            )
            legacy_by_compact = (
                self._legacy_local_power_capacity_signature_by_template_compact_signature.get(
                    str(tpl),
                    {},
                )
            )
            cache_stats["signature_class_count"] += int(len(signature_classes))
            cache_stats["compact_signature_class_count"] += int(len(compact_signature_classes))
            for _shell_pair, pose_indices in shell_pair_items:
                shell_pair_signatures = {
                    self._local_power_capacity_signature(str(tpl), int(pole_idx))
                    for pole_idx in pose_indices
                }
                shell_pair_evaluations += int(len(shell_pair_signatures))
                cache_stats["raw_pole_evaluations"] += int(len(pose_indices))
            for compact_signature, grouped_pose_indices in sorted(compact_signature_classes.items()):
                cache_stats["pole_template_evaluations"] += 1
                legacy_signature = legacy_by_compact.get(compact_signature)
                if legacy_signature is None:
                    raise RuntimeError(
                        f"Missing legacy local-capacity signature for compact signature in template {tpl}"
                    )
                cache_key = (str(tpl), compact_signature)
                coeff = _LOCAL_POWER_CAPACITY_COMPACT_CACHE.get(cache_key)
                if coeff is None:
                    cache_stats["signature_misses"] += 1
                    cache_stats["signature_class_evaluations"] += 1
                    cache_stats["compact_signature_misses"] += 1
                    cache_stats["compact_signature_class_evaluations"] += 1
                    coeff = self._solve_exact_local_power_capacity(
                        str(tpl),
                        legacy_signature,
                        compact_signature=compact_signature,
                        cache_stats=cache_stats,
                    )
                    _LOCAL_POWER_CAPACITY_COMPACT_CACHE[cache_key] = int(coeff)
                else:
                    cache_stats["signature_hits"] += 1
                    cache_stats["compact_signature_hits"] += 1
                    _LOCAL_POWER_CAPACITY_CACHE.setdefault(
                        (str(tpl), legacy_signature),
                        int(coeff),
                    )
                for pole_idx in grouped_pose_indices:
                    coeff_by_template_and_pole[str(tpl)][int(pole_idx)] = int(coeff)

        cache_stats["signature_count"] = int(len(_LOCAL_POWER_CAPACITY_COMPACT_CACHE))
        cache_stats["rect_dp_compiled_signatures"] = int(
            len(_LOCAL_POWER_CAPACITY_RECT_DP_COMPILED_CACHE)
        )
        cache_stats["rect_dp_compiled_start_options"] = int(
            sum(
                int(item.compiled_start_options)
                for item in _LOCAL_POWER_CAPACITY_RECT_DP_COMPILED_CACHE.values()
            )
        )
        cache_stats["rect_dp_deduped_start_options"] = int(
            sum(
                int(item.deduped_start_options)
                for item in _LOCAL_POWER_CAPACITY_RECT_DP_COMPILED_CACHE.values()
            )
        )
        cache_stats["rect_dp_compiled_line_subsets"] = int(
            sum(
                int(item.compiled_line_subsets)
                for item in _LOCAL_POWER_CAPACITY_RECT_DP_COMPILED_CACHE.values()
            )
        )
        cache_stats["rect_dp_peak_line_subset_options"] = int(
            max(
                [0]
                + [
                    int(item.peak_line_subset_options)
                    for item in _LOCAL_POWER_CAPACITY_RECT_DP_COMPILED_CACHE.values()
                ]
            )
        )
        self._update_exact_precompute_profile(
            power_capacity_shell_pairs=int(len(shell_pair_items)),
            power_capacity_shell_pair_evaluations=int(shell_pair_evaluations),
            power_capacity_signature_classes=int(cache_stats["signature_class_count"]),
            power_capacity_signature_class_evaluations=int(
                cache_stats["signature_class_evaluations"]
            ),
            power_capacity_compact_signature_classes=int(
                cache_stats["compact_signature_class_count"]
            ),
            power_capacity_compact_signature_evaluations=int(
                cache_stats["compact_signature_class_evaluations"]
            ),
            power_capacity_compact_signature_cache_hits=int(
                cache_stats["compact_signature_hits"]
            ),
            power_capacity_compact_signature_cache_misses=int(
                cache_stats["compact_signature_misses"]
            ),
            power_capacity_rect_dp_evaluations=int(cache_stats["rect_dp_evaluations"]),
            power_capacity_rect_dp_cache_hits=int(cache_stats["rect_dp_cache_hits"]),
            power_capacity_rect_dp_cache_misses=int(cache_stats["rect_dp_cache_misses"]),
            power_capacity_rect_dp_state_merges=int(cache_stats["rect_dp_state_merges"]),
            power_capacity_rect_dp_peak_line_states=int(
                cache_stats["rect_dp_peak_line_states"]
            ),
            power_capacity_rect_dp_peak_pos_states=int(
                cache_stats["rect_dp_peak_pos_states"]
            ),
            power_capacity_rect_dp_compiled_signatures=int(
                cache_stats["rect_dp_compiled_signatures"]
            ),
            power_capacity_rect_dp_compiled_start_options=int(
                cache_stats["rect_dp_compiled_start_options"]
            ),
            power_capacity_rect_dp_deduped_start_options=int(
                cache_stats["rect_dp_deduped_start_options"]
            ),
            power_capacity_rect_dp_compiled_line_subsets=int(
                cache_stats["rect_dp_compiled_line_subsets"]
            ),
            power_capacity_rect_dp_peak_line_subset_options=int(
                cache_stats["rect_dp_peak_line_subset_options"]
            ),
            power_capacity_rect_dp_v3_fallbacks=int(
                cache_stats["rect_dp_v3_fallbacks"]
            ),
            power_capacity_m6x4_mixed_cpsat_evaluations=int(
                cache_stats["m6x4_mixed_cpsat_evaluations"]
            ),
            power_capacity_m6x4_mixed_cpsat_cache_hits=int(
                cache_stats["m6x4_mixed_cpsat_cache_hits"]
            ),
            power_capacity_m6x4_mixed_cpsat_selected_cases=int(
                cache_stats["m6x4_mixed_cpsat_selected_cases"]
            ),
            power_capacity_m6x4_mixed_cpsat_v3_fallbacks=int(
                cache_stats["m6x4_mixed_cpsat_v3_fallbacks"]
            ),
            power_capacity_bitset_oracle_evaluations=int(
                cache_stats["bitset_oracle_evaluations"]
            ),
            power_capacity_bitset_fallbacks=int(cache_stats["bitset_fallbacks"]),
            power_capacity_cpsat_fallbacks=int(cache_stats["cpsat_fallbacks"]),
            power_capacity_oracle=str(cache_stats["oracle"]),
            power_capacity_raw_pole_evaluations=int(cache_stats["raw_pole_evaluations"]),
        )
        return coeff_by_template_and_pole

    def _exact_local_power_capacity_coefficient(
        self,
        tpl: str,
        pole_idx: int,
        cache_stats: Dict[str, Any],
    ) -> int:
        coeff_by_template_and_pole = self._exact_local_power_capacity_coefficients(
            {str(tpl): 1},
            cache_stats,
        )
        return int(coeff_by_template_and_pole[str(tpl)][int(pole_idx)])

    def _candidate_pose_indices_for_group(self, group: Mapping[str, Any]) -> List[int]:
        tpl = str(group["facility_type"])
        cached = self._candidate_pose_indices_by_template.get(tpl)
        if cached is not None:
            return list(cached)
        pool = self.facility_pools.get(tpl, [])
        if not pool:
            return []

        candidate_indices = list(range(len(pool)))
        if tpl in self._powered_templates and tpl != "power_pole":
            pose_coverers = self._power_coverers_by_template_pose.get(tpl, {})
            candidate_indices = [
                pose_idx
                for pose_idx in candidate_indices
                if pose_coverers.get(pose_idx, [])
            ]
        candidate_indices.sort(key=lambda pose_idx: self._pose_sort_key(tpl, pose_idx))
        self._candidate_pose_indices_by_template[tpl] = list(candidate_indices)
        return list(candidate_indices)

    def build_greedy_solution_hint(self) -> Dict[str, int]:
        if not self.exact_mode:
            self.build_stats["greedy_hint"] = {
                "supported": False,
                "complete": False,
                "hinted_groups": 0,
                "hinted_instances": 0,
                "skipped_groups": [],
                "used_power_coverage_filter": False,
                "reason": "exact-safe greedy warm start only runs in certified_exact mode",
            }
            return {}

        if not self._mandatory_groups:
            self.build_stats["greedy_hint"] = {
                "supported": True,
                "complete": True,
                "hinted_groups": 0,
                "hinted_instances": 0,
                "skipped_groups": [],
                "used_power_coverage_filter": False,
                "reason": "no mandatory exact groups available for warm start",
            }
            return {}

        candidates_by_group: Dict[str, List[int]] = {}
        used_power_coverage_filter = False
        for group in self._mandatory_groups:
            group_id = str(group["group_id"])
            tpl = str(group["facility_type"])
            if tpl in self._powered_templates and tpl != "power_pole":
                used_power_coverage_filter = True
            candidates_by_group[group_id] = self._candidate_pose_indices_for_group(group)

        ordered_groups = sorted(
            self._mandatory_groups,
            key=lambda group: (
                len(candidates_by_group[str(group["group_id"])]),
                str(group["facility_type"]),
                str(group["group_id"]),
            ),
        )

        solution_hint: Dict[str, int] = {}
        committed_cells: Set[Tuple[int, int]] = set()
        hinted_groups = 0
        skipped_groups: List[str] = []

        for group in ordered_groups:
            group_id = str(group["group_id"])
            tpl = str(group["facility_type"])
            required_count = int(group["count"])

            trial_cells = set(committed_cells)
            chosen_pose_indices: List[int] = []
            for pose_idx in candidates_by_group[group_id]:
                pose_cells = self._pose_cells(tpl, pose_idx)
                if trial_cells.intersection(pose_cells):
                    continue
                trial_cells.update(pose_cells)
                chosen_pose_indices.append(int(pose_idx))
                if len(chosen_pose_indices) == required_count:
                    break

            if len(chosen_pose_indices) != required_count:
                skipped_groups.append(group_id)
                continue

            committed_cells = trial_cells
            hinted_groups += 1
            for instance_id, pose_idx in zip(list(group["instance_ids"]), chosen_pose_indices):
                solution_hint[str(instance_id)] = int(pose_idx)

        hinted_instances = len(solution_hint)
        greedy_stats: Dict[str, Any] = {
            "supported": True,
            "complete": hinted_groups == len(self._mandatory_groups),
            "hinted_groups": hinted_groups,
            "hinted_instances": hinted_instances,
            "skipped_groups": skipped_groups,
            "used_power_coverage_filter": used_power_coverage_filter,
        }
        if hinted_instances == 0:
            greedy_stats["reason"] = "no exact-safe greedy placements found"

        self.build_stats["greedy_hint"] = greedy_stats
        return solution_hint

    def _clear_solution_hints(self) -> None:
        if hasattr(self.model, "ClearHints"):
            self.model.ClearHints()
            return
        proto = self.model.Proto()
        del proto.solution_hint.vars[:]
        del proto.solution_hint.values[:]

    def _hint_var_for_key(self, solution_key: str, pose_idx: int) -> Optional[cp_model.IntVar]:
        if solution_key in self._group_id_by_instance:
            group_id = self._group_id_by_instance[solution_key]
            return self.z_vars.get(group_id, {}).get(int(pose_idx))
        tpl = self._infer_optional_template_from_solution_id(solution_key)
        if tpl is not None:
            return self.optional_pose_vars.get(tpl, {}).get(int(pose_idx))
        return None

    def solve(
        self,
        time_limit_seconds: float = 60.0,
        solution_hint: Optional[Mapping[str, int]] = None,
        known_feasible_hint: bool = False,
    ) -> int:
        if not self._built:
            self.build()

        self._clear_solution_hints()
        hinted = 0
        if self.exact_mode and self._coordinate_delegate is not None and solution_hint:
            hinted = self._coordinate_delegate.apply_solution_hint(solution_hint)
        elif solution_hint:
            for key, pose_idx in solution_hint.items():
                var = self._hint_var_for_key(str(key), int(pose_idx))
                if var is None:
                    continue
                self.model.AddHint(var, 1)
                hinted += 1

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(time_limit_seconds)
        solver.parameters.num_search_workers = 8
        if self.exact_mode:
            solver.parameters.search_branching = cp_model.FIXED_SEARCH
            solver.parameters.symmetry_level = max(int(solver.parameters.symmetry_level), 3)
            solver.parameters.cp_model_probing_level = max(
                int(solver.parameters.cp_model_probing_level),
                3,
            )
            solver.parameters.hint_conflict_limit = max(
                int(solver.parameters.hint_conflict_limit),
                1000,
            )
        status = solver.Solve(self.model)

        self._solver = solver
        self._status = status
        self._last_solution = None
        self.build_stats["last_solve"] = {
            "status": solver.StatusName(status),
            "wall_time": solver.WallTime(),
            "hinted_literals": hinted,
            "known_feasible_hint": bool(known_feasible_hint),
            "search_profile": str(
                self.build_stats.get("search_guidance", {}).get("profile", "default_automatic")
            ),
            "search_branching": str(solver.parameters.search_branching),
        }
        return status

    def extract_solution(self) -> Dict[str, Any]:
        if self._solver is None or self._status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return {}
        if self._last_solution is not None:
            return dict(self._last_solution)
        if self.exact_mode and self._coordinate_delegate is not None:
            self._last_solution = dict(self._coordinate_delegate.extract_solution())
            return dict(self._last_solution)

        solution: Dict[str, Any] = {}

        for group in self._mandatory_groups:
            group_id = group["group_id"]
            tpl = group["facility_type"]
            operation_type = group["operation_type"]
            selected_pose_indices = sorted(
                pose_idx
                for pose_idx, var in self.z_vars[group_id].items()
                if self._solver.Value(var) == 1
            )
            for instance_id, pose_idx in zip(sorted(group["instance_ids"]), selected_pose_indices):
                pose = self.facility_pools[tpl][pose_idx]
                solution[instance_id] = {
                    "instance_id": instance_id,
                    "facility_type": tpl,
                    "operation_type": operation_type,
                    "pose_idx": pose_idx,
                    "pose_id": pose["pose_id"],
                    "anchor": dict(pose["anchor"]),
                    "is_mandatory": True,
                    "bound_type": "exact",
                    "solve_mode": self.solve_mode,
                }

        for tpl, vars_by_pose in self.optional_pose_vars.items():
            operation_type = POSE_LEVEL_OPTIONAL_OPERATIONS[tpl]
            for pose_idx, var in vars_by_pose.items():
                if self._solver.Value(var) != 1:
                    continue
                pose = self.facility_pools[tpl][pose_idx]
                synthetic_id = f"pose_optional::{tpl}::{pose['pose_id']}"
                solution[synthetic_id] = {
                    "instance_id": synthetic_id,
                    "facility_type": tpl,
                    "operation_type": operation_type,
                    "pose_idx": pose_idx,
                    "pose_id": pose["pose_id"],
                    "anchor": dict(pose["anchor"]),
                    "is_mandatory": False,
                    "bound_type": "exact_pose_optional" if self.exact_mode else "exploratory_pose_optional",
                    "solve_mode": self.solve_mode,
                }

        self._last_solution = dict(solution)
        return solution

    def _infer_optional_template_from_solution_id(self, solution_id: str) -> Optional[str]:
        if solution_id.startswith("pose_optional::power_pole::"):
            return "power_pole"
        if solution_id.startswith("pose_optional::protocol_storage_box::"):
            return "protocol_storage_box"
        if solution_id.startswith("power_pole_"):
            return "power_pole"
        if solution_id.startswith("protocol_box_") or solution_id.startswith("protocol_storage_box_"):
            return "protocol_storage_box"
        return None

    def add_benders_cut(self, conflict_set: Mapping[str, int]) -> bool:
        if self.exact_mode and self._coordinate_delegate is not None:
            return self._coordinate_delegate.add_benders_cut(conflict_set)
        literals: List[cp_model.IntVar] = []
        seen_names: Set[str] = set()
        for solution_id, pose_idx in conflict_set.items():
            var: Optional[cp_model.IntVar] = None
            if solution_id in self._group_id_by_instance:
                group_id = self._group_id_by_instance[solution_id]
                var = self.z_vars.get(group_id, {}).get(int(pose_idx))
            else:
                tpl = self._infer_optional_template_from_solution_id(str(solution_id))
                if tpl is not None:
                    var = self.optional_pose_vars.get(tpl, {}).get(int(pose_idx))
            if var is None:
                continue
            name = var.Name()
            if name in seen_names:
                continue
            seen_names.add(name)
            literals.append(var)

        if not literals:
            return False
        # The Benders Cut: sum of conflicting z_vars <= N - 1
        self.model.Add(sum(literals) <= len(literals) - 1)
        self._last_solution = None
        return True


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent.parent
    instances, pools, rules = load_project_data(project_root)
    model = MasterPlacementModel(instances, pools, rules, ghost_rect=(6, 6))
    model.build()
    status = model.solve(time_limit_seconds=5.0)
    print("status=", status)
