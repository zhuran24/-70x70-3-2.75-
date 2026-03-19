from __future__ import annotations

import copy
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, DefaultDict, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from ortools.sat.python import cp_model

from src.preprocess.operation_profiles import get_operation_port_profile


ModeToken = Tuple[str, str]
PoseTuple = Tuple[int, int, int]


@dataclass(frozen=True)
class ModeRectDomain:
    mode_id: int
    orientation: str
    port_mode: str
    x_min: int
    x_max: int
    y_min: int
    y_max: int
    pose_count: int


@dataclass(frozen=True)
class SignatureRegion:
    mode_id: int
    x_min: int
    x_max: int
    y_min: int
    y_max: int


@dataclass
class CoordinateSlotSpec:
    key: str
    template: str
    slot_kind: str
    slot_index: int
    dims: Tuple[int, int]
    candidate_pose_count: int
    tuple_to_pose_idx: Mapping[PoseTuple, int]
    mode_rect_domains: Mapping[int, ModeRectDomain]
    allowed_tuples: Tuple[PoseTuple, ...] = field(default_factory=tuple)
    use_domain_table: bool = False
    signature_id_to_bucket_id: Mapping[int, str] = field(default_factory=dict)
    family_id_to_family_name: Mapping[int, str] = field(default_factory=dict)
    active: Optional[cp_model.IntVar] = None
    x: Optional[cp_model.IntVar] = None
    y: Optional[cp_model.IntVar] = None
    mode: Optional[cp_model.IntVar] = None
    order_key: Optional[cp_model.IntVar] = None
    signature: Optional[cp_model.IntVar] = None
    family: Optional[cp_model.IntVar] = None
    x_interval: Optional[Any] = None
    y_interval: Optional[Any] = None


class CoordinateExactMasterDelegate:
    def __init__(self, owner: Any):
        self.owner = owner
        self.model = owner.model
        self.grid_w = int(owner.grid_w)
        self.grid_h = int(owner.grid_h)
        self.master_representation = "coordinate_exact_v2"

        self._template_mode_tokens: Dict[str, List[ModeToken]] = {}
        self._template_mode_id_by_token: Dict[str, Dict[ModeToken, int]] = {}
        self._template_pose_idx_by_tuple: Dict[str, Dict[PoseTuple, int]] = {}
        self._template_pose_tuple_by_idx: Dict[str, Dict[int, PoseTuple]] = {}
        self._template_signature_bucket_id_by_int: Dict[str, Dict[int, str]] = {}
        self._template_mode_literals: Dict[str, int] = {}
        self._template_full_mode_rect_domains: Dict[str, Dict[int, ModeRectDomain]] = {}
        self._template_uses_domain_table: Dict[str, bool] = {}

        self._mandatory_group_mode_rect_domains: Dict[str, Dict[int, ModeRectDomain]] = {}
        self._required_optional_mode_rect_domains: Dict[str, Dict[int, ModeRectDomain]] = {}
        self._mandatory_group_bucket_regions: Dict[str, Dict[str, List[SignatureRegion]]] = {}
        self._required_optional_bucket_regions: Dict[str, Dict[str, List[SignatureRegion]]] = {}
        self._mandatory_group_pose_counts: Dict[str, int] = {}
        self._required_optional_pose_counts: Dict[str, int] = {}
        self._mandatory_group_uses_domain_table: Dict[str, bool] = {}
        self._required_optional_uses_domain_table: Dict[str, bool] = {}
        self._mandatory_group_uses_signature_table: Dict[str, bool] = {}
        self._required_optional_uses_signature_table: Dict[str, bool] = {}

        self._power_pole_family_name_by_int: Dict[int, str] = {}
        self._power_pole_family_coefficients: Dict[str, Dict[str, int]] = {}
        self._power_pole_family_id_by_pose_idx: Dict[int, int] = {}
        self._power_pole_family_pose_counts: Dict[str, int] = {}
        self._power_pole_family_order: List[str] = []
        self._power_pole_use_shell_lookup = True
        self._power_pole_family_tuple_rows: List[Tuple[int, int, int, int]] = []
        self._power_pole_shell_lookup_rows: List[Tuple[int, int, int]] = []
        self._power_pole_shell_lookup_pairs: List[Dict[str, Any]] = []
        self._power_pole_slot_upper_bound = 0
        self._power_capacity_cache_stats: Dict[str, Any] = {
            "scope": "process_memory",
            "signature_hits": 0,
            "signature_misses": 0,
            "signature_count": 0,
            "pole_template_evaluations": 0,
            "signature_class_count": 0,
            "signature_class_evaluations": 0,
            "raw_pole_evaluations": 0,
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
            "m6x4_mixed_cpsat_evaluations": 0,
            "m6x4_mixed_cpsat_cache_hits": 0,
            "m6x4_mixed_cpsat_selected_cases": 0,
            "m6x4_mixed_cpsat_v3_fallbacks": 0,
            "bitset_oracle_evaluations": 0,
            "bitset_fallbacks": 0,
            "cpsat_fallbacks": 0,
            "oracle": "rectangle_frontier_dp_v4",
            "coefficient_source": "exact_rect_dp_cache_v7",
            "shell_pair_count": 0,
        }
        self._power_capacity_coeff_stats: Dict[str, Any] = {}

        self.mandatory_slots: Dict[str, List[CoordinateSlotSpec]] = {}
        self.required_optional_slots: Dict[str, List[CoordinateSlotSpec]] = {}
        self.residual_optional_slots: Dict[str, List[CoordinateSlotSpec]] = {}

        self.mandatory_signature_count_vars: Dict[str, Dict[str, cp_model.IntVar]] = {}
        self.required_optional_signature_count_vars: Dict[str, Dict[str, cp_model.IntVar]] = {}
        self.power_pole_family_count_vars: Dict[str, cp_model.IntVar] = {}

        self._mandatory_signature_membership: Dict[str, Dict[str, List[cp_model.IntVar]]] = {}
        self._required_optional_signature_membership: Dict[str, Dict[str, List[cp_model.IntVar]]] = {}
        self._power_pole_family_membership: Dict[str, List[cp_model.IntVar]] = {}

        self._core_x_intervals: List[Any] = []
        self._core_y_intervals: List[Any] = []
        self._ghost_x_intervals: List[Any] = []
        self._ghost_y_intervals: List[Any] = []
        self._slot_binding: Dict[str, Dict[str, int]] = {}
        self._interval_binding: Dict[str, Tuple[int, int]] = {}
        self._domain_table_row_count = 0

        self._prepare_template_domains()
        self._prepare_signature_maps()
        self._prepare_power_pole_families()
        self._prepare_slot_specs()

    def _pose_mode_token(self, pose: Mapping[str, Any]) -> ModeToken:
        params = dict(pose.get("pose_params", {}))
        return (str(params.get("orientation", "")), str(params.get("port_mode", "")))

    def _rect_points(
        self,
        x_min: int,
        x_max: int,
        y_min: int,
        y_max: int,
    ) -> Set[Tuple[int, int]]:
        if x_min > x_max or y_min > y_max:
            return set()
        return {
            (int(x_val), int(y_val))
            for x_val in range(int(x_min), int(x_max) + 1)
            for y_val in range(int(y_min), int(y_max) + 1)
        }

    def _is_rectangular_set(self, cells: Set[Tuple[int, int]]) -> bool:
        if not cells:
            return False
        xs = sorted({int(x_val) for x_val, _ in cells})
        ys = sorted({int(y_val) for _, y_val in cells})
        return cells == self._rect_points(min(xs), max(xs), min(ys), max(ys))

    def _bounding_region(self, mode_id: int, cells: Set[Tuple[int, int]]) -> SignatureRegion:
        xs = sorted({int(x_val) for x_val, _ in cells})
        ys = sorted({int(y_val) for _, y_val in cells})
        return SignatureRegion(
            mode_id=int(mode_id),
            x_min=int(min(xs)),
            x_max=int(max(xs)),
            y_min=int(min(ys)),
            y_max=int(max(ys)),
        )

    def _build_mode_rect_domains_from_pose_indices(
        self,
        tpl: str,
        pose_indices: Iterable[int],
        *,
        label: str,
    ) -> Tuple[Dict[int, ModeRectDomain], bool]:
        cells_by_mode: DefaultDict[int, Set[Tuple[int, int]]] = defaultdict(set)
        for pose_idx in pose_indices:
            pose_tuple = self._template_pose_tuple_by_idx[tpl].get(int(pose_idx))
            if pose_tuple is None:
                continue
            x_val, y_val, mode_id = pose_tuple
            cells_by_mode[int(mode_id)].add((int(x_val), int(y_val)))

        mode_rect_domains: Dict[int, ModeRectDomain] = {}
        use_domain_table = False
        for mode_id, cells in sorted(cells_by_mode.items()):
            xs = sorted({int(x_val) for x_val, _ in cells})
            ys = sorted({int(y_val) for _, y_val in cells})
            if xs != list(range(min(xs), max(xs) + 1)) or ys != list(range(min(ys), max(ys) + 1)):
                use_domain_table = True
            full_rect = self._rect_points(min(xs), max(xs), min(ys), max(ys))
            if cells != full_rect:
                use_domain_table = True
            orientation, port_mode = self._template_mode_tokens[tpl][int(mode_id)]
            mode_rect_domains[int(mode_id)] = ModeRectDomain(
                mode_id=int(mode_id),
                orientation=str(orientation),
                port_mode=str(port_mode),
                x_min=int(min(xs)),
                x_max=int(max(xs)),
                y_min=int(min(ys)),
                y_max=int(max(ys)),
                pose_count=int(len(cells)),
            )
        return mode_rect_domains, bool(use_domain_table)

    def _exact_templates_for_coordinate_master(self) -> List[str]:
        pose_level_optional_templates = {"power_pole", "protocol_storage_box"}
        templates: Set[str] = {
            str(group["facility_type"]) for group in self.owner._mandatory_groups
        }
        templates.update(
            str(tpl)
            for tpl, count in self.owner._exact_required_pose_optional_counts.items()
            if int(count) > 0
        )
        templates.update(
            str(tpl)
            for tpl in pose_level_optional_templates
            if str(tpl) in self.owner.facility_pools
            and self.owner.facility_pools.get(str(tpl))
        )
        return sorted(
            str(tpl) for tpl in templates if str(tpl) in self.owner.facility_pools
        )

    def _residual_optional_slot_upper_bound(self, tpl: str) -> int:
        tpl = str(tpl)
        if tpl == "power_pole":
            return int(self._power_pole_slot_upper_bound)
        return int(self.owner._certified_optional_slot_upper_bound(str(tpl)))

    def _prepare_template_domains(self) -> None:
        for tpl in self._exact_templates_for_coordinate_master():
            pool = list(self.owner.facility_pools.get(str(tpl), []))
            mode_tokens = sorted({self._pose_mode_token(pose) for pose in pool}) or [("", "")]
            mode_id_by_token = {token: idx for idx, token in enumerate(mode_tokens)}
            tuple_to_pose_idx: Dict[PoseTuple, int] = {}
            pose_tuple_by_idx: Dict[int, PoseTuple] = {}
            for pose_idx, pose in enumerate(pool):
                anchor = dict(pose.get("anchor", {}))
                pose_tuple = (
                    int(anchor.get("x", 0)),
                    int(anchor.get("y", 0)),
                    int(mode_id_by_token[self._pose_mode_token(pose)]),
                )
                if pose_tuple in tuple_to_pose_idx:
                    raise ValueError(f"Duplicate coordinate pose key for {tpl}: {pose_tuple}")
                tuple_to_pose_idx[pose_tuple] = int(pose_idx)
                pose_tuple_by_idx[int(pose_idx)] = pose_tuple
            self._template_mode_tokens[tpl] = mode_tokens
            self._template_mode_id_by_token[tpl] = mode_id_by_token
            self._template_pose_idx_by_tuple[tpl] = tuple_to_pose_idx
            self._template_pose_tuple_by_idx[tpl] = pose_tuple_by_idx
            self._template_mode_literals[tpl] = max(1, len(mode_tokens))
            domains, uses_domain_table = self._build_mode_rect_domains_from_pose_indices(
                tpl,
                range(len(pool)),
                label=f"template::{tpl}",
            )
            self._template_full_mode_rect_domains[tpl] = domains
            self._template_uses_domain_table[tpl] = bool(uses_domain_table)

    def _build_bucket_regions(
        self,
        tpl: str,
        bucket_defs: Sequence[Mapping[str, Any]],
        mode_rect_domains: Mapping[int, ModeRectDomain],
        allowed_pose_indices: Optional[Set[int]] = None,
    ) -> Dict[str, List[SignatureRegion]]:
        bucket_regions: Dict[str, List[SignatureRegion]] = {}
        self._template_signature_bucket_id_by_int.setdefault(tpl, {})
        expected_pose_indices: Set[int]
        if allowed_pose_indices is None:
            expected_pose_indices = set(range(len(self.owner.facility_pools.get(str(tpl), []))))
        else:
            expected_pose_indices = {int(pose_idx) for pose_idx in allowed_pose_indices}
        covered_pose_indices: Set[int] = set()
        for signature_idx, bucket in enumerate(bucket_defs):
            bucket_id = str(bucket["bucket_id"])
            self._template_signature_bucket_id_by_int[tpl][int(signature_idx)] = bucket_id
            cells_by_mode: DefaultDict[int, Set[Tuple[int, int]]] = defaultdict(set)
            for pose_idx in bucket.get("pose_indices", []):
                pose_idx = int(pose_idx)
                if allowed_pose_indices is not None and pose_idx not in allowed_pose_indices:
                    continue
                if pose_idx in covered_pose_indices:
                    raise ValueError(
                        f"Overlapping signature bucket coverage for {tpl}: pose_idx={pose_idx} "
                        f"appears in multiple buckets"
                    )
                covered_pose_indices.add(int(pose_idx))
                pose_tuple = self._template_pose_tuple_by_idx[tpl].get(int(pose_idx))
                if pose_tuple is None:
                    continue
                x_val, y_val, mode_id = pose_tuple
                if int(mode_id) not in mode_rect_domains:
                    continue
                cells_by_mode[int(mode_id)].add((int(x_val), int(y_val)))

            regions: List[SignatureRegion] = []
            for mode_id, domain in sorted(mode_rect_domains.items()):
                bucket_cells = cells_by_mode.get(int(mode_id), set())
                if not bucket_cells:
                    continue
                mode_regions = self._bucket_region_candidates_for_mode(
                    int(mode_id),
                    domain,
                    bucket_cells,
                )
                if mode_regions is None:
                    raise ValueError(
                        f"Unsupported compact signature geometry for {tpl} bucket={bucket_id} mode={mode_id}"
                    )
                regions.extend(mode_regions)
            bucket_regions[bucket_id] = regions
        missing_pose_indices = sorted(expected_pose_indices - covered_pose_indices)
        if missing_pose_indices:
            raise ValueError(
                f"Incomplete signature bucket coverage for {tpl}: "
                f"missing {len(missing_pose_indices)} pose(s), first={missing_pose_indices[:5]}"
            )
        return bucket_regions

    def _bucket_region_candidates_for_mode(
        self,
        mode_id: int,
        domain: ModeRectDomain,
        bucket_cells: Set[Tuple[int, int]],
    ) -> Optional[List[SignatureRegion]]:
        full_cells = self._rect_points(domain.x_min, domain.x_max, domain.y_min, domain.y_max)
        if bucket_cells == full_cells:
            return [self._bounding_region(mode_id, bucket_cells)]

        if self._is_rectangular_set(bucket_cells):
            return [self._bounding_region(mode_id, bucket_cells)]

        width = int(domain.x_max - domain.x_min + 1)
        height = int(domain.y_max - domain.y_min + 1)

        for thickness in range(1, (width // 2) + 1):
            left = self._rect_points(domain.x_min, domain.x_min + thickness - 1, domain.y_min, domain.y_max)
            right = self._rect_points(domain.x_max - thickness + 1, domain.x_max, domain.y_min, domain.y_max)
            if bucket_cells == left | right:
                return [
                    SignatureRegion(mode_id, domain.x_min, domain.x_min + thickness - 1, domain.y_min, domain.y_max),
                    SignatureRegion(mode_id, domain.x_max - thickness + 1, domain.x_max, domain.y_min, domain.y_max),
                ]

        for thickness in range(1, (height // 2) + 1):
            bottom = self._rect_points(domain.x_min, domain.x_max, domain.y_min, domain.y_min + thickness - 1)
            top = self._rect_points(domain.x_min, domain.x_max, domain.y_max - thickness + 1, domain.y_max)
            if bucket_cells == bottom | top:
                return [
                    SignatureRegion(mode_id, domain.x_min, domain.x_max, domain.y_min, domain.y_min + thickness - 1),
                    SignatureRegion(mode_id, domain.x_min, domain.x_max, domain.y_max - thickness + 1, domain.y_max),
                ]

        max_ring_thickness = max(0, min(width, height) // 2)
        for thickness in range(1, max_ring_thickness + 1):
            inner = self._rect_points(
                domain.x_min + thickness,
                domain.x_max - thickness,
                domain.y_min + thickness,
                domain.y_max - thickness,
            )
            ring = full_cells - inner
            if bucket_cells != ring:
                continue
            regions: List[SignatureRegion] = [
                SignatureRegion(mode_id, domain.x_min, domain.x_max, domain.y_min, domain.y_min + thickness - 1),
                SignatureRegion(mode_id, domain.x_min, domain.x_max, domain.y_max - thickness + 1, domain.y_max),
            ]
            if domain.y_min + thickness <= domain.y_max - thickness:
                regions.append(
                    SignatureRegion(
                        mode_id,
                        domain.x_min,
                        domain.x_min + thickness - 1,
                        domain.y_min + thickness,
                        domain.y_max - thickness,
                    )
                )
                regions.append(
                    SignatureRegion(
                        mode_id,
                        domain.x_max - thickness + 1,
                        domain.x_max,
                        domain.y_min + thickness,
                        domain.y_max - thickness,
                    )
                )
            return [region for region in regions if region.x_min <= region.x_max and region.y_min <= region.y_max]

        return None

    def _signature_domain_payload(
        self,
        tpl: str,
        pose_indices: Iterable[int],
        bucket_defs: Sequence[Mapping[str, Any]],
        *,
        label: str,
    ) -> Dict[str, Any]:
        cache_key = (str(tpl), frozenset(int(pose_idx) for pose_idx in pose_indices))
        cached = self.owner._signature_domain_payload_cache.get(cache_key)
        if cached is not None:
            self.owner._update_exact_precompute_profile(
                signature_bucket_cache_hits=int(self.owner._exact_precompute_profile["signature_bucket_cache_hits"]) + 1,
                signature_bucket_distinct_keys=int(len(self.owner._signature_domain_payload_cache)),
            )
            return {
                "mode_rect_domains": dict(cached["mode_rect_domains"]),
                "uses_domain_table": bool(cached["uses_domain_table"]),
                "pose_count": int(cached["pose_count"]),
                "bucket_regions": copy.deepcopy(cached["bucket_regions"]),
                "uses_signature_table": bool(cached["uses_signature_table"]),
            }

        self.owner._update_exact_precompute_profile(
            signature_bucket_cache_misses=int(self.owner._exact_precompute_profile["signature_bucket_cache_misses"]) + 1,
        )
        candidate_pose_indices = set(cache_key[1])
        mode_rect_domains, uses_domain_table = self._build_mode_rect_domains_from_pose_indices(
            str(tpl),
            candidate_pose_indices,
            label=label,
        )
        if uses_domain_table:
            bucket_regions: Dict[str, List[SignatureRegion]] = {}
            uses_signature_table = True
        else:
            bucket_regions = self._build_bucket_regions(
                str(tpl),
                bucket_defs,
                mode_rect_domains,
                allowed_pose_indices=candidate_pose_indices,
            )
            uses_signature_table = False
        payload = {
            "mode_rect_domains": dict(mode_rect_domains),
            "uses_domain_table": bool(uses_domain_table),
            "pose_count": int(sum(domain.pose_count for domain in mode_rect_domains.values())),
            "bucket_regions": copy.deepcopy(bucket_regions),
            "uses_signature_table": bool(uses_signature_table),
        }
        self.owner._signature_domain_payload_cache[cache_key] = payload
        self.owner._update_exact_precompute_profile(
            signature_bucket_distinct_keys=int(len(self.owner._signature_domain_payload_cache)),
        )
        return {
            "mode_rect_domains": dict(payload["mode_rect_domains"]),
            "uses_domain_table": bool(payload["uses_domain_table"]),
            "pose_count": int(payload["pose_count"]),
            "bucket_regions": copy.deepcopy(payload["bucket_regions"]),
            "uses_signature_table": bool(payload["uses_signature_table"]),
        }

    def _prepare_signature_maps(self) -> None:
        for group in self.owner._mandatory_groups:
            group_id = str(group["group_id"])
            tpl = str(group["facility_type"])
            payload = self._signature_domain_payload(
                tpl,
                self.owner._candidate_pose_indices_for_group(group),
                self.owner._mandatory_signature_buckets.get(group_id, []),
                label=f"mandatory_group::{group_id}",
            )
            self._mandatory_group_mode_rect_domains[group_id] = payload["mode_rect_domains"]
            self._mandatory_group_uses_domain_table[group_id] = bool(payload["uses_domain_table"])
            self._mandatory_group_pose_counts[group_id] = int(payload["pose_count"])
            self._mandatory_group_bucket_regions[group_id] = payload["bucket_regions"]
            self._mandatory_group_uses_signature_table[group_id] = bool(payload["uses_signature_table"])

        for tpl, required_count in sorted(self.owner._exact_required_pose_optional_counts.items()):
            if int(required_count) <= 0:
                continue
            payload = self._signature_domain_payload(
                str(tpl),
                range(len(self.owner.facility_pools.get(str(tpl), []))),
                self.owner._required_optional_signature_buckets.get(str(tpl), []),
                label=f"required_optional::{tpl}",
            )
            self._required_optional_mode_rect_domains[str(tpl)] = payload["mode_rect_domains"]
            self._required_optional_uses_domain_table[str(tpl)] = bool(payload["uses_domain_table"])
            self._required_optional_pose_counts[str(tpl)] = int(payload["pose_count"])
            self._required_optional_bucket_regions[str(tpl)] = payload["bucket_regions"]
            self._required_optional_uses_signature_table[str(tpl)] = bool(payload["uses_signature_table"])

    def _power_pole_shell_distance(
        self,
        domain: ModeRectDomain,
        x_val: int,
        y_val: int,
    ) -> Tuple[int, int]:
        dx = min(int(x_val - domain.x_min), int(domain.x_max - x_val))
        dy = min(int(y_val - domain.y_min), int(domain.y_max - y_val))
        return int(dx), int(dy)

    def _power_pole_family_sort_key(self, family_name: str) -> Tuple[Any, ...]:
        template_order = sorted(self.owner._exact_powered_template_demands())
        coefficients = self._power_pole_family_coefficients.get(str(family_name), {})
        coefficient_key = tuple(-int(coefficients.get(str(tpl), 0)) for tpl in template_order)
        return (
            coefficient_key,
            -int(self._power_pole_family_pose_counts.get(str(family_name), 0)),
            str(family_name),
        )

    def _prepare_power_pole_families(self) -> None:
        self._power_pole_family_name_by_int = {}
        self._power_pole_family_coefficients = {}
        self._power_pole_family_id_by_pose_idx = {}
        self._power_pole_family_pose_counts = {}
        self._power_pole_family_order = []
        self._power_pole_use_shell_lookup = True
        self._power_pole_family_tuple_rows = []
        self._power_pole_shell_lookup_rows = []
        self._power_pole_shell_lookup_pairs = []
        self._power_pole_slot_upper_bound = int(
            self.owner._mandatory_powered_nonpole_count()
            + sum(int(v) for v in self.owner._exact_fixed_required_optional_powered_demands().values())
            + sum(int(v) for v in self.owner._residual_optional_powered_slot_upper_bounds().values())
        )
        if self.owner.skip_power_coverage:
            return
        powered_template_demands = self.owner._exact_powered_template_demands()
        if not powered_template_demands:
            return

        template_order = sorted(powered_template_demands)
        family_members: DefaultDict[Tuple[Tuple[str, int], ...], List[int]] = defaultdict(list)
        cache_stats = {
            "scope": "process_memory",
            "signature_hits": 0,
            "signature_misses": 0,
            "signature_count": 0,
            "pole_template_evaluations": 0,
            "signature_class_count": 0,
            "signature_class_evaluations": 0,
            "raw_pole_evaluations": 0,
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
            "m6x4_mixed_cpsat_evaluations": 0,
            "m6x4_mixed_cpsat_cache_hits": 0,
            "m6x4_mixed_cpsat_selected_cases": 0,
            "m6x4_mixed_cpsat_v3_fallbacks": 0,
            "bitset_oracle_evaluations": 0,
            "bitset_fallbacks": 0,
            "cpsat_fallbacks": 0,
            "oracle": "rectangle_frontier_dp_v4",
            "coefficient_source": "exact_rect_dp_cache_v7",
            "shell_pair_count": int(len(self.owner._power_pole_pose_indices_by_shell_pair)),
        }
        coeff_by_template_and_pole = self.owner._exact_local_power_capacity_coefficients(
            powered_template_demands,
            cache_stats,
        )
        for pole_idx, _pose in enumerate(self.owner.facility_pools.get("power_pole", [])):
            family_key = tuple(
                (str(tpl), int(coeff_by_template_and_pole.get(str(tpl), {}).get(int(pole_idx), 0)))
                for tpl in template_order
            )
            family_members[family_key].append(int(pole_idx))

        for family_index, family_key in enumerate(sorted(family_members)):
            family_name = f"family_{family_index:03d}"
            self._power_pole_family_name_by_int[int(family_index)] = family_name
            self._power_pole_family_coefficients[family_name] = {
                str(tpl): int(coeff)
                for tpl, coeff in family_key
            }
            self._power_pole_family_pose_counts[family_name] = int(len(family_members[family_key]))
            for pose_idx in family_members[family_key]:
                self._power_pole_family_id_by_pose_idx[int(pose_idx)] = int(family_index)
        self._power_pole_family_order = sorted(
            self._power_pole_family_coefficients,
            key=self._power_pole_family_sort_key,
        )

        coeff_stats: Dict[str, Any] = {}
        for tpl in template_order:
            positive_coeffs = [
                int(value)
                for value in coeff_by_template_and_pole.get(str(tpl), {}).values()
                if int(value) > 0
            ]
            coeff_stats[str(tpl)] = {
                "demand": int(powered_template_demands[str(tpl)]),
                "total_poles": len(coeff_by_template_and_pole.get(str(tpl), {})),
                "nonzero_poles": len(positive_coeffs),
                "max_coeff": max(positive_coeffs) if positive_coeffs else 0,
                "min_nonzero_coeff": min(positive_coeffs) if positive_coeffs else None,
            }
        self._power_capacity_cache_stats = cache_stats
        self._power_capacity_coeff_stats = coeff_stats

        mode_rect_domains = self._template_full_mode_rect_domains.get("power_pole", {})
        pair_to_family_name: Dict[Tuple[int, int], str] = {}
        for pose_idx, pose_tuple in sorted(self._template_pose_tuple_by_idx.get("power_pole", {}).items()):
            x_val, y_val, mode_id = pose_tuple
            domain = mode_rect_domains.get(int(mode_id))
            if domain is None:
                continue
            family_id = self._power_pole_family_id_by_pose_idx.get(int(pose_idx))
            if family_id is None:
                raise ValueError(f"Missing power pole family for pose_idx={pose_idx}")
            family_name = self._power_pole_family_name_by_int[int(family_id)]
            dx, dy = self._power_pole_shell_distance(domain, int(x_val), int(y_val))
            shell_pair = tuple(sorted((int(dx), int(dy))))
            existing = pair_to_family_name.get(shell_pair)
            if existing is not None and existing != family_name:
                self._power_pole_use_shell_lookup = False
                pair_to_family_name = {}
                break
            pair_to_family_name[shell_pair] = family_name

        if self._power_pole_use_shell_lookup:
            for d_lo, d_hi in sorted(pair_to_family_name):
                family_name = pair_to_family_name[(int(d_lo), int(d_hi))]
                family_id = next(
                    int(idx)
                    for idx, name in self._power_pole_family_name_by_int.items()
                    if str(name) == str(family_name)
                )
                self._power_pole_shell_lookup_rows.append((int(d_lo), int(d_hi), int(family_id)))
                self._power_pole_shell_lookup_pairs.append(
                    {
                        "d_lo": int(d_lo),
                        "d_hi": int(d_hi),
                        "family_id": str(family_name),
                    }
                )
        else:
            for pose_idx, pose_tuple in sorted(self._template_pose_tuple_by_idx.get("power_pole", {}).items()):
                family_id = self._power_pole_family_id_by_pose_idx.get(int(pose_idx))
                if family_id is None:
                    continue
                x_val, y_val, mode_id = pose_tuple
                self._power_pole_family_tuple_rows.append(
                    (int(x_val), int(y_val), int(mode_id), int(family_id))
                )

    def _prepare_slot_specs(self) -> None:
        self.mandatory_slots = {}
        for group in self.owner._mandatory_groups:
            group_id = str(group["group_id"])
            tpl = str(group["facility_type"])
            dims = dict(self.owner.templates[tpl]["dimensions"])
            mode_rect_domains = dict(self._mandatory_group_mode_rect_domains.get(group_id, {}))
            candidate_pose_count = int(self._mandatory_group_pose_counts.get(group_id, 0))
            candidate_tuples = tuple(
                sorted(
                    self._template_pose_tuple_by_idx[tpl][int(pose_idx)]
                    for pose_idx in sorted(self.owner._candidate_pose_indices_for_group(group))
                    if int(pose_idx) in self._template_pose_tuple_by_idx[tpl]
                )
            )
            self.mandatory_slots[group_id] = [
                CoordinateSlotSpec(
                    key=f"{group_id}::slot::{slot_index}",
                    template=tpl,
                    slot_kind="mandatory",
                    slot_index=int(slot_index),
                    dims=(int(dims["w"]), int(dims["h"])),
                    candidate_pose_count=int(candidate_pose_count),
                    tuple_to_pose_idx=dict(self._template_pose_idx_by_tuple[tpl]),
                    mode_rect_domains=mode_rect_domains,
                    allowed_tuples=candidate_tuples,
                    use_domain_table=bool(self._mandatory_group_uses_domain_table.get(group_id, False)),
                    signature_id_to_bucket_id=dict(self._template_signature_bucket_id_by_int.get(tpl, {})),
                )
                for slot_index in range(int(group["count"]))
            ]

        self.required_optional_slots = {}
        for tpl, required_count in sorted(self.owner._exact_required_pose_optional_counts.items()):
            if int(required_count) <= 0:
                continue
            dims = dict(self.owner.templates[str(tpl)]["dimensions"])
            mode_rect_domains = dict(self._required_optional_mode_rect_domains.get(str(tpl), {}))
            candidate_pose_count = int(self._required_optional_pose_counts.get(str(tpl), 0))
            self.required_optional_slots[str(tpl)] = [
                CoordinateSlotSpec(
                    key=f"required_optional::{tpl}::slot::{slot_index}",
                    template=str(tpl),
                    slot_kind="required_optional",
                    slot_index=int(slot_index),
                    dims=(int(dims["w"]), int(dims["h"])),
                    candidate_pose_count=int(candidate_pose_count),
                    tuple_to_pose_idx=dict(self._template_pose_idx_by_tuple[str(tpl)]),
                    mode_rect_domains=mode_rect_domains,
                    allowed_tuples=tuple(sorted(self._template_pose_idx_by_tuple[str(tpl)])),
                    use_domain_table=bool(self._required_optional_uses_domain_table.get(str(tpl), False)),
                    signature_id_to_bucket_id=dict(self._template_signature_bucket_id_by_int.get(str(tpl), {})),
                )
                for slot_index in range(int(required_count))
            ]

        self.residual_optional_slots = {}
        for tpl in ("protocol_storage_box", "power_pole"):
            if tpl not in self.owner.templates:
                continue
            if int(self.owner._exact_required_pose_optional_counts.get(str(tpl), 0)) > 0:
                continue
            slot_upper_bound = int(self._residual_optional_slot_upper_bound(str(tpl)))
            if slot_upper_bound <= 0:
                continue
            mode_rect_domains = dict(self._template_full_mode_rect_domains.get(str(tpl), {}))
            candidate_pose_count = int(sum(domain.pose_count for domain in mode_rect_domains.values()))
            if candidate_pose_count <= 0:
                continue
            dims = dict(self.owner.templates[str(tpl)]["dimensions"])
            slot_specs = [
                CoordinateSlotSpec(
                    key=f"residual_optional::{tpl}::slot::{slot_index}",
                    template=str(tpl),
                    slot_kind="residual_optional",
                    slot_index=int(slot_index),
                    dims=(int(dims["w"]), int(dims["h"])),
                    candidate_pose_count=int(candidate_pose_count),
                    tuple_to_pose_idx=dict(self._template_pose_idx_by_tuple[str(tpl)]),
                    mode_rect_domains=mode_rect_domains,
                    allowed_tuples=tuple(sorted(self._template_pose_idx_by_tuple[str(tpl)])),
                    use_domain_table=bool(self._template_uses_domain_table.get(str(tpl), False)),
                    family_id_to_family_name=(
                        dict(self._power_pole_family_name_by_int)
                        if str(tpl) == "power_pole"
                        else {}
                    ),
                )
                for slot_index in range(int(slot_upper_bound))
            ]
            if slot_specs:
                self.residual_optional_slots[str(tpl)] = slot_specs

    def _new_interval_end(
        self,
        start_var: cp_model.IntVar,
        size: int,
        name: str,
    ) -> cp_model.IntVar:
        end_var = self.model.NewIntVar(0, max(self.grid_w, self.grid_h) + int(size), name)
        self.model.Add(end_var == start_var + int(size))
        return end_var

    def _slot_order_key_bounds(self, slot: CoordinateSlotSpec) -> Tuple[int, int]:
        mode_count = max(1, self._template_mode_literals.get(slot.template, 1))
        scale_x = int(self.grid_h * mode_count)
        scale_y = int(mode_count)
        return int(scale_x), int(scale_y)

    def _slot_order_key_upper_bound(self, slot: CoordinateSlotSpec) -> int:
        scale_x, scale_y = self._slot_order_key_bounds(slot)
        mode_count = max(1, self._template_mode_literals.get(slot.template, 1))
        return int((self.grid_w - 1) * scale_x + (self.grid_h - 1) * scale_y + (mode_count - 1))

    def _create_base_slot_geometry(
        self,
        slot: CoordinateSlotSpec,
        *,
        optional: bool,
    ) -> None:
        all_domains = list(slot.mode_rect_domains.values())
        if not all_domains:
            slot.x = self.model.NewIntVar(0, 0, f"x__{slot.key}")
            slot.y = self.model.NewIntVar(0, 0, f"y__{slot.key}")
            slot.mode = self.model.NewIntVar(0, 0, f"mode__{slot.key}")
            slot.order_key = self.model.NewIntVar(0, 0, f"order_key__{slot.key}")
            self.model.Add(slot.order_key == 0)
            x_end = self._new_interval_end(slot.x, int(slot.dims[0]), f"x_end__{slot.key}")
            y_end = self._new_interval_end(slot.y, int(slot.dims[1]), f"y_end__{slot.key}")
            if optional:
                if slot.active is None:
                    raise RuntimeError(f"optional slot missing active literal: {slot.key}")
                slot.x_interval = self.model.NewOptionalIntervalVar(
                    slot.x,
                    int(slot.dims[0]),
                    x_end,
                    slot.active,
                    f"x_iv__{slot.key}",
                )
                slot.y_interval = self.model.NewOptionalIntervalVar(
                    slot.y,
                    int(slot.dims[1]),
                    y_end,
                    slot.active,
                    f"y_iv__{slot.key}",
                )
            else:
                slot.x_interval = self.model.NewIntervalVar(slot.x, int(slot.dims[0]), x_end, f"x_iv__{slot.key}")
                slot.y_interval = self.model.NewIntervalVar(slot.y, int(slot.dims[1]), y_end, f"y_iv__{slot.key}")
            self._core_x_intervals.append(slot.x_interval)
            self._core_y_intervals.append(slot.y_interval)
            self.model.Add(0 == 1)
            return
        x_lower = min(int(domain.x_min) for domain in all_domains)
        x_upper = max(int(domain.x_max) for domain in all_domains)
        y_lower = min(int(domain.y_min) for domain in all_domains)
        y_upper = max(int(domain.y_max) for domain in all_domains)
        mode_count = max(1, self._template_mode_literals.get(slot.template, 1))

        slot.x = self.model.NewIntVar(int(x_lower), int(x_upper), f"x__{slot.key}")
        slot.y = self.model.NewIntVar(int(y_lower), int(y_upper), f"y__{slot.key}")
        slot.mode = self.model.NewIntVar(0, mode_count - 1, f"mode__{slot.key}")
        slot.order_key = self.model.NewIntVar(
            0,
            self._slot_order_key_upper_bound(slot),
            f"order_key__{slot.key}",
        )
        scale_x, scale_y = self._slot_order_key_bounds(slot)
        self.model.Add(
            slot.order_key
            == slot.x * int(scale_x) + slot.y * int(scale_y) + slot.mode
        )

        x_end = self._new_interval_end(slot.x, int(slot.dims[0]), f"x_end__{slot.key}")
        y_end = self._new_interval_end(slot.y, int(slot.dims[1]), f"y_end__{slot.key}")
        if optional:
            if slot.active is None:
                raise RuntimeError(f"optional slot missing active literal: {slot.key}")
            slot.x_interval = self.model.NewOptionalIntervalVar(
                slot.x,
                int(slot.dims[0]),
                x_end,
                slot.active,
                f"x_iv__{slot.key}",
            )
            slot.y_interval = self.model.NewOptionalIntervalVar(
                slot.y,
                int(slot.dims[1]),
                y_end,
                slot.active,
                f"y_iv__{slot.key}",
            )
        else:
            slot.x_interval = self.model.NewIntervalVar(slot.x, int(slot.dims[0]), x_end, f"x_iv__{slot.key}")
            slot.y_interval = self.model.NewIntervalVar(slot.y, int(slot.dims[1]), y_end, f"y_iv__{slot.key}")
        self._core_x_intervals.append(slot.x_interval)
        self._core_y_intervals.append(slot.y_interval)

        if slot.use_domain_table and slot.allowed_tuples:
            allowed_rows = [
                [int(x_val), int(y_val), int(mode_id)]
                for x_val, y_val, mode_id in slot.allowed_tuples
            ]
            if optional:
                if slot.active is None:
                    raise RuntimeError(f"optional slot missing active literal: {slot.key}")
                self.model.AddAllowedAssignments(
                    [slot.x, slot.y, slot.mode],
                    allowed_rows,
                ).OnlyEnforceIf(slot.active)
            else:
                self.model.AddAllowedAssignments(
                    [slot.x, slot.y, slot.mode],
                    allowed_rows,
                )
            self._domain_table_row_count += len(allowed_rows)

    def _add_region_constraints(
        self,
        slot: CoordinateSlotSpec,
        region: SignatureRegion,
        lit: cp_model.IntVar,
    ) -> None:
        self.model.Add(slot.mode == int(region.mode_id)).OnlyEnforceIf(lit)
        self.model.Add(slot.x >= int(region.x_min)).OnlyEnforceIf(lit)
        self.model.Add(slot.x <= int(region.x_max)).OnlyEnforceIf(lit)
        self.model.Add(slot.y >= int(region.y_min)).OnlyEnforceIf(lit)
        self.model.Add(slot.y <= int(region.y_max)).OnlyEnforceIf(lit)

    def _create_signature_slot_vars(
        self,
        slot_specs: Sequence[CoordinateSlotSpec],
        *,
        bucket_defs: Sequence[Mapping[str, Any]],
        bucket_regions: Mapping[str, List[SignatureRegion]],
        membership_store: Dict[str, List[cp_model.IntVar]],
        membership_prefix: str,
    ) -> None:
        if not bucket_defs:
            example_key = str(slot_specs[0].key) if slot_specs else membership_prefix
            raise ValueError(
                f"Missing signature bucket definitions for coordinate-exact slot set: {example_key}"
            )
        bucket_id_to_int = {str(bucket["bucket_id"]): idx for idx, bucket in enumerate(bucket_defs)}
        for slot in slot_specs:
            self._create_base_slot_geometry(slot, optional=False)
            slot.signature = self.model.NewIntVar(
                0,
                max(0, len(bucket_defs) - 1),
                f"signature__{slot.key}",
            )
            self._slot_binding[slot.key] = {
                "x": int(slot.x.Index()),
                "y": int(slot.y.Index()),
                "mode": int(slot.mode.Index()),
                "signature": int(slot.signature.Index()),
            }
            self._interval_binding[slot.key] = (int(slot.x_interval.Index()), int(slot.y_interval.Index()))

            all_region_lits: List[cp_model.IntVar] = []
            for bucket in bucket_defs:
                bucket_id = str(bucket["bucket_id"])
                bucket_int = int(bucket_id_to_int[bucket_id])
                bucket_lit = self.model.NewBoolVar(f"{membership_prefix}__{slot.key}__{bucket_id}")
                self.model.Add(slot.signature == int(bucket_int)).OnlyEnforceIf(bucket_lit)
                self.model.Add(slot.signature != int(bucket_int)).OnlyEnforceIf(bucket_lit.Not())
                membership_store[bucket_id].append(bucket_lit)

                bucket_region_lits: List[cp_model.IntVar] = []
                for region_index, region in enumerate(bucket_regions.get(bucket_id, [])):
                    region_lit = self.model.NewBoolVar(
                        f"region__{slot.key}__{bucket_id}__{region_index}"
                    )
                    self._add_region_constraints(slot, region, region_lit)
                    bucket_region_lits.append(region_lit)
                    all_region_lits.append(region_lit)
                if bucket_region_lits:
                    self.model.Add(sum(bucket_region_lits) == 1).OnlyEnforceIf(bucket_lit)
                    self.model.Add(sum(bucket_region_lits) == 0).OnlyEnforceIf(bucket_lit.Not())
                else:
                    self.model.Add(bucket_lit == 0)

            if all_region_lits:
                self.model.AddExactlyOne(all_region_lits)
            else:
                self.model.Add(0 == 1)

    def _create_plain_slot_vars(
        self,
        slot_specs: Sequence[CoordinateSlotSpec],
    ) -> None:
        for slot in slot_specs:
            self._create_base_slot_geometry(slot, optional=False)
            self._slot_binding[slot.key] = {
                "x": int(slot.x.Index()),
                "y": int(slot.y.Index()),
                "mode": int(slot.mode.Index()),
            }
            self._interval_binding[slot.key] = (int(slot.x_interval.Index()), int(slot.y_interval.Index()))

    def _create_mandatory_slot_vars(self) -> None:
        self.mandatory_signature_count_vars = {}
        self._mandatory_signature_membership = {}
        for group in self.owner._mandatory_groups:
            group_id = str(group["group_id"])
            slot_specs = self.mandatory_slots[group_id]
            bucket_defs = list(self.owner._mandatory_signature_buckets.get(group_id, []))
            if self._mandatory_group_uses_signature_table.get(group_id, False):
                self._mandatory_signature_membership[group_id] = {}
                self._create_plain_slot_vars(slot_specs)
            else:
                self._mandatory_signature_membership[group_id] = {
                    str(bucket["bucket_id"]): [] for bucket in bucket_defs
                }
                self._create_signature_slot_vars(
                    slot_specs,
                    bucket_defs=bucket_defs,
                    bucket_regions=self._mandatory_group_bucket_regions.get(group_id, {}),
                    membership_store=self._mandatory_signature_membership[group_id],
                    membership_prefix="is_sig",
                )
            for left_slot, right_slot in zip(slot_specs, slot_specs[1:]):
                self.model.Add(left_slot.order_key <= right_slot.order_key)
            self.mandatory_signature_count_vars[group_id] = {}
            for bucket in bucket_defs if not self._mandatory_group_uses_signature_table.get(group_id, False) else []:
                bucket_id = str(bucket["bucket_id"])
                count_var = self.model.NewIntVar(
                    0,
                    int(group["count"]),
                    f"group_signature_count__{group_id}__{bucket_id}",
                )
                self.model.Add(count_var == sum(self._mandatory_signature_membership[group_id][bucket_id]))
                self.mandatory_signature_count_vars[group_id][bucket_id] = count_var

    def _create_required_optional_slot_vars(self) -> None:
        self.required_optional_signature_count_vars = {}
        self._required_optional_signature_membership = {}
        for tpl, slot_specs in sorted(self.required_optional_slots.items()):
            bucket_defs = list(self.owner._required_optional_signature_buckets.get(tpl, []))
            if self._required_optional_uses_signature_table.get(tpl, False):
                self._required_optional_signature_membership[tpl] = {}
                self._create_plain_slot_vars(slot_specs)
            else:
                self._required_optional_signature_membership[tpl] = {
                    str(bucket["bucket_id"]): [] for bucket in bucket_defs
                }
                self._create_signature_slot_vars(
                    slot_specs,
                    bucket_defs=bucket_defs,
                    bucket_regions=self._required_optional_bucket_regions.get(tpl, {}),
                    membership_store=self._required_optional_signature_membership[tpl],
                    membership_prefix="is_req_sig",
                )
            for left_slot, right_slot in zip(slot_specs, slot_specs[1:]):
                self.model.Add(left_slot.order_key <= right_slot.order_key)
            self.required_optional_signature_count_vars[tpl] = {}
            for bucket in bucket_defs if not self._required_optional_uses_signature_table.get(tpl, False) else []:
                bucket_id = str(bucket["bucket_id"])
                count_var = self.model.NewIntVar(
                    0,
                    len(slot_specs),
                    f"required_optional_signature_count__{tpl}__{bucket_id}",
                )
                self.model.Add(count_var == sum(self._required_optional_signature_membership[tpl][bucket_id]))
                self.required_optional_signature_count_vars[tpl][bucket_id] = count_var

    def _create_residual_optional_slot_vars(self) -> None:
        for tpl, slot_specs in sorted(self.residual_optional_slots.items()):
            if str(tpl) == "power_pole":
                continue
            all_domains = list(self._template_full_mode_rect_domains.get(str(tpl), {}).values())
            if not all_domains:
                continue
            default_domain = min(
                all_domains,
                key=lambda domain: (
                    int(domain.mode_id),
                    int(domain.x_min),
                    int(domain.y_min),
                ),
            )
            for slot in slot_specs:
                slot.active = self.model.NewBoolVar(f"active__{slot.key}")
                self._create_base_slot_geometry(slot, optional=True)
                self.model.Add(slot.mode == int(default_domain.mode_id)).OnlyEnforceIf(slot.active.Not())
                self.model.Add(slot.x == int(default_domain.x_min)).OnlyEnforceIf(slot.active.Not())
                self.model.Add(slot.y == int(default_domain.y_min)).OnlyEnforceIf(slot.active.Not())
                self._slot_binding[slot.key] = {
                    "active": int(slot.active.Index()),
                    "x": int(slot.x.Index()),
                    "y": int(slot.y.Index()),
                    "mode": int(slot.mode.Index()),
                    "order_key": int(slot.order_key.Index()),
                }
                self._interval_binding[slot.key] = (
                    int(slot.x_interval.Index()),
                    int(slot.y_interval.Index()),
                )
            for left_slot, right_slot in zip(slot_specs, slot_specs[1:]):
                self.model.Add(left_slot.active >= right_slot.active)
                self.model.Add(left_slot.order_key <= right_slot.order_key).OnlyEnforceIf(
                    right_slot.active
                )

    def _power_pole_shell_payload(self) -> Dict[str, Any]:
        return {
            "pair_count": int(len(self._power_pole_shell_lookup_pairs)),
            "pairs": copy.deepcopy(self._power_pole_shell_lookup_pairs),
        }

    def _create_power_pole_slot_vars(self) -> None:
        self.power_pole_family_count_vars = {}
        self._power_pole_family_membership = {
            family_name: [] for family_name in self._power_pole_family_name_by_int.values()
        }
        pole_domains = dict(self._template_full_mode_rect_domains.get("power_pole", {}))
        if not pole_domains:
            return
        pole_mode_id = min(pole_domains)
        pole_domain = pole_domains[int(pole_mode_id)]
        sentinel_family = len(self._power_pole_family_name_by_int)

        for slot in self.residual_optional_slots.get("power_pole", []):
            slot.active = self.model.NewBoolVar(f"active__{slot.key}")
            self._create_base_slot_geometry(slot, optional=True)
            slot.family = self.model.NewIntVar(
                0,
                max(0, sentinel_family),
                f"family__{slot.key}",
            )

            self.model.Add(slot.mode == int(pole_mode_id))
            self.model.Add(slot.x == int(pole_domain.x_min)).OnlyEnforceIf(slot.active.Not())
            self.model.Add(slot.y == int(pole_domain.y_min)).OnlyEnforceIf(slot.active.Not())

            if self._power_pole_use_shell_lookup and self._power_pole_shell_lookup_rows:
                dx = self.model.NewIntVar(0, int(pole_domain.x_max - pole_domain.x_min), f"dx__{slot.key}")
                dy = self.model.NewIntVar(0, int(pole_domain.y_max - pole_domain.y_min), f"dy__{slot.key}")
                max_shell = max(int(pole_domain.x_max - pole_domain.x_min), int(pole_domain.y_max - pole_domain.y_min))
                d_lo = self.model.NewIntVar(0, max_shell, f"d_lo__{slot.key}")
                d_hi = self.model.NewIntVar(0, max_shell, f"d_hi__{slot.key}")
                x_lookup = [
                    min(int(x_val - pole_domain.x_min), int(pole_domain.x_max - x_val))
                    if pole_domain.x_min <= x_val <= pole_domain.x_max
                    else 0
                    for x_val in range(int(pole_domain.x_max) + 1)
                ]
                y_lookup = [
                    min(int(y_val - pole_domain.y_min), int(pole_domain.y_max - y_val))
                    if pole_domain.y_min <= y_val <= pole_domain.y_max
                    else 0
                    for y_val in range(int(pole_domain.y_max) + 1)
                ]
                self.model.AddElement(slot.x, x_lookup, dx)
                self.model.AddElement(slot.y, y_lookup, dy)
                self.model.AddMinEquality(d_lo, [dx, dy])
                self.model.AddMaxEquality(d_hi, [dx, dy])
                self.model.AddAllowedAssignments(
                    [d_lo, d_hi, slot.family],
                    list(self._power_pole_shell_lookup_rows),
                ).OnlyEnforceIf(slot.active)
            elif self._power_pole_family_tuple_rows:
                self.model.AddAllowedAssignments(
                    [slot.x, slot.y, slot.mode, slot.family],
                    list(self._power_pole_family_tuple_rows),
                ).OnlyEnforceIf(slot.active)
            else:
                self.model.Add(slot.family == 0).OnlyEnforceIf(slot.active)
            self.model.Add(slot.family == int(sentinel_family)).OnlyEnforceIf(slot.active.Not())

            self._slot_binding[slot.key] = {
                "active": int(slot.active.Index()),
                "x": int(slot.x.Index()),
                "y": int(slot.y.Index()),
                "mode": int(slot.mode.Index()),
                "family": int(slot.family.Index()),
            }
            self._interval_binding[slot.key] = (int(slot.x_interval.Index()), int(slot.y_interval.Index()))

            for family_int, family_name in self._power_pole_family_name_by_int.items():
                family_lit = self.model.NewBoolVar(f"is_family__{slot.key}__{family_name}")
                self.model.Add(slot.family == int(family_int)).OnlyEnforceIf(family_lit)
                self.model.Add(slot.family != int(family_int)).OnlyEnforceIf(family_lit.Not())
                self._power_pole_family_membership[family_name].append(family_lit)

        pole_slots = self.residual_optional_slots.get("power_pole", [])
        for left_slot, right_slot in zip(pole_slots, pole_slots[1:]):
            self.model.Add(left_slot.active >= right_slot.active)
            self.model.Add(left_slot.family <= right_slot.family)
            same_family = self.model.NewBoolVar(
                f"same_family__{left_slot.key}__{right_slot.key}"
            )
            self.model.Add(left_slot.family == right_slot.family).OnlyEnforceIf(same_family)
            self.model.Add(left_slot.family != right_slot.family).OnlyEnforceIf(same_family.Not())
            self.model.Add(left_slot.order_key <= right_slot.order_key).OnlyEnforceIf(same_family)

        for family_name, members in sorted(self._power_pole_family_membership.items()):
            count_var = self.model.NewIntVar(
                0,
                len(self.residual_optional_slots.get("power_pole", [])),
                f"power_pole_family_count__{family_name}",
            )
            self.model.Add(count_var == sum(members))
            self.power_pole_family_count_vars[family_name] = count_var

    def build(self) -> None:
        self._create_mandatory_slot_vars()
        self._create_required_optional_slot_vars()
        self._create_residual_optional_slot_vars()
        self._create_power_pole_slot_vars()
        if self._core_x_intervals:
            self.model.AddNoOverlap2D(self._core_x_intervals, self._core_y_intervals)
        self._add_ghost_constraints()
        if not self.owner.skip_power_coverage:
            self._add_geometric_power_coverage_constraints()
        self._add_global_valid_inequalities()
        self._add_search_guidance()
        self._finalize_build_stats()

    def _bind_slot_specs(
        self,
        slot_specs: Iterable[CoordinateSlotSpec],
        binding: Mapping[str, Dict[str, int]],
        interval_binding: Mapping[str, Tuple[int, int]],
    ) -> None:
        for slot in slot_specs:
            slot_binding = dict(binding[str(slot.key)])
            if "active" in slot_binding:
                slot.active = self.model.GetBoolVarFromProtoIndex(int(slot_binding["active"]))
            slot.x = self.model.GetIntVarFromProtoIndex(int(slot_binding["x"]))
            slot.y = self.model.GetIntVarFromProtoIndex(int(slot_binding["y"]))
            slot.mode = self.model.GetIntVarFromProtoIndex(int(slot_binding["mode"]))
            if "order_key" in slot_binding:
                slot.order_key = self.model.GetIntVarFromProtoIndex(int(slot_binding["order_key"]))
            if "signature" in slot_binding:
                slot.signature = self.model.GetIntVarFromProtoIndex(int(slot_binding["signature"]))
            if "family" in slot_binding:
                slot.family = self.model.GetIntVarFromProtoIndex(int(slot_binding["family"]))
            x_iv_idx, y_iv_idx = interval_binding[str(slot.key)]
            slot.x_interval = self.model.GetIntervalVarFromProtoIndex(int(x_iv_idx))
            slot.y_interval = self.model.GetIntervalVarFromProtoIndex(int(y_iv_idx))

    def bind_from_core(self, coordinate_binding: Mapping[str, Any]) -> None:
        self._slot_binding = {
            str(k): {str(inner_k): int(inner_v) for inner_k, inner_v in dict(v).items()}
            for k, v in dict(coordinate_binding.get("slot_binding", {})).items()
        }
        self._interval_binding = {
            str(k): (int(v[0]), int(v[1]))
            for k, v in dict(coordinate_binding.get("interval_binding", {})).items()
        }
        for slot_specs in [*self.mandatory_slots.values(), *self.required_optional_slots.values(), *self.residual_optional_slots.values()]:
            self._bind_slot_specs(slot_specs, self._slot_binding, self._interval_binding)
        self.mandatory_signature_count_vars = {
            str(group_id): {
                str(bucket_id): self.model.GetIntVarFromProtoIndex(int(proto_idx))
                for bucket_id, proto_idx in dict(bucket_map).items()
            }
            for group_id, bucket_map in dict(coordinate_binding.get("mandatory_signature_count_vars", {})).items()
        }
        self.required_optional_signature_count_vars = {
            str(tpl): {
                str(bucket_id): self.model.GetIntVarFromProtoIndex(int(proto_idx))
                for bucket_id, proto_idx in dict(bucket_map).items()
            }
            for tpl, bucket_map in dict(coordinate_binding.get("required_optional_signature_count_vars", {})).items()
        }
        self.power_pole_family_count_vars = {
            str(family_name): self.model.GetIntVarFromProtoIndex(int(proto_idx))
            for family_name, proto_idx in dict(coordinate_binding.get("power_pole_family_count_vars", {})).items()
        }
        self._core_x_intervals = []
        self._core_y_intervals = []
        for slot_specs in [*self.mandatory_slots.values(), *self.required_optional_slots.values(), *self.residual_optional_slots.values()]:
            for slot in slot_specs:
                if slot.x_interval is not None and slot.y_interval is not None:
                    self._core_x_intervals.append(slot.x_interval)
                    self._core_y_intervals.append(slot.y_interval)

    def export_core_binding(self) -> Dict[str, Any]:
        return {
            "slot_binding": copy.deepcopy(self._slot_binding),
            "interval_binding": copy.deepcopy(self._interval_binding),
            "mandatory_signature_count_vars": {
                str(group_id): {str(bucket_id): int(var.Index()) for bucket_id, var in bucket_map.items()}
                for group_id, bucket_map in self.mandatory_signature_count_vars.items()
            },
            "required_optional_signature_count_vars": {
                str(tpl): {str(bucket_id): int(var.Index()) for bucket_id, var in bucket_map.items()}
                for tpl, bucket_map in self.required_optional_signature_count_vars.items()
            },
            "power_pole_family_count_vars": {
                str(family_name): int(var.Index()) for family_name, var in self.power_pole_family_count_vars.items()
            },
        }

    def _add_ghost_constraints(self) -> None:
        self.owner._ghost_domains.clear()
        self.owner.u_vars.clear()
        self._ghost_x_intervals = []
        self._ghost_y_intervals = []
        ghost_rect = self.owner.ghost_rect
        if not ghost_rect:
            self.owner.build_stats["ghost_rect"] = {"enabled": False}
            return

        ghost_w, ghost_h = int(ghost_rect[0]), int(ghost_rect[1])
        if ghost_w > self.grid_w or ghost_h > self.grid_h:
            self.model.Add(0 == 1)
            self.owner.build_stats["ghost_rect"] = {
                "enabled": True,
                "placements": 0,
                "reason": "rectangle larger than grid",
            }
            return

        for anchor_x in range(self.grid_w - ghost_w + 1):
            for anchor_y in range(self.grid_h - ghost_h + 1):
                rect_idx = len(self.owner._ghost_domains)
                cells = [
                    (anchor_x + dx, anchor_y + dy)
                    for dx in range(ghost_w)
                    for dy in range(ghost_h)
                ]
                var = self.model.NewBoolVar(f"ghost__{anchor_x}_{anchor_y}_{ghost_w}_{ghost_h}")
                self.owner.u_vars[rect_idx] = var
                self.owner._ghost_domains.append({"anchor": {"x": anchor_x, "y": anchor_y}, "cells": cells})
                x_interval = self.model.NewOptionalIntervalVar(
                    anchor_x,
                    ghost_w,
                    anchor_x + ghost_w,
                    var,
                    f"ghost_x_iv__{anchor_x}_{anchor_y}_{ghost_w}_{ghost_h}",
                )
                y_interval = self.model.NewOptionalIntervalVar(
                    anchor_y,
                    ghost_h,
                    anchor_y + ghost_h,
                    var,
                    f"ghost_y_iv__{anchor_x}_{anchor_y}_{ghost_w}_{ghost_h}",
                )
                self._ghost_x_intervals.append(x_interval)
                self._ghost_y_intervals.append(y_interval)

        self.model.AddExactlyOne(list(self.owner.u_vars.values()))
        self.model.AddNoOverlap2D(
            [*self._core_x_intervals, *self._ghost_x_intervals],
            [*self._core_y_intervals, *self._ghost_y_intervals],
        )
        self.owner.build_stats["ghost_rect"] = {
            "enabled": True,
            "placements": len(self.owner._ghost_domains),
            "size": {"w": ghost_w, "h": ghost_h},
        }

    def _all_powered_slots(self) -> List[CoordinateSlotSpec]:
        powered_slots: List[CoordinateSlotSpec] = []
        for group in self.owner._mandatory_groups:
            tpl = str(group["facility_type"])
            if tpl in self.owner._powered_templates and tpl != "power_pole":
                powered_slots.extend(self.mandatory_slots.get(str(group["group_id"]), []))
        for tpl, slot_specs in self.required_optional_slots.items():
            if tpl in self.owner._powered_templates and tpl != "power_pole":
                powered_slots.extend(slot_specs)
        for tpl, slot_specs in self.residual_optional_slots.items():
            if tpl in self.owner._powered_templates and tpl != "power_pole":
                powered_slots.extend(slot_specs)
        return powered_slots

    def _power_coverage_radius(self) -> int:
        template = self.owner.templates.get("power_pole")
        if not template:
            return 0
        return int(template.get("power_coverage_radius", 0))

    def _supports_rectangular_power_coverage(self) -> bool:
        template = self.owner.templates.get("power_pole")
        if not template or "power_coverage_radius" not in template:
            return False
        radius = int(template.get("power_coverage_radius", 0))
        for pose in self.owner.facility_pools.get("power_pole", []):
            anchor = dict(pose.get("anchor", {}))
            x0 = int(anchor.get("x", 0))
            y0 = int(anchor.get("y", 0))
            expected: Set[Tuple[int, int]] = set()
            for cell_x in range(max(0, x0 - radius), min(self.grid_w - 1, x0 + 1 + radius) + 1):
                for cell_y in range(max(0, y0 - radius), min(self.grid_h - 1, y0 + 1 + radius) + 1):
                    expected.add((int(cell_x), int(cell_y)))
            actual = {
                (int(cell[0]), int(cell[1]))
                for cell in pose.get("power_coverage_cells", []) or []
            }
            if actual != expected:
                return False
        return True

    def _add_table_power_coverage_constraints(self) -> int:
        powered_slots = self._all_powered_slots()
        pole_slots = list(self.residual_optional_slots.get("power_pole", []))
        cover_literals = 0
        for powered_slot in powered_slots:
            allowed_tuples: List[Tuple[int, ...]] = []
            for powered_pose_idx, coverers in self.owner._power_coverers_by_template_pose.get(powered_slot.template, {}).items():
                powered_tuple = self._template_pose_tuple_by_idx[powered_slot.template].get(int(powered_pose_idx))
                if powered_tuple is None:
                    continue
                for pole_idx in coverers:
                    pole_tuple = self._template_pose_tuple_by_idx["power_pole"].get(int(pole_idx))
                    if pole_tuple is None:
                        continue
                    allowed_tuples.append(
                        (
                            int(pole_tuple[0]),
                            int(pole_tuple[1]),
                            int(pole_tuple[2]),
                            int(powered_tuple[0]),
                            int(powered_tuple[1]),
                            int(powered_tuple[2]),
                        )
                    )

            witnesses: List[cp_model.IntVar] = []
            for pole_slot in pole_slots:
                cover_lit = self.model.NewBoolVar(f"covers__{pole_slot.key}__{powered_slot.key}")
                self.model.Add(cover_lit <= pole_slot.active)
                if powered_slot.active is not None:
                    self.model.Add(cover_lit <= powered_slot.active)
                if allowed_tuples:
                    self.model.AddAllowedAssignments(
                        [pole_slot.x, pole_slot.y, pole_slot.mode, powered_slot.x, powered_slot.y, powered_slot.mode],
                        allowed_tuples,
                    ).OnlyEnforceIf(cover_lit)
                else:
                    self.model.Add(cover_lit == 0)
                witnesses.append(cover_lit)
                cover_literals += 1
            if witnesses:
                if powered_slot.active is not None:
                    self.model.Add(sum(witnesses) >= powered_slot.active)
                else:
                    self.model.Add(sum(witnesses) >= 1)
            else:
                if powered_slot.active is not None:
                    self.model.Add(powered_slot.active == 0)
                else:
                    self.model.Add(0 >= 1)
        return int(cover_literals)

    def _add_geometric_power_coverage_constraints(self) -> None:
        powered_slots = self._all_powered_slots()
        pole_slots = list(self.residual_optional_slots.get("power_pole", []))
        radius = self._power_coverage_radius()
        if not self._supports_rectangular_power_coverage():
            cover_literals = self._add_table_power_coverage_constraints()
            self.owner.build_stats["power_coverage"] = {
                "representation": "coordinate_cover_table",
                "encoding": "table_pairwise_witness_v1",
                "powered_slots": len(powered_slots),
                "pole_slots": len(pole_slots),
                "cover_literals": int(cover_literals),
                "witness_indices": 0,
                "element_constraints": 0,
            }
            return
        witness_indices = 0
        element_constraints = 0
        if not pole_slots:
            for powered_slot in powered_slots:
                if powered_slot.active is not None:
                    self.model.Add(powered_slot.active == 0)
                else:
                    self.model.Add(0 >= 1)
            self.owner.build_stats["power_coverage"] = {
                "representation": "coordinate_geometric",
                "encoding": "geometric_element_witness_v1",
                "powered_slots": len(powered_slots),
                "pole_slots": 0,
                "cover_literals": 0,
                "witness_indices": 0,
                "element_constraints": 0,
                "radius": int(radius),
            }
            return

        active_lookup = [slot.active for slot in pole_slots if slot.active is not None]
        x_lookup = [slot.x for slot in pole_slots if slot.x is not None]
        y_lookup = [slot.y for slot in pole_slots if slot.y is not None]
        for powered_slot in powered_slots:
            cover_choice_idx = self.model.NewIntVar(
                0,
                len(pole_slots) - 1,
                f"cover_choice_idx__{powered_slot.key}",
            )
            cover_choice_active = self.model.NewBoolVar(
                f"cover_choice_active__{powered_slot.key}"
            )
            cover_choice_x = self.model.NewIntVar(
                0,
                max(0, self.grid_w - 1),
                f"cover_choice_x__{powered_slot.key}",
            )
            cover_choice_y = self.model.NewIntVar(
                0,
                max(0, self.grid_h - 1),
                f"cover_choice_y__{powered_slot.key}",
            )
            self.model.AddElement(cover_choice_idx, active_lookup, cover_choice_active)
            self.model.AddElement(cover_choice_idx, x_lookup, cover_choice_x)
            self.model.AddElement(cover_choice_idx, y_lookup, cover_choice_y)
            element_constraints += 3
            witness_indices += 1

            if powered_slot.active is not None:
                self.model.Add(cover_choice_active == 1).OnlyEnforceIf(powered_slot.active)
                self.model.Add(
                    powered_slot.x <= cover_choice_x + 2 + radius - 1
                ).OnlyEnforceIf(powered_slot.active)
                self.model.Add(
                    cover_choice_x - radius <= powered_slot.x + int(powered_slot.dims[0]) - 1
                ).OnlyEnforceIf(powered_slot.active)
                self.model.Add(
                    powered_slot.y <= cover_choice_y + 2 + radius - 1
                ).OnlyEnforceIf(powered_slot.active)
                self.model.Add(
                    cover_choice_y - radius <= powered_slot.y + int(powered_slot.dims[1]) - 1
                ).OnlyEnforceIf(powered_slot.active)
            else:
                self.model.Add(cover_choice_active == 1)
                self.model.Add(powered_slot.x <= cover_choice_x + 2 + radius - 1)
                self.model.Add(
                    cover_choice_x - radius <= powered_slot.x + int(powered_slot.dims[0]) - 1
                )
                self.model.Add(powered_slot.y <= cover_choice_y + 2 + radius - 1)
                self.model.Add(
                    cover_choice_y - radius <= powered_slot.y + int(powered_slot.dims[1]) - 1
                )
        self.owner.build_stats["power_coverage"] = {
            "representation": "coordinate_geometric",
            "encoding": "geometric_element_witness_v1",
            "powered_slots": len(powered_slots),
            "pole_slots": len(pole_slots),
            "cover_literals": 0,
            "witness_indices": int(witness_indices),
            "element_constraints": int(element_constraints),
            "radius": int(radius),
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
                "signature_count": 0,
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
                "raw_pole_count": len(self.owner.facility_pools.get("power_pole", [])),
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
                "enabled": bool(self.owner.ghost_rect),
                "explicit_u_conditioning": False,
            },
            "notes": [
                "No power-pole area lower bound is injected into certified exact mode.",
                "Coordinate exact master preserves exact-safe evidence semantics.",
            ],
        }

        protocol_count = int(self.owner._required_protocol_storage_box_lower_bound())
        stats["optional_cardinality_bounds"]["protocol_storage_box"] = {
            "mode": "required_lower_bound",
            "required_generic_input_slots": int(self.owner._required_generic_input_slot_total()),
            "slots_per_pose": int(get_operation_port_profile("wireless_sink").generic_input_slots),
            "lower": int(protocol_count),
            "upper": None,
            "candidate_pose_count": int(len(self.owner.facility_pools.get("protocol_storage_box", []))),
            "slot_pool_upper_bound": int(len(self.residual_optional_slots.get("protocol_storage_box", []))),
        }
        stats["applied"].append(
            {
                "type": "optional_cardinality_bound",
                "template": "protocol_storage_box",
                "mode": "required_lower_bound",
                "lower": int(protocol_count),
                "upper": None,
            }
        )
        protocol_slots = list(self.residual_optional_slots.get("protocol_storage_box", []))
        if protocol_count > 0:
            if protocol_slots:
                protocol_terms = [
                    slot.active
                    for slot in protocol_slots
                    if slot.active is not None
                ]
                if protocol_terms:
                    self.model.Add(sum(protocol_terms) >= int(protocol_count))
                else:
                    self.model.Add(0 >= int(protocol_count))
            else:
                self.model.Add(0 >= int(protocol_count))

        mandatory_powered_nonpole = int(self.owner._mandatory_powered_nonpole_count())
        optional_powered_templates = sorted(
            {
                str(tpl)
                for tpl in self.required_optional_slots
                if str(tpl) in self.owner._powered_templates and str(tpl) != "power_pole"
            }
            | {
                str(tpl)
                for tpl in self.residual_optional_slots
                if str(tpl) in self.owner._powered_templates and str(tpl) != "power_pole"
            }
        )
        stats["optional_cardinality_bounds"]["power_pole"] = {
            "mode": "selected_powered_upper_bound",
            "lower": 0,
            "candidate_pose_count": int(len(self.owner.facility_pools.get("power_pole", []))),
            "mandatory_powered_nonpole": int(mandatory_powered_nonpole),
            "optional_powered_templates": optional_powered_templates,
            "slot_pool_upper_bound": int(self._power_pole_slot_upper_bound),
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
        if self.residual_optional_slots.get("power_pole"):
            required_optional_powered_count = sum(
                len(slot_specs)
                for tpl, slot_specs in self.required_optional_slots.items()
                if str(tpl) in self.owner._powered_templates and str(tpl) != "power_pole"
            )
            residual_powered_optional_terms = [
                slot.active
                for tpl, slot_specs in self.residual_optional_slots.items()
                if str(tpl) in self.owner._powered_templates and str(tpl) != "power_pole"
                for slot in slot_specs
                if slot.active is not None
            ]
            self.model.Add(
                sum(slot.active for slot in self.residual_optional_slots["power_pole"] if slot.active is not None)
                <= int(mandatory_powered_nonpole)
                + int(required_optional_powered_count)
                + sum(residual_powered_optional_terms)
            )

        stats["fixed_required_optional_demands"] = dict(self.owner._exact_fixed_required_optional_powered_demands())
        stats["lower_bound_optional_powered_demands"] = dict(self.owner._lower_bound_optional_powered_demands())
        if self.owner.skip_power_coverage:
            stats["power_capacity_families"]["reason"] = "power_coverage_skipped"
            stats["aggregated_power_capacity_terms"]["reason"] = "power_coverage_skipped"
            stats["capacity_cache"] = dict(self._power_capacity_cache_stats)
            stats["capacity_coeff_stats"] = copy.deepcopy(self._power_capacity_coeff_stats)
            self.owner.build_stats["global_valid_inequalities"] = stats
            return

        powered_template_demands = self.owner._exact_powered_template_demands()
        stats["powered_template_demands"] = dict(powered_template_demands)
        if not powered_template_demands or not self.power_pole_family_count_vars:
            stats["power_capacity_families"]["reason"] = "no_powered_template_demands"
            stats["aggregated_power_capacity_terms"]["reason"] = "no_powered_template_demands"
            stats["capacity_cache"] = dict(self._power_capacity_cache_stats)
            stats["capacity_coeff_stats"] = copy.deepcopy(self._power_capacity_coeff_stats)
            self.owner.build_stats["global_valid_inequalities"] = stats
            return

        template_order = sorted(powered_template_demands)
        family_payload: List[Dict[str, Any]] = []
        for family_name, coefficients in sorted(self._power_pole_family_coefficients.items()):
            family_payload.append(
                {
                    "family_id": family_name,
                    "size": int(self._power_pole_family_pose_counts.get(family_name, 0)),
                    "coefficients": {str(tpl): int(coefficients.get(str(tpl), 0)) for tpl in template_order},
                }
            )

        raw_nonzero_terms = 0
        aggregated_nonzero_terms = 0
        for tpl, demand in sorted(powered_template_demands.items()):
            terms: List[cp_model.LinearExpr] = []
            nonzero_pose_count = 0
            for pose_idx in range(len(self.owner.facility_pools.get("power_pole", []))):
                family_id = self._power_pole_family_id_by_pose_idx.get(int(pose_idx))
                if family_id is None:
                    continue
                family_name = self._power_pole_family_name_by_int[int(family_id)]
                if int(self._power_pole_family_coefficients[family_name].get(str(tpl), 0)) > 0:
                    nonzero_pose_count += 1
            raw_nonzero_terms += int(nonzero_pose_count)
            for family_name, count_var in sorted(self.power_pole_family_count_vars.items()):
                coeff = int(self._power_pole_family_coefficients[family_name].get(str(tpl), 0))
                if coeff <= 0:
                    continue
                aggregated_nonzero_terms += 1
                terms.append(coeff * count_var)
            if terms:
                self.model.Add(sum(terms) >= int(demand))
            else:
                self.model.Add(0 >= int(demand))
            stats["applied"].append(
                {
                    "type": "power_capacity_lower_bound",
                    "template": str(tpl),
                    "demand": int(demand),
                    "nonzero_poles": int(nonzero_pose_count),
                }
            )

        stats["power_capacity_families"] = {
            "applied": True,
            "family_count": int(len(self.power_pole_family_count_vars)),
            "raw_pole_count": int(len(self.owner.facility_pools.get("power_pole", []))),
            "coefficient_source": str(
                self._power_capacity_cache_stats.get(
                    "coefficient_source",
                    "exact_rect_dp_cache_v7",
                )
            ),
            "shell_pair_count": int(self._power_capacity_cache_stats.get("shell_pair_count", 0)),
            "compact_signature_class_count": int(
                self._power_capacity_cache_stats.get("compact_signature_class_count", 0)
            ),
            "families": family_payload,
        }
        stats["aggregated_power_capacity_terms"] = {
            "applied": True,
            "raw_nonzero_terms": int(raw_nonzero_terms),
            "aggregated_nonzero_terms": int(aggregated_nonzero_terms),
        }
        stats["capacity_cache"] = dict(self._power_capacity_cache_stats)
        stats["capacity_coeff_stats"] = copy.deepcopy(self._power_capacity_coeff_stats)
        self.owner.build_stats["global_valid_inequalities"] = stats

    def _group_port_demand(self, operation_type: str) -> int:
        try:
            profile = get_operation_port_profile(str(operation_type))
        except KeyError:
            return 0
        return int(
            sum(profile.input_slots.values())
            + sum(profile.output_slots.values())
            + int(profile.generic_input_slots)
            + int(profile.generic_output_slots)
        )

    def _ordered_groups_for_search(self) -> List[Dict[str, Any]]:
        return sorted(
            self.owner._mandatory_groups,
            key=lambda group: (
                int(self._mandatory_group_pose_counts.get(str(group["group_id"]), 0)),
                -self._group_port_demand(str(group.get("operation_type", ""))),
                str(group["facility_type"]),
                str(group["group_id"]),
            ),
        )

    def _add_slot_decision_strategies(self, slot_specs: Sequence[CoordinateSlotSpec]) -> int:
        mode_literals = 0
        for slot in slot_specs:
            if slot.slot_kind == "residual_optional" and slot.active is not None:
                self.model.AddDecisionStrategy([slot.active], cp_model.CHOOSE_FIRST, cp_model.SELECT_MIN_VALUE)
            if slot.slot_kind == "residual_optional" and slot.template == "power_pole":
                if slot.family is not None and self._power_pole_family_order:
                    self.model.AddDecisionStrategy([slot.family], cp_model.CHOOSE_FIRST, cp_model.SELECT_MIN_VALUE)
            else:
                self.model.AddDecisionStrategy([slot.mode], cp_model.CHOOSE_FIRST, cp_model.SELECT_MIN_VALUE)
            self.model.AddDecisionStrategy([slot.x], cp_model.CHOOSE_FIRST, cp_model.SELECT_MIN_VALUE)
            self.model.AddDecisionStrategy([slot.y], cp_model.CHOOSE_FIRST, cp_model.SELECT_MIN_VALUE)
            if not (slot.slot_kind == "residual_optional" and slot.template == "power_pole"):
                mode_literals += int(self._template_mode_literals.get(slot.template, 1))
        return mode_literals

    def _add_search_guidance(self) -> None:
        ordered_groups = self._ordered_groups_for_search()
        mandatory_signature_counts: Dict[str, int] = {}
        required_optional_signature_counts: Dict[str, int] = {}
        mandatory_signature_count_literals = 0
        required_optional_signature_count_literals = 0
        mandatory_mode_literals = 0
        required_optional_mode_literals = 0
        residual_optional_mode_literals = 0
        mandatory_literals = 0
        ghost_literals = 0
        required_optional_literals: Dict[str, int] = {}
        residual_optional_literals: Dict[str, int] = {}
        power_pole_family_count_literals = 0
        power_pole_family_order: List[str] = []
        residual_optional_family_guided = False

        for group in ordered_groups:
            group_id = str(group["group_id"])
            count_vars = [
                self.mandatory_signature_count_vars[group_id][str(bucket["bucket_id"])]
                for bucket in self.owner._mandatory_signature_buckets.get(group_id, [])
                if str(bucket["bucket_id"]) in self.mandatory_signature_count_vars.get(group_id, {})
            ]
            if count_vars:
                self.model.AddDecisionStrategy(count_vars, cp_model.CHOOSE_FIRST, cp_model.SELECT_MAX_VALUE)
            mandatory_signature_counts[group_id] = len(count_vars)
            mandatory_signature_count_literals += len(count_vars)
            mandatory_mode_literals += self._add_slot_decision_strategies(self.mandatory_slots[group_id])
            mandatory_literals += sum(slot.candidate_pose_count for slot in self.mandatory_slots[group_id])

        ordered_ghost_indices = sorted(
            self.owner.u_vars,
            key=lambda rect_idx: (
                int(self.owner._ghost_domains[int(rect_idx)]["anchor"]["x"]),
                int(self.owner._ghost_domains[int(rect_idx)]["anchor"]["y"]),
                int(rect_idx),
            ),
        )
        if ordered_ghost_indices:
            self.model.AddDecisionStrategy(
                [self.owner.u_vars[idx] for idx in ordered_ghost_indices],
                cp_model.CHOOSE_FIRST,
                cp_model.SELECT_MAX_VALUE,
            )
            ghost_literals = len(ordered_ghost_indices)

        required_optional_templates = sorted(self.required_optional_slots)
        for tpl in required_optional_templates:
            count_vars = [
                self.required_optional_signature_count_vars[tpl][str(bucket["bucket_id"])]
                for bucket in self.owner._required_optional_signature_buckets.get(tpl, [])
                if str(bucket["bucket_id"]) in self.required_optional_signature_count_vars.get(tpl, {})
            ]
            if count_vars:
                self.model.AddDecisionStrategy(count_vars, cp_model.CHOOSE_FIRST, cp_model.SELECT_MAX_VALUE)
            required_optional_signature_counts[tpl] = len(count_vars)
            required_optional_signature_count_literals += len(count_vars)
            required_optional_mode_literals += self._add_slot_decision_strategies(self.required_optional_slots[tpl])
            required_optional_literals[tpl] = sum(
                slot.candidate_pose_count for slot in self.required_optional_slots[tpl]
            )

        for tpl, slot_specs in sorted(self.residual_optional_slots.items()):
            if tpl == "power_pole":
                ordered_family_vars = [
                    self.power_pole_family_count_vars[family_name]
                    for family_name in self._power_pole_family_order
                    if family_name in self.power_pole_family_count_vars
                ]
                if ordered_family_vars:
                    self.model.AddDecisionStrategy(
                        ordered_family_vars,
                        cp_model.CHOOSE_FIRST,
                        cp_model.SELECT_MIN_VALUE,
                    )
                    power_pole_family_count_literals = len(ordered_family_vars)
                    power_pole_family_order = list(self._power_pole_family_order)
                    residual_optional_family_guided = True
            residual_optional_mode_literals += self._add_slot_decision_strategies(slot_specs)
            residual_optional_literals[tpl] = sum(slot.candidate_pose_count for slot in slot_specs)

        self.owner.build_stats["search_guidance"] = {
            "applied": True,
            "profile": "exact_coordinate_guided_branching_v4",
            "search_branching": "FIXED_SEARCH",
            "mandatory_group_order": [str(group["group_id"]) for group in ordered_groups],
            "mandatory_signature_counts": {str(k): int(v) for k, v in mandatory_signature_counts.items()},
            "mandatory_signature_count_literals": int(mandatory_signature_count_literals),
            "required_optional_templates": [str(tpl) for tpl in required_optional_templates],
            "required_optional_signature_counts": {str(k): int(v) for k, v in required_optional_signature_counts.items()},
            "required_optional_signature_count_literals": int(required_optional_signature_count_literals),
            "required_optional_default": "SELECT_MAX_VALUE",
            "power_pole_family_order": list(power_pole_family_order),
            "power_pole_family_count_literals": int(power_pole_family_count_literals),
            "residual_optional_family_guided": bool(residual_optional_family_guided),
            "residual_optional_default": "SELECT_MIN_VALUE",
            "mandatory_literals": int(mandatory_literals),
            "ghost_literals": int(ghost_literals),
            "required_optional_literals": {str(k): int(v) for k, v in required_optional_literals.items()},
            "residual_optional_literals": {str(k): int(v) for k, v in residual_optional_literals.items()},
            "optional_literals": {
                **{str(k): int(v) for k, v in required_optional_literals.items()},
                **{str(k): int(v) for k, v in residual_optional_literals.items()},
            },
            "optional_default": "SELECT_MIN_VALUE",
            "mandatory_signature_guided": True,
            "required_optional_signature_guided": True,
            "mandatory_mode_literals": int(mandatory_mode_literals),
            "required_optional_mode_literals": int(required_optional_mode_literals),
            "residual_optional_mode_literals": int(residual_optional_mode_literals),
        }

    def _mode_rect_domains_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "mandatory_groups": {},
            "required_optionals": {},
            "residual_optionals": {},
        }
        for group_id, domains in sorted(self._mandatory_group_mode_rect_domains.items()):
            payload["mandatory_groups"][str(group_id)] = [
                {
                    "mode_id": int(domain.mode_id),
                    "orientation": str(domain.orientation),
                    "port_mode": str(domain.port_mode),
                    "x_min": int(domain.x_min),
                    "x_max": int(domain.x_max),
                    "y_min": int(domain.y_min),
                    "y_max": int(domain.y_max),
                    "pose_count": int(domain.pose_count),
                }
                for _mode_id, domain in sorted(domains.items())
            ]
        for tpl, domains in sorted(self._required_optional_mode_rect_domains.items()):
            payload["required_optionals"][str(tpl)] = [
                {
                    "mode_id": int(domain.mode_id),
                    "orientation": str(domain.orientation),
                    "port_mode": str(domain.port_mode),
                    "x_min": int(domain.x_min),
                    "x_max": int(domain.x_max),
                    "y_min": int(domain.y_min),
                    "y_max": int(domain.y_max),
                    "pose_count": int(domain.pose_count),
                }
                for _mode_id, domain in sorted(domains.items())
            ]
        for tpl in sorted(self.residual_optional_slots):
            domains = self._template_full_mode_rect_domains.get(str(tpl), {})
            payload["residual_optionals"][str(tpl)] = [
                {
                    "mode_id": int(domain.mode_id),
                    "orientation": str(domain.orientation),
                    "port_mode": str(domain.port_mode),
                    "x_min": int(domain.x_min),
                    "x_max": int(domain.x_max),
                    "y_min": int(domain.y_min),
                    "y_max": int(domain.y_max),
                    "pose_count": int(domain.pose_count),
                }
                for _mode_id, domain in sorted(domains.items())
            ]
        return payload

    def _finalize_build_stats(self) -> None:
        slot_counts = {
            "mandatory": int(sum(len(v) for v in self.mandatory_slots.values())),
            "required_optionals": {str(tpl): int(len(v)) for tpl, v in sorted(self.required_optional_slots.items())},
            "residual_optionals": {str(tpl): int(len(v)) for tpl, v in sorted(self.residual_optional_slots.items())},
        }
        interval_count = 2 * (
            sum(len(v) for v in self.mandatory_slots.values())
            + sum(len(v) for v in self.required_optional_slots.values())
            + sum(len(v) for v in self.residual_optional_slots.values())
            + len(self.owner.u_vars)
        )
        guidance = dict(self.owner.build_stats.get("search_guidance", {}))
        mode_literals = int(guidance.get("mandatory_mode_literals", 0)) + int(guidance.get("required_optional_mode_literals", 0)) + int(guidance.get("residual_optional_mode_literals", 0))
        self.owner.build_stats["master_representation"] = self.master_representation
        self.owner.build_stats["master_domain_encoding"] = "mode_rect_factorized_v1"
        self.owner.build_stats["master_domain_table_rows"] = int(self._domain_table_row_count)
        self.owner.build_stats["master_mode_rect_domains"] = self._mode_rect_domains_payload()
        self.owner.build_stats["power_pole_shell_lookup_pairs"] = self._power_pole_shell_payload()
        self.owner.build_stats["master_slot_counts"] = slot_counts
        self.owner.build_stats["master_interval_count"] = int(interval_count)
        self.owner.build_stats["master_mode_literals"] = int(mode_literals)
        self.owner.build_stats["master_pose_bool_literals"] = 0
        proto = self.model.Proto()
        self.owner.build_stats["exact_core_profile"] = {
            "proto_vars": len(proto.variables),
            "proto_constraints": len(proto.constraints),
            "master_representation": self.master_representation,
        }

    def _slot_pose_idx(self, slot: CoordinateSlotSpec) -> int:
        pose_tuple = (
            int(self.owner._solver.Value(slot.x)),
            int(self.owner._solver.Value(slot.y)),
            int(self.owner._solver.Value(slot.mode)),
        )
        pose_idx = slot.tuple_to_pose_idx.get(pose_tuple)
        if pose_idx is None:
            raise KeyError(f"Unknown pose tuple for {slot.key}: {pose_tuple}")
        return int(pose_idx)

    def extract_solution(self) -> Dict[str, Any]:
        solution: Dict[str, Any] = {}
        optional_operations = {"power_pole": "power_supply", "protocol_storage_box": "wireless_sink"}
        for group in self.owner._mandatory_groups:
            group_id = str(group["group_id"])
            tpl = str(group["facility_type"])
            operation_type = str(group["operation_type"])
            selected_pose_indices = sorted(self._slot_pose_idx(slot) for slot in self.mandatory_slots.get(group_id, []))
            for instance_id, pose_idx in zip(sorted(group["instance_ids"]), selected_pose_indices):
                pose = self.owner.facility_pools[tpl][int(pose_idx)]
                solution[str(instance_id)] = {
                    "instance_id": str(instance_id),
                    "facility_type": tpl,
                    "operation_type": operation_type,
                    "pose_idx": int(pose_idx),
                    "pose_id": pose["pose_id"],
                    "anchor": dict(pose["anchor"]),
                    "is_mandatory": True,
                    "bound_type": "exact",
                    "solve_mode": self.owner.solve_mode,
                }
        for tpl, slot_specs in sorted(self.required_optional_slots.items()):
            for pose_idx in sorted(self._slot_pose_idx(slot) for slot in slot_specs):
                pose = self.owner.facility_pools[tpl][int(pose_idx)]
                synthetic_id = f"pose_optional::{tpl}::{pose['pose_id']}"
                solution[synthetic_id] = {
                    "instance_id": synthetic_id,
                    "facility_type": tpl,
                    "operation_type": optional_operations[tpl],
                    "pose_idx": int(pose_idx),
                    "pose_id": pose["pose_id"],
                    "anchor": dict(pose["anchor"]),
                    "is_mandatory": False,
                    "bound_type": "exact_pose_optional",
                    "solve_mode": self.owner.solve_mode,
                }
        for tpl, slot_specs in sorted(self.residual_optional_slots.items()):
            selected = [
                self._slot_pose_idx(slot)
                for slot in slot_specs
                if slot.active is not None and self.owner._solver.Value(slot.active) == 1
            ]
            for pose_idx in sorted(selected):
                pose = self.owner.facility_pools[tpl][int(pose_idx)]
                synthetic_id = f"pose_optional::{tpl}::{pose['pose_id']}"
                solution[synthetic_id] = {
                    "instance_id": synthetic_id,
                    "facility_type": tpl,
                    "operation_type": optional_operations[tpl],
                    "pose_idx": int(pose_idx),
                    "pose_id": pose["pose_id"],
                    "anchor": dict(pose["anchor"]),
                    "is_mandatory": False,
                    "bound_type": "exact_pose_optional",
                    "solve_mode": self.owner.solve_mode,
                }
        return solution

    def apply_solution_hint(self, solution_hint: Mapping[str, int]) -> int:
        hinted = 0
        grouped_hints: DefaultDict[str, List[int]] = defaultdict(list)
        optional_hints: DefaultDict[str, List[int]] = defaultdict(list)
        for solution_id, pose_idx in solution_hint.items():
            if solution_id in self.owner._group_id_by_instance:
                grouped_hints[str(self.owner._group_id_by_instance[solution_id])].append(int(pose_idx))
                continue
            tpl = self.owner._infer_optional_template_from_solution_id(str(solution_id))
            if tpl is not None:
                optional_hints[str(tpl)].append(int(pose_idx))

        for group in self.owner._mandatory_groups:
            group_id = str(group["group_id"])
            tpl = str(group["facility_type"])
            hinted_pose_indices = sorted(grouped_hints.get(group_id, []), key=lambda pose_idx: self.owner._pose_sort_key(tpl, int(pose_idx)))
            for slot, pose_idx in zip(self.mandatory_slots.get(group_id, []), hinted_pose_indices):
                x_val, y_val, mode_id = self._template_pose_tuple_by_idx[tpl][int(pose_idx)]
                self.model.AddHint(slot.x, int(x_val))
                self.model.AddHint(slot.y, int(y_val))
                self.model.AddHint(slot.mode, int(mode_id))
                hinted += 3

        for tpl, slot_specs in self.required_optional_slots.items():
            hinted_pose_indices = sorted(optional_hints.get(str(tpl), []), key=lambda pose_idx: self.owner._pose_sort_key(str(tpl), int(pose_idx)))
            for slot, pose_idx in zip(slot_specs, hinted_pose_indices):
                x_val, y_val, mode_id = self._template_pose_tuple_by_idx[str(tpl)][int(pose_idx)]
                self.model.AddHint(slot.x, int(x_val))
                self.model.AddHint(slot.y, int(y_val))
                self.model.AddHint(slot.mode, int(mode_id))
                hinted += 3

        for tpl, slot_specs in self.residual_optional_slots.items():
            hinted_pose_indices = sorted(optional_hints.get(str(tpl), []), key=lambda pose_idx: self.owner._pose_sort_key(str(tpl), int(pose_idx)))
            for slot_idx, slot in enumerate(slot_specs):
                if slot_idx < len(hinted_pose_indices):
                    pose_idx = hinted_pose_indices[slot_idx]
                    x_val, y_val, mode_id = self._template_pose_tuple_by_idx[str(tpl)][int(pose_idx)]
                    self.model.AddHint(slot.active, 1)
                    self.model.AddHint(slot.x, int(x_val))
                    self.model.AddHint(slot.y, int(y_val))
                    self.model.AddHint(slot.mode, int(mode_id))
                    hinted += 4
                else:
                    self.model.AddHint(slot.active, 0)
                    hinted += 1
        return hinted

    def add_benders_cut(self, conflict_set: Mapping[str, int]) -> bool:
        applied = False
        seen_forbidden: Set[Tuple[str, int, PoseTuple]] = set()
        for solution_id, pose_idx in conflict_set.items():
            pose_idx = int(pose_idx)
            if solution_id in self.owner._group_id_by_instance:
                group_id = str(self.owner._group_id_by_instance[solution_id])
                tpl = next(str(group["facility_type"]) for group in self.owner._mandatory_groups if str(group["group_id"]) == group_id)
                pose_tuple = self._template_pose_tuple_by_idx[tpl].get(int(pose_idx))
                if pose_tuple is None:
                    continue
                for slot in self.mandatory_slots.get(group_id, []):
                    key = (slot.key, int(pose_idx), pose_tuple)
                    if key in seen_forbidden:
                        continue
                    self.model.AddForbiddenAssignments([slot.x, slot.y, slot.mode], [list(pose_tuple)])
                    seen_forbidden.add(key)
                    applied = True
                continue

            tpl = self.owner._infer_optional_template_from_solution_id(str(solution_id))
            if tpl is None:
                continue
            pose_tuple = self._template_pose_tuple_by_idx[str(tpl)].get(int(pose_idx))
            if pose_tuple is None:
                continue
            for slot in self.required_optional_slots.get(str(tpl), []):
                key = (slot.key, int(pose_idx), pose_tuple)
                if key in seen_forbidden:
                    continue
                self.model.AddForbiddenAssignments([slot.x, slot.y, slot.mode], [list(pose_tuple)])
                seen_forbidden.add(key)
                applied = True
            for slot in self.residual_optional_slots.get(str(tpl), []):
                key = (slot.key, int(pose_idx), pose_tuple)
                if key in seen_forbidden:
                    continue
                self.model.AddForbiddenAssignments(
                    [slot.active, slot.x, slot.y, slot.mode],
                    [[1, int(pose_tuple[0]), int(pose_tuple[1]), int(pose_tuple[2])]],
                )
                seen_forbidden.add(key)
                applied = True

        if applied:
            self.owner._last_solution = None
        return applied
