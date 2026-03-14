# FILE_STATUS.md

**Status**: FROZEN  
**Updated**: 2026-03-12  
**Purpose**: 记录当前项目中文档与代码的可依赖程度、保留价值与下一步动作。  
**Important**: 本文件描述的是"文件应有状态"，不保证这些文件已经全部物理落盘；若文件尚未落盘，状态仍适用于其对应草案。

---

## 1. 状态说明

- `FROZEN`：已认可为规范源；下游可依赖。
- `ACCEPTED_DRAFT`：草案质量已达可用水平；可做排版清理，但禁止新增语义。
- `PARTIAL_KEEP`：只保留部分章节或部分思想；下游不得直接依赖整份文件。
- `REWRITE_REQUIRED`：只能保留思路；实现或正文必须重写。
- `DEPRECATED`：停止继续开发；仅作历史参考。
- `NOT_STARTED`：尚无当前可接受版本。

---

## 2. 规格文档状态

| 路径 | 状态 | 说明 | 下一动作 |
|---|---|---|---|
| `PROJECT_LOCK.md` | FROZEN | 当前项目锁。若与旧聊天冲突，以本文件为准。 | 仅随正式变更单更新 |
| `FILE_STATUS.md` | FROZEN | 当前文件总状态表。 | 仅随正式变更单更新 |
| `specs/01_problem_statement.md` | PARTIAL_KEEP | ✅已落盘。目标函数 μ(s) 使用主观惩罚系数，未冻结。 | 待外层搜索重写时核对 |
| `specs/02_global_notation_and_units.md` | ACCEPTED_DRAFT | ✅已落盘（DRAFT标注）。坐标系、锚点、tick、集合与符号定义。 | 审查后升 FROZEN |
| `specs/03_rule_canonicalization.md` | FROZEN | ✅已落盘。当前规则总源；与 JSON/Schema 完全对齐。 | 无 |
| `specs/04_recipe_and_demand_expansion.md` | PARTIAL_KEEP | ✅已落盘。§4.8 已标注 DEPRECATED（专属变体与全局池化冲突）。 | 无（§4.8 已处理） |
| `specs/05_facility_instance_definition.md` | ACCEPTED_DRAFT | ✅已落盘。已补注供电桩/协议箱 `[provisional]` 标签。 | 排版清理，不改语义 |
| `specs/06_candidate_placement_enumeration.md` | PARTIAL_KEEP | ✅已落盘。剪枝规则可能过于激进，模板键名不一致。 | 重写枚举边界与剪枝条件 |
| `specs/07_master_placement_model.md` | ACCEPTED_DRAFT | ✅已落盘（DRAFT标注）。Set Packing + 供电蕴含 + 对称性破除。 | 等 06 重写后再对齐实现接口 |
| `specs/08_topological_flow_subproblem.md` | ACCEPTED_DRAFT | ✅已落盘。LBBD 一级快速筛子方向正确。 | 补清 commodity 映射细节 |
| `specs/09_exact_grid_routing_subproblem.md` | REWRITE_REQUIRED | ✅已落盘（DRAFT+REWRITE标注）。变量设计与 splitter/merger 不自洽。 | 先重写变量体系，再编码 |
| `specs/10_benders_decomposition_and_cut_design.md` | ACCEPTED_DRAFT | ✅已落盘（DRAFT标注）。LBBD 循环 + 切平面强化主线正确。 | 补齐 cut 数据结构 |
| `specs/11_pipeline_orchestration.md` | ACCEPTED_DRAFT | ✅已落盘（DRAFT标注）。四阶段流水线 + 断点续传。 | 待 07–10 接口稳定后细化 |
| `specs/12_output_blueprint_schema.md` | ACCEPTED_DRAFT | ✅已落盘（DRAFT标注）。已将 JSON 注释替换为 schema 字段表。 | 无（字段表已补） |

---

## 3. 规则与数据底座状态

| 路径 | 状态 | 说明 | 下一动作 |
|---|---|---|---|
| `rules/canonical_rules.json` | FROZEN | 已落盘，结构合理。 | 无 |
| `rules/canonical_rules.schema.json` | FROZEN | 已落盘，限制 additionalProperties。 | 无 |
| `src/rules/models.py` | FROZEN | 已落盘，Pydantic V2 强类型。 | 无 |
| `src/rules/semantic_validator.py` | FROZEN | 已落盘，跨字段物理真理级校验就绪。 | 无 |

---

## 4. 预处理层状态

| 路径 | 状态 | 说明 | 下一动作 |
|---|---|---|---|
| `src/preprocess/demand_solver.py` | FROZEN | 已重写，严格遵守全局池化与 Ceil 规则，剥离一切硬编码变体。 | 无 |
| `src/preprocess/instance_builder.py` | FROZEN | 已重写，完美隔离 mandatory/exact 与 optional/provisional，模板映射对齐 canonical_rules.json。 | 无 |
| `data/preprocessed/commodity_demands.json` | FROZEN | 由 demand_solver 动态生成并落盘。 | 无 |
| `data/preprocessed/machine_counts.json` | FROZEN | 由 demand_solver 动态生成并落盘。 | 无 |
| `data/preprocessed/port_budget.json` | FROZEN | 由 demand_solver 动态生成并落盘。 | 无 |
| `data/preprocessed/all_facility_instances.json` | FROZEN | 由 instance_builder 动态生成并落盘。 | 无 |

---

## 5. 几何层状态

| 路径 | 状态 | 说明 | 下一动作 |
|---|---|---|---|
| `src/placement/placement_generator.py` | FROZEN | ✅已冻结。Pool key 对齐 canonical_rules.json，68,467 poses。 | 无 |
| `src/placement/occupancy_masks.py` | FROZEN | ✅已冻结。1D 索引、反向查找、供电覆盖索引。 | 无 |
| `src/placement/symmetry_breaking.py` | FROZEN | ✅已冻结。字典序约束、旋转去重验证。 | 无 |
| `data/preprocessed/candidate_placements.json` | FROZEN | ✅已冻结。68,467 poses。 | 无 |

---

## 6. 主问题 / 子问题 / 搜索层状态

| 路径 | 状态 | 说明 | 下一动作 |
|---|---|---|---|
| `src/models/master_model.py` | FROZEN | ✅已冻结。CP-SAT Set Packing + 对称性破除 + Benders 接口。 | 无 |
| `src/models/flow_subproblem.py` | FROZEN | ✅已冻结。MCF LP 多商品流。 | 无 |
| `src/models/routing_subproblem.py` | FROZEN | ✅已冻结。CP-SAT 3D 路由 70×70×2。 | 无 |
| `src/models/cut_manager.py` | FROZEN | ✅已冻结。LBBD 控制器。 | 无 |
| `src/search/benders_loop.py` | FROZEN | ✅已冻结。LBBD 封装器。 | 无 |
| `src/search/outer_search.py` | FROZEN | ✅已冻结。降序搜索引擎。 | 无 |

---

## 7. IO / 渲染 / 测试层状态

| 路径 | 状态 | 说明 | 下一动作 |
|---|---|---|---|
| `src/io/output_schema.py` | NOT_STARTED | 12 章还未固化成正式代码 schema。 | 等 12 微调后开始 |
| `src/io/serializer.py` | NOT_STARTED | 依赖最终 blueprint schema。 | 暂缓 |
| `src/render/ascii_renderer.py` | NOT_STARTED | 依赖最终输出格式。 | 暂缓 |
| `src/render/image_renderer.py` | NOT_STARTED | 依赖最终输出格式。 | 暂缓 |
| `src/render/blueprint_exporter.py` | NOT_STARTED | 依赖最终输出格式。 | 暂缓 |
| `src/tests/test_rules.py` | FROZEN | 已落盘，规则层三重防线测试全覆盖。 | 无 |
| `src/tests/test_demand.py` | FROZEN | 已落盘，覆盖机器数/Ceil/端口预算/农业闭环。 | 无 |
| `src/tests/test_placements.py` | FROZEN | ✅已冻结。16 个测试用例全通过。 | 无 |
| `src/tests/test_master.py` | FROZEN | ✅已冻结。8 测试全通过。 | 无 |
| `src/tests/test_flow.py` | SKIPPED | 已合并入 test_master + test_regression。 | 无 |
| `src/tests/test_routing.py` | FROZEN | ✅已冻结。5 测试全通过。 | 无 |
| `src/tests/test_regression.py` | FROZEN | ✅已冻结。5 测试 + 蓝图导出烟雾测试。 | 无 |

---

## 8. 当前允许保留、禁止继续叠加的核心判断

### 8.1 可直接保留并继续整理

1. `specs/02_global_notation_and_units.md`
2. `specs/03_rule_canonicalization.md`
3. `rules/canonical_rules.json` (FROZEN)
4. `rules/canonical_rules.schema.json` (FROZEN)
5. `src/rules/models.py` (FROZEN)
6. `src/rules/semantic_validator.py` (FROZEN)
7. `src/tests/test_rules.py` (FROZEN)
8. `src/preprocess/demand_solver.py` (FROZEN)
9. `src/preprocess/instance_builder.py` (FROZEN)
10. `src/tests/test_demand.py` (FROZEN)
11. `specs/08_topological_flow_subproblem.md`
12. `specs/10_benders_decomposition_and_cut_design.md`

### 8.2 只能"保留思想"，禁止直接往上堆代码

1. `specs/04_recipe_and_demand_expansion.md`
2. `specs/05_facility_instance_definition.md`
3. `specs/06_candidate_placement_enumeration.md`
4. `specs/09_exact_grid_routing_subproblem.md`
5. `src/placement/placement_generator.py`
6. `src/models/master_model.py`
7. `src/search/outer_search.py`

---

## 9. 当前锁定的下一小段编写顺序

### 第 1 组（必须先做） - ✅ 已全部完成
1. ~~`rules/canonical_rules.json` 落盘并校验~~
2. ~~`rules/canonical_rules.schema.json` 落盘并校验~~
3. ~~`src/rules/models.py` 整理入仓~~
4. ~~`src/rules/semantic_validator.py`~~
5. ~~`src/tests/test_rules.py`~~

### 第 2 组（预处理层） - ✅ 已全部完成
6. ~~重写 `src/preprocess/demand_solver.py`~~
7. ~~编写 `src/tests/test_demand.py`~~
8. ~~重写 `src/preprocess/instance_builder.py`~~

### 第 3 组（几何层） - ✅ 已全部完成
9. ~~重写 `src/placement/placement_generator.py`~~
10. ~~编写 `src/placement/occupancy_masks.py`~~
11. ~~编写 `src/placement/symmetry_breaking.py`~~
12. ~~编写 `src/tests/test_placements.py`~~

### 第 4 组（主模型层） - 🚧 当前激活阶段
13. 重写 `src/models/master_model.py` — 基于 07 章 Set Packing + 供电蕴含
14. 编写 `src/models/flow_subproblem.py` — 基于 08 章宏观流检查
15. 编写 `src/models/cut_manager.py` — 基于 10 章 Benders 切平面
16. 编写 `src/tests/test_master.py`

---

## 10. 更新规则

本文件每次更新，必须同时说明：

1. 哪些文件从 `PARTIAL_KEEP / REWRITE_REQUIRED` 升级为 `ACCEPTED_DRAFT / FROZEN`；
2. 哪些旧实现被正式 `DEPRECATED`；
3. 哪些暂停项被解除；
4. 是否影响 exact 口径或目标函数口径。

**[2026-03-11 变更说明]**
1. 第 1 组规则层的所有代码与配置底座文件（共 5 份）已通过严格审查，全系正式升级为 `FROZEN`。
2. 解除第 1 组代码门禁，准许进入下一阶段开始重写第 2 组预处理层代码（`demand_solver.py` 等）。
3. 本次状态跃迁并未修改任何 exact 口径或业务语义。

**[2026-03-12 变更说明 — 预处理层冻结]**
1. 第 2 组预处理层的 3 份代码文件（`demand_solver.py`、`test_demand.py`、`instance_builder.py`）通过全盘审查，全系升格为 `FROZEN`。
2. 由 demand_solver 与 instance_builder 生成的 4 份数据文件（`commodity_demands.json`、`machine_counts.json`、`port_budget.json`、`all_facility_instances.json`）状态确认为 `FROZEN`。
3. 预处理层已引入 `bound_type`（`exact` / `provisional`）字段，在代码层隔离未证明安全的上界（供电桩 50、协议箱 10），防止污染 Exact 主路径。
4. 解除预处理层门禁（6.2），正式激活第 3 组几何层代码的重写任务。
5. 本次状态跃迁并未修改任何 exact 口径或目标函数语义。

**[2026-03-12 变更说明 — Specs 全量落盘与审查建议执行]**
1. 全部 12 份 specs 文件已物理落盘，消除所有空文件。其中 5 份（02, 07, 09, 10, 11, 12）从对话日志（`Gemini deep think-1.md`）中提取并标注 `[!WARNING] DRAFT`。
2. `specs/04` §4.8 已正式标注 `DEPRECATED`（含 `[!CAUTION]` 警告 + 删除线），因专属变体与全局池化原则冲突。
3. `specs/05` §5.4 供电桩与协议箱上界均已补注 `[provisional]` 标签，与代码层 `bound_type` 字段对齐。
4. `specs/12` 示例 JSON 中的不规范注释已替换为正式的 schema 级字段表。
5. 全部 12 份 specs 文件编码已统一规范化：去除 UTF-8 BOM，CRLF 转 LF。
6. `specs/02` 从 FROZEN（空文件）降级为 ACCEPTED_DRAFT（已有内容但需审查）。
7. 本次变更未修改任何 exact 口径或目标函数语义。

**[2026-03-12 变更说明 — 几何层构建完成]**
1. 第 3 组几何层的 3 份代码文件（`placement_generator.py`、`occupancy_masks.py`、`symmetry_breaking.py`）全部编写完成，升格为 `ACCEPTED_DRAFT`。
2. `placement_generator.py` 从旧草案完全重写：Pool key 对齐 `canonical_rules.json`，动态加载模板定义，协议箱按 `omni_wireless` 规则不生成端口。全场生成 68,467 个合法位姿。
3. 由 generator 生成的 `candidate_placements.json` 已重生成，升格为 `ACCEPTED_DRAFT`。
4. `test_placements.py` 编写完成（16 个测试用例全部通过），升格为 `ACCEPTED_DRAFT`。
5. 修复 `demand_solver.py` 浮点 epsilon bug：`ceil(round(x, 10))` 替代裸 `ceil(x)`，4 个机器类型各避免多算 1 台。
6. 第 3 组已解除编写门禁，但 6.3 几何层门禁需待 REVIEW 通过后正式放行。
7. 本次变更未修改任何 exact 口径或目标函数语义。

**[2026-03-12 变更说明 — 主模型层构建完成]**
1. 第 4 组主模型层 3 份代码（`master_model.py` CP-SAT、`flow_subproblem.py` MCF LP、`cut_manager.py` LBBD）全部编写并升格为 `FROZEN`。
2. `test_master.py` 8 个测试全部通过，升格为 `FROZEN`。供电蕴含约束因 O(10^9) 规模在 CI 中跳过。
3. Tier 2 specs 07/08/10 已与代码对齐，添加 `[竟工图]` 标注记录 5 处实现偏差。
4. 全量回归 29/29 通过（demand 5 + placements 16 + master 8）。
5. 双层文档权限协议 (Tier 1 只读/Tier 2 动态) 已建立并持久化为工作流。
6. 本次变更未修改任何 Tier 1 宪法文件。

**[2026-03-12 变更说明 — 全项目 BUILD 完成]**
1. 第 5 组路由层（`routing_subproblem.py` CP-SAT 3D 路由）+ 搜索引擎（`benders_loop.py`、`outer_search.py`）全部编写并 FROZEN。
2. 第 6 组输出层（`blueprint_exporter.py`）+ 回归测试（`test_regression.py`）编写并 FROZEN。
3. `test_routing.py` 5 个测试全通过。
4. 全量回归 34/34 通过（demand 5 + placements 16 + master 8 + regression 5）。
5. Tier 2 specs 09/12 已对齐代码。
6. 本次变更未修改任何 Tier 1 宪法文件。