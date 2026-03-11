"""
几何预处理引擎：候选摆位枚举器 (Candidate Placement Enumeration)
对应规格书：06_candidate_placement_enumeration
目标：穷举全场所有设施模板在 70x70 棋盘上的绝对合法物理坐标，并生成离散坑位字典。
"""

import json
import time
from pathlib import Path
from typing import List, Dict, Any

GRID_W = 70
GRID_H = 70

# ==========================================
# 1. 基础几何辅助函数
# ==========================================

def get_occupied_cells(x: int, y: int, w: int, h: int) -> List[List[int]]:
    """依据 02 章，计算绝对锚点下的本体地面占格投影"""
    return [[cx, cy] for cx in range(x, x + w) for cy in range(y, y + h)]

def get_edge_ports(x: int, y: int, w: int, h: int, edge: str, indices: List[int] = None) -> List[Dict[str, Any]]:
    """依据 02 章四边局部 1D 坐标系，生成选定边缘上的全部合法端口坐标及向外法向量"""
    ports = []
    if edge == 'top':
        for i in range(w):
            if indices is None or i in indices:
                ports.append({"x": x + i, "y": y + h - 1, "dir": "N"})
    elif edge == 'bottom':
        for i in range(w):
            if indices is None or i in indices:
                ports.append({"x": x + i, "y": y, "dir": "S"})
    elif edge == 'left':
        for i in range(h):
            if indices is None or i in indices:
                ports.append({"x": x, "y": y + i, "dir": "W"})
    elif edge == 'right':
        for i in range(h):
            if indices is None or i in indices:
                ports.append({"x": x + w - 1, "y": y + i, "dir": "E"})
    return ports

def is_edge_starved(ports: List[Dict[str, Any]]) -> bool:
    """面壁死锁法则 (06章 6.5.1)：若该边的所有端口全被地图物理绝对边界封死，则返回 True"""
    if not ports:
        return False
    
    def is_blocked(p):
        if p['dir'] == 'N' and p['y'] == GRID_H - 1: return True
        if p['dir'] == 'S' and p['y'] == 0: return True
        if p['dir'] == 'E' and p['x'] == GRID_W - 1: return True
        if p['dir'] == 'W' and p['x'] == 0: return True
        return False
        
    # 只有当该侧边所有的合法端口都被面壁时，才判定该边为死锁
    return all(is_blocked(p) for p in ports)

def build_placement_obj(x: int, y: int, o: int, mode: str, w: int, h: int, 
                        in_ports: List, out_ports: List, cov: List = None) -> Dict[str, Any]:
    """组装规范化的候选位姿字典对象"""
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
    """生成长方形设施 (如 6x4)，长边强制对立出入"""
    placements = []
    
    # o=0 (横向): 长边为 top/bottom
    w, h = w_base, h_base
    for x in range(GRID_W - w + 1):
        for y in range(GRID_H - h + 1):
            for in_e, out_e, mode in [('top', 'bottom', 'NS'), ('bottom', 'top', 'SN')]:
                in_p = get_edge_ports(x, y, w, h, in_e)
                out_p = get_edge_ports(x, y, w, h, out_e)
                if not is_edge_starved(in_p) and not is_edge_starved(out_p):
                    placements.append(build_placement_obj(x, y, 0, mode, w, h, in_p, out_p))
                    
    # o=1 (竖向): 长边为 left/right
    w, h = h_base, w_base
    for x in range(GRID_W - w + 1):
        for y in range(GRID_H - h + 1):
            for in_e, out_e, mode in [('right', 'left', 'EW'), ('left', 'right', 'WE')]:
                in_p = get_edge_ports(x, y, w, h, in_e)
                out_p = get_edge_ports(x, y, w, h, out_e)
                if not is_edge_starved(in_p) and not is_edge_starved(out_p):
                    placements.append(build_placement_obj(x, y, 1, mode, w, h, in_p, out_p))
                    
    return placements

def gen_square_manufacturing(s: int) -> List[Dict]:
    """生成正方形设施 (3x3, 5x5)，利用模式枚举消除旋转对称性废解"""
    placements = []
    w, h = s, s
    for x in range(GRID_W - w + 1):
        for y in range(GRID_H - h + 1):
            # 仅生成 o=0，靠改变平行边模式来覆盖物理可行域
            modes = [('top', 'bottom', 'NS'), ('bottom', 'top', 'SN'), 
                     ('right', 'left', 'EW'), ('left', 'right', 'WE')]
            for in_e, out_e, mode in modes:
                in_p = get_edge_ports(x, y, w, h, in_e)
                out_p = get_edge_ports(x, y, w, h, out_e)
                if not is_edge_starved(in_p) and not is_edge_starved(out_p):
                    placements.append(build_placement_obj(x, y, 0, mode, w, h, in_p, out_p))
    return placements

def gen_protocol_core() -> List[Dict]:
    """生成 9x9 协议核心 (带局部索引约束)"""
    placements = []
    w, h = 9, 9
    for x in range(GRID_W - w + 1):
        for y in range(GRID_H - h + 1):
            # o=0: 左右出 (1,4,7格)，上下进 (1-7格)
            out_left = get_edge_ports(x, y, w, h, 'left', [1, 4, 7])
            out_right = get_edge_ports(x, y, w, h, 'right', [1, 4, 7])
            in_bottom = get_edge_ports(x, y, w, h, 'bottom', list(range(1, 8)))
            in_top = get_edge_ports(x, y, w, h, 'top', list(range(1, 8)))
            
            # 若任一激活边缘被墙完全封死，则该方案无法接满所需的 6 个出口或输入口，当场剔除
            if not (is_edge_starved(out_left) or is_edge_starved(out_right) or 
                    is_edge_starved(in_bottom) or is_edge_starved(in_top)):
                placements.append(build_placement_obj(x, y, 0, 'core_0', w, h, 
                                                      in_bottom + in_top, out_left + out_right))
                
            # o=1: 上下出，左右进
            out_top = get_edge_ports(x, y, w, h, 'top', [1, 4, 7])
            out_bottom = get_edge_ports(x, y, w, h, 'bottom', [1, 4, 7])
            in_left = get_edge_ports(x, y, w, h, 'left', list(range(1, 8)))
            in_right = get_edge_ports(x, y, w, h, 'right', list(range(1, 8)))
            
            if not (is_edge_starved(out_top) or is_edge_starved(out_bottom) or 
                    is_edge_starved(in_left) or is_edge_starved(in_right)):
                placements.append(build_placement_obj(x, y, 1, 'core_1', w, h, 
                                                      in_left + in_right, out_top + out_bottom))
    return placements

def gen_power_pole() -> List[Dict]:
    """生成供电桩 (极简扫描 + 自动裁剪 12x12 越界覆盖域)"""
    placements = []
    w, h = 2, 2
    for x in range(GRID_W - w + 1):
        for y in range(GRID_H - h + 1):
            cov = [[cx, cy] for cx in range(max(0, x - 5), min(GRID_W, x + 7))
                            for cy in range(max(0, y - 5), min(GRID_H, y + 7))]
            placements.append(build_placement_obj(x, y, 0, 'omni', w, h, [], [], cov))
    return placements

def gen_boundary_ports() -> List[Dict]:
    """生成边界口 (强制基线锚定法，完美规避左下角0,0重叠死点)"""
    placements = []
    # 左基线: x=0, y=1..66, w=1, h=3
    for y in range(1, 67):
        out_p = [{"x": 0, "y": y + 1, "dir": "E"}] # 对场内而言，取货口是供料方(出向)
        placements.append(build_placement_obj(0, y, 0, 'left_base', 1, 3, [], out_p))
        
    # 下基线: x=1..66, y=0, w=3, h=1
    for x in range(1, 67):
        out_p = [{"x": x + 1, "y": 0, "dir": "N"}]
        placements.append(build_placement_obj(x, 0, 1, 'bottom_base', 3, 1, [], out_p))
        
    return placements

# ==========================================
# 3. 提供给外层的动态空地接口
# ==========================================
def generate_empty_rect_domain(w: int, h: int) -> List[Dict]:
    """供给外层 Python 智能打分引擎调用的动态幽灵空地候选域"""
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
# 主控引擎
# ==========================================
def main():
    print("🚀 [开始] 启动几何降维引擎，执行全图扫荡与死区剔除...")
    start_time = time.time()
    
    facility_pools = {
        "manufacturing_rect_6x4": gen_rect_manufacturing(6, 4),
        "manufacturing_square_5": gen_square_manufacturing(5),
        "manufacturing_square_3": gen_square_manufacturing(3),
        "protocol_storage_box":   gen_square_manufacturing(3), 
        "protocol_core":          gen_protocol_core(),
        "power_pole":             gen_power_pole(),
        "boundary_storage_port":  gen_boundary_ports()
    }
    
    total_placements = 0
    print("\n📊 各模板合法位姿字典规模审计：")
    for template, placements in facility_pools.items():
        count = len(placements)
        total_placements += count
        print(f"   - {template.ljust(25)}: {count:5d} 个合法解")
        
    print(f"\n✅ [降维成功] 扫描完毕！全场共生成 {total_placements} 个纯净合法坑位，耗时 {time.time() - start_time:.2f} 秒！")
    
    # 落地保存
    project_root = Path(__file__).resolve().parent.parent.parent
    output_dir = project_root / "data" / "preprocessed"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_path = output_dir / "candidate_placements.json"
    
    # 因为字典包含大量坐标数组，使用 separators=(',', ':') 紧凑格式可以节约至少 30% 的 IO 体积
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({"facility_pools": facility_pools}, f, separators=(',', ':'))
        
    print(f"💾 [保存] 降维字典序列化完成！文件大小约 {output_path.stat().st_size / (1024*1024):.2f} MB")
    print(f"   -> 已安全存储至 {output_path.relative_to(project_root)}")
    print("-" * 65)
    print("【几何引擎就绪】极其恐怖的无限坐标搜索空间，已被成功坍缩为离散的『座位名单』！")
    print("【下一步】万事俱备，即将开启最终的运筹圣杯 —— 07 章主摆放数学模型 (Master Placement Model)！")

if __name__ == "__main__":
    main()