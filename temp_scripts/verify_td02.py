"""验证 TD-02 修复：供电约束是否能在合理时间内构建。"""
import sys, time
sys.path.insert(0, ".")
from src.models.master_model import MasterPlacementModel, load_project_data
from pathlib import Path

root = Path(".")
instances, pools, rules = load_project_data(root)

print("=" * 60)
print("TD-02 验证：构建含供电蕴含约束的主模型")
print("=" * 60)

t0 = time.time()
model = MasterPlacementModel(instances, pools, rules, skip_power_coverage=False)
model.build()
elapsed = time.time() - t0

print(f"\n✅ 模型构建完成！总耗时: {elapsed:.1f}s")
print(f"   辅助变量数: {len(model.powered_cell)}")
if elapsed < 120:
    print("🎉 TD-02 修复成功：构建时间 < 2 分钟")
else:
    print("⚠️ 构建时间仍然较长，可能需要进一步优化")
