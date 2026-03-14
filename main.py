"""
统一主入口 (Unified Main Entry)

默认行为优先追求 exact 认证，不再默认走跳约束/跳子问题的快速路径。
如需保留探索性求解，请显式传入 `--exploratory`。
"""

import sys
import json
import argparse
from pathlib import Path

# 防止 Windows GBK 编码导致 UnicodeEncodeError
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))

PROJECT_ROOT = Path(__file__).parent


def run_solve(
    *,
    exploratory: bool,
    max_attempts: int | None,
    master_time_limit: float,
    benders_max_iter: int,
) -> tuple[str, dict | None]:
    """执行求解流水线。"""
    from src.search.outer_search import run_outer_search

    return run_outer_search(
        project_root=PROJECT_ROOT,
        certification_mode=not exploratory,
        max_attempts=max_attempts,
        master_time_limit=master_time_limit,
        benders_max_iter=benders_max_iter,
    )


def run_visualization(result: dict | None = None):
    """运行所有 VIS 模块。"""
    out_dir = PROJECT_ROOT / "data" / "solutions"

    if result is None:
        sol_path = out_dir / "final_solution.json"
        if sol_path.exists():
            with open(sol_path, "r", encoding="utf-8") as f:
                result = json.load(f)
        else:
            print("⚠️ 无可视化输入文件，跳过。")
            return

    pools_path = PROJECT_ROOT / "data" / "preprocessed" / "candidate_placements.json"
    if pools_path.exists():
        with open(pools_path, "r", encoding="utf-8") as f:
            pools = json.load(f)
    else:
        pools = {}

    solution = result.get("placement_solution", {})
    ghost = result.get("ghost_rect", None)

    print("\n🖼️ === VIS-01: 静态热力图 ===")
    try:
        from src.render.grid_visualizer import render_placement_heatmap

        heatmap_path = render_placement_heatmap(
            solution, pools, ghost_rect=ghost, output_path=out_dir / "heatmap.png"
        )
    except Exception as e:
        print(f"   ⚠️ VIS-01 异常: {e}")
        heatmap_path = None

    print("\n🗺️ === VIS-03: 流网络拓扑图 ===")
    try:
        from src.render.lbbd_animator import render_flow_topology

        occupied = set()
        for sol in solution.values():
            tpl = sol.get("facility_type", "")
            p_idx = sol.get("pose_idx", 0)
            pool = pools.get(tpl, [])
            if p_idx < len(pool):
                for cell in pool[p_idx].get("occupied_cells", []):
                    occupied.add((int(cell[0]), int(cell[1])))
        topo_path = render_flow_topology(
            occupied, output_path=out_dir / "flow_topology.png"
        )
    except Exception as e:
        print(f"   ⚠️ VIS-03 异常: {e}")
        topo_path = None

    print("\n🌐 === VIS-04: 交互式 Web 查看器 ===")
    import shutil

    viewer_dir = PROJECT_ROOT / "src" / "render" / "web_viewer"
    try:
        shutil.copy2(out_dir / "final_solution.json", viewer_dir / "final_solution.json")
        if pools_path.exists():
            shutil.copy2(pools_path, viewer_dir / "candidate_placements.json")
        print(f"   数据已复制到 {viewer_dir}")
        print("   启动方法: python src/render/serve.py")
        print(f"   或直接打开: {viewer_dir / 'index.html'}")
    except Exception as e:
        print(f"   ⚠️ VIS-04 异常: {e}")

    print("\n" + "=" * 60)
    print("📊 可视化输出汇总:")
    if heatmap_path:
        print(f"   🖼️ 热力图: {heatmap_path}")
    if topo_path:
        print(f"   🗺️ 拓扑图: {topo_path}")
    print("   🌐 Web 查看器: python src/render/serve.py")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="基建极值排布引擎")
    parser.add_argument("--vis", action="store_true", help="仅运行可视化")
    parser.add_argument(
        "--exploratory",
        action="store_true",
        help="允许使用当前尚未可认证的探索性链路，仅用于调试。",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=None,
        help="最多尝试多少个空地候选；默认 exhaustive。",
    )
    parser.add_argument(
        "--master-time-limit",
        type=float,
        default=600.0,
        help="每个候选的主问题求解时限（秒）。",
    )
    parser.add_argument(
        "--benders-max-iter",
        type=int,
        default=50,
        help="每个候选的 Benders 迭代上限。",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("🚀 明日方舟·终末地 极值排布引擎")
    print("=" * 60)

    if args.vis:
        run_visualization()
        return

    status, result = run_solve(
        exploratory=args.exploratory,
        max_attempts=args.max_attempts,
        master_time_limit=args.master_time_limit,
        benders_max_iter=args.benders_max_iter,
    )

    if status == "CERTIFIED" and result:
        print("\n✅ 已获得可认证终解。")
        run_visualization(result)
        return

    if status == "UNPROVEN":
        print(
            "\n⚠️ 当前工程仍存在 exact 认证阻塞项，已停止而不是继续伪装成“全局最优”。"
        )
    elif status == "UNKNOWN":
        print("\n⏸️ 当前时限内未能给出 exact 结论。")
    else:
        print("\n❌ 当前搜索未找到可认证布局。")


if __name__ == "__main__":
    main()
