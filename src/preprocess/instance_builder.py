"""
预处理核心：全局刚体实例化构建器 (Global Instance Builder)
对应规格书：05_facility_instance_definition
目标：合并制造单位实例，并补齐全场所有非制造设施（强制与可选备用），生成最终的 326 个独立刚体花名册。
"""

import json
from pathlib import Path
from typing import List, Dict, Any

def load_manufacturing_instances(filepath: Path) -> List[Dict[str, Any]]:
    """加载阶段 04 生成的制造单位实例，并标记为强制必选"""
    if not filepath.exists():
        raise FileNotFoundError(f"找不到制造单位实例文件：{filepath}。请先运行 demand_solver.py")
        
    with open(filepath, "r", encoding="utf-8") as f:
        instances = json.load(f)
        
    # 为制造单位追加 05 章定义的强制属性
    for inst in instances:
        inst["is_mandatory"] = True
    return instances

def build_core_instance() -> Dict[str, Any]:
    """生成 1 座强制必选的协议核心"""
    return {
        "instance_id": "protocol_core_001",
        "facility_type": "protocol_core",
        "is_mandatory": True,
        "needs_power": False,
        "port_topology": {
            "total_input_belts_required": 0,  # 允许入口空置
            "total_output_belts_required": 6, # 依据 04 章 52-Port 奇迹，6 个出口必须全部作为公共资源池散出矿物
        },
        "notes": "强制必选：协议核心。其 6 个出口作为全局原矿池的补充。"
    }

def build_boundary_ports() -> List[Dict[str, Any]]:
    """生成 46 个强制必选的边界仓库存/取货口"""
    ports = []
    for i in range(1, 47):
        ports.append({
            "instance_id": f"boundary_port_{i:03d}",
            "facility_type": "boundary_storage_port",
            "is_mandatory": True,
            "needs_power": False,
            "port_topology": {
                "total_input_belts_required": 0,
                "total_output_belts_required": 1, # 每个口负责向场内输入 1 根矿物带
            },
            "notes": f"强制必选：原生取货口。与核心共组 52 个原矿进口。"
        })
    return ports

def build_power_poles(count: int = 50) -> List[Dict[str, Any]]:
    """生成 50 个可选的供电桩备选实例"""
    poles = []
    for i in range(1, count + 1):
        poles.append({
            "instance_id": f"power_pole_{i:03d}",
            "facility_type": "power_pole",
            "is_mandatory": False,  # 主模型按需激活
            "needs_power": False,
            "notes": "可选备选池：供电桩。由模型激活以满足全局 12x12 覆盖。"
        })
    return poles

def build_protocol_boxes(count: int = 10) -> List[Dict[str, Any]]:
    """生成 10 个可选的协议储存箱（用作产物黑洞）"""
    boxes = []
    for i in range(1, count + 1):
        boxes.append({
            "instance_id": f"protocol_box_{i:03d}",
            "facility_type": "protocol_storage_box",
            "is_mandatory": False,  # 主模型按需激活
            "needs_power": True,    # 激活无线清仓必须通电
            "port_topology": {
                "role": "global_sink",
                "total_input_belts_required": "dynamic", # 路由算法可自由向其接入最终产物
                "total_output_belts_required": 0
            },
            "notes": "可选备选池：协议储存箱（黑洞模式）。作为电池与胶囊的最终离场归宿。"
        })
    return boxes

def main():
    print("🚀 [开始] 正在组装全局 326 个刚体实例花名册...")
    
    # 路径解析与创建
    project_root = Path(__file__).resolve().parent.parent.parent
    data_dir = project_root / "data" / "preprocessed"
    data_dir.mkdir(parents=True, exist_ok=True)
    mfg_instances_path = data_dir / "facility_instances.json"
    
    # 1. 加载 219 台制造单位
    mfg_instances = load_manufacturing_instances(mfg_instances_path)
    
    # 2. 生成 05 章定义的核心与辅助设施
    core_instance = build_core_instance()
    boundary_ports = build_boundary_ports()
    power_poles = build_power_poles(50)
    protocol_boxes = build_protocol_boxes(10)
    
    # 3. 合并全集
    all_instances = mfg_instances + [core_instance] + boundary_ports + power_poles + protocol_boxes
    
    # 4. 严格数学审计 (审计是工程的生命线)
    total_count = len(all_instances)
    mandatory_count = sum(1 for inst in all_instances if inst["is_mandatory"])
    optional_count = sum(1 for inst in all_instances if not inst["is_mandatory"])
    
    print(f"📊 [审计] 强制必选刚体 (Mandatory): {mandatory_count} 个 (制造219 + 核心1 + 边界口46)")
    print(f"📊 [审计] 按需激活刚体 (Optional) : {optional_count} 个 (供电桩50 + 协议箱10)")
    print(f"📊 [审计] 全局实例总数 (Total)    : {total_count} 个")
    
    assert mandatory_count == 266, f"❌ 严重错误：强制必选数量 {mandatory_count} != 266"
    assert optional_count == 60, f"❌ 严重错误：按需激活数量 {optional_count} != 60"
    assert total_count == 326, f"❌ 严重错误：全局实例总数 {total_count} != 326"
    
    # 5. 保存最终花名册
    output_path = data_dir / "all_facility_instances.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_instances, f, indent=2, ensure_ascii=False)
        
    print(f"✅ [成功] 完美闭环！全局实例花名册已保存至: {output_path.relative_to(project_root)}")
    print("-" * 65)
    print("【系统就绪】所有实体身份证发放完毕。求解器已明确知道它到底要摆放哪些方块。")
    print("【下一步】候选摆位枚举 (Candidate Placement Enumeration) 阶段已解锁！")

if __name__ == "__main__":
    main()