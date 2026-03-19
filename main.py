"""
Project main entry（项目主入口）.

默认模式：certified_exact（严格认证精确）
可选模式：exploratory（探索）
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))



def run_solve(
    *,
    mode: str,
    max_attempts: Optional[int],
    start_area: Optional[int],
    master_seconds: float,
    binding_seconds: float,
    routing_seconds: float,
    flow_seconds: float,
    benders_max_iter: int,
    campaign_hours: float,
    resume_campaign: bool,
    min_side: int,
    max_aspect_ratio: Optional[float],
    area_upper_bound: Optional[int],
) -> Tuple[str, Optional[Dict[str, Any]]]:
    from src.search.outer_search import run_outer_search

    return run_outer_search(
        project_root=PROJECT_ROOT,
        solve_mode=mode,
        max_attempts=max_attempts,
        start_area=start_area,
        master_seconds=master_seconds,
        binding_seconds=binding_seconds,
        routing_seconds=routing_seconds,
        flow_seconds=flow_seconds,
        benders_max_iter=benders_max_iter,
        campaign_hours=campaign_hours,
        resume_campaign=resume_campaign,
        min_side=min_side,
        max_aspect_ratio=max_aspect_ratio,
        area_upper_bound=area_upper_bound,
    )



def run_visualization(result: Optional[Dict[str, Any]] = None) -> None:
    out_dir = PROJECT_ROOT / "data" / "solutions"
    out_dir.mkdir(parents=True, exist_ok=True)

    if result is None:
        final_solution_path = out_dir / "final_solution.json"
        if not final_solution_path.exists():
            print("⚠️ No final_solution.json（没有 final_solution.json），跳过可视化。")
            return
        result = json.loads(final_solution_path.read_text(encoding="utf-8"))

    pools_path = PROJECT_ROOT / "data" / "preprocessed" / "candidate_placements.json"
    pools = {}
    if pools_path.exists():
        pools_payload = json.loads(pools_path.read_text(encoding="utf-8"))
        pools = dict(pools_payload.get("facility_pools", {}))

    solution = dict(result.get("placement_solution", {}))
    ghost = result.get("ghost_rect")

    try:
        from src.render.grid_visualizer import render_placement_heatmap

        render_placement_heatmap(
            solution,
            pools,
            ghost_rect=ghost,
            output_path=out_dir / "heatmap.png",
        )
    except Exception as exc:  # pragma: no cover - visualization is best-effort.
        print(f"⚠️ VIS heatmap（热力图） failed（失败）: {exc}")

    try:
        from src.render.lbbd_animator import render_flow_topology

        occupied = set()
        for sol in solution.values():
            tpl = str(sol.get("facility_type", ""))
            pose_idx = int(sol.get("pose_idx", 0))
            pool = pools.get(tpl, [])
            if 0 <= pose_idx < len(pool):
                for cell in pool[pose_idx].get("occupied_cells", []):
                    occupied.add((int(cell[0]), int(cell[1])))
        render_flow_topology(occupied, output_path=out_dir / "flow_topology.png")
    except Exception as exc:  # pragma: no cover - visualization is best-effort.
        print(f"⚠️ VIS topology（拓扑图） failed（失败）: {exc}")



def main() -> None:
    parser = argparse.ArgumentParser(description="终末地求解器")
    parser.add_argument("--vis", action="store_true", help="Only run visualization（只运行可视化）")
    parser.add_argument(
        "--mode",
        choices=["certified_exact", "exploratory"],
        default="certified_exact",
        help="Solve mode（求解模式），默认 certified_exact（严格认证精确）。",
    )
    parser.add_argument(
        "--exploratory",
        action="store_true",
        help="Backward-compatible flag（兼容旧参数）；等价于 --mode exploratory。",
    )
    parser.add_argument("--campaign-hours", type=float, default=168.0)
    parser.add_argument("--resume-campaign", action="store_true")
    parser.add_argument("--max-attempts", type=int, default=None)
    parser.add_argument("--start-area", type=int, default=None)
    parser.add_argument("--master-seconds", type=float, default=600.0)
    parser.add_argument("--binding-seconds", type=float, default=600.0)
    parser.add_argument("--routing-seconds", type=float, default=600.0)
    parser.add_argument("--flow-seconds", type=float, default=60.0)
    parser.add_argument("--benders-max-iter", type=int, default=30)
    parser.add_argument("--min-side", type=int, default=6)
    parser.add_argument("--max-aspect-ratio", type=float, default=None)
    parser.add_argument("--area-upper-bound", type=int, default=None)
    args = parser.parse_args()

    mode = "exploratory" if args.exploratory else args.mode

    if args.vis:
        run_visualization()
        return

    status, result = run_solve(
        mode=mode,
        max_attempts=args.max_attempts,
        start_area=args.start_area,
        master_seconds=args.master_seconds,
        binding_seconds=args.binding_seconds,
        routing_seconds=args.routing_seconds,
        flow_seconds=args.flow_seconds,
        benders_max_iter=args.benders_max_iter,
        campaign_hours=args.campaign_hours,
        resume_campaign=args.resume_campaign,
        min_side=args.min_side,
        max_aspect_ratio=args.max_aspect_ratio,
        area_upper_bound=args.area_upper_bound,
    )

    print(f"status={status}")
    if result is not None:
        print(json.dumps(result.get("ghost_rect", result), ensure_ascii=False, indent=2))

    if status == "CERTIFIED" and result is not None:
        run_visualization(result)


if __name__ == "__main__":
    main()
