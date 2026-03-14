"""POC 求解脚本：跳过供电约束的首次实际求解。

已知：
  - 含供电约束 → 66M constraints → presolve 36s → 超时
  - 跳过供电约束 → ~900K constraints → presolve ~1s → 可实时搜索
  
本脚本使用 skip_power_coverage=True 做首次 POC 求解，
验证几何摆放 + 空地留白的可行性。供电约束后续优化后再启用。
"""
import sys
import time
import json
sys.path.insert(0, ".")

from pathlib import Path
from src.models.master_model import MasterPlacementModel, load_project_data
from src.models.cut_manager import CutManager, LBBDController

project_root = Path(".")

print("=" * 60)
print("🚀 POC 求解 (skip_power_coverage=True)")
print("=" * 60)

# 加载数据
instances, pools, rules = load_project_data(project_root)

# 尝试多个空地尺寸
candidates = [
    (10, 10),  # area=100
    (12, 8),   # area=96
    (14, 7),   # area=98
    (8, 8),    # area=64
    (7, 7),    # area=49
    (6, 6),    # area=36
]

for ghost_w, ghost_h in candidates:
    area = ghost_w * ghost_h
    print(f"\n{'='*60}")
    print(f"🔍 尝试空地 {ghost_w}×{ghost_h} (面积={area})")
    print(f"{'='*60}")
    
    t0 = time.time()
    
    # 构建模型（跳过供电）
    master = MasterPlacementModel(
        instances, pools, rules,
        ghost_rect=(ghost_w, ghost_h),
        skip_power_coverage=True,
    )
    master.build()
    
    build_time = time.time() - t0
    print(f"   模型构建: {build_time:.1f}s")
    
    # LBBD 循环
    cm = CutManager()
    controller = LBBDController(
        master, cm,
        max_iterations=3,
        master_time_limit=120.0,
    )
    solution = controller.run()
    
    elapsed = time.time() - t0
    
    if solution:
        print(f"\n🏆🏆🏆 找到可行解!")
        print(f"   空地: {ghost_w}×{ghost_h} (面积={area})")
        print(f"   已定位实例: {len(solution)}")
        print(f"   总耗时: {elapsed:.1f}s")
        
        # 保存结果
        output_dir = project_root / "data" / "solutions"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        final_result = {
            "ghost_rect": {"w": ghost_w, "h": ghost_h, "area": area},
            "placement_solution": solution,
            "note": "skip_power_coverage=True (POC run)",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        
        output_path = output_dir / "final_solution.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(final_result, f, indent=2, ensure_ascii=False)
        print(f"💾 蓝图已保存至 {output_path}")
        break
    else:
        print(f"   ❌ 不可行 (耗时 {elapsed:.1f}s)")
else:
    print("\n😞 所有候选尺寸均不可行")
