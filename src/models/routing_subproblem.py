"""
Exact grid-routing subproblem.

This version keeps the exact state semantics, but shrinks the routing core to the
commodity-scoped terminal-connected domain before building CP-SAT variables.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from itertools import combinations
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

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


@dataclass
class RoutingPlacementCore:
    occupied_cells: Set[Tuple[int, int]]
    occupied_owner_by_cell: Dict[Tuple[int, int], str]
    free_cells: Set[Tuple[int, int]]
    free_neighbors_by_cell: Dict[Tuple[int, int], Tuple[Tuple[int, int], ...]]
    component_by_cell: Dict[Tuple[int, int], int]
    cells_by_component: Dict[int, Set[Tuple[int, int]]]

    @classmethod
    def from_occupied_cells(
        cls,
        occupied_cells: Set[Tuple[int, int]],
        *,
        occupied_owner_by_cell: Optional[Mapping[Tuple[int, int], str]] = None,
    ) -> "RoutingPlacementCore":
        occupied = {(int(x), int(y)) for x, y in occupied_cells}
        owner_map = {
            (int(cell[0]), int(cell[1])): str(owner)
            for cell, owner in dict(occupied_owner_by_cell or {}).items()
        }
        free_cells: Set[Tuple[int, int]] = set()
        for x in range(GRID_W):
            for y in range(GRID_H):
                if (x, y) not in occupied:
                    free_cells.add((x, y))

        free_neighbors_by_cell = {
            cell: tuple(
                sorted(
                    neighbor
                    for neighbor in _cell_neighbors(cell)
                    if neighbor in free_cells
                )
            )
            for cell in free_cells
        }
        component_by_cell, cells_by_component = _compute_free_components(
            free_cells,
            free_neighbors_by_cell=free_neighbors_by_cell,
        )
        return cls(
            occupied_cells=occupied,
            occupied_owner_by_cell=owner_map,
            free_cells=free_cells,
            free_neighbors_by_cell=free_neighbors_by_cell,
            component_by_cell=component_by_cell,
            cells_by_component=cells_by_component,
        )


def _dirs_tag(dirs: Iterable[str]) -> str:
    ordered = list(dirs)
    return "".join(ordered) if ordered else "none"


def _is_straight_state(flow_in: Tuple[str, ...], flow_out: Tuple[str, ...]) -> bool:
    return (
        len(flow_in) == 1
        and len(flow_out) == 1
        and DIR_OPP[flow_in[0]] == flow_out[0]
    )


def _sorted_cells(cells: Iterable[Tuple[int, int]]) -> List[List[int]]:
    return [[int(x), int(y)] for x, y in sorted(cells)]


def _cell_neighbors(cell: Tuple[int, int]) -> List[Tuple[int, int]]:
    x, y = cell
    neighbors: List[Tuple[int, int]] = []
    for dx, dy in DIR_DELTA.values():
        nx, ny = x + dx, y + dy
        if 0 <= nx < GRID_W and 0 <= ny < GRID_H:
            neighbors.append((nx, ny))
    return neighbors


def _compute_free_components(
    free_cells: Set[Tuple[int, int]],
    *,
    free_neighbors_by_cell: Optional[Mapping[Tuple[int, int], Sequence[Tuple[int, int]]]] = None,
) -> Tuple[Dict[Tuple[int, int], int], Dict[int, Set[Tuple[int, int]]]]:
    component_by_cell: Dict[Tuple[int, int], int] = {}
    cells_by_component: Dict[int, Set[Tuple[int, int]]] = {}
    component_id = 0

    for cell in free_cells:
        if cell in component_by_cell:
            continue
        stack = [cell]
        component_by_cell[cell] = component_id
        component_cells: Set[Tuple[int, int]] = {cell}
        while stack:
            current = stack.pop()
            neighbors = (
                free_neighbors_by_cell.get(current, ())
                if free_neighbors_by_cell is not None
                else _cell_neighbors(current)
            )
            for neighbor in neighbors:
                if neighbor not in free_cells or neighbor in component_by_cell:
                    continue
                component_by_cell[neighbor] = component_id
                component_cells.add(neighbor)
                stack.append(neighbor)
        cells_by_component[component_id] = component_cells
        component_id += 1

    return component_by_cell, cells_by_component


def _peel_terminal_core(
    component_cells: Set[Tuple[int, int]],
    terminal_cells: Set[Tuple[int, int]],
    *,
    free_neighbors_by_cell: Optional[Mapping[Tuple[int, int], Sequence[Tuple[int, int]]]] = None,
) -> Set[Tuple[int, int]]:
    if not component_cells:
        return set()

    neighbor_map: Dict[Tuple[int, int], Set[Tuple[int, int]]] = {}
    degree: Dict[Tuple[int, int], int] = {}
    for cell in component_cells:
        base_neighbors = (
            free_neighbors_by_cell.get(cell, ())
            if free_neighbors_by_cell is not None
            else _cell_neighbors(cell)
        )
        neighbors = {neighbor for neighbor in base_neighbors if neighbor in component_cells}
        neighbor_map[cell] = neighbors
        degree[cell] = len(neighbors)

    removed: Set[Tuple[int, int]] = set()
    queue = deque(
        cell
        for cell in component_cells
        if cell not in terminal_cells and degree.get(cell, 0) < 2
    )
    while queue:
        cell = queue.popleft()
        if cell in removed or cell in terminal_cells:
            continue
        if degree.get(cell, 0) >= 2:
            continue
        removed.add(cell)
        for neighbor in neighbor_map.get(cell, set()):
            if neighbor in removed:
                continue
            degree[neighbor] = degree.get(neighbor, 0) - 1
            if neighbor not in terminal_cells and degree.get(neighbor, 0) < 2:
                queue.append(neighbor)

    return {cell for cell in component_cells if cell not in removed}


def _empty_domain_stats() -> Dict[str, Any]:
    return {
        "commodity_component_cells": {},
        "commodity_active_cells": {},
        "commodity_terminal_cells": {},
        "domain_cells": 0,
        "terminal_core_cells": 0,
        "front_terminal_cells": 0,
        "blocked_ports": 0,
        "disconnected_commodity_count": 0,
    }


def _resolve_routing_domain_context(
    *,
    grid: Optional["RoutingGrid"] = None,
    placement_core: Optional[RoutingPlacementCore] = None,
    port_specs: Optional[Sequence[Mapping[str, Any]]] = None,
    occupied_owner_by_cell: Optional[Mapping[Tuple[int, int], str]] = None,
) -> Tuple[
    Optional["RoutingGrid"],
    List[Dict[str, Any]],
    Set[Tuple[int, int]],
    Dict[Tuple[int, int], str],
    Dict[Tuple[int, int], int],
    Dict[int, Set[Tuple[int, int]]],
    Optional[Mapping[Tuple[int, int], Sequence[Tuple[int, int]]]],
]:
    resolved_grid = grid
    resolved_core = placement_core
    if resolved_grid is None and resolved_core is None:
        raise ValueError("analyze_exact_routing_domain requires either grid or placement_core")

    if resolved_grid is not None:
        if resolved_core is None:
            resolved_core = getattr(resolved_grid, "placement_core", None)
        resolved_port_specs = [dict(spec) for spec in resolved_grid.port_specs]
    else:
        resolved_port_specs = [dict(spec) for spec in list(port_specs or [])]

    if resolved_core is not None:
        owner_map = dict(resolved_core.occupied_owner_by_cell)
        if occupied_owner_by_cell is not None:
            owner_map.update(
                {
                    (int(cell[0]), int(cell[1])): str(owner)
                    for cell, owner in dict(occupied_owner_by_cell).items()
                }
            )
        return (
            resolved_grid,
            resolved_port_specs,
            set(resolved_core.free_cells),
            owner_map,
            dict(resolved_core.component_by_cell),
            {
                int(component_id): set(cells)
                for component_id, cells in resolved_core.cells_by_component.items()
            },
            dict(resolved_core.free_neighbors_by_cell),
        )

    resolved_free_cells = set(getattr(resolved_grid, "free_cells", set()))
    owner_map = {
        (int(cell[0]), int(cell[1])): str(owner)
        for cell, owner in dict(
            occupied_owner_by_cell
            if occupied_owner_by_cell is not None
            else getattr(resolved_grid, "occupied_owner_by_cell", {})
        ).items()
    }
    component_by_cell, cells_by_component = _compute_free_components(resolved_free_cells)
    return (
        resolved_grid,
        resolved_port_specs,
        resolved_free_cells,
        owner_map,
        component_by_cell,
        cells_by_component,
        None,
    )


def analyze_exact_routing_domain(
    grid: Optional["RoutingGrid"] = None,
    *,
    placement_core: Optional[RoutingPlacementCore] = None,
    port_specs: Optional[Sequence[Mapping[str, Any]]] = None,
    occupied_owner_by_cell: Optional[Dict[Tuple[int, int], str]] = None,
) -> Dict[str, Any]:
    _resolved_grid, resolved_port_specs, resolved_free_cells, resolved_owner_map, component_by_cell, cells_by_component, free_neighbors_by_cell = _resolve_routing_domain_context(
        grid=grid,
        placement_core=placement_core,
        port_specs=port_specs,
        occupied_owner_by_cell=occupied_owner_by_cell,
    )
    blocked_ports: List[Dict[str, Any]] = []
    commodity_fronts: Dict[str, Set[Tuple[int, int]]] = defaultdict(set)
    commodity_source_fronts: Dict[str, Set[Tuple[int, int]]] = defaultdict(set)
    commodity_sink_fronts: Dict[str, Set[Tuple[int, int]]] = defaultdict(set)

    for spec in resolved_port_specs:
        px = int(spec["x"])
        py = int(spec["y"])
        direction = str(spec["dir"])
        commodity = str(spec.get("commodity", ""))
        dx, dy = DIR_DELTA[direction]
        fx, fy = px + dx, py + dy
        front_cell = (fx, fy)

        in_grid = 0 <= fx < GRID_W and 0 <= fy < GRID_H
        if not in_grid or front_cell not in resolved_free_cells:
            conflict_ids: List[str] = []
            instance_id = str(spec.get("instance_id", ""))
            if instance_id:
                conflict_ids.append(instance_id)

            blocking_instance_id = resolved_owner_map.get(front_cell)
            if blocking_instance_id and blocking_instance_id not in conflict_ids:
                conflict_ids.append(str(blocking_instance_id))

            blocked_ports.append(
                {
                    "instance_id": instance_id,
                    "commodity": commodity,
                    "dir": direction,
                    "front_cell": [fx, fy],
                    "blocking_instance_ids": (
                        []
                        if blocking_instance_id is None
                        else [str(blocking_instance_id)]
                    ),
                    "placement_level_conflict_set": conflict_ids,
                }
            )
            continue

        commodity_fronts[commodity].add(front_cell)
        if str(spec["type"]) == "out":
            commodity_source_fronts[commodity].add(front_cell)
        else:
            commodity_sink_fronts[commodity].add(front_cell)

    commodity_front_metadata = {
        commodity: {
            "front_cells": _sorted_cells(fronts),
            "source_front_cells": _sorted_cells(commodity_source_fronts.get(commodity, set())),
            "sink_front_cells": _sorted_cells(commodity_sink_fronts.get(commodity, set())),
        }
        for commodity, fronts in sorted(commodity_fronts.items())
    }

    if blocked_ports:
        placement_level_conflict_set: List[str] = []
        for blocked in blocked_ports:
            for instance_id in blocked["placement_level_conflict_set"]:
                if instance_id not in placement_level_conflict_set:
                    placement_level_conflict_set.append(instance_id)
        domain_stats = _empty_domain_stats()
        domain_stats["blocked_ports"] = len(blocked_ports)
        return {
            "status": "front_blocked",
            "binding_selection_safe_reject": True,
            "placement_level_conflict_set": placement_level_conflict_set,
            "blocked_ports": blocked_ports,
            "disconnected_commodities": [],
            "commodity_front_metadata": commodity_front_metadata,
            "commodity_component_cells": {},
            "commodity_active_cells": {},
            "domain_stats": domain_stats,
        }

    disconnected_commodities: List[Dict[str, Any]] = []
    commodity_component_cells: Dict[str, Set[Tuple[int, int]]] = {}
    commodity_active_cells: Dict[str, Set[Tuple[int, int]]] = {}

    for commodity, front_cells in sorted(commodity_fronts.items()):
        component_ids = {component_by_cell.get(cell, -1) for cell in front_cells}
        if len(component_ids) > 1:
            disconnected_commodities.append(
                {
                    "commodity": commodity,
                    "front_cells": _sorted_cells(front_cells),
                    "component_ids": sorted(component_ids),
                }
            )
            commodity_component_cells[commodity] = set()
            commodity_active_cells[commodity] = set()
            continue

        component_id = next(iter(component_ids), -1)
        component_cells = set(cells_by_component.get(component_id, set()))
        commodity_component_cells[commodity] = component_cells
        commodity_active_cells[commodity] = _peel_terminal_core(
            component_cells,
            set(front_cells),
            free_neighbors_by_cell=free_neighbors_by_cell,
        )

    domain_stats = {
        "commodity_component_cells": {
            commodity: len(cells)
            for commodity, cells in sorted(commodity_component_cells.items())
        },
        "commodity_active_cells": {
            commodity: len(cells)
            for commodity, cells in sorted(commodity_active_cells.items())
        },
        "commodity_terminal_cells": {
            commodity: len(commodity_fronts.get(commodity, set()))
            for commodity in sorted(commodity_fronts)
        },
        "domain_cells": sum(len(cells) for cells in commodity_component_cells.values()),
        "terminal_core_cells": sum(len(cells) for cells in commodity_active_cells.values()),
        "front_terminal_cells": sum(len(cells) for cells in commodity_fronts.values()),
        "blocked_ports": 0,
        "disconnected_commodity_count": len(disconnected_commodities),
    }

    if disconnected_commodities:
        return {
            "status": "relaxed_disconnected",
            "binding_selection_safe_reject": True,
            "placement_level_conflict_set": [],
            "blocked_ports": [],
            "disconnected_commodities": disconnected_commodities,
            "commodity_front_metadata": commodity_front_metadata,
            "commodity_component_cells": {
                commodity: _sorted_cells(cells)
                for commodity, cells in sorted(commodity_component_cells.items())
            },
            "commodity_active_cells": {
                commodity: _sorted_cells(cells)
                for commodity, cells in sorted(commodity_active_cells.items())
            },
            "domain_stats": domain_stats,
        }

    return {
        "status": "feasible",
        "binding_selection_safe_reject": False,
        "placement_level_conflict_set": [],
        "blocked_ports": [],
        "disconnected_commodities": [],
        "commodity_front_metadata": commodity_front_metadata,
        "commodity_component_cells": {
            commodity: _sorted_cells(cells)
            for commodity, cells in sorted(commodity_component_cells.items())
        },
        "commodity_active_cells": {
            commodity: _sorted_cells(cells)
            for commodity, cells in sorted(commodity_active_cells.items())
        },
        "domain_stats": domain_stats,
    }


def run_exact_routing_precheck(
    grid: Optional["RoutingGrid"] = None,
    *,
    placement_core: Optional[RoutingPlacementCore] = None,
    port_specs: Optional[Sequence[Mapping[str, Any]]] = None,
    occupied_owner_by_cell: Optional[Dict[Tuple[int, int], str]] = None,
) -> Dict[str, Any]:
    analysis = analyze_exact_routing_domain(
        grid,
        placement_core=placement_core,
        port_specs=port_specs,
        occupied_owner_by_cell=occupied_owner_by_cell,
    )
    return {
        "status": str(analysis["status"]),
        "binding_selection_safe_reject": bool(analysis["binding_selection_safe_reject"]),
        "placement_level_conflict_set": list(analysis.get("placement_level_conflict_set", [])),
        "blocked_ports": list(analysis.get("blocked_ports", [])),
        "disconnected_commodities": list(analysis.get("disconnected_commodities", [])),
        "domain_stats": dict(analysis.get("domain_stats", {})),
        "_analysis": analysis,
    }


class RoutingGrid:
    """3D grid domain for the routing subproblem."""

    def __init__(
        self,
        occupied_cells: Set[Tuple[int, int]],
        port_specs: List[Dict[str, Any]],
        *,
        occupied_owner_by_cell: Optional[Mapping[Tuple[int, int], str]] = None,
    ):
        self.occupied = {(int(x), int(y)) for x, y in occupied_cells}
        self.port_specs = [dict(spec) for spec in port_specs]
        self.occupied_owner_by_cell = {
            (int(cell[0]), int(cell[1])): str(owner)
            for cell, owner in dict(occupied_owner_by_cell or {}).items()
        }
        self.placement_core: Optional[RoutingPlacementCore] = None

        self.free_cells: Set[Tuple[int, int]] = set()
        for x in range(GRID_W):
            for y in range(GRID_H):
                if (x, y) not in self.occupied:
                    self.free_cells.add((x, y))

        self.port_cells: Set[Tuple[int, int]] = set()
        for ps in port_specs:
            self.port_cells.add((int(ps["x"]), int(ps["y"])))

        self.routable_cells = self.free_cells | self.port_cells

    @classmethod
    def from_placement_core(
        cls,
        placement_core: RoutingPlacementCore,
        port_specs: Sequence[Mapping[str, Any]],
    ) -> "RoutingGrid":
        grid = cls.__new__(cls)
        grid.occupied = set(placement_core.occupied_cells)
        grid.port_specs = [dict(spec) for spec in port_specs]
        grid.occupied_owner_by_cell = dict(placement_core.occupied_owner_by_cell)
        grid.placement_core = placement_core
        grid.free_cells = set(placement_core.free_cells)
        grid.port_cells = {
            (int(ps["x"]), int(ps["y"]))
            for ps in grid.port_specs
        }
        grid.routable_cells = grid.free_cells | grid.port_cells
        return grid

    def neighbors(self, x: int, y: int) -> List[Tuple[int, int, str]]:
        result = []
        for d, (dx, dy) in DIR_DELTA.items():
            nx, ny = x + dx, y + dy
            if 0 <= nx < GRID_W and 0 <= ny < GRID_H and (nx, ny) in self.routable_cells:
                result.append((nx, ny, d))
        return result


class RoutingSubproblem:
    """CP-SAT routing model with belt / splitter / merger / bridge states."""

    def __init__(
        self,
        grid: RoutingGrid,
        commodities: List[str],
        *,
        domain_analysis: Optional[Mapping[str, Any]] = None,
    ):
        self.grid = grid
        self._placement_core: Optional[RoutingPlacementCore] = getattr(
            grid,
            "placement_core",
            None,
        )
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

        self._domain_analysis: Optional[Mapping[str, Any]] = dict(domain_analysis) if domain_analysis else None
        self._domain_stats: Dict[str, Any] = {}
        self._commodity_active_cells: Dict[str, Set[Tuple[int, int]]] = {
            commodity: set() for commodity in self.commodities
        }
        self._commodity_component_cells: Dict[str, Set[Tuple[int, int]]] = {
            commodity: set() for commodity in self.commodities
        }

        self._source_port_fronts: Dict[Tuple[int, int, str, str], int] = defaultdict(int)
        self._sink_port_fronts: Dict[Tuple[int, int, str, str], int] = defaultdict(int)
        self._index_port_fronts()
        self._patterns_by_layer = {
            layer: list(self._iter_state_patterns(layer))
            for layer in LAYERS
        }
        self._pattern_count_per_cell = sum(len(patterns) for patterns in self._patterns_by_layer.values())

    @classmethod
    def from_placement_core(
        cls,
        placement_core: RoutingPlacementCore,
        port_specs: Sequence[Mapping[str, Any]],
        commodities: List[str],
        *,
        domain_analysis: Optional[Mapping[str, Any]] = None,
    ) -> "RoutingSubproblem":
        return cls(
            RoutingGrid.from_placement_core(placement_core, port_specs),
            commodities,
            domain_analysis=domain_analysis,
        )

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
        del time_limit
        t0 = time.time()
        analysis = (
            dict(self._domain_analysis)
            if self._domain_analysis is not None
            else analyze_exact_routing_domain(
                self.grid,
                placement_core=self._placement_core,
            )
        )
        self._bind_domain_analysis(analysis)

        if str(analysis.get("status", "feasible")) != "feasible":
            self.model.Add(0 == 1)
            self._record_state_space_stats(defaultdict(int), local_pattern_pruned_states=0)
            self._add_gap_rule()
            elapsed = time.time() - t0
            print(f"[Routing Model] build {elapsed:.1f}s")
            return

        self._create_routing_variables()
        self._add_obstacle_exclusion()
        self._add_capacity_constraints()
        self._add_bridge_constraints()
        self._add_continuity_constraints()
        self._add_port_adherence()
        self._add_gap_rule()
        elapsed = time.time() - t0
        print(f"[Routing Model] build {elapsed:.1f}s")

    def _bind_domain_analysis(self, analysis: Mapping[str, Any]) -> None:
        self._domain_analysis = dict(analysis)
        self._domain_stats = dict(analysis.get("domain_stats", {}))

        raw_component_cells = dict(analysis.get("commodity_component_cells", {}))
        raw_active_cells = dict(analysis.get("commodity_active_cells", {}))
        for commodity in self.commodities:
            component_cells = {
                (int(cell[0]), int(cell[1]))
                for cell in raw_component_cells.get(commodity, [])
            }
            active_cells = {
                (int(cell[0]), int(cell[1]))
                for cell in raw_active_cells.get(commodity, [])
            }
            self._commodity_component_cells[commodity] = component_cells
            self._commodity_active_cells[commodity] = active_cells

        self.build_stats["domain_analysis"] = {
            "status": str(analysis.get("status", "feasible")),
            "domain_stats": dict(self._domain_stats),
            "used_placement_core_reuse": bool(self._placement_core),
        }

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

    def _neighbor_in_active_domain(self, x: int, y: int, direction: str, commodity: str) -> bool:
        dx, dy = DIR_DELTA[direction]
        return (x + dx, y + dy) in self._commodity_active_cells.get(commodity, set())

    def _incoming_dir_supported(self, x: int, y: int, layer: int, direction: str, commodity: str) -> bool:
        if self._neighbor_in_active_domain(x, y, direction, commodity):
            return True
        if layer != GROUND_LAYER:
            return False
        return self._source_port_fronts.get((x, y, direction, commodity), 0) > 0

    def _outgoing_dir_supported(self, x: int, y: int, layer: int, direction: str, commodity: str) -> bool:
        if self._neighbor_in_active_domain(x, y, direction, commodity):
            return True
        if layer != GROUND_LAYER:
            return False
        return self._sink_port_fronts.get((x, y, direction, commodity), 0) > 0

    def _pattern_is_locally_supported(
        self,
        x: int,
        y: int,
        layer: int,
        commodity: str,
        flow_in: Tuple[str, ...],
        flow_out: Tuple[str, ...],
    ) -> bool:
        return all(
            self._incoming_dir_supported(x, y, layer, direction, commodity)
            for direction in flow_in
        ) and all(
            self._outgoing_dir_supported(x, y, layer, direction, commodity)
            for direction in flow_out
        )

    def _create_routing_variables(self):
        state_counter = defaultdict(int)
        local_pattern_pruned_states = 0

        for commodity in self.commodities:
            for (x, y) in sorted(self._commodity_active_cells.get(commodity, set())):
                for layer in LAYERS:
                    for pattern in self._patterns_by_layer[layer]:
                        flow_in = tuple(pattern["flow_in"])
                        flow_out = tuple(pattern["flow_out"])
                        component_type = str(pattern["component_type"])
                        if not self._pattern_is_locally_supported(
                            x,
                            y,
                            layer,
                            commodity,
                            flow_in,
                            flow_out,
                        ):
                            local_pattern_pruned_states += 1
                            continue

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

        self._record_state_space_stats(state_counter, local_pattern_pruned_states)

    def _record_state_space_stats(
        self,
        state_counter: Mapping[Tuple[int, str], int],
        local_pattern_pruned_states: int,
    ) -> None:
        commodity_component_cells = {
            commodity: int(self._domain_stats.get("commodity_component_cells", {}).get(commodity, 0))
            for commodity in self.commodities
            if commodity in self._domain_stats.get("commodity_component_cells", {})
        }
        commodity_active_cells = {
            commodity: int(self._domain_stats.get("commodity_active_cells", {}).get(commodity, 0))
            for commodity in self.commodities
            if commodity in self._domain_stats.get("commodity_active_cells", {})
        }
        naive_full_domain_vars = len(self.grid.free_cells) * len(self.commodities) * self._pattern_count_per_cell

        self.build_stats["state_space"] = {
            "commodities": len(self.commodities),
            "vars": len(self.r_vars),
            "ground_belt_states": int(state_counter.get((GROUND_LAYER, "belt"), 0)),
            "ground_splitter_states": int(state_counter.get((GROUND_LAYER, "splitter"), 0)),
            "ground_merger_states": int(state_counter.get((GROUND_LAYER, "merger"), 0)),
            "elevated_bridge_states": int(state_counter.get((ELEVATED_LAYER, "bridge"), 0)),
            "used_placement_core_reuse": bool(self._placement_core),
            "commodity_component_cells": commodity_component_cells,
            "commodity_active_cells": commodity_active_cells,
            "domain_cells": int(self._domain_stats.get("domain_cells", 0)),
            "terminal_core_cells": int(self._domain_stats.get("terminal_core_cells", 0)),
            "local_pattern_pruned_states": int(local_pattern_pruned_states),
            "naive_full_domain_vars": int(naive_full_domain_vars),
        }

    def _add_obstacle_exclusion(self):
        # Obstacle exclusion is implemented by only creating variables on active free cells.
        return

    def _add_capacity_constraints(self):
        for vars_on_cell_layer in self._vars_by_cell_layer.values():
            if vars_on_cell_layer:
                self.model.AddAtMostOne(vars_on_cell_layer)

    def _add_bridge_constraints(self):
        for cell, l1_vars in self._l1_vars.items():
            if not l1_vars:
                continue
            l0_nonstraight = self._l0_nonstraight_vars.get(cell, [])
            if not l0_nonstraight:
                continue
            x, y = cell
            l1_any = self.model.NewBoolVar(f"l1_any_{x}_{y}")
            self.model.AddMaxEquality(l1_any, l1_vars)
            for var in l0_nonstraight:
                self.model.AddImplication(l1_any, var.Not())

    def _add_continuity_constraints(self):
        for commodity in self.commodities:
            for (x, y) in self._commodity_active_cells.get(commodity, set()):
                for layer in LAYERS:
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
        if (nx, ny) not in self._commodity_active_cells.get(commodity, set()):
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
        if (px, py) not in self._commodity_active_cells.get(commodity, set()):
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

        for ps in self.grid.port_specs:
            px, py = int(ps["x"]), int(ps["y"])
            direction = str(ps["dir"])
            commodity = str(ps["commodity"])
            dx, dy = DIR_DELTA[direction]
            fx, fy = px + dx, py + dy

            if (fx, fy) not in self._commodity_active_cells.get(commodity, set()):
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
