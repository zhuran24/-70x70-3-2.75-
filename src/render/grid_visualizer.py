"""
VIS-01: 静态网格热力图渲染器
将 70×70 摆放结果渲染为彩色 PNG，按模板类型着色。
"""

import json
import numpy as np
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

try:
    import matplotlib
    matplotlib.use("Agg")  # 无头渲染
    import matplotlib.pyplot as plt
    import matplotlib.patches as patches
    from matplotlib.colors import to_rgba
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

GRID_W, GRID_H = 70, 70

# 模板类型 → 颜色映射 (RGBA)
TEMPLATE_COLORS = {
    "crusher": "#4A90D9",
    "smelter": "#E74C3C",
    "grinder": "#2ECC71",
    "workshop": "#9B59B6",
    "refinery": "#F39C12",
    "assembler": "#1ABC9C",
    "power_pole": "#F1C40F",
    "protocol_box": "#E67E22",
    "border_input": "#3498DB",
    "border_output": "#E91E63",
    "core": "#FF6B6B",
}

DEFAULT_COLOR = "#95A5A6"


def get_template_color(facility_type: str) -> str:
    """根据模板名模糊匹配颜色。"""
    ft_lower = facility_type.lower()
    for key, color in TEMPLATE_COLORS.items():
        if key in ft_lower:
            return color
    return DEFAULT_COLOR


def render_placement_heatmap(
    solution: Dict[str, Any],
    pools: Dict[str, List[Dict]],
    ghost_rect: Optional[Dict] = None,
    ghost_pos: Optional[Tuple[int, int]] = None,
    output_path: Optional[Path] = None,
    title: str = "基地基建极值排布 · 70×70 网格热力图",
) -> Optional[Path]:
    """渲染摆放方案为 70×70 彩色热力图。

    Args:
        solution: {instance_id: {facility_type, pose_idx, ...}}
        pools: {facility_type: [pose_dicts]}
        ghost_rect: {"w": int, "h": int} or None
        ghost_pos: (x, y) 空地左下角位置
        output_path: 输出 PNG 路径
        title: 图表标题

    Returns:
        PNG 文件路径
    """
    if not HAS_MPL:
        print("⚠️ matplotlib 不可用，跳过热力图渲染")
        return None

    fig, ax = plt.subplots(1, 1, figsize=(14, 14), facecolor="#1a1a2e")
    ax.set_facecolor("#16213e")

    # 网格底色
    grid_rgba = np.full((GRID_H, GRID_W, 4), [0.086, 0.129, 0.243, 1.0])

    # 记录占据信息
    cell_owner: Dict[Tuple[int, int], str] = {}

    # 填充刚体占格
    for iid, sol in solution.items():
        tpl = sol.get("facility_type", "unknown")
        p_idx = sol.get("pose_idx", 0)
        pool = pools.get(tpl, [])
        if p_idx >= len(pool):
            continue
        pose = pool[p_idx]
        color = to_rgba(get_template_color(tpl))

        for cell in pose.get("occupied_cells", []):
            cx, cy = int(cell[0]), int(cell[1])
            if 0 <= cx < GRID_W and 0 <= cy < GRID_H:
                grid_rgba[cy, cx] = color
                cell_owner[(cx, cy)] = tpl

    # 渲染供电覆盖 (半透明黄色叠加)
    for iid, sol in solution.items():
        tpl = sol.get("facility_type", "")
        if "power_pole" not in tpl.lower():
            continue
        p_idx = sol.get("pose_idx", 0)
        pool = pools.get(tpl, [])
        if p_idx >= len(pool):
            continue
        pose = pool[p_idx]
        for cell in pose.get("power_coverage_cells", []):
            cx, cy = int(cell[0]), int(cell[1])
            if 0 <= cx < GRID_W and 0 <= cy < GRID_H:
                if (cx, cy) not in cell_owner:
                    # 仅在空格上叠加覆盖色
                    old = grid_rgba[cy, cx]
                    grid_rgba[cy, cx] = [
                        old[0] * 0.6 + 0.4 * 0.95,
                        old[1] * 0.6 + 0.4 * 0.77,
                        old[2] * 0.6 + 0.4 * 0.06,
                        1.0,
                    ]

    ax.imshow(grid_rgba, origin="lower", interpolation="nearest")

    # 绘制幽灵空地矩形
    if ghost_rect and ghost_pos:
        gx, gy = ghost_pos
        gw, gh = ghost_rect.get("w", 0), ghost_rect.get("h", 0)
        rect = patches.Rectangle(
            (gx - 0.5, gy - 0.5), gw, gh,
            linewidth=2, edgecolor="#ffffff", facecolor="white",
            alpha=0.3, linestyle="--",
        )
        ax.add_patch(rect)
        ax.text(gx + gw / 2, gy + gh / 2, f"空地\n{gw}×{gh}",
                ha="center", va="center", color="white",
                fontsize=10, fontweight="bold",
                fontfamily="SimHei")

    # 绘制端口箭头
    arrow_map = {"N": (0, 0.4), "S": (0, -0.4), "E": (0.4, 0), "W": (-0.4, 0)}
    for iid, sol in solution.items():
        tpl = sol.get("facility_type", "")
        p_idx = sol.get("pose_idx", 0)
        pool = pools.get(tpl, [])
        if p_idx >= len(pool):
            continue
        pose = pool[p_idx]
        # 输出端口 (绿箭头)
        for port in pose.get("output_port_cells", []):
            dx, dy = arrow_map.get(port.get("dir", "N"), (0, 0.4))
            ax.annotate("", xy=(port["x"] + dx, port["y"] + dy),
                        xytext=(port["x"], port["y"]),
                        arrowprops=dict(arrowstyle="->", color="#2ecc71",
                                        lw=1.2))
        # 输入端口 (红箭头)
        for port in pose.get("input_port_cells", []):
            dx, dy = arrow_map.get(port.get("dir", "N"), (0, 0.4))
            ax.annotate("", xy=(port["x"] + dx, port["y"] + dy),
                        xytext=(port["x"], port["y"]),
                        arrowprops=dict(arrowstyle="->", color="#e74c3c",
                                        lw=1.2))

    # 网格线
    ax.set_xticks(range(0, GRID_W, 5))
    ax.set_yticks(range(0, GRID_H, 5))
    ax.grid(True, alpha=0.15, color="white", linewidth=0.3)
    ax.set_xlim(-0.5, GRID_W - 0.5)
    ax.set_ylim(-0.5, GRID_H - 0.5)

    # 标题
    ax.set_title(title, fontsize=16, color="white", pad=15,
                 fontfamily="SimHei", fontweight="bold")

    # 图例
    legend_items = []
    used_types = set()
    for iid, sol in solution.items():
        tpl = sol.get("facility_type", "")
        if tpl not in used_types:
            used_types.add(tpl)
            color = get_template_color(tpl)
            legend_items.append(
                patches.Patch(color=color, label=tpl[:20])
            )
    if legend_items:
        ax.legend(handles=legend_items[:12], loc="upper right",
                  fontsize=7, framealpha=0.7, fancybox=True)

    # 统计面板
    n_placed = len(solution)
    n_occupied = len(cell_owner)
    fill_rate = n_occupied / (GRID_W * GRID_H) * 100
    stats_text = (f"实例: {n_placed} | 占格: {n_occupied}/{GRID_W*GRID_H} "
                  f"| 填充率: {fill_rate:.1f}%")
    ax.text(0.5, -0.02, stats_text, transform=ax.transAxes,
            ha="center", fontsize=9, color="#aaa",
            fontfamily="SimHei")

    plt.tight_layout()

    if output_path is None:
        output_path = Path("data/solutions/heatmap.png")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(str(output_path), dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"🖼️ [VIS-01] 热力图已保存: {output_path}")
    return output_path


def render_from_json(json_path: Path, output_path: Optional[Path] = None) -> Optional[Path]:
    """从 JSON 解文件渲染热力图。"""
    import sys
    sys.path.insert(0, str(json_path.parent.parent.parent))

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    solution = data.get("placement_solution", {})
    ghost = data.get("ghost_rect", None)

    # 加载 pools
    pools_path = json_path.parent.parent / "preprocessed" / "candidate_placements.json"
    if pools_path.exists():
        with open(pools_path, "r", encoding="utf-8") as f:
            pools = json.load(f)
    else:
        pools = {}

    return render_placement_heatmap(
        solution, pools, ghost_rect=ghost, output_path=output_path
    )
