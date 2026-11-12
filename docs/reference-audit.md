# 参考代码审计

实际日期：2026-11-12，Asia/Shanghai。方法：公开 API 目录树、指定提交的小型原始文件、只读 Git refs；未运行第三方节点、编译 ROS 或连接机器人。未下载地图、模型、SDK 二进制或递归子模块。

**Confirmed** 表示有静态源码/配置证据；**Inferred** 表示由调用关系或官方默认行为推断；**Unknown** 表示尚未确认。三者均不代表运行成功。下表导航链路的动态验证全部为 **NOT_RUN**，本机缺少环境为 **BLOCKED**。

## 1. 来源、版本与许可

| 标记 | 仓库及实际分支 | 审查 commit SHA | 访问与范围 |
| --- | --- | --- | --- |
| N | [fastlio_navigation_2d / zs-ibot](https://github.com/G-SEI-Lab/fastlio_navigation_2d/tree/fee12f4f83d932466254a724cd5800bfb9981861) | `fee12f4f83d932466254a724cd5800bfb9981861` | Confirmed：README、LICENSE、package.xml、CMake、launch/config/param/shell/scripts、建图核心源码；未使用默认分支 |
| I | [elevator-robot / zsibot](https://gitee.com/wongtou/elevator-robot/tree/29d7d700d02d82436f18d8371559749f4b00f523) | `29d7d700d02d82436f18d8371559749f4b00f523` | Confirmed：README、巡检启动与任务/导航模块、目标记录器、智身客户端、SDK LICENSE；未读取现场目标点数值 |
| E | [cmu_tare_on_jetson / stable_on_go2](https://gitee.com/wongtou/cmu_tare_on_jetson/tree/a6f01f93bee980fc2ce3f805375da58f0169a3a4) | `a6f01f93bee980fc2ce3f805375da58f0169a3a4` | Confirmed：页面说明、HEAD、目录树、组件许可/manifest；根 README.md 请求返回 404，未审查探索算法 |

后文路径以 N/I/E 仓库根目录为基准，均对应上述固定提交。

| 仓库 | 许可证据与引用边界 |
| --- | --- |
| N | 根 `LICENSE` 为 GPL v2 文本；`package.xml` 声明 BSD，`src/laserMapping.cpp` 含 BSD 风格版权条款。存在多来源声明，不能用 manifest 的 BSD 替代根许可证，也不能推定每个文件统一授权；具体适用范围和其他依赖许可 **Unknown**。本次仅引用路径和独立分析。 |
| I | README 声称 Apache-2.0 并指向根 LICENSE，但该提交完整目录树中无根 LICENSE；`src/multi_floor_patrol/package.xml` 声明 MIT，`scripts/zsibot/sdk/zsibot_sdk-main/LICENSE` 为 BSD-3-Clause。仓库整体授权存在不一致，需导师/维护者澄清；SDK 许可不能覆盖全部巡检代码。 |
| E | 无根许可证。`src/FAST_LIO/LICENSE` 为 GPL v2；`src/simulation/src/velodyne_simulator/LICENSE` 为 BSD；TARE 的 `src/tare_planner/src/tare_planner/package.xml` 声明 BSD，内含 OR-Tools LICENSE 为 Apache-2.0。这里只确认这些文件，其他组件与整体可再发布范围 **Unknown**。 |

正式仓库未复制任何第三方实现。未来若确需引入代码，先逐文件确认许可与公开授权，保留版权、来源和必要许可文本。

## 2. 三个仓库的作用

| 仓库 | 核心目录/入口 | 与 B 的关系 | 依赖与未确认项 |
| --- | --- | --- | --- |
| N | `src/`、`launch/`、`config/`、`param/teb/`、`shell/`、`scripts/`；`fastlio_mapping`、`sentry_movebase_teb.launch` | 建图、定位、规划和底盘桥接参考 | ROS1/catkin、C++14、Eigen3、PCL≥1.8、Python；move_base、TEB、map_server、octomap_server、pointcloud_to_laserscan、Livox 驱动。具体可用 ROS 发行版、已安装版本、完整依赖和编译结果 Unknown。 |
| I | `src/multi_floor_patrol/`；`patrol_supervisor_node.py → TaskExecutor → NavigationClient`；`scripts/slam/`、`scripts/zsibot/` | C 到 B 的目标与结果接口；较完整的智身控制/里程计桥接 | ROS1、Python3、rospy、actionlib、move_base_msgs、tf；完整巡检还关联语音/视觉服务，均不在本期接入。 |
| E | `src/tare_planner/`、`src/FAST_LIO/`、`src/simulation/`、`src/mid_layer/`、`script/` | 页面说明用于 Jetson 上部署 TARE；未来可能自动提供探索目标（Inferred） | 平台适配、启动入口、传感器与输出话题、依赖完整性和运行情况均 Unknown；不把目录存在当成算法可用。 |

N 的 `CMakeLists.txt` 构建 `fastlio_mapping`，引用 `include/ikd-Tree/ikd_Tree.cpp`。`.gitmodules` 记录 ikd-Tree 上游；本次未递归下载或审计其授权/实现。

## 3. 建图、定位、规划、控制链路

下表是静态调用关系，动态运行均未验证。

| 环节 / 实际节点或函数 | 输入 | 输出 | 源码证据与判断 |
| --- | --- | --- | --- |
| Livox 驱动 | MID360 硬件数据 | `/livox/lidar`、`/livox/imu` | N `shell/mapping/1-mid360`、`shell/navigation/1-mid360` 调用 `livox_ros_driver2 msg_MID360.launch`。外部驱动消息兼容性 Unknown。 |
| 点云与 IMU 预处理 | 代码要求 `livox_ros_driver/CustomMsg`、`sensor_msgs/Imu`；其他 LiDAR 可走 PointCloud2 回调 | 筛选/降采样及运动补偿点云 | N `src/preprocess.h/.cpp` 的 `Preprocess::process/avia_handler`；`src/IMU_Processing.hpp::Process/UndistortPcl`；`config/mid360.yaml`。Confirmed。 |
| FAST-LIO 建图：`laserMapping/fastlio_mapping` | 同步 LiDAR+IMU、外参和滤波配置 | `/Odometry`、TF、`/cloud_registered`、`/cloud_registered_body`、`/Laser_map`；PCD | N `launch/sentry_build_map.launch → mapping_mid360_no_rviz.launch`，`src/laserMapping.cpp::main/map_incremental/publish_odometry`、迭代 Kalman 更新。Confirmed；不开启特征提取，维护 ikd-Tree 地图。 |
| 二维建图：`octomap_server` | `/cloud_registered_body` PointCloud2 | 投影占据栅格 `/projected_map`；map_saver 保存 YAML+PGM | N `launch/Pointcloud2Map.launch`，分辨率 0.05 m；`shell/mapping/2-mapping`、README 的保存入口。外部节点输出契约 Inferred，未实测。 |
| 定位：仍为 `fastlio_mapping` | 预存 PCD、LiDAR+IMU、`/initialpose` PoseWithCovarianceStamped | `/Odometry` nav_msgs/Odometry；`camera_init → body` TF | N `launch/localization_mid360.launch` 加载 `config/localization_mid360.yaml`，`only_localization_mode=true`；`src/laserMapping.cpp::loadPcdToIkdtree/ndtRegistration/init_pose_cbk`。NDT 用于初始/重置对齐，后续继续点云匹配与迭代滤波，停止增量建图。Confirmed。 |
| 二维先验地图：`map_server` | N `PCD/4.yaml` 及其引用图像 | `/prior_map` nav_msgs/OccupancyGrid | N `launch/sentry_localize_gml-floor4_20251118cjs.launch` 将 `/map` 重映射到 `prior_map`；该提交不提供所需地图，运行 Unknown。 |
| 激光切片：`pointcloud_to_laserscan` | `/cloud_registered_body` | `/scan`、`/scan_elevator` sensor_msgs/LaserScan | N `launch/PointsCloud2toLaserscan.launch`；本期仅用平地 `/scan`，高度范围和 `scan_time` 应复核。Confirmed 配置，外部转换未运行。 |
| 全局规划：`move_base1` 内部插件 | 目标 Pose、全局 costmap、TF | 全局路径 nav_msgs/Path | N `launch/sentry_movebase_teb.launch` 未设置 `base_global_planner`。标准 ROS1 move_base 默认 `navfn/NavfnROS`，Navfn 默认执行 Dijkstra；因此 **Inferred 为 Navfn/Dijkstra**，实际运行插件 Unknown。不能因加载 `GlobalPlanner.use_dijkstra` 就断言启用 global_planner。 |
| 局部规划/避障：`teb_local_planner/TebLocalPlannerROS` | 全局路径、局部 costmap、`/odom`、TF | `/cmd_vel` geometry_msgs/Twist | N launch 实际加载 `param/teb/teb_local_planner_params.yaml`，明确选择 TEB。Confirmed；没有证据显示 MPC、DWA 或其他备选参数被当前启动链启用。 |
| N 中智身桥：`RobotBridgeNode` | `/cmd_vel` Twist | TCP JSON `move`；配置指定的 String 状态话题 | `shell/navigation/4-cmd-to-go2-teb` 实际执行 `scripts/ros_to_ibot.py`，名称虽含 go2，调用的是 ibot。该脚本不发布 `/odom`。Confirmed。 |
| I 中智身桥：`RobotBridgeNode` | `/cmd_vel` Twist/TwistStamped、`/Odometry`、SDK 状态 | TCP JSON `move`；带速度的 `/odom` Odometry | `scripts/slam/4-cmd-to-zsibot-teb → scripts/zsibot/client_in_orin.py::cmd_vel_callback/odom_callback/_move_loop`。Confirmed；比 N 的桥接链多了速度反馈，但仍未动态验证。 |
| 到点/失败反馈：`NavigationClient` | `/move_base/result` MoveBaseActionResult | `(success, detail)` → `TaskResult` | I `capabilities/navigation.py::_await_result`：状态 3/SUCCEEDED 视作到达，其他状态失败，默认等待 300 s，失败后 cancel；存在下述误报风险。Confirmed。 |

官方默认行为依据：[move_base.cpp](https://github.com/ros-planning/navigation/blob/noetic-devel/move_base/src/move_base.cpp)、[navfn_ros.cpp](https://github.com/ros-planning/navigation/blob/noetic-devel/navfn/src/navfn_ros.cpp)，2026-11-12 读取，作为默认语义参考，不代表实验室安装了该版本。预期 Navfn 路径话题为 `/move_base1/NavfnROS/plan`（Inferred，需运行时核对）。FAST-LIO 的 `/path` 是轨迹而非导航规划路径，且当前 `path_en=false`。

### 地图、坐标系与规划参数

- **Confirmed：** `src/laserMapping.cpp` 在退出保存阶段写 `PCD/scans.pcd`（二进制 PCD，建图 `pcd_save_en=true`，定位 false）；定位从 `PCD/<map_name>.pcd` 加载，当前 `map_name=4`。二维导航另外加载 `4.yaml`，两种地图必须同源、原点一致。
- **Confirmed：** 定位 TF 为 `map → camera_init → body → body_foot`；前后静态变换在定位 launch 中，动态变换来自 `publish_odometry`，已投影到平面 yaw 和 z=0。Odometry 消息自身仍保存滤波位姿，不能认为它与平面 TF 完全相同。`/Odometry` 与 `/odom` 区分大小写；不是标准 `map → odom → base_link` 命名。
- **Confirmed：** `param/teb/global_costmap_params.yaml` 使用 `map` / `body_foot`，静态层+VoxelLayer+膨胀层；局部配置为同一全局坐标系，5 m×5 m、0.05 m 分辨率滚动窗口，静态层+ObstacleLayer+膨胀层。`costmap_common_params.yaml` 用 `/scan` 标记与清除障碍；静态层 `/map` 依赖 launch 的重映射得到 `/prior_map`。
- **Confirmed：** 当前 TEB 上限 `vx=0.4 m/s`、倒退 `0.2 m/s`、`vy=0`、`wz=0.3 rad/s`，到点容差 `0.2 m / 0.1 rad`，控制频率 10 Hz，move_base 恢复行为关闭；具体可运行和安全速度仍 Unknown。仅配置动态障碍选项不等于具备动态目标跟踪。
- **Unknown：** 已验证仿真真值位姿输入。没有发现本次启动链选择真值 adapter；`marsim` 配置不构成仿真可用证据。未来可由 A 提供约定 TF/位姿/速度，绕过定位节点，但须防止 TF 多发布者，并显式标记 `GROUND_TRUTH`。

## 4. 巡检目标与学生 C 的接口

I 的 `src/multi_floor_patrol/multi_floor_patrol/` 为下列相对路径前缀：

| 内容 | 证据 / 行为 |
| --- | --- |
| 任务点 | `capabilities/navigation.py::load_nav_targets` 读取 `data/<project>/nav_targets.txt` 的 JSON 列表；字段含 name、floor、frame、position/orientation，支持嵌套 pose；frame 默认 map。本次只检查解析器，未引入现场坐标。 |
| 记录位置 | `scripts/slam/record_nav_target.py` 使用 TF `map → robot_frame` 记录位置与四元数；必须核对 robot_frame 是雷达 body 还是底盘 body_foot，二者有偏移。 |
| 提交目标 | `NavigationClient.navigate_to` 通过 `SimpleActionClient('move_base', MoveBaseAction)` 发送 MoveBaseGoal；退化路径向 `/move_base_simple/goal` 发布 PoseStamped。目标 yaw 需要转换为四元数。 |
| 调用关系 | `launch/patrol_supervisor.launch → scripts/patrol_supervisor_node.py → tasks/execution.py::_handle_navigation → NavigationClient`；`SlamManager.start → scripts/slam/start_all_slam.sh` 启动传感器、定位、规划和智身客户端。未执行这些脚本。 |
| C 可复用部分 | 目标点解析及 Action 调用思路。原有 `AbstractTask/TaskResult` 没有强制 task_id 和四态反馈，需要在本项目适配层补充对应关系，不能直接把 bool 当作 REACHED。 |

`move_base1` 是节点名，**不能仅据此认定 Action 叫 `/move_base1`**：官方 move_base 使用公共 NodeHandle 建立 `move_base` Action；而 clear_costmaps 是私有服务。参考代码的 `move_base` 与 `/move_base1/clear_costmaps` 组合有依据，实际命名空间仍待核对。

## 5. 当前风险与缺失

| 优先级 | 证据与问题 | 接入前处理 |
| --- | --- | --- |
| 高 | I `navigation.py::navigate_to` 在 Action 不可用时仅发布目标就返回 True；`tasks/execution.py::_handle_navigation` 据此更新当前位置。`SlamManager.start` 等不到 Action 也返回 True。 | 目标提交成功与实际到达必须分开；缺少后端应 FAILED，禁止触发 C 的到点拍照。 |
| 高 | I `_result_cb` 接受所有 result，不校验 goal_id；等待并非当前 SimpleActionClient 自身的结果，可能串任务。 | 使用当前目标的 Action 回调/结果，并绑定 task_id；测试旧结果、取消、抢占、超时和重复提交。 |
| 高 | N 的桥接只发 String 状态，TEB 却要求 `/odom`；I 的桥接可补充速度，但保留上游 frame，另有默认 `base_link` 状态帧。 | 与 A 统一 `/Odometry`/`/odom`、body/body_foot、速度坐标系和传感器偏移；SDK 速度单位与符号尚 Unknown，不凭名称推定。 |
| 高 | N `ros_to_ibot.py` 有 0.5 s 无命令置零，但 socket recv 无超时、失败也更新已发送值、无显式 shutdown stop。I 客户端有独立通信通道、socket 超时、单调时钟和 shutdown stop，但发送端断链不能保证底盘收到停车，速度缓存无明确过期拒绝。 | 需底盘独立 watchdog、反馈新鲜度和故障注入验证；源码有停车逻辑不等于失联安全已验证。 |
| 高 | 两种桥接均未见有限数值检查或独立速度限幅；TEB 配置不能限制其他 `/cmd_vel` 发布者。 | A/B 核对仲裁、限速和急停；禁止直接运行参考真机桥接。 |
| 中 | N 启动 Livox driver2，但 C++/manifest 使用 driver1 CustomMsg；PCD/4 地图缺失、shell 与桥接有其他工作站绝对路径/外部配置。 | 核对实际消息类型/MD5、构建依赖，换成用户自己的路径和获准地图；本次不复制连接参数。 |
| 中 | N 未显式选择全局插件；`param/mpc`、其他 planner 参数不在当前 launch 加载链；TF 中 map 与 camera_init 直接静态对齐。 | 用运行时参数和真实 TF 核验算法及地图原点，不以文件名作结论。 |
| 中 | N `publish_odometry` 先 publish 再更新协方差，且未填速度；NDT 失败后仍继续主循环。 | 核对定位有效性/协方差时序；增加可信定位准入条件，失败时不允许导航启动。 |
| 中 | 许可声明不一致、ROS 版本与集成环境尚未确定。 | 暂不合并第三方实现，不把 Ubuntu 版本当作已有 ROS 环境。 |

## 6. 学生 B 优先复用顺序

先与 A 固定无真机连接的仿真 adapter、时间戳和 TF；复用 move_base 的 Action 与已确认的 TEB 配置体系，运行时明确全局插件；修复任务成功/失败语义后接 C。定位早期可以使用 A 已验证的真值来源，后续再接 FAST-LIO、NDT 初始化及两类地图。自主探索保留为后续资料，不进入当前闭环。

本轮原创建模只是接口校验器，无规划或底盘能力；实际交付状态和操作命令集中在 [week01-02.md](week01-02.md)。
