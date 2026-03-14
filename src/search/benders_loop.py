"""
Benders 分解顶层循环 (Top-Level Benders Loop)
对应规格书：10_benders_decomposition_and_cut_design §10.2
Status: ACCEPTED_DRAFT

目标：整合 master_model (07), flow_subproblem (08), routing_subproblem (09),
cut_manager (10) 为完整的 LBBD 闭环。供 outer_search 对每个 (w,h) 调用。

重要：此模块是对 cut_manager.py 中 LBBDController 的精简封装，
提供给外层搜索引擎的简洁单次调用接口。
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

from src.models.master_model import (
    MasterPlacementModel,
    POSE_LEVEL_OPTIONAL_TEMPLATES,
    load_project_data,
)
from src.preprocess.operation_profiles import find_unprofiled_operations
from src.models.cut_manager import (
    CutManager,
    LBBDController,
    RUN_STATUS_CERTIFIED,
    RUN_STATUS_INFEASIBLE,
    RUN_STATUS_UNKNOWN,
    RUN_STATUS_UNPROVEN,
)


def collect_certification_blockers(instances: List[Dict[str, Any]]) -> List[str]:
    """收集 exact 认证前置阻塞项。"""
    blockers: List[str] = []
    missing_operation_profiles = find_unprofiled_operations(instances)
    if missing_operation_profiles:
        blockers.append(
            "存在未固化 exact operation port profile 的 operation_type："
            + ", ".join(missing_operation_profiles)
        )
    unsupported_optional_templates = sorted({
        inst.get("facility_type", "<missing_facility_type>")
        for inst in instances
        if not inst.get("is_mandatory")
        and inst.get("facility_type") not in POSE_LEVEL_OPTIONAL_TEMPLATES
    })
    if unsupported_optional_templates:
        blockers.append(
            "存在未纳入 pose-level exact 建模的可选设施模板："
            + ", ".join(unsupported_optional_templates)
        )
    return blockers


def compute_mandatory_area_lower_bound(
    instances: List[Dict[str, Any]],
    rules: Dict[str, Any],
) -> int:
    """Exact lower bound for occupied area before any routing is considered."""
    templates = rules["facility_templates"]
    total = 0
    total_powered_cells = 0
    for inst in instances:
        if not inst.get("is_mandatory"):
            continue
        tpl = inst["facility_type"]
        dims = templates[tpl]["dimensions"]
        area = int(dims["w"]) * int(dims["h"])
        total += area
        if templates[tpl].get("needs_power", False):
            total_powered_cells += area

    pole_tpl = templates.get("power_pole")
    if pole_tpl and total_powered_cells > 0:
        max_coverage = 144  # 12x12
        min_poles = -(-total_powered_cells // max_coverage)
        pole_dims = pole_tpl["dimensions"]
        pole_area = int(pole_dims["w"]) * int(pole_dims["h"])
        total += min_poles * pole_area
    return total


def run_benders_for_ghost_rect(
    ghost_w: int,
    ghost_h: int,
    max_iterations: int = 50,
    master_time_limit: float = 120.0,
    project_root: Optional[Path] = None,
    certification_mode: bool = True,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """对给定空地尺寸 (w, h) 执行完整 LBBD 循环。

    Args:
        ghost_w, ghost_h: 幽灵空地尺寸
        max_iterations: 最大 Benders 迭代次数
        master_time_limit: 每轮主问题求解时限 (秒)
        project_root: 项目根目录

    Returns:
        (status, solution_dict)
        status ∈ {CERTIFIED, INFEASIBLE, UNKNOWN, UNPROVEN}
    """
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent.parent

    print(f"\n{'='*60}")
    print(f"🎯 [Benders] 空地目标: {ghost_w}×{ghost_h}")
    print(f"{'='*60}")

    instances, pools, rules = load_project_data(project_root)

    if certification_mode:
        blockers = collect_certification_blockers(instances)
        if blockers:
            print("⚠️ [Exactness] 当前输入尚不满足 exact 认证前提：")
            for blocker in blockers:
                print(f"   - {blocker}")
            return RUN_STATUS_UNPROVEN, None

    grid = rules["globals"]["grid"]
    grid_area = int(grid["width"]) * int(grid["height"])
    mandatory_area_lb = compute_mandatory_area_lower_bound(instances, rules)
    ghost_area = ghost_w * ghost_h
    if mandatory_area_lb + ghost_area > grid_area:
        print(
            "❌ [Exact Precheck] mandatory 占地面积下界 + 幽灵空地面积超出全图面积："
            f"{mandatory_area_lb} + {ghost_area} > {grid_area}"
        )
        return RUN_STATUS_INFEASIBLE, None

    # 构建主模型（含幽灵空地）
    master = MasterPlacementModel(
        instances, pools, rules,
        ghost_rect=(ghost_w, ghost_h),
        enable_symmetry_breaking=not certification_mode,
        exact_mode=certification_mode,
    )
    master.build()

    # 加载历史切平面（如果有）
    cm = CutManager()
    cuts_path = project_root / "data" / "solutions" / f"cuts_{ghost_w}x{ghost_h}.json"
    cm.load(cuts_path)

    # 注入历史切平面到模型
    for cut in cm.cuts:
        master.add_benders_cut(cut.conflict_set)

    # 执行 LBBD 循环
    controller = LBBDController(
        master, cm,
        max_iterations=max_iterations,
        master_time_limit=master_time_limit,
        exact_mode=certification_mode,
    )
    status, solution = controller.run_with_status()

    # 持久化切平面
    cuts_path.parent.mkdir(parents=True, exist_ok=True)
    cm.save(cuts_path)

    if status == RUN_STATUS_CERTIFIED and solution:
        return RUN_STATUS_CERTIFIED, solution
    if status in (RUN_STATUS_UNKNOWN, RUN_STATUS_UNPROVEN):
        return status, None
    return RUN_STATUS_INFEASIBLE, None
