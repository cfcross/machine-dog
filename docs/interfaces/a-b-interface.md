# A/B 仿真接口 v1

`ab_contract_version = 1`。本文件是待确认的契约，不是 A 已实现的 API。示例统一标记 **SYNTHETIC_EXAMPLE**。A 负责仿真、传感器、底层控制、停止和复位；B 负责地图/定位/规划与目标状态；C 负责取图后的检查流程。

## 1. 最小环境

| A 需提供 | 填写内容 | B 如何使用 |
| --- | --- | --- |
| 仿真与 ROS | 平台/版本、ROS1或ROS2发行版、Python版本 | 确定适配方式，不要求 A 更换平台 |
| 环境路径 | 获准工作空间、已有容器/解释器、环境加载命令 | 使用已有环境，不改系统或共享安装 |
| 启动与结束 | 场景、模型启动命令；停止、复位命令 | 重复同一测试并恢复初始状态 |
| 隔离与资源 | 独立 Master/Domain/namespace、当前使用安排、真机桥接是否彻底隔离 | 明确只有仿真订阅控制命令，避免占用他人任务 |
| 测试场景 | 可复位平地场景、模型及允许保存的实验数据 | 开始一处目标的动态验收 |

未经明确隔离、停止/复位验证，不自动发送任何速度或目标。本仓库没有 A 平台的已验证启动命令。

## 2. 位姿与坐标

| 输入项 | 类型/期望 | 必须说明 |
| --- | --- | --- |
| 位姿入口 | topic/service/API及消息类型 | 实际名称、读取方式、发布频率 |
| x/y、yaw或四元数 | 有限数值，m/rad | 坐标轴、frame_id、child frame、地图原点 |
| 时间戳 | 数值+时钟类型，或明确的带时区时间 | ROS仿真时间/单调时间/现实时间，是否暂停/重置 |
| pose_source | GROUND_TRUTH或ESTIMATED | 真值来自仿真器还是定位估计，不凭命名判断 |
| TF | 父子坐标关系及外参 | 谁发布、频率、有效时段，避免重复发布 |

可先用真值完成单点，不要求先打通 LiDAR+IMU 定位。但地图、位姿、目标必须同一坐标约定；这不能算 FAST-LIO 通过验证。`examples/interface_demo.py::PoseSample` 是离线数值边界，尚不是 ROS 订阅器。

## 3. 控制与反馈

| 接口 | A 需确认 |
| --- | --- |
| 运动入口 | 是否使用 /cmd_vel；实际 topic/API；Twist 还是 TwistStamped；只允许哪个仿真订阅者 |
| 速度语义 | vx/vy/wz 的轴向、参考坐标、m/s与rad/s、控制频率、线/角速度限制 |
| 里程计 | 是否有 /odom；实际消息类型、pose/twist、header/child frame、时间和频率 |
| 安全停止 | 急停、普通停止、取消目标后的处理、命令超时和独立失联 watchdog |
| 控制权 | 谁拥有控制权、是否仲裁多个发布者、如何释放或恢复 |
| 完成证明 | 速度反馈/停止状态与新鲜度；不能把通信返回或取消确认当作已停车 |

所有名称都是核对项，不能直接作为命令执行。最终速度限幅和失联停车不能只依赖 B 的客户端超时。

## 4. 传感器、地图与测试条件

| 项目 | A 提供的信息 |
| --- | --- |
| LiDAR、IMU、已有 LaserScan | topic/API、消息类型、frame_id、频率、时间同步、传感器外参；使用真值时可分阶段接入 |
| 平地地图 | 格式、加载/保存方式、frame_id、原点、地图版本与场景版本、允许公开范围 |
| 单点 | 一个实际验证可达的目标、yaw、初始位姿与复位方式；不能使用 C 的 interface_test_map 坐标替代 |
| 异常测试 | 一个不可达点、静态障碍物布置/恢复方式；成功单点之后再测 |
| 后续多点 | 3–5 个登记目标、路径/终点/时间/干预记录保存方法 |

## 5. 规划后端归谁

A 若只提供场景和底层 adapter，B 接导航规划后端。若 A 已有可用后端，请给真实目标提交、取消、状态和结果接口及规划插件；不默认 A 已实现 move_base 或 Nav2。

| 已确认平台后选择 | B 的接入方向 | 当前状态 |
| --- | --- | --- |
| ROS1 | 核验 move_base/MoveBaseAction 与 actionlib，获取实际 goal_id，接单目标取消 | 仅有消息/结果离线适配，无通信 |
| ROS2 | 核验 Nav2 NavigateToPose Action、goal UUID、结果/取消、生命周期及 QoS | 未实现，待真实平台确定 |
| 其他 API | 由 A 给已有签名、身份、状态与时间约定，再做小型转换 | 未确认，不猜测 API |

B 请求含 mission_id/task_id/checkpoint_id/request_id、frame_id、goal(x/y/yaw)、timeout_seconds。底层 Action ID 独立绑定，结果需关联当前请求；规划参数、到达容差在实际场景验证后登记，不预设成功率。

## 6. 图像与 C 的协作

A 提供图像 topic/API 或文件导出、拍摄时间戳、最新帧保证、相机内外参、拍摄位姿及时间对齐证据。三人确认哪个 adapter 把图像交给 C 的 `capture(request)`，回包必须关联当前 request_id/checkpoint_id 和来源。

C 接受 image_path、image_source、captured_at、robot_pose。现实拍摄时间未知时留空，不能把仿真秒数当 ISO 日期。机器人位姿不是井盖/杂物坐标；没有登记或深度/点云目标定位证据，`target_position` 保持空。

## 7. 第一次单点怎么联调

A 启动隔离仿真 → 验证停止/复位 → B 读取地图及位姿 → 核验 TF/时间 → 接入全局/局部规划 → 发送一个登记目标 → 仿真运动 → 读取对应 Action ID 的结果 → 核对终点位姿 → 返回状态 → 保存轨迹与日志。

当前只可运行 `python3 -m unittest discover -s tests -p test_handoff_examples.py -v`，它检查合成字段，不发送命令。样例在 `examples/ab_simulation_contract.json`；真正的启动、停止、控制命令由 A 填入 `docs/handoffs/questions-to-a.md` 后再核查。
