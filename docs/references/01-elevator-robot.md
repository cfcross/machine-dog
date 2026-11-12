# 01｜智身巡检：任务怎样交给导航

## 版本与阅读范围

[仓库 zsibot 分支](https://gitee.com/wongtou/elevator-robot/tree/zsibot)，本次核对提交 `29d7d700d02d82436f18d8371559749f4b00f523`（2026-11-12）。本地是选取文件的快照，没有 `.git`；目录树和已保存文件的 Git blob 哈希与该提交一致。

已读 README、巡检入口、任务解析/执行、导航/定位管理、状态上下文、检查配置及智身客户端。语音、视觉、机械臂和 SDK 内部实现没有完整审查，现场任务点数值未读取。本文的“确认”均指静态代码，**没有运行整个巡检系统**。

## 它解决什么问题

这个 ROS1/Python 项目把“去某处、做检查、回来”拆成任务，交给导航和检查能力执行，并记录当前位置。`zsibot` 分支提供智身机器狗的控制桥接。对我们而言，它主要帮助理清 C 如何提交任务、B 如何回报移动结果；电梯和机械臂流程不进入二维平地项目。

## 核心模块：输入怎样变成输出

下文 `P/` 表示 `src/multi_floor_patrol/multi_floor_patrol/`。

| 模块 | 作用 | 输入 → 处理 → 输出 | 关键文件/入口 |
| --- | --- | --- | --- |
| 任务入口 | 先确认任务再执行 | 指令 → 请求语言模型规划并等待用户确认 → 任务列表 | `src/multi_floor_patrol/scripts/patrol_supervisor_node.py::_handle_instruction/_handle_confirmation/_run_plan` |
| 任务解析与队列 | 把任务交给对应能力 | JSON action/target → 转为 AbstractTask，顺序出队 → TaskResult 列表 | `P/tasks/decomposition.py::parse_tasks`、`P/tasks/execution.py::TaskExecutor.execute` |
| 目标管理与导航 | 将命名检查点变成导航目标 | nav_targets JSON → 位置/四元数/坐标系 → MoveBaseGoal 与成功/失败说明 | `P/capabilities/navigation.py::load_nav_targets/NavigationClient.navigate_to` |
| 状态上下文 | 记住任务起点与当前地点 | 导航返回值 → 更新地点、楼层和历史 | `P/state/context.py::RobotContext`、`P/tasks/execution.py::_handle_navigation` |
| 检查配置 | 区分不同检查任务 | 检查名称 → 提示词、拍摄前位置等配置 → 检查能力调用 | `P/tasks/check_profiles.py::CheckProfile`、`P/tasks/execution.py::_handle_arm_check`；不是本项目井盖算法 |
| 机器人桥接 | 将 ROS 与机器人服务连接 | `/cmd_vel` → TCP move；`/Odometry`+SDK 速度 → `/odom` | `scripts/zsibot/client_in_orin.py::cmd_vel_callback/odom_callback/_move_loop` |

目录中 `P/integrations/` 对接语音和模型服务，`P/data/` 保存项目配置，`P/utils/` 负责路径/进程等工具。`scripts/slam/` 编排外部 SLAM 与导航；它们不是本仓库自行实现的规划算法。

## 算法与判断方法

- **任务分解**：指令和上下文 → 调用外部语言模型生成 action/target → `parse_tasks` 校验任务类型 → 队列。规划调用已确认；模型内部算法、效果和外部服务可用性未知，也不是导航路径搜索。
- **导航 Action**：这是 ROS 的长任务接口。目标位姿 → `move_base` 执行 → 返回状态；客户端把 SUCCEEDED（3）当作到达。具体全局/局部规划由外部导航工程决定，不能从此客户端推定。
- **位置状态维护**：导航函数的布尔结果 → 更新 `RobotContext`。它是任务记账，不是定位算法，也不能证明机器人真在该位置。
- **速度桥接**：读取 Twist 或 TwistStamped 的 vx/vy/wz → 转为服务命令。客户端带无命令超时、通信超时和退出 stop，但网络断开后的物理停车未验证。

## 主流程从哪里开始

静态入口为 `roslaunch multi_floor_patrol patrol_supervisor.launch`，本机未执行：

`launch/patrol_supervisor.launch → patrol_supervisor_node.py → TaskExecutor.execute → NavigationClient → move_base → TaskResult`。

导航前 `SlamManager.start` 调用 `scripts/slam/start_all_slam.sh`，后者会启动传感器、定位、规划及智身客户端。**不能把这个脚本当成安全仿真入口。** 运行还依赖 ROS1、actionlib、move_base_msgs，以及外部导航/机器人服务；当前依赖环境未验证。

## 对我们有用的部分与问题

先复用命名目标与 Action 的接口思路，让 C 提交带 task_id 的检查点，B 只在当前目标真正返回成功后通知 C。暂不接语音、跨层和机械臂。

三个问题影响这条边界：

1. `navigate_to` 在服务器不可用时只发布 simple goal 就返回 True。`_handle_navigation` 会据此更新位置：**目标已发送不等于到达**。
2. `_result_cb` 不检查 goal_id。此前已用旧目标的成功结果离线复现误报；我们的适配器会忽略不同 goal_id，但尚未接 ROS。
3. `TaskExecutor.execute` 在普通任务失败后仍继续取下一项，没有通用的“导航失败则不检查”规则。与 C 联调时必须明确任务依赖。

待确认：真实 Action 命名空间、task_id 与每次 goal_id 的绑定、失败/重试策略、底盘坐标与速度单位、独立停车保护。

许可也未统一：README 声称 Apache-2.0，但该提交缺根 LICENSE；巡检 package.xml 写 MIT，SDK 子目录另有 BSD-3-Clause。不能据此认定整仓可直接合并。原始证据见 [首轮审计](../reference-audit.md)，本项目只保存自主编写的接口和说明。
