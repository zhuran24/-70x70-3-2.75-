"""
几何预处理辅助：占格掩码索引构建器 (Occupancy Mask Index Builder)
Status: ACCEPTED_DRAFT

目标：将 candidate_placements.json 的 occupied_cells 转换为可复用的反向索引，
供 07 章主问题的不重叠约束 (∑ z_{i,p} ≤ 1) 使用。

关键接口：
  - cell_to_1d(x, y): 将 (x, y) 转为 1D 索引 y * 70 + x
  - build_cell_to_poses_index(pools): 构建 cell → List[(template, pose_idx)] 反向索引
  - build_occupancy_matrix(pools): 构建稀疏占格矩阵供 ILP 使用
"""

from typing import Dict, List, Tuple, Any
from collections import defaultdict

GRID_W = 70
GRID_H = 70
TOTAL_CELLS = GRID_W * GRID_H  # 4900


def cell_to_1d(x: int, y: int) -> int:
    """将 2D 网格坐标转为 1D 线性索引。
    编码方式：row-major，index = y * GRID_W + x。
    范围：[0, 4899]。
    """
    assert 0 <= x < GRID_W and 0 <= y < GRID_H, f"坐标越界: ({x}, {y})"
    return y * GRID_W + x


def cell_from_1d(idx: int) -> Tuple[int, int]:
    """将 1D 线性索引还原为 2D 坐标。"""
    assert 0 <= idx < TOTAL_CELLS, f"索引越界: {idx}"
    return idx % GRID_W, idx // GRID_W


def pose_cells_to_mask(occupied_cells: List[List[int]]) -> frozenset:
    """将一个 pose 的 occupied_cells 转为 1D 索引的 frozenset。
    用于高效的交集检测（判断两个 pose 是否重叠）。
    """
    return frozenset(cell_to_1d(c[0], c[1]) for c in occupied_cells)


def build_cell_to_poses_index(
    facility_pools: Dict[str, List[Dict[str, Any]]]
) -> Dict[int, List[Tuple[str, int]]]:
    """构建反向索引：cell_1d → List[(template_key, pose_index)]。

    对于 07 章主问题的不重叠约束：
    对每个 cell c，约束为 ∑_{(t,p) ∈ cell_to_poses[c]} z_{t,p} ≤ 1
    其中 z_{t,p} 是模板 t 的位姿 p 是否被激活的 0-1 变量。

    注意：同模板的不同实例共享同一个候选池，实例间的互斥
    由 07 章的"每实例单选"约束处理，此处不需要区分实例。
    """
    index: Dict[int, List[Tuple[str, int]]] = defaultdict(list)

    for tpl_key, placements in facility_pools.items():
        for pose_idx, pose in enumerate(placements):
            for cell in pose["occupied_cells"]:
                cell_1d = cell_to_1d(cell[0], cell[1])
                index[cell_1d].append((tpl_key, pose_idx))

    return dict(index)


def build_power_coverage_index(
    facility_pools: Dict[str, List[Dict[str, Any]]]
) -> Dict[int, List[int]]:
    """构建供电覆盖反向索引：cell_1d → List[power_pole_pose_index]。

    对于 07 章的供电蕴含约束：
    若制造单位 i 选择了位姿 p（需要供电），则 p 的占格集合中的每个 cell
    必须至少被一个激活的供电桩位姿覆盖。
    """
    index: Dict[int, List[int]] = defaultdict(list)

    if "power_pole" not in facility_pools:
        return dict(index)

    for pose_idx, pose in enumerate(facility_pools["power_pole"]):
        cov = pose.get("power_coverage_cells")
        if cov:
            for cell in cov:
                cell_1d = cell_to_1d(cell[0], cell[1])
                index[cell_1d].append(pose_idx)

    return dict(index)


def get_pool_stats(facility_pools: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """返回各模板池的统计摘要（用于审计与测试）。"""
    stats = {}
    total_poses = 0
    total_cells_covered = set()

    for tpl_key, placements in facility_pools.items():
        tpl_cells = set()
        for pose in placements:
            for cell in pose["occupied_cells"]:
                tpl_cells.add(cell_to_1d(cell[0], cell[1]))
                total_cells_covered.add(cell_to_1d(cell[0], cell[1]))

        stats[tpl_key] = {
            "num_poses": len(placements),
            "unique_cells_touched": len(tpl_cells),
        }
        total_poses += len(placements)

    stats["_summary"] = {
        "total_poses": total_poses,
        "total_unique_cells_touched": len(total_cells_covered),
        "grid_coverage_pct": round(len(total_cells_covered) / TOTAL_CELLS * 100, 2),
    }
    return stats
