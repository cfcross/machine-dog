# 2026-11-13 接口交接验证

实际日期取工作站 Asia/Shanghai。基线 `6b1843b`，原 29 项测试先复跑通过。下面是本轮执行结果，全部导航数据为 **INTERFACE_ONLY**；没有 ROS 节点、仿真运动或在线模型调用。

## 来源与审查范围

C 外层 ZIP 37 个文件，SHA256 `7acdf9b504ad14f48dd98c071cb2967b0a4b720c7563c46d93408b34d275e241`；嵌套 current_code.zip 231 个文件，SHA256 `ba78ac385c68175e98aedb7b7e6be307ab721b4955d14bfa5e69bffd098c3210`。校验 CRC、相对路径、重复项、符号链接、加密标记、大小和压缩比后，独立解压；原 ZIP 未改动。没有运行未知安装或硬件启动脚本。

已读外层接口需求、九项问题、事件字段、进度与复现说明；内层 PatrolRunner、NavigationClient、文档、计划、两种 fixture、测试和版本文件，以及导入所需检测/回放入口。实际 `patrol.py` SHA256 为 `9284fbe1a25d8661a900d06972ecf6ae61f76d6fdf625f8bf9f5b2f0c24393ad`，匹配 PATROL_REVIEW_VERSION 的后续更新。旧 PATROL_VERSION 哈希对应较早版本，不是本次读取版本。

C 已有导航不可用失败、当前 ActionClient 等待和巡检失败停止逻辑；B 没有把它们算作自己的修改。本轮仅在 B 仓库增加兼容层及原创测试，C 源码/图片/原始报告不随公开提交或交接 ZIP 分发。

## 分层结果

| 类别 | 结果 | 实际范围 |
| --- | --- | --- |
| B_UNIT_TEST | PASS，32项 | 原 29 项全部保留并通过，另 3 项检查 A/B 合成字段；不是 A/B 动态联调 |
| BC_CONTRACT_TEST | PASS，21项 | 请求/五类ID、终态、超时、取消、后端缺失/阻塞/异常、重试及无效输入 |
| C_PATROL_RUNNER_TEST | PASS，13项 | 实际导入 C 的 PatrolRunner，注入 B navigate，复用 C 的 capture、ReplayBackend 和报告 |
| C 原测试复跑 | PASS，10项 | 外部 C 工程的 test_patrol.py；不计入 B 仓库66项 |
| C 独立检测回放 | PASS，6条事件 | 原 run_inspection.py、6张合成图、哈希绑定回答，三态各2；不是6项单元测试或模型准确率 |
| Python 语法 | PASS | examples/tests 的 compileall |
| AB_SIMULATION_TEST | BLOCKED | 当前可见环境无已确认 ROS/场景/adapter，缺隔离控制、停止复位和实测目标 |
| ABC_END_TO_END_TEST | BLOCKED | 真实运动与实时图像/位姿未接；本轮B/C离线流程不能替代 |
| 在线模型 / 真机 | NOT_RUN | 未调用模型服务，未执行真机控制 |

本仓库完整执行 **66 项测试通过**：原29项＋本轮37项。未设置 C_PROJECT_ROOT 时，13项 C 集成测试会明确跳过；不能把缺源码时的测试命令退出0称作66项已验证。

## 真实 C 流程结果

| 场景 | 任务终态 | 完成检查点 | 检查事件 | 后续行为 |
| --- | --- | --- | --- | --- |
| 三点成功夹具 | completed | 3/3 | 6条成功 | 每点先到达再capture；normal/unknown/abnormal各2 |
| 第二点失败 | failed | 1/3 | 2条成功 | 第二点不取图，第三点skipped |
| 第二点持续RUNNING至期限 | failed，NAVIGATION_TIMEOUT | 1/3 | 2条成功 | 同样停止；取消意图不等于停车 |

旧 request_id、错误 checkpoint_id、旧 goal_id、迟到成功、后端不可用均没有触发错误取图。观测缺失和检测回答异常分别记录 CAPTURE_FAILED / INSPECTION_FAILED，不把先前的导航到达当整轮任务成功。

新增后端有两项启动缺陷先被测试复现：不可序列化对象抛 AttributeError、IPC 创建失败后留下活动标记。现已转为明确失败，并确认后续新请求可用。独立阻塞测试让后端睡眠10秒，父进程使用0.15秒期限；测试实际确认1.5秒内返回且没有遗留活动子进程。这是宽松测试上限，不是控制实时性承诺。

## 复现命令

在 B 仓库根目录，`C_PROJECT_ROOT` 指向已审核的 C 解压包中 project 目录：

```bash
export C_PROJECT_ROOT=/path/to/C/project
python3 -m unittest discover -s tests -v
python3 -m compileall -q examples tests
python3 -m examples.c_patrol_demo --samples
python3 -m examples.c_patrol_demo --c-project "$C_PROJECT_ROOT" --output logs/bc-success --scenario success
python3 -m examples.c_patrol_demo --c-project "$C_PROJECT_ROOT" --output logs/bc-failed --scenario nav_failed
python3 -m examples.c_patrol_demo --c-project "$C_PROJECT_ROOT" --output logs/bc-timeout --scenario nav_timeout
```

每次选择新的输出目录，不覆盖已有 mission.json。故障演示在得到预期失败结果时 CLI 退出0，原始 mission 仍为 failed。

C 独立回放，在 C 的 project 根目录：

```bash
python3 -B -m unittest discover -s tests -p test_patrol.py -v
python3 -B scripts/inspection/run_inspection.py --manifest examples/road_inspection/manifest.json --backend replay --responses examples/road_inspection/responses.json --output /path/to/own/replay-output
```

B 本机原始证据：`logs/2026-11-13-handoff/` 下 baseline-b、baseline-c-patrol、c-independent-replay、bc-startup-before/after、all-tests、syntax、c-replay-* 和 verification.json。日志不随公开 Git 提交；三份 C 流程输出中的图像和原始模型回答只在本地保存。

## 交接归档核对

由 `tools/build_handoffs.py` 明确列出的 B 原创文件打包；version.json 记录 Git SHA、日期、契约版本、包内独立测试结果和依赖。构建器解压后执行对应测试、检查 ZIP 完整性及内容一致性，再给出 SHA256。C 包复现需自带已审核 C project；A 包不依赖 C 或 Pillow。最终打包结果以各包的 version.json 与构建器实际输出为准。
