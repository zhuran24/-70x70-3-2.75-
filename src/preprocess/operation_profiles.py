"""
Canonical operation-level commodity and port-slot profiles.

This module freezes the per-tick input/output commodity rates for every
operation_type that can appear in the instance list. It is the code-level
bridge between demand_solver's backward-chaining math and the future
machine-level port binding / exact routing layers.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import DefaultDict, Dict, Iterable, Mapping, Tuple


EPSILON = 1e-9


@dataclass(frozen=True)
class OperationPortProfile:
    """Per-operation commodity rates and discrete port-slot requirements."""

    operation_type: str
    facility_type: str
    input_rates: Mapping[str, float]
    output_rates: Mapping[str, float]
    generic_input_slots: int = 0
    generic_output_slots: int = 0

    @property
    def input_slots(self) -> Dict[str, int]:
        return {
            commodity: _rate_to_slots(rate)
            for commodity, rate in self.input_rates.items()
        }

    @property
    def output_slots(self) -> Dict[str, int]:
        return {
            commodity: _rate_to_slots(rate)
            for commodity, rate in self.output_rates.items()
        }


def _rate_to_slots(rate: float) -> int:
    """Convert per-tick rate to the exact minimum integer port-slot count."""
    if rate <= 0:
        return 0
    return int(math.ceil(rate - EPSILON))


OPERATION_PORT_PROFILES: Dict[str, OperationPortProfile] = {
    "packaging_battery": OperationPortProfile(
        operation_type="packaging_battery",
        facility_type="manufacturing_6x4",
        input_rates={"dense_source_powder": 3.0, "steel_part": 2.0},
        output_rates={"valley_battery": 0.2},
    ),
    "filling_capsule": OperationPortProfile(
        operation_type="filling_capsule",
        facility_type="manufacturing_6x4",
        input_rates={"fine_buckwheat_powder": 2.0, "steel_bottle": 2.0},
        output_rates={"qiaoyu_capsule": 0.2},
    ),
    "grinder_dense_source": OperationPortProfile(
        operation_type="grinder_dense_source",
        facility_type="manufacturing_6x4",
        input_rates={"source_powder": 2.0, "sandleaf_powder": 1.0},
        output_rates={"dense_source_powder": 1.0},
    ),
    "grinder_fine_buckwheat": OperationPortProfile(
        operation_type="grinder_fine_buckwheat",
        facility_type="manufacturing_6x4",
        input_rates={"buckwheat_powder": 2.0, "sandleaf_powder": 1.0},
        output_rates={"fine_buckwheat_powder": 1.0},
    ),
    "grinder_dense_blue_iron": OperationPortProfile(
        operation_type="grinder_dense_blue_iron",
        facility_type="manufacturing_6x4",
        input_rates={"blue_iron_powder": 2.0, "sandleaf_powder": 1.0},
        output_rates={"dense_blue_iron_powder": 1.0},
    ),
    "planter_buckwheat": OperationPortProfile(
        operation_type="planter_buckwheat",
        facility_type="manufacturing_5x5",
        input_rates={"buckwheat_seed": 1.0},
        output_rates={"buckwheat": 1.0},
    ),
    "planter_sandleaf": OperationPortProfile(
        operation_type="planter_sandleaf",
        facility_type="manufacturing_5x5",
        input_rates={"sandleaf_seed": 1.0},
        output_rates={"sandleaf": 1.0},
    ),
    "seed_collector_buckwheat": OperationPortProfile(
        operation_type="seed_collector_buckwheat",
        facility_type="manufacturing_5x5",
        input_rates={"buckwheat": 1.0},
        output_rates={"buckwheat_seed": 2.0},
    ),
    "seed_collector_sandleaf": OperationPortProfile(
        operation_type="seed_collector_sandleaf",
        facility_type="manufacturing_5x5",
        input_rates={"sandleaf": 1.0},
        output_rates={"sandleaf_seed": 2.0},
    ),
    "parts_maker": OperationPortProfile(
        operation_type="parts_maker",
        facility_type="manufacturing_3x3",
        input_rates={"steel_block": 1.0},
        output_rates={"steel_part": 1.0},
    ),
    "molding_bottle": OperationPortProfile(
        operation_type="molding_bottle",
        facility_type="manufacturing_3x3",
        input_rates={"steel_block": 2.0},
        output_rates={"steel_bottle": 1.0},
    ),
    "refinery_steel": OperationPortProfile(
        operation_type="refinery_steel",
        facility_type="manufacturing_3x3",
        input_rates={"dense_blue_iron_powder": 1.0},
        output_rates={"steel_block": 1.0},
    ),
    "refinery_blue_iron": OperationPortProfile(
        operation_type="refinery_blue_iron",
        facility_type="manufacturing_3x3",
        input_rates={"blue_iron_ore": 1.0},
        output_rates={"blue_iron_block": 1.0},
    ),
    "crusher_source": OperationPortProfile(
        operation_type="crusher_source",
        facility_type="manufacturing_3x3",
        input_rates={"source_ore": 1.0},
        output_rates={"source_powder": 1.0},
    ),
    "crusher_buckwheat": OperationPortProfile(
        operation_type="crusher_buckwheat",
        facility_type="manufacturing_3x3",
        input_rates={"buckwheat": 1.0},
        output_rates={"buckwheat_powder": 2.0},
    ),
    "crusher_sandleaf": OperationPortProfile(
        operation_type="crusher_sandleaf",
        facility_type="manufacturing_3x3",
        input_rates={"sandleaf": 1.0},
        output_rates={"sandleaf_powder": 3.0},
    ),
    "crusher_blue_iron": OperationPortProfile(
        operation_type="crusher_blue_iron",
        facility_type="manufacturing_3x3",
        input_rates={"blue_iron_block": 1.0},
        output_rates={"blue_iron_powder": 1.0},
    ),
    "protocol_core": OperationPortProfile(
        operation_type="protocol_core",
        facility_type="protocol_core",
        input_rates={},
        output_rates={},
        generic_input_slots=0,
        generic_output_slots=6,
    ),
    "boundary_io": OperationPortProfile(
        operation_type="boundary_io",
        facility_type="boundary_storage_port",
        input_rates={},
        output_rates={},
        generic_output_slots=1,
    ),
    "power_supply": OperationPortProfile(
        operation_type="power_supply",
        facility_type="power_pole",
        input_rates={},
        output_rates={},
    ),
    "wireless_sink": OperationPortProfile(
        operation_type="wireless_sink",
        facility_type="protocol_storage_box",
        input_rates={},
        output_rates={},
        generic_input_slots=3,
    ),
}


def get_operation_port_profile(operation_type: str) -> OperationPortProfile:
    return OPERATION_PORT_PROFILES[operation_type]


def find_unprofiled_operations(instances: Iterable[Mapping[str, object]]) -> Tuple[str, ...]:
    return tuple(sorted({
        str(inst["operation_type"])
        for inst in instances
        if "operation_type" in inst
        and str(inst["operation_type"]) not in OPERATION_PORT_PROFILES
    }))


def count_operations(
    instances: Iterable[Mapping[str, object]],
    mandatory_only: bool = False,
) -> Counter:
    counts: Counter = Counter()
    for inst in instances:
        if mandatory_only and not inst.get("is_mandatory"):
            continue
        operation_type = inst.get("operation_type")
        if operation_type:
            counts[str(operation_type)] += 1
    return counts


def aggregate_commodity_rates(
    operation_counts: Mapping[str, float],
) -> Tuple[Dict[str, float], Dict[str, float]]:
    total_inputs: DefaultDict[str, float] = defaultdict(float)
    total_outputs: DefaultDict[str, float] = defaultdict(float)

    for operation_type, count in operation_counts.items():
        profile = OPERATION_PORT_PROFILES.get(operation_type)
        if not profile:
            continue
        for commodity, rate in profile.input_rates.items():
            total_inputs[commodity] += rate * count
        for commodity, rate in profile.output_rates.items():
            total_outputs[commodity] += rate * count

    return dict(total_inputs), dict(total_outputs)


def aggregate_port_slots(operation_counts: Mapping[str, int]) -> Dict[str, object]:
    input_slots: DefaultDict[str, int] = defaultdict(int)
    output_slots: DefaultDict[str, int] = defaultdict(int)
    generic_input_slots = 0
    generic_output_slots = 0

    for operation_type, count in operation_counts.items():
        profile = OPERATION_PORT_PROFILES.get(operation_type)
        if not profile:
            continue
        for commodity, slots in profile.input_slots.items():
            input_slots[commodity] += slots * count
        for commodity, slots in profile.output_slots.items():
            output_slots[commodity] += slots * count
        generic_input_slots += profile.generic_input_slots * count
        generic_output_slots += profile.generic_output_slots * count

    return {
        "input_slots": dict(input_slots),
        "output_slots": dict(output_slots),
        "generic_input_slots": generic_input_slots,
        "generic_output_slots": generic_output_slots,
    }
