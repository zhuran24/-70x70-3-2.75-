"""
Benders 分解切平面管理器 (Cut Manager)
对应规格书：10_benders_decomposition_and_cut_design
Status: ACCEPTED_DRAFT

目标：管理 LBBD 主从协同状态机，协调主模型 (07) 与子问题 (08, 09)，
生成并维护组合互斥切平面。

核心职责：
  1. 驱动 LBBD 循环 (§10.2)
  2. 从子问题提取冲突集并生成切平面 (§10.3, §10.4)
  3. 管理切平面持久化与去重
  4. Solution Hint 热启动 (§10.6)
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple
from collections import defaultdict

from src.models.master_model import MasterPlacementModel, load_project_data
from src.models.binding_subproblem import PortBindingModel
from src.models.routing_subproblem import RoutingGrid, RoutingSubproblem

RUN_STATUS_CERTIFIED = "CERTIFIED"
RUN_STATUS_INFEASIBLE = "INFEASIBLE"
RUN_STATUS_UNKNOWN = "UNKNOWN"
RUN_STATUS_UNPROVEN = "UNPROVEN"


# ==========================================
# 1. 切平面数据结构
# ==========================================

class BendersCut:
    """单条 Benders 切平面。"""

    def __init__(
        self,
        cut_type: str,  # "topo" (08章) or "micro" (09章)
        conflict_set: Dict[str, int],  # {instance_id: pose_idx}
        iteration: int,
        metadata: Optional[Dict] = None,
    ):
        self.cut_type = cut_type
        self.conflict_set = conflict_set
        self.iteration = iteration
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cut_type": self.cut_type,
            "conflict_set": self.conflict_set,
            "iteration": self.iteration,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BendersCut":
        return cls(
            cut_type=d["cut_type"],
            conflict_set=d["conflict_set"],
            iteration=d["iteration"],
            metadata=d.get("metadata", {}),
        )


# ==========================================
# 2. 切平面管理器
# ==========================================

class CutManager:
    """LBBD 切平面管理器。"""

    def __init__(self):
        self.cuts: List[BendersCut] = []
        self._cut_signatures: Set[frozenset] = set()  # 去重用

    def add_cut(self, cut: BendersCut) -> bool:
        """添加切平面（自动去重）。返回是否成功添加。"""
        sig = frozenset(cut.conflict_set.items())
        if sig in self._cut_signatures:
            return False
        self._cut_signatures.add(sig)
        self.cuts.append(cut)
        return True

    def get_cuts_count(self) -> Dict[str, int]:
        """按类型统计切平面数量。"""
        counts: Dict[str, int] = defaultdict(int)
        for cut in self.cuts:
            counts[cut.cut_type] += 1
        return dict(counts)

    def save(self, path: Path):
        """持久化切平面集合到 JSON。"""
        data = [c.to_dict() for c in self.cuts]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def load(self, path: Path):
        """从 JSON 恢复切平面集合。"""
        if not path.exists():
            return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for d in data:
            cut = BendersCut.from_dict(d)
            self.add_cut(cut)


# ==========================================
# 3. 冲突集提取
# ==========================================

def extract_topo_conflict_set(
    solution: Dict[str, Any],
    bottleneck_cells: Set[Tuple[int, int]],
    facility_pools: Dict[str, List[Dict]],
) -> Dict[str, int]:
    """从宏观拓扑流失败中提取肇事刚体集 (§10.3.2)。

    策略：找出所有占据瓶颈格子邻域的实例。
    """
    conflict = {}
    for iid, sol in solution.items():
        p_idx = sol["pose_idx"]
        tpl = sol["facility_type"]
        pose = facility_pools[tpl][p_idx]

        # 检查该实例的占格是否与瓶颈区域相邻
        for cell in pose["occupied_cells"]:
            cx, cy = cell[0], cell[1]
            for dx, dy in [(0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)]:
                if (cx + dx, cy + dy) in bottleneck_cells:
                    conflict[iid] = p_idx
                    break
            if iid in conflict:
                break

    return conflict


def extract_nogood_from_solution(
    solution: Dict[str, Any],
) -> Dict[str, int]:
    """退化方案：将整个解作为 no-good 切面。
    
    当无法精确定位冲突子集时，使用全解排斥。
    切平面: Σ z_{i, p_i*} ≤ |solution| - 1
    """
    return {iid: sol["pose_idx"] for iid, sol in solution.items()}


def summarize_port_balance(
    port_specs: List[Dict[str, Any]],
) -> Dict[str, Dict[str, int]]:
    """Count discrete in/out endpoints per commodity for the current micro-routing model."""
    balance: Dict[str, Dict[str, int]] = defaultdict(lambda: {"in": 0, "out": 0})
    for spec in port_specs:
        commodity = str(spec["commodity"])
        port_type = str(spec["type"])
        if port_type in ("in", "out"):
            balance[commodity][port_type] += 1
    return dict(balance)


def analyze_port_balance(
    port_specs: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Dict[str, int]]]:
    """Summarize dead-end commodities and split/merge pressure for one binding."""
    balance = summarize_port_balance(port_specs)
    dead_end: Dict[str, Dict[str, int]] = {}
    needs_splitter: Dict[str, Dict[str, int]] = {}
    needs_merger: Dict[str, Dict[str, int]] = {}

    for commodity, counts in balance.items():
        in_count = int(counts["in"])
        out_count = int(counts["out"])
        if in_count == 0 < out_count or out_count == 0 < in_count:
            dead_end[commodity] = {"in": in_count, "out": out_count}
            continue
        if in_count > out_count:
            needs_splitter[commodity] = {
                "in": in_count,
                "out": out_count,
                "delta": in_count - out_count,
            }
        elif out_count > in_count:
            needs_merger[commodity] = {
                "in": in_count,
                "out": out_count,
                "delta": out_count - in_count,
            }

    return {
        "balance": balance,
        "dead_end": dead_end,
        "needs_splitter": needs_splitter,
        "needs_merger": needs_merger,
    }


# ==========================================
# 4. LBBD 循环控制器
# ==========================================

class LBBDController:
    """逻辑型 Benders 分解主控制器 (§10.2 状态机)。"""

    def __init__(
        self,
        master: MasterPlacementModel,
        cut_manager: CutManager,
        max_iterations: int = 100,
        master_time_limit: float = 300.0,
        exact_mode: bool = False,
    ):
        self.master = master
        self.cut_manager = cut_manager
        self.max_iterations = max_iterations
        self.master_time_limit = master_time_limit
        self.exact_mode = exact_mode

        self._last_good_hint: Optional[Dict[str, int]] = None
        self._last_routing_solution: Optional[List[Dict[str, Any]]] = None
        self._last_port_specs: Optional[List[Dict[str, Any]]] = None
        self._iteration = 0

    def run(self) -> Optional[Dict[str, Any]]:
        """兼容旧接口：仅在拿到可认证结果时返回解。"""
        status, solution = self.run_with_status()
        if status == RUN_STATUS_CERTIFIED:
            return solution
        return None

    def run_with_status(self) -> Tuple[str, Optional[Dict[str, Any]]]:
        """执行 LBBD 状态机循环。

        Returns:
            (status, solution)
            status ∈ {CERTIFIED, INFEASIBLE, UNKNOWN, UNPROVEN}
        """
        from ortools.sat.python import cp_model as cp

        for iteration in range(1, self.max_iterations + 1):
            self._iteration = iteration
            print(f"\n{'='*60}")
            print(f"🔄 LBBD 迭代 #{iteration}")
            print(f"   累计切平面: {len(self.cut_manager.cuts)}")
            print(f"{'='*60}")

            # --- Step 1: 主问题求解 ---
            solve_hint = self._last_good_hint
            if solve_hint is None and self.exact_mode:
                solve_hint = self.master.build_greedy_solution_hint()
                hinted = self.master.build_stats.get("greedy_hint", {}).get("hinted_instances", 0)
                ghost_idx = self.master.build_stats.get("greedy_hint", {}).get("ghost_pose_idx")
                print(f"🧭 [Hint] exact 热启动: {hinted} 个 mandatory 实例, ghost={ghost_idx}")

            status = self.master.solve(
                time_limit_seconds=self.master_time_limit,
                solution_hint=solve_hint,
                known_feasible_hint=self._last_good_hint is not None,
            )

            if status not in (cp.OPTIMAL, cp.FEASIBLE):
                status_name = {
                    cp.UNKNOWN: "UNKNOWN (超时)",
                    cp.INFEASIBLE: "INFEASIBLE",
                    cp.MODEL_INVALID: "MODEL_INVALID",
                }.get(status, f"STATUS_{status}")
                print(f"🔍 [求解结果] {status_name}")

                # UNKNOWN = 超时,不等于不可行 — 重试一次(2x时限)
                if status == cp.UNKNOWN and iteration == 1:
                    retry_limit = self.master_time_limit * 2
                    print(f"🔄 [重试] UNKNOWN→重试, 时限 {retry_limit:.0f}s")
                    status = self.master.solve(
                        time_limit_seconds=retry_limit,
                        solution_hint=self._last_good_hint,
                        known_feasible_hint=self._last_good_hint is not None,
                    )
                    if status in (cp.OPTIMAL, cp.FEASIBLE):
                        print(f"✅ [重试成功] 在加长时限内找到可行解!")
                    else:
                        print("⏸️ [LBBD] 主问题仍未证伪，但当前时限内无法给出精确结论。")
                        return RUN_STATUS_UNKNOWN, None
                else:
                    if status == cp.UNKNOWN:
                        print("⏸️ [LBBD] 主问题在当前时限内未解开，无法宣称该尺寸无解。")
                        return RUN_STATUS_UNKNOWN, None
                    print(f"❌ [LBBD] 主问题 {status_name}，当前空地尺寸无解。")
                    return RUN_STATUS_INFEASIBLE, None

            solution = self.master.extract_solution()
            print(f"✅ [Step 1] 主问题可行，{len(solution)} 个实例已定位。")

            # --- Step 2: 一级子问题 (宏观流) ---
            flow_result = self._run_flow_check(solution)

            if flow_result == "INFEASIBLE":
                if self.exact_mode:
                    print("⚠️ [Step 2] 宏观流当前仍是近似筛子，exact 模式下不据此判死，转入微观绑定+路由。")
                else:
                    print(f"⛔ [Step 2] 宏观流拥堵！生成拓扑切平面。")
                    # 退化方案：将全解作为 no-good
                    conflict = extract_nogood_from_solution(solution)
                    cut = BendersCut("topo", conflict, iteration)
                    if self.cut_manager.add_cut(cut):
                        self.master.add_benders_cut(conflict)
                    continue
            if flow_result == RUN_STATUS_UNKNOWN:
                if self.exact_mode:
                    print("⚠️ [Step 2] 宏观流未给出确定结论，但 exact 模式继续交给微观绑定+路由。")
                else:
                    print("⏸️ [Step 2] 宏观流检查未能给出确定结论，停止 exact 认证。")
                    return RUN_STATUS_UNKNOWN, None

            if flow_result == "FEASIBLE":
                print(f"✅ [Step 2] 宏观流畅通。")
            elif self.exact_mode:
                print("➡️ [Step 2] 继续进入精确绑定+路由认证。")

            # --- Step 3: 二级子问题 (精确路由) ---
            routing_result = self._run_routing_check(solution)
            if routing_result == "INFEASIBLE":
                print("⛔ [Step 3] 微观逐格路由失败！生成退化 no-good 切平面。")
                conflict = extract_nogood_from_solution(solution)
                cut = BendersCut("micro", conflict, iteration)
                if self.cut_manager.add_cut(cut):
                    self.master.add_benders_cut(conflict)
                continue
            if routing_result == RUN_STATUS_UNKNOWN:
                print("⏸️ [Step 3] 微观路由在当前时限内未解开，停止 exact 认证。")
                return RUN_STATUS_UNKNOWN, None
            if routing_result == RUN_STATUS_UNPROVEN:
                print("⚠️ [Step 3] 当前代码路径无法提供微观路由级 exact 证书。")
                return RUN_STATUS_UNPROVEN, None

            # 记录热启动 hint
            self._last_good_hint = {
                iid: sol["pose_idx"] for iid, sol in solution.items()
            }

            print(f"\n🏆 [LBBD 胜利] 迭代 #{iteration} 找到可认证布局！")
            return RUN_STATUS_CERTIFIED, solution

        print(f"⏰ [LBBD] 达到最大迭代次数 {self.max_iterations}")
        return RUN_STATUS_UNKNOWN, None

    def _run_flow_check(self, solution: Dict[str, Any]) -> str:
        """运行宏观拓扑流检查 (§10.2 Step 2)。

        从主问题解中提取占据格和端口，调用 08 章 MCF LP。
        """
        from src.models.flow_subproblem import (
            build_flow_network, FlowSubproblem
        )

        try:
            pools = self.master.pools

            # 1. 提取所有被占据的格子
            occupied_cells: Set[Tuple[int, int]] = set()
            for iid, sol in solution.items():
                tpl = sol["facility_type"]
                p_idx = sol["pose_idx"]
                pool = pools.get(tpl, [])
                if p_idx < len(pool):
                    for cell in pool[p_idx]["occupied_cells"]:
                        occupied_cells.add((cell[0], cell[1]))

            # 2. 构建端口字典 {commodity: [port_spec]}
            # 简化: 将所有端口归为统一 commodity "material"
            # 因为全局池化不区分具体物料
            port_dict: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
            for iid, sol in solution.items():
                tpl = sol["facility_type"]
                p_idx = sol["pose_idx"]
                pool = pools.get(tpl, [])
                if p_idx >= len(pool):
                    continue
                pose = pool[p_idx]

                # 收集输入端口
                for port in pose.get("input_port_cells", []):
                    port_dict["material"].append({
                        "x": port["x"], "y": port["y"],
                        "dir": port["dir"], "type": "in",
                        "instance_id": iid,
                    })

                # 收集输出端口
                for port in pose.get("output_port_cells", []):
                    port_dict["material"].append({
                        "x": port["x"], "y": port["y"],
                        "dir": port["dir"], "type": "out",
                        "instance_id": iid,
                    })

            # 3. 简化的 commodity demand: 总端口流量需求
            n_out = sum(1 for p in port_dict.get("material", [])
                        if p["type"] == "out")
            n_in = sum(1 for p in port_dict.get("material", [])
                       if p["type"] == "in")
            demand = min(n_out, n_in) * 0.5  # 保守估计
            if demand <= 0:
                return "FEASIBLE"

            commodity_demands = {"material": demand}

            # 4. 构建并求解 MCF LP
            network = build_flow_network(
                occupied_cells, dict(port_dict), commodity_demands
            )
            flow_sub = FlowSubproblem(network, commodity_demands)
            result = flow_sub.build_and_solve(time_limit_ms=5000)

            return result

        except Exception as e:
            print(f"⚠️ [Flow] 异常: {e}")
            return RUN_STATUS_UNKNOWN

    def _run_routing_check(self, solution: Dict[str, Any]) -> str:
        """运行精确逐格路由检查。
        """
        occupied_cells = self._extract_occupied_cells(solution)
        binding = PortBindingModel(
            placement_solution=solution,
            facility_pools=self.master.pools,
            instances=self.master.source_instances,
        )
        binding.build()

        search_deadline = time.time() + 30.0
        attempts = 0
        while time.time() < search_deadline:
            attempts += 1
            remaining = max(1.0, search_deadline - time.time())
            bind_result = binding.solve(time_limit_seconds=min(5.0, remaining))
            if bind_result == "TIMEOUT":
                print("⏸️ [Binding] 端口绑定子问题超时。")
                return RUN_STATUS_UNKNOWN
            if bind_result == "INFEASIBLE":
                print(f"❌ [Binding] 已穷尽 {attempts - 1} 套绑定选择，未找到可路由候选。")
                return "INFEASIBLE"

            port_specs = binding.extract_port_specs()
            balance_diag = analyze_port_balance(port_specs)
            dead_end = balance_diag["dead_end"]
            splitter_need = balance_diag["needs_splitter"]
            merger_need = balance_diag["needs_merger"]

            if dead_end:
                print(f"⛔ [Binding] 第 {attempts} 套绑定缺失物理 source/sink: {dead_end}")
                return "INFEASIBLE"

            commodities = sorted({spec["commodity"] for spec in port_specs})
            route_remaining = max(1.0, search_deadline - time.time())

            print(f"🔌 [Binding] 尝试第 {attempts} 套端口绑定，物料种类 {len(commodities)}。")
            if splitter_need or merger_need:
                print(
                    "🔀 [Binding] 本绑定需要分流/汇流: "
                    f"splitter={splitter_need}, merger={merger_need}"
                )
            routing = RoutingSubproblem(RoutingGrid(occupied_cells, port_specs), commodities)
            routing.build()
            route_result = routing.solve(time_limit=min(10.0, route_remaining))

            if route_result == "FEASIBLE":
                self._last_routing_solution = routing.extract_routes()
                self._last_port_specs = port_specs
                print(f"✅ [Step 3] 在第 {attempts} 套绑定下找到逐格路由。")
                return "FEASIBLE"
            if route_result == "TIMEOUT":
                print("⏸️ [Step 3] 微观路由超时，无法给出确定结论。")
                return RUN_STATUS_UNKNOWN

            print(f"⛔ [Step 3] 第 {attempts} 套绑定路由失败，加入绑定 no-good 后重试。")
            binding.add_nogood_cut(binding.extract_selection())

        print("⏸️ [Step 3] 绑定+路由搜索在时限内未穷尽。")
        return RUN_STATUS_UNKNOWN

    def _extract_occupied_cells(self, solution: Dict[str, Any]) -> Set[Tuple[int, int]]:
        occupied_cells: Set[Tuple[int, int]] = set()
        for iid, sol in solution.items():
            tpl = sol["facility_type"]
            p_idx = sol["pose_idx"]
            pool = self.master.pools.get(tpl, [])
            if p_idx < len(pool):
                for cell in pool[p_idx]["occupied_cells"]:
                    occupied_cells.add((cell[0], cell[1]))
        return occupied_cells


# ==========================================
# 5. 主控入口
# ==========================================

def main():
    print("🚀 [LBBD] 启动 Benders 分解主控制器...")
    project_root = Path(__file__).resolve().parent.parent.parent

    instances, pools, rules = load_project_data(project_root)

    master = MasterPlacementModel(instances, pools, rules)
    master.build()

    cm = CutManager()
    controller = LBBDController(master, cm, max_iterations=5, master_time_limit=60.0)

    result = controller.run()
    if result:
        # 序列化结果
        output_dir = project_root / "data" / "solutions"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "placement_solution.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"💾 [保存] 布局方案已序列化至 {output_path}")
    else:
        print("❌ [结论] 未找到可行布局。")


if __name__ == "__main__":
    main()
