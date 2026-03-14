"""
VIS-02: LBBD 收敛动画 (GIF)
逐帧展示 Benders 迭代中布局的改善过程。

VIS-03: 流网络拓扑简图
展示 occupied/free 格子和瓶颈区域。
"""

import json
import numpy as np
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as patches
    from matplotlib.colors import to_rgba
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

GRID_W, GRID_H = 70, 70


# ==========================================
# VIS-02: LBBD Convergence Animation
# ==========================================

class LBBDAnimator:
    """收集 LBBD 迭代帧并输出 GIF。"""

    def __init__(self):
        self.frames: List[np.ndarray] = []
        self.iteration_info: List[Dict] = []

    def capture_frame(
        self,
        solution: Dict[str, Any],
        pools: Dict[str, List[Dict]],
        iteration: int,
        n_cuts: int,
        status: str = "",
    ):
        """捕获当前迭代的网格快照。"""
        if not HAS_MPL:
            return

        from src.render.grid_visualizer import get_template_color

        grid = np.full((GRID_H, GRID_W, 3), [22, 33, 62], dtype=np.uint8)

        for iid, sol in solution.items():
            tpl = sol.get("facility_type", "unknown")
            p_idx = sol.get("pose_idx", 0)
            pool = pools.get(tpl, [])
            if p_idx >= len(pool):
                continue
            pose = pool[p_idx]
            color_hex = get_template_color(tpl)
            r, g, b, _ = to_rgba(color_hex)

            for cell in pose.get("occupied_cells", []):
                cx, cy = int(cell[0]), int(cell[1])
                if 0 <= cx < GRID_W and 0 <= cy < GRID_H:
                    grid[cy, cx] = [int(r*255), int(g*255), int(b*255)]

        self.frames.append(grid)
        self.iteration_info.append({
            "iteration": iteration,
            "n_cuts": n_cuts,
            "n_placed": len(solution),
            "status": status,
        })

    def save_gif(self, output_path: Path, fps: int = 2) -> Optional[Path]:
        """保存收敛动画为 GIF。"""
        if not self.frames or not HAS_MPL:
            return None

        output_path.parent.mkdir(parents=True, exist_ok=True)

        fig, ax = plt.subplots(figsize=(10, 10), facecolor="#1a1a2e")

        imgs = []
        for i, (frame, info) in enumerate(zip(self.frames, self.iteration_info)):
            ax.clear()
            ax.set_facecolor("#16213e")
            ax.imshow(frame, origin="lower", interpolation="nearest")
            ax.set_title(
                f"LBBD 迭代 #{info['iteration']} | "
                f"切面: {info['n_cuts']} | "
                f"实例: {info['n_placed']} | "
                f"{info['status']}",
                fontsize=12, color="white", fontfamily="SimHei",
            )
            ax.set_xlim(-0.5, GRID_W - 0.5)
            ax.set_ylim(-0.5, GRID_H - 0.5)

            fig.canvas.draw()
            img = np.frombuffer(fig.canvas.tostring_rgb(), dtype=np.uint8)
            img = img.reshape(fig.canvas.get_width_height()[::-1] + (3,))
            imgs.append(img)

        plt.close(fig)

        # 使用 PIL 写 GIF
        try:
            from PIL import Image
            pil_imgs = [Image.fromarray(img) for img in imgs]
            duration = int(1000 / fps)
            pil_imgs[0].save(
                str(output_path), save_all=True,
                append_images=pil_imgs[1:],
                duration=duration, loop=0,
            )
            print(f"🎬 [VIS-02] 收敛动画已保存: {output_path} ({len(imgs)} 帧)")
            return output_path
        except ImportError:
            # 无 PIL，保存最后一帧为 PNG
            fallback = output_path.with_suffix(".png")
            fig2, ax2 = plt.subplots(figsize=(10, 10))
            ax2.imshow(self.frames[-1], origin="lower")
            ax2.set_title(f"LBBD 最终帧 (共 {len(self.frames)} 轮)")
            plt.savefig(str(fallback), dpi=100)
            plt.close(fig2)
            print(f"🖼️ [VIS-02] 最终帧已保存: {fallback} (PIL 不可用)")
            return fallback


# ==========================================
# VIS-03: Flow Network Topology Graph
# ==========================================

def render_flow_topology(
    occupied_cells: set,
    port_dict: Optional[Dict] = None,
    bottleneck_cells: Optional[set] = None,
    output_path: Optional[Path] = None,
    title: str = "流网络拓扑 · 占据/自由格分布",
) -> Optional[Path]:
    """渲染流网络的空间拓扑图。

    Args:
        occupied_cells: 被占据的格子集 {(x, y)}
        port_dict: 端口字典
        bottleneck_cells: 瓶颈格子集
        output_path: 输出路径
    """
    if not HAS_MPL:
        print("⚠️ matplotlib 不可用")
        return None

    fig, ax = plt.subplots(1, 1, figsize=(14, 14), facecolor="#0d1b2a")
    ax.set_facecolor("#1b2838")

    grid = np.full((GRID_H, GRID_W, 4), [0.1, 0.15, 0.22, 1.0])

    # 自由格 (走线通道) — 深绿
    for x in range(GRID_W):
        for y in range(GRID_H):
            if (x, y) not in occupied_cells:
                grid[y, x] = [0.1, 0.3, 0.15, 1.0]

    # 占据格 — 深灰
    for (x, y) in occupied_cells:
        if 0 <= x < GRID_W and 0 <= y < GRID_H:
            grid[y, x] = [0.3, 0.3, 0.35, 1.0]

    # 瓶颈格 — 红色
    if bottleneck_cells:
        for (x, y) in bottleneck_cells:
            if 0 <= x < GRID_W and 0 <= y < GRID_H:
                grid[y, x] = [0.9, 0.2, 0.1, 1.0]

    ax.imshow(grid, origin="lower", interpolation="nearest")

    # 端口标记
    if port_dict:
        for commodity, ports in port_dict.items():
            for port in ports:
                px, py = port.get("x", 0), port.get("y", 0)
                color = "#2ecc71" if port.get("type") == "out" else "#e74c3c"
                ax.plot(px, py, "^", color=color, markersize=3, alpha=0.7)

    # 统计
    n_occ = len(occupied_cells)
    n_free = GRID_W * GRID_H - n_occ
    n_bottle = len(bottleneck_cells) if bottleneck_cells else 0

    ax.set_title(title, fontsize=16, color="white", pad=15, fontfamily="SimHei")
    ax.set_xlim(-0.5, GRID_W - 0.5)
    ax.set_ylim(-0.5, GRID_H - 0.5)
    ax.grid(True, alpha=0.1, color="white")

    stats = f"占据: {n_occ} | 自由: {n_free} | 瓶颈: {n_bottle}"
    ax.text(0.5, -0.02, stats, transform=ax.transAxes,
            ha="center", fontsize=10, color="#aaa", fontfamily="SimHei")

    # 图例
    legend_items = [
        patches.Patch(color="#1a4d26", label="自由格 (走线通道)"),
        patches.Patch(color="#4d4d59", label="占据格 (刚体)"),
    ]
    if bottleneck_cells:
        legend_items.append(patches.Patch(color="#e6331a", label="瓶颈格"))
    ax.legend(handles=legend_items, loc="upper right", fontsize=8, framealpha=0.7)

    if output_path is None:
        output_path = Path("data/solutions/flow_topology.png")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(str(output_path), dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"🗺️ [VIS-03] 流网络拓扑图已保存: {output_path}")
    return output_path
