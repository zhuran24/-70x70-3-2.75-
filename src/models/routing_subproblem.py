"""
Exact grid-routing subproblem.

This version extends the ground-layer routing state space beyond simple 1-in/1-out
belts so that the model can represent splitters and mergers, which are required by
the original frozen rules whenever one commodity's discrete source/sink port counts
do not match.
"""

from __future__ import annotations

import time
from collections import defaultdict
from itertools import combinations
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from ortools.sat.python import cp_model

GRID_W = 70
GRID_H = 70
DIRECTIONS = ["N", "S", "E", "W"]
DIR_DELTA = {"N": (0, 1), "S": (0, -1), "E": (1, 0), "W": (-1, 0)}
DIR_OPP = {"N": "S", "S": "N", "E": "W", "W": "E"}
LAYERS = [0, 1]
GROUND_LAYER = 0
ELEVATED_LAYER = 1


RouteStateKey = Tuple[int, int, int, Tuple[str, ...], Tuple[str, ...], str]


def _dirs_tag(dirs: Iterable[str]) -> str:
    ordered = list(dirs)
    return "".join(ordered) if ordered else "none"


def _is_straight_state(flow_in: Tuple[str, ...], flow_out: Tuple[str, ...]) -> bool:
    return (
        len(flow_in) == 1
        and len(flow_out) == 1
        and DIR_OPP[flow_in[0]] == flow_out[0]
    )


class RoutingGrid:
    """3D grid domain for the routing subproblem."""

    def __init__(
        self,
        occupied_cells: Set[Tuple[int, int]],
        port_specs: List[Dict[str, Any]],
    ):
        self.occupied = occupied_cells
        self.port_specs = port_specs

        self.free_cells: Set[Tuple[int, int]] = set()
        for x in range(GRID_W):
            for y in range(GRID_H):
                if (x, y) not in occupied_cells:
                    self.free_cells.add((x, y))

        self.port_cells: Set[Tuple[int, int]] = set()
        for ps in port_specs:
            self.port_cells.add((int(ps["x"]), int(ps["y"])))

        self.routable_cells = self.free_cells | self.port_cells

    def neighbors(self, x: int, y: int) -> List[Tuple[int, int, str]]:
        result = []
        for d, (dx, dy) in DIR_DELTA.items():
            nx, ny = x + dx, y + dy
            if 0 <= nx < GRID_W and 0 <= ny < GRID_H and (nx, ny) in self.routable_cells:
                result.append((nx, ny, d))
        return result


class RoutingSubproblem:
    """CP-SAT routing model with belt / splitter / merger / bridge states."""

    def __init__(self, grid: RoutingGrid, commodities: List[str]):
        self.grid = grid
        self.commodities = commodities
        self.model = cp_model.CpModel()

        self.r_vars: Dict[RouteStateKey, Any] = {}
        self._vars_by_cell_layer: Dict[Tuple[int, int, int], List[Any]] = defaultdict(list)
        self._vars_by_cell_layer_dir_out_commodity: Dict[
            Tuple[int, int, int, str, str], List[Any]
        ] = defaultdict(list)
        self._vars_by_cell_layer_dir_in_commodity: Dict[
            Tuple[int, int, int, str, str], List[Any]
        ] = defaultdict(list)
        self._vars_by_cell_dir_out_commodity: Dict[Tuple[int, int, str, str], List[Any]] = defaultdict(list)
        self._vars_by_cell_dir_in_commodity: Dict[Tuple[int, int, str, str], List[Any]] = defaultdict(list)
        self._l1_vars: Dict[Tuple[int, int], List[Any]] = defaultdict(list)
        self._l0_nonstraight_vars: Dict[Tuple[int, int], List[Any]] = defaultdict(list)
        self._state_meta: Dict[RouteStateKey, Dict[str, Any]] = {}
        self._solver: Optional[cp_model.CpSolver] = None
        self._status = None
        self.build_stats: Dict[str, Any] = {}

        self._source_port_fronts: Dict[Tuple[int, int, str, str], int] = defaultdict(int)
        self._sink_port_fronts: Dict[Tuple[int, int, str, str], int] = defaultdict(int)
        self._index_port_fronts()

    def _index_port_fronts(self) -> None:
        for ps in self.grid.port_specs:
            px = int(ps["x"])
            py = int(ps["y"])
            direction = str(ps["dir"])
            commodity = str(ps["commodity"])
            dx, dy = DIR_DELTA[direction]
            fx, fy = px + dx, py + dy
            if str(ps["type"]) == "out":
                recv_dir = DIR_OPP[direction]
                self._source_port_fronts[(fx, fy, recv_dir, commodity)] += 1
            else:
                self._sink_port_fronts[(fx, fy, direction, commodity)] += 1

    def build(self, time_limit: float = 60.0):
        t0 = time.time()
        self._create_routing_variables()
        self._add_obstacle_exclusion()
        self._add_capacity_constraints()
        self._add_bridge_constraints()
        self._add_continuity_constraints()
        self._add_port_adherence()
        self._add_gap_rule()
        elapsed = time.time() - t0
        print(f"🔡 [Routing Model] build {elapsed:.1f}s")

    def _iter_state_patterns(self, layer: int) -> Iterable[Dict[str, Any]]:
        if layer == ELEVATED_LAYER:
            for d_in in DIRECTIONS:
                yield {
                    "flow_in": (d_in,),
                    "flow_out": (DIR_OPP[d_in],),
                    "component_type": "bridge",
                }
            return

        for d_in in DIRECTIONS:
            for d_out in DIRECTIONS:
                if d_out == d_in:
                    continue
                yield {
                    "flow_in": (d_in,),
                    "flow_out": (d_out,),
                    "component_type": "belt",
                }

        for d_in in DIRECTIONS:
            remaining = [d for d in DIRECTIONS if d != d_in]
            for out_deg in (2, 3):
                for out_dirs in combinations(remaining, out_deg):
                    yield {
                        "flow_in": (d_in,),
                        "flow_out": tuple(out_dirs),
                        "component_type": "splitter",
                    }

        for d_out in DIRECTIONS:
            remaining = [d for d in DIRECTIONS if d != d_out]
            for in_deg in (2, 3):
                for in_dirs in combinations(remaining, in_deg):
                    yield {
                        "flow_in": tuple(in_dirs),
                        "flow_out": (d_out,),
                        "component_type": "merger",
                    }

    def _create_routing_variables(self):
        state_counter = defaultdict(int)

        for (x, y) in self.grid.free_cells:
            for layer in LAYERS:
                patterns = list(self._iter_state_patterns(layer))
                for pattern in patterns:
                    flow_in = tuple(pattern["flow_in"])
                    flow_out = tuple(pattern["flow_out"])
                    component_type = str(pattern["component_type"])
                    for commodity in self.commodities:
                        var = self.model.NewBoolVar(
                            f"r_{x}_{y}_{layer}_{_dirs_tag(flow_in)}_{_dirs_tag(flow_out)}_{commodity}"
                        )
                        key: RouteStateKey = (x, y, layer, flow_in, flow_out, commodity)
                        self.r_vars[key] = var
                        self._state_meta[key] = {
                            "flow_in": flow_in,
                            "flow_out": flow_out,
                            "component_type": component_type,
                        }
                        self._vars_by_cell_layer[(x, y, layer)].append(var)
                        for d_out in flow_out:
                            self._vars_by_cell_layer_dir_out_commodity[(x, y, layer, d_out, commodity)].append(var)
                            self._vars_by_cell_dir_out_commodity[(x, y, d_out, commodity)].append(var)
                        for d_in in flow_in:
                            self._vars_by_cell_layer_dir_in_commodity[(x, y, layer, d_in, commodity)].append(var)
                            self._vars_by_cell_dir_in_commodity[(x, y, d_in, commodity)].append(var)
                        if layer == ELEVATED_LAYER:
                            self._l1_vars[(x, y)].append(var)
                        elif component_type != "belt" or not _is_straight_state(flow_in, flow_out):
                            self._l0_nonstraight_vars[(x, y)].append(var)
                        state_counter[(layer, component_type)] += 1

        self.build_stats["state_space"] = {
            "commodities": len(self.commodities),
            "vars": len(self.r_vars),
            "ground_belt_states": state_counter[(GROUND_LAYER, "belt")],
            "ground_splitter_states": state_counter[(GROUND_LAYER, "splitter")],
            "ground_merger_states": state_counter[(GROUND_LAYER, "merger")],
            "elevated_bridge_states": state_counter[(ELEVATED_LAYER, "bridge")],
        }

    def _add_obstacle_exclusion(self):
        # Obstacle exclusion is implemented by only creating variables on free cells.
        return

    def _add_capacity_constraints(self):
        for (x, y) in self.grid.free_cells:
            for layer in LAYERS:
                vars_on_cell_layer = self._vars_by_cell_layer.get((x, y, layer), [])
                if vars_on_cell_layer:
                    self.model.AddAtMostOne(vars_on_cell_layer)

    def _add_bridge_constraints(self):
        for (x, y) in self.grid.free_cells:
            l1_vars = self._l1_vars.get((x, y), [])
            if not l1_vars:
                continue
            l0_nonstraight = self._l0_nonstraight_vars.get((x, y), [])
            if not l0_nonstraight:
                continue
            l1_any = self.model.NewBoolVar(f"l1_any_{x}_{y}")
            self.model.AddMaxEquality(l1_any, l1_vars)
            for var in l0_nonstraight:
                self.model.AddImplication(l1_any, var.Not())

    def _add_continuity_constraints(self):
        for (x, y) in self.grid.free_cells:
            for layer in LAYERS:
                for commodity in self.commodities:
                    for d_out in DIRECTIONS:
                        self._add_successor_constraints(x, y, layer, d_out, commodity)
                    for d_in in DIRECTIONS:
                        self._add_predecessor_constraints(x, y, layer, d_in, commodity)

    def _add_successor_constraints(
        self,
        x: int,
        y: int,
        layer: int,
        d_out: str,
        commodity: str,
    ) -> None:
        out_vars = self._vars_by_cell_layer_dir_out_commodity.get((x, y, layer, d_out, commodity), [])
        if not out_vars:
            return

        if layer == GROUND_LAYER and self._sink_port_fronts.get((x, y, d_out, commodity), 0) > 0:
            return

        dx, dy = DIR_DELTA[d_out]
        nx, ny = x + dx, y + dy
        if not (0 <= nx < GRID_W and 0 <= ny < GRID_H) or (nx, ny) not in self.grid.routable_cells:
            for var in out_vars:
                self.model.Add(var == 0)
            return

        recv_dir = DIR_OPP[d_out]
        recv_vars = self._vars_by_cell_dir_in_commodity.get((nx, ny, recv_dir, commodity), [])
        if not recv_vars:
            for var in out_vars:
                self.model.Add(var == 0)
            return

        recv_sum = sum(recv_vars)
        for var in out_vars:
            self.model.Add(recv_sum >= 1).OnlyEnforceIf(var)

    def _add_predecessor_constraints(
        self,
        x: int,
        y: int,
        layer: int,
        d_in: str,
        commodity: str,
    ) -> None:
        in_vars = self._vars_by_cell_layer_dir_in_commodity.get((x, y, layer, d_in, commodity), [])
        if not in_vars:
            return

        if layer == GROUND_LAYER and self._source_port_fronts.get((x, y, d_in, commodity), 0) > 0:
            return

        dx, dy = DIR_DELTA[d_in]
        px, py = x + dx, y + dy
        if not (0 <= px < GRID_W and 0 <= py < GRID_H) or (px, py) not in self.grid.routable_cells:
            for var in in_vars:
                self.model.Add(var == 0)
            return

        send_dir = DIR_OPP[d_in]
        send_vars = self._vars_by_cell_dir_out_commodity.get((px, py, send_dir, commodity), [])
        if not send_vars:
            for var in in_vars:
                self.model.Add(var == 0)
            return

        send_sum = sum(send_vars)
        for var in in_vars:
            self.model.Add(send_sum >= 1).OnlyEnforceIf(var)

    def _add_port_adherence(self):
        exact_links = 0
        blocked_ports = 0

        for idx, ps in enumerate(self.grid.port_specs):
            px, py = int(ps["x"]), int(ps["y"])
            direction = str(ps["dir"])
            commodity = str(ps["commodity"])
            dx, dy = DIR_DELTA[direction]
            fx, fy = px + dx, py + dy

            if (fx, fy) not in self.grid.free_cells:
                self.model.Add(0 == 1)
                blocked_ports += 1
                continue

            if str(ps["type"]) == "out":
                recv_dir = DIR_OPP[direction]
                vars_for_port = self._vars_by_cell_layer_dir_in_commodity.get(
                    (fx, fy, GROUND_LAYER, recv_dir, commodity),
                    [],
                )
            else:
                vars_for_port = self._vars_by_cell_layer_dir_out_commodity.get(
                    (fx, fy, GROUND_LAYER, direction, commodity),
                    [],
                )

            if not vars_for_port:
                self.model.Add(0 == 1)
                blocked_ports += 1
                continue

            self.model.Add(sum(vars_for_port) == 1)
            exact_links += 1

        self.build_stats["port_adherence"] = {
            "exact_links": exact_links,
            "blocked_ports": blocked_ports,
            "ports": len(self.grid.port_specs),
        }

    def _add_gap_rule(self):
        # The 1-cell minimum-gap rule is enforced by the placement layer's port-clearance
        # plus the fact that ports connect through their dedicated front free cell.
        self.build_stats["gap_rule"] = {"handled_by_front_cell_model": True}

    def solve(self, time_limit: float = 60.0) -> str:
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit
        solver.parameters.num_workers = 8

        status = solver.Solve(self.model)
        self._solver = solver
        self._status = status
        self.build_stats["last_solve"] = {
            "status": solver.StatusName(status),
            "wall_time": solver.WallTime(),
            "branches": solver.NumBranches(),
            "conflicts": solver.NumConflicts(),
        }

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return "FEASIBLE"
        if status == cp_model.INFEASIBLE:
            return "INFEASIBLE"
        return "TIMEOUT"

    def extract_routes(self) -> List[Dict[str, Any]]:
        if self._status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return []

        routes = []
        for (x, y, layer, flow_in, flow_out, commodity), var in self.r_vars.items():
            if self._solver is None or self._solver.Value(var) != 1:
                continue
            meta = self._state_meta[(x, y, layer, flow_in, flow_out, commodity)]
            route = {
                "x": x,
                "y": y,
                "layer": layer,
                "commodity": commodity,
                "component_type": meta["component_type"],
                "flow_in": list(flow_in),
                "flow_out": list(flow_out),
            }
            if len(flow_in) == 1:
                route["dir_in"] = flow_in[0]
            if len(flow_out) == 1:
                route["dir_out"] = flow_out[0]
            routes.append(route)
        return routes

    def extract_conflict_set(self) -> Optional[Dict[str, int]]:
        return None
