"""Regression tests（回归测试） for project artifacts and exact boundary contracts（严格边界契约）."""

from __future__ import annotations

import json
from pathlib import Path

from ortools.sat.python import cp_model

from src.models.master_model import (
    MasterPlacementModel,
    load_generic_io_requirements_artifact,
    load_project_data,
)
from src.search.benders_loop import (
    compute_exact_static_area_lower_bound,
    compute_mandatory_area_lower_bound,
)
from src.models.cut_manager import RUN_STATUS_UNKNOWN
from src.search.benders_loop import run_benders_for_ghost_rect
from src.search.exact_campaign import ExactCampaign
import src.search.outer_search as outer_search_module
from src.search.outer_search import generate_candidate_sizes, run_outer_search


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _build_empty_frontier_project(project_root: Path) -> Path:
    _write_json(
        project_root / "rules" / "canonical_rules.json",
        {
            "globals": {"grid": {"width": 6, "height": 6}},
            "facility_templates": {},
        },
    )
    _write_json(project_root / "data" / "preprocessed" / "candidate_placements.json", {"facility_pools": {}})
    _write_json(project_root / "data" / "preprocessed" / "mandatory_exact_instances.json", [])
    _write_json(project_root / "data" / "preprocessed" / "all_facility_instances.json", [])
    _write_json(
        project_root / "data" / "preprocessed" / "generic_io_requirements.json",
        {"required_generic_outputs": {}, "required_generic_inputs": {}},
    )
    return project_root



def test_preprocessed_artifacts_exist_and_are_nonempty() -> None:
    project_root = Path(__file__).resolve().parent.parent.parent
    data_dir = project_root / "data" / "preprocessed"
    expected = [
        "commodity_demands.json",
        "machine_counts.json",
        "port_budget.json",
        "candidate_placements.json",
        "all_facility_instances.json",
        "mandatory_exact_instances.json",
        "exploratory_optional_caps.json",
        "generic_io_requirements.json",
    ]
    for filename in expected:
        path = data_dir / filename
        assert path.exists(), f"missing artifact（缺失工件）: {filename}"
        assert path.stat().st_size > 0, f"empty artifact（空工件）: {filename}"



def test_frozen_counts_align_with_new_split() -> None:
    project_root = Path(__file__).resolve().parent.parent.parent
    data_dir = project_root / "data" / "preprocessed"

    machine_counts = json.loads((data_dir / "machine_counts.json").read_text(encoding="utf-8"))
    assert sum(machine_counts.values()) == 219

    mandatory_exact = json.loads((data_dir / "mandatory_exact_instances.json").read_text(encoding="utf-8"))
    all_instances = json.loads((data_dir / "all_facility_instances.json").read_text(encoding="utf-8"))
    caps = json.loads((data_dir / "exploratory_optional_caps.json").read_text(encoding="utf-8"))
    placements = json.loads((data_dir / "candidate_placements.json").read_text(encoding="utf-8"))
    total_poses = sum(len(pool) for pool in placements["facility_pools"].values())

    assert len(mandatory_exact) == 266
    assert len(all_instances) == 326
    assert caps["power_pole"]["cap"] == 50
    assert caps["protocol_storage_box"]["cap"] == 10
    assert total_poses == 81795



def test_generic_io_requirements_are_generated_from_preprocess() -> None:
    project_root = Path(__file__).resolve().parent.parent.parent
    payload = json.loads(
        (project_root / "data" / "preprocessed" / "generic_io_requirements.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["required_generic_outputs"] == {"source_ore": 18, "blue_iron_ore": 34}
    assert payload["required_generic_inputs"] == {"valley_battery": 1, "qiaoyu_capsule": 1}



def test_exact_static_area_lower_bound_excludes_power_pole_area_heuristic() -> None:
    project_root = Path(__file__).resolve().parent.parent.parent
    exact_instances, _pools, rules = load_project_data(project_root, solve_mode="certified_exact")
    exploratory_instances, _pools2, _rules2 = load_project_data(project_root, solve_mode="exploratory")

    lower_bound = compute_mandatory_area_lower_bound(exact_instances, rules)
    manual = 0
    templates = rules["facility_templates"]
    for inst in exact_instances:
        dims = templates[inst["facility_type"]]["dimensions"]
        manual += int(dims["w"]) * int(dims["h"])
    assert lower_bound == manual

    # Adding exploratory optional instances must not change the exact-safe lower bound.
    assert compute_mandatory_area_lower_bound(exploratory_instances, rules) == manual


def test_exact_static_area_lower_bound_includes_protocol_storage_box_minimum_area_lower_bound() -> None:
    project_root = Path(__file__).resolve().parent.parent.parent
    exact_instances, _pools, rules = load_project_data(project_root, solve_mode="certified_exact")
    generic_io_requirements = load_generic_io_requirements_artifact(project_root)

    mandatory_lower_bound = compute_mandatory_area_lower_bound(exact_instances, rules)
    exact_static_lower_bound = compute_exact_static_area_lower_bound(
        exact_instances,
        rules,
        generic_io_requirements,
    )

    assert mandatory_lower_bound == 3544
    assert exact_static_lower_bound == 3553


def test_exact_master_notes_keep_power_pole_area_lower_bound_disabled() -> None:
    model = MasterPlacementModel(
        instances=[],
        facility_pools={"power_pole": [], "protocol_storage_box": []},
        rules={
            "globals": {"grid": {"width": 2, "height": 2}},
            "facility_templates": {
                "power_pole": {"dimensions": {"w": 1, "h": 1}, "needs_power": False},
                "protocol_storage_box": {"dimensions": {"w": 1, "h": 1}, "needs_power": True},
            },
        },
        solve_mode="certified_exact",
    )

    model.build()

    notes = model.build_stats["global_valid_inequalities"]["notes"]
    assert "No power-pole area lower bound is injected into certified exact mode." in notes


def test_exact_optional_cardinality_bounds_align_with_preprocessed_artifacts() -> None:
    project_root = Path(__file__).resolve().parent.parent.parent
    exact_instances, pools, rules = load_project_data(project_root, solve_mode="certified_exact")
    generic_io_requirements = load_generic_io_requirements_artifact(project_root)

    model = MasterPlacementModel(
        exact_instances,
        pools,
        rules,
        solve_mode="certified_exact",
        generic_io_requirements=generic_io_requirements,
    )
    model.build()

    bounds = model.build_stats["global_valid_inequalities"]["optional_cardinality_bounds"]
    guidance = model.build_stats["search_guidance"]
    signature_buckets = model.build_stats["signature_buckets"]["mandatory_groups"]
    family_stats = model.build_stats["global_valid_inequalities"]["power_capacity_families"]
    power_coverage = model.build_stats["power_coverage"]
    exact_core_profile = model.build_stats["exact_core_profile"]
    precompute = model.build_stats["exact_precompute_profile"]
    assert bounds["protocol_storage_box"]["required_generic_input_slots"] == 2
    assert bounds["protocol_storage_box"]["mode"] == "required_lower_bound"
    assert bounds["protocol_storage_box"]["lower"] == 1
    assert bounds["protocol_storage_box"]["upper"] is None
    assert bounds["protocol_storage_box"]["slot_pool_upper_bound"] > 0
    assert bounds["power_pole"]["mandatory_powered_nonpole"] == 219
    assert bounds["power_pole"]["optional_powered_templates"] == ["protocol_storage_box"]
    assert model.build_stats["exact_required_optionals"] == {}
    assert model.build_stats["exact_optional_lower_bounds"] == {"protocol_storage_box": 1}
    assert guidance["profile"] == "exact_coordinate_guided_branching_v4"
    assert guidance["required_optional_templates"] == []
    assert guidance["required_optional_signature_counts"] == {}
    assert guidance["required_optional_signature_count_literals"] == 0
    assert guidance["required_optional_literals"] == {}
    assert guidance["residual_optional_literals"]["protocol_storage_box"] > 0
    assert guidance["power_pole_family_count_literals"] == family_stats["family_count"]
    assert len(guidance["power_pole_family_order"]) == family_stats["family_count"]
    assert guidance["residual_optional_family_guided"] is True
    assert model.build_stats["master_representation"] == "coordinate_exact_v2"
    assert model.build_stats["master_pose_bool_literals"] == 0
    assert model.build_stats["master_domain_encoding"] == "mode_rect_factorized_v1"
    assert model.build_stats["master_domain_table_rows"] == 0
    assert model.build_stats["master_mode_rect_domains"]["required_optionals"] == {}
    assert "protocol_storage_box" in model.build_stats["master_mode_rect_domains"]["residual_optionals"]
    assert model.build_stats["master_slot_counts"]["required_optionals"] == {}
    assert model.build_stats["master_slot_counts"]["residual_optionals"]["protocol_storage_box"] > 0
    assert model.build_stats["power_pole_shell_lookup_pairs"]["pair_count"] > 0
    assert power_coverage["representation"] == "coordinate_geometric"
    assert power_coverage["encoding"] == "geometric_element_witness_v1"
    assert power_coverage["cover_literals"] == 0
    assert power_coverage["witness_indices"] == power_coverage["powered_slots"]
    assert power_coverage["powered_slots"] >= 220
    assert power_coverage["element_constraints"] == power_coverage["powered_slots"] * 3
    assert 2 <= signature_buckets["group::manufacturing_3x3::crusher_blue_iron::1"]["bucket_count"] <= 4
    assert 2 <= signature_buckets["group::manufacturing_5x5::planter_sandleaf::10"]["bucket_count"] <= 4
    assert 2 <= signature_buckets["group::manufacturing_6x4::grinder_dense_blue_iron::14"]["bucket_count"] <= 4
    assert family_stats["applied"] is True
    assert family_stats["family_count"] < family_stats["raw_pole_count"]
    assert family_stats["coefficient_source"] == "exact_rect_dp_cache_v7"
    assert family_stats["shell_pair_count"] < family_stats["raw_pole_count"]
    assert family_stats["compact_signature_class_count"] > 0
    assert precompute["power_capacity_shell_pairs"] == family_stats["shell_pair_count"]
    assert precompute["power_capacity_signature_classes"] > 0
    assert precompute["power_capacity_compact_signature_classes"] > 0
    assert precompute["power_capacity_signature_classes"] < precompute["power_capacity_shell_pair_evaluations"]
    assert (
        precompute["power_capacity_signature_class_evaluations"]
        < precompute["power_capacity_shell_pair_evaluations"]
        < precompute["power_capacity_raw_pole_evaluations"]
    )
    assert (
        precompute["power_capacity_compact_signature_evaluations"]
        <= precompute["power_capacity_signature_class_evaluations"]
    )
    assert precompute["power_capacity_rect_dp_evaluations"] > 0
    assert precompute["power_capacity_rect_dp_cache_misses"] > 0
    assert precompute["power_capacity_rect_dp_state_merges"] > 0
    assert precompute["power_capacity_rect_dp_peak_line_states"] > 0
    assert precompute["power_capacity_rect_dp_peak_pos_states"] > 0
    assert precompute["power_capacity_rect_dp_compiled_signatures"] > 0
    assert precompute["power_capacity_rect_dp_compiled_start_options"] > 0
    assert precompute["power_capacity_rect_dp_deduped_start_options"] > 0
    assert (
        precompute["power_capacity_rect_dp_deduped_start_options"]
        <= precompute["power_capacity_rect_dp_compiled_start_options"]
    )
    assert precompute["power_capacity_rect_dp_compiled_line_subsets"] > 0
    assert precompute["power_capacity_rect_dp_peak_line_subset_options"] > 0
    assert 0 < precompute["power_capacity_rect_dp_v3_fallbacks"] < 131
    assert precompute["power_capacity_m6x4_mixed_cpsat_evaluations"] > 0
    assert precompute["power_capacity_m6x4_mixed_cpsat_selected_cases"] > 0
    assert precompute["power_capacity_m6x4_mixed_cpsat_v3_fallbacks"] == 0
    assert precompute["power_capacity_bitset_oracle_evaluations"] == 0
    assert precompute["power_capacity_bitset_fallbacks"] == 0
    assert precompute["power_capacity_cpsat_fallbacks"] == 0
    assert precompute["power_capacity_oracle"] == "rectangle_frontier_dp_v4"
    assert precompute["power_capacity_shell_pair_evaluations"] < precompute["power_capacity_raw_pole_evaluations"]
    assert precompute["signature_bucket_cache_hits"] > 0
    assert precompute["signature_bucket_distinct_keys"] > 0
    assert precompute["geometry_cache_templates"] > 0
    rectangle_variants = {
        tpl: {
            (variant.width, variant.height)
            for variant in model._ensure_local_rectangle_variants(tpl).values()
            if variant is not None
        }
        for tpl in ("manufacturing_3x3", "manufacturing_5x5", "manufacturing_6x4", "protocol_storage_box")
    }
    assert rectangle_variants["manufacturing_3x3"] == {(3, 3)}
    assert rectangle_variants["manufacturing_5x5"] == {(5, 5)}
    assert rectangle_variants["manufacturing_6x4"] == {(6, 4), (4, 6)}
    assert rectangle_variants["protocol_storage_box"] == {(3, 3)}
    assert model.build_stats["global_valid_inequalities"]["fixed_required_optional_demands"] == {}
    assert model.build_stats["global_valid_inequalities"]["lower_bound_optional_powered_demands"] == {
        "protocol_storage_box": 1
    }
    assert exact_core_profile["proto_vars"] < 64462
    assert exact_core_profile["proto_constraints"] < 280631


def test_campaign_resume_reconstructs_frontier_without_reinvoking_solver(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_root = _build_empty_frontier_project(tmp_path / "resume_frontier")
    calls: list[tuple[int, int]] = []

    def _is_feasible(ghost_w: int, ghost_h: int) -> bool:
        return (ghost_w <= 4 and ghost_h <= 3) or (ghost_w <= 6 and ghost_h <= 2)

    def fake_run_benders_for_ghost_rect(*, ghost_w: int, ghost_h: int, session=None, **kwargs):
        calls.append((ghost_w, ghost_h))
        fake_run_benders_for_ghost_rect.last_run_metadata = {
            "proof_summary": {
                "mode": "certified_exact",
                "master_status": "FEASIBLE" if _is_feasible(ghost_w, ghost_h) else "INFEASIBLE",
            },
            "exact_safe_cuts": [],
            "loaded_exact_safe_cut_count": 0,
            "generated_exact_safe_cut_count": 0,
        }
        if _is_feasible(ghost_w, ghost_h):
            return "CERTIFIED", {
                "ghost_pick": {
                    "pose_idx": 0,
                    "pose_id": f"ghost_{ghost_w}x{ghost_h}",
                    "facility_type": "synthetic",
                }
            }
        return "INFEASIBLE", None

    fake_run_benders_for_ghost_rect.last_run_metadata = {
        "proof_summary": {},
        "exact_safe_cuts": [],
        "loaded_exact_safe_cut_count": 0,
        "generated_exact_safe_cut_count": 0,
    }

    monkeypatch.setattr(outer_search_module, "run_benders_for_ghost_rect", fake_run_benders_for_ghost_rect)
    monkeypatch.setattr(
        outer_search_module.ExactSearchSession,
        "create",
        staticmethod(lambda project_root, solve_mode="certified_exact": object()),
    )

    status, result = run_outer_search(
        project_root=project_root,
        solve_mode="certified_exact",
        max_attempts=64,
        min_side=1,
        area_upper_bound=12,
        max_aspect_ratio=3.0,
        master_seconds=0.01,
        binding_seconds=0.01,
        routing_seconds=0.01,
        benders_max_iter=1,
        campaign_hours=1.0,
        resume_campaign=False,
    )

    assert status == "CERTIFIED"
    assert result is not None
    first_run_calls = list(calls)
    calls.clear()

    status, result = run_outer_search(
        project_root=project_root,
        solve_mode="certified_exact",
        max_attempts=64,
        min_side=1,
        area_upper_bound=12,
        max_aspect_ratio=3.0,
        master_seconds=0.01,
        binding_seconds=0.01,
        routing_seconds=0.01,
        benders_max_iter=1,
        campaign_hours=1.0,
        resume_campaign=True,
    )

    assert status == "CERTIFIED"
    assert result is not None
    assert first_run_calls
    assert calls == []


def test_frontier_resume_reconstructs_same_next_selected_candidate(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_root = _build_empty_frontier_project(tmp_path / "resume_frontier_next_pick")
    calls: list[tuple[int, int]] = []

    def fake_run_benders_for_ghost_rect(*, ghost_w: int, ghost_h: int, session=None, **kwargs):
        calls.append((ghost_w, ghost_h))
        fake_run_benders_for_ghost_rect.last_run_metadata = {
            "proof_summary": {
                "mode": "certified_exact",
                "master_status": "INFEASIBLE",
            },
            "exact_safe_cuts": [],
            "loaded_exact_safe_cut_count": 0,
            "generated_exact_safe_cut_count": 0,
        }
        return "INFEASIBLE", None

    fake_run_benders_for_ghost_rect.last_run_metadata = {
        "proof_summary": {},
        "exact_safe_cuts": [],
        "loaded_exact_safe_cut_count": 0,
        "generated_exact_safe_cut_count": 0,
    }

    monkeypatch.setattr(outer_search_module, "run_benders_for_ghost_rect", fake_run_benders_for_ghost_rect)
    monkeypatch.setattr(
        outer_search_module.ExactSearchSession,
        "create",
        staticmethod(lambda project_root, solve_mode="certified_exact": object()),
    )

    status, result = run_outer_search(
        project_root=project_root,
        solve_mode="certified_exact",
        max_attempts=1,
        min_side=1,
        area_upper_bound=9,
        master_seconds=0.01,
        binding_seconds=0.01,
        routing_seconds=0.01,
        benders_max_iter=1,
        campaign_hours=1.0,
        resume_campaign=False,
    )

    assert status == "UNKNOWN"
    assert result is None
    assert calls == [(6, 1)]

    resumed_campaign = ExactCampaign.load_or_create(project_root, campaign_hours=1.0, resume=True)
    candidates = generate_candidate_sizes(
        max_w=6,
        max_h=6,
        min_side=1,
        area_upper_bound=9,
    )
    frontier_state = outer_search_module._compute_exact_frontier_state(
        candidates,
        resumed_campaign,
        grid_w=6,
        grid_h=6,
    )
    expected_next = frontier_state["selected_candidate"]
    assert expected_next is not None

    calls.clear()
    status, result = run_outer_search(
        project_root=project_root,
        solve_mode="certified_exact",
        max_attempts=1,
        min_side=1,
        area_upper_bound=9,
        master_seconds=0.01,
        binding_seconds=0.01,
        routing_seconds=0.01,
        benders_max_iter=1,
        campaign_hours=1.0,
        resume_campaign=True,
    )

    assert status == "UNKNOWN"
    assert result is None
    assert calls == [(expected_next[1], expected_next[2])]


def test_resume_replays_fine_grained_exact_safe_cuts_into_master(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_root = _build_empty_frontier_project(tmp_path / "resume_fine_grained_cuts")
    campaign = ExactCampaign.load_or_create(project_root, campaign_hours=1.0, resume=False)
    exact_cut = {
        "schema_version": 2,
        "cut_type": "routing_front_blocked_nogood",
        "conflict_set": {"pose_optional::power_pole::pole_0": 0},
        "iteration": 1,
        "metadata": {"kind": "placement_local_nogood"},
        "source_mode": "certified_exact",
        "exact_safe": True,
        "artifact_hashes": campaign.artifact_hashes,
        "proof_stage": "routing",
        "binding_exhausted": False,
        "routing_exhausted": False,
        "proof_summary": {"routing_status": "PRECHECK_FRONT_BLOCKED"},
        "created_at": "2026-03-16T00:00:00Z",
    }
    campaign.mark_candidate_started(1, 1)
    campaign.mark_candidate_result(
        1,
        1,
        RUN_STATUS_UNKNOWN,
        exact_safe_cuts=[exact_cut],
        proof_summary={"master_status": "UNKNOWN"},
        loaded_exact_safe_cut_count=0,
        generated_exact_safe_cut_count=1,
    )
    campaign.save()

    replayed_cuts: list[dict[str, int]] = []

    def fake_add_benders_cut(self, conflict_set):
        replayed_cuts.append(dict(conflict_set))
        return True

    def fake_solve(self, time_limit_seconds: float = 60.0, solution_hint=None, known_feasible_hint: bool = False):
        self.build_stats["last_solve"] = {
            "status": "UNKNOWN",
            "wall_time": 0.0,
            "hinted_literals": 0,
            "known_feasible_hint": bool(known_feasible_hint),
        }
        return cp_model.UNKNOWN

    monkeypatch.setattr(MasterPlacementModel, "add_benders_cut", fake_add_benders_cut)
    monkeypatch.setattr(MasterPlacementModel, "solve", fake_solve)
    monkeypatch.setattr(MasterPlacementModel, "build_greedy_solution_hint", lambda self: {})

    status, result = run_benders_for_ghost_rect(
        ghost_w=1,
        ghost_h=1,
        project_root=project_root,
        solve_mode="certified_exact",
        master_seconds=0.01,
        binding_seconds=0.01,
        routing_seconds=0.01,
        max_iterations=1,
        campaign=campaign,
    )
    metadata = getattr(run_benders_for_ghost_rect, "last_run_metadata")

    assert status == RUN_STATUS_UNKNOWN
    assert result is None
    assert replayed_cuts == [{"pose_optional::power_pole::pole_0": 0}]
    assert metadata["loaded_exact_safe_cut_count"] == 1
