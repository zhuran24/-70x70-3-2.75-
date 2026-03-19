"""
Topological flow subproblem（拓扑流子问题）.

重要降级说明：
1. 本模块在 exploratory mode（探索模式）中可作为 accelerator（加速器）使用。
2. 在 certified_exact mode（严格认证精确模式）中，本模块只允许作为
   diagnostic（诊断器），不得单独产生正式剪枝证书。
3. 因此它返回的 INFEASIBLE / UNKNOWN 只能被上层按模式解释，
   exact 路径不得把这里的失败直接写成 exact-safe cut（精确安全切平面）。
4. 集成了 Benders Cuts 的提取基础接口。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from ortools.linear_solver import pywraplp

GRID_W = 70
GRID_H = 70


@dataclass
class FlowNetwork:
    """Directed flow network（有向流网络） used by the diagnostic LP（诊断线性规划）."""

    nodes: Set[str] = field(default_factory=set)
    edges: Dict[Tuple[str, str], float] = field(default_factory=dict)
    
    # Track the origin (machine instance) of port nodes to trace back Min-Cut
    port_to_instance: Dict[str, str] = field(default_factory=dict)

    def add_node(self, node_id: str) -> None:
        self.nodes.add(node_id)

    def add_edge(self, u: str, v: str, capacity: float) -> None:
        self.nodes.add(u)
        self.nodes.add(v)
        self.edges[(u, v)] = float(capacity)

    def get_capacity(self, u: str, v: str) -> float:
        return float(self.edges.get((u, v), 0.0))


def cell_id(x: int, y: int) -> str:
    return f"c_{x}_{y}"


def _front_cell(x: int, y: int, direction: str) -> Optional[Tuple[int, int]]:
    if direction == "N":
        return (x, y + 1)
    if direction == "S":
        return (x, y - 1)
    if direction == "E":
        return (x + 1, y)
    if direction == "W":
        return (x - 1, y)
    return None


def build_flow_network(
    occupied_cells: Set[Tuple[int, int]],
    port_dict: Dict[str, List[Dict[str, Any]]],
    commodity_demands: Dict[str, float],
) -> FlowNetwork:
    """Construct a coarse network（构建粗粒度网络） from occupied cells and ports."""

    net = FlowNetwork()

    free_cells: Set[Tuple[int, int]] = set()
    for x in range(GRID_W):
        for y in range(GRID_H):
            if (x, y) not in occupied_cells:
                free_cells.add((x, y))
                net.add_node(cell_id(x, y))

    for (x, y) in free_cells:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if (nx, ny) in free_cells:
                net.add_edge(cell_id(x, y), cell_id(nx, ny), capacity=2.0)

    for commodity, ports in port_dict.items():
        for port in ports:
            px = int(port["x"])
            py = int(port["y"])
            front = _front_cell(px, py, str(port["dir"]))
            if front is None or front not in free_cells:
                continue
            port_node = f"port_{commodity}_{port['instance_id']}_{px}_{py}_{port['type']}"
            net.add_node(port_node)
            net.port_to_instance[port_node] = port["instance_id"]
            
            adj_node = cell_id(front[0], front[1])
            if str(port["type"]) == "out":
                net.add_edge(port_node, adj_node, capacity=1.0)
            else:
                net.add_edge(adj_node, port_node, capacity=1.0)

    for commodity, demand in commodity_demands.items():
        src = f"S_{commodity}"
        snk = f"T_{commodity}"
        net.add_node(src)
        net.add_node(snk)
        if demand <= 0:
            continue
        for port in port_dict.get(commodity, []):
            port_node = f"port_{commodity}_{port['instance_id']}_{int(port['x'])}_{int(port['y'])}_{port['type']}"
            if str(port["type"]) == "out":
                net.add_edge(src, port_node, capacity=1.0)
            else:
                net.add_edge(port_node, snk, capacity=1.0)

    return net


class FlowSubproblem:
    """Continuous multi-commodity flow diagnostic（连续多商品流诊断器）."""

    def __init__(
        self,
        network: FlowNetwork,
        commodity_demands: Dict[str, float],
        *,
        solve_mode: str = "exploratory",
    ):
        self.network = network
        self.demands = {str(k): float(v) for k, v in commodity_demands.items()}
        self.solve_mode = str(solve_mode)
        self.commodities = sorted(self.demands.keys())

        self._solver: Optional[pywraplp.Solver] = None
        self._flow_vars: Dict[Tuple[str, str, str], Any] = {}
        self._status: Optional[str] = None
        self.diagnostics: Dict[str, Any] = {
            "solve_mode": self.solve_mode,
            "commodity_demands": dict(self.demands),
            "warning": (
                "Exploratory accelerator only" if self.solve_mode == "exploratory"
                else "Certified-exact diagnostic only; not a pruning oracle"
            ),
        }
        
        self.bottleneck_instances: Set[str] = set()

    def build_and_solve(self, time_limit_ms: int = 10000) -> str:
        solver = pywraplp.Solver.CreateSolver("GLOP")
        if not solver:
            raise RuntimeError("GLOP solver（GLOP 求解器） is unavailable（不可用）")

        solver.SetTimeLimit(int(time_limit_ms))
        self._solver = solver
        self.bottleneck_instances.clear()

        for (u, v), _cap in self.network.edges.items():
            for commodity in self.commodities:
                self._flow_vars[(u, v, commodity)] = solver.NumVar(
                    0.0,
                    solver.infinity(),
                    f"f_{u}_{v}_{commodity}",
                )

        for commodity in self.commodities:
            demand = float(self.demands[commodity])
            src = f"S_{commodity}"
            snk = f"T_{commodity}"

            src_out = [
                self._flow_vars[(src, v, commodity)]
                for (u, v) in self.network.edges
                if u == src and (src, v, commodity) in self._flow_vars
            ]
            snk_in = [
                self._flow_vars[(u, snk, commodity)]
                for (u, v) in self.network.edges
                if v == snk and (u, snk, commodity) in self._flow_vars
            ]

            if src_out:
                solver.Add(solver.Sum(src_out) == demand)
            elif demand > 0:
                self._status = "INFEASIBLE"
                self.diagnostics["early_infeasible"] = f"missing_source_edges::{commodity}"
                return self._status

            if snk_in:
                solver.Add(solver.Sum(snk_in) == demand)
            elif demand > 0:
                self._status = "INFEASIBLE"
                self.diagnostics["early_infeasible"] = f"missing_sink_edges::{commodity}"
                return self._status

        for node in self.network.nodes:
            if node.startswith("S_") or node.startswith("T_"):
                continue
            for commodity in self.commodities:
                in_vars = [
                    self._flow_vars[(u, node, commodity)]
                    for (u, v) in self.network.edges
                    if v == node and (u, node, commodity) in self._flow_vars
                ]
                out_vars = [
                    self._flow_vars[(node, v, commodity)]
                    for (u, v) in self.network.edges
                    if u == node and (node, v, commodity) in self._flow_vars
                ]
                if in_vars or out_vars:
                    solver.Add(solver.Sum(in_vars) == solver.Sum(out_vars))

        for (u, v), capacity in self.network.edges.items():
            if u.startswith("S_") or u.startswith("T_") or v.startswith("S_") or v.startswith("T_"):
                continue
            vars_on_edge = [
                self._flow_vars[(u, v, commodity)]
                for commodity in self.commodities
                if (u, v, commodity) in self._flow_vars
            ]
            if vars_on_edge:
                solver.Add(solver.Sum(vars_on_edge) <= float(capacity))

        status_code = solver.Solve()
        self.diagnostics["status_code"] = int(status_code)
        self.diagnostics["wall_time_ms"] = solver.wall_time()
        self.diagnostics["iterations"] = solver.iterations()

        if status_code in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
            self._status = "FEASIBLE"
        elif status_code == pywraplp.Solver.INFEASIBLE:
            self._status = "INFEASIBLE"
            self._extract_bottlenecks()
        else:
            self._status = "UNKNOWN"
        return self._status

    def _extract_bottlenecks(self):
        """Extract instances responsible for bottlenecks."""
        # Simple heuristic since GLOP python api doesn't easily expose rays:
        # Just grab instances that have ports in the network as potential blockers.
        for node, instance_id in self.network.port_to_instance.items():
            self.bottleneck_instances.add(instance_id)

    def extract_flow_matrix(self) -> Dict[str, Dict[Tuple[str, str], float]]:
        if self._status != "FEASIBLE":
            return {}

        flows: Dict[str, Dict[Tuple[str, str], float]] = defaultdict(dict)
        for (u, v, commodity), var in self._flow_vars.items():
            value = var.solution_value()
            if value > 1e-8:
                flows[commodity][(u, v)] = value
        return dict(flows)

    def extract_bottleneck_instances(self) -> Set[str]:
        """Return the instances involved in the bottleneck (Min-Cut heuristic)."""
        return self.bottleneck_instances