"""Tests for certified exact contracts（严格精确契约测试）."""

from __future__ import annotations

import json
from pathlib import Path

from ortools.sat.python import cp_model

from src.models.binding_subproblem import PortBindingModel
from src.models.cut_manager import (
    RUN_STATUS_CERTIFIED,
    RUN_STATUS_INFEASIBLE,
    RUN_STATUS_UNKNOWN,
    RUN_STATUS_UNPROVEN,
)
from src.models.master_model import MasterPlacementModel
import src.search.benders_loop as benders_loop_module
import src.search.outer_search as outer_search_module
from src.search.benders_loop import collect_certification_blockers, run_benders_for_ghost_rect
from src.search.exact_campaign import ExactCampaign
from src.search.outer_search import generate_candidate_sizes, run_outer_search



def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")



def _build_toy_exact_project(project_root: Path) -> Path:
    data_dir = project_root / "data" / "preprocessed"
    rules_dir = project_root / "rules"

    _write_json(
        rules_dir / "canonical_rules.json",
        {
            "globals": {"grid": {"width": 2, "height": 1}},
            "facility_templates": {
                "tiny_facility": {"dimensions": {"w": 1, "h": 1}, "needs_power": False},
            },
        },
    )
    _write_json(
        data_dir / "candidate_placements.json",
        {
            "facility_pools": {
                "tiny_facility": [
                    {
                        "pose_id": "tiny_left",
                        "anchor": {"x": 0, "y": 0},
                        "occupied_cells": [[0, 0]],
                        "input_port_cells": [],
                        "output_port_cells": [],
                        "power_coverage_cells": None,
                    }
                ]
            }
        },
    )
    mandatory_instances = [
        {
            "instance_id": "tiny_001",
            "facility_type": "tiny_facility",
            "is_mandatory": True,
            "bound_type": "exact",
            "solve_modes": ["certified_exact"],
        }
    ]
    _write_json(data_dir / "mandatory_exact_instances.json", mandatory_instances)
    _write_json(data_dir / "all_facility_instances.json", mandatory_instances)
    _write_json(
        data_dir / "generic_io_requirements.json",
        {
            "required_generic_outputs": {},
            "required_generic_inputs": {},
        },
    )
    return project_root


def _build_required_protocol_box_project(project_root: Path) -> Path:
    data_dir = project_root / "data" / "preprocessed"
    rules_dir = project_root / "rules"

    _write_json(
        rules_dir / "canonical_rules.json",
        {
            "globals": {"grid": {"width": 2, "height": 2}},
            "facility_templates": {
                "power_pole": {"dimensions": {"w": 1, "h": 1}, "needs_power": False},
                "protocol_storage_box": {"dimensions": {"w": 1, "h": 1}, "needs_power": True},
            },
        },
    )
    _write_json(
        data_dir / "candidate_placements.json",
        {
            "facility_pools": {
                "power_pole": [
                    {
                        "pose_id": "pole_0",
                        "anchor": {"x": 1, "y": 1},
                        "occupied_cells": [[1, 1]],
                        "input_port_cells": [],
                        "output_port_cells": [],
                        "power_coverage_cells": [[0, 0]],
                    }
                ],
                "protocol_storage_box": [
                    {
                        "pose_id": "box_0",
                        "anchor": {"x": 0, "y": 0},
                        "occupied_cells": [[0, 0]],
                        "input_port_cells": [{"x": 0, "y": 1, "dir": "N"}],
                        "output_port_cells": [],
                        "power_coverage_cells": None,
                    }
                ],
            }
        },
    )
    _write_json(data_dir / "mandatory_exact_instances.json", [])
    _write_json(data_dir / "all_facility_instances.json", [])
    _write_json(
        data_dir / "generic_io_requirements.json",
        {
            "required_generic_outputs": {},
            "required_generic_inputs": {"valley_battery": 1},
        },
    )
    return project_root


def _build_multi_pose_exact_project(
    project_root: Path,
    *,
    pose_anchors: list[int],
    include_pole_block: bool = False,
) -> Path:
    data_dir = project_root / "data" / "preprocessed"
    rules_dir = project_root / "rules"
    grid_width = max(pose_anchors + ([1] if include_pole_block else [0])) + 3

    facility_templates = {
        "tiny_facility": {"dimensions": {"w": 1, "h": 1}, "needs_power": False},
    }
    pools: dict[str, list[dict]] = {
        "tiny_facility": [
            {
                "pose_id": f"tiny_{anchor}",
                "anchor": {"x": anchor, "y": 0},
                "occupied_cells": [[anchor, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            }
            for anchor in pose_anchors
        ]
    }
    if include_pole_block:
        facility_templates["power_pole"] = {
            "dimensions": {"w": 1, "h": 1},
            "needs_power": False,
        }
        pools["power_pole"] = [
            {
                "pose_id": "pole_block",
                "anchor": {"x": 1, "y": 0},
                "occupied_cells": [[1, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": [[1, 0]],
            }
        ]
        pools["protocol_storage_box"] = []

    _write_json(
        rules_dir / "canonical_rules.json",
        {
            "globals": {"grid": {"width": grid_width, "height": 1}},
            "facility_templates": facility_templates,
        },
    )
    _write_json(data_dir / "candidate_placements.json", {"facility_pools": pools})
    mandatory_instances = [
        {
            "instance_id": "tiny_001",
            "facility_type": "tiny_facility",
            "is_mandatory": True,
            "bound_type": "exact",
            "solve_modes": ["certified_exact"],
        }
    ]
    _write_json(data_dir / "mandatory_exact_instances.json", mandatory_instances)
    _write_json(data_dir / "all_facility_instances.json", mandatory_instances)
    _write_json(
        data_dir / "generic_io_requirements.json",
        {
            "required_generic_outputs": {},
            "required_generic_inputs": {},
        },
    )
    return project_root


def _build_frontier_project(project_root: Path, *, width: int = 6, height: int = 6) -> Path:
    data_dir = project_root / "data" / "preprocessed"
    rules_dir = project_root / "rules"

    _write_json(
        rules_dir / "canonical_rules.json",
        {
            "globals": {"grid": {"width": width, "height": height}},
            "facility_templates": {},
        },
    )
    _write_json(data_dir / "candidate_placements.json", {"facility_pools": {}})
    _write_json(data_dir / "mandatory_exact_instances.json", [])
    _write_json(data_dir / "all_facility_instances.json", [])
    _write_json(
        data_dir / "generic_io_requirements.json",
        {
            "required_generic_outputs": {},
            "required_generic_inputs": {},
        },
    )
    return project_root


def _read_campaign_state(project_root: Path) -> dict:
    return json.loads(
        (project_root / "data" / "checkpoints" / "exact_campaign_state.json").read_text(
            encoding="utf-8"
        )
    )



def test_certified_exact_rejects_provisional_instances() -> None:
    blockers = collect_certification_blockers(
        instances=[
            {
                "instance_id": "power_pole_001",
                "facility_type": "power_pole",
                "operation_type": "power_supply",
                "is_mandatory": False,
                "bound_type": "provisional",
                "solve_mode": "exploratory",
            }
        ],
        solve_mode="certified_exact",
    )
    codes = {item["code"] for item in blockers}
    assert "provisional_instance_forbidden" in codes
    assert "non_mandatory_instance_forbidden" in codes
    assert "instance_mode_pollution" in codes


def test_collect_certification_blockers_accepts_certified_exact_mode_metadata() -> None:
    blockers = collect_certification_blockers(
        instances=[
            {
                "instance_id": "tiny_001",
                "facility_type": "tiny_facility",
                "operation_type": "processing",
                "is_mandatory": True,
                "bound_type": "exact",
                "solve_mode": "certified_exact",
            }
        ],
        solve_mode="certified_exact",
    )

    assert blockers == []


def test_collect_certification_blockers_accepts_certified_exact_in_solve_modes_list() -> None:
    blockers = collect_certification_blockers(
        instances=[
            {
                "instance_id": "tiny_001",
                "facility_type": "tiny_facility",
                "operation_type": "processing",
                "is_mandatory": True,
                "bound_type": "exact",
                "solve_modes": ["certified_exact"],
            }
        ],
        solve_mode="certified_exact",
    )

    assert blockers == []


def test_collect_certification_blockers_accepts_certified_exact_in_mixed_solve_modes_list() -> None:
    blockers = collect_certification_blockers(
        instances=[
            {
                "instance_id": "tiny_001",
                "facility_type": "tiny_facility",
                "operation_type": "processing",
                "is_mandatory": True,
                "bound_type": "exact",
                "solve_modes": ["certified_exact", "exploratory"],
            }
        ],
        solve_mode="certified_exact",
    )

    assert blockers == []


def test_collect_certification_blockers_rejects_exploratory_only_mode_metadata() -> None:
    blockers = collect_certification_blockers(
        instances=[
            {
                "instance_id": "tiny_001",
                "facility_type": "tiny_facility",
                "operation_type": "processing",
                "is_mandatory": True,
                "bound_type": "exact",
                "solve_mode": "exploratory",
            }
        ],
        solve_mode="certified_exact",
    )

    assert [item["code"] for item in blockers] == ["instance_mode_pollution"]

    blockers = collect_certification_blockers(
        instances=[
            {
                "instance_id": "tiny_002",
                "facility_type": "tiny_facility",
                "operation_type": "processing",
                "is_mandatory": True,
                "bound_type": "exact",
                "solve_modes": ["exploratory"],
            }
        ],
        solve_mode="certified_exact",
    )

    assert [item["code"] for item in blockers] == ["instance_mode_pollution"]


def test_collect_certification_blockers_rejects_missing_or_malformed_mode_metadata() -> None:
    missing_blockers = collect_certification_blockers(
        instances=[
            {
                "instance_id": "tiny_missing",
                "facility_type": "tiny_facility",
                "operation_type": "processing",
                "is_mandatory": True,
                "bound_type": "exact",
            }
        ],
        solve_mode="certified_exact",
    )
    malformed_blockers = collect_certification_blockers(
        instances=[
            {
                "instance_id": "tiny_bad",
                "facility_type": "tiny_facility",
                "operation_type": "processing",
                "is_mandatory": True,
                "bound_type": "exact",
                "solve_modes": ["certified_exact", 7],
            },
            {
                "instance_id": "tiny_unknown",
                "facility_type": "tiny_facility",
                "operation_type": "processing",
                "is_mandatory": True,
                "bound_type": "exact",
                "solve_modes": ["unknown_mode"],
            },
        ],
        solve_mode="certified_exact",
    )

    assert [item["code"] for item in missing_blockers] == ["instance_mode_pollution"]
    assert [item["code"] for item in malformed_blockers] == [
        "instance_mode_pollution",
        "instance_mode_pollution",
    ]


def test_collect_certification_blockers_rejects_conflicting_mode_metadata() -> None:
    blockers = collect_certification_blockers(
        instances=[
            {
                "instance_id": "tiny_conflict_1",
                "facility_type": "tiny_facility",
                "operation_type": "processing",
                "is_mandatory": True,
                "bound_type": "exact",
                "solve_mode": "exploratory",
                "solve_modes": ["certified_exact"],
            },
            {
                "instance_id": "tiny_conflict_2",
                "facility_type": "tiny_facility",
                "operation_type": "processing",
                "is_mandatory": True,
                "bound_type": "exact",
                "solve_mode": "certified_exact",
                "solve_modes": ["exploratory"],
            },
        ],
        solve_mode="certified_exact",
    )

    assert [item["code"] for item in blockers] == [
        "instance_mode_pollution",
        "instance_mode_pollution",
    ]
    assert all("conflicting_mode_metadata" in str(item["detail"]) for item in blockers)


def test_collect_certification_blockers_accepts_matching_dual_mode_metadata() -> None:
    blockers = collect_certification_blockers(
        instances=[
            {
                "instance_id": "tiny_safe",
                "facility_type": "tiny_facility",
                "operation_type": "processing",
                "is_mandatory": True,
                "bound_type": "exact",
                "solve_mode": "certified_exact",
                "solve_modes": ["certified_exact"],
            }
        ],
        solve_mode="certified_exact",
    )

    assert blockers == []


def test_collect_certification_blockers_rejects_matching_exploratory_dual_mode_metadata() -> None:
    blockers = collect_certification_blockers(
        instances=[
            {
                "instance_id": "tiny_exploratory_dual",
                "facility_type": "tiny_facility",
                "operation_type": "processing",
                "is_mandatory": True,
                "bound_type": "exact",
                "solve_mode": "exploratory",
                "solve_modes": ["exploratory"],
            }
        ],
        solve_mode="certified_exact",
    )

    assert [item["code"] for item in blockers] == ["instance_mode_pollution"]



def test_binding_recognizes_pose_optional_protocol_storage_box() -> None:
    placement_solution = {
        "boundary_port_001": {
            "pose_idx": 0,
            "pose_id": "boundary_pose_0",
            "anchor": {"x": 0, "y": 0},
            "facility_type": "boundary_storage_port",
        },
        "pose_optional::protocol_storage_box::box_pose_0": {
            "pose_idx": 0,
            "pose_id": "box_pose_0",
            "anchor": {"x": 2, "y": 0},
            "facility_type": "protocol_storage_box",
        },
    }
    facility_pools = {
        "boundary_storage_port": [
            {
                "pose_id": "boundary_pose_0",
                "anchor": {"x": 0, "y": 0},
                "occupied_cells": [[0, 0]],
                "input_port_cells": [],
                "output_port_cells": [{"x": 0, "y": 0, "dir": "E"}],
                "power_coverage_cells": None,
            }
        ],
        "protocol_storage_box": [
            {
                "pose_id": "box_pose_0",
                "anchor": {"x": 2, "y": 0},
                "occupied_cells": [[2, 0]],
                "input_port_cells": [{"x": 2, "y": 0, "dir": "W"}],
                "output_port_cells": [],
                "power_coverage_cells": None,
            }
        ],
    }
    instances = [
        {
            "instance_id": "boundary_port_001",
            "facility_type": "boundary_storage_port",
            "operation_type": "boundary_io",
            "is_mandatory": True,
            "bound_type": "exact",
        }
    ]

    model = PortBindingModel(
        placement_solution,
        facility_pools,
        instances,
        required_generic_outputs={"source_ore": 1},
        required_generic_inputs={"valley_battery": 1},
    )
    model.build()
    assert model.solve(time_limit_seconds=5.0) == "FEASIBLE"

    specs = model.extract_port_specs()
    assert any(spec["instance_id"] == "pose_optional::protocol_storage_box::box_pose_0" for spec in specs)
    assert any(spec["commodity"] == "valley_battery" for spec in specs)



def test_timeout_returns_unknown(monkeypatch, tmp_path: Path) -> None:
    project_root = _build_toy_exact_project(tmp_path / "toy_timeout")

    def _always_unknown(self, *args, **kwargs):
        return cp_model.UNKNOWN

    monkeypatch.setattr(MasterPlacementModel, "solve", _always_unknown)
    status, _result = run_benders_for_ghost_rect(
        ghost_w=1,
        ghost_h=1,
        project_root=project_root,
        solve_mode="certified_exact",
        master_seconds=0.01,
        binding_seconds=0.01,
        routing_seconds=0.01,
        max_iterations=1,
    )
    assert status == RUN_STATUS_UNKNOWN



def test_campaign_resume_requires_matching_hashes(tmp_path: Path) -> None:
    project_root = _build_toy_exact_project(tmp_path / "campaign_hash")
    campaign = ExactCampaign.load_or_create(project_root, campaign_hours=1.0, resume=False)
    campaign.save()

    _write_json(
        project_root / "data" / "preprocessed" / "generic_io_requirements.json",
        {
            "required_generic_outputs": {"ore": 1},
            "required_generic_inputs": {},
        },
    )
    resumed = ExactCampaign.load_or_create(project_root, campaign_hours=1.0, resume=True)
    assert resumed.resumed is False
    assert resumed.compatible_hashes is False
    assert resumed.reset_reason == "artifact_hash_mismatch"


def test_campaign_resume_resets_on_schema_mismatch(tmp_path: Path) -> None:
    project_root = _build_toy_exact_project(tmp_path / "campaign_schema_mismatch")
    campaign_path = project_root / "data" / "checkpoints" / "exact_campaign_state.json"
    campaign_path.parent.mkdir(parents=True, exist_ok=True)
    campaign_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "solve_mode": "certified_exact",
                "campaign_hours": 1.0,
                "created_at": "2026-03-16T00:00:00Z",
                "updated_at": "2026-03-16T00:00:00Z",
                "artifact_hashes": ExactCampaign.load_or_create(
                    project_root,
                    campaign_hours=1.0,
                    resume=False,
                ).artifact_hashes,
                "proof_summary_schema_version": 1,
                "reset_reason": None,
                "final_result": None,
                "final_status": None,
                "last_stop_reason": None,
                "candidates": {},
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    resumed = ExactCampaign.load_or_create(project_root, campaign_hours=1.0, resume=True)
    assert resumed.resumed is False
    assert resumed.compatible_hashes is False
    assert resumed.reset_reason == "schema_version_mismatch"


def test_campaign_resume_keeps_valid_candidates(tmp_path: Path) -> None:
    project_root = _build_toy_exact_project(tmp_path / "campaign_keep_valid")
    campaign = ExactCampaign.load_or_create(project_root, campaign_hours=1.0, resume=False)
    campaign.mark_candidate_started(1, 1)
    campaign.mark_candidate_result(
        1,
        1,
        RUN_STATUS_INFEASIBLE,
        proof_summary={"reason": "toy_infeasible"},
        exact_safe_cuts=[],
        loaded_exact_safe_cut_count=0,
        generated_exact_safe_cut_count=0,
    )
    campaign.mark_candidate_started(2, 1)
    campaign.mark_candidate_result(
        2,
        1,
        RUN_STATUS_CERTIFIED,
        solution={"tiny_001": {"pose_idx": 0, "pose_id": "tiny_left", "facility_type": "tiny_facility"}},
        proof_summary={"reason": "toy_certified"},
        exact_safe_cuts=[],
        loaded_exact_safe_cut_count=0,
        generated_exact_safe_cut_count=0,
    )
    campaign.save()

    resumed = ExactCampaign.load_or_create(project_root, campaign_hours=1.0, resume=True)
    assert resumed.resumed is True
    assert resumed.compatible_hashes is True
    assert resumed.get_candidate_record(1, 1)["status"] == RUN_STATUS_INFEASIBLE
    assert resumed.get_candidate_record(2, 1)["status"] == RUN_STATUS_CERTIFIED
    assert resumed.best_certified_result()["ghost_rect"] == {"w": 2, "h": 1, "area": 2}



def test_toy_project_can_be_truly_certified(tmp_path: Path) -> None:
    project_root = _build_toy_exact_project(tmp_path / "toy_certified")
    status, result = run_outer_search(
        project_root=project_root,
        solve_mode="certified_exact",
        max_attempts=1,
        min_side=1,
        area_upper_bound=1,
        master_seconds=5.0,
        binding_seconds=5.0,
        routing_seconds=5.0,
        benders_max_iter=5,
        campaign_hours=1.0,
        resume_campaign=False,
    )
    assert status == RUN_STATUS_CERTIFIED
    assert result is not None
    assert result["ghost_rect"] == {"w": 1, "h": 1, "area": 1}
    state = _read_campaign_state(project_root)
    candidate = state["candidates"]["1x1"]
    assert state["final_status"] == RUN_STATUS_CERTIFIED
    assert candidate["status"] == RUN_STATUS_CERTIFIED
    assert candidate["finished_at"] is not None


def test_area_precheck_accounts_for_fixed_required_protocol_storage_box(
    tmp_path: Path,
) -> None:
    project_root = _build_required_protocol_box_project(tmp_path / "required_box_area_precheck")

    status, result = run_benders_for_ghost_rect(
        ghost_w=2,
        ghost_h=2,
        project_root=project_root,
        solve_mode="certified_exact",
        master_seconds=5.0,
        binding_seconds=5.0,
        routing_seconds=5.0,
        max_iterations=1,
    )
    metadata = getattr(run_benders_for_ghost_rect, "last_run_metadata")

    assert status == RUN_STATUS_INFEASIBLE
    assert result is None
    assert metadata["proof_summary"]["master_status"] == "AREA_PRECHECK_FAILED"
    assert metadata["generated_exact_safe_cut_count"] == 0


def test_outer_search_safe_area_upper_bound_accounts_for_fixed_required_protocol_storage_box(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_root = _build_required_protocol_box_project(tmp_path / "required_box_outer_search")
    calls: list[tuple[int, int]] = []

    def fake_run_benders_for_ghost_rect(*, ghost_w: int, ghost_h: int, session=None, **kwargs):
        del session, kwargs
        calls.append((ghost_w, ghost_h))
        fake_run_benders_for_ghost_rect.last_run_metadata = {
            "proof_summary": {"mode": "certified_exact", "master_status": "INFEASIBLE"},
            "exact_safe_cuts": [],
            "loaded_exact_safe_cut_count": 0,
            "generated_exact_safe_cut_count": 0,
        }
        return RUN_STATUS_INFEASIBLE, None

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
        max_attempts=8,
        min_side=1,
        master_seconds=0.01,
        binding_seconds=0.01,
        routing_seconds=0.01,
        benders_max_iter=1,
        campaign_hours=1.0,
        resume_campaign=False,
    )

    assert status == RUN_STATUS_INFEASIBLE
    assert result is None
    assert (2, 2) not in calls
    assert all((ghost_w * ghost_h) <= 3 for ghost_w, ghost_h in calls)


def test_exact_mode_uses_greedy_warm_start(tmp_path: Path) -> None:
    project_root = _build_toy_exact_project(tmp_path / "toy_greedy_hint")

    status, result = run_benders_for_ghost_rect(
        ghost_w=1,
        ghost_h=1,
        project_root=project_root,
        solve_mode="certified_exact",
        master_seconds=5.0,
        binding_seconds=5.0,
        routing_seconds=5.0,
        max_iterations=2,
    )
    metadata = getattr(run_benders_for_ghost_rect, "last_run_metadata")

    assert status == RUN_STATUS_CERTIFIED
    assert result is not None
    assert metadata["proof_summary"]["used_greedy_hint"] is True
    assert metadata["proof_summary"]["greedy_hint_instances"] == 1
    assert metadata["proof_summary"]["master_hinted_literals"] > 0


def test_ghost_rect_can_screen_high_capacity_pole_in_exact_master() -> None:
    instances = [
        {
            "instance_id": "powered_001",
            "facility_type": "powered_machine",
            "operation_type": "processing",
            "is_mandatory": True,
            "bound_type": "exact",
        },
        {
            "instance_id": "powered_002",
            "facility_type": "powered_machine",
            "operation_type": "processing",
            "is_mandatory": True,
            "bound_type": "exact",
        },
    ]
    pools = {
        "power_pole": [
            {
                "pose_id": "pole_high",
                "anchor": {"x": 0, "y": 1},
                "occupied_cells": [[0, 1]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": [[0, 0], [1, 0], [3, 0], [4, 0]],
            },
            {
                "pose_id": "pole_low",
                "anchor": {"x": 5, "y": 1},
                "occupied_cells": [[5, 1]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": [[0, 0], [1, 0], [2, 0]],
            },
        ],
        "protocol_storage_box": [],
        "powered_machine": [
            {
                "pose_id": "machine_a",
                "anchor": {"x": 0, "y": 0},
                "occupied_cells": [[0, 0], [1, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
            {
                "pose_id": "machine_b",
                "anchor": {"x": 1, "y": 0},
                "occupied_cells": [[1, 0], [2, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
            {
                "pose_id": "machine_c",
                "anchor": {"x": 3, "y": 0},
                "occupied_cells": [[3, 0], [4, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
        ],
    }
    rules = {
        "globals": {"grid": {"width": 6, "height": 2}},
        "facility_templates": {
            "power_pole": {"dimensions": {"w": 1, "h": 1}, "needs_power": False},
            "protocol_storage_box": {"dimensions": {"w": 1, "h": 1}, "needs_power": True},
            "powered_machine": {"dimensions": {"w": 2, "h": 1}, "needs_power": True},
        },
    }

    baseline_model = MasterPlacementModel(
        instances,
        pools,
        rules,
        solve_mode="certified_exact",
    )
    baseline_model.build()
    assert baseline_model.solve(time_limit_seconds=5.0) in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    ghost_model = MasterPlacementModel(
        instances,
        pools,
        rules,
        solve_mode="certified_exact",
        ghost_rect=(1, 1),
    )
    ghost_model.build()
    forced_anchor_idx = next(
        idx
        for idx, domain in enumerate(ghost_model._ghost_domains)
        if domain["anchor"] == {"x": 0, "y": 1}
    )
    ghost_model.model.Add(ghost_model.u_vars[forced_anchor_idx] == 1)
    stats = ghost_model.build_stats["global_valid_inequalities"]

    assert stats["ghost_aware_via_pole_feasibility"]["enabled"] is True
    assert stats["capacity_coeff_stats"]["powered_machine"]["max_coeff"] == 2
    assert stats["capacity_coeff_stats"]["powered_machine"]["min_nonzero_coeff"] == 1
    assert ghost_model.solve(time_limit_seconds=5.0) == cp_model.INFEASIBLE


def test_exact_mode_uses_flow_only_as_diagnostic(monkeypatch, tmp_path: Path) -> None:
    project_root = _build_toy_exact_project(tmp_path / "toy_flow_diag")

    monkeypatch.setattr(
        benders_loop_module.FlowSubproblem,
        "build_and_solve",
        lambda self, time_limit_ms=10000: "INFEASIBLE",
    )

    status, result = run_benders_for_ghost_rect(
        ghost_w=1,
        ghost_h=1,
        project_root=project_root,
        solve_mode="certified_exact",
        master_seconds=5.0,
        binding_seconds=5.0,
        routing_seconds=5.0,
        flow_seconds=1.0,
        max_iterations=2,
    )
    metadata = getattr(run_benders_for_ghost_rect, "last_run_metadata")

    assert status == RUN_STATUS_CERTIFIED
    assert result is not None
    assert metadata["proof_summary"]["diagnostic_flow_status"] == "INFEASIBLE"
    assert metadata["exact_safe_cuts"] == []
    assert metadata["loaded_exact_safe_cut_count"] == 0
    assert metadata["generated_exact_safe_cut_count"] == 0
    assert metadata["diagnostic_flow_status"] == "INFEASIBLE"


def test_binding_infeasible_generates_exact_safe_whole_layout_cut(monkeypatch, tmp_path: Path) -> None:
    project_root = _build_toy_exact_project(tmp_path / "toy_binding_infeasible")

    class FakeBindingModel:
        def __init__(self, *args, **kwargs):
            self._summary = {"fake": "binding_infeasible"}

        def build(self) -> None:
            return None

        def solve(self, time_limit_seconds: float = 30.0) -> str:
            return "INFEASIBLE"

        def extract_conflict_summary(self) -> dict:
            return dict(self._summary)

    monkeypatch.setattr(benders_loop_module, "PortBindingModel", FakeBindingModel)

    status, result = run_benders_for_ghost_rect(
        ghost_w=1,
        ghost_h=1,
        project_root=project_root,
        solve_mode="certified_exact",
        master_seconds=5.0,
        binding_seconds=5.0,
        routing_seconds=5.0,
        max_iterations=2,
    )
    metadata = getattr(run_benders_for_ghost_rect, "last_run_metadata")
    cuts = metadata["exact_safe_cuts"]

    assert status == RUN_STATUS_INFEASIBLE
    assert result is None
    assert len(cuts) == 1
    assert cuts[0]["cut_type"] == "binding_infeasible_nogood"
    assert cuts[0]["proof_stage"] == "binding"
    assert cuts[0]["binding_exhausted"] is True
    assert cuts[0]["routing_exhausted"] is False
    assert metadata["loaded_exact_safe_cut_count"] == 0
    assert metadata["generated_exact_safe_cut_count"] == 1


def test_routing_exhaustion_generates_exact_safe_whole_layout_cut(monkeypatch, tmp_path: Path) -> None:
    project_root = _build_toy_exact_project(tmp_path / "toy_routing_exhausted")

    selections = [
        {
            "binding_choice": {"tiny_001": 0},
            "generic_inputs": {},
            "generic_outputs": {},
        },
        {
            "binding_choice": {"tiny_001": 1},
            "generic_inputs": {},
            "generic_outputs": {},
        },
    ]

    class FakeBindingModel:
        def __init__(self, *args, **kwargs):
            self.index = 0
            self.binding_vars = {"tiny_001": {0: object(), 1: object()}}
            self.generic_input_vars = {}
            self.generic_output_vars = {}

        def build(self) -> None:
            return None

        def solve(self, time_limit_seconds: float = 30.0) -> str:
            if self.index < len(selections):
                return "FEASIBLE"
            return "INFEASIBLE"

        def extract_selection(self) -> dict:
            return dict(selections[self.index])

        def extract_port_specs(self) -> list[dict]:
            return []

        def add_nogood_cut(self, selection: dict) -> None:
            assert selection == selections[self.index]
            self.index += 1

        def extract_conflict_summary(self) -> dict:
            return {"enumerated": self.index}

    class FakeRoutingGrid:
        def __init__(self, occupied_cells, port_specs):
            self.occupied_cells = occupied_cells
            self.port_specs = port_specs

    class FakeRoutingSubproblem:
        solve_calls = 0

        def __init__(self, grid, commodities):
            self.grid = grid
            self.commodities = commodities
            self.build_stats = {"fake": "routing"}

        def build(self) -> None:
            return None

        def solve(self, time_limit: float = 60.0) -> str:
            FakeRoutingSubproblem.solve_calls += 1
            return "INFEASIBLE"

    monkeypatch.setattr(benders_loop_module, "PortBindingModel", FakeBindingModel)
    monkeypatch.setattr(benders_loop_module, "RoutingGrid", FakeRoutingGrid)
    monkeypatch.setattr(benders_loop_module, "RoutingSubproblem", FakeRoutingSubproblem)

    status, result = run_benders_for_ghost_rect(
        ghost_w=1,
        ghost_h=1,
        project_root=project_root,
        solve_mode="certified_exact",
        master_seconds=5.0,
        binding_seconds=5.0,
        routing_seconds=5.0,
        max_iterations=2,
    )
    metadata = getattr(run_benders_for_ghost_rect, "last_run_metadata")
    cuts = metadata["exact_safe_cuts"]

    assert status == RUN_STATUS_INFEASIBLE
    assert result is None
    assert FakeRoutingSubproblem.solve_calls == 2
    assert len(cuts) == 1
    assert cuts[0]["cut_type"] == "routing_exhausted_nogood"
    assert cuts[0]["proof_stage"] == "routing"
    assert cuts[0]["binding_exhausted"] is True
    assert cuts[0]["routing_exhausted"] is True
    assert metadata["proof_summary"]["enumerated_bindings"] == 2
    assert metadata["proof_summary"]["routing_attempts"] == 2
    assert metadata["loaded_exact_safe_cut_count"] == 0
    assert metadata["generated_exact_safe_cut_count"] == 1


def test_routing_timeout_returns_unknown_without_exact_safe_cut(monkeypatch, tmp_path: Path) -> None:
    project_root = _build_toy_exact_project(tmp_path / "toy_routing_timeout")

    class FakeBindingModel:
        def __init__(self, *args, **kwargs):
            self.binding_vars = {}
            self.generic_input_vars = {}
            self.generic_output_vars = {}

        def build(self) -> None:
            return None

        def solve(self, time_limit_seconds: float = 30.0) -> str:
            return "FEASIBLE"

        def extract_selection(self) -> dict:
            return {
                "binding_choice": {"tiny_001": 0},
                "generic_inputs": {},
                "generic_outputs": {},
            }

        def extract_port_specs(self) -> list[dict]:
            return []

        def extract_conflict_summary(self) -> dict:
            return {"fake": "timeout"}

    class FakeRoutingGrid:
        def __init__(self, occupied_cells, port_specs):
            self.occupied_cells = occupied_cells
            self.port_specs = port_specs

    class FakeRoutingSubproblem:
        def __init__(self, grid, commodities):
            self.build_stats = {"fake": "timeout"}

        def build(self) -> None:
            return None

        def solve(self, time_limit: float = 60.0) -> str:
            return "TIMEOUT"

    monkeypatch.setattr(benders_loop_module, "PortBindingModel", FakeBindingModel)
    monkeypatch.setattr(benders_loop_module, "RoutingGrid", FakeRoutingGrid)
    monkeypatch.setattr(benders_loop_module, "RoutingSubproblem", FakeRoutingSubproblem)

    status, result = run_benders_for_ghost_rect(
        ghost_w=1,
        ghost_h=1,
        project_root=project_root,
        solve_mode="certified_exact",
        master_seconds=5.0,
        binding_seconds=5.0,
        routing_seconds=5.0,
        max_iterations=2,
    )
    metadata = getattr(run_benders_for_ghost_rect, "last_run_metadata")

    assert status == RUN_STATUS_UNKNOWN
    assert result is None
    assert metadata["exact_safe_cuts"] == []
    assert metadata["loaded_exact_safe_cut_count"] == 0
    assert metadata["generated_exact_safe_cut_count"] == 0


def test_binding_domain_empty_generates_singleton_cut_and_continues_master_loop(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_root = _build_multi_pose_exact_project(
        tmp_path / "binding_domain_empty_continue",
        pose_anchors=[0, 2],
    )

    def fake_master_solve(self, time_limit_seconds: float = 60.0, solution_hint=None, known_feasible_hint: bool = False):
        solve_calls = int(getattr(self, "_test_solve_calls", 0)) + 1
        self._test_solve_calls = solve_calls
        self.build_stats["last_solve"] = {
            "status": "FEASIBLE",
            "wall_time": 0.0,
            "hinted_literals": 0,
            "known_feasible_hint": bool(known_feasible_hint),
        }
        return cp_model.FEASIBLE

    def fake_extract_solution(self):
        pose_idx = 0 if int(getattr(self, "_test_solve_calls", 0)) <= 1 else 1
        pose = self.facility_pools["tiny_facility"][pose_idx]
        return {
            "tiny_001": {
                "pose_idx": pose_idx,
                "pose_id": pose["pose_id"],
                "anchor": dict(pose["anchor"]),
                "facility_type": "tiny_facility",
            }
        }

    class FakeBindingModel:
        def __init__(self, placement_solution, *args, **kwargs):
            self.pose_idx = int(placement_solution["tiny_001"]["pose_idx"])
            self.binding_vars = {}
            self.generic_input_vars = {}
            self.generic_output_vars = {}

        def build(self) -> None:
            return None

        def extract_empty_binding_domain_instances(self) -> list[dict]:
            if self.pose_idx == 0:
                return [
                    {
                        "instance_id": "tiny_001",
                        "pose_idx": 0,
                        "pose_id": "tiny_0",
                        "facility_type": "tiny_facility",
                    }
                ]
            return []

        def solve(self, time_limit_seconds: float = 30.0) -> str:
            return "FEASIBLE"

        def extract_selection(self) -> dict:
            return {
                "binding_choice": {"tiny_001": 0},
                "generic_inputs": {},
                "generic_outputs": {},
            }

        def extract_port_specs(self) -> list[dict]:
            return []

        def extract_conflict_summary(self) -> dict:
            return {
                "empty_binding_domain_instances": self.extract_empty_binding_domain_instances(),
            }

    class FakeRoutingSubproblem:
        def __init__(self, grid, commodities):
            self.build_stats = {"fake": "routing"}

        def build(self) -> None:
            return None

        def solve(self, time_limit: float = 60.0) -> str:
            return "FEASIBLE"

    monkeypatch.setattr(MasterPlacementModel, "solve", fake_master_solve)
    monkeypatch.setattr(MasterPlacementModel, "extract_solution", fake_extract_solution)
    monkeypatch.setattr(MasterPlacementModel, "build_greedy_solution_hint", lambda self: {})
    monkeypatch.setattr(
        benders_loop_module.LBBDController,
        "_run_flow_diagnostic",
        lambda self, solution: ("FEASIBLE", set()),
    )
    monkeypatch.setattr(benders_loop_module, "PortBindingModel", FakeBindingModel)
    monkeypatch.setattr(benders_loop_module, "RoutingSubproblem", FakeRoutingSubproblem)

    status, result = run_benders_for_ghost_rect(
        ghost_w=1,
        ghost_h=1,
        project_root=project_root,
        solve_mode="certified_exact",
        master_seconds=5.0,
        binding_seconds=5.0,
        routing_seconds=5.0,
        max_iterations=3,
    )
    metadata = getattr(run_benders_for_ghost_rect, "last_run_metadata")

    assert status == RUN_STATUS_CERTIFIED
    assert result is not None
    assert result["tiny_001"]["pose_idx"] == 1
    assert metadata["generated_exact_safe_cut_count"] == 1
    assert metadata["fine_grained_exact_safe_cut_count"] == 1
    assert metadata["binding_domain_empty_cut_count"] == 1
    assert metadata["routing_front_blocked_cut_count"] == 0
    assert metadata["exact_safe_cuts"][0]["cut_type"] == "binding_pose_domain_empty_nogood"
    assert metadata["exact_safe_cuts"][0]["conflict_set"] == {"tiny_001": 0}
    assert metadata["exact_safe_cuts"][0]["proof_summary"]["fine_grained_exact_safe_cut_count"] == 1
    assert metadata["exact_safe_cuts"][0]["proof_summary"]["binding_domain_empty_cut_count"] == 1


def test_routing_front_blocked_generates_small_cut_and_continues_master_loop(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_root = _build_multi_pose_exact_project(
        tmp_path / "routing_front_blocked_continue",
        pose_anchors=[0, 2],
        include_pole_block=True,
    )

    def fake_master_solve(self, time_limit_seconds: float = 60.0, solution_hint=None, known_feasible_hint: bool = False):
        solve_calls = int(getattr(self, "_test_solve_calls", 0)) + 1
        self._test_solve_calls = solve_calls
        self.build_stats["last_solve"] = {
            "status": "FEASIBLE",
            "wall_time": 0.0,
            "hinted_literals": 0,
            "known_feasible_hint": bool(known_feasible_hint),
        }
        return cp_model.FEASIBLE

    def fake_extract_solution(self):
        pose_idx = 0 if int(getattr(self, "_test_solve_calls", 0)) <= 1 else 1
        tiny_pose = self.facility_pools["tiny_facility"][pose_idx]
        solution = {
            "tiny_001": {
                "pose_idx": pose_idx,
                "pose_id": tiny_pose["pose_id"],
                "anchor": dict(tiny_pose["anchor"]),
                "facility_type": "tiny_facility",
            }
        }
        pole_pose = self.facility_pools["power_pole"][0]
        solution["pose_optional::power_pole::pole_block"] = {
            "pose_idx": 0,
            "pose_id": pole_pose["pose_id"],
            "anchor": dict(pole_pose["anchor"]),
            "facility_type": "power_pole",
        }
        return solution

    class FakeBindingModel:
        def __init__(self, placement_solution, *args, **kwargs):
            self.pose_idx = int(placement_solution["tiny_001"]["pose_idx"])
            self.binding_vars = {}
            self.generic_input_vars = {}
            self.generic_output_vars = {}

        def build(self) -> None:
            return None

        def extract_empty_binding_domain_instances(self) -> list[dict]:
            return []

        def solve(self, time_limit_seconds: float = 30.0) -> str:
            return "FEASIBLE"

        def extract_selection(self) -> dict:
            return {
                "binding_choice": {"tiny_001": 0},
                "generic_inputs": {},
                "generic_outputs": {},
            }

        def extract_port_specs(self) -> list[dict]:
            port_x = 0 if self.pose_idx == 0 else 2
            return [
                {
                    "instance_id": "tiny_001",
                    "x": port_x,
                    "y": 0,
                    "dir": "E",
                    "type": "out",
                    "commodity": "ore",
                }
            ]

        def extract_conflict_summary(self) -> dict:
            return {"pose_idx": self.pose_idx}

    class FakeRoutingSubproblem:
        def __init__(self, grid, commodities):
            self.build_stats = {"fake": "routing"}

        def build(self) -> None:
            return None

        def solve(self, time_limit: float = 60.0) -> str:
            return "FEASIBLE"

    monkeypatch.setattr(MasterPlacementModel, "solve", fake_master_solve)
    monkeypatch.setattr(MasterPlacementModel, "extract_solution", fake_extract_solution)
    monkeypatch.setattr(MasterPlacementModel, "build_greedy_solution_hint", lambda self: {})
    monkeypatch.setattr(
        benders_loop_module.LBBDController,
        "_run_flow_diagnostic",
        lambda self, solution: ("FEASIBLE", set()),
    )
    monkeypatch.setattr(benders_loop_module, "PortBindingModel", FakeBindingModel)
    monkeypatch.setattr(benders_loop_module, "RoutingSubproblem", FakeRoutingSubproblem)

    status, result = run_benders_for_ghost_rect(
        ghost_w=1,
        ghost_h=1,
        project_root=project_root,
        solve_mode="certified_exact",
        master_seconds=5.0,
        binding_seconds=5.0,
        routing_seconds=5.0,
        max_iterations=3,
    )
    metadata = getattr(run_benders_for_ghost_rect, "last_run_metadata")

    assert status == RUN_STATUS_CERTIFIED
    assert result is not None
    assert result["tiny_001"]["pose_idx"] == 1
    assert metadata["generated_exact_safe_cut_count"] == 1
    assert metadata["fine_grained_exact_safe_cut_count"] == 1
    assert metadata["binding_domain_empty_cut_count"] == 0
    assert metadata["routing_front_blocked_cut_count"] == 1
    assert metadata["exact_safe_cuts"][0]["cut_type"] == "routing_front_blocked_nogood"
    assert set(metadata["exact_safe_cuts"][0]["conflict_set"]) == {
        "tiny_001",
        "pose_optional::power_pole::pole_block",
    }
    assert metadata["exact_safe_cuts"][0]["proof_summary"]["fine_grained_exact_safe_cut_count"] == 1
    assert metadata["exact_safe_cuts"][0]["proof_summary"]["routing_front_blocked_cut_count"] == 1


def test_relaxed_disconnected_only_rejects_binding_selection_without_persisted_cut(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_root = _build_multi_pose_exact_project(
        tmp_path / "relaxed_disconnected_binding_reject",
        pose_anchors=[0],
    )

    def fake_master_solve(self, time_limit_seconds: float = 60.0, solution_hint=None, known_feasible_hint: bool = False):
        self.build_stats["last_solve"] = {
            "status": "FEASIBLE",
            "wall_time": 0.0,
            "hinted_literals": 0,
            "known_feasible_hint": bool(known_feasible_hint),
        }
        return cp_model.FEASIBLE

    def fake_extract_solution(self):
        pose = self.facility_pools["tiny_facility"][0]
        return {
            "tiny_001": {
                "pose_idx": 0,
                "pose_id": pose["pose_id"],
                "anchor": dict(pose["anchor"]),
                "facility_type": "tiny_facility",
            }
        }

    class FakeBindingModel:
        def __init__(self, *args, **kwargs):
            self.index = 0
            self.binding_vars = {"tiny_001": {0: object(), 1: object()}}
            self.generic_input_vars = {}
            self.generic_output_vars = {}

        def build(self) -> None:
            return None

        def extract_empty_binding_domain_instances(self) -> list[dict]:
            return []

        def solve(self, time_limit_seconds: float = 30.0) -> str:
            if self.index < 2:
                return "FEASIBLE"
            return "INFEASIBLE"

        def extract_selection(self) -> dict:
            return {
                "binding_choice": {"tiny_001": self.index},
                "generic_inputs": {},
                "generic_outputs": {},
            }

        def extract_port_specs(self) -> list[dict]:
            return []

        def add_nogood_cut(self, selection: dict) -> None:
            assert selection["binding_choice"]["tiny_001"] == self.index
            self.index += 1

        def extract_conflict_summary(self) -> dict:
            return {"binding_index": self.index}

    class FakeRoutingSubproblem:
        def __init__(self, grid, commodities):
            self.build_stats = {"fake": "routing"}

        def build(self) -> None:
            return None

        def solve(self, time_limit: float = 60.0) -> str:
            return "FEASIBLE"

    precheck_calls = {"count": 0}

    def fake_routing_precheck(grid, *, occupied_owner_by_cell=None):
        precheck_calls["count"] += 1
        if precheck_calls["count"] == 1:
            return {
                "status": "relaxed_disconnected",
                "binding_selection_safe_reject": True,
                "placement_level_conflict_set": [],
                "blocked_ports": [],
                "disconnected_commodities": [{"commodity": "ore"}],
            }
        return {
            "status": "feasible",
            "binding_selection_safe_reject": False,
            "placement_level_conflict_set": [],
            "blocked_ports": [],
            "disconnected_commodities": [],
        }

    monkeypatch.setattr(MasterPlacementModel, "solve", fake_master_solve)
    monkeypatch.setattr(MasterPlacementModel, "extract_solution", fake_extract_solution)
    monkeypatch.setattr(MasterPlacementModel, "build_greedy_solution_hint", lambda self: {})
    monkeypatch.setattr(
        benders_loop_module.LBBDController,
        "_run_flow_diagnostic",
        lambda self, solution: ("FEASIBLE", set()),
    )
    monkeypatch.setattr(benders_loop_module, "PortBindingModel", FakeBindingModel)
    monkeypatch.setattr(benders_loop_module, "RoutingSubproblem", FakeRoutingSubproblem)
    monkeypatch.setattr(benders_loop_module, "run_exact_routing_precheck", fake_routing_precheck)

    status, result = run_benders_for_ghost_rect(
        ghost_w=1,
        ghost_h=1,
        project_root=project_root,
        solve_mode="certified_exact",
        master_seconds=5.0,
        binding_seconds=5.0,
        routing_seconds=5.0,
        max_iterations=2,
    )
    metadata = getattr(run_benders_for_ghost_rect, "last_run_metadata")

    assert status == RUN_STATUS_CERTIFIED
    assert result is not None
    assert metadata["generated_exact_safe_cut_count"] == 0
    assert metadata["exact_safe_cuts"] == []
    assert metadata["proof_summary"]["enumerated_bindings"] == 2
    assert metadata["proof_summary"]["routing_precheck_rejections"] == 1
    assert metadata["proof_summary"]["routing_precheck_statuses"] == [
        "relaxed_disconnected",
        "feasible",
    ]
    assert metadata["used_routing_core_reuse"] is True
    assert metadata["routing_core_build_seconds"] >= 0.0
    assert metadata["routing_overlay_build_seconds"] >= 0.0


def test_exact_mode_reports_routing_shrink_stats(monkeypatch, tmp_path: Path) -> None:
    project_root = _build_toy_exact_project(tmp_path / "toy_routing_shrink")

    def fake_master_solve(self, time_limit_seconds: float = 60.0, solution_hint=None, known_feasible_hint: bool = False):
        self.build_stats["last_solve"] = {
            "status": "FEASIBLE",
            "wall_time": 0.0,
            "hinted_literals": 0,
            "known_feasible_hint": bool(known_feasible_hint),
        }
        return cp_model.FEASIBLE

    def fake_extract_solution(self):
        pose = self.facility_pools["tiny_facility"][0]
        return {
            "tiny_001": {
                "pose_idx": 0,
                "pose_id": pose["pose_id"],
                "anchor": dict(pose["anchor"]),
                "facility_type": "tiny_facility",
            }
        }

    class FakeBindingModel:
        def __init__(self, *args, **kwargs):
            self.binding_vars = {}
            self.generic_input_vars = {}
            self.generic_output_vars = {}

        def build(self) -> None:
            return None

        def extract_empty_binding_domain_instances(self) -> list[dict]:
            return []

        def solve(self, time_limit_seconds: float = 30.0) -> str:
            return "FEASIBLE"

        def extract_selection(self) -> dict:
            return {
                "binding_choice": {"tiny_001": 0},
                "generic_inputs": {},
                "generic_outputs": {},
            }

        def extract_port_specs(self) -> list[dict]:
            return [
                {
                    "instance_id": "tiny_001",
                    "x": 0,
                    "y": 2,
                    "dir": "E",
                    "type": "out",
                    "commodity": "ore",
                },
                {
                    "instance_id": "tiny_001",
                    "x": 8,
                    "y": 3,
                    "dir": "S",
                    "type": "in",
                    "commodity": "ore",
                },
            ]

        def extract_conflict_summary(self) -> dict:
            return {"fake": "routing_shrink"}

    class CorridorRoutingGrid:
        def __init__(self, occupied_cells, port_specs):
            del occupied_cells
            self.port_specs = list(port_specs)
            self.free_cells = {(x, 2) for x in range(1, 9)} | {(4, 3), (4, 4)}
            self.port_cells = {
                (int(port["x"]), int(port["y"]))
                for port in self.port_specs
            }
            self.routable_cells = self.free_cells | self.port_cells

        def neighbors(self, x: int, y: int) -> list[tuple[int, int, str]]:
            result = []
            for direction, (dx, dy) in {
                "N": (0, 1),
                "S": (0, -1),
                "E": (1, 0),
                "W": (-1, 0),
            }.items():
                nx, ny = x + dx, y + dy
                if 0 <= nx < 70 and 0 <= ny < 70 and (nx, ny) in self.routable_cells:
                    result.append((nx, ny, direction))
            return result

    monkeypatch.setattr(MasterPlacementModel, "solve", fake_master_solve)
    monkeypatch.setattr(MasterPlacementModel, "extract_solution", fake_extract_solution)
    monkeypatch.setattr(MasterPlacementModel, "build_greedy_solution_hint", lambda self: {})
    monkeypatch.setattr(
        benders_loop_module.LBBDController,
        "_run_flow_diagnostic",
        lambda self, solution: ("FEASIBLE", set()),
    )
    monkeypatch.setattr(benders_loop_module, "PortBindingModel", FakeBindingModel)
    monkeypatch.setattr(benders_loop_module, "RoutingGrid", CorridorRoutingGrid)

    status, result = run_benders_for_ghost_rect(
        ghost_w=1,
        ghost_h=1,
        project_root=project_root,
        solve_mode="certified_exact",
        master_seconds=5.0,
        binding_seconds=5.0,
        routing_seconds=5.0,
        max_iterations=2,
    )
    metadata = getattr(run_benders_for_ghost_rect, "last_run_metadata")
    routing_summary = metadata["proof_summary"]["routing_summary"]["state_space"]

    assert status == RUN_STATUS_CERTIFIED
    assert result is not None
    assert metadata["proof_summary"]["routing_domain_cells"] == 10
    assert metadata["proof_summary"]["routing_terminal_core_cells"] == 8
    assert metadata["proof_summary"]["routing_state_space_vars"] == routing_summary["vars"]
    assert (
        metadata["proof_summary"]["routing_local_pattern_pruned_states"]
        == routing_summary["local_pattern_pruned_states"]
    )
    assert routing_summary["vars"] < routing_summary["naive_full_domain_vars"]
    assert "used_routing_core_reuse" in metadata
    assert metadata["routing_core_build_seconds"] >= 0.0
    assert metadata["routing_overlay_build_seconds"] >= 0.0
    assert metadata["binding_domain_cache_hits"] == 0
    assert metadata["binding_domain_cache_misses"] == 0


def test_unknown_result_is_persisted_to_campaign(monkeypatch, tmp_path: Path) -> None:
    project_root = _build_toy_exact_project(tmp_path / "campaign_unknown")

    def _always_unknown(self, *args, **kwargs):
        return cp_model.UNKNOWN

    monkeypatch.setattr(MasterPlacementModel, "solve", _always_unknown)
    status, result = run_outer_search(
        project_root=project_root,
        solve_mode="certified_exact",
        max_attempts=1,
        min_side=1,
        area_upper_bound=1,
        master_seconds=0.01,
        binding_seconds=0.01,
        routing_seconds=0.01,
        benders_max_iter=1,
        campaign_hours=1.0,
        resume_campaign=False,
    )
    state = _read_campaign_state(project_root)
    candidate = state["candidates"]["1x1"]

    assert status == RUN_STATUS_UNKNOWN
    assert result is None
    assert state["final_status"] == RUN_STATUS_UNKNOWN
    assert state["last_stop_reason"]["reason"] == "candidate_returned_unknown"
    assert candidate["status"] == RUN_STATUS_UNKNOWN
    assert candidate["finished_at"] is not None
    assert candidate["proof_summary"]["master_status"] == "UNKNOWN"


def test_unproven_result_is_persisted_to_campaign(tmp_path: Path) -> None:
    project_root = _build_toy_exact_project(tmp_path / "campaign_unproven")
    _write_json(
        project_root / "data" / "preprocessed" / "mandatory_exact_instances.json",
        [
            {
                "instance_id": "tiny_001",
                "facility_type": "tiny_facility",
                "is_mandatory": False,
                "bound_type": "provisional",
                "solve_mode": "exploratory",
            }
        ],
    )

    status, result = run_outer_search(
        project_root=project_root,
        solve_mode="certified_exact",
        max_attempts=1,
        min_side=1,
        area_upper_bound=1,
        master_seconds=0.01,
        binding_seconds=0.01,
        routing_seconds=0.01,
        benders_max_iter=1,
        campaign_hours=1.0,
        resume_campaign=False,
    )
    state = _read_campaign_state(project_root)
    candidate = state["candidates"]["1x1"]

    assert status == RUN_STATUS_UNPROVEN
    assert result is None
    assert state["final_status"] == RUN_STATUS_UNPROVEN
    assert state["last_stop_reason"]["reason"] == "candidate_returned_unproven"
    assert candidate["status"] == RUN_STATUS_UNPROVEN
    assert candidate["finished_at"] is not None
    assert candidate["proof_summary"]["master_status"] == "BLOCKED"
    assert candidate["proof_summary"]["blockers"]


def test_max_attempts_stop_reason_is_persisted(tmp_path: Path) -> None:
    project_root = _build_toy_exact_project(tmp_path / "campaign_max_attempts")
    status, result = run_outer_search(
        project_root=project_root,
        solve_mode="certified_exact",
        max_attempts=0,
        min_side=1,
        area_upper_bound=1,
        master_seconds=0.01,
        binding_seconds=0.01,
        routing_seconds=0.01,
        benders_max_iter=1,
        campaign_hours=1.0,
        resume_campaign=False,
    )
    state = _read_campaign_state(project_root)

    assert status == RUN_STATUS_UNKNOWN
    assert result is None
    assert state["final_status"] == RUN_STATUS_UNKNOWN
    assert state["last_stop_reason"]["reason"] == "max_attempts_exhausted"
    assert state["candidates"] == {}


def test_exact_path_publishes_core_reuse_metadata(tmp_path: Path) -> None:
    project_root = _build_toy_exact_project(tmp_path / "core_reuse_metadata")

    status, result = run_benders_for_ghost_rect(
        ghost_w=1,
        ghost_h=1,
        project_root=project_root,
        solve_mode="certified_exact",
        master_seconds=5.0,
        binding_seconds=5.0,
        routing_seconds=5.0,
        max_iterations=2,
    )
    metadata = getattr(run_benders_for_ghost_rect, "last_run_metadata")

    assert status == RUN_STATUS_CERTIFIED
    assert result is not None
    assert metadata["used_exact_core_reuse"] is True
    assert metadata["core_build_seconds"] >= 0.0
    assert metadata["overlay_build_seconds"] >= 0.0
    assert metadata["ghost_constraint_seconds"] >= 0.0
    assert metadata["cut_replay_seconds"] >= 0.0
    assert metadata["master_search_profile"] == "exact_coordinate_guided_branching_v4"
    assert "power_pole_family_order" in metadata
    assert "power_pole_family_count_literals" in metadata
    assert "residual_optional_family_guided" in metadata
    assert metadata["binding_search_profile"] == "exact_binding_guided_branching_v1"
    assert metadata["used_routing_core_reuse"] is True
    assert metadata["routing_core_build_seconds"] >= 0.0
    assert metadata["routing_overlay_build_seconds"] >= 0.0
    assert "binding_domain_cache_hits" in metadata
    assert "binding_domain_cache_misses" in metadata
    assert metadata["master_representation"] == "coordinate_exact_v2"
    assert metadata["master_pose_bool_literals"] == 0
    assert metadata["master_domain_encoding"] == "mode_rect_factorized_v1"
    assert metadata["master_domain_table_rows"] == 0
    assert "power_coverage_representation" in metadata
    assert "power_coverage_encoding" in metadata
    assert "power_coverage_cover_literals" in metadata
    assert "power_coverage_witness_indices" in metadata
    assert "power_coverage_element_constraints" in metadata
    assert "power_capacity_shell_pairs" in metadata
    assert "power_capacity_shell_pair_evaluations" in metadata
    assert "power_capacity_signature_classes" in metadata
    assert "power_capacity_signature_class_evaluations" in metadata
    assert "power_capacity_compact_signature_classes" in metadata
    assert "power_capacity_compact_signature_evaluations" in metadata
    assert "power_capacity_compact_signature_cache_hits" in metadata
    assert "power_capacity_compact_signature_cache_misses" in metadata
    assert "power_capacity_rect_dp_evaluations" in metadata
    assert "power_capacity_rect_dp_cache_hits" in metadata
    assert "power_capacity_rect_dp_cache_misses" in metadata
    assert "power_capacity_rect_dp_state_merges" in metadata
    assert "power_capacity_rect_dp_peak_line_states" in metadata
    assert "power_capacity_rect_dp_peak_pos_states" in metadata
    assert "power_capacity_rect_dp_compiled_signatures" in metadata
    assert "power_capacity_rect_dp_compiled_start_options" in metadata
    assert "power_capacity_rect_dp_deduped_start_options" in metadata
    assert "power_capacity_rect_dp_compiled_line_subsets" in metadata
    assert "power_capacity_rect_dp_peak_line_subset_options" in metadata
    assert "power_capacity_rect_dp_v3_fallbacks" in metadata
    assert "power_capacity_bitset_oracle_evaluations" in metadata
    assert "power_capacity_bitset_fallbacks" in metadata
    assert "power_capacity_cpsat_fallbacks" in metadata
    assert "power_capacity_oracle" in metadata
    assert "power_capacity_raw_pole_evaluations" in metadata
    assert "signature_bucket_cache_hits" in metadata
    assert "signature_bucket_cache_misses" in metadata
    assert "signature_bucket_distinct_keys" in metadata
    assert "geometry_cache_templates" in metadata
    assert metadata["power_capacity_oracle"] == "rectangle_frontier_dp_v4"
    assert metadata["power_coverage_encoding"] == "table_pairwise_witness_v1"
    assert metadata["power_coverage_cover_literals"] == 0
    assert metadata["power_coverage_witness_indices"] == 0


def test_certification_first_frontier_prefers_prune_per_anchor_over_objective_head() -> None:
    candidates = generate_candidate_sizes(
        max_w=6,
        max_h=6,
        min_side=1,
        area_upper_bound=9,
    )

    frontier_state = outer_search_module._compute_exact_frontier_state(
        candidates,
        None,
        grid_w=6,
        grid_h=6,
    )

    assert frontier_state["frontier"][0] == (9, 3, 3)
    assert frontier_state["selected_candidate"] == (6, 6, 1)
    assert frontier_state["selected_candidate_metrics"] == {
        "selection_score_num": 4,
        "selection_score_den": 3,
        "certification_prune_gain": 8,
        "infeasible_prune_gain": 1,
        "anchor_count": 6,
        "frontier_size": 3,
    }


def test_frontier_selection_tiebreak_falls_back_to_objective_order(monkeypatch) -> None:
    def fake_metrics(candidate, potential_domain, *, grid_w: int, grid_h: int):
        return {
            "selection_score_num": 7,
            "selection_score_den": 5,
            "certification_prune_gain": 7,
            "infeasible_prune_gain": 2,
            "anchor_count": 5,
        }

    monkeypatch.setattr(outer_search_module, "_compute_frontier_candidate_metrics", fake_metrics)

    selected_candidate, selected_metrics, metrics_by_key = outer_search_module._select_frontier_candidate(
        [(12, 6, 2), (12, 4, 3)],
        [(12, 6, 2), (12, 4, 3)],
        grid_w=6,
        grid_h=6,
    )

    assert selected_candidate == (12, 6, 2)
    assert selected_metrics["frontier_size"] == 2
    assert metrics_by_key["6x2"]["frontier_size"] == 2
    assert metrics_by_key["4x3"]["frontier_size"] == 2


def test_antichain_frontier_matches_bruteforce_and_preserves_tiebreak(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_root = _build_frontier_project(tmp_path / "frontier_bruteforce", width=6, height=6)
    calls: list[tuple[int, int, bool]] = []

    def _is_feasible(ghost_w: int, ghost_h: int) -> bool:
        return (ghost_w <= 4 and ghost_h <= 3) or (ghost_w <= 6 and ghost_h <= 2)

    def fake_run_benders_for_ghost_rect(*, ghost_w: int, ghost_h: int, session=None, **kwargs):
        calls.append((ghost_w, ghost_h, session is not None))
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
            return RUN_STATUS_CERTIFIED, {
                "ghost_pick": {
                    "pose_idx": 0,
                    "pose_id": f"ghost_{ghost_w}x{ghost_h}",
                    "facility_type": "synthetic",
                }
            }
        return RUN_STATUS_INFEASIBLE, None

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

    explicit_candidates = generate_candidate_sizes(
        max_w=6,
        max_h=6,
        min_side=1,
        max_aspect_ratio=3.0,
        area_upper_bound=12,
    )
    frontier_state = outer_search_module._compute_exact_frontier_state(
        explicit_candidates,
        None,
        grid_w=6,
        grid_h=6,
    )
    expected = max(
        (candidate for candidate in explicit_candidates if _is_feasible(candidate[1], candidate[2])),
        key=lambda item: (item[0], item[1], item[2]),
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

    assert status == RUN_STATUS_CERTIFIED
    assert result is not None
    assert result["ghost_rect"] == {"w": expected[1], "h": expected[2], "area": expected[0]}
    assert calls[0][:2] == (
        frontier_state["selected_candidate"][1],
        frontier_state["selected_candidate"][2],
    )
    assert result["search_stats"]["frontier_peak_size"] >= 1
    assert result["search_stats"]["derived_pruned_candidates"] > 0
    assert (
        result["search_stats"]["frontier_selection_policy"]
        == outer_search_module.FRONTIER_SELECTION_POLICY
    )
    assert result["search_stats"]["frontier_candidate_metrics"]
    assert all(item[2] is True for item in calls)

    state = _read_campaign_state(project_root)
    first_candidate_key = f"{calls[0][0]}x{calls[0][1]}"
    assert (
        state["candidates"][first_candidate_key]["proof_summary"]["frontier_selection_policy"]
        == outer_search_module.FRONTIER_SELECTION_POLICY
    )
    assert state["candidates"][first_candidate_key]["proof_summary"]["frontier_candidate_metrics"]


def test_unknown_candidate_is_retried_on_resume_without_monotone_prune(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_root = _build_frontier_project(tmp_path / "frontier_unknown_resume", width=2, height=2)
    call_counts: dict[tuple[int, int], int] = {}

    def fake_run_benders_for_ghost_rect(*, ghost_w: int, ghost_h: int, session=None, **kwargs):
        key = (ghost_w, ghost_h)
        call_counts[key] = call_counts.get(key, 0) + 1
        attempt = call_counts[key]
        if key == (2, 2) and attempt == 1:
            fake_run_benders_for_ghost_rect.last_run_metadata = {
                "proof_summary": {"mode": "certified_exact", "master_status": "UNKNOWN"},
                "exact_safe_cuts": [],
                "loaded_exact_safe_cut_count": 0,
                "generated_exact_safe_cut_count": 0,
            }
            return RUN_STATUS_UNKNOWN, None
        if key == (2, 2):
            fake_run_benders_for_ghost_rect.last_run_metadata = {
                "proof_summary": {"mode": "certified_exact", "master_status": "INFEASIBLE"},
                "exact_safe_cuts": [],
                "loaded_exact_safe_cut_count": 0,
                "generated_exact_safe_cut_count": 0,
            }
            return RUN_STATUS_INFEASIBLE, None

        fake_run_benders_for_ghost_rect.last_run_metadata = {
            "proof_summary": {"mode": "certified_exact", "master_status": "FEASIBLE"},
            "exact_safe_cuts": [],
            "loaded_exact_safe_cut_count": 0,
            "generated_exact_safe_cut_count": 0,
        }
        return RUN_STATUS_CERTIFIED, {
            "ghost_pick": {
                "pose_idx": 0,
                "pose_id": f"ghost_{ghost_w}x{ghost_h}",
                "facility_type": "synthetic",
            }
        }

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
        max_attempts=2,
        min_side=1,
        area_upper_bound=4,
        master_seconds=0.01,
        binding_seconds=0.01,
        routing_seconds=0.01,
        benders_max_iter=1,
        campaign_hours=1.0,
        resume_campaign=False,
    )
    assert status == RUN_STATUS_UNKNOWN
    assert result is None
    assert call_counts[(2, 2)] == 1

    status, result = run_outer_search(
        project_root=project_root,
        solve_mode="certified_exact",
        max_attempts=4,
        min_side=1,
        area_upper_bound=4,
        master_seconds=0.01,
        binding_seconds=0.01,
        routing_seconds=0.01,
        benders_max_iter=1,
        campaign_hours=1.0,
        resume_campaign=True,
    )

    assert status == RUN_STATUS_CERTIFIED
    assert result is not None
    assert result["ghost_rect"] == {"w": 2, "h": 1, "area": 2}
    assert call_counts[(2, 2)] == 2


def test_prune_first_partial_run_can_deviate_from_objective_prefix_and_resume(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_root = _build_frontier_project(tmp_path / "frontier_prune_first_resume", width=6, height=6)
    calls: list[tuple[int, int]] = []

    def _is_feasible(ghost_w: int, ghost_h: int) -> bool:
        return (ghost_w, ghost_h) == (6, 1)

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
            return RUN_STATUS_CERTIFIED, {
                "ghost_pick": {
                    "pose_idx": 0,
                    "pose_id": f"ghost_{ghost_w}x{ghost_h}",
                    "facility_type": "synthetic",
                }
            }
        return RUN_STATUS_INFEASIBLE, None

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

    assert status == RUN_STATUS_UNKNOWN
    assert result is None
    assert calls == [(6, 1)]

    partial_state = _read_campaign_state(project_root)
    assert "6x1" in partial_state["candidates"]
    assert "3x3" not in partial_state["candidates"]
    assert partial_state["last_stop_reason"]["reason"] == "max_attempts_exhausted"

    status, result = run_outer_search(
        project_root=project_root,
        solve_mode="certified_exact",
        max_attempts=32,
        min_side=1,
        area_upper_bound=9,
        master_seconds=0.01,
        binding_seconds=0.01,
        routing_seconds=0.01,
        benders_max_iter=1,
        campaign_hours=1.0,
        resume_campaign=True,
    )

    assert status == RUN_STATUS_CERTIFIED
    assert result is not None
    assert result["ghost_rect"] == {"w": 6, "h": 1, "area": 6}
