# 03｜TARE：没有预设检查点时，下一步去哪里

## 版本与阅读范围

[仓库](https://gitee.com/wongtou/cmu_tare_on_jetson)本次 HEAD 为 `stable_on_go2`，提交 `a6f01f93bee980fc2ce3f805375da58f0169a3a4`（2026-11-12）。没有根 README；本地不是完整 Git 检出。新增保存的文件均按此提交下载并核验 Git blob 哈希，没有替换原文件。

本轮补读 `start.txt`、GO2/zsl 启动链、TARE 主循环、覆盖/视点/全局规划主要函数、局部规划与路径跟随、传感器适配、地形处理、manifest 和许可证。未审计全部第三方库、SDK、模型、场景资源或运行二进制。以下均为源码结论，**未执行探索或仿真**。

## 它解决什么问题

普通巡检已经知道要去哪些井盖。自主探索则要边观察边决定下一处值得去的位置，直到按自身判据认为没有剩余目标。该仓库页面面向 Jetson/Go2，源码中确实存在 TARE 的分层覆盖规划，还包含智身相关启动文件。它是后续自动建图/选探索目标的参考，本轮不集成。

## 核心模块与真实目录

下文 `T/` 表示 `src/tare_planner/src/tare_planner/`，`M/` 表示 `src/mid_layer/src/`。

| 模块 | 作用 | 输入 → 处理 → 输出 | 关键文件/入口 |
| --- | --- | --- | --- |
| 位姿与点云适配 | 把 SLAM 输出接到探索接口 | `/Odometry`、注册点云 → 旋转/重发布，再同步位姿与点云 → `/state_estimation_at_scan` 等 | `src/gps_follow/src/fastlio_repub.cpp`、`M/slam_interface/src/slamInterface.cpp`、`M/sensor_scan_generation/src/sensorScanGeneration.cpp` |
| 地形与可见区域 | 判断哪里可走、哪里还没看见 | 点云/位姿 → 地面高度、占据栅格、遮挡与前沿提取 → 地形点云及未覆盖点 | `M/terrain_analysis/src/terrainAnalysis.cpp`；`T/src/planning_env/planning_env.cpp`、`T/src/rolling_occupancy_grid/rolling_occupancy_grid.cpp` |
| 观察位置选择 | 找能看到新区域的位置 | 未覆盖表面/前沿+候选视点 → 可达、碰撞与新增覆盖筛选 → 选中视点 | `T/src/viewpoint_manager/viewpoint_manager.cpp`、`T/src/local_coverage_planner/local_coverage_planner.cpp::SelectViewPoint` |
| 分层访问顺序 | 避免只在附近来回走 | 探索网格/视点距离 → 全局与局部访问顺序 → 探索路径、`/way_point` | `T/src/grid_world/grid_world.cpp::SolveGlobalTSP`、局部 `SolveLocalCoverageProblem`、`T/src/tsp_solver/tsp_solver.cpp` |
| 局部避障与跟随 | 把前方路点变成速度 | `/way_point`、地形/点云 → 筛选预生成路径 → `/path`，再跟随得到速度 | `M/local_planner/src/localPlanner.cpp`、`M/local_planner/src/pathFollower.cpp` |
| 完成与恢复 | 防止无路或结束后继续乱走 | 返回起点、剩余目标、反馈有效性 → 完成锁存或暂时排除阻塞区域 | `T/include/sensor_coverage_planner/exploration_completion.h`、`T/include/sensor_coverage_planner/blocked_target_recovery.h`；主循环调用 |

`T/config/` 配置场景；`T/launch/` 启动节点；`src/FAST_LIO/` 是此工程自己的 SLAM 副本；`src/simulation/` 有仿真相关目录，不能仅据此认为实验室场景可启动。

## 算法怎样选目标

- **前沿提取**：占据栅格 → 找未知区域与已知空闲区域的邻接边界，再过滤/聚类 → 前沿点。例如看见门口但没看见房内，门后的未知区域会提供继续观察的线索。`GetFrontier/UpdateFrontiers` 有实现，默认 `floor4.yaml` 的 `kUseFrontier=true`。
- **覆盖与视点选择**：点云、视点和激光可见性 → 统计某位置还能看见多少未覆盖表面/前沿点 → 选择一组观察位置。代码有贪心队列和随机候选采样，不是“永远去最近前沿”，也没有证据表明这里使用了概率熵公式。
- **分层 TSP**：把待访问区域或视点的距离组成矩阵 → 用 OR-Tools 求访问顺序 → 全局/局部路径。TSP 即旅行商问题；代码使用 `PATH_CHEAPEST_ARC` 初始策略，不能宣称得到数学上的全局最优解。
- **局部路径库**：路点、地形障碍 → 对预生成路径旋转/缩放并排除碰撞候选、评分 → `/path`；跟随器再根据方向误差计算速度。此处不是 move_base+TEB。

“走过”和“看过”不同：`PlanningEnv::UpdateCoveredArea` 根据视场、遮挡和访问过的视点标记表面覆盖；`GridWorld::UpdateCellStatus` 管理区域状态。完成判据还要求离开过起点、回到起点附近、无剩余目标且数据有效，结果会锁存；它不是对真实世界已全部探索的证明。

## 主程序怎样串起来

`start.txt` 指向 `roslaunch exploration_go2 GO2.launch`（`M/exploration_go2/launch/GO2.launch`），并另列 `gps_follow lio_repub.launch`。GO2 默认选 FAST-LIO、`scenario=floor4`，包含传感器、SLAM 接口、地形分析、局部规划和 `T/launch/explore.launch`。

`T/src/tare_planner_node/tare_planner_node.cpp` 创建 `SensorCoveragePlanner3D`；`T/src/sensor_coverage_planner/sensor_coverage_planner_ground.cpp::execute` 的定时循环依次更新地图/视点、统计未覆盖点、调用全局和局部规划，再发布 `/way_point` 与探索状态。`localPlanner` 输出 `/path`；`pathFollower` 发布 `/cmd_vel` **TwistStamped** 和 `/cmd_vel_only` Twist，不能无适配地混接另一仓库的接口。

启动链里 TARE、前沿和局部路径跟随已由代码/配置确认；阻塞目标恢复虽然有实现，主循环默认参数为 false，`floor4.yaml` 未覆盖它，**不能说默认已启用恢复**。所有运行效果仍 Unknown。

## 对我们有用的部分与待确认项

后续可参考“未覆盖区域→探索目标”的上层思路；当前井盖巡检先用明确目标点，不同时引入另一套局部规划。依赖 ROS1、C++/PCL/Eigen 与 OR-Tools；构建文件引用仓库内的 OR-Tools 动态库，目标架构/可用性未验证。

需确认预生成路径资源、地图/车体 TF、速度消息、位姿同步，以及完成判据和安全停止。`GO2.launch` 本身不包含上述重发布节点，`start.txt` 将它列为另一条命令；同时 `lio_repub.launch` 设置全局 `/use_sim_time=false`，不能直接用于共享仿真。默认入口还会录包、可自动开始探索，均未执行。

许可按组件不同：FAST_LIO 为 GPL v2，TARE manifest 声明 BSD，OR-Tools 为 Apache-2.0，其他范围未完全确认。原始许可记录见 [首轮审计](../reference-audit.md)。本轮只扩展阅读范围，不引入源码或数据。
