# 机器狗二维路面巡检

光明实验室《二维路面巡检学生任务书》学生 B 工程基线。项目周期为 **2026-10-26—2027-01-17**；本次实际审查与测试日期为 **2026-11-12（Asia/Shanghai）**，不回填第 1–2 周实验记录。

最终目标是在平地沿指定路线巡检，在井盖检查点停车拍照，发现沿途碎渣或杂物时保存异常照片及位置，交由任务系统生成可追溯报告。这些是项目目标，尚未在本仓库实现。

本期范围为二维平地导航，不涉及楼梯、多楼层、机械臂或训练行走策略。

| 成员 | 职责 |
| --- | --- |
| A | 仿真环境、机器人与传感器、adapter、实验记录 |
| **B（本仓库）** | **地图、定位、路径规划、导航执行、避障与移动状态反馈** |
| C | 巡检任务、图像检测、异常事件和报告 |

预期协作流程：C 提交带任务编号的目标 → B 规划和导航 → A 的仿真 adapter 执行并提供位姿/传感器 → B 返回到达或失败结果 → C 开展检查并记录。当前只完成接口离线验证。

## 当前进度

- 已完成：指定参考分支的静态审计、导航启动说明 v0、位姿/控制接口清单、原创 Python 标准库接口示例和 13 项基础测试。
- 部分完成：第 1–2 周交付。单点示例可重复运行，但只是人工测试数据的接口演示。
- **单点导航尚未完成动态验证**：本机未发现 ROS、Gazebo、可运行样例场景或已验证的位姿/仿真控制接口。未进行真实机器狗测试。
- 未实现路径搜索、避障或 ROS adapter；后续优先接入参考系统，不重写已有导航算法。

## 目录与环境

工作目录：`/home/student2/projects/machine-dog`。
参考源码单独保存在 `/home/student2/projects/machine-dog-references`，不随本仓库发布。

```text
README.md
.gitignore
docs/reference-audit.md       # 指定版本、算法链路、证据与风险
docs/week01-02.md             # 启动说明 v0、接口约定与真实测试记录
examples/interface_demo.py   # 原创离线接口演示，无运动控制
tests/test_interface_demo.py # 人工数据驱动的接口测试
```

本次实测环境：Ubuntu 22.04.5 LTS、Python 3.10.12、Git 2.34.1。离线示例只依赖 Python 标准库，无需安装依赖，不使用 GPU。用户提供的 GPU/驱动信息未在本轮复测；此前沙盒内 `nvidia-smi` 失败不能说明 GPU 损坏。

## 已验证的启动与测试命令

在仓库根目录执行：

```bash
python3 examples/interface_demo.py --scenario reached
python3 examples/interface_demo.py --scenario failed
python3 examples/interface_demo.py --scenario timeout
python3 -m py_compile examples/interface_demo.py tests/test_interface_demo.py
python3 -m unittest discover -s tests -v
```

2026-11-12：以上命令实际执行通过，13 项测试通过。三个场景分别输出 `RUNNING → REACHED / FAILED / TIMEOUT`，每次都带 `mode=interface-demo`、`validation_scope=INTERFACE_ONLY` 和 `pose_data=SYNTHETIC_FIXTURE`。`REACHED` 仅说明输入测试位姿满足位置和朝向容差，**不是仿真或真机到点成功**；位姿来源为 `UNKNOWN`。

示例没有 ROS、网络、速度发布或 sleep 到点逻辑。配置、判据和失败原因见 [第 1–2 周记录](docs/week01-02.md)。ROS 启动命令仅作为待验证的源码入口列在该文档中，不能直接当作本站安装或运行说明。

## 参考与后续

| 参考仓库 | 审查分支 | 用途 |
| --- | --- | --- |
| [智身巡检](https://gitee.com/wongtou/elevator-robot/tree/zsibot) | `zsibot` | 任务点、导航调用、状态处理和机器狗桥接 |
| [SLAM 与导航](https://github.com/G-SEI-Lab/fastlio_navigation_2d/tree/zs-ibot) | `zs-ibot` | FAST-LIO 建图/定位、move_base、TEB |
| [自主探索](https://gitee.com/wongtou/cmu_tare_on_jetson) | `stable_on_go2`（本次 HEAD） | 未来探索目标来源，本期不开发 |

具体 SHA、许可冲突和源码依据见 [参考审计](docs/reference-audit.md)。本仓库仅含原创文档与接口示例，不合并第三方源码、地图、模型、现场数据或机器连接配置；未擅自添加项目许可证。

下一步与 A 确认仿真、时间/坐标系和控制隔离；与 C 确认任务编号与终态语义；随后修正参考系统的成功判定、核实实际规划插件和 `/odom` 来源，再做可重复的仿真单点到达及障碍物测试。
