"""
预处理核心：全局刚体实例化构建器 (Global Instance Builder)
Status: ACCEPTED_DRAFT

目标：合并制造单位实例，并补齐全场所有非制造设施（强制与可选备用），生成最终的刚体花名册。
重点：严格区分 exact(精确证明) 边界与 provisional(临时启发式) 上界，防止污染求解空间的合法性。
"""

import json
from pathlib import Path
from typing import List, Dict, Any

# ==========================================
# 业务机型 -> 物理几何模板 映射表
# 必须完全兼容 rules/canonical_rules.json 中注册的 facility_templates
# ==========================================
TEMPLATE_MAPPING = {
    # 6x4 设施
    "packaging_battery": "manufacturing_6x4",
    "filling_capsule": "manufacturing_6x4",
    "grinder_dense_source": "manufacturing_6x4",
    "grinder_fine_buckwheat": "manufacturing_6x4",
    "grinder_dense_blue_iron": "manufacturing_6x4",
    
    # 5x5 设施
    "planter_buckwheat": "manufacturing_5x5",
    "planter_sandleaf": "manufacturing_5x5",
    "seed_collector_buckwheat": "manufacturing_5x5",
    "seed_collector_sandleaf": "manufacturing_5x5",
    
    # 3x3 设施
    "parts_maker": "manufacturing_3x3",
    "molding_bottle": "manufacturing_3x3",
    "refinery_steel": "manufacturing_3x3",
    "refinery_blue_iron": "manufacturing_3x3",
    "crusher_source": "manufacturing_3x3",
    "crusher_buckwheat": "manufacturing_3x3",
    "crusher_sandleaf": "manufacturing_3x3",
    "crusher_blue_iron": "manufacturing_3x3",
}

def build_manufacturing_instances(counts: Dict[str, int]) -> List[Dict[str, Any]]:
    """生成 219 台强制必选的制造单位实例 (Exact Bound)"""
    instances = []
    for op_type, count in counts.items():
        template = TEMPLATE_MAPPING.get(op_type)
        if not template:
            raise ValueError(f"未知的制造单元业务类型: {op_type}，无法映射至物理模板。")
            
        for i in range(1, count + 1):
            instances.append({
                "instance_id": f"{op_type}_{i:03d}",
                "facility_type": template,
                "operation_type": op_type,
                "is_mandatory": True,
                "bound_type": "exact",
                "notes": "强制实体：由配方矩阵精确推导出的固定算力单元。"
            })
    return instances

def build_core_instance() -> List[Dict[str, Any]]:
    """生成 1 座强制必选的协议核心 (Exact Bound)"""
    return [{
        "instance_id": "protocol_core_001",
        "facility_type": "protocol_core",
        "operation_type": "protocol_core",
        "is_mandatory": True,
        "bound_type": "exact",
        "notes": "强制实体：唯一的协议核心，提供全局公用出货口。"
    }]

def build_boundary_ports(count: int = 46) -> List[Dict[str, Any]]:
    """生成 46 个强制必选的边界仓库存/取货口 (Exact Bound)"""
    ports = []
    for i in range(1, count + 1):
        ports.append({
            "instance_id": f"boundary_port_{i:03d}",
            "facility_type": "boundary_storage_port",
            "operation_type": "boundary_io",
            "is_mandatory": True,
            "bound_type": "exact",
            "notes": "强制实体：贴合物理基线的原生取货口。"
        })
    return ports

def build_power_poles(count: int = 50) -> List[Dict[str, Any]]:
    """生成 50 个可选的供电桩 (Provisional Bound)"""
    poles = []
    for i in range(1, count + 1):
        poles.append({
            "instance_id": f"power_pole_{i:03d}",
            "facility_type": "power_pole",
            "operation_type": "power_supply",
            "is_mandatory": False,
            "bound_type": "provisional",  # 警告：此上限未经验证，不可宣称该上界下的求解为全局最优
            "notes": "可选实体：数量上界为经验设定，供主模型按需激活以覆盖用电需求。"
        })
    return poles

def build_protocol_boxes(count: int = 10) -> List[Dict[str, Any]]:
    """生成 10 个可选的协议储存箱 (Provisional Bound)"""
    boxes = []
    for i in range(1, count + 1):
        boxes.append({
            "instance_id": f"protocol_box_{i:03d}",
            "facility_type": "protocol_storage_box",
            "operation_type": "wireless_sink",
            "is_mandatory": False,
            "bound_type": "provisional",
            "notes": "可选实体：数量上界为经验设定，作为终极产物离场的自由接收终端。"
        })
    return boxes

def main():
    print("🚀 [预处理] 启动全局实例花名册 (Instance Builder) 装配...")
    
    project_root = Path(__file__).resolve().parent.parent.parent
    data_dir = project_root / "data" / "preprocessed"
    counts_path = data_dir / "machine_counts.json"
    
    if not counts_path.exists():
        raise FileNotFoundError(f"找不到文件: {counts_path}。请先运行 demand_solver.py。")
        
    with open(counts_path, "r", encoding="utf-8") as f:
        machine_counts = json.load(f)
        
    # 1. 装配实体
    mfg_instances = build_manufacturing_instances(machine_counts)
    core_instance = build_core_instance()
    boundary_ports = build_boundary_ports(46)
    power_poles = build_power_poles(50)
    protocol_boxes = build_protocol_boxes(10)
    
    # 2. 合并全集
    all_instances = mfg_instances + core_instance + boundary_ports + power_poles + protocol_boxes
    
    # 3. 严格审计与屏障校验
    total_count = len(all_instances)
    mandatory_exact_count = sum(1 for inst in all_instances if inst["is_mandatory"] and inst["bound_type"] == "exact")
    optional_provisional_count = sum(1 for inst in all_instances if not inst["is_mandatory"] and inst["bound_type"] == "provisional")
    
    print(f"📊 [审计] 强制必选 & 精确数量 (Mandatory/Exact) : {mandatory_exact_count} 个 (制造219 + 核心1 + 边界口46)")
    print(f"📊 [审计] 按需激活 & 经验上限 (Optional/Provisional) : {optional_provisional_count} 个 (供电桩50 + 协议箱10)")
    print(f"📊 [审计] 全局可用实例库总规模 (Total) : {total_count} 个")
    
    assert mandatory_exact_count == 266, f"❌ 严重违规：Exact 实体数量 {mandatory_exact_count} != 266"
    assert optional_provisional_count == 60, f"❌ 严重违规：Provisional 实体数量 {optional_provisional_count} != 60"
    assert total_count == 326, f"❌ 严重违规：实例总数 {total_count} != 326"
    
    # 4. 落盘序列化
    output_path = data_dir / "all_facility_instances.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_instances, f, indent=2, ensure_ascii=False)
        
    print(f"💾 [保存] 实例花名册已序列化至: {output_path.relative_to(project_root)}")
    print("✅ [系统就绪] 第 2 组开发顺利通关，预处理层底座已绝对纯净！")

if __name__ == "__main__":
    main()