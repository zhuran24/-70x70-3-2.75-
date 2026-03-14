"""
主摆放运筹学模型 (Master Placement Model)
对应规格书：07_master_placement_model
Status: ACCEPTED_DRAFT

目标：使用 OR-Tools CP-SAT 为 326 个候选刚体在 70×70 网格中寻找一个
  绝对不重叠、且 100% 满足供电覆盖的合法坐标组合。

接口依赖 (全部 FROZEN)：
  - data/preprocessed/all_facility_instances.json
  - data/preprocessed/candidate_placements.json
  - rules/canonical_rules.json
  - src/placement/occupancy_masks.py
  - src/placement/symmetry_breaking.py
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Set
from collections import defaultdict

from ortools.sat.python import cp_model

POSE_LEVEL_OPTIONAL_TEMPLATES = {"power_pole", "protocol_storage_box"}
POSE_LEVEL_OPTIONAL_PREFIX = {
    "power_pole": "power_pole",
    "protocol_storage_box": "protocol_box",
}
DIR_DELTA = {"N": (0, 1), "S": (0, -1), "E": (1, 0), "W": (-1, 0)}

# ==========================================
# 0. 数据加载
# ==========================================

def load_project_data(project_root: Path) -> Tuple[
    List[Dict], Dict[str, List[Dict]], Dict[str, Any]
]:
    """加载全部预处理数据。"""
    data_dir = project_root / "data" / "preprocessed"

    with open(data_dir / "all_facility_instances.json", "r", encoding="utf-8") as f:
        instances = json.load(f)

    with open(data_dir / "candidate_placements.json", "r", encoding="utf-8") as f:
        placements_data = json.load(f)
    pools = placements_data["facility_pools"]

    with open(project_root / "rules" / "canonical_rules.json", "r", encoding="utf-8") as f:
        rules = json.load(f)

    return instances, pools, rules


# ==========================================
# 1. 模型构建器
# ==========================================

class MasterPlacementModel:
    """07 章主摆放模型的 CP-SAT 实现。

    核心约束：
      (1) Assignment: 强制实例单选, 可选实例条件单选
      (2) Set Packing: 每格最多 1 个刚体
      (3) Power Coverage: 需电设施必须被至少 1 个供电桩覆盖
      (4) Symmetry Breaking: 同模板等价实例字典序排列
      (5) Global Valid Inequality: 供电桩数 ≥ 理论下界
    """

    def __init__(
        self,
        instances: List[Dict],
        facility_pools: Dict[str, List[Dict]],
        rules: Dict[str, Any],
        ghost_rect: Optional[Tuple[int, int]] = None,
        skip_power_coverage: bool = False,
        enable_symmetry_breaking: bool = True,
        exact_mode: bool = False,
    ):
        self.source_instances = instances
        self.instances = [i for i in instances if i["is_mandatory"]]
        self.pools = facility_pools
        self.rules = rules
        self.templates = rules["facility_templates"]
        self.ghost_rect = ghost_rect  # (w, h) or None
        self.skip_power_coverage = skip_power_coverage
        self.enable_symmetry_breaking = enable_symmetry_breaking
        self.exact_mode = exact_mode

        self.model = cp_model.CpModel()
        self._template_ord = {
            tpl: idx for idx, tpl in enumerate(sorted(self.templates.keys()))
        }
        self._instance_ord = {
            inst["instance_id"]: idx for idx, inst in enumerate(self.source_instances)
        }

        # 变量存储
        self.z_vars: Dict[str, Dict[int, Any]] = {}  # z_vars[group_or_inst_id][pose_idx]
        self.x_vars: Dict[str, Any] = {}  # x_vars[inst_id] (optional activation)
        self.optional_pose_vars: Dict[str, Dict[int, Any]] = {}
        self.u_vars: Dict[int, Any] = {}  # u_vars[rect_idx] (ghost rect)
        self._ghost_cell_vars: Dict[int, List[Any]] = defaultdict(list)
        self._ghost_domains: List[Dict[str, Any]] = []
        self._power_pose_info: Dict[str, List[Tuple[bool, List[int]]]] = {}
        self._power_pose_and: Dict[str, Dict[int, Any]] = {}
        self.build_stats: Dict[str, Any] = {}

        # 索引缓存
        self._mandatory = list(self.instances)
        self._optional = [
            i for i in instances
            if not i["is_mandatory"]
            and i["facility_type"] not in POSE_LEVEL_OPTIONAL_TEMPLATES
        ]
        self._pose_optional_templates = sorted({
            i["facility_type"]
            for i in instances
            if not i["is_mandatory"]
            and i["facility_type"] in POSE_LEVEL_OPTIONAL_TEMPLATES
        })
        self._powered_types = {
            tpl_key for tpl_key, tpl_def in self.templates.items()
            if tpl_def.get("needs_power", False)
        }
        self._mandatory_groups: List[Dict[str, Any]] = []
        self._group_id_by_instance: Dict[str, str] = {}
        self._groups_by_template: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._group_ord: Dict[str, int] = {}
        self._exact_search_strategy_added = False
        self._greedy_hint_cache: Optional[Dict[str, int]] = None
        self._build_mandatory_groups()

    def _build_mandatory_groups(self):
        grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
        for inst in self.instances:
            grouped[(inst["facility_type"], str(inst.get("operation_type", "")))].append(inst)

        self._mandatory_groups = []
        self._group_id_by_instance.clear()
        self._groups_by_template = defaultdict(list)

        for group_ord, key in enumerate(sorted(grouped.keys())):
            tpl, operation_type = key
            members = sorted(grouped[key], key=lambda inst: inst["instance_id"])
            group_id = f"{tpl}::{operation_type}"
            group_info = {
                "group_id": group_id,
                "facility_type": tpl,
                "operation_type": operation_type,
                "instance_ids": [inst["instance_id"] for inst in members],
                "count": len(members),
            }
            self._mandatory_groups.append(group_info)
            self._groups_by_template[tpl].append(group_info)
            self._group_ord[group_id] = group_ord
            for iid in group_info["instance_ids"]:
                self._group_id_by_instance[iid] = group_id

        self.build_stats["grouped_encoding"] = {
            "mandatory_instances": len(self.instances),
            "mandatory_groups": len(self._mandatory_groups),
        }

    def build(self):
        """构建完整模型。"""
        t0 = time.time()
        self._create_variables()
        self._add_assignment_constraints()
        if self.ghost_rect:
            self._add_ghost_rect_constraints()
        self._add_set_packing_constraints()
        self._add_port_clearance_constraints()
        if not self.skip_power_coverage:
            self._add_power_coverage_constraints()
        else:
            print("⏭️ [跳过] 供电覆盖约束 (skip_power_coverage=True)")
        if self.enable_symmetry_breaking:
            self._add_symmetry_breaking_constraints()
        else:
            self.build_stats["symmetry_breaking"] = {"skipped": True}
            print("⏭️ [跳过] 对称性破除约束 (enable_symmetry_breaking=False)")
        self._add_global_valid_inequalities()
        elapsed = time.time() - t0
        print(f"📐 [模型构建] 耗时 {elapsed:.2f}s, "
              f"变量: {self.model.Proto().variables.__len__()}, "  # type: ignore
              f"约束: {self.model.Proto().constraints.__len__()}")  # type: ignore

    # ------------------------------------------
    # 1.1 变量创建
    # ------------------------------------------
    def _create_variables(self):
        for group in self._mandatory_groups:
            group_id = group["group_id"]
            tpl = group["facility_type"]
            pool = self.pools[tpl]
            num_poses = len(pool)
            group_ord = self._group_ord[group_id]

            # z_{g,p}: mandatory operation group g 是否占用位姿 p
            self.z_vars[group_id] = {}
            for p_idx in range(num_poses):
                self.z_vars[group_id][p_idx] = self.model.NewBoolVar(
                    f"zg_{group_ord}_{p_idx}"
                )

        for inst in self._optional:
            iid = inst["instance_id"]
            tpl = inst["facility_type"]
            pool = self.pools[tpl]
            num_poses = len(pool)
            inst_ord = self._instance_ord[iid]

            self.z_vars[iid] = {}
            for p_idx in range(num_poses):
                self.z_vars[iid][p_idx] = self.model.NewBoolVar(
                    f"zo_{inst_ord}_{p_idx}"
                )
            self.x_vars[iid] = self.model.NewBoolVar(f"x_{inst_ord}")

        for tpl in self._pose_optional_templates:
            pool = self.pools.get(tpl, [])
            tpl_ord = self._template_ord.get(tpl, 0)
            self.optional_pose_vars[tpl] = {}
            for p_idx in range(len(pool)):
                self.optional_pose_vars[tpl][p_idx] = self.model.NewBoolVar(
                    f"o_{tpl_ord}_{p_idx}"
                )

    # ------------------------------------------
    # 1.2 Assignment 约束 (§7.4.1)
    # ------------------------------------------
    def _add_assignment_constraints(self):
        # Mandatory operation groups: each group chooses exactly count many poses.
        for group in self._mandatory_groups:
            group_id = group["group_id"]
            self.model.Add(sum(self.z_vars[group_id].values()) == group["count"])

        # 可选实例：激活时选 1 个，未激活时 0 个
        for inst in self._optional:
            iid = inst["instance_id"]
            x_i = self.x_vars[iid]
            z_list = list(self.z_vars[iid].values())
            self.model.Add(sum(z_list) == x_i)

        for tpl in self._pose_optional_templates:
            instance_cap = sum(
                1 for inst in self.source_instances
                if not inst["is_mandatory"] and inst["facility_type"] == tpl
            )
            if instance_cap > 0:
                self.model.Add(sum(self.optional_pose_vars[tpl].values()) <= instance_cap)

    # ------------------------------------------
    # 1.3 Set Packing: 防碰撞 (§7.4.2)
    # ------------------------------------------
    def _add_set_packing_constraints(self):
        """稀疏 Set Packing: 模板级聚合避免 59M literals 爆炸。

        旧策略: 每格 AtMostOne(z[i,p] for ALL instances i covering cell)
                → 326 instances × ~36 poses/cell = ~12K vars/cell × 4900 cells = 59M literals
        新策略: 先聚合 any_active[tpl,p] = OR(z[i,p] for i ∈ instances(tpl))
                每格 AtMostOne(any_active[tpl,p]) → ~7 templates × ~20 poses/cell ≈ 140 vars/cell
                → 4900 × 140 = 686K literals (86x 压缩)

        正确性: 若 any_active[tpl,p]=1 则恰有 1 个 instance 选了 pose p (由 ExactlyOne 保证)
                AtMostOne(any_active...) 确保同一格不被两个不同(tpl,p)覆盖
        """
        import time as _time
        t0 = _time.time()

        # Phase 1: 模板级 cell → [pose_idx] 索引
        tpl_cell_index: Dict[str, Dict[int, List[int]]] = {}
        for tpl_key, pool in self.pools.items():
            cell_map: Dict[int, List[int]] = defaultdict(list)
            for p_idx, pose in enumerate(pool):
                for cell in pose["occupied_cells"]:
                    cell_key = cell[1] * 70 + cell[0]
                    cell_map[cell_key].append(p_idx)
            tpl_cell_index[tpl_key] = dict(cell_map)

        # Phase 2: 模板级聚合变量 any_active[tpl][p_idx]
        # any_active[tpl][p] = 1 iff 至少一个 tpl 类型 mandatory group / optional pose 占用了位姿 p
        self._any_active: Dict[str, Dict[int, Any]] = {}
        n_agg = 0
        for tpl_key, groups in self._groups_by_template.items():
            pool = self.pools.get(tpl_key, [])
            if not pool:
                continue
            self._any_active[tpl_key] = {}
            tpl_ord = self._template_ord.get(tpl_key, 0)
            for p_idx in range(len(pool)):
                z_list = [self.z_vars[group["group_id"]][p_idx] for group in groups]
                if len(z_list) == 1:
                    self._any_active[tpl_key][p_idx] = z_list[0]
                else:
                    agg = self.model.NewBoolVar(f"a_{tpl_ord}_{p_idx}")
                    self.model.AddMaxEquality(agg, z_list)
                    self._any_active[tpl_key][p_idx] = agg
                    n_agg += 1

        for tpl_key in self._pose_optional_templates:
            pool = self.pools.get(tpl_key, [])
            if not pool:
                continue
            self._any_active.setdefault(tpl_key, {})
            for p_idx in range(len(pool)):
                self._any_active[tpl_key][p_idx] = self.optional_pose_vars[tpl_key][p_idx]

        elapsed_agg = _time.time() - t0

        # Phase 3: 稀疏 AtMostOne (使用聚合变量)
        n_constraints = 0
        n_literals = 0
        self._solid_occupied_cell: Dict[int, Any] = {}
        cell_keys = set().union(*(cm.keys() for cm in tpl_cell_index.values()))
        cell_keys.update(self._ghost_cell_vars.keys())
        for cell_key in cell_keys:
            z_list = []
            for tpl_key, cell_map in tpl_cell_index.items():
                if cell_key not in cell_map:
                    continue
                agg_map = self._any_active.get(tpl_key, {})
                for p_idx in cell_map[cell_key]:
                    if p_idx in agg_map:
                        z_list.append(agg_map[p_idx])
            z_list.extend(self._ghost_cell_vars.get(cell_key, []))

            if z_list:
                if len(z_list) == 1:
                    self._solid_occupied_cell[cell_key] = z_list[0]
                else:
                    occ = self.model.NewBoolVar(f"oc_{cell_key}")
                    self.model.AddMaxEquality(occ, z_list)
                    self._solid_occupied_cell[cell_key] = occ

            if len(z_list) <= 1:
                continue
            self.model.AddAtMostOne(z_list)
            n_constraints += 1
            n_literals += len(z_list)

        elapsed = _time.time() - t0
        print(f"📐 [Set Packing·稀疏] {n_constraints} 约束, "
              f"{n_literals:,} literals (聚合{n_agg}变量), "
              f"耗时 {elapsed:.1f}s (聚合{elapsed_agg:.1f}s)")

    def _add_port_clearance_constraints(self):
        """Every machine port must face at least one free grid cell in the master layout."""
        n_implications = 0
        n_disabled = 0

        for tpl_key, active_map in self._any_active.items():
            pool = self.pools.get(tpl_key, [])
            for p_idx, pose_active in active_map.items():
                pose = pool[p_idx]
                front_cell_keys = set()
                feasible = True
                for port in pose.get("input_port_cells", []) + pose.get("output_port_cells", []):
                    dx, dy = DIR_DELTA[str(port["dir"])]
                    fx = int(port["x"]) + dx
                    fy = int(port["y"]) + dy
                    if not (0 <= fx < 70 and 0 <= fy < 70):
                        feasible = False
                        break
                    front_cell_keys.add(fy * 70 + fx)

                if not feasible:
                    self.model.Add(pose_active == 0)
                    n_disabled += 1
                    continue

                for cell_key in front_cell_keys:
                    occ_var = self._solid_occupied_cell.get(cell_key)
                    if occ_var is not None:
                        self.model.Add(occ_var == 0).OnlyEnforceIf(pose_active)
                        n_implications += 1

        self.build_stats["port_clearance"] = {
            "implications": n_implications,
            "disabled_poses": n_disabled,
        }
        print(
            f"📐 [端口缓冲] {n_implications} 条缓冲蕴含, "
            f"{n_disabled} 个位姿因端口出界被禁用"
        )

    # ------------------------------------------
    # 1.4 供电覆盖蕴含 (§7.4.3) - 辅助变量方案
    # ------------------------------------------
    def _add_power_coverage_constraints(self):
        """OPT-01: 模板级池化供电蕴含。

        旧策略: powered[c] = max(z[pole_j,q]) for all j,q — 31.8M 变量引用
        新策略:
          Step A: any_pose[q] = OR(z[pole_1,q], ..., z[pole_50,q]) — 4761 个聚合变量
          Step B: powered[c] = max(any_pose[q] for q covering c) — ~637K 变量引用
          Step C: z[i,p] → powered[c]=1 (不变)

        复杂度: O(50×4761) + O(4900×130) + O(269×18K×9) ≈ O(44M) vs 旧 O(78M)
        关键突破: Step B 从 31.8M 降至 637K (50x 压缩)
        """
        pole_pool = self.pools.get("power_pole", [])
        if not pole_pool:
            return

        t0 = time.time()

        # Step A: 模板级聚合 — any_pose[q] = OR(全部 pole 实例在位姿 q 的 z 变量)
        any_pose_active: Dict[int, Any] = {}
        n_agg_links = 0
        if "power_pole" in self.optional_pose_vars:
            for q_idx, var in self.optional_pose_vars["power_pole"].items():
                any_pose_active[q_idx] = var
        else:
            pole_instances = [
                i for i in self._optional if i["facility_type"] == "power_pole"
            ]
            for q_idx in range(len(pole_pool)):
                instance_z_list = [
                    self.z_vars[pi["instance_id"]][q_idx]
                    for pi in pole_instances
                ]
                if instance_z_list:
                    agg_var = self.model.NewBoolVar(f"agg_pole_q{q_idx}")
                    self.model.AddMaxEquality(agg_var, instance_z_list)
                    any_pose_active[q_idx] = agg_var
                    n_agg_links += len(instance_z_list)

        elapsed_a = time.time() - t0

        # Step B: powered[c] = max(any_pose[q] for q covering c)
        self.powered_cell: Dict[int, Any] = {}
        cell_to_covering_poses: Dict[int, set] = defaultdict(set)
        for q_idx, pose in enumerate(pole_pool):
            cov = pose.get("power_coverage_cells")
            if cov:
                for cell in cov:
                    cell_key = cell[1] * 70 + cell[0]
                    cell_to_covering_poses[cell_key].add(q_idx)

        n_cell_links = 0
        for cell_key, q_set in cell_to_covering_poses.items():
            pc = self.model.NewBoolVar(f"pwrd_{cell_key}")
            self.powered_cell[cell_key] = pc

            covering_agg = [any_pose_active[q] for q in q_set if q in any_pose_active]
            if covering_agg:
                self.model.AddMaxEquality(pc, covering_agg)
                n_cell_links += len(covering_agg)
            else:
                self.model.Add(pc == 0)

        elapsed_b = time.time() - t0

        # Step C (OPT-01 优化): 模板级预计算 + 位姿聚合
        # 旧: z[i,p] → powered[c]=1 for each c => ~9 constraints/pose => 43M total
        # 新: 预计算 all_occ_pwrd[tpl,p] = AND(powered[c]) per template-pose
        #     z[i,p] → all_occ_pwrd[tpl,p] => 1 constraint/pose => ~4.7M total
        n_imp = 0
        n_disabled = 0

        # 预计算: 每个模板的每个位姿 → (is_valid, cell_keys_list)
        tpl_pose_info: Dict[str, List] = {}  # tpl -> [(is_valid, [cell_keys])]
        for tpl in self._powered_types:
            pool = self.pools.get(tpl, [])
            pose_infos = []
            for p_idx, pose in enumerate(pool):
                cell_keys = [c[1] * 70 + c[0] for c in pose["occupied_cells"]]
                is_valid = all(ck in self.powered_cell for ck in cell_keys)
                pose_infos.append((is_valid, cell_keys))
            tpl_pose_info[tpl] = pose_infos

        # 对每个模板的有效位姿，创建聚合 AND 变量 (模板级共享)
        tpl_agg_and: Dict[str, Dict[int, Any]] = {}  # tpl -> {p_idx: and_var}
        for tpl, pose_infos in tpl_pose_info.items():
            tpl_agg_and[tpl] = {}
            for p_idx, (is_valid, cell_keys) in enumerate(pose_infos):
                if not is_valid:
                    continue
                # 创建 AND(powered[c] for c in Occ(p))
                pc_list = [self.powered_cell[ck] for ck in cell_keys]
                if len(pc_list) == 1:
                    tpl_agg_and[tpl][p_idx] = pc_list[0]
                else:
                    and_var = self.model.NewBoolVar(f"aopc_{tpl[:6]}_{p_idx}")
                    # and_var = 1 iff all powered cells = 1
                    self.model.AddMinEquality(and_var, pc_list)
                    tpl_agg_and[tpl][p_idx] = and_var

        # 每个模板-位姿只需受一次供电约束：
        # 一旦该位姿被任一实例（或 pose-level optional）占用，则其占格必须全被供电。
        for tpl in self._powered_types:
            pose_infos = tpl_pose_info.get(tpl, [])
            agg_map = tpl_agg_and.get(tpl, {})
            any_active_map = self._any_active.get(tpl, {})
            for p_idx, (is_valid, _) in enumerate(pose_infos):
                pose_active = any_active_map.get(p_idx)
                if pose_active is None:
                    continue
                if not is_valid:
                    self.model.Add(pose_active == 0)
                    n_disabled += 1
                    continue
                and_var = agg_map[p_idx]
                self.model.Add(and_var == 1).OnlyEnforceIf(pose_active)
                n_imp += 1

        self._power_pose_info = tpl_pose_info
        self._power_pose_and = tpl_agg_and

        elapsed = time.time() - t0
        n_aux = len(self.powered_cell)
        n_agg = len(any_pose_active)
        n_and = sum(len(v) for v in tpl_agg_and.values())
        self.build_stats["power_coverage"] = {
            "aggregate_pose_vars": n_agg,
            "and_vars": n_and,
            "powered_cells": n_aux,
            "cell_links": n_cell_links,
            "implications": n_imp,
            "disabled_poses": n_disabled,
        }
        print(f"📐 [供电蕴含·OPT-01] {n_agg} 聚合变量, {n_and} AND变量, "
              f"{n_aux} powered格, {n_cell_links} 格链接, "
              f"{n_imp} 蕴含约束, {n_disabled} 位姿禁用, "
              f"StepA={elapsed_a:.1f}s, 总耗时={elapsed:.1f}s")

    # ------------------------------------------
    # 1.5 对称性破除 (§7.5)
    # ------------------------------------------
    def _add_symmetry_breaking_constraints(self):
        """Grouped encoding already removes permutation symmetry among mandatory clones."""
        order_constraints = 0
        index_link_terms = 0

        # 可选实例瀑布式激活: x_k ≥ x_{k+1}
        optional_by_type: Dict[str, List[str]] = defaultdict(list)
        for inst in self._optional:
            optional_by_type[inst["facility_type"]].append(inst["instance_id"])

        for tpl, ids in optional_by_type.items():
            ids_sorted = sorted(ids)
            for k in range(len(ids_sorted) - 1):
                self.model.Add(
                    self.x_vars[ids_sorted[k]] >= self.x_vars[ids_sorted[k + 1]]
                )
                order_constraints += 1
        self.build_stats["symmetry_breaking"] = {
            "index_link_terms": index_link_terms,
            "order_constraints": order_constraints,
        }

    # ------------------------------------------
    # 1.6 全局有效不等式 (§7.6)
    # ------------------------------------------
    def _add_global_valid_inequalities(self):
        """供电桩最少数量下界。"""
        # 全场需电机器总占地面积
        total_powered_cells = 0
        for inst in self.instances:
            tpl = inst["facility_type"]
            if tpl in self._powered_types:
                dims = self.templates[tpl]["dimensions"]
                total_powered_cells += dims["w"] * dims["h"]

        max_coverage = 144  # 12×12
        min_poles = -(-total_powered_cells // max_coverage)  # ceil division

        if "power_pole" in self.optional_pose_vars:
            pole_vars = list(self.optional_pose_vars["power_pole"].values())
        else:
            pole_instances = [
                i for i in self._optional if i["facility_type"] == "power_pole"
            ]
            pole_vars = [self.x_vars[i["instance_id"]] for i in pole_instances]

        self.model.Add(sum(pole_vars) >= min_poles)
        print(f"📐 [全局割] 供电桩下界: ≥ {min_poles} (覆盖 {total_powered_cells} 格)")

    # ------------------------------------------
    # 1.7 幽灵空地 (§7.4.1 u_r)
    # ------------------------------------------
    def _add_ghost_rect_constraints(self):
        """幽灵空地矩形必须单选一个位置，且与所有刚体互斥。"""
        from src.placement.placement_generator import generate_empty_rect_domain

        w, h = self.ghost_rect
        domains = generate_empty_rect_domain(w, h)
        self._ghost_domains = domains
        print(f"📐 [幽灵空地] {w}×{h} 矩形, {len(domains)} 个候选位置")

        # 创建 u_r 变量
        for r_idx in range(len(domains)):
            self.u_vars[r_idx] = self.model.NewBoolVar(f"u_{r_idx}")

        # 恰好选 1 个位置
        self.model.AddExactlyOne(list(self.u_vars.values()))

        # 构建 ghost cell → [u_r] 索引 (供 set_packing 使用)
        self._ghost_cell_vars.clear()
        for r_idx, domain in enumerate(domains):
            for cell in domain["occupied_cells"]:
                cell_key = cell[1] * 70 + cell[0]
                self._ghost_cell_vars[cell_key].append(self.u_vars[r_idx])

    # ------------------------------------------
    # 2. 求解与切平面接口
    # ------------------------------------------
    def _infer_optional_template_from_solution_id(self, solution_id: str) -> Optional[str]:
        for tpl, prefix in POSE_LEVEL_OPTIONAL_PREFIX.items():
            if solution_id.startswith(f"{prefix}_"):
                return tpl
        return None

    def _solve_power_pole_hint_subproblem(
        self,
        occupied_cells: Set[Tuple[int, int]],
        reserved_front_cells: Set[Tuple[int, int]],
        powered_targets: Set[Tuple[int, int]],
        time_limit_seconds: float = 2.0,
    ) -> Dict[str, Any]:
        if self.skip_power_coverage or not powered_targets:
            return {
                "status": "TRIVIAL",
                "selected_pose_indices": [],
                "unreachable_cell": None,
            }

        pole_pool = self.pools.get("power_pole", [])
        if not pole_pool:
            return {
                "status": "UNREACHABLE",
                "selected_pose_indices": [],
                "unreachable_cell": min(powered_targets),
            }

        pole_cap = sum(
            1 for inst in self.source_instances
            if not inst["is_mandatory"] and inst["facility_type"] == "power_pole"
        )
        if pole_cap <= 0:
            return {
                "status": "UNREACHABLE",
                "selected_pose_indices": [],
                "unreachable_cell": min(powered_targets),
            }

        submodel = cp_model.CpModel()
        pose_vars: Dict[int, Any] = {}
        cell_cover_vars: Dict[Tuple[int, int], List[Any]] = defaultdict(list)
        occupied_cell_vars: Dict[Tuple[int, int], List[Any]] = defaultdict(list)

        for p_idx, pose in enumerate(pole_pool):
            pose_cells = {
                (int(cell[0]), int(cell[1]))
                for cell in pose.get("occupied_cells", [])
            }
            if pose_cells & occupied_cells:
                continue
            if pose_cells & reserved_front_cells:
                continue

            var = submodel.NewBoolVar(f"hp_{p_idx}")
            pose_vars[p_idx] = var
            for cell in pose_cells:
                occupied_cell_vars[cell].append(var)
            for cell in pose.get("power_coverage_cells", []):
                cell_cover_vars[(int(cell[0]), int(cell[1]))].append(var)

        for vars_for_cell in occupied_cell_vars.values():
            if len(vars_for_cell) > 1:
                submodel.AddAtMostOne(vars_for_cell)

        for cell in powered_targets:
            cover_vars = cell_cover_vars.get(cell, [])
            if not cover_vars:
                return {
                    "status": "UNREACHABLE",
                    "selected_pose_indices": [],
                    "unreachable_cell": cell,
                }
            submodel.Add(sum(cover_vars) >= 1)

        submodel.Add(sum(pose_vars.values()) <= pole_cap)
        submodel.Minimize(sum(pose_vars.values()))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit_seconds
        solver.parameters.num_workers = 8
        solver.parameters.cp_model_probing_level = 0
        status = solver.Solve(submodel)

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            selected = [
                p_idx for p_idx, var in pose_vars.items()
                if solver.Value(var) == 1
            ]
            return {
                "status": "FEASIBLE",
                "selected_pose_indices": selected,
                "unreachable_cell": None,
            }

        return {
            "status": solver.StatusName(status),
            "selected_pose_indices": [],
            "unreachable_cell": None,
        }

    def build_greedy_solution_hint(self) -> Dict[str, int]:
        if self._greedy_hint_cache is not None:
            return dict(self._greedy_hint_cache)

        def _group_priority(group: Dict[str, Any]) -> Tuple[int, int, int, str]:
            tpl = group["facility_type"]
            dims = self.templates[tpl]["dimensions"]
            area = int(dims["w"]) * int(dims["h"])
            special = 0
            if tpl == "boundary_storage_port":
                special = -3
            elif tpl == "protocol_core":
                special = -2
            elif tpl == "manufacturing_5x5":
                special = -1
            return (special, -area, len(self.pools[tpl]), group["group_id"])

        def _domain_anchor(domain: Dict[str, Any]) -> Tuple[int, int]:
            anchor = domain.get("anchor")
            if anchor:
                return int(anchor["x"]), int(anchor["y"])
            xs = [int(c[0]) for c in domain["occupied_cells"]]
            ys = [int(c[1]) for c in domain["occupied_cells"]]
            return min(xs), min(ys)

        pole_cover_count: Dict[Tuple[int, int], int] = defaultdict(int)
        pole_footprint_count: Dict[Tuple[int, int], int] = defaultdict(int)
        for pole_pose in self.pools.get("power_pole", []):
            for cell in pole_pose.get("power_coverage_cells", []):
                pole_cover_count[(int(cell[0]), int(cell[1]))] += 1
            for cell in pole_pose.get("occupied_cells", []):
                pole_footprint_count[(int(cell[0]), int(cell[1]))] += 1

        def _pose_candidate_order(tpl: str) -> List[int]:
            pool = self.pools[tpl]
            if tpl == "boundary_storage_port":
                return list(range(len(pool)))

            dims = self.templates[tpl]["dimensions"]
            width = int(dims["w"])
            height = int(dims["h"])

            def _pose_score(p_idx: int) -> Tuple[Any, ...]:
                pose = pool[p_idx]
                ax, ay = _domain_anchor(pose)
                cx = ax + width / 2.0
                cy = ay + height / 2.0
                center_distance = abs(cx - 35.0) + abs(cy - 35.0)
                border_slack = min(cx, cy, 69.0 - cx, 69.0 - cy)
                occupied_cells = _cell_set(pose, "occupied_cells")
                coverability_min = min(
                    (pole_cover_count[cell] for cell in occupied_cells),
                    default=0,
                )
                coverability_sum = sum(
                    pole_cover_count[cell] for cell in occupied_cells
                )
                pole_block_cost = sum(
                    pole_footprint_count[cell] for cell in occupied_cells
                )

                if self.templates[tpl].get("needs_power", False):
                    return (
                        -coverability_min,
                        -coverability_sum,
                        pole_block_cost,
                        center_distance,
                        -border_slack,
                        ay,
                        ax,
                    )

                return (
                    pole_block_cost,
                    center_distance,
                    -border_slack,
                    ay,
                    ax,
                )

            return sorted(range(len(pool)), key=_pose_score)

        def _cell_set(pose: Dict[str, Any], key: str) -> Set[Tuple[int, int]]:
            return {
                (int(cell[0]), int(cell[1]))
                for cell in (pose.get(key) or [])
            }

        def _front_cells(pose: Dict[str, Any]) -> Tuple[bool, Set[Tuple[int, int]]]:
            front_cells: Set[Tuple[int, int]] = set()
            for port in pose.get("input_port_cells", []) + pose.get("output_port_cells", []):
                dx, dy = DIR_DELTA[str(port["dir"])]
                fx = int(port["x"]) + dx
                fy = int(port["y"]) + dy
                if not (0 <= fx < 70 and 0 <= fy < 70):
                    return False, set()
                front_cells.add((fx, fy))
            return True, front_cells

        def _power_pole_cap() -> int:
            return sum(
                1 for inst in self.source_instances
                if not inst["is_mandatory"] and inst["facility_type"] == "power_pole"
            )

        def _min_required_power_poles() -> int:
            total_powered_cells = 0
            for inst in self.instances:
                tpl = inst["facility_type"]
                if not self.templates[tpl].get("needs_power", False):
                    continue
                dims = self.templates[tpl]["dimensions"]
                total_powered_cells += int(dims["w"]) * int(dims["h"])
            if total_powered_cells <= 0:
                return 0
            max_coverage = 144  # 12x12
            return -(-total_powered_cells // max_coverage)

        def _select_power_poles(
            occupied_cells: Set[Tuple[int, int]],
            reserved_front_cells: Set[Tuple[int, int]],
            powered_targets: Set[Tuple[int, int]],
        ) -> Tuple[List[int], int]:
            if self.skip_power_coverage or not powered_targets:
                return [], 0

            pole_pool = self.pools.get("power_pole", [])
            cap = _power_pole_cap()
            if not pole_pool or cap <= 0:
                return [], len(powered_targets)

            local_occupied = set(occupied_cells)
            local_reserved = set(reserved_front_cells)
            uncovered = set(powered_targets)
            chosen_pose_indices: List[int] = []
            chosen_set = set()
            desired_count = min(_min_required_power_poles(), cap)

            while uncovered and len(chosen_pose_indices) < desired_count:
                best_choice = None
                best_score = None

                for p_idx, pose in enumerate(pole_pool):
                    if p_idx in chosen_set:
                        continue
                    pose_cells = _cell_set(pose, "occupied_cells")
                    fronts_ok, front_cells = _front_cells(pose)
                    if not fronts_ok:
                        continue
                    if pose_cells & local_occupied:
                        continue
                    if pose_cells & local_reserved:
                        continue
                    if front_cells & local_occupied:
                        continue

                    covered = _cell_set(pose, "power_coverage_cells") & uncovered
                    if not covered:
                        continue

                    anchor_x, anchor_y = _domain_anchor(pose)
                    score = (len(covered), -anchor_y, -anchor_x)
                    if best_score is None or score > best_score:
                        best_score = score
                        best_choice = (p_idx, pose_cells, front_cells, covered)

                if best_choice is None:
                    break

                p_idx, pose_cells, front_cells, covered = best_choice
                chosen_pose_indices.append(p_idx)
                chosen_set.add(p_idx)
                local_occupied.update(pose_cells)
                local_reserved.update(front_cells)
                uncovered.difference_update(covered)

            while len(chosen_pose_indices) < desired_count:
                best_choice = None
                best_score = None

                for p_idx, pose in enumerate(pole_pool):
                    if p_idx in chosen_set:
                        continue
                    pose_cells = _cell_set(pose, "occupied_cells")
                    fronts_ok, front_cells = _front_cells(pose)
                    if not fronts_ok:
                        continue
                    if pose_cells & local_occupied:
                        continue
                    if pose_cells & local_reserved:
                        continue
                    if front_cells & local_occupied:
                        continue

                    anchor_x, anchor_y = _domain_anchor(pose)
                    coverage_score = len(_cell_set(pose, "power_coverage_cells") & powered_targets)
                    score = (coverage_score, -anchor_y, -anchor_x)
                    if best_score is None or score > best_score:
                        best_score = score
                        best_choice = (p_idx, pose_cells, front_cells)

                if best_choice is None:
                    break

                p_idx, pose_cells, front_cells = best_choice
                chosen_pose_indices.append(p_idx)
                chosen_set.add(p_idx)
                local_occupied.update(pose_cells)
                local_reserved.update(front_cells)

            return chosen_pose_indices, len(uncovered)

        group_by_id = {
            group["group_id"]: group
            for group in self._mandatory_groups
        }
        pose_candidate_orders = {
            group["facility_type"]: _pose_candidate_order(group["facility_type"])
            for group in self._mandatory_groups
        }
        pole_pose_cells = [
            _cell_set(pose, "occupied_cells")
            for pose in self.pools.get("power_pole", [])
        ]
        pole_pose_cover_cells = [
            _cell_set(pose, "power_coverage_cells")
            for pose in self.pools.get("power_pole", [])
        ]

        def _materialize_group_selection(
            group_pose_selection: Dict[str, List[int]],
            ghost_idx: Optional[int],
        ) -> Optional[Dict[str, Any]]:
            occupied_cells: Set[Tuple[int, int]] = set()
            reserved_front_cells: Set[Tuple[int, int]] = set()
            powered_targets: Set[Tuple[int, int]] = set()
            occupied_owner: Dict[Tuple[int, int], str] = {}
            reserved_owner: Dict[Tuple[int, int], Set[str]] = defaultdict(set)
            hint: Dict[str, int] = {}
            placed_instances = 0

            if ghost_idx is not None:
                for cell in self._ghost_domains[ghost_idx]["occupied_cells"]:
                    xy = (int(cell[0]), int(cell[1]))
                    occupied_cells.add(xy)
                    occupied_owner[xy] = "__ghost__"

            for group in sorted(self._mandatory_groups, key=_group_priority):
                tpl = group["facility_type"]
                chosen = list(group_pose_selection.get(group["group_id"], []))
                if len(chosen) != group["count"]:
                    return None

                for p_idx in chosen:
                    pose = self.pools[tpl][p_idx]
                    cells = _cell_set(pose, "occupied_cells")
                    fronts_ok, front_cells = _front_cells(pose)
                    if not fronts_ok:
                        return None
                    if occupied_cells & cells:
                        return None
                    if reserved_front_cells & cells:
                        return None
                    if occupied_cells & front_cells:
                        return None

                    occupied_cells.update(cells)
                    for cell in cells:
                        occupied_owner[cell] = group["group_id"]
                    for cell in front_cells:
                        reserved_front_cells.add(cell)
                        reserved_owner[cell].add(group["group_id"])
                    if self.templates[tpl].get("needs_power", False):
                        powered_targets.update(cells)

                chosen_sorted = sorted(
                    chosen,
                    key=lambda p_idx: self.pools[tpl][p_idx]["pose_id"],
                )
                for iid, p_idx in zip(group["instance_ids"], chosen_sorted):
                    hint[iid] = p_idx
                placed_instances += len(chosen_sorted)

            if ghost_idx is not None:
                hint["__ghost__"] = ghost_idx

            return {
                "occupied_cells": occupied_cells,
                "reserved_front_cells": reserved_front_cells,
                "powered_targets": powered_targets,
                "occupied_owner": occupied_owner,
                "reserved_owner": reserved_owner,
                "hint": hint,
                "placed_instances": placed_instances,
            }

        def _analyze_power_reachability(
            layout: Dict[str, Any],
        ) -> Dict[str, Any]:
            coverable_cells: Set[Tuple[int, int]] = set()
            occupied_cells = layout["occupied_cells"]
            reserved_front_cells = layout["reserved_front_cells"]

            for pose_cells, cover_cells in zip(pole_pose_cells, pole_pose_cover_cells):
                if pose_cells & occupied_cells:
                    continue
                if pose_cells & reserved_front_cells:
                    continue
                coverable_cells.update(cover_cells)

            missing_cells = sorted(layout["powered_targets"] - coverable_cells)
            first_missing = missing_cells[0] if missing_cells else None
            blocking_groups: List[str] = []
            if first_missing is not None:
                groups = set()
                for pose_cells, cover_cells in zip(pole_pose_cells, pole_pose_cover_cells):
                    if first_missing not in cover_cells:
                        continue
                    overlap_occ = pose_cells & occupied_cells
                    overlap_res = pose_cells & reserved_front_cells
                    if not overlap_occ and not overlap_res:
                        continue
                    for cell in overlap_occ:
                        groups.add(layout["occupied_owner"][cell])
                    for cell in overlap_res:
                        groups.update(layout["reserved_owner"][cell])
                blocking_groups = sorted(groups)

            return {
                "coverable_count": len(layout["powered_targets"] & coverable_cells),
                "powered_count": len(layout["powered_targets"]),
                "first_missing": first_missing,
                "blocking_groups": blocking_groups,
            }

        def _repair_group_selection_for_power(
            group_pose_selection: Dict[str, List[int]],
            ghost_idx: Optional[int],
        ) -> Tuple[Dict[str, List[int]], Dict[str, Any], Dict[str, Any]]:
            layout = _materialize_group_selection(group_pose_selection, ghost_idx)
            if layout is None:
                return group_pose_selection, {}, {
                    "coverable_count": 0,
                    "powered_count": 0,
                    "first_missing": None,
                    "blocking_groups": [],
                }

            analysis = _analyze_power_reachability(layout)
            for _ in range(2):
                if analysis["first_missing"] is None:
                    break

                best_selection = None
                best_layout = None
                best_analysis = None
                best_score = None

                for group_id in analysis["blocking_groups"][:6]:
                    if group_id == "__ghost__":
                        continue
                    group = group_by_id.get(group_id)
                    if group is None:
                        continue
                    tpl = group["facility_type"]
                    selected = list(group_pose_selection[group_id])
                    order = pose_candidate_orders[tpl]

                    for old_idx in selected:
                        old_anchor_x, old_anchor_y = _domain_anchor(self.pools[tpl][old_idx])
                        alternatives = []
                        for p_idx in order:
                            if p_idx == old_idx:
                                continue
                            if p_idx in selected and p_idx != old_idx:
                                continue
                            anchor_x, anchor_y = _domain_anchor(self.pools[tpl][p_idx])
                            move = abs(anchor_x - old_anchor_x) + abs(anchor_y - old_anchor_y)
                            if move > 6:
                                continue
                            alternatives.append((move, p_idx))

                        for move, alt_idx in alternatives[:24]:
                            trial_selection = {
                                gid: list(pose_list)
                                for gid, pose_list in group_pose_selection.items()
                            }
                            trial_group = list(trial_selection[group_id])
                            trial_group[trial_group.index(old_idx)] = alt_idx
                            trial_selection[group_id] = trial_group

                            trial_layout = _materialize_group_selection(
                                trial_selection,
                                ghost_idx,
                            )
                            if trial_layout is None:
                                continue

                            trial_analysis = _analyze_power_reachability(trial_layout)
                            if trial_analysis["coverable_count"] <= analysis["coverable_count"]:
                                continue

                            score = (
                                trial_analysis["coverable_count"],
                                1 if trial_analysis["first_missing"] is None else 0,
                                -move,
                            )
                            if best_score is None or score > best_score:
                                best_score = score
                                best_selection = trial_selection
                                best_layout = trial_layout
                                best_analysis = trial_analysis

                if best_selection is None or best_layout is None or best_analysis is None:
                    break

                group_pose_selection = best_selection
                layout = best_layout
                analysis = best_analysis

            return group_pose_selection, layout, analysis

        beam_width = 3
        group_seed_limit = 3
        branch_group_budget = 4

        def _state_signature(state: Dict[str, Any]) -> Tuple[Tuple[str, Tuple[int, ...]], ...]:
            return tuple(
                (
                    group["group_id"],
                    tuple(state["group_pose_selection"].get(group["group_id"], [])),
                )
                for group in sorted(self._mandatory_groups, key=_group_priority)
            )

        def _state_score(state: Dict[str, Any]) -> Tuple[int, int, int, int, int]:
            return (
                int(state["placed_instances"]),
                int(state["completed_groups"]),
                int(state["power_coverability_sum"]),
                -len(state["reserved_front_cells"]),
                -len(state["occupied_cells"]),
            )

        def _clone_state(state: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "occupied_cells": set(state["occupied_cells"]),
                "reserved_front_cells": set(state["reserved_front_cells"]),
                "powered_targets": set(state["powered_targets"]),
                "hint": dict(state["hint"]),
                "group_pose_selection": {
                    gid: list(pose_list)
                    for gid, pose_list in state["group_pose_selection"].items()
                },
                "placed_instances": int(state["placed_instances"]),
                "completed_groups": int(state["completed_groups"]),
                "power_coverability_sum": int(state["power_coverability_sum"]),
            }

        def _make_initial_state(ghost_idx: Optional[int]) -> Dict[str, Any]:
            occupied_cells: Set[Tuple[int, int]] = set()
            hint: Dict[str, int] = {}
            if ghost_idx is not None:
                for cell in self._ghost_domains[ghost_idx]["occupied_cells"]:
                    occupied_cells.add((int(cell[0]), int(cell[1])))
                hint["__ghost__"] = ghost_idx
            return {
                "occupied_cells": occupied_cells,
                "reserved_front_cells": set(),
                "powered_targets": set(),
                "hint": hint,
                "group_pose_selection": {},
                "placed_instances": 0,
                "completed_groups": 0,
                "power_coverability_sum": 0,
            }

        def _pose_fits_state(state: Dict[str, Any], pose: Dict[str, Any]) -> bool:
            cells = _cell_set(pose, "occupied_cells")
            fronts_ok, front_cells = _front_cells(pose)
            if not fronts_ok:
                return False
            if state["occupied_cells"] & cells:
                return False
            if state["reserved_front_cells"] & cells:
                return False
            if state["occupied_cells"] & front_cells:
                return False
            return True

        def _extend_state_with_group(
            state: Dict[str, Any],
            group: Dict[str, Any],
            forced_first_idx: Optional[int] = None,
        ) -> Dict[str, Any]:
            tpl = group["facility_type"]
            order = pose_candidate_orders[tpl]
            new_state = _clone_state(state)
            chosen: List[int] = []
            chosen_set: Set[int] = set()

            candidate_order: List[int] = []
            if forced_first_idx is not None:
                candidate_order.append(int(forced_first_idx))
            candidate_order.extend(order)

            for p_idx in candidate_order:
                p_idx = int(p_idx)
                if p_idx in chosen_set:
                    continue
                pose = self.pools[tpl][p_idx]
                if not _pose_fits_state(new_state, pose):
                    continue

                cells = _cell_set(pose, "occupied_cells")
                _, front_cells = _front_cells(pose)
                chosen.append(p_idx)
                chosen_set.add(p_idx)
                new_state["occupied_cells"].update(cells)
                new_state["reserved_front_cells"].update(front_cells)
                if self.templates[tpl].get("needs_power", False):
                    new_state["powered_targets"].update(cells)
                    new_state["power_coverability_sum"] += sum(
                        pole_cover_count[cell] for cell in cells
                    )
                if len(chosen) == group["count"]:
                    break

            chosen.sort(key=lambda p_idx: self.pools[tpl][p_idx]["pose_id"])
            new_state["group_pose_selection"][group["group_id"]] = list(chosen)
            for iid, p_idx in zip(group["instance_ids"], chosen):
                new_state["hint"][iid] = p_idx
            new_state["placed_instances"] += len(chosen)
            if len(chosen) == group["count"]:
                new_state["completed_groups"] += 1
            return new_state

        def _prune_states(states: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            best_by_signature: Dict[Tuple[Tuple[str, Tuple[int, ...]], ...], Dict[str, Any]] = {}
            for state in states:
                signature = _state_signature(state)
                incumbent = best_by_signature.get(signature)
                if incumbent is None or _state_score(state) > _state_score(incumbent):
                    best_by_signature[signature] = state
            ranked = sorted(
                best_by_signature.values(),
                key=_state_score,
                reverse=True,
            )
            return ranked[:beam_width]

        def _build_state_for_ghost(ghost_idx: Optional[int]) -> Dict[str, Any]:
            beam: List[Dict[str, Any]] = [_make_initial_state(ghost_idx)]
            branched_groups = 0

            for group in sorted(self._mandatory_groups, key=_group_priority):
                next_states: List[Dict[str, Any]] = []
                tpl = group["facility_type"]
                should_branch = (
                    branched_groups < branch_group_budget
                    and (
                        group["count"] >= 6
                        or tpl in {
                            "boundary_storage_port",
                            "protocol_core",
                            "manufacturing_5x5",
                        }
                    )
                )

                for state in beam:
                    next_states.append(_extend_state_with_group(state, group))

                    if should_branch:
                        feasible_starts: List[int] = []
                        for p_idx in pose_candidate_orders[tpl]:
                            if not _pose_fits_state(state, self.pools[tpl][p_idx]):
                                continue
                            feasible_starts.append(int(p_idx))
                            if len(feasible_starts) >= group_seed_limit:
                                break

                        for p_idx in feasible_starts[1:]:
                            next_states.append(_extend_state_with_group(state, group, p_idx))

                beam = _prune_states(next_states)
                if should_branch:
                    branched_groups += 1

            return max(beam, key=_state_score)

        candidate_ghost_indices = [None]
        if self._ghost_domains:
            anchor_to_idx = {
                _domain_anchor(domain): idx
                for idx, domain in enumerate(self._ghost_domains)
            }
            w, h = self.ghost_rect or (0, 0)
            trial_anchors = [
                (0, 0),
                (0, 70 - h),
                (70 - w, 0),
                (70 - w, 70 - h),
                ((70 - w) // 2, (70 - h) // 2),
            ]
            candidate_ghost_indices = []
            seen = set()
            for anchor in trial_anchors:
                idx = anchor_to_idx.get(anchor)
                if idx is not None and idx not in seen:
                    candidate_ghost_indices.append(idx)
                    seen.add(idx)
            if self._ghost_domains:
                last_idx = len(self._ghost_domains) - 1
                if last_idx not in seen:
                    candidate_ghost_indices.append(last_idx)
            if not candidate_ghost_indices:
                candidate_ghost_indices = [None]

        best_hint: Dict[str, int] = {}
        best_count = -1
        best_ghost_idx = None
        best_power_pose_indices: List[int] = []
        best_uncovered_power_cells = 0
        best_power_status = "SKIPPED"
        best_unreachable_power_cell = None
        best_completed_groups = 0

        for ghost_idx in candidate_ghost_indices:
            candidate_state = _build_state_for_ghost(ghost_idx)
            occupied = set(candidate_state["occupied_cells"])
            reserved_front_cells = set(candidate_state["reserved_front_cells"])
            powered_targets = set(candidate_state["powered_targets"])
            group_pose_selection = {
                gid: list(pose_list)
                for gid, pose_list in candidate_state["group_pose_selection"].items()
            }
            hint = dict(candidate_state["hint"])
            placed_instances = int(candidate_state["placed_instances"])
            completed_groups = int(candidate_state["completed_groups"])

            repair_analysis = {
                "coverable_count": 0,
                "powered_count": len(powered_targets),
                "first_missing": None,
                "blocking_groups": [],
            }
            if placed_instances == len(self.instances):
                (
                    group_pose_selection,
                    repaired_layout,
                    repair_analysis,
                ) = _repair_group_selection_for_power(
                    group_pose_selection,
                    ghost_idx,
                )
                if repaired_layout:
                    occupied = repaired_layout["occupied_cells"]
                    reserved_front_cells = repaired_layout["reserved_front_cells"]
                    powered_targets = repaired_layout["powered_targets"]
                    hint = repaired_layout["hint"]
                    placed_instances = repaired_layout["placed_instances"]
                    completed_groups = len(self._mandatory_groups)

            power_hint = self._solve_power_pole_hint_subproblem(
                occupied,
                reserved_front_cells,
                powered_targets,
            )
            if power_hint["status"] == "FEASIBLE":
                power_pose_indices = list(power_hint["selected_pose_indices"])
                uncovered_power_cells = 0
            else:
                power_pose_indices, uncovered_power_cells = _select_power_poles(
                    occupied,
                    reserved_front_cells,
                    powered_targets,
                )
            candidate_score = (
                placed_instances,
                1 if power_hint["status"] == "FEASIBLE" else 0,
                -uncovered_power_cells,
                -len(power_pose_indices),
            )
            best_score = (
                best_count,
                1 if best_power_status == "FEASIBLE" else 0,
                -best_uncovered_power_cells,
                -len(best_power_pose_indices),
            )
            if candidate_score > best_score:
                best_hint = hint
                best_count = placed_instances
                best_ghost_idx = ghost_idx
                best_power_pose_indices = list(power_pose_indices)
                best_uncovered_power_cells = uncovered_power_cells
                best_power_status = str(power_hint["status"])
                best_unreachable_power_cell = power_hint.get("unreachable_cell")
                best_completed_groups = completed_groups
                self.build_stats["greedy_hint_repair"] = {
                    "coverable_power_cells": repair_analysis["coverable_count"],
                    "powered_cells": repair_analysis["powered_count"],
                    "first_missing": repair_analysis["first_missing"],
                    "blocking_groups": repair_analysis["blocking_groups"][:6],
                }

        if best_ghost_idx is not None:
            best_hint["__ghost__"] = best_ghost_idx
        for pole_ord, p_idx in enumerate(best_power_pose_indices):
            best_hint[f"power_pole_hint_{pole_ord:03d}"] = p_idx

        self.build_stats["greedy_hint"] = {
            "hinted_instances": max(best_count, 0),
            "ghost_pose_idx": best_ghost_idx,
            "hinted_power_poles": len(best_power_pose_indices),
            "uncovered_power_cells": best_uncovered_power_cells,
            "power_hint_status": best_power_status,
            "unreachable_power_cell": best_unreachable_power_cell,
            "completed_groups": best_completed_groups,
            "beam_width": beam_width,
            "group_seed_limit": group_seed_limit,
            "branch_group_budget": branch_group_budget,
        }
        self._greedy_hint_cache = dict(best_hint)
        return dict(best_hint)

    def _add_exact_decision_strategies(self):
        if self._exact_search_strategy_added:
            return

        hint = self.build_greedy_solution_hint()

        def _split_vars(
            var_map: Dict[int, Any],
            preferred_indices: List[int],
        ) -> Tuple[List[Any], List[Any]]:
            preferred_vars: List[Any] = []
            preferred_set = set()
            for idx in preferred_indices:
                idx = int(idx)
                if idx in var_map and idx not in preferred_set:
                    preferred_vars.append(var_map[idx])
                    preferred_set.add(idx)
            remaining_vars = [
                var_map[idx]
                for idx in sorted(var_map.keys())
                if idx not in preferred_set
            ]
            return preferred_vars, remaining_vars

        preferred_group_vars: List[Any] = []
        remaining_group_zero_vars: List[Any] = []
        remaining_group_fill_vars: List[Any] = []
        for group in self._mandatory_groups:
            preferred = [
                int(hint[iid])
                for iid in group["instance_ids"]
                if iid in hint
            ]
            preferred_vars, remaining_vars = _split_vars(
                self.z_vars[group["group_id"]],
                preferred,
            )
            preferred_group_vars.extend(preferred_vars)
            if len(preferred_vars) < group["count"]:
                remaining_group_fill_vars.extend(remaining_vars)
            else:
                remaining_group_zero_vars.extend(remaining_vars)

        preferred_optional_vars: List[Any] = []
        remaining_optional_vars: List[Any] = []
        for tpl in sorted(self.optional_pose_vars.keys()):
            preferred = [
                int(p_idx)
                for hint_id, p_idx in hint.items()
                if self._infer_optional_template_from_solution_id(str(hint_id)) == tpl
            ]
            preferred_vars, remaining_vars = _split_vars(
                self.optional_pose_vars[tpl],
                preferred,
            )
            preferred_optional_vars.extend(preferred_vars)
            remaining_optional_vars.extend(remaining_vars)

        preferred_ghost_vars: List[Any] = []
        remaining_ghost_vars: List[Any] = []
        if self.u_vars:
            preferred = [int(hint["__ghost__"])] if "__ghost__" in hint else []
            preferred_ghost_vars, remaining_ghost_vars = _split_vars(self.u_vars, preferred)

        if preferred_ghost_vars:
            self.model.AddDecisionStrategy(
                preferred_ghost_vars,
                cp_model.CHOOSE_FIRST,
                cp_model.SELECT_MAX_VALUE,
            )

        if preferred_group_vars:
            self.model.AddDecisionStrategy(
                preferred_group_vars,
                cp_model.CHOOSE_FIRST,
                cp_model.SELECT_MAX_VALUE,
            )

        if remaining_group_fill_vars:
            self.model.AddDecisionStrategy(
                remaining_group_fill_vars,
                cp_model.CHOOSE_FIRST,
                cp_model.SELECT_MAX_VALUE,
            )

        if preferred_optional_vars:
            self.model.AddDecisionStrategy(
                preferred_optional_vars,
                cp_model.CHOOSE_FIRST,
                cp_model.SELECT_MAX_VALUE,
            )

        skipped_zero_tail_vars = (
            len(remaining_group_zero_vars)
            + len(remaining_optional_vars)
            + len(remaining_ghost_vars)
        )
        self.build_stats["exact_search_strategy"] = {
            "guided_group_vars": len(preferred_group_vars),
            "guided_optional_vars": len(preferred_optional_vars),
            "guided_ghost_vars": len(preferred_ghost_vars),
            "guided_group_fill_vars": len(remaining_group_fill_vars),
            "skipped_group_zero_vars": len(remaining_group_zero_vars),
            "skipped_optional_zero_vars": len(remaining_optional_vars),
            "skipped_ghost_zero_vars": len(remaining_ghost_vars),
            "skipped_zero_tail_vars": skipped_zero_tail_vars,
            "search_branching": "PARTIAL_FIXED_SEARCH",
            "strategy_sequence": [
                "preferred_ghost",
                "preferred_group",
                "remaining_group_fill",
                "preferred_optional",
            ],
        }

        self._exact_search_strategy_added = True

    def solve(
        self,
        time_limit_seconds: float = 300.0,
        solution_hint: Optional[Dict[str, int]] = None,
        known_feasible_hint: bool = False,
    ) -> cp_model.CpSolverStatus:
        """求解主模型。"""
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit_seconds
        solver.parameters.log_search_progress = True
        solver.parameters.cp_model_probing_level = 0  # 跳过冗余probing轮次

        if self.exact_mode:
            if solution_hint is None:
                solution_hint = self.build_greedy_solution_hint()
            # Exact path: guide the high-value prefix, then let CP-SAT branch freely on
            # the massive zero tail instead of forcing a brittle full fixed search.
            self._add_exact_decision_strategies()
            solver.parameters.num_workers = 1
            solver.parameters.cp_model_presolve = False
            solver.parameters.symmetry_level = 0
            solver.parameters.linearization_level = 0
            solver.parameters.search_branching = cp_model.PARTIAL_FIXED_SEARCH
        else:
            solver.parameters.num_workers = 4
            # 当前主问题是超大规模 SAT 可行性模型；默认 presolve 会先吃掉整段预算，
            # 先关闭它以便更早进入真实搜索。
            solver.parameters.cp_model_presolve = False

        # Hot-start hint
        hint_proto = self.model.Proto().solution_hint  # type: ignore[attr-defined]
        hint_proto.vars.clear()
        hint_proto.values.clear()
        effective_hinted_vars = 0
        if solution_hint:
            hinted_group_poses = set()
            hinted_var_indices = set()
            selected_group_poses: Dict[str, Set[int]] = defaultdict(set)
            selected_tpl_poses: Dict[str, Set[int]] = defaultdict(set)
            selected_optional_poses: Dict[str, Set[int]] = defaultdict(set)
            selected_ghost_idx: Optional[int] = None

            def _add_hint_once(var: Any, value: int = 1) -> None:
                var_index = var.Index()
                if var_index in hinted_var_indices:
                    return
                self.model.AddHint(var, value)
                hinted_var_indices.add(var_index)

            for iid, p_idx in solution_hint.items():
                if iid == "__ghost__" and p_idx in self.u_vars:
                    _add_hint_once(self.u_vars[p_idx], 1)
                    selected_ghost_idx = int(p_idx)
                    continue

                if iid in self.z_vars and p_idx in self.z_vars[iid]:
                    _add_hint_once(self.z_vars[iid][p_idx], 1)
                    if iid in self._group_ord:
                        selected_group_poses[iid].add(int(p_idx))
                    tpl = next(
                        (
                            group["facility_type"]
                            for group in self._mandatory_groups
                            if group["group_id"] == iid
                        ),
                        None,
                    )
                    if tpl is not None:
                        selected_tpl_poses[tpl].add(int(p_idx))
                    continue

                group_id = self._group_id_by_instance.get(iid)
                if group_id and p_idx in self.z_vars.get(group_id, {}):
                    key = (group_id, p_idx)
                    if key not in hinted_group_poses:
                        _add_hint_once(self.z_vars[group_id][p_idx], 1)
                        hinted_group_poses.add(key)
                        selected_group_poses[group_id].add(int(p_idx))
                        tpl = next(
                            group["facility_type"]
                            for group in self._mandatory_groups
                            if group["group_id"] == group_id
                        )
                        selected_tpl_poses[tpl].add(int(p_idx))
                    continue

                optional_tpl = self._infer_optional_template_from_solution_id(iid)
                if optional_tpl and p_idx in self.optional_pose_vars.get(optional_tpl, {}):
                    _add_hint_once(self.optional_pose_vars[optional_tpl][p_idx], 1)
                    selected_optional_poses[optional_tpl].add(int(p_idx))
                    selected_tpl_poses[optional_tpl].add(int(p_idx))

            if self.exact_mode:
                for group in self._mandatory_groups:
                    selected = selected_group_poses.get(group["group_id"])
                    if not selected:
                        continue
                    for p_idx, z_var in self.z_vars[group["group_id"]].items():
                        if p_idx not in selected:
                            _add_hint_once(z_var, 0)

                for tpl, pose_map in self.optional_pose_vars.items():
                    selected = selected_optional_poses.get(tpl, set())
                    for p_idx, pose_var in pose_map.items():
                        if p_idx not in selected:
                            _add_hint_once(pose_var, 0)

                if self.u_vars:
                    for p_idx, u_var in self.u_vars.items():
                        if p_idx != selected_ghost_idx:
                            _add_hint_once(u_var, 0)

                if known_feasible_hint:
                    for tpl, active_map in self._any_active.items():
                        selected = selected_tpl_poses.get(tpl, set())
                        for p_idx, active_var in active_map.items():
                            _add_hint_once(active_var, 1 if p_idx in selected else 0)

                    occupied_cell_keys: Set[int] = set()
                    for group in self._mandatory_groups:
                        tpl = group["facility_type"]
                        pool = self.pools[tpl]
                        for p_idx in selected_group_poses.get(group["group_id"], set()):
                            for cell in pool[p_idx]["occupied_cells"]:
                                occupied_cell_keys.add(int(cell[1]) * 70 + int(cell[0]))
                    for tpl, selected in selected_optional_poses.items():
                        pool = self.pools.get(tpl, [])
                        for p_idx in selected:
                            for cell in pool[p_idx]["occupied_cells"]:
                                occupied_cell_keys.add(int(cell[1]) * 70 + int(cell[0]))
                    if selected_ghost_idx is not None:
                        for cell in self._ghost_domains[selected_ghost_idx]["occupied_cells"]:
                            occupied_cell_keys.add(int(cell[1]) * 70 + int(cell[0]))

                    for cell_key, occ_var in self._solid_occupied_cell.items():
                        _add_hint_once(occ_var, 1 if cell_key in occupied_cell_keys else 0)

                    powered_cell_keys: Set[int] = set()
                    for p_idx in selected_optional_poses.get("power_pole", set()):
                        for cell in self.pools["power_pole"][p_idx].get("power_coverage_cells", []):
                            powered_cell_keys.add(int(cell[1]) * 70 + int(cell[0]))

                    for cell_key, powered_var in getattr(self, "powered_cell", {}).items():
                        _add_hint_once(powered_var, 1 if cell_key in powered_cell_keys else 0)

                    for tpl, pose_infos in self._power_pose_info.items():
                        and_map = self._power_pose_and.get(tpl, {})
                        for p_idx, and_var in and_map.items():
                            is_valid, cell_keys = pose_infos[p_idx]
                            is_powered = int(is_valid and all(cell_key in powered_cell_keys for cell_key in cell_keys))
                            _add_hint_once(and_var, is_powered)

            effective_hinted_vars = len(hinted_var_indices)

        status = solver.Solve(self.model)
        self._solver = solver
        self._status = status
        self.build_stats["last_solve"] = {
            "status": solver.StatusName(status),
            "wall_time": solver.WallTime(),
            "branches": solver.NumBranches(),
            "conflicts": solver.NumConflicts(),
            "hinted_vars": len(solution_hint or {}),
            "effective_hinted_vars": effective_hinted_vars,
        }

        status_name = solver.StatusName(status)
        print(f"🔍 [求解结果] {status_name}")
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            print(f"  目标值: {solver.ObjectiveValue()}")
            print(f"  求解时间: {solver.WallTime():.2f}s")

        return status

    def extract_solution(self) -> Dict[str, Any]:
        """提取当前可行解：每个实例被分配的位姿索引。"""
        if self._status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return {}

        solution = {}
        for group in self._mandatory_groups:
            tpl = group["facility_type"]
            pool = self.pools[tpl]
            selected_pose_indices = [
                p_idx
                for p_idx, z_var in self.z_vars[group["group_id"]].items()
                if self._solver.Value(z_var) == 1
            ]
            selected_pose_indices.sort(key=lambda p_idx: pool[p_idx]["pose_id"])

            for iid, p_idx in zip(group["instance_ids"], selected_pose_indices):
                solution[iid] = {
                    "pose_idx": p_idx,
                    "pose_id": pool[p_idx]["pose_id"],
                    "anchor": pool[p_idx]["anchor"],
                    "facility_type": tpl,
                }

        for tpl in self._pose_optional_templates:
            prefix = POSE_LEVEL_OPTIONAL_PREFIX.get(tpl, tpl)
            pool = self.pools[tpl]
            active_idx = 1
            for p_idx, pose_var in self.optional_pose_vars[tpl].items():
                if self._solver.Value(pose_var) == 1:
                    solution[f"{prefix}_{active_idx:03d}"] = {
                        "pose_idx": p_idx,
                        "pose_id": pool[p_idx]["pose_id"],
                        "anchor": pool[p_idx]["anchor"],
                        "facility_type": tpl,
                    }
                    active_idx += 1

        return solution

    def add_benders_cut(self, conflict_set: Dict[str, int]):
        """添加 Benders No-Good 切平面 (§10.3 / §10.4)。

        conflict_set: {instance_id: pose_idx} 被识别为冲突的实例-位姿组合
        约束: Σ z_{i, p_i*} ≤ |conflict_set| - 1
        """
        conflict_vars = []
        seen_group_poses = set()
        seen_optional_poses = set()
        for iid, p_idx in conflict_set.items():
            if iid in self.z_vars and p_idx in self.z_vars[iid]:
                conflict_vars.append(self.z_vars[iid][p_idx])
                continue

            group_id = self._group_id_by_instance.get(iid)
            if group_id and p_idx in self.z_vars.get(group_id, {}):
                key = (group_id, p_idx)
                if key not in seen_group_poses:
                    conflict_vars.append(self.z_vars[group_id][p_idx])
                    seen_group_poses.add(key)
                continue

            optional_tpl = self._infer_optional_template_from_solution_id(iid)
            if optional_tpl and p_idx in self.optional_pose_vars.get(optional_tpl, {}):
                key = (optional_tpl, p_idx)
                if key not in seen_optional_poses:
                    conflict_vars.append(self.optional_pose_vars[optional_tpl][p_idx])
                    seen_optional_poses.add(key)
        if conflict_vars:
            self.model.Add(sum(conflict_vars) <= len(conflict_vars) - 1)


# ==========================================
# 3. 主控入口
# ==========================================

def main():
    print("🚀 [主模型] 启动 Master Placement Model 构建...")
    project_root = Path(__file__).resolve().parent.parent.parent

    instances, pools, rules = load_project_data(project_root)

    model = MasterPlacementModel(instances, pools, rules)
    model.build()

    print(f"📊 [统计] 强制实例: {len(model._mandatory)}, "
          f"可选实例: {len(model._optional)}, "
          f"供电桩候选位姿: {len(model.optional_pose_vars.get('power_pole', {}))}")

    # 不执行求解（太耗时），仅验证模型构建
    print("✅ [模型构建完成] Master Placement Model 已就绪。")
    print("   调用 model.solve() 启动求解。")


if __name__ == "__main__":
    main()
