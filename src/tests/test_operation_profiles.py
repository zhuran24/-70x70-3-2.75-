"""
Tests for canonical operation-level commodity and port-slot profiles.
"""

import json
import math
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def test_operation_profiles_cover_all_instance_operations(project_root):
    import sys

    sys.path.insert(0, str(project_root))
    from src.preprocess.operation_profiles import find_unprofiled_operations

    instances = json.loads(
        (project_root / "data" / "preprocessed" / "all_facility_instances.json").read_text(
            encoding="utf-8"
        )
    )
    assert not find_unprofiled_operations(instances)


def test_aggregated_operation_rates_match_global_flows(project_root):
    import sys

    sys.path.insert(0, str(project_root))
    from src.preprocess.operation_profiles import aggregate_commodity_rates
    from src.preprocess.demand_solver import solve_demands

    data_dir = project_root / "data" / "preprocessed"
    flows = json.loads((data_dir / "commodity_demands.json").read_text(encoding="utf-8"))
    _, machine_loads = solve_demands()

    total_inputs, total_outputs = aggregate_commodity_rates(machine_loads)

    for commodity, demand in flows.items():
        if commodity == "buckwheat":
            assert math.isclose(total_inputs.get(commodity, 0.0), demand * 2.0)
            assert math.isclose(total_outputs.get(commodity, 0.0), demand * 2.0)
            continue
        if commodity == "sandleaf":
            assert math.isclose(total_inputs.get(commodity, 0.0), demand * 2.0)
            assert math.isclose(total_outputs.get(commodity, 0.0), demand * 2.0)
            continue
        observed = max(total_inputs.get(commodity, 0.0), total_outputs.get(commodity, 0.0))
        assert math.isclose(observed, demand), f"{commodity} 的 operation profile 聚合流量失真"

    assert math.isclose(total_inputs["buckwheat_seed"], total_outputs["buckwheat_seed"])
    assert math.isclose(total_inputs["sandleaf_seed"], total_outputs["sandleaf_seed"])
    assert "buckwheat_seed" not in flows
    assert "sandleaf_seed" not in flows


def test_ceiled_machine_capacity_dominates_realized_flows(project_root):
    import sys

    sys.path.insert(0, str(project_root))
    from src.preprocess.operation_profiles import aggregate_commodity_rates

    data_dir = project_root / "data" / "preprocessed"
    machine_counts = json.loads((data_dir / "machine_counts.json").read_text(encoding="utf-8"))
    flows = json.loads((data_dir / "commodity_demands.json").read_text(encoding="utf-8"))

    total_inputs, total_outputs = aggregate_commodity_rates(machine_counts)

    for commodity, demand in flows.items():
        observed = max(total_inputs.get(commodity, 0.0), total_outputs.get(commodity, 0.0))
        assert observed + 1e-9 >= demand, f"{commodity} 的装机容量不应低于目标 realized 流量"


def test_operation_port_slots_respect_template_capacities(project_root):
    import sys

    sys.path.insert(0, str(project_root))
    from src.preprocess.operation_profiles import OPERATION_PORT_PROFILES

    capacities = {
        "manufacturing_3x3": {"input": 3, "output": 3, "generic_input": 0, "generic_output": 0},
        "manufacturing_5x5": {"input": 5, "output": 5, "generic_input": 0, "generic_output": 0},
        "manufacturing_6x4": {"input": 6, "output": 6, "generic_input": 0, "generic_output": 0},
        "protocol_core": {"input": 14, "output": 6, "generic_input": 14, "generic_output": 6},
        "boundary_storage_port": {"input": 0, "output": 1, "generic_input": 0, "generic_output": 1},
        "power_pole": {"input": 0, "output": 0, "generic_input": 0, "generic_output": 0},
        "protocol_storage_box": {"input": 3, "output": 3, "generic_input": 3, "generic_output": 0},
    }

    for profile in OPERATION_PORT_PROFILES.values():
        cap = capacities[profile.facility_type]
        assert sum(profile.input_slots.values()) <= cap["input"]
        assert sum(profile.output_slots.values()) <= cap["output"]
        assert profile.generic_input_slots <= cap["generic_input"]
        assert profile.generic_output_slots <= cap["generic_output"]


def test_generic_source_slots_match_the_52_port_budget(project_root):
    import sys

    sys.path.insert(0, str(project_root))
    from src.preprocess.operation_profiles import aggregate_port_slots, count_operations

    instances = json.loads(
        (project_root / "data" / "preprocessed" / "all_facility_instances.json").read_text(
            encoding="utf-8"
        )
    )
    operation_counts = count_operations(instances, mandatory_only=True)
    slot_summary = aggregate_port_slots(operation_counts)

    assert slot_summary["generic_output_slots"] == 52
    assert slot_summary["generic_input_slots"] == 0
