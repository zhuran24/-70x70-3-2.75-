"""
Tests for Group 4 Master Model Layer.
Status: ACCEPTED_DRAFT

验证主模型构建、子问题接口、切平面管理器的正确性。
注意：本测试不执行完整求解（太耗时），仅验证模型构建与数据一致性。
"""

import json
import pytest
from pathlib import Path
from typing import Dict, Any

# ============================================================================
# 夹具 (Fixtures)
# ============================================================================

@pytest.fixture(scope="session")
def project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="session")
def project_data(project_root):
    import sys
    sys.path.insert(0, str(project_root))
    from src.models.master_model import load_project_data
    return load_project_data(project_root)


@pytest.fixture(scope="session")
def instances(project_data):
    return project_data[0]


@pytest.fixture(scope="session")
def pools(project_data):
    return project_data[1]


@pytest.fixture(scope="session")
def rules(project_data):
    return project_data[2]


# ============================================================================
# 模型构建测试
# ============================================================================

def test_master_model_builds(project_root, instances, pools, rules):
    """主模型必须能够无错误地完成构建。
    
    注意：skip_power_coverage=True 因为供电蕴含约束在全量规模下
    构建耗时 >5min (O(10^9) LHS terms)，不适合 CI 测试。
    供电覆盖的正确性在单独的集成测试中验证。
    """
    import sys
    sys.path.insert(0, str(project_root))
    from src.models.master_model import MasterPlacementModel

    model = MasterPlacementModel(instances, pools, rules, skip_power_coverage=True)
    model.build()

    # Grouped encoding: mandatory placement vars are keyed by operation-groups, not clones.
    assert model.build_stats["grouped_encoding"]["mandatory_instances"] == 266
    assert model.build_stats["grouped_encoding"]["mandatory_groups"] == 19
    assert len(model.z_vars) == 19, f"z_vars 应有 19 个 mandatory operation-groups, 实际 {len(model.z_vars)}"
    assert len(model.x_vars) == 0, f"x_vars 应为 0（可选设施已改为 pose-level 建模）, 实际 {len(model.x_vars)}"
    assert "power_pole" in model.optional_pose_vars
    assert "protocol_storage_box" in model.optional_pose_vars
    assert len(model.optional_pose_vars["power_pole"]) == len(pools["power_pole"])
    assert len(model.optional_pose_vars["protocol_storage_box"]) == len(pools["protocol_storage_box"])


def test_mandatory_optional_split(instances):
    """强制/可选实例数量必须符合预期。"""
    mandatory = [i for i in instances if i["is_mandatory"]]
    optional = [i for i in instances if not i["is_mandatory"]]
    assert len(mandatory) == 266
    assert len(optional) == 60


def test_powered_types_identified(project_root, rules):
    """需电设施类型应被正确识别。"""
    templates = rules["facility_templates"]
    powered = {k for k, v in templates.items() if v.get("needs_power", False)}

    # 预期: 3x3, 5x5, 6x4 制造单位 + 协议箱
    expected = {"manufacturing_3x3", "manufacturing_5x5", "manufacturing_6x4",
                "protocol_storage_box"}
    assert powered == expected


def test_pole_instances_count(instances):
    """供电桩实例数应为 50。"""
    poles = [i for i in instances if i["facility_type"] == "power_pole"]
    assert len(poles) == 50


# ============================================================================
# 切平面管理器测试
# ============================================================================

def test_cut_manager_deduplication(project_root):
    """切平面管理器应自动去重。"""
    import sys
    sys.path.insert(0, str(project_root))
    from src.models.cut_manager import CutManager, BendersCut

    cm = CutManager()

    cut1 = BendersCut("topo", {"inst_A": 0, "inst_B": 1}, 1)
    cut2 = BendersCut("topo", {"inst_A": 0, "inst_B": 1}, 2)  # 同一冲突集
    cut3 = BendersCut("topo", {"inst_A": 0, "inst_C": 2}, 3)  # 不同冲突集

    assert cm.add_cut(cut1) is True   # 首次添加
    assert cm.add_cut(cut2) is False  # 重复
    assert cm.add_cut(cut3) is True   # 新切面
    assert len(cm.cuts) == 2


def test_cut_serialization(project_root, tmp_path):
    """切平面必须能序列化和反序列化。"""
    import sys
    sys.path.insert(0, str(project_root))
    from src.models.cut_manager import CutManager, BendersCut

    cm = CutManager()
    cm.add_cut(BendersCut("topo", {"a": 0, "b": 1}, 1))
    cm.add_cut(BendersCut("micro", {"c": 2}, 2))

    path = tmp_path / "cuts.json"
    cm.save(path)

    cm2 = CutManager()
    cm2.load(path)
    assert len(cm2.cuts) == 2
    assert cm2.cuts[0].cut_type == "topo"
    assert cm2.cuts[1].cut_type == "micro"


# ============================================================================
# 流子问题接口测试
# ============================================================================

def test_flow_network_construction(project_root):
    """流网络应能从简单输入构建。"""
    import sys
    sys.path.insert(0, str(project_root))
    from src.models.flow_subproblem import FlowNetwork, build_flow_network

    # 极小测试：3x3 网格，中心 1x1 被占据
    occupied = {(1, 1)}
    port_dict = {
        "test_commodity": [
            {"x": 0, "y": 1, "dir": "E", "type": "out", "instance_id": "src_1"},
            {"x": 2, "y": 1, "dir": "W", "type": "in", "instance_id": "snk_1"},
        ]
    }
    demands = {"test_commodity": 1.0}

    # 使用 70x70 网格但大部分是空的
    net = build_flow_network(occupied, port_dict, demands)
    assert len(net.nodes) > 0
    assert len(net.edges) > 0


# ============================================================================
# Benders cut 接口集成测试
# ============================================================================

def test_benders_cut_integration(project_root, instances, pools, rules):
    """Benders 切平面应能无错误地注入主模型。"""
    import sys
    sys.path.insert(0, str(project_root))
    from src.models.master_model import MasterPlacementModel

    model = MasterPlacementModel(instances, pools, rules, skip_power_coverage=True)
    model.build()

    # 模拟切平面（使用真实实例 ID）
    conflict = {
        instances[0]["instance_id"]: 0,
        instances[1]["instance_id"]: 0,
    }
    model.add_benders_cut(conflict)  # 不应抛异常


def test_ghost_rect_conflicts_with_mandatory_facility(project_root):
    """幽灵空地必须真实参与 set packing，否则目标矩形会和刚体重叠。"""
    import sys

    from ortools.sat.python import cp_model

    sys.path.insert(0, str(project_root))
    from src.models.master_model import MasterPlacementModel

    instances = [
        {
            "instance_id": "tiny_001",
            "facility_type": "tiny_facility",
            "is_mandatory": True,
            "bound_type": "exact",
        }
    ]
    pools = {
        "tiny_facility": [
            {
                "pose_id": "tiny_at_origin",
                "anchor": {"x": 0, "y": 0},
                "occupied_cells": [[0, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            }
        ]
    }
    rules = {
        "facility_templates": {
            "tiny_facility": {
                "dimensions": {"w": 1, "h": 1},
                "needs_power": False,
            }
        }
    }

    model = MasterPlacementModel(
        instances,
        pools,
        rules,
        ghost_rect=(70, 70),
        skip_power_coverage=True,
    )
    model.build()

    status = model.solve(time_limit_seconds=5.0)
    assert status == cp_model.INFEASIBLE


def test_port_clearance_rejects_blocked_front_cell(project_root):
    """端口前方缓冲格若被其他刚体占用，主模型就应直接判不可行。"""
    import sys

    from ortools.sat.python import cp_model

    sys.path.insert(0, str(project_root))
    from src.models.master_model import MasterPlacementModel

    instances = [
        {
            "instance_id": "src_001",
            "facility_type": "src",
            "operation_type": "src_op",
            "is_mandatory": True,
            "bound_type": "exact",
        },
        {
            "instance_id": "blk_001",
            "facility_type": "blk",
            "operation_type": "blk_op",
            "is_mandatory": True,
            "bound_type": "exact",
        },
    ]
    pools = {
        "src": [
            {
                "pose_id": "src_fixed",
                "anchor": {"x": 0, "y": 0},
                "occupied_cells": [[0, 0]],
                "input_port_cells": [],
                "output_port_cells": [{"x": 0, "y": 0, "dir": "E"}],
                "power_coverage_cells": None,
            }
        ],
        "blk": [
            {
                "pose_id": "blk_fixed",
                "anchor": {"x": 1, "y": 0},
                "occupied_cells": [[1, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            }
        ],
    }
    rules = {
        "facility_templates": {
            "src": {
                "dimensions": {"w": 1, "h": 1},
                "needs_power": False,
            },
            "blk": {
                "dimensions": {"w": 1, "h": 1},
                "needs_power": False,
            },
        }
    }

    model = MasterPlacementModel(
        instances,
        pools,
        rules,
        skip_power_coverage=True,
        enable_symmetry_breaking=False,
    )
    model.build()

    status = model.solve(time_limit_seconds=2.0)
    assert status == cp_model.INFEASIBLE


def test_power_coverage_implications_are_template_pose_level(project_root):
    """供电蕴含应按模板-位姿聚合，而不是对同模板每个实例重复展开。"""
    import sys

    sys.path.insert(0, str(project_root))
    from src.models.master_model import MasterPlacementModel

    instances = [
        {
            "instance_id": "fab_001",
            "facility_type": "fab",
            "is_mandatory": True,
            "bound_type": "exact",
        },
        {
            "instance_id": "fab_002",
            "facility_type": "fab",
            "is_mandatory": True,
            "bound_type": "exact",
        },
        {
            "instance_id": "pole_001",
            "facility_type": "power_pole",
            "is_mandatory": False,
            "bound_type": "exact",
        },
    ]
    pools = {
        "fab": [
            {
                "pose_id": "fab_left",
                "anchor": {"x": 0, "y": 0},
                "occupied_cells": [[0, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
            {
                "pose_id": "fab_right",
                "anchor": {"x": 2, "y": 0},
                "occupied_cells": [[2, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
        ],
        "power_pole": [
            {
                "pose_id": "pole_cover_all",
                "anchor": {"x": 1, "y": 0},
                "occupied_cells": [[1, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": [[0, 0], [2, 0]],
            }
        ],
    }
    rules = {
        "facility_templates": {
            "fab": {
                "dimensions": {"w": 1, "h": 1},
                "needs_power": True,
            },
            "power_pole": {
                "dimensions": {"w": 1, "h": 1},
                "needs_power": False,
            },
        }
    }

    model = MasterPlacementModel(instances, pools, rules)
    model.build()

    stats = model.build_stats["power_coverage"]
    assert stats["implications"] == 2
    assert stats["disabled_poses"] == 0


def test_grouped_encoding_canonicalizes_identical_clones(project_root):
    """Grouped encoding 应直接去掉同 operation clones 的排列对称性，并稳定还原实例解。"""
    import sys

    from ortools.sat.python import cp_model

    sys.path.insert(0, str(project_root))
    from src.models.master_model import MasterPlacementModel

    instances = [
        {
            "instance_id": "fab_001",
            "facility_type": "fab",
            "is_mandatory": True,
            "bound_type": "exact",
        },
        {
            "instance_id": "fab_002",
            "facility_type": "fab",
            "is_mandatory": True,
            "bound_type": "exact",
        },
    ]
    pools = {
        "fab": [
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
                "anchor": {"x": 2, "y": 0},
                "occupied_cells": [[2, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
        ]
    }
    rules = {
        "facility_templates": {
            "fab": {
                "dimensions": {"w": 1, "h": 1},
                "needs_power": False,
            }
        }
    }

    model = MasterPlacementModel(instances, pools, rules, skip_power_coverage=True)
    model.build()

    grouped = model.build_stats["grouped_encoding"]
    assert grouped["mandatory_instances"] == 2
    assert grouped["mandatory_groups"] == 1

    stats = model.build_stats["symmetry_breaking"]
    assert stats["index_link_terms"] == 0
    assert stats["order_constraints"] == 0

    status = model.solve(time_limit_seconds=5.0)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    solution = model.extract_solution()
    assert solution["fab_001"]["pose_id"] == "pose_a"
    assert solution["fab_002"]["pose_id"] == "pose_b"


def test_exact_mode_registers_search_strategy_and_stats(project_root):
    """Exact mode 应切到 fixed-search 路径，并记录分支统计。"""
    import sys

    from ortools.sat.python import cp_model

    sys.path.insert(0, str(project_root))
    from src.models.master_model import MasterPlacementModel

    instances = [
        {
            "instance_id": "tiny_001",
            "facility_type": "tiny_facility",
            "is_mandatory": True,
            "bound_type": "exact",
        }
    ]
    pools = {
        "tiny_facility": [
            {
                "pose_id": "left",
                "anchor": {"x": 0, "y": 0},
                "occupied_cells": [[0, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
            {
                "pose_id": "right",
                "anchor": {"x": 2, "y": 0},
                "occupied_cells": [[2, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
        ]
    }
    rules = {
        "facility_templates": {
            "tiny_facility": {
                "dimensions": {"w": 1, "h": 1},
                "needs_power": False,
            }
        }
    }

    model = MasterPlacementModel(
        instances,
        pools,
        rules,
        skip_power_coverage=True,
        exact_mode=True,
        enable_symmetry_breaking=False,
    )
    model.build()
    assert model._exact_search_strategy_added is False

    status = model.solve(time_limit_seconds=2.0)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert model._exact_search_strategy_added is True
    assert model.build_stats["last_solve"]["status"] in {"OPTIMAL", "FEASIBLE"}
    assert model.build_stats["last_solve"]["hinted_vars"] == 1
    assert model.build_stats["last_solve"]["effective_hinted_vars"] >= 1
    strategy_stats = model.build_stats["exact_search_strategy"]
    assert strategy_stats["guided_group_vars"] == 1
    assert strategy_stats["skipped_group_zero_vars"] == 1
    assert strategy_stats["skipped_zero_tail_vars"] == 1
    assert strategy_stats["search_branching"] == "PARTIAL_FIXED_SEARCH"
    assert strategy_stats["strategy_sequence"][0] == "preferred_ghost"


def test_greedy_hint_prefers_corner_ghost_and_canonical_group_assignment(project_root):
    """Greedy hint 应能给出稳定的 grouped mandatory 提示与 ghost 提示。"""
    import sys

    sys.path.insert(0, str(project_root))
    from src.models.master_model import MasterPlacementModel

    instances = [
        {
            "instance_id": "fab_001",
            "facility_type": "fab",
            "operation_type": "fab_op",
            "is_mandatory": True,
            "bound_type": "exact",
        },
        {
            "instance_id": "fab_002",
            "facility_type": "fab",
            "operation_type": "fab_op",
            "is_mandatory": True,
            "bound_type": "exact",
        },
    ]
    pools = {
        "fab": [
            {
                "pose_id": "left",
                "anchor": {"x": 0, "y": 0},
                "occupied_cells": [[0, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
            {
                "pose_id": "mid",
                "anchor": {"x": 1, "y": 0},
                "occupied_cells": [[1, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
            {
                "pose_id": "right",
                "anchor": {"x": 2, "y": 0},
                "occupied_cells": [[2, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
        ]
    }
    rules = {
        "facility_templates": {
            "fab": {
                "dimensions": {"w": 1, "h": 1},
                "needs_power": False,
            }
        }
    }

    model = MasterPlacementModel(
        instances,
        pools,
        rules,
        ghost_rect=(68, 70),
        skip_power_coverage=True,
        exact_mode=True,
        enable_symmetry_breaking=False,
    )
    model.build()

    hint = model.build_greedy_solution_hint()
    assert hint["__ghost__"] == 2
    assert hint["fab_001"] == 0
    assert hint["fab_002"] == 1
    assert model.build_stats["greedy_hint"]["hinted_instances"] == 2


def test_greedy_hint_adds_power_pole_without_blocking_port_front(project_root):
    """Greedy hint should add a power pole, but never by occupying a reserved port-front cell."""
    import sys

    sys.path.insert(0, str(project_root))
    from src.models.master_model import MasterPlacementModel

    instances = [
        {
            "instance_id": "fab_001",
            "facility_type": "fab",
            "operation_type": "fab_op",
            "is_mandatory": True,
            "bound_type": "exact",
        },
        {
            "instance_id": "pole_001",
            "facility_type": "power_pole",
            "operation_type": "power",
            "is_mandatory": False,
            "bound_type": "exact",
        },
    ]
    pools = {
        "fab": [
            {
                "pose_id": "fab_origin",
                "anchor": {"x": 0, "y": 0},
                "occupied_cells": [[0, 0]],
                "input_port_cells": [],
                "output_port_cells": [{"x": 0, "y": 0, "dir": "E"}],
                "power_coverage_cells": None,
            }
        ],
        "power_pole": [
            {
                "pose_id": "blocked_front",
                "anchor": {"x": 1, "y": 0},
                "occupied_cells": [[1, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": [[0, 0]],
            },
            {
                "pose_id": "clear_cover",
                "anchor": {"x": 2, "y": 0},
                "occupied_cells": [[2, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": [[0, 0]],
            },
        ],
    }
    rules = {
        "facility_templates": {
            "fab": {
                "dimensions": {"w": 1, "h": 1},
                "needs_power": True,
            },
            "power_pole": {
                "dimensions": {"w": 1, "h": 1},
                "needs_power": False,
            },
        }
    }

    model = MasterPlacementModel(
        instances,
        pools,
        rules,
        exact_mode=True,
        enable_symmetry_breaking=False,
    )
    model.build()

    hint = model.build_greedy_solution_hint()
    pole_hints = {
        key: value
        for key, value in hint.items()
        if str(key).startswith("power_pole_")
    }
    assert pole_hints == {"power_pole_hint_000": 1}
    assert model.build_stats["greedy_hint"]["hinted_power_poles"] == 1
    assert model.build_stats["greedy_hint"]["uncovered_power_cells"] == 0
    assert model.build_stats["greedy_hint"]["power_hint_status"] == "FEASIBLE"
    assert model.build_stats["greedy_hint"]["unreachable_power_cell"] is None


def test_greedy_hint_avoids_blocking_another_machine_front_cell(project_root):
    """Greedy mandatory placement should avoid poses that occupy another machine's front cell."""
    import sys

    sys.path.insert(0, str(project_root))
    from src.models.master_model import MasterPlacementModel

    instances = [
        {
            "instance_id": "src_001",
            "facility_type": "aaa_src",
            "operation_type": "src_op",
            "is_mandatory": True,
            "bound_type": "exact",
        },
        {
            "instance_id": "blk_001",
            "facility_type": "zzz_blk",
            "operation_type": "blk_op",
            "is_mandatory": True,
            "bound_type": "exact",
        },
    ]
    pools = {
        "aaa_src": [
            {
                "pose_id": "src_fixed",
                "anchor": {"x": 33, "y": 33},
                "occupied_cells": [[33, 33]],
                "input_port_cells": [],
                "output_port_cells": [{"x": 33, "y": 33, "dir": "E"}],
                "power_coverage_cells": None,
            }
        ],
        "zzz_blk": [
            {
                "pose_id": "blocked_centerish",
                "anchor": {"x": 34, "y": 33},
                "occupied_cells": [[34, 33]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
            {
                "pose_id": "safe_far",
                "anchor": {"x": 10, "y": 10},
                "occupied_cells": [[10, 10]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
        ],
    }
    rules = {
        "facility_templates": {
            "aaa_src": {
                "dimensions": {"w": 1, "h": 1},
                "needs_power": False,
            },
            "zzz_blk": {
                "dimensions": {"w": 1, "h": 1},
                "needs_power": False,
            },
        }
    }

    model = MasterPlacementModel(
        instances,
        pools,
        rules,
        skip_power_coverage=True,
        exact_mode=True,
        enable_symmetry_breaking=False,
    )
    model.build()

    hint = model.build_greedy_solution_hint()
    assert hint["src_001"] == 0
    assert hint["blk_001"] == 1


def test_greedy_hint_prefers_central_pose_for_non_boundary_templates(project_root):
    """Greedy hint should prefer a center-friendly pose instead of hugging the map border."""
    import sys

    sys.path.insert(0, str(project_root))
    from src.models.master_model import MasterPlacementModel

    instances = [
        {
            "instance_id": "fab_001",
            "facility_type": "fab",
            "operation_type": "fab_op",
            "is_mandatory": True,
            "bound_type": "exact",
        }
    ]
    pools = {
        "fab": [
            {
                "pose_id": "top_left",
                "anchor": {"x": 0, "y": 0},
                "occupied_cells": [[0, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
            {
                "pose_id": "centerish",
                "anchor": {"x": 34, "y": 34},
                "occupied_cells": [[34, 34]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
            {
                "pose_id": "bottom_right",
                "anchor": {"x": 69, "y": 69},
                "occupied_cells": [[69, 69]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
        ]
    }
    rules = {
        "facility_templates": {
            "fab": {
                "dimensions": {"w": 1, "h": 1},
                "needs_power": False,
            }
        }
    }

    model = MasterPlacementModel(
        instances,
        pools,
        rules,
        skip_power_coverage=True,
        exact_mode=True,
        enable_symmetry_breaking=False,
    )
    model.build()

    hint = model.build_greedy_solution_hint()
    assert hint["fab_001"] == 1


def test_greedy_hint_prefers_power_coverable_pose_for_powered_template(project_root):
    """Powered facilities should prefer poses that remain easier to cover by poles."""
    import sys

    sys.path.insert(0, str(project_root))
    from src.models.master_model import MasterPlacementModel

    instances = [
        {
            "instance_id": "fab_001",
            "facility_type": "fab",
            "operation_type": "fab_op",
            "is_mandatory": True,
            "bound_type": "exact",
        },
        {
            "instance_id": "pole_001",
            "facility_type": "power_pole",
            "operation_type": "power",
            "is_mandatory": False,
            "bound_type": "exact",
        },
    ]
    pools = {
        "fab": [
            {
                "pose_id": "center_but_uncovered",
                "anchor": {"x": 34, "y": 34},
                "occupied_cells": [[34, 34]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
            {
                "pose_id": "coverable_off_center",
                "anchor": {"x": 10, "y": 10},
                "occupied_cells": [[10, 10]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
        ],
        "power_pole": [
            {
                "pose_id": "covers_only_pose_b",
                "anchor": {"x": 9, "y": 10},
                "occupied_cells": [[9, 10]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": [[10, 10]],
            }
        ],
    }
    rules = {
        "facility_templates": {
            "fab": {
                "dimensions": {"w": 1, "h": 1},
                "needs_power": True,
            },
            "power_pole": {
                "dimensions": {"w": 1, "h": 1},
                "needs_power": False,
            },
        }
    }

    model = MasterPlacementModel(
        instances,
        pools,
        rules,
        exact_mode=True,
        enable_symmetry_breaking=False,
    )
    model.build()

    hint = model.build_greedy_solution_hint()
    assert hint["fab_001"] == 1


def test_power_hint_subproblem_reports_unreachable_cell(project_root):
    """The reduced pole-cover subproblem should explain which powered cell became impossible."""
    import sys

    sys.path.insert(0, str(project_root))
    from src.models.master_model import MasterPlacementModel

    instances = [
        {
            "instance_id": "pole_001",
            "facility_type": "power_pole",
            "operation_type": "power",
            "is_mandatory": False,
            "bound_type": "exact",
        }
    ]
    pools = {
        "power_pole": [
            {
                "pose_id": "pole_only_here",
                "anchor": {"x": 0, "y": 0},
                "occupied_cells": [[0, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": [[5, 5]],
            }
        ]
    }
    rules = {
        "facility_templates": {
            "power_pole": {
                "dimensions": {"w": 1, "h": 1},
                "needs_power": False,
            }
        }
    }

    model = MasterPlacementModel(
        instances,
        pools,
        rules,
        exact_mode=True,
        enable_symmetry_breaking=False,
    )

    result = model._solve_power_pole_hint_subproblem(
        occupied_cells={(0, 0)},
        reserved_front_cells=set(),
        powered_targets={(5, 5)},
        time_limit_seconds=1.0,
    )

    assert result["status"] == "UNREACHABLE"
    assert result["unreachable_cell"] == (5, 5)


def test_pose_level_optional_templates_respect_instance_caps(project_root):
    """Pose-level optional encoding must still obey the roster-level instance upper bound."""
    import sys

    from ortools.sat.python import cp_model

    sys.path.insert(0, str(project_root))
    from src.models.master_model import MasterPlacementModel

    instances = [
        {
            "instance_id": "protocol_box_001",
            "facility_type": "protocol_storage_box",
            "operation_type": "wireless_sink",
            "is_mandatory": False,
            "bound_type": "provisional",
        }
    ]
    pools = {
        "protocol_storage_box": [
            {
                "pose_id": "box_a",
                "anchor": {"x": 0, "y": 0},
                "occupied_cells": [[0, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
            {
                "pose_id": "box_b",
                "anchor": {"x": 2, "y": 0},
                "occupied_cells": [[2, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
        ]
    }
    rules = {
        "facility_templates": {
            "protocol_storage_box": {
                "dimensions": {"w": 1, "h": 1},
                "needs_power": False,
            }
        }
    }

    model = MasterPlacementModel(
        instances,
        pools,
        rules,
        skip_power_coverage=True,
        enable_symmetry_breaking=False,
    )
    model.build()

    status = model.solve(time_limit_seconds=2.0)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    solution = model.extract_solution()
    assert len(solution) <= 1


def test_repeated_solve_clears_stale_solution_hints(project_root):
    """Repeated solve() calls should not accumulate duplicate hints into MODEL_INVALID."""
    import sys

    from ortools.sat.python import cp_model

    sys.path.insert(0, str(project_root))
    from src.models.master_model import MasterPlacementModel

    instances = [
        {
            "instance_id": "fab_001",
            "facility_type": "fab",
            "operation_type": "fab_op",
            "is_mandatory": True,
            "bound_type": "exact",
        },
        {
            "instance_id": "fab_002",
            "facility_type": "fab",
            "operation_type": "fab_op",
            "is_mandatory": True,
            "bound_type": "exact",
        },
    ]
    pools = {
        "fab": [
            {
                "pose_id": "left",
                "anchor": {"x": 0, "y": 0},
                "occupied_cells": [[0, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
            {
                "pose_id": "mid",
                "anchor": {"x": 1, "y": 0},
                "occupied_cells": [[1, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
            {
                "pose_id": "right",
                "anchor": {"x": 2, "y": 0},
                "occupied_cells": [[2, 0]],
                "input_port_cells": [],
                "output_port_cells": [],
                "power_coverage_cells": None,
            },
        ]
    }
    rules = {
        "facility_templates": {
            "fab": {
                "dimensions": {"w": 1, "h": 1},
                "needs_power": False,
            }
        }
    }

    model = MasterPlacementModel(
        instances,
        pools,
        rules,
        skip_power_coverage=True,
        exact_mode=True,
        enable_symmetry_breaking=False,
    )
    model.build()
    hint = {"fab_001": 0, "fab_002": 1}

    first = model.solve(time_limit_seconds=2.0, solution_hint=hint)
    second = model.solve(time_limit_seconds=2.0, solution_hint=hint)

    assert first in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert second in (cp_model.OPTIMAL, cp_model.FEASIBLE)
