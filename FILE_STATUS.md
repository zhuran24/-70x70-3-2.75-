# FILE_STATUS.md

**Status**: ACCEPTED_DRAFT  
**Updated**: 2026-03-18  
**Purpose**: 用“future runtime role（未来运行角色）”而不是“改过 / 没改过”来说明这个仓库里哪些文件以后还会进入 `certified_exact`（严格认证精确）主路径，哪些只在 `exploratory`（探索）或开发维护里使用，哪些只是归档材料，求解器以后根本不会读取。

---

## 1. 先看最重要的结论

这份文件最重要的读法不是：

- 这个文件新不新
- 这个文件改没改

而是：

- 这个文件以后还会不会被 `certified_exact`（严格认证精确）主路径直接读取
- 这个文件是不是只在“重建预处理工件”时才会用到
- 这个文件是不是只给 `exploratory`（探索）模式用
- 这个文件是不是只给测试、展示、文档或归档使用

**当前总判断**：

1. 仓库已经完成了 `certified_exact`（严格认证精确）与 `exploratory`（探索）两条路径的基本分离。  
2. 以后真正的严格精确主线，不应再读取 `provisional`（临时经验上限）工件、legacy `cuts`（历史遗留切平面）和粗粒度 `flow`（流量近似诊断器）结论。  
3. 仓库里仍然保留了大量历史日志、历史背景材料和兼容工件；**这些文件存在于仓库中，不等于以后运行求解器还会读取它们**。  
4. 尤其是 `diag_log.txt`、`temp_outer_exact_one.log`、`temp_*.log`、`logs/*` 这些文件，应明确视为 `ARCHIVE_ONLY`（仅归档），**不能再拿它们当“当前版本性能现状”**。  

---

## 2. 这份文件里的两个标签系统

### 2.1 `status`（状态）标签

- `FROZEN`：当前轮次内可作为稳定依赖使用。  
- `ACCEPTED_DRAFT`：语义已经明确，但后续仍可能继续补测试、补说明或小修。  
- `EXPLORATORY_ONLY`：只允许探索路径使用，严格精确主路径不得拿它当正式证明。  
- `EXACT_DIAGNOSTIC_ONLY`：严格精确路径可调用，但只能做诊断、提示或日志，不可单独形成正式剪枝或认证结论。  
- `DEV_TEST_ONLY`：仅开发、测试、文档、打包、展示使用，不属于最终求解主线。  
- `ARCHIVE_ONLY`：仅归档或历史留痕，求解器以后不会主动读取。  

### 2.2 `runtime_role`（运行角色）标签

- `CERTIFIED_EXACT_ACTIVE`：严格精确主线以后仍会直接读取。  
- `PREPROCESS_ONLY`：只在“从规则重新生成工件”时会用到，最终求解通常不会直接读取。  
- `EXPLORATORY_ONLY`：只给探索模式、兼容模式或实验流程使用。  
- `EXACT_DIAGNOSTIC_ONLY`：严格精确路径可调用，但只能做诊断，不得单独形成正式剪枝。  
- `DEV_TEST_ONLY`：只给测试、开发、说明、依赖管理使用。  
- `POSTPROCESS_ONLY`：只给展示、导出、可视化或后处理使用。  
- `ARCHIVE_ONLY`：只是历史记录或背景材料，求解器运行不会读取。  
- `REPO_METADATA_ONLY`：仓库元数据或缓存，不属于求解器内容。  

---

## 3. 当前已对齐的项目真值

以下内容是当前仓库里已经对齐、且后文会用到的事实：

- 候选位姿总数：`81,795`  
- 强制精确实例数：`266`  
- 探索兼容实例总数：`326`  
- 制造单位总数：`219`  
- 探索模式经验上限：  
  - `power_pole`（供电桩）=`50`  
  - `protocol_storage_box`（协议储存箱）=`10`  
- 严格安全的静态占地下界：`3544`  
- 严格精确路径当前直接依赖的预处理工件：  
  - `candidate_placements.json`（候选位姿全集）  
  - `mandatory_exact_instances.json`（严格精确必选实例工件）  
  - `generic_io_requirements.json`（通用输入输出需求工件）  
- `certified_exact`（严格认证精确）默认战役预算：`168` 小时  
- legacy `cuts`（历史遗留切平面）只能视为 `exploratory`（探索）遗留件，不得直接进入严格精确主路径。  

---

## 4. 以后仍会进入 `certified_exact`（严格认证精确）主路径的文件

这些文件以后仍然会被严格精确求解器**直接读取或直接调用**。

| 路径 | status | runtime_role | 未来是否被严格精确主线直接读取 | 说明 |
|---|---|---|---|---|
| `main.py` | ACCEPTED_DRAFT | `CERTIFIED_EXACT_ACTIVE` | 是 | CLI（命令行入口），默认 `--mode certified_exact` |
| `src/search/outer_search.py` | ACCEPTED_DRAFT | `CERTIFIED_EXACT_ACTIVE` | 是 | 外层最大空地搜索，严格精确模式只用安全静态占地下界 |
| `src/search/benders_loop.py` | ACCEPTED_DRAFT | `CERTIFIED_EXACT_ACTIVE` | 是 | 单尺寸 `Benders`（逻辑分解）封装，负责 blocker（阻塞检查）、artifact hash（工件哈希）、cut（切平面）加载边界 |
| `src/search/exact_campaign.py` | ACCEPTED_DRAFT | `CERTIFIED_EXACT_ACTIVE` | 是 | `campaign state`（持续战役状态）持久化与恢复 |
| `src/models/master_model.py` | ACCEPTED_DRAFT | `CERTIFIED_EXACT_ACTIVE` | 是 | 主摆放模型；严格精确模式下不再把 50/10 经验上限写成正式约束，并已支持保守版 exact-safe greedy warm start |
| `src/models/binding_subproblem.py` | ACCEPTED_DRAFT | `CERTIFIED_EXACT_ACTIVE` | 是 | 精确绑定子问题；从 `generic_io_requirements.json` 读取通用 I/O 需求 |
| `src/models/cut_manager.py` | ACCEPTED_DRAFT | `CERTIFIED_EXACT_ACTIVE` | 是 | `cut`（切平面）来源追踪、哈希校验和 `LBBD`（逻辑分解）控制 |
| `src/models/port_binding.py` | ACCEPTED_DRAFT | `CERTIFIED_EXACT_ACTIVE` | 是 | 端口级绑定骨架，供精确绑定 / 路由联动使用 |
| `src/models/routing_subproblem.py` | ACCEPTED_DRAFT | `CERTIFIED_EXACT_ACTIVE` | 是 | 精确离散路由子问题 |
| `src/preprocess/operation_profiles.py` | FROZEN | `CERTIFIED_EXACT_ACTIVE` | 是 | 运行时仍会读它提供的操作端口画像 |
| `rules/canonical_rules.json` | FROZEN | `CERTIFIED_EXACT_ACTIVE` | 是 | 规则真源文件 |
| `data/preprocessed/candidate_placements.json` | FROZEN | `CERTIFIED_EXACT_ACTIVE` | 是 | 候选位姿全集，严格精确主线核心输入 |
| `data/preprocessed/mandatory_exact_instances.json` | FROZEN | `CERTIFIED_EXACT_ACTIVE` | 是 | 严格精确只读这份必选实例工件 |
| `data/preprocessed/generic_io_requirements.json` | FROZEN | `CERTIFIED_EXACT_ACTIVE` | 是 | 绑定子问题当前正式输入之一 |

### 这一类文件怎么理解

如果以后你要真正跑“严格精确主线”，优先看的就是这一类。  
它们不是“可能会用”，而是**正常情况下就会用**。

---

## 5. 以后不会直接进入最终求解，但在“重建工件”时还会用到的文件

这些文件通常不会被最终严格精确求解器直接读取；但只要你想从规则重新生成输入工件，它们仍然必不可少。

| 路径 | status | runtime_role | 未来是否被严格精确主线直接读取 | 说明 |
|---|---|---|---|---|
| `src/preprocess/demand_solver.py` | FROZEN | `PREPROCESS_ONLY` | 否 | 生成 `commodity_demands.json`、`machine_counts.json`、`port_budget.json`、`generic_io_requirements.json` |
| `src/preprocess/instance_builder.py` | FROZEN | `PREPROCESS_ONLY` | 否 | 生成 `mandatory_exact_instances.json`、`exploratory_optional_caps.json`、`all_facility_instances.json` |
| `src/placement/placement_generator.py` | ACCEPTED_DRAFT | `PREPROCESS_ONLY` | 否 | 生成 `candidate_placements.json` |
| `src/placement/occupancy_masks.py` | ACCEPTED_DRAFT | `PREPROCESS_ONLY` | 否 | 位姿占用索引与辅助结构；当前更多服务于重建 / 校验 / 后续加速 |
| `src/placement/symmetry_breaking.py` | ACCEPTED_DRAFT | `PREPROCESS_ONLY` | 否 | 几何去重与验证辅助；运行时对称性约束主要已内置到主模型 |
| `data/preprocessed/commodity_demands.json` | FROZEN | `PREPROCESS_ONLY` | 否 | 需求展开结果；更多用于审计、回归与重建 |
| `data/preprocessed/machine_counts.json` | FROZEN | `PREPROCESS_ONLY` | 否 | 机器数量展开结果；更多用于审计、回归与重建 |
| `data/preprocessed/port_budget.json` | FROZEN | `PREPROCESS_ONLY` | 否 | 端口预算工件；更多用于审计、回归与重建 |

### 这一类文件怎么理解

它们不是废文件。  
只是平时直接跑最终求解时，你通常不会重新碰它们；只有在“从源头再生成一遍工件”时才会再次进入流程。

---

## 6. 以后严格精确主线不会再用，但探索或兼容流程还会用到的文件

这是最容易让人误解的一类。  
它们仍然存在于仓库里，也可能仍然被某些流程读取；但**严格精确主线以后不该再直接使用它们**。

| 路径 | status | runtime_role | 未来是否被严格精确主线直接读取 | 说明 |
|---|---|---|---|---|
| `data/preprocessed/exploratory_optional_caps.json` | FROZEN | `EXPLORATORY_ONLY` | 否 | 只给探索模式提供 `provisional`（临时经验上限） |
| `data/preprocessed/all_facility_instances.json` | ACCEPTED_DRAFT | `EXPLORATORY_ONLY` | 否 | 兼容旧流程 / 探索流程的“全实例工件”；严格精确主线不应再依赖它 |
| `data/solutions/cuts_*.json` | `EXPLORATORY_ONLY` | `EXPLORATORY_ONLY` | 否 | 历史切平面存档，只能用于探索或人工参考 |
| `src/models/flow_subproblem.py` | `EXACT_DIAGNOSTIC_ONLY` | `EXACT_DIAGNOSTIC_ONLY` | 否（可被调用但不能正式剪枝） | 粗粒度流量诊断器；严格精确路径不得拿它形成正式不可行证明 |

### 这一类文件怎么理解

这一类文件不是“以后完全没用”。  
但它们的用途必须被限制成：

- 只给 `exploratory`（探索）模式用  
- 只给兼容旧实验流程用  
- 只给诊断或日志用  

**绝不能再把它们偷偷混回 `certified_exact`（严格认证精确）主路径。**

---

## 7. 以后求解器不会直接读取，但开发、测试、文档和展示仍会用到的文件

这些文件不属于最终求解主线，但对项目维护仍然重要。

### 7.1 测试与验证

| 路径 | status | runtime_role | 未来是否被严格精确主线直接读取 | 说明 |
|---|---|---|---|---|
| `src/tests/test_master.py` | ACCEPTED_DRAFT | `DEV_TEST_ONLY` | 否 | 主模型契约与模式边界测试 |
| `src/tests/test_regression.py` | ACCEPTED_DRAFT | `DEV_TEST_ONLY` | 否 | 数据工件回归测试 |
| `src/tests/test_exact_contract.py` | ACCEPTED_DRAFT | `DEV_TEST_ONLY` | 否 | 严格精确契约测试 |
| `src/tests/test_cut_provenance.py` | ACCEPTED_DRAFT | `DEV_TEST_ONLY` | 否 | `cut`（切平面）来源追踪测试 |
| `src/tests/test_binding.py` | ACCEPTED_DRAFT | `DEV_TEST_ONLY` | 否 | 绑定子问题测试 |
| `src/tests/test_routing.py` | ACCEPTED_DRAFT | `DEV_TEST_ONLY` | 否 | 路由子问题测试 |
| `src/tests/test_flow.py` | ACCEPTED_DRAFT | `DEV_TEST_ONLY` | 否 | 流量诊断器测试 |
| `src/tests/test_placements.py` | ACCEPTED_DRAFT | `DEV_TEST_ONLY` | 否 | 候选位姿与几何生成测试 |
| `src/tests/test_demand.py` | ACCEPTED_DRAFT | `DEV_TEST_ONLY` | 否 | 预处理需求展开测试 |
| `src/tests/test_operation_profiles.py` | ACCEPTED_DRAFT | `DEV_TEST_ONLY` | 否 | 端口画像测试 |
| `src/tests/test_rules.py` | ACCEPTED_DRAFT | `DEV_TEST_ONLY` | 否 | 规则 JSON、Schema（模式）与语义验证测试 |
| `src/tests/conftest.py` | ACCEPTED_DRAFT | `DEV_TEST_ONLY` | 否 | 测试公共夹具 |

### 7.2 文档与规则验证辅助

| 路径 | status | runtime_role | 未来是否被严格精确主线直接读取 | 说明 |
|---|---|---|---|---|
| `FILE_STATUS.md` | ACCEPTED_DRAFT | `DEV_TEST_ONLY` | 否 | 当前文件，负责解释未来运行角色 |
| `PROJECT_LOCK.md` | ACCEPTED_DRAFT | `DEV_TEST_ONLY` | 否 | 项目红线、边界与禁止事项 |
| `specs/*` | ACCEPTED_DRAFT | `DEV_TEST_ONLY` | 否 | 规格文档，主要用于对齐语义和交接 |
| `rules/canonical_rules.schema.json` | ACCEPTED_DRAFT | `DEV_TEST_ONLY` | 否 | 规则 Schema（结构模式）校验文件，主要给测试 / 校验工具用 |
| `src/rules/models.py` | ACCEPTED_DRAFT | `DEV_TEST_ONLY` | 否 | 规则 Pydantic（数据模型）定义 |
| `src/rules/semantic_validator.py` | ACCEPTED_DRAFT | `DEV_TEST_ONLY` | 否 | 规则跨字段语义校验 |

### 7.3 展示、导出与后处理

| 路径 | status | runtime_role | 未来是否被严格精确主线直接读取 | 说明 |
|---|---|---|---|---|
| `src/render/*` | ACCEPTED_DRAFT | `POSTPROCESS_ONLY` | 否 | 图像、ASCII（字符画）、网页可视化、动画、蓝图导出等 |
| `src/io/output_schema.py` | ACCEPTED_DRAFT | `POSTPROCESS_ONLY` | 否 | 输出结构定义，不属于严格精确核心求解 |
| `src/io/serializer.py` | ACCEPTED_DRAFT | `POSTPROCESS_ONLY` | 否 | 结果序列化工具，不属于严格精确核心求解 |

### 7.4 依赖与打包文件

| 路径 | status | runtime_role | 未来是否被严格精确主线直接读取 | 说明 |
|---|---|---|---|---|
| `requirements.txt` | ACCEPTED_DRAFT | `DEV_TEST_ONLY` | 否 | 依赖说明 |
| `requirements.lock.txt` | ACCEPTED_DRAFT | `DEV_TEST_ONLY` | 否 | 锁定版本说明 |
| `vendor/wheels/*` | ACCEPTED_DRAFT | `DEV_TEST_ONLY` | 否 | 离线依赖包；本轮 exact（严格精确）验收不以其是否完整为中心 |

---

## 8. 以后求解器根本不会读取，只是归档或历史留痕的文件

这一类是你最关心的“以后完全不会进入求解器”的文件。  
它们留在仓库中，是为了保留历史、背景、调试记录或临时脚本；**不是为了未来运行时继续读取**。

### 8.1 历史日志

| 路径 | status | runtime_role | 未来是否被严格精确主线直接读取 | 说明 |
|---|---|---|---|---|
| `diag_log.txt` | `ARCHIVE_ONLY` | `ARCHIVE_ONLY` | 否 | 历史诊断日志；不能当当前版本性能现状 |
| `temp_outer_exact_one.log` | `ARCHIVE_ONLY` | `ARCHIVE_ONLY` | 否 | 历史外层求解日志；不能当当前版本性能现状 |
| `temp_*.log` | `ARCHIVE_ONLY` | `ARCHIVE_ONLY` | 否 | 历史实验 / 对比 / 调参日志；仅归档 |

### 8.2 初始背景材料与历史讨论记录

| 路径 | status | runtime_role | 未来是否被严格精确主线直接读取 | 说明 |
|---|---|---|---|---|
| `logs/ChatGPT5.4 Pro-0.md` | `ARCHIVE_ONLY` | `ARCHIVE_ONLY` | 否 | 初始背景材料 |
| `logs/ChatGPT5.4 Pro-2.md` | `ARCHIVE_ONLY` | `ARCHIVE_ONLY` | 否 | 初始背景材料 |
| `logs/Gemini 3.1 pro-4.md` | `ARCHIVE_ONLY` | `ARCHIVE_ONLY` | 否 | 初始背景材料 |
| `logs/Gemini deep think-1.md` | `ARCHIVE_ONLY` | `ARCHIVE_ONLY` | 否 | 初始背景材料 |
| `logs/Gemini deep think-3.md` | `ARCHIVE_ONLY` | `ARCHIVE_ONLY` | 否 | 初始背景材料 |
| `logs/image.png` | `ARCHIVE_ONLY` | `ARCHIVE_ONLY` | 否 | 背景示意图 |
| `logs/image copy.png` | `ARCHIVE_ONLY` | `ARCHIVE_ONLY` | 否 | 背景示意图；不能被当成固定宏模块蓝图 |

### 8.3 临时脚本与仓库元数据

| 路径 | status | runtime_role | 未来是否被严格精确主线直接读取 | 说明 |
|---|---|---|---|---|
| `temp_scripts/*` | `ARCHIVE_ONLY` | `ARCHIVE_ONLY` | 否 | 临时诊断脚本，不属于正式主线 |
| `.git/*` | `ARCHIVE_ONLY` | `REPO_METADATA_ONLY` | 否 | Git（版本控制）元数据 |
| `.pytest_cache/*` | `ARCHIVE_ONLY` | `REPO_METADATA_ONLY` | 否 | 测试缓存 |

### 这一类文件怎么理解

这些文件以后对“运行求解器求严格精确解”来说，**完全不会被程序主动读取**。  
它们最多只是：

- 回顾历史  
- 对照旧实验  
- 看背景来源  
- 辅助人工排查  

**尤其是历史日志，不应再被当成当前版本性能结论。**

---

## 9. 一眼判断：哪些文件以后最不该再被混进严格精确主线

以下文件或模式，今后最需要被反复提醒“不要混回 `certified_exact`（严格认证精确）主路径”：

1. `data/preprocessed/exploratory_optional_caps.json`  
2. `data/preprocessed/all_facility_instances.json`  
3. `data/solutions/cuts_*.json`  
4. `src/models/flow_subproblem.py` 的诊断结论  
5. `diag_log.txt`、`temp_outer_exact_one.log`、`temp_*.log` 中的历史性能数字  
6. `logs/*` 里的方案背景与示意图  

这些东西不是“以后完全没用”，但它们都**不是严格精确主线的正式输入证据**。

---

## 10. 当前不允许的误读

以下说法在当前仓库中都不成立：

- “仓库里存在的文件，以后运行求解器都会读到。”  
- “历史日志里的性能数据可以直接代表当前重构后版本。”  
- “`all_facility_instances.json` 仍然是严格精确主线的正式实例输入。”  
- “历史 `cuts`（切平面）文件依然可以直接拿来做严格精确证明。”  
- “`flow_subproblem.py` 的粗粒度近似结论可以直接当严格精确剪枝。”  
- “背景图和历史讨论材料会被求解器当规则真源读取。”  

---

## 11. 当前最建议的仓库阅读顺序

如果你以后只想关心“最终严格精确主线到底还靠哪些文件”，建议按这个顺序看：

1. `main.py`  
2. `src/search/outer_search.py`  
3. `src/search/benders_loop.py`  
4. `src/search/exact_campaign.py`  
5. `src/models/master_model.py`  
6. `src/models/binding_subproblem.py`  
7. `src/models/cut_manager.py`  
8. `src/models/port_binding.py`  
9. `src/models/routing_subproblem.py`  
10. `rules/canonical_rules.json`  
11. `data/preprocessed/candidate_placements.json`  
12. `data/preprocessed/mandatory_exact_instances.json`  
13. `data/preprocessed/generic_io_requirements.json`  

如果你只想关心“哪些东西以后完全不要再拿来判断当前求解器”，优先避开：

1. `diag_log.txt`  
2. `temp_outer_exact_one.log`  
3. `temp_*.log`  
4. `logs/*`  
5. `data/solutions/cuts_*.json`  
6. `data/preprocessed/exploratory_optional_caps.json`  
7. `data/preprocessed/all_facility_instances.json`  

---

## 12. 这份文件未来还要怎么继续维护

后续如果再改仓库，优先更新的不是“谁改了谁没改”，而是下面这 3 件事：

1. 某个文件的 `runtime_role`（运行角色）有没有变化。  
2. 某个文件是否开始进入或退出 `certified_exact`（严格认证精确）主路径。  
3. 某个历史文件是否已明确降级成 `ARCHIVE_ONLY`（仅归档）。  

也就是说，`FILE_STATUS.md` 以后最重要的使命不是记“开发历史”，而是记：

**“这个文件未来在求解器生态里到底扮演什么角色。”**
---

## 2026-03-16 Exact Lower Bound Update

- Scope: `certified_exact`
- Affected runtime role: `src/models/master_model.py` remains `CERTIFIED_EXACT_ACTIVE`
- New exact-safe behavior: master now injects template-level local power-capacity lower bounds for powered mandatory exact templates.
- Safety boundary: this is not the forbidden `power-pole area lower bound`; coefficients come from exact local non-overlap micro-models and stay in process memory only.
- Ghost handling: the bound is ghost-aware only through existing pole feasibility and occupancy constraints; there is no explicit `u_var`-conditioned coefficient table.
- Artifacts: no new artifact files
- Campaign compatibility: no `campaign hash` rule change

## 2026-03-16 Exact Search Reuse And Frontier Update

- Scope: `certified_exact`
- Affected runtime roles:
  - `src/models/master_model.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/search/benders_loop.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/search/outer_search.py` remains `CERTIFIED_EXACT_ACTIVE`
- New exact-safe behavior:
  - master now supports a candidate-independent `ExactMasterCore` plus per-candidate ghost overlay cloning
  - exact outer search now runs on an explicit-domain `2D antichain frontier` instead of linear full sweep
  - exact resume reconstructs frontier from persisted candidate terminal states instead of persisting derived prune state
- Safety boundary:
  - no exploratory heuristic is promoted into the certified evidence chain
  - whole-layout exact-safe cuts remain candidate-local and are replayed only into the current overlay
  - `UNKNOWN` / `UNPROVEN` candidates do not generate monotone closure
- Artifacts: no new artifact files and no new cut/campaign protocol files
- Campaign compatibility: no `campaign hash` rule change and no new campaign schema fields for frontier state

## 2026-03-16 Certification-First Frontier Scheduling Update

- Scope: `certified_exact`
- Affected runtime role: `src/search/outer_search.py` remains `CERTIFIED_EXACT_ACTIVE`
- New exact-safe behavior:
  - exact frontier selection now uses runtime-only `certification_prune_per_anchor_v1`
  - each frontier candidate is scored by exact, deterministic metrics derived from the explicit candidate domain:
    - `certification_prune_gain`
    - `infeasible_prune_gain`
    - `anchor_count`
    - exact rational `selection_score = certification_prune_gain / anchor_count`
  - partial runs now explicitly follow `Prune-First` semantics instead of objective-prefix semantics
- Safety boundary:
  - this changes scheduling only and does not change master/binding/routing proof semantics
  - `UNKNOWN` / `UNPROVEN` still do not create monotone closure
  - frontier scores and derived prune state remain runtime-only and are recomputed on resume from persisted explicit candidate records
- Artifacts: no new artifact files
- Campaign compatibility: no `campaign hash` rule change and no campaign schema change

## 2026-03-18 Addendum: `coordinate_exact_v3` residual `power_pole` family guidance
- Scope: `certified_exact`
- Runtime effect:
  - residual `power_pole` slots now branch through `power_pole_family_count_vars` before slot-level `active -> family -> x -> y`
  - active residual pole slots now keep a stable exact-safe order: active prefix, then nondecreasing `family`, then nondecreasing `order_key` inside one family
  - master search guidance now reports `profile = exact_coordinate_guided_branching_v4`
- Observability:
  - `search_guidance` now exposes `power_pole_family_order`
  - `search_guidance` now exposes `power_pole_family_count_literals`
  - `search_guidance` now exposes `residual_optional_family_guided`
  - exact run metadata now forwards the same residual-family guidance fields
- Exactness boundary:
  - no cut schema change, no solution schema change, no campaign schema change
  - sparse toy coordinate domains may use exact allowed-assignment fallback rows when mode-rect compression is not exact, but full-project certified artifacts remain on the compressed path

## 2026-03-16 Exact Subproblem Cut Ladder Update

- Scope: `certified_exact`
- Affected runtime roles:
  - `src/search/benders_loop.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/models/binding_subproblem.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/models/routing_subproblem.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/models/cut_manager.py` remains `CERTIFIED_EXACT_ACTIVE`
- New exact-safe behavior:
  - exact loop now supports fine-grained exact-safe subproblem cuts before escalating to whole-layout no-goods
  - binding now exposes structured `empty_binding_domain_instances` diagnostics instead of crashing on zero legal pose-level binding domain
  - routing now runs an exact-safe precheck layer with `front_blocked` and `relaxed_disconnected`
- Admissible new persisted cut types:
  - `binding_pose_domain_empty_nogood`
  - `routing_front_blocked_nogood`
- Safety boundary:
  - `binding_pose_domain_empty_nogood` is singleton placement-local and only records the offending placed instance pose
  - `routing_front_blocked_nogood` is placement-local and only records the blocked-port placement together with the blocking placement
  - `relaxed_disconnected` is currently a binding-selection rejection only; it is not persisted as a master cut in this round
  - whole-layout exact-safe cuts remain restricted to binding-wide infeasibility or routing exhaustion
- Artifacts: no new artifact files and no new cut protocol file
- Campaign compatibility: no `campaign hash` rule change and no campaign schema change

## 2026-03-16 Exact Routing Core Shrink Update

- Scope: `certified_exact`
- Affected runtime roles:
  - `src/models/routing_subproblem.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/search/benders_loop.py` remains `CERTIFIED_EXACT_ACTIVE`
- New exact-safe behavior:
  - routing precheck and routing CP-SAT build now share one exact domain analysis
  - each commodity is restricted to the connected free-cell component containing its front terminals
  - a terminal-aware dead-end peeling pass removes non-terminal leaf branches before state creation
  - routing variables are now created only on commodity-scoped active cells and only for locally supported direction patterns
- Safety boundary:
  - no bounding box, Manhattan corridor, A*, or shortest-path heuristic is introduced
  - no exploratory information enters `certified_exact`
  - this changes routing engineering only and does not change exact cut admissibility or campaign schema
- Observability:
  - exact proof summaries now expose `routing_domain_cells`
  - exact proof summaries now expose `routing_terminal_core_cells`
  - exact proof summaries now expose `routing_state_space_vars`
  - exact proof summaries now expose `routing_local_pattern_pruned_states`
- Artifacts: no new artifact files
- Campaign compatibility: no `campaign hash` rule change and no campaign schema change

## 2026-03-17 Placement-Fixed Exact Subproblem Reuse Update

- Scope: `certified_exact`
- Affected runtime roles:
  - `src/models/port_binding.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/models/binding_subproblem.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/models/routing_subproblem.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/search/benders_loop.py` remains `CERTIFIED_EXACT_ACTIVE`
- New exact-safe behavior:
  - pose-level exact binding domains now use a process-memory memo keyed by operation type plus normalized port geometry
  - exact binding summaries now expose `binding_domain_cache_hits`, `binding_domain_cache_misses`, and `binding_domain_reused_instances`
  - routing now supports a placement-fixed reusable core built once from `occupied_cells` and `occupied_owner_by_cell`
  - exact routing precheck and routing CP-SAT overlay may reuse that placement-fixed core across multiple binding selections under the same master placement
- Safety boundary:
  - all reuse is in-memory only and does not write a new artifact
  - reuse changes engineering only and does not change exact evidence admissibility
  - generic-slot operations still stay in the higher-level binding model and are not memoized as pose-level exact domains
- Observability:
  - exact proof summaries now expose `used_routing_core_reuse`
  - exact proof summaries now expose `routing_core_build_seconds`
  - exact proof summaries now expose `routing_overlay_build_seconds`
- Artifacts: no new artifact files
- Campaign compatibility: no `campaign hash` rule change and no campaign schema change

## 2026-03-17 Exact Search Guidance Update

- Scope: `certified_exact`
- Affected runtime roles:
  - `src/models/master_model.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/models/binding_subproblem.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/search/benders_loop.py` remains `CERTIFIED_EXACT_ACTIVE`
- New exact-safe behavior:
  - exact master now installs deterministic decision strategies over mandatory grouped poses, ghost-anchor choices, and pose-level optional facilities
  - exact binding now installs deterministic decision strategies over binding-choice literals and generic slot assignment literals
  - exact master solve now runs with an exact-guided CP-SAT profile that intentionally cooperates with greedy warm starts instead of relying on default automatic branching alone
- Safety boundary:
  - this is search guidance only and does not change the feasible set or exact evidence admissibility
  - no exploratory heuristic or historical artifact enters `certified_exact`
- Observability:
  - master build stats now expose `search_guidance`
  - master last-solve stats now expose `search_profile`
  - exact binding summaries now expose `search_guidance`, `search_profile`, and `search_branching`
  - exact run metadata may expose `master_search_profile` and `binding_search_profile`
- Artifacts: no new artifact files
- Campaign compatibility: no `campaign hash` rule change and no campaign schema change

## 2026-03-17 Exact Optional Cardinality Bounds Update

- Scope: `certified_exact`
- Affected runtime roles:
  - `src/models/master_model.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `data/preprocessed/generic_io_requirements.json` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/search/benders_loop.py` remains `CERTIFIED_EXACT_ACTIVE`
- New exact-safe behavior:
  - exact master may derive a certified-exact lower bound for `protocol_storage_box` directly from `required_generic_inputs` and the wireless-sink slot capacity per box
  - exact master may forbid selecting more `power_pole` poses than the number of selected powered non-pole facilities
  - these bounds replace a slice of the old exploratory caps with artifact-backed exact-safe cardinality logic
- Safety boundary:
  - these are completeness-preserving exact bounds, not exploratory heuristics
  - they do not reintroduce the forbidden exploratory `50 / 10` caps into certified exact mode
  - they do not add a new artifact file or change cut admissibility
- Observability:
  - master global-valid-inequality stats now expose `optional_cardinality_bounds`
- Artifacts: no new artifact files
- Campaign compatibility: no `campaign hash` rule change and no campaign schema change

## 2026-03-17 Certified Optional Lower-Bound Propagation Update

- Scope: `certified_exact`
- Affected runtime roles:
  - `src/models/master_model.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/search/benders_loop.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/search/outer_search.py` remains `CERTIFIED_EXACT_ACTIVE`
- New exact-safe behavior:
  - artifact-backed optional lower bounds are now propagated explicitly into certified-exact diagnostics and lower-bound computations
  - `protocol_storage_box = 1` is now treated as a certified-exact lower bound, not an exact-required optional count
  - the exact static occupied-area lower bound may add that minimum protocol-box area on top of mandatory exact area
  - exact local power-capacity lower bounds may include that minimum powered protocol-box demand without claiming sufficiency
- Safety boundary:
  - this does not rewrite pose-level optionals into mandatory instances and does not change solution ids, cut keys, or campaign schema
  - only independently proven exact fixed counts may enter `exact_required_optionals`; exploratory caps and historical heuristics remain forbidden
- Observability:
  - master build stats now expose `exact_required_optionals` for truly exact counts and `exact_optional_lower_bounds` for lower-bound-only propagation
  - master `search_guidance` now separates `required_optional_literals` from `residual_optional_literals`
  - global valid-inequality stats now expose `fixed_required_optional_demands` for exact counts only and `lower_bound_optional_powered_demands` for lower-bound-only propagation
- Artifacts: no new artifact files
- Campaign compatibility: no `campaign hash` rule change and no campaign schema change

## 2026-03-17 Signature-Count Guided Exact Master Prune

- Scope: `certified_exact`
- Affected runtime roles:
  - `src/models/master_model.py` remains `CERTIFIED_EXACT_ACTIVE`
- New exact-safe behavior:
  - grouped encoding still handles clone permutations, but exact master now adds a second decision layer over group-local pose signature counts before raw pose literals
  - exact-required pose optionals now receive the same signature-count guidance layer before raw required optional literals
  - exact local power-capacity lower bounds are now expressed through `power_pole` coefficient families instead of repeating one term per pole pose when coefficients are identical
- Safety boundary:
  - local pose signatures are built only from candidate-independent normalized occupied/front/power-coverage geometry
  - raw pose literals, solution ids, cut conflict-set keys, and campaign schema remain unchanged
  - this update changes propagation and branching only; it does not widen or narrow the exact feasible set
- Observability:
  - master build stats now expose `signature_buckets`
  - master `search_guidance` now exposes `mandatory_signature_counts` and `required_optional_signature_counts`
  - global valid-inequality stats now expose `power_capacity_families` and `aggregated_power_capacity_terms`
- Artifacts: no new artifact files
- Campaign compatibility: no `campaign hash` rule change and no campaign schema change

## 2026-03-17 Coordinate-Encoded Exact Master

- Scope: `certified_exact`
- Affected runtime roles:
  - `src/models/master_model.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/models/exact_coordinate_master.py` is now `CERTIFIED_EXACT_ACTIVE`
  - `src/search/benders_loop.py` remains `CERTIFIED_EXACT_ACTIVE`
- New exact-safe behavior:
  - certified exact master no longer uses grouped mandatory raw pose booleans as its primary representation
  - mandatory exact groups are now solved through coordinate slots with deterministic `(x, y, mode)` domains and direct lex ordering on `(x, y, mode)` rather than a table-driven rank
  - exact-required pose optionals reuse the same coordinate-slot representation
  - residual `power_pole` facilities now use an optional slot pool bounded by the exact-safe powered-demand upper bound instead of an unbounded pose-bool layer
  - ghost rectangle exclusion now composes with the same interval-based geometry used by exact facilities
  - exact path solution extraction and cut replay still emit and consume the existing `pose_idx` / `pose_id` / `pose_optional::...` wire shape
- exact-safe domain compression:
  - mandatory and exact-required slots now use `mode`-conditioned rectangular anchor domains instead of slot-level allowed-assignment tables
  - signature membership is now driven by compact geometric region predicates rather than per-pose membership rows
  - residual `power_pole` slots now derive family ids from shell-distance lookup over `sorted(dx, dy)` instead of raw pose rows
- Safety boundary:
  - this update changes only the certified exact master representation and search engineering
  - it does not change outer search semantics, binding/routing proof admissibility, cut schema, solution schema, or campaign schema
  - no new artifact file is introduced and no `campaign hash` rule changes
- Observability:
  - master build stats now expose `master_representation = coordinate_exact_v2`
  - master build stats now expose `master_domain_encoding = mode_rect_factorized_v1`
  - master build stats now expose `master_domain_table_rows = 0`
  - master build stats now expose `master_mode_rect_domains`
  - master build stats now expose `power_pole_shell_lookup_pairs`
  - master build stats now expose `master_slot_counts`, `master_interval_count`, `master_mode_literals`, and `master_pose_bool_literals`
  - exact run metadata now exposes the same coordinate-master summary fields through `run_benders_for_ghost_rect.last_run_metadata`
- Artifacts: no new artifact files
- Campaign compatibility: no `campaign hash` rule change and no campaign schema change

## 2026-03-18 Exact Campaign Hardening Update

- Scope: `certified_exact`
- Affected runtime roles:
  - `src/search/exact_campaign.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/search/outer_search.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/search/benders_loop.py` remains `CERTIFIED_EXACT_ACTIVE`
- New exact-safe behavior:
  - campaign resume now requires `schema_version`, `proof_summary_schema_version`, `solve_mode = certified_exact`, artifact hashes, and required state fields to all match before reusing persisted state
  - incompatible or malformed persisted campaign state is now auto-reset into a fresh exact campaign instead of being silently reused
  - candidate terminal states now persist `CERTIFIED / INFEASIBLE / UNKNOWN / UNPROVEN` together with `proof_summary`, `exact_safe_cuts`, and loaded/generated exact-safe cut counts
  - campaign stop conditions now persist `last_stop_reason`, while certified final results keep `final_result` and `final_status` aligned
- Safety boundary:
  - resume hardening changes persistence semantics only; it does not change exact feasible sets, cut admissibility, or solve-mode semantics
  - no new artifact file is introduced and `campaign hash` compatibility remains tied to the exact artifact hashes already in use
- Observability:
  - campaign state now carries `schema_version`, `proof_summary_schema_version`, `reset_reason`, `final_status`, and `last_stop_reason`
  - exact run metadata continues to flow through the persisted `proof_summary` and exact-safe cut counters
- Artifacts: no new artifact files
- Campaign compatibility: this round hardens the in-file campaign state schema and reset rules, but does not change exact artifact hash rules

## 2026-03-18 Witness-Indexed Geometric Power Coverage Update

- Scope: `certified_exact`
- Affected runtime roles:
  - `src/models/exact_coordinate_master.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/search/benders_loop.py` remains `CERTIFIED_EXACT_ACTIVE`
- New exact-safe behavior:
  - the geometric `power_coverage` layer no longer creates one pairwise witness bool per `powered_slot × pole_slot`
  - each powered exact-demand slot now selects one witness `power_pole` slot index through `AddElement`, with identical geometric coverage semantics
  - one active pole may still witness multiple powered slots; this round does not introduce any one-to-one matching restriction
  - the non-geometric `coordinate_cover_table` fallback remains exact and unchanged in solve semantics
- Safety boundary:
  - this update only changes the certified exact master encoding of geometric power coverage
  - it does not change outer search, binding/routing admissibility, cut schema, solution schema, or campaign schema
  - no new artifact file is introduced and no `campaign hash` rule changes
- Observability:
  - master build stats now expose `power_coverage.encoding = geometric_element_witness_v1` on the geometric path
  - master build stats now expose `power_coverage.witness_indices` and `power_coverage.element_constraints`
  - geometric power coverage now records `cover_literals = 0`
  - exact run metadata now forwards the same power-coverage summary fields through `run_benders_for_ghost_rect.last_run_metadata`
- Artifacts: no new artifact files
- Campaign compatibility: no campaign schema or artifact-hash rule changes

## 2026-03-18 Exact Precompute Collapse Update

- Scope: `certified_exact`
- Affected runtime roles:
  - `src/models/master_model.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/models/exact_coordinate_master.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/search/benders_loop.py` remains `CERTIFIED_EXACT_ACTIVE`
- New exact-safe behavior:
  - exact initialization now caches normalized pose geometry once per template / pose and reuses it across `_index_pools()`, local signature construction, and exact power-capacity preprocessing
  - exact local power-capacity preprocessing now groups `power_pole` poses by shell pair and reuses one coefficient evaluation across the whole shell-pair bucket when the bucket is geometry-uniform
  - custom non-uniform toy pole geometry inside one shell-pair bucket still keeps exactness by falling back to finer-grained per-geometry evaluation inside that bucket
  - mandatory and required-optional signature/domain payloads are now memoized by `(template, candidate_pose_set)` and reused across repeated exact groups
- Safety boundary:
  - this round changes only certified-exact preprocessing and initialization cost; it does not change exact feasible sets, cut admissibility, solution schema, campaign schema, or evidence-chain semantics
  - no new artifact file is introduced and no `campaign hash` rule changes
- Observability:
  - master build stats now expose `exact_precompute_profile`
  - `exact_precompute_profile` now exposes `power_capacity_shell_pairs`, `power_capacity_shell_pair_evaluations`, `power_capacity_raw_pole_evaluations`, `signature_bucket_cache_hits`, `signature_bucket_cache_misses`, `signature_bucket_distinct_keys`, and `geometry_cache_templates`
  - exact power-capacity family stats now expose `coefficient_source = shell_pair_cache_v1` and `shell_pair_count`
  - exact run metadata now forwards the same precompute summary fields through `run_benders_for_ghost_rect.last_run_metadata`
- Artifacts: no new artifact files
- Campaign compatibility: no campaign schema or artifact-hash rule changes

## 2026-03-18 Local-Capacity Signature-Class Cache Update

- Scope: `certified_exact`
- Affected runtime roles:
  - `src/models/master_model.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/models/exact_coordinate_master.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/search/benders_loop.py` remains `CERTIFIED_EXACT_ACTIVE`
- New exact-safe behavior:
  - exact local power-capacity preprocessing now uses the exact local-capacity signature class as the decisive coefficient reuse key instead of stopping at shell-pair grouping
  - each distinct `(template, exact local-capacity signature class)` is evaluated once, then broadcast to every raw `power_pole` pose in that class
  - shell-pair grouping remains available for diagnostics and comparative profiling, but it is no longer the coefficient truth source
  - repeated exact signature/domain payloads continue to reuse the existing `(template, candidate_pose_set)` memo path
- Safety boundary:
  - this round changes only certified-exact preprocessing reuse; it does not change exact feasible sets, cut admissibility, solution schema, campaign schema, or evidence-chain semantics
  - no new artifact file is introduced and no `campaign hash` rule changes
- Observability:
  - `exact_precompute_profile` now also exposes `power_capacity_signature_classes` and `power_capacity_signature_class_evaluations`
  - exact power-capacity family stats now expose `coefficient_source = exact_signature_cache_v2`
  - exact run metadata now forwards the same new precompute summary fields through `run_benders_for_ghost_rect.last_run_metadata`
- Artifacts: no new artifact files
- Campaign compatibility: no campaign schema or artifact-hash rule changes

## 2026-03-19 Local-Capacity Oracle v3 Update

- Scope: `certified_exact`
- Affected runtime roles:
  - `src/models/master_model.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/models/exact_coordinate_master.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/search/benders_loop.py` remains `CERTIFIED_EXACT_ACTIVE`
- New exact-safe behavior:
  - exact local-capacity signature-class construction now uses compact items `(dx, dy, local_shape_token)` as the primary preprocessing key, where `local_shape_token` is interned directly from the exact cached occupied shape
  - the heavy per-pole shifted-cell materialization path is no longer the primary grouping mechanism; legacy `LocalCapacitySignature` objects are reconstructed only for compatibility and consistency checks
  - local-capacity evaluation now defaults to an exact bitset MIS oracle instead of the previous tiny CP-SAT oracle
  - the previous CP-SAT local-capacity model remains in place as an explicit exact fallback and regression oracle; current build stats record fallback counts instead of hiding them
- Safety boundary:
  - `(dx, dy, orientation)` is still not accepted as the certified-exact truth source; compact-key correctness remains grounded in the exact cached local occupied shape
  - compact-to-legacy reconstruction mismatches now hard-fail instead of silently widening the cache key
  - this round changes only certified-exact preprocessing/oracle internals; it does not change outer search, cut admissibility, solution schema, campaign schema, or evidence-chain semantics
  - no new artifact file is introduced and no `campaign hash` rule changes
- Observability:
  - `exact_precompute_profile` now also exposes `power_capacity_compact_signature_classes`, `power_capacity_compact_signature_evaluations`, `power_capacity_compact_signature_cache_hits`, `power_capacity_compact_signature_cache_misses`, `power_capacity_bitset_oracle_evaluations`, `power_capacity_cpsat_fallbacks`, and `power_capacity_oracle = bitset_mis_v1`
  - exact power-capacity family stats now expose `coefficient_source = exact_compact_bitset_cache_v3`
  - exact power-capacity family stats now expose `compact_signature_class_count`
  - exact run metadata now forwards the same new precompute/oracle summary fields through `run_benders_for_ghost_rect.last_run_metadata`
- Validation:
  - `python -m pytest -q` now passes with this oracle path enabled
- Artifacts: no new artifact files
- Campaign compatibility: no campaign schema or artifact-hash rule changes

## 2026-03-19 Local-Capacity Oracle v4 Update

- Scope: `certified_exact`
- Affected runtime roles:
  - `src/models/master_model.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/models/exact_coordinate_master.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/search/benders_loop.py` remains `CERTIFIED_EXACT_ACTIVE`
- New exact-safe behavior:
  - exact local-capacity evaluation now prefers `rectangle_frontier_dp_v1` whenever the compact signature can be reconstructed entirely from exact cached full-rectangle local shapes
  - current powered exact-demand templates remain on that primary path, including mixed `manufacturing_6x4` `6x4 / 4x6` rectangle variants
  - `bitset_mis_v1` is preserved as the first explicit exact fallback, and the previous tiny CP-SAT local-capacity model remains the second explicit exact fallback
  - compact local-capacity signatures still use `(dx, dy, local_shape_token)` as the preprocessing and coefficient-cache truth source; no external solution, cut, campaign, or artifact wire shape changes were introduced
- Safety boundary:
  - rectangle frontier DP only consumes exact cached occupied-shape truth; it does not promote orientation or any other proxy into the certified-exact truth source
  - non-rectangular local shapes must explicitly fall back to the existing exact bitset oracle, and any remaining oracle failure must explicitly fall back to the existing exact CP-SAT model
  - this round changes only certified-exact local-capacity oracle internals; it does not change outer search, cut admissibility, solution schema, campaign schema, or evidence-chain semantics
  - no new artifact file is introduced and no `campaign hash` rule changes
- Observability:
  - `exact_precompute_profile` now also exposes `power_capacity_rect_dp_evaluations`, `power_capacity_rect_dp_cache_hits`, `power_capacity_rect_dp_cache_misses`, `power_capacity_bitset_fallbacks`, `power_capacity_cpsat_fallbacks`, and `power_capacity_oracle = rectangle_frontier_dp_v1`
  - exact power-capacity family stats now expose `coefficient_source = exact_rect_dp_cache_v4`
  - exact run metadata now forwards the same new precompute/oracle summary fields through `run_benders_for_ghost_rect.last_run_metadata`
- Validation:
  - regression now checks that the current full-project artifact stays on the rectangle-frontier primary path with `power_capacity_bitset_fallbacks == 0` and `power_capacity_cpsat_fallbacks == 0`
- Artifacts: no new artifact files
- Campaign compatibility: no campaign schema or artifact-hash rule changes

## 2026-03-19 Local-Capacity Oracle v5 Update

- Scope: `certified_exact`
- Affected runtime roles:
  - `src/models/master_model.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/models/exact_coordinate_master.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/search/benders_loop.py` remains `CERTIFIED_EXACT_ACTIVE`
- New exact-safe behavior:
  - exact local-capacity evaluation still prefers the rectangle frontier path for current full-project powered templates, but the primary implementation is now the iterative `rectangle_frontier_dp_v2` scanline automaton rather than the previous recursive runtime
  - the previous recursive rectangle DP remains available only as an internal comparison helper for exact regression tests; it is no longer the default runtime oracle
  - internal compile caching for the rectangle automaton is now keyed by `(template, compact_signature, scan_axis)` and remains strictly process-memory only
  - `bitset_mis_v1` and the previous tiny CP-SAT local-capacity model both remain as explicit exact fallbacks, with no silent downgrade
- Safety boundary:
  - this round changes only certified-exact local-capacity oracle internals; it does not change outer search, cut admissibility, solution schema, campaign schema, or evidence-chain semantics
  - the iterative rectangle automaton still consumes exact cached occupied-shape truth and does not promote orientation or any other proxy into the certified-exact truth source
  - non-rectangular local shapes must still explicitly fall back to the existing exact bitset oracle, and any remaining oracle failure must still explicitly fall back to the existing exact CP-SAT model
  - no new artifact file is introduced and no `campaign hash` rule changes
- Observability:
  - `exact_precompute_profile` now also exposes `power_capacity_oracle = rectangle_frontier_dp_v2`
  - `exact_precompute_profile` now also exposes `power_capacity_rect_dp_state_merges`, `power_capacity_rect_dp_peak_line_states`, `power_capacity_rect_dp_peak_pos_states`, and `power_capacity_rect_dp_compiled_signatures`
  - exact power-capacity family stats now expose `coefficient_source = exact_rect_dp_cache_v5`
  - exact run metadata now forwards the same new precompute/oracle summary fields through `run_benders_for_ghost_rect.last_run_metadata`
- Validation:
  - direct regression now checks `rectangle_frontier_dp_v2 == rectangle_frontier_dp_v1 == bitset_mis_v1 == CP-SAT` on toy rectangle signatures
  - full-project regression keeps requiring `power_capacity_bitset_fallbacks == 0` and `power_capacity_cpsat_fallbacks == 0`
- Artifacts: no new artifact files
- Campaign compatibility: no campaign schema or artifact-hash rule changes

## 2026-03-19 Local-Capacity Oracle v6 Update

- Scope: `certified_exact`
- Affected runtime roles:
  - `src/models/master_model.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/models/exact_coordinate_master.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/search/benders_loop.py` remains `CERTIFIED_EXACT_ACTIVE`
- New exact-safe behavior:
  - exact local-capacity evaluation still prefers the rectangle frontier path for current full-project powered templates, but the primary implementation is now the packed-transition `rectangle_frontier_dp_v3` kernel instead of the prior generic iterative automaton
  - the v3 kernel compiles exact `(conflict_mask, future_write_mask, gain)` start-option transitions per `(template, compact_signature, scan_axis)` and runs rect-DP directly on packed frontier states
  - previous `rectangle_frontier_dp_v1` and `rectangle_frontier_dp_v2` implementations remain available only as internal comparison helpers for exact regression tests
  - `bitset_mis_v1` and the previous tiny CP-SAT local-capacity model both remain as explicit exact fallbacks, with no silent downgrade
- Safety boundary:
  - this round changes only certified-exact local-capacity oracle internals; it does not change outer search, cut admissibility, solution schema, campaign schema, or evidence-chain semantics
  - the packed kernel still consumes exact cached occupied-shape truth and does not promote orientation or any other proxy into the certified-exact truth source
  - non-rectangular local shapes must still explicitly fall back to the existing exact bitset oracle, and any remaining oracle failure must still explicitly fall back to the existing exact CP-SAT model
  - no new artifact file is introduced and no `campaign hash` rule changes
- Observability:
  - `exact_precompute_profile` now also exposes `power_capacity_oracle = rectangle_frontier_dp_v3`
  - `exact_precompute_profile` now also exposes `power_capacity_rect_dp_compiled_start_options` and `power_capacity_rect_dp_deduped_start_options`
  - exact power-capacity family stats now expose `coefficient_source = exact_rect_dp_cache_v6`
  - exact run metadata now forwards the same new precompute/oracle summary fields through `run_benders_for_ghost_rect.last_run_metadata`
- Validation:
  - direct regression now checks `rectangle_frontier_dp_v3 == rectangle_frontier_dp_v2 == rectangle_frontier_dp_v1 == bitset_mis_v1 == CP-SAT` on toy rectangle signatures
  - full-project regression keeps requiring `power_capacity_bitset_fallbacks == 0` and `power_capacity_cpsat_fallbacks == 0`
- Artifacts: no new artifact files
- Campaign compatibility: no campaign schema or artifact-hash rule changes

## 2026-03-19 Local-Capacity Oracle v7 Finalization

- Scope: `certified_exact`
- Affected runtime roles:
  - `src/models/master_model.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/models/exact_coordinate_master.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/search/benders_loop.py` remains `CERTIFIED_EXACT_ACTIVE`
- New exact-safe behavior:
  - exact local-capacity evaluation still advertises `rectangle_frontier_dp_v4` as the primary rect-DP path, but runtime now chooses between `v4` and the earlier packed-kernel `v3` through explicit line-subset guardrails
  - the `v4` line-subset transfer kernel is used only when `peak_line_subset_options <= 160` and `compiled_line_subsets <= 2000`; otherwise the solver explicitly falls back to `rectangle_frontier_dp_v3`
  - that `v3` route is still an exact rect-DP oracle, not a heuristic shortcut, and it is now counted explicitly instead of hiding behind the generic rect-DP label
  - `bitset_mis_v1` and the previous tiny CP-SAT local-capacity model both remain as downstream explicit exact fallbacks, with no silent downgrade
- Safety boundary:
  - this round changes only certified-exact local-capacity oracle internals; it does not change outer search, cut admissibility, solution schema, campaign schema, or evidence-chain semantics
  - the guarded `v4 -> v3 -> bitset -> CP-SAT` stack still consumes exact cached occupied-shape truth and still does not promote orientation or any other proxy into the certified-exact truth source
  - non-rectangular local shapes must still explicitly fall back to the existing exact bitset oracle, and any remaining oracle failure must still explicitly fall back to the existing exact CP-SAT model
  - no new artifact file is introduced and no `campaign hash` rule changes
- Observability:
  - `exact_precompute_profile` now also exposes `power_capacity_oracle = rectangle_frontier_dp_v4`
  - `exact_precompute_profile` now also exposes `power_capacity_rect_dp_v3_fallbacks`, `power_capacity_rect_dp_compiled_line_subsets`, and `power_capacity_rect_dp_peak_line_subset_options`
  - exact power-capacity family stats now expose `coefficient_source = exact_rect_dp_cache_v7`
  - exact run metadata now forwards the same guarded-routing summary fields through `run_benders_for_ghost_rect.last_run_metadata`
- Validation:
  - direct regression now checks that a representative `5x5` signature stays on `v4` while a dense mixed `6x4 / 4x6` signature explicitly routes to the `v3` exact fallback
  - full-project regression now requires `power_capacity_rect_dp_v3_fallbacks > 0` while still requiring `power_capacity_bitset_fallbacks == 0` and `power_capacity_cpsat_fallbacks == 0`
- Artifacts: no new artifact files
- Campaign compatibility: no campaign schema or artifact-hash rule changes

## 2026-03-19 `manufacturing_6x4` Mixed CP-SAT Specialization

- Scope: `certified_exact`
- Affected runtime roles:
  - `src/models/master_model.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/models/exact_coordinate_master.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/search/benders_loop.py` remains `CERTIFIED_EXACT_ACTIVE`
- New exact-safe behavior:
  - exact local-capacity evaluation still advertises `rectangle_frontier_dp_v4` as the primary rect-DP path, but dense mixed `manufacturing_6x4` signatures now route explicitly into a template-specialized exact CP-SAT oracle before trying `rectangle_frontier_dp_v3`
  - that specialized CP-SAT path is limited to mixed `6x4 / 4x6` signatures derived from the existing compact truth source `(dx, dy, local_shape_token)`; it does not promote any proxy key into the certified-exact truth source
  - if the specialized CP-SAT path does not prove `OPTIMAL`, the solver now records that event explicitly and falls back explicitly to `rectangle_frontier_dp_v3`; `bitset_mis_v1` and the legacy tiny CP-SAT model remain downstream exact fallbacks
- Safety boundary:
  - this round changes only certified-exact local-capacity internals for one template family; it does not change outer search, cut admissibility, solution schema, campaign schema, or evidence-chain semantics
  - non-rectangular local shapes must still explicitly fall back to the existing exact bitset oracle, and any remaining oracle failure must still explicitly fall back to the existing exact CP-SAT model
  - no new artifact file is introduced and no `campaign hash` rule changes
- Observability:
  - `exact_precompute_profile` now also exposes `power_capacity_m6x4_mixed_cpsat_evaluations`
  - `exact_precompute_profile` now also exposes `power_capacity_m6x4_mixed_cpsat_cache_hits`
  - `exact_precompute_profile` now also exposes `power_capacity_m6x4_mixed_cpsat_selected_cases`
  - `exact_precompute_profile` now also exposes `power_capacity_m6x4_mixed_cpsat_v3_fallbacks`
  - exact run metadata now forwards the same specialized-routing counters through `run_benders_for_ghost_rect.last_run_metadata`
- Validation:
  - direct regression now checks that a dense mixed `manufacturing_6x4` signature routes to the specialized exact CP-SAT path and still matches `rectangle_frontier_dp_v3`, bitset MIS, and the legacy exact CP-SAT oracle
  - full-project regression now requires the specialized mixed-template CP-SAT path to activate while still requiring `power_capacity_bitset_fallbacks == 0` and `power_capacity_cpsat_fallbacks == 0`
- Artifacts: no new artifact files
- Campaign compatibility: no campaign schema or artifact-hash rule changes

## 2026-03-19 Protocol Storage Box Lower-Bound Correction

- Scope: `certified_exact`
- Affected runtime roles:
  - `src/models/master_model.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/models/exact_coordinate_master.py` remains `CERTIFIED_EXACT_ACTIVE`
  - `src/search/benders_loop.py` remains `CERTIFIED_EXACT_ACTIVE`
- New exact-safe behavior:
  - `protocol_storage_box` inferred from generic input slots is now treated only as a certified-exact lower bound, not an exact equality
  - `protocol_storage_box` no longer enters the exact-required optional layer unless an independent sufficiency proof exists; it remains in the residual optional layer under an explicit lower-bound constraint
  - exact static occupied-area lower bounds and powered-demand lower bounds may still use that minimum protocol-box count soundly
  - certification blocker checks now normalize both `solve_mode` and `solve_modes`, and conservatively block missing or malformed exact-mode metadata
- Safety boundary:
  - this correction removes a potentially unsound equality that could cut legal certified-exact layouts
  - missing, malformed, or unknown solve-mode metadata now blocks certified exact rather than silently passing contamination
  - `solve_modes` containing `certified_exact` remain admissible even if `exploratory` is also listed
  - no new artifact file is introduced and no `campaign hash` rule changes
- Observability:
  - master build stats now expose `exact_optional_lower_bounds`
  - exact global-valid-inequality stats now expose `lower_bound_optional_powered_demands`
  - protocol-box cardinality diagnostics now report `mode = required_lower_bound` rather than `fixed_exact_count`
