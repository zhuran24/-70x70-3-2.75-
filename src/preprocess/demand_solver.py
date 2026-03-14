"""
预处理核心：全局需求展开与算力推演 (Global Demand Solver)
Status: ACCEPTED_DRAFT

目标：基于终极业务目标 (3电池满载 + 2.75胶囊满载)，通过拓扑逆向推导，
计算全场精确的物料流率与机器实例化总数。
遵循规则：全局池化 (无专属专线)、严格向上取整 (Ceil)、农业自洽闭环。
"""

import json
import math
from pathlib import Path
from collections import defaultdict
from typing import Dict, Any

# ==========================================
# 1. 终极吞吐目标 (Unit: items / tick)
# ==========================================
# 1 tick = 2s
# 电池配方: 10s (5 ticks) 产出 1，故单台满载 = 0.2 / tick
# 胶囊配方: 10s (5 ticks) 产出 1，故单台满载 = 0.2 / tick
TARGET_FLOWS = {
    "valley_battery": 3.0 * 0.2,    # 3 条满速 = 0.6 / tick
    "qiaoyu_capsule": 2.75 * 0.2    # 2.75 等效满速 = 0.55 / tick
}

def solve_demands() -> tuple[Dict[str, float], Dict[str, float]]:
    """
    通过反向链式推导 (Backward Chaining)，计算全场理论物料流率与分数态机器算力。
    """
    flows = defaultdict(float)
    machines_fractional = defaultdict(float)

    # --- 第一级：最终组装层 ---
    flows["valley_battery"] = TARGET_FLOWS["valley_battery"]
    machines_fractional["packaging_battery"] = flows["valley_battery"] / 0.2
    # 封装机单次配方(5 ticks) 消耗 15 致密源石，10 钢制零件
    flows["dense_source_powder"] += machines_fractional["packaging_battery"] * (15.0 / 5.0)
    flows["steel_part"] += machines_fractional["packaging_battery"] * (10.0 / 5.0)

    flows["qiaoyu_capsule"] = TARGET_FLOWS["qiaoyu_capsule"]
    machines_fractional["filling_capsule"] = flows["qiaoyu_capsule"] / 0.2
    # 灌装机单次配方(5 ticks) 消耗 10 钢质瓶，10 细磨荞花
    flows["fine_buckwheat_powder"] += machines_fractional["filling_capsule"] * (10.0 / 5.0)
    flows["steel_bottle"] += machines_fractional["filling_capsule"] * (10.0 / 5.0)

    # --- 第二级：五金与初级合成层 ---
    # 配件机(1 tick): 1 钢块 -> 1 零件
    machines_fractional["parts_maker"] = flows["steel_part"] / 1.0
    flows["steel_block"] += machines_fractional["parts_maker"] * 1.0

    # 塑型机(1 tick): 2 钢块 -> 1 钢质瓶
    machines_fractional["molding_bottle"] = flows["steel_bottle"] / 1.0
    flows["steel_block"] += machines_fractional["molding_bottle"] * 2.0

    # 研磨机(致密源石)(1 tick): 2 源石粉 + 1 砂叶粉 -> 1 致密源石
    machines_fractional["grinder_dense_source"] = flows["dense_source_powder"] / 1.0
    flows["source_powder"] += machines_fractional["grinder_dense_source"] * 2.0
    flows["sandleaf_powder"] += machines_fractional["grinder_dense_source"] * 1.0

    # 研磨机(细磨荞花)(1 tick): 2 荞花粉 + 1 砂叶粉 -> 1 细磨荞花
    machines_fractional["grinder_fine_buckwheat"] = flows["fine_buckwheat_powder"] / 1.0
    flows["buckwheat_powder"] += machines_fractional["grinder_fine_buckwheat"] * 2.0
    flows["sandleaf_powder"] += machines_fractional["grinder_fine_buckwheat"] * 1.0

    # --- 第三级：钢铁精炼层 ---
    # 精炼炉(钢块)(1 tick): 1 致密蓝铁粉 -> 1 钢块
    machines_fractional["refinery_steel"] = flows["steel_block"] / 1.0
    flows["dense_blue_iron_powder"] += machines_fractional["refinery_steel"] * 1.0

    # --- 第四级：蓝铁调和与作物粉碎层 ---
    # 研磨机(致密蓝铁)(1 tick): 2 蓝铁粉 + 1 砂叶粉 -> 1 致密蓝铁
    machines_fractional["grinder_dense_blue_iron"] = flows["dense_blue_iron_powder"] / 1.0
    flows["blue_iron_powder"] += machines_fractional["grinder_dense_blue_iron"] * 2.0
    flows["sandleaf_powder"] += machines_fractional["grinder_dense_blue_iron"] * 1.0

    # 粉碎机(源石)(1 tick): 1 源矿 -> 1 源石粉
    machines_fractional["crusher_source"] = flows["source_powder"] / 1.0
    flows["source_ore"] += machines_fractional["crusher_source"] * 1.0

    # 粉碎机(荞花)(1 tick): 1 荞花 -> 2 荞花粉
    machines_fractional["crusher_buckwheat"] = flows["buckwheat_powder"] / 2.0
    flows["buckwheat"] += machines_fractional["crusher_buckwheat"] * 1.0

    # 粉碎机(砂叶)(1 tick): 1 砂叶 -> 3 砂叶粉
    machines_fractional["crusher_sandleaf"] = flows["sandleaf_powder"] / 3.0
    flows["sandleaf"] += machines_fractional["crusher_sandleaf"] * 1.0

    # --- 第五级：矿石粉碎与冶炼底层 ---
    # 粉碎机(蓝铁)(1 tick): 1 蓝铁块 -> 1 蓝铁粉
    machines_fractional["crusher_blue_iron"] = flows["blue_iron_powder"] / 1.0
    flows["blue_iron_block"] += machines_fractional["crusher_blue_iron"] * 1.0

    # 精炼炉(蓝铁块)(1 tick): 1 蓝铁矿 -> 1 蓝铁块
    machines_fractional["refinery_blue_iron"] = flows["blue_iron_block"] / 1.0
    flows["blue_iron_ore"] += machines_fractional["refinery_blue_iron"] * 1.0

    # --- 第六级：农业自洽系统解析 (依据 04 章代数闭环) ---
    # 对于净需求为 D 的作物，需精确配备 2D 台种植机与 D 台采种机
    machines_fractional["planter_buckwheat"] = flows["buckwheat"] * 2.0
    machines_fractional["seed_collector_buckwheat"] = flows["buckwheat"] * 1.0

    machines_fractional["planter_sandleaf"] = flows["sandleaf"] * 2.0
    machines_fractional["seed_collector_sandleaf"] = flows["sandleaf"] * 1.0

    return flows, machines_fractional

def generate_ceil_machine_counts(machines_fractional: Dict[str, float]) -> Dict[str, int]:
    """严格向上取整规则 (Ceil Rule)
    
    注意：由于浮点链式计算可能产生微小误差（如 3.0 变成 3.0000000000000004），
    必须先 round(x, 10) 吸收 IEEE 754 噪声，再执行 ceil，否则会导致虚假 +1。
    round(10) 足以消灭 1e-15 级别的误差，但完全保留如 2.75、10.5 等真实分数。
    """
    counts = {}
    for machine_type, frac_count in machines_fractional.items():
        counts[machine_type] = math.ceil(round(frac_count, 10))
    return counts

def generate_port_budget(flows: Dict[str, float]) -> Dict[str, Any]:
    """生成原生矿物进口的硬性预算稽核（The 52-Port Miracle）"""
    source_req = flows["source_ore"]
    blue_iron_req = flows["blue_iron_ore"]
    total_req = source_req + blue_iron_req

    return {
        "miracle_52_budget": {
            "source_ore_inputs_required": source_req,
            "blue_iron_ore_inputs_required": blue_iron_req,
            "total_boundary_and_core_ports_required": total_req
        },
        "available_resources": {
            "max_boundary_ports_left_and_bottom": 46,
            "protocol_core_extra_outputs": 6,
            "total_available": 52
        },
        "status": "FEASIBLE" if total_req <= 52.0 else "INFEASIBLE_EXCEEDS_CAPACITY"
    }

def main():
    print("🚀 [预处理] 启动全局算力推演引擎...")
    
    flows, machines_fractional = solve_demands()
    machine_counts = generate_ceil_machine_counts(machines_fractional)
    port_budget = generate_port_budget(flows)

    total_machines = sum(machine_counts.values())
    print(f"📊 [推演完成] 全局需实例化制造单位总计: {total_machines} 台。")
    print(f"📊 [预算稽核] 原矿接口总需求: {port_budget['miracle_52_budget']['total_boundary_and_core_ports_required']} 口。")
    
    # 建立输出目录
    project_root = Path(__file__).resolve().parent.parent.parent
    output_dir = project_root / "data" / "preprocessed"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 数据落盘
    flows_path = output_dir / "commodity_demands.json"
    with open(flows_path, "w", encoding="utf-8") as f:
        json.dump(flows, f, indent=2, ensure_ascii=False)

    counts_path = output_dir / "machine_counts.json"
    with open(counts_path, "w", encoding="utf-8") as f:
        json.dump(machine_counts, f, indent=2, ensure_ascii=False)

    budget_path = output_dir / "port_budget.json"
    with open(budget_path, "w", encoding="utf-8") as f:
        json.dump(port_budget, f, indent=2, ensure_ascii=False)

    print(f"💾 [保存] 算力矩阵、流量字典与端口预算已写入 {output_dir.relative_to(project_root)}。")
    print("✅ [就绪] 待进入下一环节：instance_builder.py。")

if __name__ == "__main__":
    main()
