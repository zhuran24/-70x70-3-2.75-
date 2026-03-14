"""
全局回归测试套件 (Regression Test Suite)
Status: ACCEPTED_DRAFT

目标：运行最小闭环，验证从数据预处理到蓝图导出的完整流水线。
"""

import json
import pytest
from pathlib import Path


@pytest.fixture(scope="session")
def project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


# ============================================================================
# 数据完整性回归
# ============================================================================

def test_preprocessed_data_exists(project_root):
    """所有预处理数据文件必须存在。"""
    expected = [
        "commodity_demands.json",
        "machine_counts.json",
        "port_budget.json",
        "all_facility_instances.json",
        "candidate_placements.json",
    ]
    data_dir = project_root / "data" / "preprocessed"
    for fname in expected:
        path = data_dir / fname
        assert path.exists(), f"缺失: {fname}"
        assert path.stat().st_size > 0, f"空文件: {fname}"


def test_frozen_truth_consistency(project_root):
    """Frozen truth 常量必须保持一致。"""
    data_dir = project_root / "data" / "preprocessed"

    counts = json.load(open(data_dir / "machine_counts.json", encoding="utf-8"))
    assert sum(counts.values()) == 219

    instances = json.load(open(data_dir / "all_facility_instances.json", encoding="utf-8"))
    assert len(instances) == 326

    mandatory = sum(1 for i in instances if i["is_mandatory"])
    assert mandatory == 266

    pools = json.load(open(data_dir / "candidate_placements.json", encoding="utf-8"))
    total_poses = sum(len(v) for v in pools["facility_pools"].values())
    assert total_poses == 81795


def test_canonical_rules_intact(project_root):
    """canonical_rules.json 必须包含 7 个模板。"""
    with open(project_root / "rules" / "canonical_rules.json", encoding="utf-8") as f:
        rules = json.load(f)
    assert len(rules["facility_templates"]) == 7


# ============================================================================
# 模块导入回归
# ============================================================================

def test_all_modules_importable(project_root):
    """所有核心模块必须可以无错导入。"""
    import sys
    sys.path.insert(0, str(project_root))

    from src.preprocess import demand_solver
    from src.preprocess import instance_builder
    from src.placement import placement_generator
    from src.placement import occupancy_masks
    from src.placement import symmetry_breaking
    from src.models import master_model
    from src.models import flow_subproblem
    from src.models import cut_manager
    from src.models import routing_subproblem
    from src.search import benders_loop
    from src.search import outer_search
    from src.render import blueprint_exporter


def test_blueprint_export_smoke(project_root):
    """蓝图导出器应能从模拟数据正确导出 JSON。"""
    import sys
    sys.path.insert(0, str(project_root))
    from src.render.blueprint_exporter import export_blueprint

    # 极简模拟数据
    mock_solution = {
        "test_inst_001": {
            "pose_idx": 0,
            "pose_id": "p_x00_y00_o0_m_TB",
            "anchor": {"x": 0, "y": 0},
            "facility_type": "manufacturing_3x3",
        }
    }

    pools = json.load(
        open(project_root / "data" / "preprocessed" / "candidate_placements.json",
             encoding="utf-8")
    )

    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        output_path = Path(f.name)

    try:
        bp = export_blueprint(
            placement_solution=mock_solution,
            routing_solution=None,
            ghost_rect={"w": 5, "h": 5, "area": 25},
            solve_time=1.0,
            benders_iterations=1,
            facility_pools=pools["facility_pools"],
            output_path=output_path,
        )

        assert "metadata" in bp
        assert "facilities" in bp
        assert len(bp["facilities"]) == 1
        assert bp["objective_achieved"]["empty_rect"]["w"] == 5
    finally:
        output_path.unlink(missing_ok=True)


def test_default_candidate_search_is_exhaustive(project_root):
    """默认候选生成应覆盖全部 min_side>=6 的尺寸，不再偷偷做启发式裁剪。"""
    import sys

    sys.path.insert(0, str(project_root))
    from src.search.outer_search import generate_candidate_sizes

    candidates = generate_candidate_sizes()
    assert len(candidates) == 2145
    assert all(min(w, h) >= 6 for _, w, h in candidates)
    assert candidates[0] == (4900, 70, 70)


def test_certification_blockers_only_report_actual_static_schema_gaps(project_root):
    """exact 认证前置检查不应再拿已落地的绑定层缺口做静态拦截。"""
    import sys

    sys.path.insert(0, str(project_root))
    from src.search.benders_loop import collect_certification_blockers

    blockers = collect_certification_blockers([
        {
            "instance_id": "mandatory_001",
            "bound_type": "exact",
            "is_mandatory": True,
            "facility_type": "manufacturing_3x3",
            "operation_type": "parts_maker",
        },
        {
            "instance_id": "power_pole_001",
            "bound_type": "provisional",
            "is_mandatory": False,
            "facility_type": "power_pole",
            "operation_type": "power_supply",
        },
    ])
    assert blockers == []


def test_truncated_outer_search_is_not_reported_infeasible(project_root, monkeypatch):
    """如果外层搜索被人为截断，就不能把结果包装成全局无解。"""
    import sys

    sys.path.insert(0, str(project_root))
    from src.models.cut_manager import RUN_STATUS_INFEASIBLE, RUN_STATUS_UNKNOWN
    from src.search import benders_loop
    from src.search.outer_search import run_outer_search

    def fake_run_benders_for_ghost_rect(**kwargs):
        return RUN_STATUS_INFEASIBLE, None

    monkeypatch.setattr(
        benders_loop,
        "run_benders_for_ghost_rect",
        fake_run_benders_for_ghost_rect,
    )

    status, result = run_outer_search(
        start_area=49,
        max_attempts=1,
        project_root=project_root,
        certification_mode=True,
    )

    assert status == RUN_STATUS_UNKNOWN
    assert result is None


def test_certification_outer_search_uses_exact_area_upper_bound(project_root, monkeypatch):
    """exact 模式应先用冻结下界裁掉不可能的大空地，再进入逐候选搜索。"""
    import sys

    sys.path.insert(0, str(project_root))
    from src.models.cut_manager import RUN_STATUS_UNKNOWN
    from src.models.master_model import load_project_data
    from src.search import benders_loop
    from src.search.benders_loop import compute_mandatory_area_lower_bound
    from src.search.outer_search import generate_candidate_sizes, run_outer_search

    instances, _, rules = load_project_data(project_root)
    grid = rules["globals"]["grid"]
    exact_area_upper_bound = (
        int(grid["width"]) * int(grid["height"])
        - compute_mandatory_area_lower_bound(instances, rules)
    )
    expected_first_area, expected_w, expected_h = generate_candidate_sizes(
        min_side=6,
        area_upper_bound=exact_area_upper_bound,
    )[0]

    seen = {}

    def fake_run_benders_for_ghost_rect(**kwargs):
        seen["ghost_w"] = kwargs["ghost_w"]
        seen["ghost_h"] = kwargs["ghost_h"]
        return RUN_STATUS_UNKNOWN, None

    monkeypatch.setattr(
        benders_loop,
        "run_benders_for_ghost_rect",
        fake_run_benders_for_ghost_rect,
    )

    status, result = run_outer_search(
        max_attempts=1,
        master_time_limit=1.0,
        benders_max_iter=1,
        project_root=project_root,
        certification_mode=True,
    )

    assert status == RUN_STATUS_UNKNOWN
    assert result is None
    assert seen == {"ghost_w": expected_w, "ghost_h": expected_h}
    assert expected_first_area == exact_area_upper_bound


def test_exact_area_lower_bound_precheck_short_circuits_impossible_ghost(project_root):
    """mandatory 占地下界应能在建主模型前精确排掉明显不可能的大空地。"""
    import sys

    sys.path.insert(0, str(project_root))
    from src.models.cut_manager import RUN_STATUS_INFEASIBLE
    from src.models.master_model import load_project_data
    from src.search.benders_loop import (
        compute_mandatory_area_lower_bound,
        run_benders_for_ghost_rect,
    )

    instances, _, rules = load_project_data(project_root)
    assert compute_mandatory_area_lower_bound(instances, rules) == 3640

    status, result = run_benders_for_ghost_rect(
        ghost_w=70,
        ghost_h=70,
        max_iterations=1,
        master_time_limit=1.0,
        project_root=project_root,
        certification_mode=True,
    )

    assert status == RUN_STATUS_INFEASIBLE
    assert result is None
