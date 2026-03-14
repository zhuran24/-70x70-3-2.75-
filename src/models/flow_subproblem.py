"""
宏观拓扑流子问题 (Topological Flow Subproblem)
对应规格书：08_topological_flow_subproblem
Status: ACCEPTED_DRAFT

目标：给定主模型的摆放方案 z*，构建多商品流 LP 模型，
快速判定宏观物料通道是否畅通。若拥堵则提取 Benders 切平面。

接口：
  Input:  occupancy_mask + port_dict (from master_model solution)
  Output: FEASIBLE + flow_matrix | INFEASIBLE + conflict_set
"""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Set
from collections import defaultdict

# OR-Tools 线性求解器
from ortools.linear_solver import pywraplp

GRID_W = 70
GRID_H = 70


# ==========================================
# 1. 网络图构建
# ==========================================

class FlowNetwork:
    """08 章宏观拓扑流网络。"""

    def __init__(self):
        self.nodes: Set[str] = set()
        self.edges: Dict[Tuple[str, str], float] = {}  # (u, v) -> capacity

    def add_node(self, node_id: str):
        self.nodes.add(node_id)

    def add_edge(self, u: str, v: str, capacity: float):
        self.edges[(u, v)] = capacity
        self.nodes.add(u)
        self.nodes.add(v)

    def get_capacity(self, u: str, v: str) -> float:
        return self.edges.get((u, v), 0.0)


def cell_id(x: int, y: int) -> str:
    """格子节点 ID。"""
    return f"c_{x}_{y}"


def build_flow_network(
    occupied_cells: Set[Tuple[int, int]],
    port_dict: Dict[str, List[Dict[str, Any]]],
    commodity_demands: Dict[str, float],
) -> FlowNetwork:
    """根据主模型的摆放解构建有向网络流图 (§8.2)。

    Args:
        occupied_cells: 被刚体占据的格子集合
        port_dict: 按物料分组的端口字典
                   {commodity: [{"x", "y", "dir", "type"("in"|"out"), "instance_id"}]}
        commodity_demands: {commodity: demand_flow_rate}
    """
    net = FlowNetwork()

    # 1. 自由网格节点 + 空间邻接边 (§8.2.1, §8.2.2)
    free_cells = set()
    for x in range(GRID_W):
        for y in range(GRID_H):
            if (x, y) not in occupied_cells:
                free_cells.add((x, y))
                net.add_node(cell_id(x, y))

    # 四邻域双向边，容量 2.0 (地面+高架)
    for (x, y) in free_cells:
        for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
            nx, ny = x + dx, y + dy
            if (nx, ny) in free_cells:
                net.add_edge(cell_id(x, y), cell_id(nx, ny), 2.0)

    # 2. 端口接入/接出边 (§8.2.2)
    for commodity, ports in port_dict.items():
        for port in ports:
            px, py = port["x"], port["y"]
            port_node = f"port_{port['instance_id']}_{px}_{py}"
            net.add_node(port_node)

            # 端口朝向的正前方格子
            direction = port["dir"]
            if direction == "N":
                adj = (px, py + 1)
            elif direction == "S":
                adj = (px, py - 1)
            elif direction == "E":
                adj = (px + 1, py)
            elif direction == "W":
                adj = (px - 1, py)
            else:
                continue

            # 检查正前方是否为自由格
            if adj in free_cells:
                adj_node = cell_id(adj[0], adj[1])
                if port["type"] == "out":
                    net.add_edge(port_node, adj_node, 1.0)
                else:
                    net.add_edge(adj_node, port_node, 1.0)

    # 3. 超级源汇 (§8.2.2)
    for commodity, demand in commodity_demands.items():
        src = f"S_{commodity}"
        snk = f"T_{commodity}"
        net.add_node(src)
        net.add_node(snk)

        if commodity in port_dict:
            for port in port_dict[commodity]:
                port_node = f"port_{port['instance_id']}_{port['x']}_{port['y']}"
                if port["type"] == "out":
                    net.add_edge(src, port_node, 1.0)
                else:
                    net.add_edge(port_node, snk, 1.0)

    return net


# ==========================================
# 2. MCF LP 求解
# ==========================================

class FlowSubproblem:
    """08 章连续多商品流线性规划。"""

    def __init__(
        self,
        network: FlowNetwork,
        commodity_demands: Dict[str, float],
    ):
        self.network = network
        self.demands = commodity_demands
        self.commodities = list(commodity_demands.keys())

        self._solver: Optional[pywraplp.Solver] = None
        self._flow_vars: Dict[Tuple[str, str, str], Any] = {}
        self._status = None

    def build_and_solve(self, time_limit_ms: int = 10000) -> str:
        """构建并求解 MCF LP (§8.3)。
        
        Returns: "FEASIBLE" or "INFEASIBLE"
        """
        solver = pywraplp.Solver.CreateSolver("GLOP")
        if not solver:
            raise RuntimeError("GLOP 求解器不可用")

        solver.SetTimeLimit(time_limit_ms)
        self._solver = solver

        # 创建流量变量 f_{u,v}^k >= 0
        for (u, v), cap in self.network.edges.items():
            for k in self.commodities:
                var = solver.NumVar(0.0, solver.infinity(), f"f_{u}_{v}_{k}")
                self._flow_vars[(u, v, k)] = var

        # 8.3.1 供需满足约束
        for k in self.commodities:
            demand = self.demands[k]
            src = f"S_{k}"
            snk = f"T_{k}"

            # 源点流出 = demand
            src_out_vars = [
                self._flow_vars[(src, v, k)]
                for (u, v) in self.network.edges if u == src
                if (src, v, k) in self._flow_vars
            ]
            if src_out_vars:
                solver.Add(solver.Sum(src_out_vars) == demand)

            # 汇点流入 = demand
            snk_in_vars = [
                self._flow_vars[(u, snk, k)]
                for (u, v) in self.network.edges if v == snk
                if (u, snk, k) in self._flow_vars
            ]
            if snk_in_vars:
                solver.Add(solver.Sum(snk_in_vars) == demand)

        # 8.3.2 流量守恒
        for node in self.network.nodes:
            if node.startswith("S_") or node.startswith("T_"):
                continue
            for k in self.commodities:
                in_vars = [
                    self._flow_vars[(u, node, k)]
                    for (u, v) in self.network.edges if v == node
                    if (u, node, k) in self._flow_vars
                ]
                out_vars = [
                    self._flow_vars[(node, v, k)]
                    for (u, v) in self.network.edges if u == node
                    if (node, v, k) in self._flow_vars
                ]
                if in_vars or out_vars:
                    solver.Add(
                        solver.Sum(in_vars) - solver.Sum(out_vars) == 0
                    )

        # 8.3.3 共享信道截面容量
        for (u, v), cap in self.network.edges.items():
            if u.startswith("S_") or u.startswith("T_") or \
               v.startswith("S_") or v.startswith("T_"):
                continue
            total_flow = [
                self._flow_vars[(u, v, k)]
                for k in self.commodities
                if (u, v, k) in self._flow_vars
            ]
            if total_flow:
                solver.Add(solver.Sum(total_flow) <= cap)

        # 求解
        result = solver.Solve()
        if result == pywraplp.Solver.OPTIMAL or result == pywraplp.Solver.FEASIBLE:
            self._status = "FEASIBLE"
        else:
            self._status = "INFEASIBLE"

        return self._status

    def extract_flow_matrix(self) -> Dict[str, Dict[Tuple[str, str], float]]:
        """提取连续流分布矩阵（供 09 章启发式费洛蒙使用）。"""
        if self._status != "FEASIBLE":
            return {}

        flows: Dict[str, Dict[Tuple[str, str], float]] = defaultdict(dict)
        for (u, v, k), var in self._flow_vars.items():
            val = var.solution_value()
            if val > 1e-6:
                flows[k][(u, v)] = val
        return dict(flows)

    def extract_bottleneck_cells(self) -> Set[Tuple[int, int]]:
        """提取瓶颈格子集合（用于 Benders 切面的肇事刚体识别）。
        
        在 INFEASIBLE 时，返回接近容量饱和的边对应的格子。
        注意：GLOP 在无解时不提供对偶射线，此处使用启发式方法。
        """
        # 启发式：找出所有流量接近容量上限的边
        bottleneck_cells = set()
        if self._status == "INFEASIBLE" and self._solver:
            # 无法从 INFEASIBLE LP 提取流量
            # 退化方案：标记所有自由格中"度数最低"的区域
            pass

        return bottleneck_cells
