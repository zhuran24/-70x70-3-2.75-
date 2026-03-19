"""Tests for the master placement layer（主摆放层测试）."""

from __future__ import annotations

from pathlib import Path

import pytest
from ortools.sat.python import cp_model

from src.models.master_model import (
    MasterPlacementModel,
    _LOCAL_POWER_CAPACITY_CACHE,
    _LOCAL_POWER_CAPACITY_COMPACT_CACHE,
    _LOCAL_POWER_CAPACITY_M6X4_MIXED_CPSAT_DATA_CACHE,
    _LOCAL_POWER_CAPACITY_RECT_DP_COMPILED_CACHE,
    _LOCAL_POWER_CAPACITY_RECT_DP_CACHE,
    _Manufacturing6x4MixedCpSatFallback,
    load_generic_io_requirements_artifact,
    load_project_data,
)


@pytest.fixture(scope="session")
def project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _clear_local_power_capacity_caches() -> None:
    _LOCAL_POWER_CAPACITY_CACHE.clear()
    _LOCAL_POWER_CAPACITY_COMPACT_CACHE.clear()
    _LOCAL_POWER_CAPACITY_M6X4_MIXED_CPSAT_DATA_CACHE.clear()
    _LOCAL_POWER_CAPACITY_RECT_DP_CACHE.clear()
    _LOCAL_POWER_CAPACITY_RECT_DP_COMPILED_CACHE.clear()


def _build_exact_power_capacity_model(
    *,
    solve_mode: str = "certified_exact",
    ghost_rect: tuple[int, int] | None = None,
) -> MasterPlacementModel:
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
                "pose_id": "pole_left",
                "anchor": {"x": 0, "y": 1},
                "occupied_cells": [[0, 1]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": [[1, 0], [2, 0]],
            },
            {
                "pose_id": "pole_right",
                "anchor": {"x": 3, "y": 1},
                "occupied_cells": [[3, 1]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": [[4, 0], [5, 0]],
            },
        ],
        "protocol_storage_box": [],
        "powered_machine": [
            {
                "pose_id": "machine_left_a",
                "anchor": {"x": 1, "y": 0},
                "occupied_cells": [[1, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
            {
                "pose_id": "machine_left_b",
                "anchor": {"x": 2, "y": 0},
                "occupied_cells": [[2, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
            {
                "pose_id": "machine_right_a",
                "anchor": {"x": 4, "y": 0},
                "occupied_cells": [[4, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
            {
                "pose_id": "machine_right_b",
                "anchor": {"x": 5, "y": 0},
                "occupied_cells": [[5, 0]],
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
            "powered_machine": {"dimensions": {"w": 1, "h": 1}, "needs_power": True},
        },
    }
    return MasterPlacementModel(
        instances,
        pools,
        rules,
        solve_mode=solve_mode,
        ghost_rect=ghost_rect,
    )


def _build_exact_geometric_power_coverage_model() -> MasterPlacementModel:
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
                "pose_id": "pole_center",
                "anchor": {"x": 0, "y": 1},
                "occupied_cells": [[0, 1]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": [
                    [0, 0],
                    [0, 1],
                    [1, 0],
                    [1, 1],
                    [2, 0],
                    [2, 1],
                ],
            }
        ],
        "protocol_storage_box": [],
        "powered_machine": [
            {
                "pose_id": "machine_left",
                "anchor": {"x": 1, "y": 0},
                "occupied_cells": [[1, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
            {
                "pose_id": "machine_right",
                "anchor": {"x": 2, "y": 0},
                "occupied_cells": [[2, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
        ],
    }
    rules = {
        "globals": {"grid": {"width": 3, "height": 2}},
        "facility_templates": {
            "power_pole": {
                "dimensions": {"w": 1, "h": 1},
                "needs_power": False,
                "power_coverage_radius": 1,
            },
            "protocol_storage_box": {"dimensions": {"w": 1, "h": 1}, "needs_power": True},
            "powered_machine": {"dimensions": {"w": 1, "h": 1}, "needs_power": True},
        },
    }
    return MasterPlacementModel(
        instances,
        pools,
        rules,
        solve_mode="certified_exact",
    )



def test_load_project_data_separates_exact_and_exploratory(project_root: Path) -> None:
    exact_instances, pools, rules = load_project_data(project_root, solve_mode="certified_exact")
    exploratory_instances, _, _ = load_project_data(project_root, solve_mode="exploratory")

    assert len(exact_instances) == 266
    assert all(inst["is_mandatory"] for inst in exact_instances)
    assert all(inst["bound_type"] == "exact" for inst in exact_instances)

    assert len(exploratory_instances) == 326
    assert sum(1 for inst in exploratory_instances if not inst["is_mandatory"]) == 60
    assert sum(len(pool) for pool in pools.values()) == 81795
    assert rules["globals"]["grid"]["width"] == 70
    assert rules["globals"]["grid"]["height"] == 70



def test_exact_mode_optional_pose_variables_ignore_provisional_caps() -> None:
    instances = [
        {
            "instance_id": f"power_pole_{idx:03d}",
            "facility_type": "power_pole",
            "operation_type": "power_supply",
            "is_mandatory": False,
            "bound_type": "provisional",
        }
        for idx in range(1, 51)
    ]
    pools = {
        "power_pole": [
            {
                "pose_id": f"pole_{idx}",
                "anchor": {"x": idx, "y": 0},
                "occupied_cells": [[idx, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": [[idx, 0]],
            }
            for idx in range(51)
        ],
        "protocol_storage_box": [],
    }
    rules = {
        "globals": {"grid": {"width": 70, "height": 70}},
        "facility_templates": {
            "power_pole": {"dimensions": {"w": 1, "h": 1}, "needs_power": False},
            "protocol_storage_box": {"dimensions": {"w": 1, "h": 1}, "needs_power": True},
        },
    }

    exact_model = MasterPlacementModel(
        instances,
        pools,
        rules,
        solve_mode="certified_exact",
        skip_power_coverage=True,
    )
    exact_model.build()
    assert exact_model.build_stats["master_representation"] == "coordinate_exact_v2"
    assert exact_model.build_stats["master_domain_encoding"] == "mode_rect_factorized_v1"
    assert exact_model.build_stats["master_domain_table_rows"] == 0
    assert exact_model.build_stats["master_slot_counts"]["residual_optionals"] == {}
    assert "power_coverage" not in exact_model.build_stats
    assert exact_model.build_stats["exact_required_optionals"] == {}
    optional_bounds = exact_model.build_stats["global_valid_inequalities"]["optional_cardinality_bounds"]
    family_stats = exact_model.build_stats["global_valid_inequalities"]["power_capacity_families"]
    assert optional_bounds["power_pole"]["candidate_pose_count"] == 51
    assert optional_bounds["power_pole"]["mandatory_powered_nonpole"] == 0
    assert optional_bounds["power_pole"]["slot_pool_upper_bound"] == 0
    assert family_stats["applied"] is False
    assert family_stats["reason"] == "power_coverage_skipped"
    assert exact_model.solve(time_limit_seconds=5.0) in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    exploratory_model = MasterPlacementModel(
        instances,
        pools,
        rules,
        solve_mode="exploratory",
        skip_power_coverage=True,
    )
    exploratory_model.build()
    for var in exploratory_model.optional_pose_vars["power_pole"].values():
        exploratory_model.model.Add(var == 1)
    assert exploratory_model.solve(time_limit_seconds=5.0) == cp_model.INFEASIBLE



def test_extract_solution_emits_pose_optional_identifier() -> None:
    instances = []
    pools = {
        "power_pole": [],
        "protocol_storage_box": [
            {
                "pose_id": "box_0",
                "anchor": {"x": 1, "y": 0},
                "occupied_cells": [[1, 0]],
                "input_port_cells": [{"x": 1, "y": 1, "dir": "N"}],
                "output_port_cells": [],
                "power_coverage_cells": None,
            }
        ],
    }
    rules = {
        "globals": {"grid": {"width": 70, "height": 70}},
        "facility_templates": {
            "power_pole": {"dimensions": {"w": 1, "h": 1}, "needs_power": False},
            "protocol_storage_box": {"dimensions": {"w": 1, "h": 1}, "needs_power": True},
        },
    }

    model = MasterPlacementModel(
        instances,
        pools,
        rules,
        solve_mode="certified_exact",
        skip_power_coverage=True,
        generic_io_requirements={
            "required_generic_outputs": {},
            "required_generic_inputs": {"valley_battery": 1},
        },
    )
    model.build()
    assert model.solve(time_limit_seconds=5.0) in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    solution = model.extract_solution()
    assert list(solution.keys()) == ["pose_optional::protocol_storage_box::box_0"]
    entry = solution["pose_optional::protocol_storage_box::box_0"]
    assert entry["facility_type"] == "protocol_storage_box"
    assert entry["bound_type"] == "exact_pose_optional"


def test_exact_greedy_solution_hint_is_deterministic_and_mandatory_only() -> None:
    instances = [
        {
            "instance_id": "miner_001",
            "facility_type": "miner",
            "operation_type": "mining",
            "is_mandatory": True,
            "bound_type": "exact",
        },
        {
            "instance_id": "miner_002",
            "facility_type": "miner",
            "operation_type": "mining",
            "is_mandatory": True,
            "bound_type": "exact",
        },
    ]
    pools = {
        "miner": [
            {
                "pose_id": "pose_b",
                "anchor": {"x": 2, "y": 0},
                "occupied_cells": [[2, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
            {
                "pose_id": "pose_a",
                "anchor": {"x": 0, "y": 0},
                "occupied_cells": [[0, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
            {
                "pose_id": "pose_c",
                "anchor": {"x": 1, "y": 0},
                "occupied_cells": [[1, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
        ]
    }
    rules = {
        "globals": {"grid": {"width": 4, "height": 4}},
        "facility_templates": {
            "miner": {"dimensions": {"w": 1, "h": 1}, "needs_power": False},
        },
    }

    model = MasterPlacementModel(
        instances,
        pools,
        rules,
        solve_mode="certified_exact",
        skip_power_coverage=True,
    )

    hint_1 = model.build_greedy_solution_hint()
    hint_2 = model.build_greedy_solution_hint()

    assert hint_1 == hint_2 == {"miner_001": 1, "miner_002": 2}
    assert all(not key.startswith("pose_optional::") for key in hint_1)
    assert model.build_stats["greedy_hint"] == {
        "supported": True,
        "complete": True,
        "hinted_groups": 1,
        "hinted_instances": 2,
        "skipped_groups": [],
        "used_power_coverage_filter": False,
    }


def test_exact_master_search_guidance_profile_is_exposed() -> None:
    instances = [
        {
            "instance_id": "miner_001",
            "facility_type": "miner",
            "operation_type": "mining",
            "is_mandatory": True,
            "bound_type": "exact",
        }
    ]
    pools = {
        "miner": [
            {
                "pose_id": "pose_a",
                "anchor": {"x": 0, "y": 0},
                "occupied_cells": [[0, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
            {
                "pose_id": "pose_b",
                "anchor": {"x": 1, "y": 0},
                "occupied_cells": [[1, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
        ],
        "power_pole": [
            {
                "pose_id": "pole_0",
                "anchor": {"x": 2, "y": 0},
                "occupied_cells": [[2, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": [[2, 0]],
            }
        ],
        "protocol_storage_box": [],
    }
    rules = {
        "globals": {"grid": {"width": 4, "height": 1}},
        "facility_templates": {
            "miner": {"dimensions": {"w": 1, "h": 1}, "needs_power": False},
            "power_pole": {"dimensions": {"w": 1, "h": 1}, "needs_power": False},
            "protocol_storage_box": {"dimensions": {"w": 1, "h": 1}, "needs_power": True},
        },
    }

    model = MasterPlacementModel(
        instances,
        pools,
        rules,
        solve_mode="certified_exact",
        ghost_rect=(1, 1),
        skip_power_coverage=True,
    )
    model.build()

    guidance = model.build_stats["search_guidance"]
    assert guidance["applied"] is True
    assert guidance["profile"] == "exact_coordinate_guided_branching_v4"
    assert guidance["mandatory_signature_counts"] == {
        "group::miner::mining::0": 1,
    }
    assert guidance["mandatory_signature_count_literals"] == 1
    assert guidance["mandatory_literals"] == 2
    assert guidance["ghost_literals"] == 4
    assert guidance["power_pole_family_order"] == []
    assert guidance["power_pole_family_count_literals"] == 0
    assert guidance["residual_optional_family_guided"] is False
    assert guidance["optional_literals"] == {}
    assert guidance["optional_default"] == "SELECT_MIN_VALUE"
    assert model.build_stats["master_representation"] == "coordinate_exact_v2"
    assert model.build_stats["master_pose_bool_literals"] == 0
    assert model.build_stats["master_domain_encoding"] == "mode_rect_factorized_v1"
    assert model.build_stats["master_domain_table_rows"] == 0
    assert model.build_stats["master_mode_rect_domains"]["mandatory_groups"]["group::miner::mining::0"][0]["pose_count"] == 2

    status = model.solve(time_limit_seconds=5.0)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert model.build_stats["last_solve"]["search_profile"] == "exact_coordinate_guided_branching_v4"
    assert model.build_stats["last_solve"]["search_branching"].endswith("FIXED_SEARCH")


def test_exact_search_guidance_separates_required_and_residual_optionals() -> None:
    model = MasterPlacementModel(
        instances=[],
        facility_pools={
            "power_pole": [
                {
                    "pose_id": "pole_0",
                    "anchor": {"x": 0, "y": 0},
                    "occupied_cells": [[0, 0]],
                    "input_port_cells": [],
                    "output_port_cells": [],
                    "power_coverage_cells": [[1, 0]],
                }
            ],
            "protocol_storage_box": [
                {
                    "pose_id": "box_0",
                    "anchor": {"x": 1, "y": 0},
                    "occupied_cells": [[1, 0]],
                    "input_port_cells": [{"x": 1, "y": 1, "dir": "N"}],
                    "output_port_cells": [],
                    "power_coverage_cells": None,
                }
            ],
        },
        rules={
            "globals": {"grid": {"width": 3, "height": 3}},
            "facility_templates": {
                "power_pole": {"dimensions": {"w": 1, "h": 1}, "needs_power": False},
                "protocol_storage_box": {"dimensions": {"w": 1, "h": 1}, "needs_power": True},
            },
        },
        solve_mode="certified_exact",
        skip_power_coverage=True,
        generic_io_requirements={
            "required_generic_outputs": {},
            "required_generic_inputs": {"valley_battery": 1},
        },
    )

    model.build()

    assert model.build_stats["exact_required_optionals"] == {}
    assert model.build_stats["exact_optional_lower_bounds"] == {"protocol_storage_box": 1}
    guidance = model.build_stats["search_guidance"]
    assert guidance["required_optional_templates"] == []
    assert guidance["required_optional_signature_counts"] == {}
    assert guidance["required_optional_signature_count_literals"] == 0
    assert guidance["required_optional_literals"] == {}
    assert guidance["required_optional_default"] == "SELECT_MAX_VALUE"
    assert guidance["residual_optional_literals"] == {
        "power_pole": 1,
        "protocol_storage_box": 1,
    }
    assert guidance["power_pole_family_order"] == []
    assert guidance["power_pole_family_count_literals"] == 0
    assert guidance["residual_optional_family_guided"] is False
    assert guidance["residual_optional_default"] == "SELECT_MIN_VALUE"
    assert guidance["optional_literals"] == {
        "power_pole": 1,
        "protocol_storage_box": 1,
    }


def test_mandatory_signature_buckets_are_stable_and_linked_to_raw_vars() -> None:
    instances = [
        {
            "instance_id": "router_001",
            "facility_type": "router",
            "operation_type": "routing",
            "is_mandatory": True,
            "bound_type": "exact",
        }
    ]
    pools = {
        "router": [
            {
                "pose_id": "plain_left",
                "anchor": {"x": 0, "y": 0},
                "occupied_cells": [[0, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
            {
                "pose_id": "plain_mid",
                "anchor": {"x": 1, "y": 0},
                "occupied_cells": [[1, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
            {
                "pose_id": "ported_right",
                "anchor": {"x": 2, "y": 0},
                "occupied_cells": [[2, 0]],
                "input_port_cells": [],
                "output_port_cells": [{"x": 2, "y": 0, "dir": "E"}],
                "power_coverage_cells": None,
            },
        ],
    }
    rules = {
        "globals": {"grid": {"width": 4, "height": 2}},
        "facility_templates": {
            "router": {"dimensions": {"w": 1, "h": 1}, "needs_power": False},
        },
    }

    model = MasterPlacementModel(
        instances,
        pools,
        rules,
        solve_mode="certified_exact",
        skip_power_coverage=True,
    )
    model.build()

    bucket_stats = model.build_stats["signature_buckets"]["mandatory_groups"]["group::router::routing::0"]
    assert bucket_stats == {
        "bucket_count": 2,
        "pose_count": 3,
        "bucket_sizes": [2, 1],
    }
    count_vars = model._mandatory_signature_count_vars["group::router::routing::0"]
    assert sorted(count_vars) == ["sig_000", "sig_001"]
    model.model.Add(count_vars["sig_000"] == 0)

    status = model.solve(time_limit_seconds=5.0)

    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    solution = model.extract_solution()
    assert solution["router_001"]["pose_id"] == "ported_right"


def test_exact_greedy_solution_hint_filters_powered_poses_without_theoretical_cover() -> None:
    instances = [
        {
            "instance_id": "powered_001",
            "facility_type": "powered_machine",
            "operation_type": "processing",
            "is_mandatory": True,
            "bound_type": "exact",
        }
    ]
    pools = {
        "power_pole": [
            {
                "pose_id": "pole_0",
                "anchor": {"x": 3, "y": 3},
                "occupied_cells": [[3, 3]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": [[1, 0]],
            }
        ],
        "powered_machine": [
            {
                "pose_id": "machine_uncov",
                "anchor": {"x": 0, "y": 0},
                "occupied_cells": [[0, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
            {
                "pose_id": "machine_cov",
                "anchor": {"x": 1, "y": 0},
                "occupied_cells": [[1, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
        ],
    }
    rules = {
        "globals": {"grid": {"width": 4, "height": 4}},
        "facility_templates": {
            "power_pole": {"dimensions": {"w": 1, "h": 1}, "needs_power": False},
            "powered_machine": {"dimensions": {"w": 1, "h": 1}, "needs_power": True},
        },
    }

    model = MasterPlacementModel(
        instances,
        pools,
        rules,
        solve_mode="certified_exact",
        skip_power_coverage=True,
    )

    hint = model.build_greedy_solution_hint()

    assert hint == {"powered_001": 1}
    assert model.build_stats["greedy_hint"]["used_power_coverage_filter"] is True


def test_exact_solve_records_hint_statistics_without_known_feasible_flag() -> None:
    instances = [
        {
            "instance_id": "miner_001",
            "facility_type": "miner",
            "operation_type": "mining",
            "is_mandatory": True,
            "bound_type": "exact",
        }
    ]
    pools = {
        "miner": [
            {
                "pose_id": "pose_0",
                "anchor": {"x": 0, "y": 0},
                "occupied_cells": [[0, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            }
        ]
    }
    rules = {
        "globals": {"grid": {"width": 3, "height": 3}},
        "facility_templates": {
            "miner": {"dimensions": {"w": 1, "h": 1}, "needs_power": False},
        },
    }

    model = MasterPlacementModel(
        instances,
        pools,
        rules,
        solve_mode="certified_exact",
        skip_power_coverage=True,
    )
    model.build()
    hint = model.build_greedy_solution_hint()
    assert hint == {"miner_001": 0}

    status = model.solve(
        time_limit_seconds=5.0,
        solution_hint=hint,
        known_feasible_hint=False,
    )

    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert model.build_stats["last_solve"]["hinted_literals"] == 3
    assert model.build_stats["last_solve"]["known_feasible_hint"] is False


def test_exploratory_mode_does_not_support_exact_greedy_hint() -> None:
    model = MasterPlacementModel(
        instances=[],
        facility_pools={"power_pole": [], "protocol_storage_box": []},
        rules={
            "globals": {"grid": {"width": 3, "height": 3}},
            "facility_templates": {
                "power_pole": {"dimensions": {"w": 1, "h": 1}, "needs_power": False},
                "protocol_storage_box": {"dimensions": {"w": 1, "h": 1}, "needs_power": True},
            },
        },
        solve_mode="exploratory",
        skip_power_coverage=True,
    )

    hint = model.build_greedy_solution_hint()

    assert hint == {}
    assert model.build_stats["greedy_hint"]["supported"] is False
    assert model.build_stats["greedy_hint"]["reason"] == (
        "exact-safe greedy warm start only runs in certified_exact mode"
    )


def test_exact_power_capacity_lower_bound_records_template_demand_and_cache_hits() -> None:
    _clear_local_power_capacity_caches()
    model = _build_exact_power_capacity_model()

    model.build()

    stats = model.build_stats["global_valid_inequalities"]
    precompute = model.build_stats["exact_precompute_profile"]
    assert {
        "type": "power_capacity_lower_bound",
        "template": "powered_machine",
        "demand": 2,
        "nonzero_poles": 2,
    } in stats["applied"]
    assert stats["fixed_required_optional_demands"] == {}
    assert stats["powered_template_demands"] == {"powered_machine": 2}
    assert stats["capacity_coeff_stats"]["powered_machine"]["max_coeff"] == 2
    assert stats["capacity_coeff_stats"]["powered_machine"]["min_nonzero_coeff"] == 2
    assert model._local_power_capacity_signature("powered_machine", 0) == model._local_power_capacity_signature(
        "powered_machine",
        1,
    )
    assert stats["capacity_cache"]["coefficient_source"] == "exact_rect_dp_cache_v7"
    assert stats["capacity_cache"]["shell_pair_count"] == 1
    assert stats["capacity_cache"]["pole_template_evaluations"] == 1
    assert stats["capacity_cache"]["signature_class_count"] == 1
    assert stats["capacity_cache"]["signature_class_evaluations"] == 1
    assert stats["capacity_cache"]["compact_signature_class_count"] == 1
    assert stats["capacity_cache"]["compact_signature_class_evaluations"] == 1
    assert stats["capacity_cache"]["compact_signature_hits"] == 0
    assert stats["capacity_cache"]["compact_signature_misses"] == 1
    assert stats["capacity_cache"]["rect_dp_evaluations"] == 1
    assert stats["capacity_cache"]["rect_dp_cache_hits"] == 0
    assert stats["capacity_cache"]["rect_dp_cache_misses"] == 1
    assert stats["capacity_cache"]["rect_dp_state_merges"] > 0
    assert stats["capacity_cache"]["rect_dp_peak_line_states"] > 0
    assert stats["capacity_cache"]["rect_dp_peak_pos_states"] > 0
    assert stats["capacity_cache"]["rect_dp_compiled_signatures"] >= 1
    assert stats["capacity_cache"]["rect_dp_compiled_start_options"] > 0
    assert stats["capacity_cache"]["rect_dp_deduped_start_options"] > 0
    assert (
        stats["capacity_cache"]["rect_dp_deduped_start_options"]
        <= stats["capacity_cache"]["rect_dp_compiled_start_options"]
    )
    assert stats["capacity_cache"]["rect_dp_compiled_line_subsets"] > 0
    assert stats["capacity_cache"]["rect_dp_peak_line_subset_options"] > 0
    assert stats["capacity_cache"]["rect_dp_v3_fallbacks"] == 0
    assert stats["capacity_cache"]["m6x4_mixed_cpsat_evaluations"] == 0
    assert stats["capacity_cache"]["m6x4_mixed_cpsat_cache_hits"] == 0
    assert stats["capacity_cache"]["m6x4_mixed_cpsat_selected_cases"] == 0
    assert stats["capacity_cache"]["m6x4_mixed_cpsat_v3_fallbacks"] == 0
    assert stats["capacity_cache"]["bitset_oracle_evaluations"] == 0
    assert stats["capacity_cache"]["bitset_fallbacks"] == 0
    assert stats["capacity_cache"]["cpsat_fallbacks"] == 0
    assert stats["capacity_cache"]["oracle"] == "rectangle_frontier_dp_v4"
    assert stats["capacity_cache"]["raw_pole_evaluations"] == 2
    assert stats["capacity_cache"]["signature_misses"] == 1
    assert stats["capacity_cache"]["signature_hits"] == 0
    assert stats["capacity_cache"]["signature_count"] >= 1
    assert precompute["power_capacity_shell_pairs"] == 1
    assert precompute["power_capacity_shell_pair_evaluations"] == 1
    assert precompute["power_capacity_signature_classes"] == 1
    assert precompute["power_capacity_signature_class_evaluations"] == 1
    assert precompute["power_capacity_compact_signature_classes"] == 1
    assert precompute["power_capacity_compact_signature_evaluations"] == 1
    assert precompute["power_capacity_compact_signature_cache_hits"] == 0
    assert precompute["power_capacity_compact_signature_cache_misses"] == 1
    assert precompute["power_capacity_rect_dp_evaluations"] == 1
    assert precompute["power_capacity_rect_dp_cache_hits"] == 0
    assert precompute["power_capacity_rect_dp_cache_misses"] == 1
    assert precompute["power_capacity_rect_dp_state_merges"] > 0
    assert precompute["power_capacity_rect_dp_peak_line_states"] > 0
    assert precompute["power_capacity_rect_dp_peak_pos_states"] > 0
    assert precompute["power_capacity_rect_dp_compiled_signatures"] >= 1
    assert precompute["power_capacity_rect_dp_compiled_start_options"] > 0
    assert precompute["power_capacity_rect_dp_deduped_start_options"] > 0
    assert (
        precompute["power_capacity_rect_dp_deduped_start_options"]
        <= precompute["power_capacity_rect_dp_compiled_start_options"]
    )
    assert precompute["power_capacity_rect_dp_compiled_line_subsets"] > 0
    assert precompute["power_capacity_rect_dp_peak_line_subset_options"] > 0
    assert precompute["power_capacity_rect_dp_v3_fallbacks"] == 0
    assert precompute["power_capacity_m6x4_mixed_cpsat_evaluations"] == 0
    assert precompute["power_capacity_m6x4_mixed_cpsat_cache_hits"] == 0
    assert precompute["power_capacity_m6x4_mixed_cpsat_selected_cases"] == 0
    assert precompute["power_capacity_m6x4_mixed_cpsat_v3_fallbacks"] == 0
    assert precompute["power_capacity_bitset_oracle_evaluations"] == 0
    assert precompute["power_capacity_bitset_fallbacks"] == 0
    assert precompute["power_capacity_cpsat_fallbacks"] == 0
    assert precompute["power_capacity_oracle"] == "rectangle_frontier_dp_v4"
    assert precompute["power_capacity_signature_classes"] == stats["capacity_cache"]["signature_class_count"]
    assert precompute["power_capacity_raw_pole_evaluations"] == 2
    assert stats["power_capacity_families"] == {
        "applied": True,
        "family_count": 1,
        "raw_pole_count": 2,
        "coefficient_source": "exact_rect_dp_cache_v7",
        "shell_pair_count": 1,
        "compact_signature_class_count": 1,
        "families": [
            {
                "family_id": "family_000",
                "size": 2,
                "coefficients": {"powered_machine": 2},
            }
        ],
    }
    assert stats["aggregated_power_capacity_terms"] == {
        "applied": True,
        "raw_nonzero_terms": 2,
        "aggregated_nonzero_terms": 1,
    }


def test_compact_local_capacity_signature_matches_legacy_signature_and_cpsat_oracle() -> None:
    _clear_local_power_capacity_caches()
    model = _build_exact_power_capacity_model()
    model.build()

    compact_groups = model._power_pole_pose_indices_by_template_compact_capacity_signature[
        "powered_machine"
    ]
    legacy_by_compact = model._legacy_local_power_capacity_signature_by_template_compact_signature[
        "powered_machine"
    ]
    assert len(compact_groups) == 1

    for compact_signature, pose_indices in compact_groups.items():
        legacy_signature = legacy_by_compact[compact_signature]
        assert compact_signature == model._compact_local_power_capacity_signature(
            "powered_machine",
            pose_indices[0],
        )
        assert legacy_signature == model._local_power_capacity_signature(
            "powered_machine",
            pose_indices[0],
        )
        assert legacy_signature == model._materialize_local_power_capacity_signature_from_compact(
            "powered_machine",
            compact_signature,
        )
        assert model._solve_exact_local_power_capacity_rectangle_frontier_dp_v1(
            "powered_machine",
            compact_signature,
        ) == model._solve_exact_local_power_capacity_rectangle_frontier_dp_v2(
            "powered_machine",
            compact_signature,
        )
        assert model._solve_exact_local_power_capacity_rectangle_frontier_dp_v2(
            "powered_machine",
            compact_signature,
        ) == model._solve_exact_local_power_capacity_rectangle_frontier_dp_v3(
            "powered_machine",
            compact_signature,
        )
        assert model._solve_exact_local_power_capacity_rectangle_frontier_dp_v3(
            "powered_machine",
            compact_signature,
        ) == model._solve_exact_local_power_capacity_rectangle_frontier_dp_v4(
            "powered_machine",
            compact_signature,
        ) == model._solve_exact_local_power_capacity_cpsat(
            "powered_machine",
            legacy_signature,
        )
        assert model._solve_exact_local_power_capacity(
            "powered_machine",
            legacy_signature,
            compact_signature=compact_signature,
        ) == model._solve_exact_local_power_capacity_cpsat(
            "powered_machine",
            legacy_signature,
        )


def test_compact_local_capacity_signature_hard_fails_on_legacy_mismatch() -> None:
    _clear_local_power_capacity_caches()
    model = _build_exact_power_capacity_model()
    token = model._pose_local_shape_token_by_template_pose["powered_machine"][0]
    model._local_shape_by_template_token["powered_machine"][token] = ((999, 999),)
    model._local_power_capacity_signature_by_template_pole.pop("powered_machine", None)
    model._compact_local_power_capacity_signature_by_template_pole.pop("powered_machine", None)
    model._power_pole_pose_indices_by_template_capacity_signature.pop("powered_machine", None)
    model._power_pole_pose_indices_by_template_compact_capacity_signature.pop(
        "powered_machine",
        None,
    )
    model._legacy_local_power_capacity_signature_by_template_compact_signature.pop(
        "powered_machine",
        None,
    )

    with pytest.raises(RuntimeError, match="Compact local-capacity signature mismatch"):
        model._build_local_power_capacity_signature_classes("powered_machine")


def test_rectangle_frontier_dp_v4_matches_v3_v2_v1_bitset_and_cpsat_for_mixed_rectangles() -> None:
    _clear_local_power_capacity_caches()
    model = _build_exact_power_capacity_model()
    rect_tpl = "mixed_rectangles"
    shape_6x4 = tuple((x_val, y_val) for x_val in range(6) for y_val in range(4))
    shape_4x6 = tuple((x_val, y_val) for x_val in range(4) for y_val in range(6))
    model._local_shape_by_template_token[rect_tpl] = {
        0: shape_6x4,
        1: shape_4x6,
    }
    model._local_rectangle_variant_by_template_token.pop(rect_tpl, None)
    compact_signature = tuple(
        sorted(
            [
                (0, 0, 0),
                (6, 0, 0),
                (0, 4, 1),
                (4, 4, 1),
            ]
        )
    )
    legacy_signature = model._materialize_local_power_capacity_signature_from_compact(
        rect_tpl,
        compact_signature,
    )

    row_capacity_v1 = model._solve_exact_local_power_capacity_rectangle_frontier_dp_v1(
        rect_tpl,
        compact_signature,
        scan_axis="row",
    )
    column_capacity_v1 = model._solve_exact_local_power_capacity_rectangle_frontier_dp_v1(
        rect_tpl,
        compact_signature,
        scan_axis="column",
    )
    row_capacity_v2 = model._solve_exact_local_power_capacity_rectangle_frontier_dp_v2(
        rect_tpl,
        compact_signature,
        scan_axis="row",
    )
    column_capacity_v2 = model._solve_exact_local_power_capacity_rectangle_frontier_dp_v2(
        rect_tpl,
        compact_signature,
        scan_axis="column",
    )
    row_capacity_v3 = model._solve_exact_local_power_capacity_rectangle_frontier_dp_v3(
        rect_tpl,
        compact_signature,
        scan_axis="row",
    )
    column_capacity_v3 = model._solve_exact_local_power_capacity_rectangle_frontier_dp_v3(
        rect_tpl,
        compact_signature,
        scan_axis="column",
    )
    row_capacity_v4 = model._solve_exact_local_power_capacity_rectangle_frontier_dp_v4(
        rect_tpl,
        compact_signature,
        scan_axis="row",
    )
    column_capacity_v4 = model._solve_exact_local_power_capacity_rectangle_frontier_dp_v4(
        rect_tpl,
        compact_signature,
        scan_axis="column",
    )
    bitset_capacity = model._solve_exact_local_power_capacity_bitset_mis(
        rect_tpl,
        legacy_signature,
    )
    cpsat_capacity = model._solve_exact_local_power_capacity_cpsat(
        rect_tpl,
        legacy_signature,
    )

    assert (
        row_capacity_v1
        == column_capacity_v1
        == row_capacity_v2
        == column_capacity_v2
        == row_capacity_v3
        == column_capacity_v3
        == row_capacity_v4
        == column_capacity_v4
        == bitset_capacity
        == cpsat_capacity
        == 4
    )


def test_manufacturing_6x4_mixed_specialized_cpsat_matches_v3_bitset_and_legacy_cpsat() -> None:
    _clear_local_power_capacity_caches()
    model = _build_exact_power_capacity_model()

    shape_6x4 = tuple((x_val, y_val) for x_val in range(6) for y_val in range(4))
    shape_4x6 = tuple((x_val, y_val) for x_val in range(4) for y_val in range(6))
    model._local_shape_by_template_token["manufacturing_6x4"] = {0: shape_6x4, 1: shape_4x6}
    model._local_rectangle_variant_by_template_token.pop("manufacturing_6x4", None)

    compact_signature = tuple(
        sorted(
            [
                (0, 0, 0),
                (6, 0, 0),
                (0, 4, 1),
                (4, 4, 1),
            ]
        )
    )
    legacy_signature = model._materialize_local_power_capacity_signature_from_compact(
        "manufacturing_6x4",
        compact_signature,
    )

    specialized_capacity = (
        model._solve_exact_local_power_capacity_manufacturing_6x4_mixed_cpsat(
            "manufacturing_6x4",
            compact_signature,
        )
    )
    v3_capacity = model._solve_exact_local_power_capacity_rectangle_frontier_dp_v3(
        "manufacturing_6x4",
        compact_signature,
        scan_axis="row",
    )
    bitset_capacity = model._solve_exact_local_power_capacity_bitset_mis(
        "manufacturing_6x4",
        legacy_signature,
    )
    legacy_cpsat_capacity = model._solve_exact_local_power_capacity_cpsat(
        "manufacturing_6x4",
        legacy_signature,
    )

    assert (
        specialized_capacity
        == v3_capacity
        == bitset_capacity
        == legacy_cpsat_capacity
        == 4
    )


def test_rectangle_frontier_dp_v4_guarded_routing_uses_v4_for_small_5x5_and_specialized_cpsat_for_dense_6x4() -> None:
    _clear_local_power_capacity_caches()
    model = _build_exact_power_capacity_model()

    shape_5x5 = tuple((x_val, y_val) for x_val in range(5) for y_val in range(5))
    shape_6x4 = tuple((x_val, y_val) for x_val in range(6) for y_val in range(4))
    shape_4x6 = tuple((x_val, y_val) for x_val in range(4) for y_val in range(6))
    model._local_shape_by_template_token["representative_5x5"] = {0: shape_5x5}
    model._local_shape_by_template_token["manufacturing_6x4"] = {0: shape_6x4, 1: shape_4x6}
    model._local_rectangle_variant_by_template_token.pop("representative_5x5", None)
    model._local_rectangle_variant_by_template_token.pop("manufacturing_6x4", None)

    compact_signature_5x5 = tuple(
        sorted(
            [
                (0, 0, 0),
                (5, 0, 0),
                (0, 5, 0),
                (5, 5, 0),
                (10, 0, 0),
                (10, 5, 0),
            ]
        )
    )
    compact_signature_dense_6x4 = tuple(
        sorted(
            [
                (x_val, y_val, token)
                for x_val in range(16)
                for y_val in range(8)
                for token, (width, height) in ((0, (6, 4)), (1, (4, 6)))
                if x_val + width <= 16 and y_val + height <= 8
            ]
        )
    )

    compiled_5x5 = model._compile_rectangle_frontier_dp(
        "representative_5x5",
        compact_signature_5x5,
        scan_axis="row",
    )
    compiled_dense_6x4 = model._compile_rectangle_frontier_dp(
        "manufacturing_6x4",
        compact_signature_dense_6x4,
        scan_axis="row",
    )

    assert model._should_use_rectangle_frontier_dp_v4(compiled_5x5) is True
    assert model._should_use_rectangle_frontier_dp_v4(compiled_dense_6x4) is False

    cache_stats_v4 = {
        "rect_dp_v3_fallbacks": 0,
        "m6x4_mixed_cpsat_evaluations": 0,
        "m6x4_mixed_cpsat_cache_hits": 0,
        "m6x4_mixed_cpsat_selected_cases": 0,
        "m6x4_mixed_cpsat_v3_fallbacks": 0,
    }
    cache_stats_mixed = {
        "rect_dp_v3_fallbacks": 0,
        "m6x4_mixed_cpsat_evaluations": 0,
        "m6x4_mixed_cpsat_cache_hits": 0,
        "m6x4_mixed_cpsat_selected_cases": 0,
        "m6x4_mixed_cpsat_v3_fallbacks": 0,
    }
    routed_5x5 = model._solve_exact_local_power_capacity_rectangle_frontier_dp(
        "representative_5x5",
        compact_signature_5x5,
        scan_axis="row",
        cache_stats=cache_stats_v4,
    )
    routed_dense_6x4 = model._solve_exact_local_power_capacity_rectangle_frontier_dp(
        "manufacturing_6x4",
        compact_signature_dense_6x4,
        scan_axis="row",
        cache_stats=cache_stats_mixed,
    )
    direct_specialized = (
        model._solve_exact_local_power_capacity_manufacturing_6x4_mixed_cpsat(
            "manufacturing_6x4",
            compact_signature_dense_6x4,
            cache_stats={
                "m6x4_mixed_cpsat_evaluations": 0,
                "m6x4_mixed_cpsat_cache_hits": 0,
            },
        )
    )

    assert cache_stats_v4["rect_dp_v3_fallbacks"] == 0
    assert cache_stats_v4["m6x4_mixed_cpsat_selected_cases"] == 0
    assert cache_stats_mixed["rect_dp_v3_fallbacks"] == 0
    assert cache_stats_mixed["m6x4_mixed_cpsat_selected_cases"] == 1
    assert cache_stats_mixed["m6x4_mixed_cpsat_evaluations"] == 1
    assert cache_stats_mixed["m6x4_mixed_cpsat_v3_fallbacks"] == 0
    assert routed_5x5 == model._solve_exact_local_power_capacity_rectangle_frontier_dp_v4(
        "representative_5x5",
        compact_signature_5x5,
        scan_axis="row",
        compiled=compiled_5x5,
    )
    assert routed_dense_6x4 == direct_specialized
    assert routed_dense_6x4 == model._solve_exact_local_power_capacity_rectangle_frontier_dp_v3(
        "manufacturing_6x4",
        compact_signature_dense_6x4,
        scan_axis="row",
        compiled=compiled_dense_6x4,
    )


def test_manufacturing_6x4_mixed_specialized_cpsat_falls_back_to_v3_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_local_power_capacity_caches()
    model = _build_exact_power_capacity_model()

    shape_6x4 = tuple((x_val, y_val) for x_val in range(6) for y_val in range(4))
    shape_4x6 = tuple((x_val, y_val) for x_val in range(4) for y_val in range(6))
    model._local_shape_by_template_token["manufacturing_6x4"] = {0: shape_6x4, 1: shape_4x6}
    model._local_rectangle_variant_by_template_token.pop("manufacturing_6x4", None)
    compact_signature_dense_6x4 = tuple(
        sorted(
            [
                (x_val, y_val, token)
                for x_val in range(16)
                for y_val in range(8)
                for token, (width, height) in ((0, (6, 4)), (1, (4, 6)))
                if x_val + width <= 16 and y_val + height <= 8
            ]
        )
    )
    expected = model._solve_exact_local_power_capacity_rectangle_frontier_dp_v3(
        "manufacturing_6x4",
        compact_signature_dense_6x4,
        scan_axis="row",
    )

    def _force_fallback(*args: object, **kwargs: object) -> int:
        raise _Manufacturing6x4MixedCpSatFallback("forced_for_test")

    monkeypatch.setattr(
        model,
        "_solve_exact_local_power_capacity_manufacturing_6x4_mixed_cpsat",
        _force_fallback,
    )
    cache_stats = {
        "rect_dp_v3_fallbacks": 0,
        "m6x4_mixed_cpsat_evaluations": 0,
        "m6x4_mixed_cpsat_cache_hits": 0,
        "m6x4_mixed_cpsat_selected_cases": 0,
        "m6x4_mixed_cpsat_v3_fallbacks": 0,
    }

    routed = model._solve_exact_local_power_capacity_rectangle_frontier_dp(
        "manufacturing_6x4",
        compact_signature_dense_6x4,
        scan_axis="row",
        cache_stats=cache_stats,
    )

    assert cache_stats["m6x4_mixed_cpsat_selected_cases"] == 1
    assert cache_stats["m6x4_mixed_cpsat_v3_fallbacks"] == 1
    assert cache_stats["rect_dp_v3_fallbacks"] == 1
    assert routed == expected


def test_exact_local_power_capacity_rect_dp_falls_back_to_bitset_then_cpsat_without_losing_exactness() -> None:
    _clear_local_power_capacity_caches()
    model = _build_exact_power_capacity_model()
    model.build()
    non_rect_tpl = "non_rectangles"
    l_shape = ((0, 0), (1, 0), (1, 1))
    model._local_shape_by_template_token[non_rect_tpl] = {0: l_shape}
    model._local_rectangle_variant_by_template_token.pop(non_rect_tpl, None)
    compact_signature = tuple(sorted([(0, 0, 0), (2, 0, 0)]))
    legacy_signature = model._materialize_local_power_capacity_signature_from_compact(
        non_rect_tpl,
        compact_signature,
    )

    _LOCAL_POWER_CAPACITY_CACHE.clear()
    _LOCAL_POWER_CAPACITY_COMPACT_CACHE.clear()
    _LOCAL_POWER_CAPACITY_RECT_DP_CACHE.clear()
    model._local_power_capacity_bitset_max_iterations = 0
    cache_stats = {
        "rect_dp_evaluations": 0,
        "rect_dp_cache_hits": 0,
        "rect_dp_cache_misses": 0,
        "bitset_oracle_evaluations": 0,
        "bitset_fallbacks": 0,
        "cpsat_fallbacks": 0,
    }

    exact_capacity = model._solve_exact_local_power_capacity(
        non_rect_tpl,
        legacy_signature,
        compact_signature=compact_signature,
        cache_stats=cache_stats,
    )

    assert cache_stats["rect_dp_evaluations"] == 1
    assert cache_stats["rect_dp_cache_hits"] == 0
    assert cache_stats["rect_dp_cache_misses"] == 1
    assert cache_stats["bitset_fallbacks"] == 1
    assert cache_stats["bitset_oracle_evaluations"] == 1
    assert cache_stats["cpsat_fallbacks"] == 1
    assert exact_capacity == model._solve_exact_local_power_capacity_cpsat(
        non_rect_tpl,
        legacy_signature,
    )


def test_exact_search_guidance_orders_residual_power_poles_by_family() -> None:
    _clear_local_power_capacity_caches()
    model = _build_exact_power_capacity_model()

    model.build()

    guidance = model.build_stats["search_guidance"]
    family_stats = model.build_stats["global_valid_inequalities"]["power_capacity_families"]
    assert guidance["profile"] == "exact_coordinate_guided_branching_v4"
    assert guidance["power_pole_family_count_literals"] == family_stats["family_count"]
    assert guidance["power_pole_family_order"] == [
        family["family_id"] for family in family_stats["families"]
    ]
    assert guidance["residual_optional_family_guided"] is True

    status = model.solve(time_limit_seconds=5.0)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    delegate = model._coordinate_delegate
    assert delegate is not None
    pole_slots = delegate.residual_optional_slots["power_pole"]
    active_slots = [
        slot
        for slot in pole_slots
        if slot.active is not None and model._solver.Value(slot.active) == 1
    ]
    active_family_ints = [model._solver.Value(slot.family) for slot in active_slots if slot.family is not None]
    assert active_family_ints == sorted(active_family_ints)

    for left_slot, right_slot in zip(active_slots, active_slots[1:]):
        left_family = model._solver.Value(left_slot.family)
        right_family = model._solver.Value(right_slot.family)
        assert left_family <= right_family
        if left_family == right_family:
            assert model._solver.Value(left_slot.order_key) <= model._solver.Value(right_slot.order_key)

    active_family_counts: dict[str, int] = {}
    for slot in active_slots:
        family_int = model._solver.Value(slot.family)
        family_name = slot.family_id_to_family_name[family_int]
        active_family_counts[family_name] = active_family_counts.get(family_name, 0) + 1

    for family_name, count_var in delegate.power_pole_family_count_vars.items():
        assert model._solver.Value(count_var) == active_family_counts.get(family_name, 0)


def test_exact_geometric_power_coverage_uses_witness_indices_and_reuses_one_pole() -> None:
    _clear_local_power_capacity_caches()
    model = _build_exact_geometric_power_coverage_model()

    model.build()

    power_coverage = model.build_stats["power_coverage"]
    assert power_coverage == {
        "representation": "coordinate_geometric",
        "encoding": "geometric_element_witness_v1",
        "powered_slots": 2,
        "pole_slots": 2,
        "cover_literals": 0,
        "witness_indices": 2,
        "element_constraints": 6,
        "radius": 1,
    }

    status = model.solve(time_limit_seconds=5.0)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    solution = model.extract_solution()
    active_poles = [
        entry for entry in solution.values() if str(entry.get("facility_type")) == "power_pole"
    ]
    assert len(active_poles) == 1
    assert {str(entry["pose_id"]) for entry in active_poles} == {"pole_center"}


def test_exact_power_capacity_lower_bound_excludes_pole_overlapping_pose() -> None:
    _clear_local_power_capacity_caches()
    instances = [
        {
            "instance_id": "powered_001",
            "facility_type": "powered_machine",
            "operation_type": "processing",
            "is_mandatory": True,
            "bound_type": "exact",
        }
    ]
    pools = {
        "power_pole": [
            {
                "pose_id": "pole_0",
                "anchor": {"x": 0, "y": 0},
                "occupied_cells": [[0, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": [[0, 0], [1, 0]],
            }
        ],
        "protocol_storage_box": [],
        "powered_machine": [
            {
                "pose_id": "machine_overlap",
                "anchor": {"x": 0, "y": 0},
                "occupied_cells": [[0, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
            {
                "pose_id": "machine_safe",
                "anchor": {"x": 1, "y": 0},
                "occupied_cells": [[1, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
        ],
    }
    rules = {
        "globals": {"grid": {"width": 2, "height": 1}},
        "facility_templates": {
            "power_pole": {"dimensions": {"w": 1, "h": 1}, "needs_power": False},
            "protocol_storage_box": {"dimensions": {"w": 1, "h": 1}, "needs_power": True},
            "powered_machine": {"dimensions": {"w": 1, "h": 1}, "needs_power": True},
        },
    }

    model = MasterPlacementModel(
        instances,
        pools,
        rules,
        solve_mode="certified_exact",
    )
    model.build()

    assert model._power_coverers_by_template_pose["powered_machine"][0] == []
    assert model._power_coverers_by_template_pose["powered_machine"][1] == [0]
    assert model.build_stats["global_valid_inequalities"]["capacity_coeff_stats"]["powered_machine"] == {
        "demand": 1,
        "total_poles": 1,
        "nonzero_poles": 1,
        "max_coeff": 1,
        "min_nonzero_coeff": 1,
    }


def test_exact_optional_cardinality_bound_fixes_protocol_storage_box_count() -> None:
    instances = []
    pools = {
        "power_pole": [],
        "protocol_storage_box": [
            {
                "pose_id": "box_0",
                "anchor": {"x": 0, "y": 0},
                "occupied_cells": [[0, 0]],
                "input_port_cells": [{"x": 0, "y": 1, "dir": "N"}],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
            {
                "pose_id": "box_1",
                "anchor": {"x": 2, "y": 0},
                "occupied_cells": [[2, 0]],
                "input_port_cells": [{"x": 2, "y": 1, "dir": "N"}],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
        ],
    }
    rules = {
        "globals": {"grid": {"width": 4, "height": 4}},
        "facility_templates": {
            "power_pole": {"dimensions": {"w": 1, "h": 1}, "needs_power": False},
            "protocol_storage_box": {"dimensions": {"w": 1, "h": 1}, "needs_power": True},
        },
    }

    model = MasterPlacementModel(
        instances,
        pools,
        rules,
        solve_mode="certified_exact",
        skip_power_coverage=True,
        generic_io_requirements={
            "required_generic_outputs": {},
            "required_generic_inputs": {"valley_battery": 1, "qiaoyu_capsule": 1},
        },
    )
    model.build()

    bounds = model.build_stats["global_valid_inequalities"]["optional_cardinality_bounds"]
    assert bounds["protocol_storage_box"] == {
        "mode": "required_lower_bound",
        "required_generic_input_slots": 2,
        "slots_per_pose": 3,
        "lower": 1,
        "upper": None,
        "candidate_pose_count": 2,
        "slot_pool_upper_bound": 2,
    }
    assert model.build_stats["master_slot_counts"]["required_optionals"] == {}
    assert model.build_stats["master_slot_counts"]["residual_optionals"]["protocol_storage_box"] == 2
    box_slots = model._coordinate_delegate.residual_optional_slots["protocol_storage_box"]
    for slot in box_slots:
        model.model.Add(slot.active == 1)
    assert model.solve(time_limit_seconds=5.0) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    solution = model.extract_solution()
    protocol_boxes = [
        key for key in solution if key.startswith("pose_optional::protocol_storage_box::")
    ]
    assert protocol_boxes == [
        "pose_optional::protocol_storage_box::box_0",
        "pose_optional::protocol_storage_box::box_1",
    ]


def test_exact_optional_cardinality_bound_limits_power_poles_to_powered_facilities() -> None:
    instances = [
        {
            "instance_id": "powered_001",
            "facility_type": "powered_machine",
            "operation_type": "processing",
            "is_mandatory": True,
            "bound_type": "exact",
        }
    ]
    pools = {
        "power_pole": [
            {
                "pose_id": f"pole_{idx}",
                "anchor": {"x": idx, "y": 0},
                "occupied_cells": [[idx, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": [[idx, 0]],
            }
            for idx in range(3)
        ],
        "protocol_storage_box": [
            {
                "pose_id": "box_0",
                "anchor": {"x": 4, "y": 0},
                "occupied_cells": [[4, 0]],
                "input_port_cells": [{"x": 4, "y": 1, "dir": "N"}],
                "output_port_cells": [],
                "power_coverage_cells": None,
            }
        ],
        "powered_machine": [
            {
                "pose_id": "machine_0",
                "anchor": {"x": 6, "y": 0},
                "occupied_cells": [[6, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            }
        ],
    }
    rules = {
        "globals": {"grid": {"width": 8, "height": 2}},
        "facility_templates": {
            "power_pole": {"dimensions": {"w": 1, "h": 1}, "needs_power": False},
            "protocol_storage_box": {"dimensions": {"w": 1, "h": 1}, "needs_power": True},
            "powered_machine": {"dimensions": {"w": 1, "h": 1}, "needs_power": True},
        },
    }

    model = MasterPlacementModel(
        instances,
        pools,
        rules,
        solve_mode="certified_exact",
        skip_power_coverage=True,
        generic_io_requirements={
            "required_generic_outputs": {},
            "required_generic_inputs": {"valley_battery": 1},
        },
    )
    model.build()

    bounds = model.build_stats["global_valid_inequalities"]["optional_cardinality_bounds"]
    assert bounds["power_pole"] == {
        "mode": "selected_powered_upper_bound",
        "lower": 0,
        "candidate_pose_count": 3,
        "mandatory_powered_nonpole": 1,
        "optional_powered_templates": ["protocol_storage_box"],
        "slot_pool_upper_bound": 2,
    }
    assert model.build_stats["master_slot_counts"]["residual_optionals"]["power_pole"] == 2
    assert model.build_stats["master_pose_bool_literals"] == 0


def test_coordinate_exact_v2_emits_factorized_domain_and_shell_metadata() -> None:
    model = MasterPlacementModel(
        instances=[],
        facility_pools={
            "power_pole": [
                {
                    "pose_id": f"pole_{idx}",
                    "anchor": {"x": idx, "y": 0},
                    "occupied_cells": [[idx, 0]],
                    "input_port_cells": [],
                    "output_port_cells": [],
                    "power_coverage_cells": [[idx, 0]],
                }
                for idx in range(3)
            ],
            "protocol_storage_box": [
                {
                    "pose_id": "box_0",
                    "anchor": {"x": 0, "y": 1},
                    "occupied_cells": [[0, 1]],
                    "input_port_cells": [{"x": 0, "y": 2, "dir": "N"}],
                    "output_port_cells": [],
                    "power_coverage_cells": None,
                }
            ],
        },
        rules={
            "globals": {"grid": {"width": 4, "height": 4}},
            "facility_templates": {
                "power_pole": {"dimensions": {"w": 1, "h": 1}, "needs_power": False},
                "protocol_storage_box": {"dimensions": {"w": 1, "h": 1}, "needs_power": True},
            },
        },
        solve_mode="certified_exact",
        skip_power_coverage=True,
        generic_io_requirements={
            "required_generic_outputs": {},
            "required_generic_inputs": {"valley_battery": 1},
        },
    )

    model.build()

    assert model.build_stats["master_representation"] == "coordinate_exact_v2"
    assert model.build_stats["master_domain_encoding"] == "mode_rect_factorized_v1"
    assert model.build_stats["master_domain_table_rows"] == 0
    assert model.build_stats["master_mode_rect_domains"]["required_optionals"] == {}
    assert "protocol_storage_box" in model.build_stats["master_mode_rect_domains"]["residual_optionals"]
    assert "power_pole" in model.build_stats["master_mode_rect_domains"]["residual_optionals"]
    assert "pair_count" in model.build_stats["power_pole_shell_lookup_pairs"]


def test_exact_power_capacity_lower_bound_includes_protocol_storage_box_lower_bound_demand() -> None:
    _clear_local_power_capacity_caches()
    model = MasterPlacementModel(
        instances=[],
        facility_pools={
            "power_pole": [
                {
                    "pose_id": "pole_0",
                    "anchor": {"x": 0, "y": 0},
                    "occupied_cells": [[0, 0]],
                    "input_port_cells": [],
                    "output_port_cells": [],
                    "power_coverage_cells": [[1, 0]],
                }
            ],
            "protocol_storage_box": [
                {
                    "pose_id": "box_0",
                    "anchor": {"x": 1, "y": 0},
                    "occupied_cells": [[1, 0]],
                    "input_port_cells": [{"x": 1, "y": 1, "dir": "N"}],
                    "output_port_cells": [],
                    "power_coverage_cells": None,
                }
            ],
        },
        rules={
            "globals": {"grid": {"width": 3, "height": 2}},
            "facility_templates": {
                "power_pole": {"dimensions": {"w": 1, "h": 1}, "needs_power": False},
                "protocol_storage_box": {"dimensions": {"w": 1, "h": 1}, "needs_power": True},
            },
        },
        solve_mode="certified_exact",
        generic_io_requirements={
            "required_generic_outputs": {},
            "required_generic_inputs": {"valley_battery": 1},
        },
    )

    model.build()

    stats = model.build_stats["global_valid_inequalities"]
    assert model.build_stats["exact_required_optionals"] == {}
    assert model.build_stats["exact_optional_lower_bounds"] == {"protocol_storage_box": 1}
    assert stats["fixed_required_optional_demands"] == {}
    assert stats["lower_bound_optional_powered_demands"] == {"protocol_storage_box": 1}
    assert stats["powered_template_demands"] == {"protocol_storage_box": 1}
    assert stats["capacity_coeff_stats"]["protocol_storage_box"] == {
        "demand": 1,
        "total_poles": 1,
        "nonzero_poles": 1,
        "max_coeff": 1,
        "min_nonzero_coeff": 1,
    }
    assert {
        "type": "power_capacity_lower_bound",
        "template": "protocol_storage_box",
        "demand": 1,
        "nonzero_poles": 1,
    } in stats["applied"]
    assert stats["power_capacity_families"] == {
        "applied": True,
        "family_count": 1,
        "raw_pole_count": 1,
        "coefficient_source": "exact_rect_dp_cache_v7",
        "shell_pair_count": 1,
        "compact_signature_class_count": 1,
        "families": [
            {
                "family_id": "family_000",
                "size": 1,
                "coefficients": {"protocol_storage_box": 1},
            }
        ],
    }


def test_exploratory_mode_does_not_apply_exact_power_capacity_lower_bound() -> None:
    _clear_local_power_capacity_caches()
    model = _build_exact_power_capacity_model(solve_mode="exploratory")

    model.build()

    stats = model.build_stats["global_valid_inequalities"]
    assert stats["applied"] == []
    assert stats["powered_template_demands"] == {}
    assert stats["capacity_cache"]["pole_template_evaluations"] == 0
    assert stats["capacity_cache"]["signature_class_evaluations"] == 0
    assert stats["capacity_cache"]["compact_signature_class_evaluations"] == 0
    assert stats["capacity_cache"]["rect_dp_evaluations"] == 0
    assert stats["capacity_cache"]["bitset_oracle_evaluations"] == 0
    assert stats["capacity_cache"]["bitset_fallbacks"] == 0
    assert stats["capacity_cache"]["cpsat_fallbacks"] == 0
    assert stats["capacity_cache"]["raw_pole_evaluations"] == 0
    assert stats["capacity_cache"]["coefficient_source"] == "exact_rect_dp_cache_v7"


def test_exact_core_clone_rebinds_solution_extraction_and_benders_cuts() -> None:
    instances = [
        {
            "instance_id": "miner_001",
            "facility_type": "miner",
            "operation_type": "mining",
            "is_mandatory": True,
            "bound_type": "exact",
        }
    ]
    pools = {
        "miner": [
            {
                "pose_id": "pose_left",
                "anchor": {"x": 0, "y": 0},
                "occupied_cells": [[0, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
            {
                "pose_id": "pose_mid",
                "anchor": {"x": 1, "y": 0},
                "occupied_cells": [[1, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
        ]
    }
    rules = {
        "globals": {"grid": {"width": 3, "height": 1}},
        "facility_templates": {
            "miner": {"dimensions": {"w": 1, "h": 1}, "needs_power": False},
        },
    }

    core = MasterPlacementModel.build_exact_core(
        instances,
        pools,
        rules,
        skip_power_coverage=True,
    )
    overlay = MasterPlacementModel.from_exact_core(core, ghost_rect=(1, 1))
    forced_anchor_idx = next(
        idx
        for idx, domain in enumerate(overlay._ghost_domains)
        if domain["anchor"] == {"x": 2, "y": 0}
    )
    overlay.model.Add(overlay.u_vars[forced_anchor_idx] == 1)

    status = overlay.solve(time_limit_seconds=5.0)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    first_solution = overlay.extract_solution()
    first_pose_idx = int(first_solution["miner_001"]["pose_idx"])
    assert overlay.build_stats["exact_core_reuse"]["used"] is True
    assert overlay.build_stats["ghost_rect"]["size"] == {"w": 1, "h": 1}
    assert core.master_representation == "coordinate_exact_v2"
    assert overlay.build_stats["master_domain_table_rows"] == 0
    assert all("rank" not in binding for binding in core.coordinate_binding["slot_binding"].values())

    assert overlay.add_benders_cut({"miner_001": first_pose_idx}) is True
    status = overlay.solve(time_limit_seconds=5.0)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    second_solution = overlay.extract_solution()
    assert int(second_solution["miner_001"]["pose_idx"]) != first_pose_idx
