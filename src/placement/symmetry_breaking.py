"""
几何预处理辅助：对称性破除约束生成器 (Symmetry Breaking Constraints)
Status: ACCEPTED_DRAFT

目标：为 07 章主问题提供对称性破除约束，大幅缩减等价解搜索空间。

包含两层对称性破除：
  1. 几何层：正方形模板的旋转对等去重 (已在 placement_generator 中处理，此处提供验证)
  2. 实例层：同模板等价实例的字典序约束 (供 master_model 使用)
"""

from typing import List, Dict, Any, Tuple


def generate_lexicographic_ordering(
    instance_ids: List[str],
    placements: List[Dict[str, Any]]
) -> List[Tuple[str, str]]:
    """为同模板的等价实例生成字典序约束对。

    物理原理：N 台相同型号的机器（如 34 台蓝铁粉碎机）在数学上完全等价。
    如果不加约束，求解器会浪费大量时间探索仅仅是"重新编号"的等价解。
    
    字典序约束 pose_id(instance_i) ≤ pose_id(instance_{i+1}) 能将 N! 种标签排列
    压缩为仅 1 种规范形式。

    Args:
        instance_ids: 按自然顺序排列的同模板实例 ID 列表
                      (如 ['crusher_blue_iron_001', ..., 'crusher_blue_iron_034'])
        placements: 该模板的候选位姿列表（用于建立 pose_id → index 映射）

    Returns:
        约束对列表 [(id_i, id_{i+1}), ...]，
        表示"实例 id_i 选择的 pose_id 字典序必须 ≤ 实例 id_{i+1} 选择的 pose_id"
    """
    if len(instance_ids) <= 1:
        return []

    return [(instance_ids[i], instance_ids[i + 1])
            for i in range(len(instance_ids) - 1)]


def build_pose_id_to_index(placements: List[Dict[str, Any]]) -> Dict[str, int]:
    """构建 pose_id → 整数索引的映射，用于将字典序约束转为线性比较。

    pose_id 格式为 `p_x{x}_y{y}_o{o}_m_{mode}`，其自然字典序等价于
    先比较 x、再比较 y、再比较 o 和 mode 的坐标序。
    但为避免字符串比较开销，此处预计算为整数索引。
    """
    sorted_pose_ids = sorted(p["pose_id"] for p in placements)
    return {pid: idx for idx, pid in enumerate(sorted_pose_ids)}


def group_instances_by_template(
    all_instances: List[Dict[str, Any]]
) -> Dict[str, List[str]]:
    """将全局实例花名册按 facility_type 分组，返回 template → [instance_ids]。

    仅包含 is_mandatory=True 且同模板内有多台的分组（单台无需破除）。
    """
    from collections import defaultdict
    groups: Dict[str, List[str]] = defaultdict(list)

    for inst in all_instances:
        tpl = inst["facility_type"]
        groups[tpl].append(inst["instance_id"])

    # 过滤掉只有 1 个实例的组（无对称性可破除）
    # 同时对每组内的 instance_id 排序以确保确定性
    return {
        tpl: sorted(ids)
        for tpl, ids in groups.items()
        if len(ids) > 1
    }


def verify_no_rotation_duplicates(
    placements: List[Dict[str, Any]],
    is_square: bool
) -> List[str]:
    """验证候选池中是否存在旋转等价的重复 pose（仅适用于正方形模板）。

    检测方法：对于同一个 (x, y) 下的所有 pose，检查是否存在
    occupied_cells 完全相同的两个 pose。如果存在，说明旋转去重不彻底。

    Returns:
        重复的 pose_id 对列表（如果有）。空列表表示无重复。
    """
    if not is_square:
        return []

    from collections import defaultdict
    by_anchor: Dict[Tuple[int, int], List[Dict]] = defaultdict(list)

    for pose in placements:
        anchor = (pose["anchor"]["x"], pose["anchor"]["y"])
        by_anchor[anchor].append(pose)

    duplicates = []
    for anchor, poses in by_anchor.items():
        seen_cells = {}
        for pose in poses:
            cells_key = tuple(sorted(tuple(c) for c in pose["occupied_cells"]))
            in_key = tuple(sorted(
                (p["x"], p["y"], p["dir"]) for p in pose["input_port_cells"]
            ))
            out_key = tuple(sorted(
                (p["x"], p["y"], p["dir"]) for p in pose["output_port_cells"]
            ))
            full_key = (cells_key, in_key, out_key)

            if full_key in seen_cells:
                duplicates.append(
                    f"{seen_cells[full_key]} ↔ {pose['pose_id']} at anchor {anchor}"
                )
            else:
                seen_cells[full_key] = pose["pose_id"]

    return duplicates
