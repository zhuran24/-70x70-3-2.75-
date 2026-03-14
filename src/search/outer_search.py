"""
外层降序搜索引擎 (Outer Descending Search)
对应规格书：01 §1.x 极值目标
Status: ACCEPTED_DRAFT

目标：在给定的 (w, h) 空间中降序搜索最大空地尺寸。
对每个候选尺寸调用 benders_loop，只有拿到可认证证书时才输出终极蓝图。
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple


def generate_candidate_sizes(
    max_w: int = 70,
    max_h: int = 70,
    min_side: int = 6,
    max_aspect_ratio: Optional[float] = None,
    area_upper_bound: Optional[int] = None,
) -> List[Tuple[int, int, int]]:
    """生成空地候选尺寸。

    默认路径尽量贴近 exact 语义：
      - 不使用启发式面积上界
      - 不使用长宽比过滤
      - 仅应用已冻结的短边可用性下限 min_side >= 6

    Returns:
        [(area, w, h), ...]，按面积优先、短边次优、形状更方正再次优先排序
    """
    candidates = []
    for w in range(min_side, max_w + 1):
        for h in range(min_side, min(max_h, w) + 1):
            area = w * h
            if area_upper_bound is not None and area > area_upper_bound:
                continue
            if max_aspect_ratio is not None and w / h > max_aspect_ratio:
                continue
            candidates.append((area, w, h))

    # 对应“面积最大优先；面积相同则短边更厚优先；再次按更接近方形优先”
    candidates.sort(key=lambda x: (-x[0], -min(x[1], x[2]), abs(x[1] - x[2])))
    return candidates


def run_outer_search(
    start_area: Optional[int] = None,
    max_attempts: Optional[int] = None,
    master_time_limit: float = 60.0,
    benders_max_iter: int = 30,
    project_root: Optional[Path] = None,
    certification_mode: bool = True,
    max_aspect_ratio: Optional[float] = None,
    area_upper_bound: Optional[int] = None,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """执行外层降序搜索。

    Returns:
        (status, result)
        status ∈ {CERTIFIED, INFEASIBLE, UNKNOWN, UNPROVEN}
    """
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent.parent

    exact_area_upper_bound = None
    if certification_mode:
        from src.models.master_model import load_project_data
        from src.search.benders_loop import compute_mandatory_area_lower_bound

        instances, _, rules = load_project_data(project_root)
        grid = rules["globals"]["grid"]
        grid_area = int(grid["width"]) * int(grid["height"])
        occupied_area_lb = compute_mandatory_area_lower_bound(instances, rules)
        exact_area_upper_bound = max(0, grid_area - occupied_area_lb)
        if area_upper_bound is None:
            area_upper_bound = exact_area_upper_bound
        else:
            area_upper_bound = min(area_upper_bound, exact_area_upper_bound)

    from src.models.cut_manager import (
        RUN_STATUS_CERTIFIED,
        RUN_STATUS_INFEASIBLE,
        RUN_STATUS_UNKNOWN,
        RUN_STATUS_UNPROVEN,
    )
    from src.search.benders_loop import run_benders_for_ghost_rect

    candidates = generate_candidate_sizes(
        min_side=6,
        max_aspect_ratio=max_aspect_ratio,
        area_upper_bound=area_upper_bound,
    )

    if start_area is not None:
        candidates = [(a, w, h) for (a, w, h) in candidates if a <= start_area]

    print(f"\n{'#' * 60}")
    print("🔎 [外层搜索] 启动降序空地搜索引擎")
    print(f"   候选尺寸: {len(candidates)} 个")
    print(f"   模式: {'CERTIFICATION' if certification_mode else 'EXPLORATORY'}")
    if exact_area_upper_bound is not None:
        print(f"   Exact面积上界: {exact_area_upper_bound}")
    print(f"   每尺寸 Benders 上限: {benders_max_iter} 轮")
    if max_attempts is None:
        print("   尝试上限: exhaustive")
    else:
        print(f"   尝试上限: {max_attempts}")
    print(f"{'#' * 60}")

    attempts = 0
    exhausted = True
    for area, w, h in candidates:
        if max_attempts is not None and attempts >= max_attempts:
            print(f"⏰ [搜索] 达到最大尝试次数 {max_attempts}")
            exhausted = False
            break

        attempts += 1
        print(f"\n🔍 [{attempts}] 尝试空地 {w}×{h} (面积={area})")

        status, solution = run_benders_for_ghost_rect(
            ghost_w=w,
            ghost_h=h,
            max_iterations=benders_max_iter,
            master_time_limit=master_time_limit,
            project_root=project_root,
            certification_mode=certification_mode,
        )

        if status == RUN_STATUS_CERTIFIED and solution:
            print(f"\n🏆 [终极胜利] 找到可认证空地: {w}×{h} (面积={area})!")

            output_dir = project_root / "data" / "solutions"
            output_dir.mkdir(parents=True, exist_ok=True)

            final_result = {
                "ghost_rect": {"w": w, "h": h, "area": area},
                "placement_solution": solution,
                "search_status": status,
                "search_stats": {
                    "attempts": attempts,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                },
            }

            output_path = output_dir / "final_solution.json"
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(final_result, f, indent=2, ensure_ascii=False)
            print(f"💾 终极蓝图已保存至 {output_path}")

            return RUN_STATUS_CERTIFIED, final_result

        if status == RUN_STATUS_INFEASIBLE:
            print(f"   ❌ 空地 {w}×{h} 已被证明不可行，继续搜索...")
            continue

        if status == RUN_STATUS_UNKNOWN:
            print("⏸️ [搜索停止] 当前候选未能在时限内证伪/证成，不能继续宣称后续候选最优。")
            return RUN_STATUS_UNKNOWN, None

        if status == RUN_STATUS_UNPROVEN:
            print("⚠️ [搜索停止] 当前工程链路尚不能对候选给出 exact 证书。")
            return RUN_STATUS_UNPROVEN, None

    if not exhausted:
        print("\n⏸️ [搜索结束] 搜索被尝试上限提前截断，不能宣称全局无解。")
        return RUN_STATUS_UNKNOWN, None

    print(f"\n😞 [搜索结束] 在 {attempts} 次尝试中未找到可认证布局")
    return RUN_STATUS_INFEASIBLE, None


def main():
    """运行外层搜索引擎。"""
    print("🚀 [启动] 明日方舟终末地 极值排布搜索引擎")
    print("=" * 60)

    status, result = run_outer_search(
        max_attempts=10,
        master_time_limit=30.0,
        benders_max_iter=10,
        certification_mode=False,
        max_aspect_ratio=8.0,
        area_upper_bound=400,
    )

    if status == "CERTIFIED" and result:
        ghost = result["ghost_rect"]
        print(f"\n✅ 最优空地: {ghost['w']}×{ghost['h']} (面积={ghost['area']})")
    else:
        print(f"\n❌ 搜索未得到可认证终解，状态={status}")


if __name__ == "__main__":
    main()
