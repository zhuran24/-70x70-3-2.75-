"""
Tests for Group 3 Geometry Layer: Candidate Placement Enumeration & Supporting Modules.
Status: ACCEPTED_DRAFT

验证几何降维引擎的正确性，包括：
  - Pool key 与 canonical_rules.json 对齐
  - 占格数量与模板尺寸一致
  - 无越界坐标
  - 面壁死锁已剔除
  - 边界口锚定规则
  - 供电桩覆盖域截断
  - 协议箱无端口
  - 正方形无旋转重复
  - 占格掩码索引一致性
  - 对称性破除约束生成
"""

import json
import math
import pytest
from pathlib import Path
from typing import Dict, List, Any

# ============================================================================
# 夹具 (Fixtures)
# ============================================================================

@pytest.fixture(scope="session")
def project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="session")
def canonical_templates(project_root) -> Dict[str, Any]:
    with open(project_root / "rules" / "canonical_rules.json", "r", encoding="utf-8") as f:
        return json.load(f)["facility_templates"]


@pytest.fixture(scope="session")
def facility_pools(project_root):
    """从已生成的 candidate_placements.json 加载，避免重复计算。"""
    path = project_root / "data" / "preprocessed" / "candidate_placements.json"
    if not path.exists():
        pytest.skip("candidate_placements.json 尚未生成，请先运行 placement_generator.py")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["facility_pools"]


@pytest.fixture(scope="session")
def all_instances(project_root):
    path = project_root / "data" / "preprocessed" / "all_facility_instances.json"
    if not path.exists():
        pytest.skip("all_facility_instances.json 尚未生成")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================================
# 核心测试：Pool 对齐
# ============================================================================

def test_pool_keys_match_canonical(facility_pools, canonical_templates):
    """Pool key 必须与 canonical_rules.json 的 template key 一一对应。"""
    pool_keys = set(facility_pools.keys())
    template_keys = set(canonical_templates.keys())
    assert pool_keys == template_keys, (
        f"Pool key 不匹配！\n"
        f"  多出: {pool_keys - template_keys}\n"
        f"  缺少: {template_keys - pool_keys}"
    )


def test_all_pools_nonempty(facility_pools):
    """每个模板池必须至少有 1 个合法位姿。"""
    for tpl_key, placements in facility_pools.items():
        assert len(placements) > 0, f"模板 {tpl_key} 的候选池为空"


# ============================================================================
# 核心测试：占格正确性
# ============================================================================

def test_occupied_cells_count(facility_pools, canonical_templates):
    """每个 pose 的 occupied_cells 数量必须等于模板的 w × h。"""
    for tpl_key, placements in facility_pools.items():
        dims = canonical_templates[tpl_key]["dimensions"]
        expected_area = dims["w"] * dims["h"]

        for pose in placements[:50]:  # 抽样检查前 50 个
            actual = len(pose["occupied_cells"])
            assert actual == expected_area, (
                f"{tpl_key}/{pose['pose_id']}: 占格数 {actual} != 预期 {expected_area}"
            )


def test_no_out_of_bounds_cells(facility_pools):
    """所有 occupied_cells 坐标必须在 [0, 69] 范围内。"""
    for tpl_key, placements in facility_pools.items():
        for pose in placements:
            for cell in pose["occupied_cells"]:
                x, y = cell[0], cell[1]
                assert 0 <= x <= 69 and 0 <= y <= 69, (
                    f"{tpl_key}/{pose['pose_id']}: 占格越界 ({x}, {y})"
                )


def test_no_out_of_bounds_ports(facility_pools):
    """所有端口的接管格坐标必须在 [0, 69] 范围内（已经是相邻格）。"""
    for tpl_key, placements in facility_pools.items():
        for pose in placements:
            for port in pose["input_port_cells"] + pose["output_port_cells"]:
                x, y = port["x"], port["y"]
                assert 0 <= x <= 69 and 0 <= y <= 69, (
                    f"{tpl_key}/{pose['pose_id']}: 端口越界 ({x}, {y}, dir={port['dir']})"
                )


# ============================================================================
# 核心测试：面壁死锁剔除
# ============================================================================

def test_wall_facing_pruned(facility_pools):
    """不应存在输入或输出端口全部朝墙外的 pose（面壁死锁 §6.5.1）。
    检测方法：如果一个 pose 有端口，则至少有一个端口的接管格在地图内。
    """
    for tpl_key, placements in facility_pools.items():
        for pose in placements:
            for port_type in ["input_port_cells", "output_port_cells"]:
                ports = pose[port_type]
                if not ports:
                    continue  # 无端口的模板（如供电桩、协议箱）跳过

                all_blocked = all(
                    p["x"] < 0 or p["x"] >= 70 or p["y"] < 0 or p["y"] >= 70
                    for p in ports
                )
                assert not all_blocked, (
                    f"{tpl_key}/{pose['pose_id']}: {port_type} 全部朝墙外（面壁死锁未剔除）"
                )


# ============================================================================
# 核心测试：边界口锚定
# ============================================================================

def test_boundary_port_anchoring(facility_pools):
    """边界口只应出现在 x=0 (左基线) 或 y=0 (下基线)。"""
    if "boundary_storage_port" not in facility_pools:
        pytest.skip("无 boundary_storage_port 池")

    for pose in facility_pools["boundary_storage_port"]:
        ax = pose["anchor"]["x"]
        ay = pose["anchor"]["y"]
        assert ax == 0 or ay == 0, (
            f"边界口 {pose['pose_id']} 锚点 ({ax}, {ay}) 不在基线上"
        )


def test_boundary_port_no_corner_overlap(facility_pools):
    """边界口不应出现在 (0, 0) 拐角处（§6.4.3 起点从 1 开始）。"""
    if "boundary_storage_port" not in facility_pools:
        pytest.skip("无 boundary_storage_port 池")

    for pose in facility_pools["boundary_storage_port"]:
        ax = pose["anchor"]["x"]
        ay = pose["anchor"]["y"]
        assert not (ax == 0 and ay == 0), (
            f"边界口 {pose['pose_id']} 出现在 (0, 0) 拐角"
        )


# ============================================================================
# 核心测试：供电桩覆盖域截断
# ============================================================================

def test_power_pole_coverage_clipped(facility_pools):
    """供电桩的覆盖域不应超出 [0, 69]。"""
    if "power_pole" not in facility_pools:
        pytest.skip("无 power_pole 池")

    for pose in facility_pools["power_pole"]:
        cov = pose.get("power_coverage_cells")
        if cov is None:
            continue
        for cell in cov:
            x, y = cell[0], cell[1]
            assert 0 <= x <= 69 and 0 <= y <= 69, (
                f"供电桩 {pose['pose_id']}: 覆盖域越界 ({x}, {y})"
            )


def test_power_pole_coverage_size(facility_pools):
    """供电桩覆盖域最大为 12×12=144 格（中心位置），边缘处应更小。"""
    if "power_pole" not in facility_pools:
        pytest.skip("无 power_pole 池")

    for pose in facility_pools["power_pole"]:
        cov = pose.get("power_coverage_cells")
        if cov is None:
            continue
        assert 0 < len(cov) <= 144, (
            f"供电桩 {pose['pose_id']}: 覆盖域大小 {len(cov)} 异常"
        )


# ============================================================================
# 核心测试：协议箱端口几何
# ============================================================================

def test_protocol_box_has_square_side_ports(facility_pools):
    """协议箱虽然支持无线清仓，但仍应保留 3 入 3 出的方形边端口。"""
    if "protocol_storage_box" not in facility_pools:
        pytest.skip("无 protocol_storage_box 池")

    for pose in facility_pools["protocol_storage_box"]:
        assert len(pose["input_port_cells"]) == 3, (
            f"协议箱 {pose['pose_id']} 应有 3 个输入端口"
        )
        assert len(pose["output_port_cells"]) == 3, (
            f"协议箱 {pose['pose_id']} 应有 3 个输出端口"
        )


# ============================================================================
# 核心测试：正方形旋转去重
# ============================================================================

def test_square_no_duplicate_rotations(facility_pools, canonical_templates):
    """3x3 和 5x5 正方形模板不应有同 (x,y) 下占格+端口完全相同的重复 pose。"""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from src.placement.symmetry_breaking import verify_no_rotation_duplicates

    for tpl_key in ["manufacturing_3x3", "manufacturing_5x5"]:
        if tpl_key not in facility_pools:
            continue
        dims = canonical_templates[tpl_key]["dimensions"]
        is_sq = dims["w"] == dims["h"]
        dups = verify_no_rotation_duplicates(facility_pools[tpl_key], is_sq)
        assert len(dups) == 0, f"{tpl_key} 存在旋转重复: {dups[:5]}"


# ============================================================================
# 核心测试：占格掩码索引
# ============================================================================

def test_cell_to_1d_roundtrip():
    """cell_to_1d 和 cell_from_1d 必须互逆。"""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from src.placement.occupancy_masks import cell_to_1d, cell_from_1d

    for x in [0, 35, 69]:
        for y in [0, 35, 69]:
            idx = cell_to_1d(x, y)
            rx, ry = cell_from_1d(idx)
            assert (rx, ry) == (x, y), f"Round-trip 失败: ({x},{y}) → {idx} → ({rx},{ry})"


def test_occupancy_index_consistency(facility_pools):
    """反向索引的每个 (template, pose_idx) 引用必须有效。"""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from src.placement.occupancy_masks import build_cell_to_poses_index

    index = build_cell_to_poses_index(facility_pools)

    for cell_1d, entries in index.items():
        assert 0 <= cell_1d < 4900, f"索引越界: {cell_1d}"
        for tpl_key, pose_idx in entries:
            assert tpl_key in facility_pools, f"未知模板: {tpl_key}"
            assert 0 <= pose_idx < len(facility_pools[tpl_key]), (
                f"pose 索引越界: {tpl_key}[{pose_idx}]"
            )


# ============================================================================
# 核心测试：对称性破除约束
# ============================================================================

def test_lexicographic_ordering_pairs(all_instances):
    """字典序约束对的数量应等于同组实例数 - 1。"""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from src.placement.symmetry_breaking import (
        group_instances_by_template,
        generate_lexicographic_ordering,
    )

    groups = group_instances_by_template(all_instances)

    for tpl, ids in groups.items():
        pairs = generate_lexicographic_ordering(ids, [])
        assert len(pairs) == len(ids) - 1, (
            f"{tpl}: 约束对数 {len(pairs)} != 实例数-1 ({len(ids) - 1})"
        )


# ============================================================================
# 合理性检查
# ============================================================================

def test_total_pool_sizes_sanity(facility_pools):
    """各模板池总量应在合理范围内：>0 且 < 100000。"""
    total = 0
    for tpl_key, placements in facility_pools.items():
        n = len(placements)
        assert 0 < n < 100000, f"{tpl_key}: 池规模 {n} 不合理"
        total += n
    # 总量预估：50k-100k 之间
    assert 30000 < total < 200000, f"总计 {total} 个 pose 不在合理范围内"
