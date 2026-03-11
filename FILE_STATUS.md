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
| `specs/01_problem_statement.md` | PARTIAL_KEEP | 目标函数部分多次漂移，exact 口径未完全代码化。 | 待外层搜索重写时核对 |
| `specs/02_global_notation_and_units.md` | FROZEN | 坐标系、锚点、tick、集合与符号定义稳定。 | 仅做排版清理 |
| `specs/03_rule_canonicalization.md` | FROZEN | 当前规则总源；与 JSON/Schema 完全对齐。 | 无 |
| `specs/04_recipe_and_demand_expansion.md` | PARTIAL_KEEP | "4.8 实例级固定拓扑/专属降速变体"已在代码中被剥离废弃。 | 剔除 4.8 的硬绑定描述 |
| `specs/05_facility_instance_definition.md` | ACCEPTED_DRAFT | 实例清单已通过代码修正，区分了 exact 与 provisional 上界。 | 排版清理，不改语义 |
| `specs/06_candidate_placement_enumeration.md` | PARTIAL_KEEP | 候选摆位预计算路线正确；具体剪枝与模板共享规则需要校正。 | 重写枚举边界与剪枝条件 |
| `specs/07_master_placement_model.md` | ACCEPTED_DRAFT | 主问题大框架可用。 | 等 06 重写后再对齐实现接口 |
| `specs/08_topological_flow_subproblem.md` | ACCEPTED_DRAFT | 作为 LBBD 的一级快速筛子方向正确。 | 补清 commodity 映射细节 |
| `specs/09_exact_grid_routing_subproblem.md` | REWRITE_REQUIRED | 变量设计与 splitter/merger 不自洽。 | 先重写变量体系，再编码 |
| `specs/10_benders_decomposition_and_cut_design.md` | ACCEPTED_DRAFT | LBBD 循环主线正确。 | 补齐 cut 数据结构 |
| `specs/11_pipeline_orchestration.md` | ACCEPTED_DRAFT | 总控、缓存、日志思路可保留。 | 待 07–10 接口稳定后细化 |
| `specs/12_output_blueprint_schema.md` | ACCEPTED_DRAFT | 最终输出契约思路基本正确。 | 补 schema 级字段表 |

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
| `src/placement/placement_generator.py` | REWRITE_REQUIRED | 当前草案存在模板键/实例键不稳、核心剪枝过强等问题。 | 重写 |
| `src/placement/occupancy_masks.py` | NOT_STARTED | 需把候选摆位转成可复用 mask 索引。 | 等 placement_generator 接口冻结后创建 |
| `src/placement/symmetry_breaking.py` | NOT_STARTED | 对称性破除尚未从文档独立成代码。 | 等候选索引冻结后创建 |
| `data/preprocessed/candidate_placements.json` | DEPRECATED | 若由旧 generator 生成，存在过度删解风险。 | 删除后重生成 |

---

## 6. 主问题 / 子问题 / 搜索层状态

| 路径 | 状态 | 说明 | 下一动作 |
|---|---|---|---|
| `src/models/master_model.py` | DEPRECATED | 抢跑代码。 | 待几何层重写后重建 |
| `src/models/flow_subproblem.py` | NOT_STARTED | 当前只有文档。 | 06 重写后开始 |
| `src/models/routing_subproblem.py` | NOT_STARTED | 09 章尚需重写。 | 等 09 冻结后开始 |
| `src/models/cut_manager.py` | NOT_STARTED | cut 结构还未定稿。 | 待 10 章补齐后开始 |
| `src/search/benders_loop.py` | NOT_STARTED | 等 master + flow 可运行后再写。 | 暂缓 |
| `src/search/outer_search.py` | DEPRECATED | 旧草稿。 | 等 01 冻结后重写 |

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
| `src/tests/test_placements.py` | NOT_STARTED | 需覆盖摆位完整性、边界、端口位置。 | 随新版 placement_generator 编写 |
| `src/tests/test_master.py` | NOT_STARTED | 依赖稳定的 master_model。 | 暂缓 |
| `src/tests/test_flow.py` | NOT_STARTED | 依赖 flow_subproblem。 | 暂缓 |
| `src/tests/test_routing.py` | NOT_STARTED | 依赖 routing_subproblem。 | 暂缓 |
| `src/tests/test_regression.py` | NOT_STARTED | 需在最小闭环跑通后建立。 | 暂缓 |

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

### 第 3 组（几何层） - 🚧 当前激活阶段
9. 重写 `src/placement/placement_generator.py`
10. 编写 `src/placement/occupancy_masks.py`
11. 编写 `src/placement/symmetry_breaking.py`
12. 编写 `src/tests/test_placements.py`

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

**[2026-03-12 变更说明]**
1. 第 2 组预处理层的 3 份代码文件（`demand_solver.py`、`test_demand.py`、`instance_builder.py`）通过全盘审查，全系升格为 `FROZEN`。
2. 由 demand_solver 与 instance_builder 生成的 4 份数据文件（`commodity_demands.json`、`machine_counts.json`、`port_budget.json`、`all_facility_instances.json`）状态确认为 `FROZEN`。
3. 预处理层已引入 `bound_type`（`exact` / `provisional`）字段，在代码层隔离未证明安全的上界（供电桩 50、协议箱 10），防止污染 Exact 主路径。
4. 解除预处理层门禁（6.2），正式激活第 3 组几何层代码的重写任务。
5. 本次状态跃迁并未修改任何 exact 口径或目标函数语义。