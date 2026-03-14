---
description: 终端使用纪律 — 严禁 python -c，严禁 OS 高危命令，严禁终端清理
---

# 终端极度安全与免打扰协议

// turbo-all

## 🔴 绝对禁止项

1. **禁用 OS 高危命令**：严禁 `rm`, `del`, `Remove-Item`, `mv`, `Move-Item`, `chmod`, `ren` 等一切涉及文件删除、移动或系统权限的 Shell 命令
2. **禁用内联代码**：严禁 `python -c`
3. **禁止终端打扫战场**：脚本执行完毕后，不得在终端中用命令删除临时文件

## ✅ 正确做法

### 临时验证脚本
1. 新建 `.py` 脚本至 `temp_scripts/` 目录（例如 `temp_scripts/check_xxx.py`）
2. 执行脚本：`python temp_scripts/check_xxx.py`
3. **不要删除**。人类开发者后续统一手动清理

### 如确需自清理
- 仅限在 Python 脚本内部使用 `os.remove()` 或 `tempfile` 模块
- 绝不允许将删除动作暴露给终端 Shell

## 适用范围

- 数据打印与中间值检查
- 环境与依赖测试
- JSON 内容验证
- 任何需要 Python 解释器的一次性操作
- 所有文件清理操作
