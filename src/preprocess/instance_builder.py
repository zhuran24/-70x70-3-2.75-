"""
Global Instance Builder（全局实例构建器）.

本模块把 demand solver（需求求解器）输出的机器数量转成三类工件：
1. mandatory_exact_instances.json（严格精确必选实例）
2. exploratory_optional_caps.json（探索模式经验上限）
3. all_facility_instances.json（探索兼容全集，明确降级为兼容工件）

严格精确路径只允许读取 mandatory_exact_instances.json；
不允许再把 all_facility_instances.json 里的 provisional（临时经验上限）实例
误当成 certified exact（严格认证精确）输入。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

TEMPLATE_MAPPING = {
    "packaging_battery": "manufacturing_6x4",
    "filling_capsule": "manufacturing_6x4",
    "grinder_dense_source": "manufacturing_6x4",
    "grinder_fine_buckwheat": "manufacturing_6x4",
    "grinder_dense_blue_iron": "manufacturing_6x4",
    "planter_buckwheat": "manufacturing_5x5",
    "planter_sandleaf": "manufacturing_5x5",
    "seed_collector_buckwheat": "manufacturing_5x5",
    "seed_collector_sandleaf": "manufacturing_5x5",
    "parts_maker": "manufacturing_3x3",
    "molding_bottle": "manufacturing_3x3",
    "refinery_steel": "manufacturing_3x3",
    "refinery_blue_iron": "manufacturing_3x3",
    "crusher_source": "manufacturing_3x3",
    "crusher_buckwheat": "manufacturing_3x3",
    "crusher_sandleaf": "manufacturing_3x3",
    "crusher_blue_iron": "manufacturing_3x3",
}

EXPLORATORY_OPTIONAL_CAPS = {
    "power_pole": {
        "cap": 50,
        "bound_type": "provisional",
        "operation_type": "power_supply",
        "notes": "经验上限，仅探索模式可用。",
    },
    "protocol_storage_box": {
        "cap": 10,
        "bound_type": "provisional",
        "operation_type": "wireless_sink",
        "notes": "经验上限，仅探索模式可用。",
    },
}


def build_manufacturing_instances(counts: Mapping[str, int]) -> List[Dict[str, Any]]:
    instances: List[Dict[str, Any]] = []
    for operation_type, count in sorted(counts.items()):
        template = TEMPLATE_MAPPING.get(operation_type)
        if template is None:
            raise ValueError(f"未知 operation_type（操作类型）: {operation_type}")
        for index in range(1, int(count) + 1):
            instances.append(
                {
                    "instance_id": f"{operation_type}_{index:03d}",
                    "facility_type": template,
                    "operation_type": operation_type,
                    "is_mandatory": True,
                    "bound_type": "exact",
                    "solve_modes": ["certified_exact", "exploratory"],
                    "notes": "由配方矩阵严格推导出的强制制造实例。",
                }
            )
    return instances



def build_core_instance() -> List[Dict[str, Any]]:
    return [
        {
            "instance_id": "protocol_core_001",
            "facility_type": "protocol_core",
            "operation_type": "protocol_core",
            "is_mandatory": True,
            "bound_type": "exact",
            "solve_modes": ["certified_exact", "exploratory"],
            "notes": "唯一协议核心，属于严格精确必选实体。",
        }
    ]



def build_boundary_ports(count: int = 46) -> List[Dict[str, Any]]:
    return [
        {
            "instance_id": f"boundary_port_{index:03d}",
            "facility_type": "boundary_storage_port",
            "operation_type": "boundary_io",
            "is_mandatory": True,
            "bound_type": "exact",
            "solve_modes": ["certified_exact", "exploratory"],
            "notes": "贴左/下基线的强制原生仓库口。",
        }
        for index in range(1, count + 1)
    ]



def build_exploratory_optional_instances(
    caps: Mapping[str, Mapping[str, Any]] = EXPLORATORY_OPTIONAL_CAPS,
) -> List[Dict[str, Any]]:
    instances: List[Dict[str, Any]] = []
    for facility_type, spec in caps.items():
        cap = int(spec["cap"])
        prefix = "power_pole" if facility_type == "power_pole" else "protocol_box"
        for index in range(1, cap + 1):
            instances.append(
                {
                    "instance_id": f"{prefix}_{index:03d}",
                    "facility_type": facility_type,
                    "operation_type": str(spec["operation_type"]),
                    "is_mandatory": False,
                    "bound_type": str(spec["bound_type"]),
                    "solve_modes": ["exploratory"],
                    "notes": str(spec["notes"]),
                }
            )
    return instances



def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)



def audit_instances(instances: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
    stats = {
        "total": 0,
        "mandatory_exact": 0,
        "optional_provisional": 0,
    }
    for instance in instances:
        stats["total"] += 1
        if bool(instance.get("is_mandatory")) and instance.get("bound_type") == "exact":
            stats["mandatory_exact"] += 1
        if (not bool(instance.get("is_mandatory"))) and instance.get("bound_type") == "provisional":
            stats["optional_provisional"] += 1
    return stats



def main() -> None:
    print("🚀 [预处理] 启动 Global Instance Builder（全局实例构建器）...")

    project_root = Path(__file__).resolve().parent.parent.parent
    data_dir = project_root / "data" / "preprocessed"
    counts_path = data_dir / "machine_counts.json"
    if not counts_path.exists():
        raise FileNotFoundError(f"缺少 {counts_path}；请先运行 demand_solver.py")

    machine_counts = json.loads(counts_path.read_text(encoding="utf-8"))

    mandatory_exact_instances = (
        build_manufacturing_instances(machine_counts)
        + build_core_instance()
        + build_boundary_ports(46)
    )
    exploratory_optional_instances = build_exploratory_optional_instances()
    all_facility_instances = mandatory_exact_instances + exploratory_optional_instances

    save_json(data_dir / "mandatory_exact_instances.json", mandatory_exact_instances)
    save_json(data_dir / "exploratory_optional_caps.json", EXPLORATORY_OPTIONAL_CAPS)
    save_json(data_dir / "all_facility_instances.json", all_facility_instances)

    stats = audit_instances(all_facility_instances)
    print(
        "📊 [审计] mandatory_exact="
        f"{stats['mandatory_exact']}, optional_provisional={stats['optional_provisional']}, total={stats['total']}"
    )
    print(f"💾 [保存] 工件已写入 {data_dir.relative_to(project_root)}")


if __name__ == "__main__":
    main()
