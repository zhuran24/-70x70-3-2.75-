"""
Global Demand Solver（全局需求求解器）.

本模块只做一件事：把冻结的业务目标展开成
1. commodity_demands.json（物料需求）
2. machine_counts.json（机器数量）
3. port_budget.json（端口预算）
4. generic_io_requirements.json（通用 I/O 需求）

这里的 generic I/O requirements（通用输入输出需求）
只描述“边界/协议核心/协议储存箱”这一类通用枢纽口需要承担的离散端口需求，
供 binding subproblem（绑定子问题）读取；
绑定子问题不再依赖模型内部硬编码默认值。
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Mapping, Tuple

EPSILON = 1e-9

# 1 tick = 2s.
TARGET_FLOWS = {
    "valley_battery": 3.0 * 0.2,
    "qiaoyu_capsule": 2.75 * 0.2,
}


def solve_demands() -> tuple[Dict[str, float], Dict[str, float]]:
    """Backward Chaining（反向链式推导）得到全场物料流率与分数机器数。"""

    flows: Dict[str, float] = defaultdict(float)
    machines_fractional: Dict[str, float] = defaultdict(float)

    # Final assembly（最终组装）.
    flows["valley_battery"] = TARGET_FLOWS["valley_battery"]
    machines_fractional["packaging_battery"] = flows["valley_battery"] / 0.2
    flows["dense_source_powder"] += machines_fractional["packaging_battery"] * (15.0 / 5.0)
    flows["steel_part"] += machines_fractional["packaging_battery"] * (10.0 / 5.0)

    flows["qiaoyu_capsule"] = TARGET_FLOWS["qiaoyu_capsule"]
    machines_fractional["filling_capsule"] = flows["qiaoyu_capsule"] / 0.2
    flows["fine_buckwheat_powder"] += machines_fractional["filling_capsule"] * (10.0 / 5.0)
    flows["steel_bottle"] += machines_fractional["filling_capsule"] * (10.0 / 5.0)

    # Midstream conversion（中游转换）.
    machines_fractional["parts_maker"] = flows["steel_part"] / 1.0
    flows["steel_block"] += machines_fractional["parts_maker"] * 1.0

    machines_fractional["molding_bottle"] = flows["steel_bottle"] / 1.0
    flows["steel_block"] += machines_fractional["molding_bottle"] * 2.0

    machines_fractional["grinder_dense_source"] = flows["dense_source_powder"] / 1.0
    flows["source_powder"] += machines_fractional["grinder_dense_source"] * 2.0
    flows["sandleaf_powder"] += machines_fractional["grinder_dense_source"] * 1.0

    machines_fractional["grinder_fine_buckwheat"] = flows["fine_buckwheat_powder"] / 1.0
    flows["buckwheat_powder"] += machines_fractional["grinder_fine_buckwheat"] * 2.0
    flows["sandleaf_powder"] += machines_fractional["grinder_fine_buckwheat"] * 1.0

    machines_fractional["refinery_steel"] = flows["steel_block"] / 1.0
    flows["dense_blue_iron_powder"] += machines_fractional["refinery_steel"] * 1.0

    machines_fractional["grinder_dense_blue_iron"] = flows["dense_blue_iron_powder"] / 1.0
    flows["blue_iron_powder"] += machines_fractional["grinder_dense_blue_iron"] * 2.0
    flows["sandleaf_powder"] += machines_fractional["grinder_dense_blue_iron"] * 1.0

    # Raw crushing / refining（底层粉碎与精炼）.
    machines_fractional["crusher_source"] = flows["source_powder"] / 1.0
    flows["source_ore"] += machines_fractional["crusher_source"] * 1.0

    machines_fractional["crusher_buckwheat"] = flows["buckwheat_powder"] / 2.0
    flows["buckwheat"] += machines_fractional["crusher_buckwheat"] * 1.0

    machines_fractional["crusher_sandleaf"] = flows["sandleaf_powder"] / 3.0
    flows["sandleaf"] += machines_fractional["crusher_sandleaf"] * 1.0

    machines_fractional["crusher_blue_iron"] = flows["blue_iron_powder"] / 1.0
    flows["blue_iron_block"] += machines_fractional["crusher_blue_iron"] * 1.0

    machines_fractional["refinery_blue_iron"] = flows["blue_iron_block"] / 1.0
    flows["blue_iron_ore"] += machines_fractional["refinery_blue_iron"] * 1.0

    # Agricultural self-cycle（农业自循环）.
    machines_fractional["planter_buckwheat"] = flows["buckwheat"] * 2.0
    machines_fractional["seed_collector_buckwheat"] = flows["buckwheat"] * 1.0

    machines_fractional["planter_sandleaf"] = flows["sandleaf"] * 2.0
    machines_fractional["seed_collector_sandleaf"] = flows["sandleaf"] * 1.0

    return dict(flows), dict(machines_fractional)


def generate_ceil_machine_counts(machines_fractional: Mapping[str, float]) -> Dict[str, int]:
    """Ceil Rule（向上取整规则）.

    先 round 再 ceil，避免 IEEE 754 浮点噪声造成虚假的 +1。
    """

    return {
        machine_type: int(math.ceil(round(frac_count, 10) - EPSILON))
        for machine_type, frac_count in machines_fractional.items()
    }


def generate_port_budget(flows: Mapping[str, float]) -> Dict[str, Any]:
    """The 52-Port Miracle（52 口闭环）预算。"""

    source_req = float(flows["source_ore"])
    blue_iron_req = float(flows["blue_iron_ore"])
    total_req = source_req + blue_iron_req

    return {
        "miracle_52_budget": {
            "source_ore_inputs_required": source_req,
            "blue_iron_ore_inputs_required": blue_iron_req,
            "total_boundary_and_core_ports_required": total_req,
        },
        "available_resources": {
            "max_boundary_ports_left_and_bottom": 46,
            "protocol_core_extra_outputs": 6,
            "total_available": 52,
        },
        "status": "FEASIBLE" if total_req <= 52.0 + EPSILON else "INFEASIBLE_EXCEEDS_CAPACITY",
    }



def generate_generic_io_requirements(
    flows: Mapping[str, float],
    port_budget: Mapping[str, Any],
) -> Dict[str, Any]:
    """Generate generic_io_requirements.json（生成通用 I/O 需求工件）.

    required_generic_outputs（所需通用输出）
    对应边界仓库口 + 协议核心这类“向工厂提供资源”的离散输出槽数。

    required_generic_inputs（所需通用输入）
    对应协议储存箱 / 其他通用收货终端需要承接的离散输入槽数。

    这里对最终产物采用“每个商品至少 1 个通用收货槽”的严格离散需求，
    其含义是：只要某种最终产物存在正流量，就必须在绑定层为其分配至少一个合法收货端口。
    这不把收货端口数量硬写进绑定模型，而是作为预处理工件明确落盘。
    """

    required_generic_outputs = {
        "source_ore": int(round(float(port_budget["miracle_52_budget"]["source_ore_inputs_required"]))),
        "blue_iron_ore": int(round(float(port_budget["miracle_52_budget"]["blue_iron_ore_inputs_required"]))),
    }

    required_generic_inputs = {
        commodity: 1
        for commodity in ("valley_battery", "qiaoyu_capsule")
        if float(flows.get(commodity, 0.0)) > EPSILON
    }

    return {
        "metadata": {
            "artifact_type": "generic_io_requirements",
            "generated_by": "src/preprocess/demand_solver.py",
            "unit": "discrete_port_slots",
            "notes": [
                "required_generic_outputs describes resource-source slots from boundary ports and protocol core.",
                "required_generic_inputs describes sink slots for final products at generic receiving facilities.",
            ],
        },
        "required_generic_outputs": required_generic_outputs,
        "required_generic_inputs": required_generic_inputs,
    }



def save_preprocessed_artifacts(
    output_dir: Path,
    flows: Mapping[str, float],
    machine_counts: Mapping[str, int],
    port_budget: Mapping[str, Any],
    generic_io_requirements: Mapping[str, Any],
) -> None:
    """Write JSON artifacts（写出 JSON 工件）到 data/preprocessed。"""

    output_dir.mkdir(parents=True, exist_ok=True)

    artifacts = {
        "commodity_demands.json": flows,
        "machine_counts.json": machine_counts,
        "port_budget.json": port_budget,
        "generic_io_requirements.json": generic_io_requirements,
    }
    for filename, payload in artifacts.items():
        with (output_dir / filename).open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)



def main() -> None:
    print("🚀 [预处理] 启动 Global Demand Solver（全局需求求解器）...")

    flows, machines_fractional = solve_demands()
    machine_counts = generate_ceil_machine_counts(machines_fractional)
    port_budget = generate_port_budget(flows)
    generic_io_requirements = generate_generic_io_requirements(flows, port_budget)

    project_root = Path(__file__).resolve().parent.parent.parent
    output_dir = project_root / "data" / "preprocessed"
    save_preprocessed_artifacts(
        output_dir=output_dir,
        flows=flows,
        machine_counts=machine_counts,
        port_budget=port_budget,
        generic_io_requirements=generic_io_requirements,
    )

    total_machines = sum(machine_counts.values())
    print(f"📊 [推演完成] 制造单位总数: {total_machines} 台")
    print(
        "📊 [I/O 工件] required_generic_outputs="
        f"{generic_io_requirements['required_generic_outputs']}, "
        "required_generic_inputs="
        f"{generic_io_requirements['required_generic_inputs']}"
    )
    print(f"💾 [保存] 工件已写入 {output_dir.relative_to(project_root)}")


if __name__ == "__main__":
    main()
