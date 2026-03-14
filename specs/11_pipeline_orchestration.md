> [!WARNING]
> **DRAFT — 本文件为草案，来源于 Gemini deep think-1.md Turn 23。总控、缓存、检查点、日志思路可保留。待 07–10 代码接口稳定后细化。**

# 11 全局流水线编排与总控状态机 (Global Pipeline Orchestration)

## 11.1 文档目的与架构定位

本文档是《明日方舟：终末地》基地极值排布工程的**最高软件工程执行规范**。
在前 10 章，我们构建了从物理规则解析到几何降维，再到运筹学 Benders 分解的全部理论模型。本章旨在定义整个系统的**主程序入口 (`main.py`)**，将所有离散的数学模型统合为一个全自动、具备高容错性、支持断点续传的**工业级软件流水线 (Automated Pipeline)**。

---

## 11.2 全局执行生命周期 (The Global Lifecycle)

整个工程流水线严格划分为四大串行阶段 (Phases)。

### Phase A: 静态数据底座预热 (Static Precomputation)
1.  运行 `demand_solver.py` (04章)：计算 219 台机器与度数矩阵。
2.  运行 `instance_builder.py` (05章)：发放 326 张绝对刚体身份证。
3.  运行 `placement_generator.py` (06章)：穷举并过滤所有合法几何候选位姿字典。
*   **工程优化 (Cache Hit)**：Phase A 生成的 JSON 文件被视为"编译缓存"，若输入规则未变，直接从磁盘加载。

### Phase B: 外层目标降序发生器 (Outer Lexicographical Dispatch)
依据 01 章目标函数，生成空地组合候选集，按 $\Phi(w, h)$ 绝对降序排列。

### Phase C: 逻辑型 Benders 求解引擎 (The LBBD Core Engine)
全系统的算力心脏。从候选队列头部弹出最高分空地，启动 10 章 Benders 状态机闭环。

### Phase D: 蓝图验收与序列化 (Blueprint Finalization)
一旦 Phase C 宣告 `SATISFIABLE`，按 12 章规范序列化为 `optimal_blueprint.json`。

---

## 11.3 Phase C: LBBD 核心状态机流转图

```text
[ START ] 提取当前最高分空地尺寸 (w, h)
   │
   ▼
[ STATE 1: MASTER_SOLVE ] 求解 07 章主问题 (CP-SAT) <────────────────────────┐
   ├─ 返回 INFEASIBLE ───► 抛弃，拉取下一名 (w, h)。                        │
   │                                                                     │
   ├─ 返回 FEASIBLE (z*) ─► 锁定 326 个刚体草图坐标。                      │
   │                                                                     │
   ▼                                                                     │
[ STATE 2: MACRO_FLOW ] 求解 08 章拓扑流子问题 (LP)                             │
   ├─ 返回 INFEASIBLE ───► 生成 Type-I 拓扑 Cut，注入主问题 ───────────┤
   │                                                                     │
   ├─ 返回 FEASIBLE ──────► 允许进入微观排雷。                             │
   │                                                                     │
   ▼                                                                     │
[ STATE 3: MICRO_ROUTING ] 求解 09 章精确布线子问题 (SAT)                        │
   ├─ 返回 INFEASIBLE ───► 生成 Type-II 微观死结 Cut，注入主问题 ───────┘
   │
   ├─ 返回 FEASIBLE ──────► 【全系统终止】跳转 Phase D！
```

---

## 11.4 工业级容错与断点续传 (Checkpointing & Fault Tolerance)

1. **外层游标持久化 (Outer Cursor State)**：
   维护 `search_cursor.json`，重启时跳过已否决的目标。
2. **全局切平面池化保存 (Global Cut Pool Persistence)**：
   所有 Cut 立即追加写入 `data/checkpoints/benders_cuts.jsonl`。
   重启时全量预加载历史切平面（Hot-Start）。

---

## 11.5 极速超时熔断策略 (Timeout & Heuristic Failsafe)

1. **微观层单次熔断**：09 章单次布线上限 `60 秒`。超时则虚构粗粒度 Cut 强行打回。
2. **宏观层全局熔断**：单一空地目标总迭代次数上限 `MAX_ITER = 300`。

---

## 11.6 并发与硬件算力压榨策略 (Concurrency & Hardware Utilization)

1. **主问题引擎满载并行**：07 章 CP-SAT 给予 `num_search_workers = 24`。
2. **子问题引擎快速单线程**：08/09 章锁定 `num_search_workers = 1`。

---

## 11.7 可观测性与日志规范 (Observability & Logging UX)

- `[INFO] [OUTER]`：播报当前攻坚的空地目标尺寸与得分。
- `[SOLVE] [MASTER]`：主问题寻找可行草图的耗时。
- `[WARN] [CUT]`：子问题报错打回，播报切平面内容。
- `[SUCCESS] [ROUTING]`：布线成功的终极宣告。
