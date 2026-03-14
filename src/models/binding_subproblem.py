"""
Exact port-binding subproblem.

Given a concrete placement solution, choose one exact commodity-to-port-cell
binding for each fixed-operation instance and assign commodities to the generic
source-output slots provided by boundary ports / protocol core.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ortools.sat.python import cp_model

from src.models.port_binding import (
    enumerate_pose_level_port_bindings,
    supports_exact_pose_level_binding,
)


DEFAULT_GENERIC_SOURCE_REQUIREMENTS = {
    "source_ore": 18,
    "blue_iron_ore": 34,
}

DEFAULT_GENERIC_SINK_REQUIREMENTS = {
    "valley_battery": 1,
    "qiaoyu_capsule": 1,
}


class PortBindingModel:
    """CP-SAT model for exact port-binding selection on a fixed placement."""

    def __init__(
        self,
        placement_solution: Mapping[str, Mapping[str, Any]],
        facility_pools: Mapping[str, List[Dict[str, Any]]],
        instances: Sequence[Mapping[str, Any]],
        required_generic_outputs: Optional[Mapping[str, int]] = None,
        required_generic_inputs: Optional[Mapping[str, int]] = None,
    ):
        self.placement_solution = dict(placement_solution)
        self.facility_pools = facility_pools
        self.instances_by_id = {
            str(inst["instance_id"]): dict(inst)
            for inst in instances
        }
        self.required_generic_outputs = dict(
            required_generic_outputs or DEFAULT_GENERIC_SOURCE_REQUIREMENTS
        )
        self.required_generic_inputs = dict(
            required_generic_inputs or DEFAULT_GENERIC_SINK_REQUIREMENTS
        )

        self.model = cp_model.CpModel()
        self._solver: Optional[cp_model.CpSolver] = None
        self._status = None

        self.binding_domains: Dict[str, List[Dict[str, List[Dict[str, Any]]]]] = {}
        self.binding_vars: Dict[str, Dict[int, Any]] = {}
        self.fixed_binding_choice: Dict[str, int] = {}
        self.generic_output_slots: List[Dict[str, Any]] = []
        self.generic_output_vars: Dict[str, Dict[str, Any]] = {}
        self.generic_input_slots: List[Dict[str, Any]] = []
        self.generic_input_vars: Dict[str, Dict[str, Any]] = {}

    def build(self) -> None:
        self._build_fixed_operation_domains()
        self._build_generic_input_domains()
        self._build_generic_output_domains()
        self._add_generic_input_requirements()
        self._add_generic_output_requirements()

    def _build_fixed_operation_domains(self) -> None:
        for instance_id, sol in self.placement_solution.items():
            inst = self.instances_by_id.get(instance_id)
            if not inst:
                continue

            operation_type = inst.get("operation_type")
            if not operation_type or not supports_exact_pose_level_binding(str(operation_type)):
                continue

            tpl = sol["facility_type"]
            pose = self.facility_pools[tpl][sol["pose_idx"]]
            domains = enumerate_pose_level_port_bindings(str(operation_type), pose)
            if not domains:
                raise ValueError(f"{instance_id} has no legal port-binding domain")

            self.binding_domains[instance_id] = domains
            if len(domains) == 1:
                self.fixed_binding_choice[instance_id] = 0
                continue

            self.binding_vars[instance_id] = {}
            for idx in range(len(domains)):
                self.binding_vars[instance_id][idx] = self.model.NewBoolVar(
                    f"bind_{instance_id}_{idx}"
                )
            self.model.AddExactlyOne(list(self.binding_vars[instance_id].values()))

    def _build_generic_output_domains(self) -> None:
        generic_commodities = sorted(self.required_generic_outputs.keys())

        for instance_id, sol in self.placement_solution.items():
            inst = self.instances_by_id.get(instance_id)
            if not inst:
                continue
            operation_type = str(inst.get("operation_type", ""))
            if operation_type not in {"boundary_io", "protocol_core"}:
                continue

            tpl = sol["facility_type"]
            pose = self.facility_pools[tpl][sol["pose_idx"]]
            for local_idx, port in enumerate(pose.get("output_port_cells", [])):
                slot_id = f"{instance_id}:out:{local_idx}"
                slot = {
                    "slot_id": slot_id,
                    "instance_id": instance_id,
                    "x": int(port["x"]),
                    "y": int(port["y"]),
                    "dir": str(port["dir"]),
                    "type": "out",
                }
                self.generic_output_slots.append(slot)
                self.generic_output_vars[slot_id] = {}
                for commodity in generic_commodities:
                    self.generic_output_vars[slot_id][commodity] = self.model.NewBoolVar(
                        f"slot_{slot_id}_{commodity}"
                    )
                self.model.AddExactlyOne(list(self.generic_output_vars[slot_id].values()))

    def _build_generic_input_domains(self) -> None:
        generic_commodities = sorted(self.required_generic_inputs.keys())
        if not generic_commodities:
            return
        slot_commodities = generic_commodities + ["__unused__"]

        for instance_id, sol in self.placement_solution.items():
            inst = self.instances_by_id.get(instance_id)
            if not inst:
                continue
            operation_type = str(inst.get("operation_type", ""))
            if operation_type != "wireless_sink":
                continue

            tpl = sol["facility_type"]
            pose = self.facility_pools[tpl][sol["pose_idx"]]
            for local_idx, port in enumerate(pose.get("input_port_cells", [])):
                slot_id = f"{instance_id}:in:{local_idx}"
                slot = {
                    "slot_id": slot_id,
                    "instance_id": instance_id,
                    "x": int(port["x"]),
                    "y": int(port["y"]),
                    "dir": str(port["dir"]),
                    "type": "in",
                }
                self.generic_input_slots.append(slot)
                self.generic_input_vars[slot_id] = {}
                for commodity in slot_commodities:
                    self.generic_input_vars[slot_id][commodity] = self.model.NewBoolVar(
                        f"slot_{slot_id}_{commodity}"
                    )
                self.model.AddExactlyOne(list(self.generic_input_vars[slot_id].values()))

    def _add_generic_input_requirements(self) -> None:
        if not self.required_generic_inputs:
            return

        for commodity, required in self.required_generic_inputs.items():
            vars_for_commodity = [
                commodity_vars[commodity]
                for commodity_vars in self.generic_input_vars.values()
                if commodity in commodity_vars
            ]
            if required == 0:
                for var in vars_for_commodity:
                    self.model.Add(var == 0)
                continue
            self.model.Add(sum(vars_for_commodity) == required)

    def _add_generic_output_requirements(self) -> None:
        if not self.required_generic_outputs:
            return

        for commodity, required in self.required_generic_outputs.items():
            vars_for_commodity = [
                commodity_vars[commodity]
                for commodity_vars in self.generic_output_vars.values()
                if commodity in commodity_vars
            ]
            if required == 0:
                for var in vars_for_commodity:
                    self.model.Add(var == 0)
                continue
            self.model.Add(sum(vars_for_commodity) == required)

    def solve(self, time_limit_seconds: float = 30.0) -> str:
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit_seconds
        solver.parameters.num_workers = 4
        status = solver.Solve(self.model)
        self._solver = solver
        self._status = status

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return "FEASIBLE"
        if status == cp_model.INFEASIBLE:
            return "INFEASIBLE"
        return "TIMEOUT"

    def extract_selection(self) -> Dict[str, Any]:
        if self._status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return {}

        selection = {
            "binding_choice": {},
            "generic_inputs": {},
            "generic_outputs": {},
        }

        for instance_id, choice in self.fixed_binding_choice.items():
            selection["binding_choice"][instance_id] = choice

        for instance_id, vars_by_idx in self.binding_vars.items():
            for idx, var in vars_by_idx.items():
                if self._solver.Value(var) == 1:
                    selection["binding_choice"][instance_id] = idx
                    break

        for slot in self.generic_input_slots:
            slot_id = slot["slot_id"]
            for commodity, var in self.generic_input_vars[slot_id].items():
                if self._solver.Value(var) == 1:
                    selection["generic_inputs"][slot_id] = commodity
                    break

        for slot in self.generic_output_slots:
            slot_id = slot["slot_id"]
            for commodity, var in self.generic_output_vars[slot_id].items():
                if self._solver.Value(var) == 1:
                    selection["generic_outputs"][slot_id] = commodity
                    break

        return selection

    def extract_port_specs(self) -> List[Dict[str, Any]]:
        if self._status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return []

        selection = self.extract_selection()
        port_specs: List[Dict[str, Any]] = []

        for instance_id, binding_idx in selection.get("binding_choice", {}).items():
            for side_key in ("input_ports", "output_ports"):
                for port in self.binding_domains[instance_id][binding_idx][side_key]:
                    port_specs.append({
                        "instance_id": instance_id,
                        "x": port["x"],
                        "y": port["y"],
                        "dir": port["dir"],
                        "type": "in" if side_key == "input_ports" else "out",
                        "commodity": port["commodity"],
                    })

        for slot in self.generic_input_slots:
            slot_id = slot["slot_id"]
            commodity = selection["generic_inputs"][slot_id]
            if commodity == "__unused__":
                continue
            port_specs.append({
                "instance_id": slot["instance_id"],
                "x": slot["x"],
                "y": slot["y"],
                "dir": slot["dir"],
                "type": slot["type"],
                "commodity": commodity,
            })

        for slot in self.generic_output_slots:
            slot_id = slot["slot_id"]
            commodity = selection["generic_outputs"][slot_id]
            port_specs.append({
                "instance_id": slot["instance_id"],
                "x": slot["x"],
                "y": slot["y"],
                "dir": slot["dir"],
                "type": slot["type"],
                "commodity": commodity,
            })

        return port_specs

    def add_nogood_cut(self, selection: Mapping[str, Any]) -> None:
        literals = []

        for instance_id, binding_idx in selection.get("binding_choice", {}).items():
            if instance_id in self.binding_vars and binding_idx in self.binding_vars[instance_id]:
                literals.append(self.binding_vars[instance_id][binding_idx])

        for slot_id, commodity in selection.get("generic_inputs", {}).items():
            if slot_id in self.generic_input_vars and commodity in self.generic_input_vars[slot_id]:
                literals.append(self.generic_input_vars[slot_id][commodity])

        for slot_id, commodity in selection.get("generic_outputs", {}).items():
            if slot_id in self.generic_output_vars and commodity in self.generic_output_vars[slot_id]:
                literals.append(self.generic_output_vars[slot_id][commodity])

        if literals:
            self.model.Add(sum(literals) <= len(literals) - 1)
