"""
几何预处理引擎：候选摆位枚举器 (Candidate Placement Enumeration)
对应规格书：06_candidate_placement_enumeration
Status: ACCEPTED_DRAFT

目标：穷举全场所有设施模板在 70x70 棋盘上的绝对合法物理坐标，并生成离散坑位字典。
重写自旧版草案，修正以下已知缺陷：
  - pool key 与 canonical_rules.json 的 template key 对齐
  - 协议箱(protocol_storage_box) 按 omni_wireless 规则不生成端口
  - 动态从 canonical_rules.json 读取模板定义
"""

import json
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

# ==========================================
# 0. 常量
# ==========================================
GRID_W = 70
GRID_H = 70

# ==========================================
# 1. 基础几何辅助函数
# ==========================================

def get_occupied_cells(x: int, y: int, w: int, h: int) -> List[List[int]]:
    """依据 02 章，计算绝对锚点下的本体地面占格投影。
    锚点为包围盒左下角 (x, y)，右上角为 (x+w-1, y+h-1)。
    """
    return [[cx, cy] for cx in range(x, x + w) for cy in range(y, y + h)]


def get_edge_ports(x: int, y: int, w: int, h: int, edge: str,
                   indices: Optional[List[int]] = None) -> List[Dict[str, Any]]:
    """依据 02 章四边局部 1D 坐标系，生成选定边缘上的合法端口坐标及向外法向量。

    Args:
        x, y: 包围盒左下角锚点
        w, h: 包围盒宽高
        edge: 'top' | 'bottom' | 'left' | 'right'
        indices: 可选，指定该边上局部 1D 索引中允许的端口位置
    """
    ports = []
    if edge == 'top':
        for i in range(w):
            if indices is None or i in indices:
                ports.append({"x": x + i, "y": y + h, "dir": "N"})
    elif edge == 'bottom':
        for i in range(w):
            if indices is None or i in indices:
                ports.append({"x": x + i, "y": y - 1, "dir": "S"})
    elif edge == 'left':
        for i in range(h):
            if indices is None or i in indices:
                ports.append({"x": x - 1, "y": y + i, "dir": "W"})
    elif edge == 'right':
        for i in range(h):
            if indices is None or i in indices:
                ports.append({"x": x + w, "y": y + i, "dir": "E"})
    return ports


def is_edge_starved(ports: List[Dict[str, Any]]) -> bool:
    """面壁死锁法则 (06章 §6.5.1)：
    若该边的所有端口的接管格坐标全部落在地图外，则返回 True。
    端口的接管格坐标已经是"向外一格"，所以只需检查 [0, 69] 范围。
    """
    if not ports:
        return False

    def is_blocked(p: Dict[str, Any]) -> bool:
        px, py = p['x'], p['y']
        return px < 0 or px >= GRID_W or py < 0 or py >= GRID_H

    return all(is_blocked(p) for p in ports)


def build_placement_obj(x: int, y: int, o: int, mode: str, w: int, h: int,
                        in_ports: List, out_ports: List,
                        cov: Optional[List] = None) -> Dict[str, Any]:
    """组装规范化的候选位姿字典对象。"""
    return {
        "pose_id": f"p_x{x:02d}_y{y:02d}_o{o}_m_{mode}",
        "anchor": {"x": x, "y": y},
        "pose_params": {"orientation": o, "port_mode": mode},
        "occupied_cells": get_occupied_cells(x, y, w, h),
        "input_port_cells": in_ports,
        "output_port_cells": out_ports,
        "power_coverage_cells": cov
    }


# ==========================================
# 2. 设施模板遍历发生器 (Generators)
# ==========================================

def gen_rect_manufacturing(w_base: int, h_base: int) -> List[Dict]:
    """生成长方形设施 (如 6x4)。
    port_rule=long_sides: 端口强制分布在两条长边上。
    对于 6x4，长边=6 格，两种旋转 (o=0 横向, o=1 竖向) × 两种通流方向。
    """
    placements = []

    # o=0 (横向 w_base x h_base): 长边为 top/bottom (w_base 格)
    w, h = w_base, h_base
    for x in range(GRID_W - w + 1):
        for y in range(GRID_H - h + 1):
            for in_e, out_e, mode in [('top', 'bottom', 'TB'), ('bottom', 'top', 'BT')]:
                in_p = get_edge_ports(x, y, w, h, in_e)
                out_p = get_edge_ports(x, y, w, h, out_e)
                if not is_edge_starved(in_p) and not is_edge_starved(out_p):
                    placements.append(build_placement_obj(x, y, 0, mode, w, h, in_p, out_p))

    # o=1 (竖向 h_base x w_base): 长边为 left/right (w_base 格)
    w, h = h_base, w_base
    for x in range(GRID_W - w + 1):
        for y in range(GRID_H - h + 1):
            for in_e, out_e, mode in [('right', 'left', 'RL'), ('left', 'right', 'LR')]:
                in_p = get_edge_ports(x, y, w, h, in_e)
                out_p = get_edge_ports(x, y, w, h, out_e)
                if not is_edge_starved(in_p) and not is_edge_starved(out_p):
                    placements.append(build_placement_obj(x, y, 1, mode, w, h, in_p, out_p))

    return placements


def gen_square_manufacturing(s: int) -> List[Dict]:
    """生成正方形设施 (3x3, 5x5)。
    port_rule=opposite_parallel_sides: 在每个 (x,y) 下生成四种正交端口模式。
    旋转对等性去重 (§6.5.2): 正方形 o=0 与 o=2 等价, o=1 与 o=3 等价。
    因此固定 o=0，通过 port_mode 覆盖所有物理可行域。
    """
    placements = []
    w, h = s, s
    for x in range(GRID_W - w + 1):
        for y in range(GRID_H - h + 1):
            modes = [
                ('top', 'bottom', 'TB'),
                ('bottom', 'top', 'BT'),
                ('right', 'left', 'RL'),
                ('left', 'right', 'LR'),
            ]
            for in_e, out_e, mode in modes:
                in_p = get_edge_ports(x, y, w, h, in_e)
                out_p = get_edge_ports(x, y, w, h, out_e)
                if not is_edge_starved(in_p) and not is_edge_starved(out_p):
                    placements.append(build_placement_obj(x, y, 0, mode, w, h, in_p, out_p))
    return placements


def gen_protocol_core() -> List[Dict]:
    """生成 9x9 协议核心。
    port_rule=core_specific:
      o=0: 左右出 (局部索引 1,4,7 → 3×2=6 出口)，上下进 (局部索引 1-7 → 7×2=14 入口)
      o=1: 上下出 (局部索引 1,4,7)，左右进 (局部索引 1-7)
    """
    placements = []
    w, h = 9, 9
    output_indices = [1, 4, 7]
    input_indices = list(range(1, 8))

    for x in range(GRID_W - w + 1):
        for y in range(GRID_H - h + 1):

            # o=0: 左右出，上下进
            out_left = get_edge_ports(x, y, w, h, 'left', output_indices)
            out_right = get_edge_ports(x, y, w, h, 'right', output_indices)
            in_bottom = get_edge_ports(x, y, w, h, 'bottom', input_indices)
            in_top = get_edge_ports(x, y, w, h, 'top', input_indices)

            all_out_0 = out_left + out_right
            all_in_0 = in_bottom + in_top

            # 只要出口或入口中有任何一侧被完全封死，就剔除
            if not is_edge_starved(out_left) and not is_edge_starved(out_right) \
               and not is_edge_starved(in_bottom) and not is_edge_starved(in_top):
                placements.append(build_placement_obj(
                    x, y, 0, 'core_LR_out', w, h, all_in_0, all_out_0))

            # o=1: 上下出，左右进
            out_top = get_edge_ports(x, y, w, h, 'top', output_indices)
            out_bottom = get_edge_ports(x, y, w, h, 'bottom', output_indices)
            in_left = get_edge_ports(x, y, w, h, 'left', input_indices)
            in_right = get_edge_ports(x, y, w, h, 'right', input_indices)

            all_out_1 = out_top + out_bottom
            all_in_1 = in_left + in_right

            if not is_edge_starved(out_top) and not is_edge_starved(out_bottom) \
               and not is_edge_starved(in_left) and not is_edge_starved(in_right):
                placements.append(build_placement_obj(
                    x, y, 1, 'core_TB_out', w, h, all_in_1, all_out_1))

    return placements


def gen_protocol_storage_box() -> List[Dict]:
    """生成 3x3 协议储存箱。

    虽然协议箱支持无线清仓，但根据冻结规则，它仍有明确的物理输入/输出边，
    因此候选几何必须保留和方形设施一致的对边端口模式。
    """
    return gen_square_manufacturing(3)


def gen_power_pole() -> List[Dict]:
    """生成供电桩 (极简扫描 + 自动裁剪 12x12 越界覆盖域)。
    port_rule=none: 无端口，面壁死锁不适用。
    旋转对称：2x2 正方形，固定 o=0。
    覆盖域：以桩体中心为圆心的 12x12 方形区域，边界处自动截断至 [0, 69]。
    桩体占格 [x, x+1] × [y, y+1]，覆盖域中心约为 (x+0.5, y+0.5)，
    因此覆盖 X ∈ [x-5, x+6], Y ∈ [y-5, y+6]。
    """
    placements = []
    w, h = 2, 2
    for x in range(GRID_W - w + 1):
        for y in range(GRID_H - h + 1):
            cov = [[cx, cy]
                   for cx in range(max(0, x - 5), min(GRID_W, x + 7))
                   for cy in range(max(0, y - 5), min(GRID_H, y + 7))]
            placements.append(build_placement_obj(x, y, 0, 'omni', w, h, [], [], cov))
    return placements


def gen_boundary_ports() -> List[Dict]:
    """生成边界仓库存/取货口 (强制基线锚定法 §6.4.3)。
    port_rule=inward_facing: 端口固定朝场内方向。
    placement_rule=left_or_bottom_boundary。

    左基线: x=0, 竖向 1×3, y ∈ [1, 67)。中间格向右出向。
    下基线: y=0, 横向 3×1, x ∈ [1, 67)。中间格向上出向。
    起点从 1 开始，避开左下角 (0, 0) 的拐角重叠。
    
    注意：边界口的端口方向是"对场内供料"，因此算作 output_port_cells。
    """
    placements = []

    # 左基线: x=0, w=1, h=3, y ∈ [1, 67]
    for y in range(1, GRID_H - 3 + 1):
        # 端口在中间格 (0, y+1)，向右 (E) 供料给场内
        out_p = [{"x": 1, "y": y + 1, "dir": "E"}]
        placements.append(build_placement_obj(0, y, 0, 'left_base', 1, 3, [], out_p))

    # 下基线: y=0, w=3, h=1, x ∈ [1, 67]
    for x in range(1, GRID_W - 3 + 1):
        # 端口在中间格 (x+1, 0)，向上 (N) 供料给场内
        out_p = [{"x": x + 1, "y": 1, "dir": "N"}]
        placements.append(build_placement_obj(x, 0, 1, 'bottom_base', 3, 1, [], out_p))

    return placements


def generate_empty_rect_domain(w: int, h: int) -> List[Dict]:
    """供给外层 Python 智能打分引擎调用的动态幽灵空地候选域 (§6.7)。
    输入：外层传入的空地宽度 w 和高度 h。
    输出：纯粹的占格集合。
    """
    domains = []
    for x in range(GRID_W - w + 1):
        for y in range(GRID_H - h + 1):
            domains.append({
                "pose_id": f"rect_w{w}_h{h}_x{x:02d}_y{y:02d}",
                "anchor": {"x": x, "y": y},
                "occupied_cells": get_occupied_cells(x, y, w, h)
            })
    return domains


# ==========================================
# 3. 主控引擎
# ==========================================

def load_templates() -> Dict[str, Any]:
    """从 canonical_rules.json 动态加载模板定义。"""
    project_root = Path(__file__).resolve().parent.parent.parent
    rules_path = project_root / "rules" / "canonical_rules.json"
    with open(rules_path, "r", encoding="utf-8") as f:
        rules = json.load(f)
    return rules["facility_templates"]


def generate_all_pools(templates: Dict[str, Any]) -> Dict[str, List[Dict]]:
    """根据模板定义分派对应的枚举逻辑，生成全部模板级候选池。
    Pool key 严格使用 canonical_rules.json 中的 template key。
    """
    pools: Dict[str, List[Dict]] = {}

    for tpl_key, tpl_def in templates.items():
        dims = tpl_def["dimensions"]
        w, h = dims["w"], dims["h"]
        port_rule = tpl_def["port_rule"]

        if port_rule == "long_sides":
            # 长方形制造设施 (如 manufacturing_6x4)
            pools[tpl_key] = gen_rect_manufacturing(w, h)

        elif port_rule == "opposite_parallel_sides":
            # 正方形制造设施 (如 manufacturing_3x3, manufacturing_5x5)
            assert w == h, f"opposite_parallel_sides 只适用于正方形，但 {tpl_key} 尺寸为 {w}x{h}"
            pools[tpl_key] = gen_square_manufacturing(w)

        elif port_rule == "core_specific":
            # 协议核心
            pools[tpl_key] = gen_protocol_core()

        elif port_rule == "omni_wireless":
            # 协议储存箱 (无线终端，不生成端口)
            pools[tpl_key] = gen_protocol_storage_box()

        elif port_rule == "none":
            # 供电桩
            pools[tpl_key] = gen_power_pole()

        elif port_rule == "inward_facing":
            # 边界仓库口
            pools[tpl_key] = gen_boundary_ports()

        else:
            raise ValueError(f"未知的 port_rule: {port_rule} (模板: {tpl_key})")

    return pools


def main():
    print("🚀 [开始] 启动几何降维引擎，执行全图扫荡与死区剔除...")
    start_time = time.time()

    templates = load_templates()
    facility_pools = generate_all_pools(templates)

    total_placements = 0
    print("\n📊 各模板合法位姿字典规模审计：")
    for template, placements in facility_pools.items():
        count = len(placements)
        total_placements += count
        print(f"   - {template.ljust(30)}: {count:7d} 个合法解")

    elapsed = time.time() - start_time
    print(f"\n✅ [降维成功] 扫描完毕！全场共生成 {total_placements} 个纯净合法坑位，耗时 {elapsed:.2f} 秒！")

    # 落地保存
    project_root = Path(__file__).resolve().parent.parent.parent
    output_dir = project_root / "data" / "preprocessed"
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / "candidate_placements.json"

    # 使用紧凑格式节约 IO 体积
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({"facility_pools": facility_pools}, f, separators=(',', ':'))

    file_size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"💾 [保存] 降维字典序列化完成！文件大小约 {file_size_mb:.2f} MB")
    print(f"   -> 已安全存储至 {output_path.relative_to(project_root)}")
    print("-" * 65)
    print("【几何引擎就绪】极其恐怖的无限坐标搜索空间，已被成功坍缩为离散的『座位名单』！")
    print("【下一步】即将开启 occupancy_masks 与 symmetry_breaking 构建。")


if __name__ == "__main__":
    main()
