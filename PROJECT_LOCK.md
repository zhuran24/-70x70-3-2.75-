# PROJECT_LOCK.md

**Status**: ACCEPTED_DRAFT  
**Updated**: 2026-03-18  
**Purpose**: 锁定当前项目在 `certified_exact`（严格认证精确）与 `exploratory`（探索）两条路径下的边界、禁止事项、证据规则与变更流程。  
**Reading rule**: 若旧聊天、旧日志、旧 `cuts`（切平面）、旧实现、旧文档与本文件冲突，以本文件为准。  

---

## 1. 本文件锁定的是什么

本文件锁定的不是“整个仓库已经完全完成并永久冻结”，而是：

1. 当前项目必须坚持的 `strict exact boundary`（严格精确边界）。
2. `certified_exact`（严格认证精确）与 `exploratory`（探索）两条路径的使用范围。
3. 哪些输入、工件、日志、旧 `cuts` 可以进主线，哪些绝对不能进。
4. 后续改动时，什么必须同步更新，什么不能偷偷改。

**当前总判断**：

- 本项目现在已经不应再被描述成“单路径、全仓库、完全冻结的精确求解器”。
- 当前正确说法应是：**仓库已经建立了严格精确主线，但仍允许保留探索与兼容层；两者必须严格分离。**
- 任何会污染 `certified_exact`（严格认证精确）证据链的旧逻辑、经验上限、旧 `cuts`、近似筛子，都不得再伪装成正式精确证据。

---

## 2. 这个项目当前真正锁定的核心目标

当前锁定目标不是“立刻保证 70×70 最终问题已经会在 168 小时内出证书”，而是先锁死下面这几件事：

1. **严格精确口径必须干净。**
2. **探索路径不得污染严格精确路径。**
3. **历史材料不得再冒充当前版本现状。**
4. **后续所有提速，都必须是 `exact-safe`（精确安全）的提速，而不是偷砍搜索空间。**
5. **求解器必须具备最长 `168` 小时 `campaign`（持续战役）运行与恢复的基础设施。**

换句话说：

- 允许继续开发；
- 不允许再假装“已经没有边界问题”；
- 不允许再把经验上限、旧 `cuts`、近似流筛、历史日志写成严格精确证据；
- 不允许用“测试通过”替代“严格精确口径成立”。

---

## 3. 当前锁定的双路径架构

### 3.1 `certified_exact`（严格认证精确）路径

这条路径只允许使用下面这些东西：

1. `rules/canonical_rules.json`（规则真源）
2. `data/preprocessed/candidate_placements.json`（候选位姿全集）
3. `data/preprocessed/mandatory_exact_instances.json`（严格精确必选实例工件）
4. `data/preprocessed/generic_io_requirements.json`（通用输入输出需求工件）
5. `operation profiles`（操作端口画像）
6. provenance-complete（来源完整）且哈希匹配的 `exact_safe cuts`（严格精确安全切平面）
7. 绑定与路由给出的严格失败证明
8. `campaign state`（战役状态）里哈希一致的已持久化严格证据

这条路径明确禁止使用下面这些东西：

1. `provisional`（临时经验上限）实例
2. `50 / 10` 这类探索模式经验上限
3. `data/preprocessed/all_facility_instances.json` 作为严格精确主输入
4. `data/preprocessed/exploratory_optional_caps.json`
5. `data/solutions/cuts_*.json` 这类 legacy `cuts`（历史遗留切平面）
6. `flow_subproblem.py` 的失败结论直接形成正式剪枝
7. 未证明安全的 `power-pole area lower bound`（供电桩面积下界）
8. 历史日志中的性能数字作为“当前版本性能现状”

### 3.2 `exploratory`（探索）路径

这条路径允许使用下面这些东西：

1. `data/preprocessed/all_facility_instances.json`
2. `data/preprocessed/exploratory_optional_caps.json`
3. `data/solutions/cuts_*.json`
4. `src/models/flow_subproblem.py` 作为加速器或诊断器
5. 兼容旧实验流程的热启动、筛子、旧缓存、旧 `cuts`、经验上限

但必须满足：

- `exploratory` 的任何结果都不得标记成 `CERTIFIED`（已认证）。
- 探索模式产出的 `cuts`、缓存、日志、结果，都必须带上模式来源。
- 探索路径只能用于试探、调参、定位瓶颈、建立候选假设，不能冒充严格精确证据。

---

## 4. 当前锁定的数据真值

以下数据当前视为已对齐事实，后续文档、测试、说明不得再写错：

1. 网格尺寸：`70 × 70`
2. 候选位姿总数：`81,795`
3. 制造单位总数：`219`
4. 强制精确实例数：`266`
5. 探索兼容实例总数：`326`
6. 探索模式经验上限：
   - `power_pole`（供电桩）=`50`
   - `protocol_storage_box`（协议储存箱）=`10`
7. 严格安全的静态占地下界：`3544`
8. `generic_io_requirements.json` 已取代绑定子问题内部写死的默认 generic I/O 常量
9. 默认严格精确战役预算：`168` 小时

**注意**：

- 旧版把 `power-pole area lower bound`（供电桩面积下界）混入静态占地下界的做法，当前已经被视为**不得进入严格精确剪枝**。
- 旧版日志里出现的 `39x25 / 4.40GB / 46~47s` 与 `36x35 / 3,976,931 variables / 174,694 constraints` 这类数字，当前只能视为**历史实验记录**，不能再自动当成新版本现状。

---

## 5. 当前锁定的模块边界

### 5.1 预处理层

#### `src/preprocess/demand_solver.py`
必须负责生成：

- `commodity_demands.json`
- `machine_counts.json`
- `port_budget.json`
- `generic_io_requirements.json`

并且：

- `generic source/sink requirements`（通用源汇需求）必须从这里输出为工件；
- 不允许再长期藏在绑定模型内部当默认常量。

#### `src/preprocess/instance_builder.py`
必须负责生成：

- `mandatory_exact_instances.json`
- `exploratory_optional_caps.json`
- `all_facility_instances.json`

并且：

- `mandatory_exact_instances.json` 才是严格精确主线的正式实例工件；
- `50 / 10` 之类经验上限只能留在探索工件中；
- 不允许再把经验上限伪装成严格精确域定义。

#### `src/placement/placement_generator.py`
职责是生成：

- `candidate_placements.json`

并且：

- 候选位姿全集是严格精确主线下可选设施的正式有限域来源；
- 不允许退回“靠 counted clones（预生成实例数量）定义可选设施上界”的旧做法。

### 5.2 主模型层

#### `src/models/master_model.py`
必须满足：

1. 接收 `solve_mode`（求解模式）
2. 在 `certified_exact` 下，不再用 `50 / 10` 经验上限约束 `optional poses`（可选位姿）
3. 在 `exploratory` 下，允许继续读取经验上限并加 cap（上限）
4. `extract_solution()` 必须能为 `pose-level optional facilities`（位姿级可选设施）生成可被下游识别的完整条目
5. 在 `certified_exact` 下，允许使用只基于几何不冲突与理论供电可覆盖性的 `exact-safe greedy warm start`（严格精确安全贪心热启动），但它只能作为求解提示，不得被写成严格精确证据

这意味着：

- 严格精确主线中，可选设施的上界来自 `candidate placements`（候选位姿全集）本身；
- 不能再依赖预先生成好的 `protocol_box_001..010`、`power_pole_001..050` 之类编号做正式域定义。
- 严格精确主线允许有保守版 warm start，但该 warm start 不得使用探索模式经验上限、流量诊断或历史日志。

### 5.3 绑定 / 路由层

#### `src/models/binding_subproblem.py`
必须满足：

- 只从工件读取 `generic_io_requirements.json`
- 能识别 `pose_optional::...` 这种位姿级可选设施实例
- 不允许回退到长期写死默认业务需求的旧做法

#### `src/models/routing_subproblem.py`
当前允许作为严格精确子问题的一部分继续使用。

#### `src/models/flow_subproblem.py`
当前锁定角色是：

- 在严格精确路径中，只能是 `diagnostic`（诊断器）
- 在探索路径中，可以是 `accelerator`（加速器）

**不得**：

- 单独生成严格精确不可行证明
- 单独生成严格精确正式剪枝

### 5.4 `cuts` / 搜索 / 战役层

#### `src/models/cut_manager.py`
必须负责：

- `cut provenance`（切平面来源追踪）
- `artifact hash`（工件哈希）
- `exact_safe`（严格精确安全标记）
- 探索与严格精确两条路径的 `cut` 读写边界

#### `src/search/benders_loop.py`
必须负责阻拦：

1. `provisional` 输入混入 `certified_exact`
2. legacy `cuts`
3. 模式污染
4. 哈希不一致
5. 不安全的旧剪枝逻辑回流

#### `src/search/exact_campaign.py`
必须负责：

- 最长 `168` 小时级别的战役状态保存
- 哈希一致时恢复
- 严格精确证据的持续累积

#### `src/search/outer_search.py`
必须保持：

- 目标仍然是“最大连续矩形空地”
- 外层剪枝必须是 `exact-safe`（精确安全）的
- 不得再偷偷恢复未证明安全的供电桩下界

---

## 6. 当前锁定的严格禁止事项

以下行为当前被明确禁止：

1. 把 `provisional`（临时经验上限）实例装进 `certified_exact` 路径。
2. 把 `exploratory_optional_caps.json` 装进 `certified_exact` 路径。
3. 把 `all_facility_instances.json` 当成严格精确主输入继续沿用。
4. 把 legacy `cuts`（遗留旧切平面）装进 `certified_exact` 路径。
5. 把 `flow_subproblem.py` 的失败结论写成严格精确证书。
6. 把未证明安全的 `power-pole area lower bound` 写成严格精确下界。
7. 把探索模式结果命名成 `CERTIFIED`。
8. 把历史日志里的性能数字写成当前版本现状。
9. 在未同步更新本文件与 `FILE_STATUS.md` 的前提下，新增新的模式边界、工件边界或证据边界。
10. 将 `logs/image copy.png`（农业自循环示意图）的几何图样直接硬编码成固定宏模块。

---

## 7. 当前锁定的允许事项

以下变更在当前项目锁下允许进行：

1. 增强 `exact-safe tests`（严格精确安全测试）。
2. 强化 `campaign state`（战役状态）的字段、恢复逻辑与摘要信息。
3. 为探索路径继续加速，但前提是不污染严格精确路径。
4. 增加更强的 `exact-safe lower bounds`（严格精确安全下界），前提是它们有明确数学安全性依据。
5. 增加更强的 `dominance pruning`（支配性剪枝）与 `symmetry breaking`（对称性打破），前提是它们不砍合法解空间。
6. 补更强的缓存与复用，但必须带模式来源、工件哈希与恢复校验。
7. 继续把文档改得更诚实、更易读。

---

## 8. 当前锁定的证据规则

### 8.1 什么才算 `certified_exact evidence`（严格精确证据）

只有满足下面条件的东西，才允许被称为严格精确证据：

1. 来源模式是 `certified_exact`
2. 输入工件哈希与当前运行完全一致
3. 证明链可追踪
4. 没有使用被禁止的探索输入或近似筛子
5. 对应测试与文档没有与之冲突的口径错误

### 8.2 `cuts`（切平面）进入严格精确路径的条件

只有同时满足下面条件的 `cuts` 才允许进入 `certified_exact`：

- `source_mode == certified_exact`
- `exact_safe == true`
- `artifact_hashes` 与当前工件完全一致
- 证明阶段清晰可追踪

### 8.3 `campaign state`（战役状态）允许恢复的条件

只有在以下工件哈希全部一致时，才允许恢复严格精确战役：

- `mandatory_exact_instances.json`
- `candidate_placements.json`
- `generic_io_requirements.json`
- `canonical_rules.json`

必要时还应包含：

- 关键代码版本或 schema（结构模式）版本
- 输出摘要版本

### 8.4 `whole-layout no-good cut`（整布局禁忌切平面）写回条件

只有在以下任一条件成立时，才允许把整布局写回为严格精确 `no-good`（禁忌）证据：

1. 绑定子问题本身已被严格证明不可行；或
2. 绑定已被严格穷尽，且每个可行绑定都被严格路由证伪。

---

## 9. 当前锁定的文档诚实义务

从当前版本开始，以下表述必须强制诚实：

1. 不能再把整个仓库写成“已经完全冻结并已全局认证”。
2. 不能把 `flow_subproblem.py` 写成严格精确剪枝器。
3. 不能把历史 `cuts` 写成天然可复用的严格证书。
4. 不能把 `exploratory` 的能力表述成 `certified_exact` 的能力。
5. 所有关于候选位姿总数的表述必须对齐到 `81,795`。
6. 所有关于严格安全静态占地下界的表述必须对齐到 `3544`。
7. 历史日志只能写成“归档 / 历史记录”，不能写成“当前版本性能现状”。

---

## 10. 当前仍未锁死、不得冒充“已解决”的事项

以下内容当前仍然开放，不得被误写成“已经做完”：

1. full-scale（全尺寸）70×70 问题的最终 `CERTIFIED` 终局结果。
2. 是否还需要更强的 `exact-safe lower bounds`（严格精确安全下界）。
3. 是否还需要更强的 `dominance rules`（支配规则）与 `symmetry breaking`（对称性打破）来压缩搜索。
4. 中等规模与全尺寸的真实性能画像。
5. 输出 schema（输出结构）与最终 serializer（序列化）规范是否完全稳定。
6. 若干历史 `specs`（规格文档）与现代码的最终清理顺序。
7. `168` 小时目标在全尺寸问题上是否现实；当前只能说“基础设施已开始具备”，不能说“已经证明可达”。

---

## 11. 当前锁定的未来运行角色优先级

当某个文件“存在于仓库中”与“是否仍可进入严格精确主路径”发生冲突时，以它的 `runtime_role`（运行角色）为准，而不是以“它还在仓库里”或“它是新文件”来判断。

也就是说：

- **仓库里存在，不等于严格精确主线会继续读取。**
- **旧日志存在，不等于当前版本性能就是旧日志写的那样。**
- **探索工件存在，不等于严格精确主线还能继续读它。**

这条规则必须与 `FILE_STATUS.md` 保持一致。

---

## 12. 变更流程

只要涉及以下任一事项，就必须同步更新：

1. `PROJECT_LOCK.md`
2. `FILE_STATUS.md`
3. 对应代码 / 工件 / 测试 / 文档本体

每次变更必须明确说明：

- 这次改动属于 `certified_exact` 还是 `exploratory`
- 是否影响 `exact-safe evidence chain`（严格精确证据链）
- 是否引入了新的工件文件
- 是否影响了 `campaign hash`（战役哈希）兼容性
- 是否改变了文件的未来运行角色

如果这几点说不清，就不允许把该改动宣称为“已经锁定”。

---

## 13. 一句话版本的项目锁

**当前项目锁的核心不是“仓库已经完全完成”，而是“严格精确主线的边界已经明确，探索路径必须被隔离，后续所有提速都必须在不污染 `certified_exact` 的前提下进行”。**
---

## 2026-03-16 Lock Addendum: Exact Local Power Capacity Lower Bound

- Scope: `certified_exact`
- This change extends the allowed `exact-safe lower bounds` line with a concrete implemented family inside `src/models/master_model.py`.
- The new bound is a template-level power-capacity inequality:
  `sum(local_exact_capacity[pole_idx, template] * y_power_pole[pole_idx]) >= mandatory_exact_count[template]`
- Coefficients are exact-safe because each `local_exact_capacity` is computed from a local same-template non-overlap micro-model under the current power-coverage semantics.
- Ghost awareness is indirect only: ghost occupancy can force pole poses to `0`, which tightens the same inequality without any explicit `u_var`-conditioned coefficient table.
- This is still not the forbidden `power-pole area lower bound`.
- No new artifact files are introduced.
- `campaign hash` compatibility rules do not change.

## 2026-03-16 Lock Addendum: Static Exact Core Reuse And 2D Frontier

- Scope: `certified_exact`
- This change allows a candidate-independent exact master core to be built once and cloned into per-ghost overlays.
- The reuse layer changes solver engineering only; it does not change the exact-safe evidence chain, artifact hashes, or cut admissibility rules.
- Exact outer search is now allowed to derive prune decisions from explicit candidate terminal results using componentwise monotonicity on the explicit candidate domain.
- Derived frontier/prune state is runtime-only:
  - it must be recomputed from persisted candidate records on resume
  - it must not introduce a new campaign schema field or artifact file in this round
- `UNKNOWN` and `UNPROVEN` remain non-monotone outcomes:
  - they cannot create upper/lower closure
  - they remain retryable on resume
- Exact-safe whole-layout cuts remain candidate-local and may be replayed only into the current overlay for that candidate.
- No new artifact files are introduced.
- `campaign hash` compatibility rules do not change.

## 2026-03-16 Lock Addendum: Certification-First Frontier Scheduling

- Scope: `certified_exact`
- Exact outer search is allowed to choose the next frontier candidate by a deterministic prune-first score instead of strict objective order.
- The currently locked policy is:
  - `frontier_selection_policy = certification_prune_per_anchor_v1`
  - prefer higher `certification_prune_gain / anchor_count`
  - then higher `certification_prune_gain`
  - then lower `anchor_count`
  - then higher `infeasible_prune_gain`
  - then the existing objective order `area DESC, width DESC, height DESC`
- This changes search scheduling only:
  - it does not change the exact-safe evidence chain
  - it does not promote exploratory information into certified exact mode
  - it does not change master/binding/routing admissibility
- Partial runs are now explicitly locked to `Prune-First` semantics:
  - the set of already solved candidates is no longer required to be an objective-prefix
  - persisted candidate records remain the only recoverable truth
  - frontier scores and derived prune state must be recomputed on resume and must not be persisted as new campaign schema
- `UNKNOWN` and `UNPROVEN` remain non-monotone and retryable.
- No new artifact files are introduced.
- `campaign hash` compatibility rules do not change.

## 2026-03-16 Lock Addendum: Two-Stage Exact Subproblem Cut Ladder

- Scope: `certified_exact`
- This change extends the allowed exact-safe evidence chain with a two-stage subproblem cut ladder inside `src/search/benders_loop.py`.
- The currently locked fine-grained persisted cut types are:
  - `binding_pose_domain_empty_nogood`
  - `routing_front_blocked_nogood`
- Admissibility rules:
  - `binding_pose_domain_empty_nogood` is allowed only when a placed exact instance has zero legal exact binding domain at its current pose
  - `routing_front_blocked_nogood` is allowed only when a required routing front cell is blocked by the current placement and the blocking proof is placement-local and monotone under adding more facilities
  - ghost anchors must not appear in these persisted conflict sets
- The currently locked non-persisted rejection rule is:
  - `relaxed_disconnected` may reject only the current binding selection
  - it may add a binding-level nogood
  - it must not be persisted as a master cut in this round without a stronger placement-local certificate
- Whole-layout exact-safe cuts remain restricted to:
  - binding-wide exact infeasibility
  - routing exhaustion after strict binding enumeration
- This update changes exact controller behavior only:
  - it does not introduce exploratory information into certified exact mode
  - it does not add a new artifact file or campaign schema field
  - it does not change `campaign hash` compatibility rules

## 2026-03-16 Lock Addendum: Terminal-Aware Commodity Routing Core Shrink

- Scope: `certified_exact`
- This change allows `src/models/routing_subproblem.py` to shrink the routing state space before CP-SAT build, but only by exact-safe domain restriction.
- The currently locked admissible shrink steps are:
  - restrict each commodity to the free-cell connected component containing its front terminals
  - iteratively peel non-terminal cells with active degree `< 2`
  - create routing states only when every local `flow_in/flow_out` direction is supported by an active neighbor or the corresponding ground-layer terminal condition
- The currently forbidden shrink steps remain:
  - bounding-box corridor restriction
  - Manhattan corridor restriction
  - A* or shortest-path heuristic filtering
  - any exploratory or historical-route prior
- Elevated bridge states remain admissible only when both opposite neighboring active cells exist for that commodity.
- This update changes routing engineering only:
  - it does not change exact-safe evidence admissibility
  - it does not add a new artifact file or campaign schema field
  - it does not change `campaign hash` compatibility rules

## 2026-03-17 Lock Addendum: Placement-Fixed Exact Subproblem Reuse

- Scope: `certified_exact`
- This change extends the allowed exact-safe engineering reuse inside `src/models/port_binding.py`, `src/models/binding_subproblem.py`, `src/models/routing_subproblem.py`, and `src/search/benders_loop.py`.
- The currently locked admissible reuse steps are:
  - memoize pose-level exact binding domains by `operation_type + normalized port geometry`
  - reuse a placement-fixed routing core built from `occupied_cells` and `occupied_owner_by_cell`
  - rebuild only binding-selection-specific routing overlays and front-terminal analysis on top of that placement-fixed core
- The currently locked safety restrictions are:
  - reuse is process-memory only
  - reuse must not write or depend on a new artifact file
  - reuse must not change exact-safe cut admissibility
  - generic-slot operations must remain in the higher-level binding model and must not be collapsed into cached pose-level exact domains
- The currently locked observability additions are:
  - exact summaries may expose `used_routing_core_reuse`
  - exact summaries may expose `routing_core_build_seconds`
  - exact summaries may expose `routing_overlay_build_seconds`
  - exact summaries may expose binding-domain cache hit/miss counters
- This update changes exact solving engineering only:
  - it does not introduce exploratory information into certified exact mode
  - it does not add a campaign schema field
  - it does not change `campaign hash` compatibility rules

## 2026-03-17 Lock Addendum: Exact Search Guidance

- Scope: `certified_exact`
- This change extends the allowed exact-safe engineering guidance inside `src/models/master_model.py`, `src/models/binding_subproblem.py`, and `src/search/benders_loop.py`.
- The currently locked admissible guidance steps are:
  - deterministic branching over grouped mandatory pose literals in the exact master
  - deterministic branching over ghost-anchor literals in the exact master
  - deterministic branching over pose-level optional facility literals in the exact master
  - deterministic branching over exact binding-choice and generic-slot assignment literals in the exact binding model
  - exact CP-SAT parameter tuning that remains completeness-preserving
- The currently locked safety restrictions are:
  - guidance must not remove or relax any feasible exact solution
  - guidance must not depend on exploratory artifacts, historical logs, or legacy cuts
  - guidance may bias search order, but it must not change exact-safe evidence admissibility
- The currently locked observability additions are:
  - master build and solve stats may expose an exact search profile
  - binding summaries may expose an exact binding search profile
  - exact run metadata may expose `master_search_profile` and `binding_search_profile`
- This update changes solver search order only:
  - it does not add a new artifact file
  - it does not add a campaign schema field
  - it does not change `campaign hash` compatibility rules

## 2026-03-17 Lock Addendum: Exact Optional Cardinality Bounds

- Scope: `certified_exact`
- This change extends the allowed exact-safe lower-bound / upper-bound line inside `src/models/master_model.py` using `data/preprocessed/generic_io_requirements.json`.
- The currently locked admissible optional-cardinality steps are:
  - derive a fixed `protocol_storage_box` count from total `required_generic_inputs` divided by the exact wireless-sink slot count per box
  - enforce that `power_pole` count cannot exceed the number of selected powered non-pole facilities
- The currently locked safety restrictions are:
  - these bounds must be justified from current certified artifacts or current exact model semantics
  - these bounds must not reintroduce exploratory `50 / 10` caps under another name
  - these bounds must remain completeness-preserving for certified exact mode
- The currently locked observability additions are:
  - master global-valid-inequality stats may expose `optional_cardinality_bounds`
- This update changes exact-safe pruning only:
  - it does not add a new artifact file
  - it does not add a campaign schema field
  - it does not change `campaign hash` compatibility rules

## 2026-03-17 Lock Addendum: Certified Optional Lower-Bound Propagation

- Scope: `certified_exact`
- This change extends the allowed exact-safe propagation line from artifact-backed optional cardinality into `src/models/master_model.py`, `src/search/benders_loop.py`, and `src/search/outer_search.py`.
- The currently locked admissible propagation steps are:
  - derive certified-exact optional lower bounds from current certified artifacts and current template semantics
  - keep those lower bounds available to exact static occupied-area lower bounds, diagnostics, and powered-demand lower bounds
  - do not promote `protocol_storage_box` into `exact_required_optionals` or a dedicated exact-required search-guidance layer unless an independent sufficiency proof exists
- The currently locked safety restrictions are:
  - this must not rewrite pose-level optionals into mandatory instances
  - this must not change solution ids, cut conflict-set keys, or campaign record schema
  - only independently proven exact fixed counts may enter `exact_required_optionals`; exploratory caps and historical heuristics remain forbidden
- The currently locked observability additions are:
  - master build stats may expose `exact_required_optionals` for truly exact counts only
  - master build stats may expose `exact_optional_lower_bounds` for certified-exact lower-bound-only propagation
  - master search-guidance stats may expose `required_optional_literals` and `residual_optional_literals`
  - global-valid-inequality stats may expose `fixed_required_optional_demands` for exact counts only and `lower_bound_optional_powered_demands` for lower-bound-only propagation
- This update changes exact-safe pruning and guidance only:
  - it does not add a new artifact file
  - it does not add a campaign schema field
  - it does not change `campaign hash` compatibility rules

## 2026-03-17 Lock Addendum: Signature-Count Guided Exact Master Prune

- Scope: `certified_exact`
- This change extends the allowed exact-safe guidance and aggregation line inside `src/models/master_model.py`.
- The currently locked admissible steps are:
  - keep grouped encoding as the only clone-permutation reduction layer across mandatory instances
  - add group-local pose-signature count variables built from normalized occupied/front/power-coverage geometry
  - branch on those signature-count variables before raw mandatory pose literals and before raw exact-required optional pose literals
  - aggregate exact local power-capacity lower bounds through `power_pole` coefficient families when poles share the same coefficient vector across powered exact-demand templates
- The currently locked safety restrictions are:
  - local pose signatures must remain candidate-independent and must not depend on ghost placement, exploratory caps, history, or legacy artifacts
  - this must not rewrite raw pose literals, solution ids, cut conflict-set keys, or campaign state schema
  - this must not introduce a new artifact file or change `campaign hash` compatibility rules
- The currently locked observability additions are:
  - master build stats may expose `signature_buckets`
  - master search-guidance stats may expose `mandatory_signature_counts` and `required_optional_signature_counts`
  - global-valid-inequality stats may expose `power_capacity_families` and `aggregated_power_capacity_terms`

## 2026-03-17 Lock Addendum: Coordinate-Encoded Exact Master

- Scope: `certified_exact`
- This change extends the allowed exact-safe master-engineering line inside `src/models/master_model.py`, `src/models/exact_coordinate_master.py`, and `src/search/benders_loop.py`.
- The currently locked admissible steps are:
  - replace grouped mandatory raw pose booleans as the primary exact-master representation with coordinate slots over `(x, y, mode)`
  - keep grouped mandatory clone reduction through deterministic slot ordering rather than raw pose-literal symmetry alone
  - represent exact-required pose optionals through the same coordinate-slot machinery
  - represent residual `power_pole` facilities through an exact-safe optional slot pool bounded by powered exact demand
  - keep exact solution extraction and Benders cut replay compatible with existing `pose_idx`, `pose_id`, and `pose_optional::...` wire shapes
  - expose coordinate-master reuse through the existing exact core / overlay lifecycle
  - factor exact mandatory and exact-required slot domains into validated mode-rect domains instead of slot-level pose tables
  - derive compact signature membership only from validated rectangle / strip / ring geometry within those mode-rect domains
  - derive residual `power_pole` family ids from validated shell-distance lookup over `sorted(dx, dy)`
- The currently locked safety restrictions are:
  - this must remain completeness-preserving for certified exact mode
  - this must not change cut admissibility, solution schema, campaign schema, or artifact-hash rules
  - this must not reintroduce exploratory caps, legacy cuts, or historical heuristics into certified exact mode
  - grouped mandatory cuts must retain their existing stronger replay semantics when mapped onto coordinate slots
- The currently locked observability additions are:
  - master build stats may expose `master_representation = coordinate_exact_v2`
  - master build stats may expose `master_domain_encoding = mode_rect_factorized_v1`
  - master build stats may expose `master_domain_table_rows`
  - master build stats may expose `master_mode_rect_domains`
  - master build stats may expose `power_pole_shell_lookup_pairs`
  - master build stats may expose `master_slot_counts`, `master_interval_count`, `master_mode_literals`, and `master_pose_bool_literals`
  - exact run metadata may expose the same coordinate-master summary fields
- This update changes exact master representation and engineering only:
  - it does not add a new artifact file
  - it does not add a campaign schema field
  - it does not change `campaign hash` compatibility rules

## 2026-03-18 Lock Addendum: Exact Campaign Hardening

- Scope: `certified_exact`
- This change extends the allowed campaign-state hardening line inside `src/search/exact_campaign.py`, `src/search/outer_search.py`, and `src/search/benders_loop.py`.
- The currently locked admissible steps are:
  - require `schema_version`, `proof_summary_schema_version`, `solve_mode`, artifact hashes, and required state fields to all match before resuming a persisted exact campaign
  - auto-reset incompatible or malformed persisted exact campaign state instead of reusing it
  - persist terminal candidate records for `CERTIFIED`, `INFEASIBLE`, `UNKNOWN`, and `UNPROVEN` together with `proof_summary`, `exact_safe_cuts`, and loaded/generated exact-safe cut counts
  - persist `last_stop_reason`, `final_status`, and `final_result` in a way that stays aligned with the actual exact run outcome
- The currently locked safety restrictions are:
  - resume must not cross `solve_mode = certified_exact` boundaries or artifact-hash mismatches
  - this hardening must not change exact feasible sets, cut admissibility, or proof semantics
  - this round must not add a new external artifact file or change exact artifact-hash compatibility rules
- The currently locked observability additions are:
  - campaign state may expose `schema_version`, `proof_summary_schema_version`, `reset_reason`, `final_status`, and `last_stop_reason`
  - persisted candidate records may expose stable exact-safe cut counters and `proof_summary`

## 2026-03-18 Lock Addendum: `coordinate_exact_v3` Power-Pole Family-Guided Residual Search

- Scope: `certified_exact`
- This change extends the allowed exact-safe master-search line inside `src/models/exact_coordinate_master.py` and the exact metadata bridge in `src/search/benders_loop.py`.
- The currently locked admissible steps are:
  - guide residual `power_pole` search first through exact-safe family-count variables, then through slot-level `active -> family -> x -> y` branching
  - enforce residual active-slot symmetry reduction through active-prefix ordering, nondecreasing family order, and nondecreasing `order_key` inside one family
  - keep sparse non-rectangular toy domains exact by using internal allowed-assignment fallback rows when the compressed mode-rect path is not exact
- The currently locked safety restrictions are:
  - this family-guided search layer applies only to residual `power_pole` slots and must not change mandatory, required-optional, cut, or solution wire shapes
  - any sparse-domain fallback must remain completeness-preserving and exact-safe, and must not silently relax the compressed full-project path
- The currently locked observability additions are:
  - the locked search profile name is `exact_coordinate_guided_branching_v4`
  - master search-guidance stats and exact metadata may expose `power_pole_family_order`, `power_pole_family_count_literals`, and `residual_optional_family_guided`

## 2026-03-18 Lock Addendum: Witness-Indexed Geometric Power Coverage

- Scope: `certified_exact`
- This change extends the allowed exact-safe master-compression line inside `src/models/exact_coordinate_master.py` and the exact metadata bridge in `src/search/benders_loop.py`.
- The currently locked admissible steps are:
  - encode geometric `power_coverage` as one witness pole index per powered slot, bound through `AddElement` to ordered residual `power_pole` slot arrays
  - keep the geometric coverage semantics unchanged: coverage is still witness-based existential reachability, and one active pole may cover multiple powered exact-demand slots
  - keep the non-geometric `coordinate_cover_table` fallback exact and admissible without forcing it onto the new encoding
- The currently locked safety restrictions are:
  - this change must not alter exact feasible sets, cut admissibility, binding/routing proof semantics, or external solution wire shapes
  - this round must not add a new artifact file, campaign field, or `campaign hash` compatibility rule
- The currently locked observability additions are:
  - geometric power-coverage stats may expose `encoding = geometric_element_witness_v1`
  - geometric power-coverage stats may expose `witness_indices`, `element_constraints`, and `cover_literals = 0`
  - exact run metadata may expose the same power-coverage summary fields

## 2026-03-18 Lock Addendum: Exact Precompute Collapse

- Scope: `certified_exact`
- This change extends the allowed exact-safe initialization-compression line inside `src/models/master_model.py`, `src/models/exact_coordinate_master.py`, and `src/search/benders_loop.py`.
- The currently locked admissible steps are:
  - precompute normalized pose geometry once per template / pose and reuse it across occupancy indexing, local-signature construction, and exact-safe power-capacity preprocessing
  - derive `power_pole` shell pairs once and reuse them as the primary grouping key for exact local power-capacity coefficient evaluation
  - evaluate exact local power-capacity coefficients once per `(template, shell_pair)` when the shell-pair bucket is geometry-uniform, then broadcast the coefficient to all raw poles in that bucket
  - retain exact per-geometry fallback inside a shell-pair bucket when custom toy geometry makes one shell pair non-uniform, rather than weakening exactness
  - memoize signature-bucket payloads and coordinate-domain payloads by `(template, candidate_pose_set)` so repeated mandatory groups reuse the same exact-safe domain analysis
- The currently locked safety restrictions are:
  - this round changes only certified-exact initialization and preprocessing; it must not change exact feasible sets, cut admissibility, proof semantics, solution schema, or campaign schema
  - no exploratory caps, legacy cuts, or historical heuristics may be reintroduced into the certified exact path
  - no new artifact file is introduced and no `campaign hash` compatibility rule changes
- The currently locked observability additions are:
  - master build stats may expose `exact_precompute_profile`
  - `exact_precompute_profile` may expose `power_capacity_shell_pairs`, `power_capacity_shell_pair_evaluations`, `power_capacity_raw_pole_evaluations`, `signature_bucket_cache_hits`, `signature_bucket_cache_misses`, `signature_bucket_distinct_keys`, and `geometry_cache_templates`
  - exact global valid-inequality stats may expose `power_capacity_families.coefficient_source = shell_pair_cache_v1`
  - exact global valid-inequality stats may expose `power_capacity_families.shell_pair_count`
  - exact run metadata may expose the same precompute-profile summary fields through `run_benders_for_ghost_rect.last_run_metadata`

## 2026-03-18 Lock Addendum: Local-Capacity Signature-Class Cache

- Scope: `certified_exact`
- This change extends the allowed exact-safe preprocessing reuse line inside `src/models/master_model.py`, `src/models/exact_coordinate_master.py`, and `src/search/benders_loop.py`.
- The currently locked admissible steps are:
  - treat the exact local-capacity signature class, not shell pair alone, as the decisive reuse key for certified-exact local power-capacity coefficient evaluation
  - evaluate each `(template, exact local-capacity signature class)` at most once per process-memory cache state, then broadcast that coefficient to every raw `power_pole` pose in the class
  - continue exposing shell-pair grouping as an observability and diagnostic layer, without using it as the final coefficient truth source
  - continue reusing `(template, candidate_pose_set)` signature/domain payload memoization for repeated exact groups and required optionals
- The currently locked safety restrictions are:
  - this round changes only certified-exact preprocessing reuse; it must not change exact feasible sets, cut admissibility, proof semantics, solution schema, or campaign schema
  - if future artifacts break the assumption that exact local-capacity coefficients are determined by the exact local-capacity signature class, certified exact must fail fast instead of silently widening the cache key or reverting to heuristic reuse
  - no new artifact file is introduced and no `campaign hash` compatibility rule changes
- The currently locked observability additions are:
  - `exact_precompute_profile` may expose `power_capacity_signature_classes` and `power_capacity_signature_class_evaluations`
  - exact global valid-inequality stats may expose `power_capacity_families.coefficient_source = exact_signature_cache_v2`
  - exact run metadata may expose the same new precompute summary fields through `run_benders_for_ghost_rect.last_run_metadata`

## 2026-03-19 Lock Addendum: Local-Capacity Oracle v3

- Scope: `certified_exact`
- This change extends the allowed exact-safe preprocessing and local-oracle line inside `src/models/master_model.py`, `src/models/exact_coordinate_master.py`, and `src/search/benders_loop.py`.
- The currently locked admissible steps are:
  - treat compact local-capacity items as `(dx, dy, local_shape_token)`, where `local_shape_token` is interned directly from the exact cached `LocalPoseShape`
  - use that compact signature as the primary class-building key for certified-exact local power-capacity preprocessing, instead of repeatedly materializing full shifted cell tuples for every raw pole
  - keep a deterministic legacy-materialization consistency check from compact signature back to the exact legacy `LocalCapacitySignature`, and fail fast on mismatch instead of silently widening or weakening the encoding
  - use a custom exact bitset MIS oracle as the default local-capacity evaluator
  - keep the legacy tiny CP-SAT local-capacity oracle as an exact fallback only, with explicit counters and no silent downgrade
- The currently locked safety restrictions are:
  - `(dx, dy, orientation)` alone is not an admissible certified-exact key; the compact signature truth source must remain the exact cached local occupied shape
  - this round changes only certified-exact preprocessing/oracle internals; it must not change exact feasible sets, cut admissibility, solution schema, campaign schema, or proof semantics
  - any compact-signature inconsistency must hard-fail; any local-oracle fallback must remain exact by returning to the legacy CP-SAT oracle
  - no new artifact file is introduced and no `campaign hash` compatibility rule changes
- The currently locked observability additions are:
  - `exact_precompute_profile` may expose `power_capacity_compact_signature_classes`, `power_capacity_compact_signature_evaluations`, `power_capacity_compact_signature_cache_hits`, `power_capacity_compact_signature_cache_misses`, `power_capacity_bitset_oracle_evaluations`, `power_capacity_cpsat_fallbacks`, and `power_capacity_oracle = bitset_mis_v1`
  - exact global valid-inequality stats may expose `power_capacity_families.coefficient_source = exact_compact_bitset_cache_v3`
  - exact global valid-inequality stats may expose `power_capacity_families.compact_signature_class_count`
  - exact run metadata may expose the same new precompute/oracle summary fields through `run_benders_for_ghost_rect.last_run_metadata`

## 2026-03-19 Lock Addendum: Local-Capacity Oracle v4

- Scope: `certified_exact`
- This change extends the allowed exact-safe local-oracle line inside `src/models/master_model.py`, `src/models/exact_coordinate_master.py`, and `src/search/benders_loop.py`.
- The currently locked admissible steps are:
  - use `rectangle_frontier_dp_v1` as the primary local-capacity oracle when the compact local-capacity signature is composed entirely of exact cached full-rectangle local shapes
  - continue treating `(dx, dy, local_shape_token)` as the decisive compact truth source for certified-exact local-capacity classes
  - explicitly fall back from rectangle frontier DP to `bitset_mis_v1`, and from `bitset_mis_v1` to the legacy tiny CP-SAT oracle, with both fallbacks remaining exact-safe and explicitly counted
  - allow mixed exact rectangle variants inside the same compact signature class, including the current `manufacturing_6x4` `6x4 / 4x6` orientation mix
- The currently locked safety restrictions are:
  - rectangle frontier DP must only consume exact cached local occupied-shape truth; `(dx, dy, orientation)` alone is still not an admissible certified-exact key
  - if a compact signature contains any non-rectangular local shape, certified exact must explicitly fall back to the bitset oracle instead of approximating or silently widening the rectangle abstraction
  - if rectangle frontier DP cannot complete under its explicit exact-safe guardrails, the solver may only fall back to the existing exact bitset and CP-SAT oracles; no heuristic substitute is admissible
  - this round changes only certified-exact local-capacity oracle internals; it must not change exact feasible sets, cut admissibility, proof semantics, solution schema, or campaign schema
  - no new artifact file is introduced and no `campaign hash` compatibility rule changes
- The currently locked observability additions are:
  - `exact_precompute_profile` may expose `power_capacity_rect_dp_evaluations`, `power_capacity_rect_dp_cache_hits`, `power_capacity_rect_dp_cache_misses`, `power_capacity_bitset_fallbacks`, `power_capacity_cpsat_fallbacks`, and `power_capacity_oracle = rectangle_frontier_dp_v1`
  - exact global valid-inequality stats may expose `power_capacity_families.coefficient_source = exact_rect_dp_cache_v4`
  - exact global valid-inequality stats may continue exposing `power_capacity_families.shell_pair_count` and `power_capacity_families.compact_signature_class_count`
  - exact run metadata may expose the same new precompute/oracle summary fields through `run_benders_for_ghost_rect.last_run_metadata`

## 2026-03-19 Lock Addendum: Local-Capacity Oracle v5

- Scope: `certified_exact`
- This change extends the allowed exact-safe local-oracle line inside `src/models/master_model.py`, `src/models/exact_coordinate_master.py`, and `src/search/benders_loop.py`.
- The currently locked admissible steps are:
  - keep the certified-exact local-capacity truth source grounded in `(dx, dy, local_shape_token)` and exact cached local occupied shapes
  - replace the recursive rectangle frontier DP runtime with an iterative scanline frontier automaton while keeping the same exact rectangle abstraction and the same scan-axis selection rule
  - continue keeping the recursive rectangle solver only as a test/comparison helper, not as the default runtime oracle
  - continue falling back explicitly from the rectangle automaton to `bitset_mis_v1`, and from `bitset_mis_v1` to the legacy tiny CP-SAT oracle, with both fallbacks remaining exact-safe and explicitly counted
  - allow internal compile caching keyed by `(template, compact_signature, scan_axis)` so long as it remains process-memory only and does not change coefficient truth
- The currently locked safety restrictions are:
  - the iterative automaton must preserve the exact same feasible-set semantics as the previous rectangle frontier DP; no heuristic pruning, approximate corridor restriction, or silent downgrade is admissible
  - non-rectangular local shapes must still explicitly fall back to the existing exact bitset oracle, and any remaining oracle failure must still explicitly fall back to the existing exact CP-SAT model
  - this round changes only certified-exact local-capacity oracle internals; it must not change exact feasible sets, cut admissibility, proof semantics, solution schema, or campaign schema
  - no new artifact file is introduced and no `campaign hash` compatibility rule changes
- The currently locked observability additions are:
  - `exact_precompute_profile` may expose `power_capacity_oracle = rectangle_frontier_dp_v2`
  - `exact_precompute_profile` may expose `power_capacity_rect_dp_state_merges`, `power_capacity_rect_dp_peak_line_states`, `power_capacity_rect_dp_peak_pos_states`, and `power_capacity_rect_dp_compiled_signatures`
  - exact global valid-inequality stats may expose `power_capacity_families.coefficient_source = exact_rect_dp_cache_v5`
  - exact run metadata may expose the same new precompute/oracle summary fields through `run_benders_for_ghost_rect.last_run_metadata`

## 2026-03-19 Lock Addendum: Local-Capacity Oracle v6

- Scope: `certified_exact`
- This change extends the allowed exact-safe local-oracle line inside `src/models/master_model.py`, `src/models/exact_coordinate_master.py`, and `src/search/benders_loop.py`.
- The currently locked admissible steps are:
  - keep the certified-exact local-capacity truth source grounded in `(dx, dy, local_shape_token)` and exact cached local occupied shapes
  - keep rectangle frontier DP as the primary local-capacity oracle for compact signatures composed entirely of exact cached full-rectangle local shapes
  - replace the generic iterative rect-DP runtime with a packed scanline transition kernel that precompiles `(conflict_mask, future_write_mask, gain)` start options per `(template, compact_signature, scan_axis)`
  - continue allowing only explicit fallback from rectangle frontier DP to `bitset_mis_v1`, and from `bitset_mis_v1` to the legacy tiny CP-SAT oracle
  - continue keeping prior `rectangle_frontier_dp_v1` and `rectangle_frontier_dp_v2` implementations only as exact regression helpers, not as the default runtime oracle
- The currently locked safety restrictions are:
  - the packed transition kernel must preserve the exact same feasible-set semantics as the previous rectangle frontier implementations; no heuristic pruning, approximate corridor restriction, or silent downgrade is admissible
  - rectangle frontier DP must still consume exact cached occupied-shape truth; `(dx, dy, orientation)` or any other proxy remains inadmissible as a certified-exact truth source
  - non-rectangular local shapes must still explicitly fall back to the exact bitset oracle, and any remaining oracle failure must still explicitly fall back to the exact CP-SAT model
  - this round changes only certified-exact local-capacity oracle internals; it must not change exact feasible sets, cut admissibility, proof semantics, solution schema, or campaign schema
  - no new artifact file is introduced and no `campaign hash` compatibility rule changes
- The currently locked observability additions are:
  - `exact_precompute_profile` may expose `power_capacity_oracle = rectangle_frontier_dp_v3`
  - `exact_precompute_profile` may expose `power_capacity_rect_dp_compiled_start_options` and `power_capacity_rect_dp_deduped_start_options`, in addition to the existing rect-DP state and cache counters
  - exact global valid-inequality stats may expose `power_capacity_families.coefficient_source = exact_rect_dp_cache_v6`
  - exact run metadata may expose the same new precompute/oracle summary fields through `run_benders_for_ghost_rect.last_run_metadata`

## 2026-03-19 Lock Addendum: Local-Capacity Oracle v7 Finalization

- Scope: `certified_exact`
- This change finalizes the allowed exact-safe local-capacity runtime line inside `src/models/master_model.py`, `src/models/exact_coordinate_master.py`, and `src/search/benders_loop.py`.
- The currently locked admissible steps are:
  - keep `rectangle_frontier_dp_v4` as the primary local-capacity oracle name and the line-subset transfer implementation as the preferred runtime path
  - route into `rectangle_frontier_dp_v4` only when the compiled line-subset kernel stays within the explicit exact-safe guardrails `peak_line_subset_options <= 160` and `compiled_line_subsets <= 2000`
  - treat `rectangle_frontier_dp_v3` as the first explicit exact fallback under those guardrails, not as a silent downgrade and not as a heuristic substitute
  - continue keeping `bitset_mis_v1` as the next explicit exact fallback and the legacy tiny CP-SAT oracle as the final explicit exact fallback
  - keep the certified-exact truth source grounded in `(dx, dy, local_shape_token)` and exact cached local occupied shapes; no proxy key becomes admissible
- The currently locked safety restrictions are:
  - the guarded `v4 -> v3 -> bitset -> CP-SAT` stack must preserve the exact same feasible-set semantics as the prior certified-exact local-capacity pipeline; no approximation, heuristic pruning, or silent downgrade is admissible
  - `rectangle_frontier_dp_v3` remains an exact rect-DP oracle; using it as the explicit fallback does not loosen the certified-exact boundary
  - non-rectangular local shapes must still explicitly fall back to the exact bitset oracle, and any remaining oracle failure must still explicitly fall back to the exact CP-SAT model
  - this round changes only certified-exact local-capacity oracle internals; it must not change exact feasible sets, cut admissibility, proof semantics, solution schema, or campaign schema
  - no new artifact file is introduced and no `campaign hash` compatibility rule changes
- The currently locked observability additions are:
  - `exact_precompute_profile` may expose `power_capacity_oracle = rectangle_frontier_dp_v4`
  - `exact_precompute_profile` may expose `power_capacity_rect_dp_v3_fallbacks`, `power_capacity_rect_dp_compiled_line_subsets`, and `power_capacity_rect_dp_peak_line_subset_options`
  - exact global valid-inequality stats may expose `power_capacity_families.coefficient_source = exact_rect_dp_cache_v7`
  - exact run metadata may expose the same guarded-routing summary fields through `run_benders_for_ghost_rect.last_run_metadata`

## 2026-03-19 Lock Addendum: `manufacturing_6x4` Mixed CP-SAT Specialization

- Scope: `certified_exact`
- This change narrows one local-capacity hotspot inside `src/models/master_model.py`, `src/models/exact_coordinate_master.py`, and `src/search/benders_loop.py`.
- The currently locked admissible steps are:
  - keep `rectangle_frontier_dp_v4` as the advertised primary rect oracle name
  - when `v4` guardrails reject a compact signature and the template is `manufacturing_6x4` with mixed `6x4 / 4x6` rectangle variants, route explicitly into a template-specialized exact CP-SAT oracle before trying `rectangle_frontier_dp_v3`
  - keep that specialized CP-SAT route grounded in the existing certified-exact truth source `(dx, dy, local_shape_token)` and exact cached local occupied shapes
  - if the specialized CP-SAT path fails to prove optimality, count it explicitly and fall back explicitly to `rectangle_frontier_dp_v3`; no silent downgrade is admissible
  - keep `bitset_mis_v1` and the legacy tiny CP-SAT model as downstream exact fallbacks for non-rectangular or otherwise unsupported local signatures
- The currently locked safety restrictions are:
  - this specialization does not introduce a new feasible-set relaxation, proof shortcut, or schema change; it only reorders exact local-capacity kernels for a narrow template family
  - non-rectangular local shapes must still explicitly fall back to the exact bitset oracle, and any remaining oracle failure must still explicitly fall back to the legacy exact CP-SAT model
  - no new artifact file is introduced and no `campaign hash` compatibility rule changes
- The currently locked observability additions are:
  - `exact_precompute_profile` may expose `power_capacity_m6x4_mixed_cpsat_evaluations`
  - `exact_precompute_profile` may expose `power_capacity_m6x4_mixed_cpsat_cache_hits`
  - `exact_precompute_profile` may expose `power_capacity_m6x4_mixed_cpsat_selected_cases`
  - `exact_precompute_profile` may expose `power_capacity_m6x4_mixed_cpsat_v3_fallbacks`
  - exact run metadata may expose the same specialized-routing counters through `run_benders_for_ghost_rect.last_run_metadata`

## 2026-03-19 Lock Addendum: Protocol Storage Box Lower-Bound Correction

- Scope: `certified_exact`
- This change corrects one optional-cardinality assumption inside `src/models/master_model.py`, `src/models/exact_coordinate_master.py`, and `src/search/benders_loop.py`.
- The currently locked admissible steps are:
  - treat the `protocol_storage_box` count inferred from `required_generic_inputs` as a certified-exact lower bound only
  - keep that lower bound available to exact static occupied-area lower bounds, diagnostics, and powered-demand lower bounds
  - keep `protocol_storage_box` in the residual optional layer unless an independent proof upgrades it to an exact count
  - normalize `solve_mode` / `solve_modes` metadata conservatively inside certification blocker checks
- The currently locked safety restrictions are:
  - the inferred generic-input protocol-box count must not be enforced as an exact equality unless sufficiency is formally proven in the full certified-exact geometry / routing model
  - missing, malformed, or unknown solve-mode metadata must conservatively block certified exact rather than silently pass contamination
  - `solve_modes` containing `certified_exact` remain admissible even when `exploratory` is also listed
  - this correction must not change solution schema, cut schema, campaign schema, or `campaign hash` compatibility rules
- The currently locked observability additions are:
  - master build stats may expose `exact_optional_lower_bounds`
  - exact global valid-inequality stats may expose `lower_bound_optional_powered_demands`
  - protocol-box cardinality diagnostics may expose `mode = required_lower_bound` rather than `fixed_exact_count`
