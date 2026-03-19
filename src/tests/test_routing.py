"""
Tests for Group 5: routing subproblem, benders loop, and outer search.
Status: ACCEPTED_DRAFT

验证路由子问题的基本功能和搜索引擎接口。
注意：全量路由求解太耗时，仅测试模型构建和小规模求解。
"""

import json
import pytest
from pathlib import Path
from typing import Dict, Any

# ============================================================================
# 夹具
# ============================================================================

@pytest.fixture(scope="session")
def project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


# ============================================================================
# 路由子问题测试
# ============================================================================

def test_routing_grid_construction(project_root):
    """路由网格应从占据格集合正确构建。"""
    import sys
    sys.path.insert(0, str(project_root))
    from src.models.routing_subproblem import RoutingGrid

    # 简单场景：中间 3x3 被占据
    occupied = {(x, y) for x in range(34, 37) for y in range(34, 37)}
    port_specs = [
        {"instance_id": "m1", "x": 37, "y": 35, "dir": "E",
         "type": "out", "commodity": "iron"},
    ]

    grid = RoutingGrid(occupied, port_specs)

    assert len(grid.free_cells) == 70 * 70 - 9  # 4900 - 9
    assert (34, 34) not in grid.free_cells
    assert (33, 33) in grid.free_cells
    assert (37, 35) in grid.port_cells


def test_routing_small_solve(project_root):
    """小规模路由模型应能构建并求解。"""
    import sys
    sys.path.insert(0, str(project_root))
    from src.models.routing_subproblem import RoutingGrid, RoutingSubproblem

    # 极小场景：全场只有 1 对端口
    occupied = {(x, y) for x in range(0, 3) for y in range(0, 3)}
    port_specs = [
        {"instance_id": "m1", "x": 3, "y": 1, "dir": "E",
         "type": "out", "commodity": "test"},
        {"instance_id": "m2", "x": 6, "y": 1, "dir": "W",
         "type": "in", "commodity": "test"},
    ]

    grid = RoutingGrid(occupied, port_specs)
    routing = RoutingSubproblem(grid, ["test"])
    routing.build()

    result = routing.solve(time_limit=10.0)
    assert result in ("FEASIBLE", "INFEASIBLE", "TIMEOUT")


def test_routing_supports_splitter_state(project_root):
    """1 source -> 2 sinks of the same commodity should be routable via a splitter."""
    import sys

    sys.path.insert(0, str(project_root))
    from src.models.routing_subproblem import RoutingGrid, RoutingSubproblem

    allowed = {(x, 2) for x in range(1, 8)} | {(7, 1), (8, 1), (7, 3), (8, 3)}
    occupied = {
        (x, y)
        for x in range(70)
        for y in range(70)
        if (x, y) not in allowed
    }
    port_specs = [
        {"instance_id": "src", "x": 0, "y": 2, "dir": "E", "type": "out", "commodity": "test"},
        {"instance_id": "sink_a", "x": 8, "y": 2, "dir": "S", "type": "in", "commodity": "test"},
        {"instance_id": "sink_b", "x": 8, "y": 2, "dir": "N", "type": "in", "commodity": "test"},
    ]

    routing = RoutingSubproblem(RoutingGrid(occupied, port_specs), ["test"])
    routing.build()

    result = routing.solve(time_limit=10.0)
    assert result == "FEASIBLE"

    routes = routing.extract_routes()
    assert any(seg["component_type"] == "splitter" for seg in routes)


def test_packaging_battery_pose_binding_domain(project_root):
    """6x4 电池封装机的 pose-level 绑定域应可被精确枚举。"""
    import sys

    sys.path.insert(0, str(project_root))
    from src.models.port_binding import enumerate_pose_level_port_bindings

    pools = json.loads(
        (project_root / "data" / "preprocessed" / "candidate_placements.json").read_text(
            encoding="utf-8"
        )
    )["facility_pools"]
    pose = pools["manufacturing_6x4"][0]

    bindings = enumerate_pose_level_port_bindings("packaging_battery", pose)
    assert len(bindings) == 360

    first = bindings[0]
    assert len(first["input_ports"]) == 5
    assert len(first["output_ports"]) == 1
    assert sum(1 for port in first["input_ports"] if port["commodity"] == "dense_source_powder") == 3
    assert sum(1 for port in first["input_ports"] if port["commodity"] == "steel_part") == 2
    assert first["output_ports"][0]["commodity"] == "valley_battery"


def test_crusher_sandleaf_pose_binding_domain(project_root):
    """3x3 三输出工序的绑定域规模应符合组合数。"""
    import sys

    sys.path.insert(0, str(project_root))
    from src.models.port_binding import enumerate_pose_level_port_bindings

    pools = json.loads(
        (project_root / "data" / "preprocessed" / "candidate_placements.json").read_text(
            encoding="utf-8"
        )
    )["facility_pools"]
    pose = pools["manufacturing_3x3"][0]

    bindings = enumerate_pose_level_port_bindings("crusher_sandleaf", pose)
    assert len(bindings) == 3
    assert all(len(binding["input_ports"]) == 1 for binding in bindings)
    assert all(len(binding["output_ports"]) == 3 for binding in bindings)
    assert all(port["commodity"] == "sandleaf_powder" for port in bindings[0]["output_ports"])


def test_generic_hub_binding_is_not_locally_enumerable(project_root):
    """boundary/core 的 generic 口仍需更高层 exact 分配，局部枚举器应拒绝硬绑定。"""
    import sys

    sys.path.insert(0, str(project_root))
    from src.models.port_binding import (
        enumerate_pose_level_port_bindings,
        supports_exact_pose_level_binding,
    )

    pools = json.loads(
        (project_root / "data" / "preprocessed" / "candidate_placements.json").read_text(
            encoding="utf-8"
        )
    )["facility_pools"]
    pose = pools["protocol_core"][0]

    assert supports_exact_pose_level_binding("protocol_core") is False
    with pytest.raises(ValueError):
        enumerate_pose_level_port_bindings("protocol_core", pose)


def test_port_balance_analysis_identifies_dead_end_and_split_merge_needs(project_root):
    import sys

    sys.path.insert(0, str(project_root))
    from src.models.cut_manager import analyze_port_balance

    port_specs = [
        {"instance_id": "a", "x": 1, "y": 1, "dir": "E", "type": "out", "commodity": "capsule"},
        {"instance_id": "b", "x": 2, "y": 1, "dir": "W", "type": "out", "commodity": "capsule"},
        {"instance_id": "c", "x": 3, "y": 1, "dir": "E", "type": "out", "commodity": "ore"},
        {"instance_id": "d", "x": 4, "y": 1, "dir": "W", "type": "in", "commodity": "ore"},
        {"instance_id": "e", "x": 5, "y": 1, "dir": "W", "type": "in", "commodity": "ore"},
        {"instance_id": "f", "x": 6, "y": 1, "dir": "E", "type": "out", "commodity": "powder"},
        {"instance_id": "g", "x": 7, "y": 1, "dir": "E", "type": "out", "commodity": "powder"},
        {"instance_id": "h", "x": 8, "y": 1, "dir": "W", "type": "in", "commodity": "powder"},
    ]

    diag = analyze_port_balance(port_specs)
    assert diag["dead_end"]["capsule"] == {"in": 0, "out": 2}
    assert diag["needs_splitter"]["ore"]["delta"] == 1
    assert diag["needs_merger"]["powder"]["delta"] == 1


def test_exact_routing_precheck_flags_front_blocked(project_root):
    import sys

    sys.path.insert(0, str(project_root))
    from src.models.routing_subproblem import RoutingGrid, run_exact_routing_precheck

    occupied = {(1, 0)}
    port_specs = [
        {"instance_id": "src", "x": 0, "y": 0, "dir": "E", "type": "out", "commodity": "ore"},
    ]

    precheck = run_exact_routing_precheck(
        RoutingGrid(occupied, port_specs),
        occupied_owner_by_cell={(1, 0): "blocker"},
    )

    assert precheck["status"] == "front_blocked"
    assert precheck["binding_selection_safe_reject"] is True
    assert precheck["placement_level_conflict_set"] == ["src", "blocker"]
    assert precheck["blocked_ports"][0]["front_cell"] == [1, 0]


def test_exact_routing_precheck_flags_relaxed_disconnected(project_root):
    import sys

    sys.path.insert(0, str(project_root))
    from src.models.routing_subproblem import RoutingGrid, run_exact_routing_precheck

    allowed = {(1, 1), (5, 5)}
    occupied = {
        (x, y)
        for x in range(70)
        for y in range(70)
        if (x, y) not in allowed
    }
    port_specs = [
        {"instance_id": "src", "x": 0, "y": 1, "dir": "E", "type": "out", "commodity": "ore"},
        {"instance_id": "sink", "x": 6, "y": 5, "dir": "W", "type": "in", "commodity": "ore"},
    ]

    precheck = run_exact_routing_precheck(RoutingGrid(occupied, port_specs))

    assert precheck["status"] == "relaxed_disconnected"
    assert precheck["binding_selection_safe_reject"] is True
    assert precheck["placement_level_conflict_set"] == []
    assert precheck["disconnected_commodities"][0]["commodity"] == "ore"


def test_terminal_aware_peeling_prunes_non_terminal_dead_end_branch(project_root):
    import sys

    sys.path.insert(0, str(project_root))
    from src.models.routing_subproblem import RoutingGrid, analyze_exact_routing_domain

    allowed = {(x, 2) for x in range(1, 9)} | {(4, 3), (4, 4)}
    occupied = {
        (x, y)
        for x in range(70)
        for y in range(70)
        if (x, y) not in allowed
    }
    port_specs = [
        {"instance_id": "src", "x": 0, "y": 2, "dir": "E", "type": "out", "commodity": "ore"},
        {"instance_id": "sink", "x": 8, "y": 3, "dir": "S", "type": "in", "commodity": "ore"},
    ]

    analysis = analyze_exact_routing_domain(RoutingGrid(occupied, port_specs))

    assert analysis["status"] == "feasible"
    assert analysis["domain_stats"]["commodity_component_cells"]["ore"] == 10
    assert analysis["domain_stats"]["commodity_active_cells"]["ore"] == 8
    assert [4, 3] not in analysis["commodity_active_cells"]["ore"]
    assert [4, 4] not in analysis["commodity_active_cells"]["ore"]
    assert [1, 2] in analysis["commodity_active_cells"]["ore"]
    assert [8, 2] in analysis["commodity_active_cells"]["ore"]


def test_routing_local_pattern_filter_reduces_state_space_without_changing_feasibility(project_root):
    import sys

    sys.path.insert(0, str(project_root))
    from src.models.routing_subproblem import RoutingGrid, RoutingSubproblem

    allowed = {(x, 2) for x in range(1, 9)} | {(4, 3), (4, 4)}
    occupied = {
        (x, y)
        for x in range(70)
        for y in range(70)
        if (x, y) not in allowed
    }
    port_specs = [
        {"instance_id": "src", "x": 0, "y": 2, "dir": "E", "type": "out", "commodity": "ore"},
        {"instance_id": "sink", "x": 8, "y": 3, "dir": "S", "type": "in", "commodity": "ore"},
    ]

    routing = RoutingSubproblem(RoutingGrid(occupied, port_specs), ["ore"])
    routing.build()
    state_space = routing.build_stats["state_space"]

    assert state_space["vars"] < state_space["naive_full_domain_vars"]
    assert state_space["domain_cells"] > state_space["terminal_core_cells"]
    assert state_space["local_pattern_pruned_states"] > 0
    assert routing.solve(time_limit=10.0) == "FEASIBLE"


def test_elevated_bridge_states_require_opposite_neighbors(project_root):
    import sys

    sys.path.insert(0, str(project_root))
    from src.models.routing_subproblem import RoutingGrid, RoutingSubproblem

    allowed = {(2, 2), (3, 2)}
    occupied = {
        (x, y)
        for x in range(70)
        for y in range(70)
        if (x, y) not in allowed
    }
    port_specs = [
        {"instance_id": "src", "x": 1, "y": 2, "dir": "E", "type": "out", "commodity": "ore"},
        {"instance_id": "sink", "x": 3, "y": 3, "dir": "S", "type": "in", "commodity": "ore"},
    ]

    routing = RoutingSubproblem(RoutingGrid(occupied, port_specs), ["ore"])
    routing.build()

    elevated_states = [
        key for key in routing.r_vars
        if key[2] == 1
    ]
    assert elevated_states == []


def test_routing_placement_core_precheck_matches_grid_path(project_root):
    import sys

    sys.path.insert(0, str(project_root))
    from src.models.routing_subproblem import (
        RoutingGrid,
        RoutingPlacementCore,
        analyze_exact_routing_domain,
        run_exact_routing_precheck,
    )

    feasible_allowed = {(x, 2) for x in range(1, 9)} | {(4, 3), (4, 4)}
    disconnected_allowed = {(1, 1), (5, 5)}
    cases = [
        (
            "front_blocked",
            {(1, 0)},
            [{"instance_id": "src", "x": 0, "y": 0, "dir": "E", "type": "out", "commodity": "ore"}],
            {(1, 0): "blocker"},
        ),
        (
            "relaxed_disconnected",
            {
                (x, y)
                for x in range(70)
                for y in range(70)
                if (x, y) not in disconnected_allowed
            },
            [
                {"instance_id": "src", "x": 0, "y": 1, "dir": "E", "type": "out", "commodity": "ore"},
                {"instance_id": "sink", "x": 6, "y": 5, "dir": "W", "type": "in", "commodity": "ore"},
            ],
            {},
        ),
        (
            "feasible",
            {
                (x, y)
                for x in range(70)
                for y in range(70)
                if (x, y) not in feasible_allowed
            },
            [
                {"instance_id": "src", "x": 0, "y": 2, "dir": "E", "type": "out", "commodity": "ore"},
                {"instance_id": "sink", "x": 8, "y": 3, "dir": "S", "type": "in", "commodity": "ore"},
            ],
            {},
        ),
    ]

    for expected_status, occupied, port_specs, owner_map in cases:
        grid = RoutingGrid(occupied, list(port_specs), occupied_owner_by_cell=owner_map)
        placement_core = RoutingPlacementCore.from_occupied_cells(
            occupied,
            occupied_owner_by_cell=owner_map,
        )

        grid_analysis = analyze_exact_routing_domain(
            grid,
            occupied_owner_by_cell=owner_map,
        )
        core_analysis = analyze_exact_routing_domain(
            placement_core=placement_core,
            port_specs=port_specs,
            occupied_owner_by_cell=owner_map,
        )
        grid_precheck = run_exact_routing_precheck(
            grid,
            occupied_owner_by_cell=owner_map,
        )
        core_precheck = run_exact_routing_precheck(
            placement_core=placement_core,
            port_specs=port_specs,
            occupied_owner_by_cell=owner_map,
        )

        assert grid_analysis["status"] == expected_status
        assert core_analysis["status"] == expected_status
        assert grid_analysis["domain_stats"] == core_analysis["domain_stats"]
        assert grid_precheck["status"] == core_precheck["status"]
        assert grid_precheck["placement_level_conflict_set"] == core_precheck["placement_level_conflict_set"]


def test_routing_subproblem_from_placement_core_matches_grid_build(project_root):
    import sys

    sys.path.insert(0, str(project_root))
    from src.models.routing_subproblem import RoutingGrid, RoutingPlacementCore, RoutingSubproblem

    allowed = {(x, 2) for x in range(1, 9)} | {(4, 3), (4, 4)}
    occupied = {
        (x, y)
        for x in range(70)
        for y in range(70)
        if (x, y) not in allowed
    }
    port_specs_a = [
        {"instance_id": "src_a", "x": 0, "y": 2, "dir": "E", "type": "out", "commodity": "ore"},
        {"instance_id": "sink_a", "x": 8, "y": 3, "dir": "S", "type": "in", "commodity": "ore"},
    ]
    port_specs_b = [
        {"instance_id": "src_b", "x": 1, "y": 2, "dir": "E", "type": "out", "commodity": "ore"},
        {"instance_id": "sink_b", "x": 7, "y": 2, "dir": "W", "type": "in", "commodity": "ore"},
    ]
    placement_core = RoutingPlacementCore.from_occupied_cells(occupied)

    for port_specs in (port_specs_a, port_specs_b):
        routing_from_grid = RoutingSubproblem(RoutingGrid(occupied, list(port_specs)), ["ore"])
        routing_from_grid.build()

        routing_from_core = RoutingSubproblem.from_placement_core(
            placement_core,
            port_specs,
            ["ore"],
        )
        routing_from_core.build()

        assert routing_from_core.grid.placement_core is placement_core
        core_state_space = dict(routing_from_core.build_stats["state_space"])
        grid_state_space = dict(routing_from_grid.build_stats["state_space"])
        assert core_state_space.pop("used_placement_core_reuse") is True
        assert grid_state_space.pop("used_placement_core_reuse") is False
        assert core_state_space == grid_state_space
        assert routing_from_core.solve(time_limit=10.0) == routing_from_grid.solve(time_limit=10.0)


# ============================================================================
# Benders Loop 接口测试
# ============================================================================

def test_benders_loop_import(project_root):
    """benders_loop 模块应能正常导入。"""
    import sys
    sys.path.insert(0, str(project_root))
    from src.search.benders_loop import run_benders_for_ghost_rect
    assert callable(run_benders_for_ghost_rect)


# ============================================================================
# 外层搜索测试
# ============================================================================

def test_candidate_sizes_generation(project_root):
    """候选尺寸应按面积降序排列。"""
    import sys
    sys.path.insert(0, str(project_root))
    from src.search.outer_search import generate_candidate_sizes

    sizes = generate_candidate_sizes(max_w=10, max_h=10, min_side=3)

    # 面积应降序
    areas = [a for a, w, h in sizes]
    assert areas == sorted(areas, reverse=True)

    # 最大面积应为 10x10=100
    assert sizes[0] == (100, 10, 10)

    # 最小面积应为 3x3=9
    assert sizes[-1] == (9, 3, 3)

    # w >= h 避免重复
    for a, w, h in sizes:
        assert w >= h


def test_outer_search_import(project_root):
    """outer_search 模块应能正常导入。"""
    import sys
    sys.path.insert(0, str(project_root))
    from src.search.outer_search import run_outer_search
    assert callable(run_outer_search)
