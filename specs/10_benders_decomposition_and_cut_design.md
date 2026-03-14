> [!NOTE]
> **ACCEPTED_DRAFT — 本文件已与 `src/models/cut_manager.py` 对齐。`[竣工图]` 标注反映代码实际状态。**

# 10 逻辑型 Benders 分解与切平面通信协议 (Logic-based Benders Decomposition & Cut Design)

## 10.1 文档目的与架构定位

本文档是《明日方舟：终末地》极值排布工程的**中央调度与反馈通信协议**。
在确立了主摆放模型 (07 章)、宏观拓扑流预筛子问题 (08 章) 与微观精确路由子问题 (09 章) 后，必须构建一套能够让这三个模型自动协同、自我纠错的算法架构。本章定义了**逻辑型 Benders 分解 (LBBD)** 的执行闭环，以及当子问题判定布线失败时，如何向主问题生成极具剪枝威力的**组合互斥切平面 (Combinatorial No-Good Cuts)**。

---

## 10.2 LBBD 主从协同状态机 (The Master-Subproblem Loop)

针对外层搜索（01 章）传入的每一个确定的空地尺寸目标 $(w, h)$，系统内部执行以下 LBBD 状态机循环：

*   **Step 1: 主问题求解 (Master Placement)**
    调用 07 章 CP-SAT 模型求解当前约束下的摆放方案。
    *   *若返回 `INFEASIBLE`*：终止当前 $(w, h)$ 的探索。
    *   *若返回 `FEASIBLE`*：提取 $\mathbf{z}^*$，进入 Step 2。

*   **Step 2: 一级子问题验证 (Macro-Topological Flow)**
    将 $\mathbf{z}^*$ 冻结为静态网格障碍物，传入 08 章连续 LP 流体模型。
    *   *若返回 `INFEASIBLE`*：执行 10.3 宏观瓶颈切平面提取。**回退至 Step 1**。
    *   *若返回 `FEASIBLE`*：进入 Step 3。

*   **Step 3: 二级子问题验证 (Micro-Exact Routing)**
    将 $\mathbf{z}^*$ 传入 09 章离散 SAT 路由模型。
    *   *若返回 `INFEASIBLE`*：执行 10.4 微观死结切平面提取。**回退至 Step 1**。
    *   *若返回 `FEASIBLE`*：**【系统最高胜利】** 输出终极蓝图！

---

## 10.3 Type-I: 宏观拓扑瓶颈切 (Topological Bottleneck Cuts)

### 10.3.1 最小割溯源 (Min-Cut Extraction)
当 LP 模型无解时，依据 Farkas 引理提取对偶不可行射线，对应"最小割面障碍界限"。

### 10.3.2 肇事刚体集锁定 (Conflict Set Identification)
收集紧贴"最小割面"的实体刚体，构成**拓扑肇事集合 $\Omega_{\text{topo}} \subset \mathcal{I}$**。

### 10.3.3 切平面方程 (The Benders Cut)
$$ \sum_{i \in \Omega_{\text{topo}}} z_{i, p_i^*} \le |\Omega_{\text{topo}}| - 1 $$

---

## 10.4 Type-II: 微观精确死结切 (Micro-Routing Deadlock Cuts)

### 10.4.1 极小不可满足核提取 (MUC Extraction)
调用 `FindUnsatisfiableCore()` 提取最少冲突子句集，映射回**微观肇事集合 $\Omega_{\text{micro}}$**。

### 10.4.2 微观排斥方程 (Micro No-Good Cut)
$$ \sum_{i \in \Omega_{\text{micro}}} z_{i, p_i^*} \le |\Omega_{\text{micro}}| - 1 $$

---

## 10.5 工业级切平面强化技术 (Industrial Cut Lifting)

### 10.5.1 空间平移不变性提拉 (Spatial Translation Lifting)
对 $\Omega_{\text{micro}}$ 中每台机器定义局部邻域 $\Delta(p_i^*)$，注入强化切平面：
$$ \sum_{i \in \Omega_{\text{micro}}} \left( \sum_{q \in \Delta(p_i^*)} z_{i, q} \right) \le |\Omega_{\text{micro}}| - 1 $$

### 10.5.2 模板级对称性拉黑 (Template-Level Symmetry Breaking)
将基于实例 ID 的切平面升维为模板级聚合变量 $Z_{T(i), p}$：
$$ \sum_{i \in \Omega_{\text{conflict}}} Z_{T(i), p_i^*} \le |\Omega_{\text{conflict}}| - 1 $$

> [!NOTE]
> **[竣工图]** 空间平移提拉 (§10.5.1) 和模板级对称性拉黑 (§10.5.2) 在代码中尚未实现。[TBD] 待路由子问题完成后，根据实际切面效果决定是否需要这些强化技术。

---

## 10.6 代码落地：惰性回调与热启动 (Lazy Callbacks & Hot-Start)

本工程强制采用 **惰性约束注入架构 (Lazy Constraint Callback / Hot-Start)**：
1. 主模型收到切平面。
2. 将上一次合法摆放解中（未惹事的机器位置）作为 **Solution Hint** 喂给主模型。
3. 求解器瞬间意识到只需微调惹事机器，每次 Benders 迭代重新求解时间从数十秒坍缩至几百毫秒。

> [!NOTE]
> **[竣工图]** CP-SAT 不支持真正的惰性约束回调 (Lazy Constraint Callback)。代码中使用「累积切面 + 重新求解」的模式替代：每轮将新切面注入模型后重新调用 `model.Solve()`，通过 `model.AddHint()` 提供上一轮解作为热启动。效果等价但每轮有模型重建开销。
