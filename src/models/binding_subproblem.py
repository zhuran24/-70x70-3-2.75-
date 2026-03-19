"""
Exact port-binding subproblem（精确端口绑定子问题）.

职责：
1. 对固定摆放解选择 exact pose-level binding（精确位姿级端口绑定）。
2. 从预处理工件 generic_io_requirements.json（通用 I/O 需求工件）读取默认需求，
   不再在模型内部长期硬编码默认值。
3. 识别 pose_optional::...（位姿级可选设施）合成实例，尤其是
   protocol_storage_box（协议储存箱）与 power_pole（供电桩）。
4. 输出可持久化的 conflict summary（冲突摘要），供 exact campaign（精确战役）写盘。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ortools.sat.python import cp_model

from src.models.port_binding import (
    enumerate_pose_level_port_bindings_with_cache_info,
    supports_exact_pose_level_binding,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
GENERIC_IO_REQUIREMENTS_PATH = (
    PROJECT_ROOT / "data" / "preprocessed" / "generic_io_requirements.json"
)

POSE_OPTIONAL_OPERATION_BY_TEMPLATE = {
    "protocol_storage_box": "wireless_sink",
    "power_pole": "power_supply",
}



def load_generic_io_requirements(
    *,
    project_root: Optional[Path] = None,
    path: Optional[Path] = None,
) -> Dict[str, Dict[str, int]]:
    """Load generic I/O requirements（加载通用 I/O 需求）.

    Returns:
        {
            "required_generic_outputs": {...},
            "required_generic_inputs": {...},
        }
    """

    if path is None:
        root = project_root or PROJECT_ROOT
        path = root / "data" / "preprocessed" / "generic_io_requirements.json"

    if not path.exists():
        raise FileNotFoundError(
            f"Missing generic_io_requirements artifact（缺少通用 I/O 需求工件）: {path}"
        )

    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "required_generic_outputs": {
            str(k): int(v)
            for k, v in dict(payload.get("required_generic_outputs", {})).items()
        },
        "required_generic_inputs": {
            str(k): int(v)
            for k, v in dict(payload.get("required_generic_inputs", {})).items()
        },
    }


class PortBindingModel:
    """CP-SAT model（CP-SAT 模型）for exact port binding（精确端口绑定）."""

    def __init__(
        self,
        placement_solution: Mapping[str, Mapping[str, Any]],
        facility_pools: Mapping[str, List[Dict[str, Any]]],
        instances: Sequence[Mapping[str, Any]],
        required_generic_outputs: Optional[Mapping[str, int]] = None,
        required_generic_inputs: Optional[Mapping[str, int]] = None,
        project_root: Optional[Path] = None,
        io_requirements_path: Optional[Path] = None,
    ):
        self.project_root = project_root or PROJECT_ROOT
        self.io_requirements_path = io_requirements_path
        self.placement_solution = {
            str(instance_id): dict(sol)
            for instance_id, sol in placement_solution.items()
        }
        self.facility_pools = {tpl: list(pool) for tpl, pool in facility_pools.items()}
        self.instances_by_id = {
            str(inst["instance_id"]): dict(inst)
            for inst in instances
        }

        if required_generic_outputs is None or required_generic_inputs is None:
            io_requirements = load_generic_io_requirements(
                project_root=self.project_root,
                path=self.io_requirements_path,
            )
        else:
            io_requirements = {
                "required_generic_outputs": {},
                "required_generic_inputs": {},
            }

        self.required_generic_outputs = {
            str(k): int(v)
            for k, v in (
                required_generic_outputs
                if required_generic_outputs is not None
                else io_requirements["required_generic_outputs"]
            ).items()
        }
        self.required_generic_inputs = {
            str(k): int(v)
            for k, v in (
                required_generic_inputs
                if required_generic_inputs is not None
                else io_requirements["required_generic_inputs"]
            ).items()
        }

        self.model = cp_model.CpModel()
        self._solver: Optional[cp_model.CpSolver] = None
        self._status: Optional[int] = None
        self._conflict_summary: Dict[str, Any] = {
            "placement_instances": sorted(self.placement_solution.keys()),
            "synthesized_instances": [],
            "missing_instance_ids": [],
            "binding_domains": {},
            "empty_binding_domain_instances": [],
            "binding_domain_cache_hits": 0,
            "binding_domain_cache_misses": 0,
            "binding_domain_reused_instances": [],
            "required_generic_outputs": dict(self.required_generic_outputs),
            "required_generic_inputs": dict(self.required_generic_inputs),
        }

        self.binding_domains: Dict[str, List[Dict[str, List[Dict[str, Any]]]]] = {}
        self.binding_vars: Dict[str, Dict[int, Any]] = {}
        self.fixed_binding_choice: Dict[str, int] = {}
        self.empty_binding_domain_instances: List[Dict[str, Any]] = []
        self.generic_output_slots: List[Dict[str, Any]] = []
        self.generic_output_vars: Dict[str, Dict[str, Any]] = {}
        self.generic_input_slots: List[Dict[str, Any]] = []
        self.generic_input_vars: Dict[str, Dict[str, Any]] = {}
        self.binding_domain_cache_hits = 0
        self.binding_domain_cache_misses = 0
        self.binding_domain_reused_instances: List[str] = []

        self._materialize_pose_optional_instances()

    def _materialize_pose_optional_instances(self) -> None:
        synthesized: List[str] = []
        missing: List[str] = []

        for instance_id, sol in self.placement_solution.items():
            if instance_id in self.instances_by_id:
                continue

            facility_type = str(sol.get("facility_type", ""))
            operation_type = POSE_OPTIONAL_OPERATION_BY_TEMPLATE.get(facility_type)
            if operation_type is None and instance_id.startswith("pose_optional::"):
                _, inferred_tpl, *_rest = instance_id.split("::")
                operation_type = POSE_OPTIONAL_OPERATION_BY_TEMPLATE.get(inferred_tpl)
                if operation_type is not None:
                    facility_type = inferred_tpl

            if operation_type is None:
                missing.append(instance_id)
                continue

            self.instances_by_id[instance_id] = {
                "instance_id": instance_id,
                "facility_type": facility_type,
                "operation_type": operation_type,
                "is_mandatory": False,
                "bound_type": str(sol.get("bound_type", "exact_pose_optional")),
                "solve_mode": str(sol.get("solve_mode", "unknown")),
            }
            synthesized.append(instance_id)

        self._conflict_summary["synthesized_instances"] = synthesized
        self._conflict_summary["missing_instance_ids"] = missing

    def build(self) -> None:
        self._build_fixed_operation_domains()
        self._build_generic_input_domains()
        self._build_generic_output_domains()
        self._add_generic_input_requirements()
        self._add_generic_output_requirements()
        if self.empty_binding_domain_instances:
            self.model.Add(0 == 1)
        self._add_search_guidance()
        self._conflict_summary["generic_output_slot_count"] = len(self.generic_output_slots)
        self._conflict_summary["generic_input_slot_count"] = len(self.generic_input_slots)

    def _resolve_instance(self, instance_id: str) -> Optional[Dict[str, Any]]:
        inst = self.instances_by_id.get(instance_id)
        if inst is not None:
            return inst
        self._conflict_summary.setdefault("missing_instance_ids", []).append(instance_id)
        return None

    def _resolve_pose(self, facility_type: str, pose_idx: int) -> Dict[str, Any]:
        pool = self.facility_pools.get(facility_type, [])
        if pose_idx < 0 or pose_idx >= len(pool):
            raise IndexError(
                f"Pose index（位姿索引） out of range（越界）: {facility_type}[{pose_idx}]"
            )
        return pool[pose_idx]

    def _build_fixed_operation_domains(self) -> None:
        for instance_id, sol in self.placement_solution.items():
            inst = self._resolve_instance(instance_id)
            if not inst:
                continue

            operation_type = str(inst.get("operation_type", ""))
            if not operation_type or not supports_exact_pose_level_binding(operation_type):
                continue

            tpl = str(sol["facility_type"])
            pose = self._resolve_pose(tpl, int(sol["pose_idx"]))
            domains, cache_hit = enumerate_pose_level_port_bindings_with_cache_info(
                operation_type,
                pose,
            )
            if cache_hit:
                self.binding_domain_cache_hits += 1
                self.binding_domain_reused_instances.append(instance_id)
            else:
                self.binding_domain_cache_misses += 1
            if not domains:
                empty_domain = {
                    "instance_id": instance_id,
                    "facility_type": tpl,
                    "operation_type": operation_type,
                    "pose_idx": int(sol["pose_idx"]),
                    "pose_id": str(pose.get("pose_id", "")),
                }
                self.empty_binding_domain_instances.append(empty_domain)
                self._conflict_summary["binding_domains"][instance_id] = 0
                continue

            self.binding_domains[instance_id] = domains
            self._conflict_summary["binding_domains"][instance_id] = len(domains)
            if len(domains) == 1:
                self.fixed_binding_choice[instance_id] = 0
                continue

            self.binding_vars[instance_id] = {}
            for idx in range(len(domains)):
                self.binding_vars[instance_id][idx] = self.model.NewBoolVar(
                    f"bind_{instance_id}_{idx}"
                )
            self.model.AddExactlyOne(list(self.binding_vars[instance_id].values()))
        self._conflict_summary["binding_domain_cache_hits"] = int(self.binding_domain_cache_hits)
        self._conflict_summary["binding_domain_cache_misses"] = int(self.binding_domain_cache_misses)
        self._conflict_summary["binding_domain_reused_instances"] = list(
            self.binding_domain_reused_instances
        )

    def _build_generic_output_domains(self) -> None:
        generic_commodities = sorted(self.required_generic_outputs.keys())
        if not generic_commodities:
            return

        for instance_id, sol in self.placement_solution.items():
            inst = self._resolve_instance(instance_id)
            if not inst:
                continue
            operation_type = str(inst.get("operation_type", ""))
            if operation_type not in {"boundary_io", "protocol_core"}:
                continue

            tpl = str(sol["facility_type"])
            pose = self._resolve_pose(tpl, int(sol["pose_idx"]))
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
            inst = self._resolve_instance(instance_id)
            if not inst:
                continue
            operation_type = str(inst.get("operation_type", ""))
            if operation_type != "wireless_sink":
                continue

            tpl = str(sol["facility_type"])
            pose = self._resolve_pose(tpl, int(sol["pose_idx"]))
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

    def _ordered_generic_slot_commodities(
        self,
        commodity_vars: Mapping[str, Any],
    ) -> List[str]:
        return sorted(
            commodity_vars,
            key=lambda commodity: (
                str(commodity) == "__unused__",
                str(commodity),
            ),
        )

    def _add_search_guidance(self) -> None:
        binding_literals = 0
        generic_input_literals = 0
        generic_output_literals = 0

        for instance_id in sorted(self.binding_vars):
            ordered_vars = [
                self.binding_vars[instance_id][idx]
                for idx in sorted(self.binding_vars[instance_id])
            ]
            if not ordered_vars:
                continue
            self.model.AddDecisionStrategy(
                ordered_vars,
                cp_model.CHOOSE_FIRST,
                cp_model.SELECT_MAX_VALUE,
            )
            binding_literals += len(ordered_vars)

        for slot_id in sorted(self.generic_input_vars):
            ordered_vars = [
                self.generic_input_vars[slot_id][commodity]
                for commodity in self._ordered_generic_slot_commodities(
                    self.generic_input_vars[slot_id]
                )
            ]
            if not ordered_vars:
                continue
            self.model.AddDecisionStrategy(
                ordered_vars,
                cp_model.CHOOSE_FIRST,
                cp_model.SELECT_MAX_VALUE,
            )
            generic_input_literals += len(ordered_vars)

        for slot_id in sorted(self.generic_output_vars):
            ordered_vars = [
                self.generic_output_vars[slot_id][commodity]
                for commodity in self._ordered_generic_slot_commodities(
                    self.generic_output_vars[slot_id]
                )
            ]
            if not ordered_vars:
                continue
            self.model.AddDecisionStrategy(
                ordered_vars,
                cp_model.CHOOSE_FIRST,
                cp_model.SELECT_MAX_VALUE,
            )
            generic_output_literals += len(ordered_vars)

        self._conflict_summary["search_guidance"] = {
            "applied": bool(
                binding_literals or generic_input_literals or generic_output_literals
            ),
            "profile": "exact_binding_guided_branching_v1",
            "search_branching": "FIXED_SEARCH",
            "binding_literals": int(binding_literals),
            "generic_input_literals": int(generic_input_literals),
            "generic_output_literals": int(generic_output_literals),
        }

    def solve(self, time_limit_seconds: float = 30.0) -> str:
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(time_limit_seconds)
        solver.parameters.num_workers = 4
        solver.parameters.search_branching = cp_model.FIXED_SEARCH
        solver.parameters.symmetry_level = max(int(solver.parameters.symmetry_level), 3)
        solver.parameters.cp_model_probing_level = max(
            int(solver.parameters.cp_model_probing_level),
            3,
        )
        status = solver.Solve(self.model)
        self._solver = solver
        self._status = status

        self._conflict_summary["solver_status"] = solver.StatusName(status)
        self._conflict_summary["wall_time"] = solver.WallTime()
        self._conflict_summary["search_profile"] = str(
            self._conflict_summary.get("search_guidance", {}).get(
                "profile",
                "exact_binding_guided_branching_v1",
            )
        )
        self._conflict_summary["search_branching"] = str(solver.parameters.search_branching)

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
                if self._solver is not None and self._solver.Value(var) == 1:
                    selection["binding_choice"][instance_id] = idx
                    break

        for slot in self.generic_input_slots:
            slot_id = slot["slot_id"]
            for commodity, var in self.generic_input_vars[slot_id].items():
                if self._solver is not None and self._solver.Value(var) == 1:
                    selection["generic_inputs"][slot_id] = commodity
                    break

        for slot in self.generic_output_slots:
            slot_id = slot["slot_id"]
            for commodity, var in self.generic_output_vars[slot_id].items():
                if self._solver is not None and self._solver.Value(var) == 1:
                    selection["generic_outputs"][slot_id] = commodity
                    break

        return selection

    def extract_port_specs(self) -> List[Dict[str, Any]]:
        if self._status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return []

        selection = self.extract_selection()
        port_specs: List[Dict[str, Any]] = []

        for instance_id, binding_idx in selection.get("binding_choice", {}).items():
            domain = self.binding_domains.get(instance_id, [])
            if binding_idx < 0 or binding_idx >= len(domain):
                continue
            for side_key in ("input_ports", "output_ports"):
                for port in domain[binding_idx][side_key]:
                    port_specs.append(
                        {
                            "instance_id": instance_id,
                            "x": int(port["x"]),
                            "y": int(port["y"]),
                            "dir": str(port["dir"]),
                            "type": "in" if side_key == "input_ports" else "out",
                            "commodity": str(port["commodity"]),
                        }
                    )

        for slot in self.generic_input_slots:
            slot_id = slot["slot_id"]
            commodity = selection["generic_inputs"].get(slot_id)
            if commodity in (None, "__unused__"):
                continue
            port_specs.append(
                {
                    "instance_id": slot["instance_id"],
                    "x": slot["x"],
                    "y": slot["y"],
                    "dir": slot["dir"],
                    "type": slot["type"],
                    "commodity": commodity,
                }
            )

        for slot in self.generic_output_slots:
            slot_id = slot["slot_id"]
            commodity = selection["generic_outputs"].get(slot_id)
            if commodity is None:
                continue
            port_specs.append(
                {
                    "instance_id": slot["instance_id"],
                    "x": slot["x"],
                    "y": slot["y"],
                    "dir": slot["dir"],
                    "type": slot["type"],
                    "commodity": commodity,
                }
            )

        return port_specs

    def extract_conflict_summary(self) -> Dict[str, Any]:
        summary = dict(self._conflict_summary)
        summary["binding_domain_count"] = sum(len(v) for v in self.binding_domains.values())
        summary["binding_instance_count"] = len(self.binding_domains)
        summary["empty_binding_domain_count"] = len(self.empty_binding_domain_instances)
        summary["empty_binding_domain_instances"] = self.extract_empty_binding_domain_instances()
        summary["binding_domain_cache_hits"] = int(self.binding_domain_cache_hits)
        summary["binding_domain_cache_misses"] = int(self.binding_domain_cache_misses)
        summary["binding_domain_reused_instances"] = list(self.binding_domain_reused_instances)
        summary["selection"] = self.extract_selection() if self._status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else {}
        return summary

    def extract_empty_binding_domain_instances(self) -> List[Dict[str, Any]]:
        return [dict(item) for item in self.empty_binding_domain_instances]

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
