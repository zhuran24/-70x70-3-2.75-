# PROJECT_LOCK.md

**Status**: FROZEN  
**Updated**: 2026-03-12  
**Scope**: 本文件锁定当前项目的目录、术语边界、开发门禁与变更流程。  
**Priority**: 若历史聊天内容、旧草稿或临时代码与本文件冲突，以本文件和 `FILE_STATUS.md` 为准。

---

## 1. 目的

本文件用于阻止项目在长线程协作中发生以下失控行为：

1. 在上游规格未冻结前，抢写下游代码。
2. 将启发式、临时上界或实现技巧误写成硬规格。
3. 在未经批准的情况下擅自改目录树、改命名、改目标函数、改实例语义。
4. 在接口尚未打通前，让不同文件各自演化，最终互相不兼容。

本文件的目标不是"限制开发速度"，而是保证后续每一轮输出都能被安全纳入主线，而不是堆成新的技术债。

---

## 2. 当前锁定的仓库骨架

### 2.1 规范目录树（Canonical Layout）

```text
specs/
├── 01_problem_statement.md
├── 02_global_notation_and_units.md
├── 03_rule_canonicalization.md
├── 04_recipe_and_demand_expansion.md
├── 05_facility_instance_definition.md
├── 06_candidate_placement_enumeration.md
├── 07_master_placement_model.md
├── 08_topological_flow_subproblem.md
├── 09_exact_grid_routing_subproblem.md
├── 10_benders_decomposition_and_cut_design.md
├── 11_pipeline_orchestration.md
└── 12_output_blueprint_schema.md

rules/
├── canonical_rules.json
└── canonical_rules.schema.json

src/
├── rules/
│   ├── models.py
│   └── semantic_validator.py
├── preprocess/
│   ├── demand_solver.py
│   └── instance_builder.py
├── placement/
│   ├── placement_generator.py
│   ├── occupancy_masks.py
│   └── symmetry_breaking.py
├── models/
│   ├── master_model.py
│   ├── flow_subproblem.py
│   ├── routing_subproblem.py
│   └── cut_manager.py
├── search/
│   ├── benders_loop.py
│   └── outer_search.py
├── io/
│   ├── output_schema.py
│   └── serializer.py
├── render/
│   ├── ascii_renderer.py
│   ├── image_renderer.py
│   └── blueprint_exporter.py
└── tests/
    ├── test_rules.py
    ├── test_demand.py
    ├── test_placements.py
    ├── test_master.py
    ├── test_flow.py
    ├── test_routing.py
    └── test_regression.py

data/
├── preprocessed/
├── blueprints/
└── checkpoints/
```

### 2.2 目录树锁定规则

1. `rules/` 只存放**静态规则数据**，不放 Python 逻辑。
2. `src/rules/` 只存放**规则解析与语义校验代码**。
3. `specs/` 只存放规格文档；规格文档不得夹带可执行代码作为主内容。
4. `data/` 只存放程序生成物与检查点；不得把手写源文件放入 `data/`。
5. 任何新文件或改名，必须先更新本文件与 `FILE_STATUS.md`。

---

## 3. 当前已冻结的业务语义（Frozen Truths）

以下内容已经视为项目级真值，后续代码与规格不得擅自改写：

1. 主基地为 `70 x 70` 离散网格。
2. 基础时间单位为 `1 tick = 2 秒`。
3. 出货口资源池化成立；禁止对协议核心额外 6 个出口做先验硬绑定。
4. 中间产物全局池化成立；禁止把"某条线的中间产物"硬编码为专属资源。
5. 农业系统可内部闭环，不要求外部输入口。
6. 机器数量必须 `ceil` 向上取整；禁止分数机器。
7. 所有制造单位必须供电；物流设施不需要供电。
8. 协议核心可移动、可旋转。
9. 协议储存箱数量在游戏规则层面无上限。
10. 物流桥允许真三维重叠，并允许连续高架拼接。
11. 边界仓库口位于基地内部，并受左/下基线约束。
12. 空地允许被完全包围，不要求对外连通。
13. 必须通过 `bound_type` 区分 `exact`（数学证明）边界与 `provisional`（未证明安全）上限；`provisional` 上界不得进入 Exact 主求解路径并宣称全局最优。

---

## 4. 当前**未**冻结的内容（Open / Not Frozen）

以下内容已经出现过多个版本，现阶段不得当作最终真理：

1. **01 章目标函数的最终数学标量化形式**。  
   已冻结的只有业务语义：
   - 空地必须"可用"；
   - 短边 `< 6` 视为不可用；
   - 短边达到约 `8` 后，额外宽度收益明显饱和。  
   但"如何把这套语义写成最终精确目标函数"，尚未最终冻结。

2. **可选设施的安全上界（safe proven upper bounds）**。  
   供电桩（50）、协议储存箱（10）等的候选数量上界为 `provisional`，若无法证明安全，不得进入 exact 主路径并宣称"全局最优"。

3. **09 章的最终离散路由变量设计**。  
   当前关于 splitter / merger / gate / bridge 的精确变量体系尚未完全冻结。

4. **任何把 75% 产线写成"专属机器变体"或"专属半载机器"的实现**。  
   这类做法只能是临时实现技巧，不能升级为 canonical 规则。（注：当前预处理代码已彻底剥离此类硬绑定，但此条保留作为持续禁令。）

---

## 5. 当前开发协议（必须遵守）

### 5.1 单轮单模式

每一轮协作只能处于以下四种模式之一：

- `PLAN`
- `SPEC`
- `CODE`
- `REVIEW`

禁止在同一轮中同时：规划路径 + 写规格 + 写代码。

### 5.2 单轮单任务

每一轮只能处理一个 `TASK_ID`，且只允许输出一个主要文件。

### 5.3 单轮单文件

除非明确要求"补丁集"或"成对文件"，否则一轮只允许新增/重写一个文件。

### 5.4 禁止擅自推进

任何协作者不得主动：

1. 进入下一章；
2. 新增新文件；
3. 修改目录树；
4. 改写已冻结的业务语义；
5. 用"顺便"名义写下游实现。

如遇阻塞，只允许输出《阻塞清单》，不得自行绕路立新设定。

---

## 6. 代码门禁（Dependency Gates）

### 6.1 规则层门禁【✅ 已放行】

以下文件已达到完全可依赖的 `FROZEN` 状态，后续任何预处理与运筹求解代码均必须依赖它们：

- `specs/02_global_notation_and_units.md`
- `specs/03_rule_canonicalization.md`
- `rules/canonical_rules.json`
- `rules/canonical_rules.schema.json`
- `src/rules/models.py`
- `src/rules/semantic_validator.py`
- `src/tests/test_rules.py`

### 6.2 预处理层门禁【✅ 已放行】

以下文件已通过全盘审查并升格为 `FROZEN`，数据底座纯净无污染，供几何层和下游直接调用：

- `src/preprocess/demand_solver.py`
- `src/preprocess/instance_builder.py`
- `src/tests/test_demand.py`
- `data/preprocessed/commodity_demands.json`
- `data/preprocessed/machine_counts.json`
- `data/preprocessed/port_budget.json`
- `data/preprocessed/all_facility_instances.json`

### 6.3 几何层门禁【🔒 锁定中】

在以下文件未重写并通过测试前，禁止继续扩展 `master_model.py`：

- `src/placement/placement_generator.py`
- `src/placement/occupancy_masks.py`
- `src/placement/symmetry_breaking.py`

### 6.4 主问题门禁【🔒 锁定中】

在以下条件未满足前，禁止把 `master_model.py`、`outer_search.py` 当作 exact 主线：

1. 01 章目标函数已冻结；
2. 05 章 optional instance 语义已冻结；
3. 10 章 cut 接口与持久化协议已冻结；
4. 所有 provisional 上界已隔离，不会污染 exact 路径。

### 6.5 路由层门禁【🔒 锁定中】

在 `specs/09_exact_grid_routing_subproblem.md` 重写冻结前，禁止开始正式实现 `src/models/routing_subproblem.py`。

---

## 7. 明令禁止的事项

1. 禁止新增任何未经批准的上界，并把它伪装成硬规格。
2. 禁止把启发式排序、经验打分函数写成"已被严格证明最优"。
3. 禁止把 pooled 资源写成硬绑定专线。
4. 禁止为 75% 线创建 canonical 的"专属半载机器"语义。
5. 禁止在规格未冻结前写下游代码然后倒逼上游文档配合。
6. 禁止改文件名、改路径、改 JSON 键名而不更新 `FILE_STATUS.md`。
7. 禁止一个回答同时完成：重构目录树 + 新增规则 + 新增代码。
8. 禁止把聊天中的临时讨论结论直接当作 repo 真值，必须落盘到文档。

---

## 8. 文件状态词汇表（与 FILE_STATUS.md 一致）

- `FROZEN`：规范源；下游可依赖。
- `ACCEPTED_DRAFT`：基本可用；允许文字清理，不允许语义扩张。
- `PARTIAL_KEEP`：文件中只有部分内容可保留；不得直接作为下游依赖。
- `REWRITE_REQUIRED`：只能参考思路，必须重写。
- `DEPRECATED`：停止使用，仅保留作为历史参考。
- `NOT_STARTED`：尚无可依赖版本。

---

## 9. 变更流程

任何变更必须同时更新：

1. `PROJECT_LOCK.md`
2. `FILE_STATUS.md`
3. 对应目标文件本体（若已存在）

每次变更单至少包含：

- 变更原因；
- 影响范围；
- 是否改变语义；
- 是否影响 exact 口径；
- 是否引入 provisional 假设；
- 需要重测哪些测试文件。

---

## 10. 当前锁定的短程开发顺序

在当前节点，后续一小段的**唯一推荐顺序**为：

### 第 1 组（规则层） - ✅ 已全部完成

~~1. 将 `03` 相关文档与规则 JSON/Schema 正式落盘。~~  
~~2. 编写 `src/rules/semantic_validator.py`，把 JSON Schema 之外的语义校验补齐。~~  
~~3. 编写 `src/tests/test_rules.py`。~~

### 第 2 组（预处理层） - ✅ 已全部完成

~~4. 重写 `src/preprocess/demand_solver.py`，去掉专属硬绑定与不安全实现。按"全局池化 + 仅输出需求/机器数/端口预算"原则重构。~~  
~~5. 编写 `src/tests/test_demand.py`。~~  
~~6. 重写 `src/preprocess/instance_builder.py`，明确 mandatory / optional / provisional 边界。~~

### 第 3 组（几何层） - 🚧 当前激活阶段

7. 重写 `src/placement/placement_generator.py`，修正 pool key、边界遍历与过强剪枝。
8. 编写 `src/placement/occupancy_masks.py`
9. 编写 `src/placement/symmetry_breaking.py`
10. 编写 `src/tests/test_placements.py`

---

## 11. 生效说明

本文件自写入仓库起立即生效。

凡与历史聊天、旧草稿、临时代码、未审查 AI 输出相冲突之处，一律以本文件和 `FILE_STATUS.md` 的联合定义为准。