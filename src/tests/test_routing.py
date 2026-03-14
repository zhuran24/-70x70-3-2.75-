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

    allowed = {(x, y) for x in range(0, 10) for y in range(0, 5)}
    occupied = {
        (x, y)
        for x in range(70)
        for y in range(70)
        if (x, y) not in allowed
    }
    port_specs = [
        {"instance_id": "src", "x": 1, "y": 2, "dir": "E", "type": "out", "commodity": "test"},
        {"instance_id": "sink_a", "x": 8, "y": 1, "dir": "W", "type": "in", "commodity": "test"},
        {"instance_id": "sink_b", "x": 8, "y": 3, "dir": "W", "type": "in", "commodity": "test"},
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
