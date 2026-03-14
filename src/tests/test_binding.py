"""
Tests for the exact port-binding subproblem.
"""

import json
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="session")
def facility_pools(project_root):
    data = json.loads(
        (project_root / "data" / "preprocessed" / "candidate_placements.json").read_text(
            encoding="utf-8"
        )
    )
    return data["facility_pools"]


def test_binding_model_extracts_concrete_port_specs(project_root, facility_pools):
    import sys

    sys.path.insert(0, str(project_root))
    from src.models.binding_subproblem import PortBindingModel

    instances = [
        {
            "instance_id": "packaging_battery_001",
            "facility_type": "manufacturing_6x4",
            "operation_type": "packaging_battery",
            "is_mandatory": True,
        },
        {
            "instance_id": "boundary_port_001",
            "facility_type": "boundary_storage_port",
            "operation_type": "boundary_io",
            "is_mandatory": True,
        },
    ]
    placement_solution = {
        "packaging_battery_001": {
            "pose_idx": 0,
            "pose_id": facility_pools["manufacturing_6x4"][0]["pose_id"],
            "anchor": facility_pools["manufacturing_6x4"][0]["anchor"],
            "facility_type": "manufacturing_6x4",
        },
        "boundary_port_001": {
            "pose_idx": 0,
            "pose_id": facility_pools["boundary_storage_port"][0]["pose_id"],
            "anchor": facility_pools["boundary_storage_port"][0]["anchor"],
            "facility_type": "boundary_storage_port",
        },
    }

    model = PortBindingModel(
        placement_solution,
        facility_pools,
        instances,
        required_generic_outputs={"source_ore": 1, "blue_iron_ore": 0},
        required_generic_inputs={"valley_battery": 0, "qiaoyu_capsule": 0},
    )
    model.build()
    assert model.solve(time_limit_seconds=10.0) == "FEASIBLE"

    port_specs = model.extract_port_specs()
    assert len(port_specs) == 7
    assert sum(1 for p in port_specs if p["type"] == "in") == 5
    assert sum(1 for p in port_specs if p["type"] == "out") == 2
    assert sum(1 for p in port_specs if p["commodity"] == "dense_source_powder") == 3
    assert sum(1 for p in port_specs if p["commodity"] == "steel_part") == 2
    assert sum(1 for p in port_specs if p["commodity"] == "valley_battery") == 1
    assert sum(1 for p in port_specs if p["commodity"] == "source_ore") == 1


def test_binding_model_nogood_cut_forces_new_selection(project_root, facility_pools):
    import sys

    sys.path.insert(0, str(project_root))
    from src.models.binding_subproblem import PortBindingModel

    instances = [
        {
            "instance_id": "packaging_battery_001",
            "facility_type": "manufacturing_6x4",
            "operation_type": "packaging_battery",
            "is_mandatory": True,
        },
        {
            "instance_id": "boundary_port_001",
            "facility_type": "boundary_storage_port",
            "operation_type": "boundary_io",
            "is_mandatory": True,
        },
    ]
    placement_solution = {
        "packaging_battery_001": {
            "pose_idx": 0,
            "pose_id": facility_pools["manufacturing_6x4"][0]["pose_id"],
            "anchor": facility_pools["manufacturing_6x4"][0]["anchor"],
            "facility_type": "manufacturing_6x4",
        },
        "boundary_port_001": {
            "pose_idx": 0,
            "pose_id": facility_pools["boundary_storage_port"][0]["pose_id"],
            "anchor": facility_pools["boundary_storage_port"][0]["anchor"],
            "facility_type": "boundary_storage_port",
        },
    }

    model = PortBindingModel(
        placement_solution,
        facility_pools,
        instances,
        required_generic_outputs={"source_ore": 1, "blue_iron_ore": 0},
        required_generic_inputs={"valley_battery": 0, "qiaoyu_capsule": 0},
    )
    model.build()
    assert model.solve(time_limit_seconds=10.0) == "FEASIBLE"
    first = model.extract_selection()

    model.add_nogood_cut(first)
    assert model.solve(time_limit_seconds=10.0) == "FEASIBLE"
    second = model.extract_selection()

    assert first != second


def test_binding_model_assigns_generic_wireless_sink_inputs(project_root, facility_pools):
    import sys

    sys.path.insert(0, str(project_root))
    from src.models.binding_subproblem import PortBindingModel

    instances = [
        {
            "instance_id": "protocol_box_001",
            "facility_type": "protocol_storage_box",
            "operation_type": "wireless_sink",
            "is_mandatory": False,
        },
    ]
    placement_solution = {
        "protocol_box_001": {
            "pose_idx": 0,
            "pose_id": facility_pools["protocol_storage_box"][0]["pose_id"],
            "anchor": facility_pools["protocol_storage_box"][0]["anchor"],
            "facility_type": "protocol_storage_box",
        },
    }

    model = PortBindingModel(
        placement_solution,
        facility_pools,
        instances,
        required_generic_outputs={"source_ore": 0, "blue_iron_ore": 0},
        required_generic_inputs={"valley_battery": 1, "qiaoyu_capsule": 1},
    )
    model.build()
    assert model.solve(time_limit_seconds=10.0) == "FEASIBLE"

    selection = model.extract_selection()
    assert len(selection["generic_inputs"]) == 3
    assert sum(1 for c in selection["generic_inputs"].values() if c == "valley_battery") == 1
    assert sum(1 for c in selection["generic_inputs"].values() if c == "qiaoyu_capsule") == 1
    assert sum(1 for c in selection["generic_inputs"].values() if c == "__unused__") == 1

    port_specs = model.extract_port_specs()
    sink_specs = [p for p in port_specs if p["instance_id"] == "protocol_box_001" and p["type"] == "in"]
    assert len(sink_specs) == 2
