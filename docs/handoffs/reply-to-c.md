# B 给 C 的九项回复

实际执行：2026-11-13。按收到的 `B/reply_from_B.md` 原顺序回复。接口版本 `bc_contract_version=1`。本次是 **B/C 离线接口联调**，不是机器人巡检成功。

1. **导航启动、环境、地图版本**

   当前可运行 Python 3.10.12 标准库接口，入口 `python3 -m examples.c_patrol_demo --samples`。与 C 联调另用已有 Pillow 9.0.1。没有已验证 ROS/仿真导航启动命令，也没有实际地图版本。完整 C 流程命令和结果见 `validation-2026-11-13.md`；地图/场景版本仍沿用 C 测试计划的说明，不能当作真实地图。

2. **坐标系、位置和朝向**

   请求 `frame_id + goal{x,y,yaw}`，位置米、yaw 弧度。当前只接受实例明确配置的 frame，测试为 `interface_test_map`；不自动做 TF 变换。未来 ROS 目标四元数由既有 B 消息适配器构造，实际地图坐标待 A/B 登记。

3. **已知可达点**

   暂无真实地图中已验证的可达点。C 的 CP01/02/03 是接口夹具坐标，本轮没有向仿真或真机发送。需要 A 提供可复位场景、初始位姿和一处实测可达点。

4. **移动请求入口与例子**

   `examples/c_patrol_adapter.py::CPatrolNavigator.navigate(request)` 接受 C 现有字典。请求的四项业务 ID 全部保留，内部 `MoveRequest.task_id=request_id`。可运行 `python3 -m examples.c_patrol_demo --samples` 查看请求、转换目标及 arrived/failed/timeout/错误编号回包；交接 ZIP 的 `examples/contract_samples.json` 保存同一入口的实际输出。均标为合成数据。

5. **运行、到达、失败和超时如何区分**

   backend 内部使用 RUNNING/REACHED/FAILED/TIMEOUT，navigate 只返回 arrived/failed/timeout。RUNNING 受控等待，四项 ID、内部执行 ID 和已绑定 goal_id 都核对。重复 request_id 拒绝；重试创建新 request_id，真实 Action 还需新 goal_id。当前没有 ROS goal_id，普通回包为 null。取消只登记意图，确认与物理停车分开；详见 `docs/interfaces/b-c-interface.md`。

6. **已有导航结果与日志**

   没有动态导航日志。本轮实际调用 C 的 PatrolRunner：三点六项回放检查完成；第二点失败/超时时只完成第一点两项检查，第二点不取图、第三点跳过。错误 request_id/checkpoint_id/goal_id、迟到成功、后端缺失等已测试。原始输出位于 B 本地 `logs/2026-11-13-handoff/`，不公开图片和 C 的完整运行记录。精简结果与命令见测试报告。

7. **拍摄时刻机器人位姿**

   当前不能提供。本轮继续保留 C 回放的 captured_at=null、robot_pose=null，不拿请求目标或 B 处理时间填充。A 需提供图像时间、最新帧、对应位姿、来源及 TF；B 协助核对坐标和时序。机器人拍摄位姿不能直接填 target_position。

8. **task_list_draft.json / feedback_draft.json 如何调整**

   本次交接内没有这两个文件名，因此无法逐字段评价该草案。已按实际 `plan_demo.json` 和 `PatrolRunner._request/_reply` 对齐：无需修改现有请求字段和终态名称。接入时把已有 adapter.navigate 指向 B navigator.navigate，capture/检测/报告保持 C 原实现。新增的 mission_id/task_id/取消与来源等回包字段均为兼容扩展，C 现有校验接受。map_version/scene_version 当前只在 mission 保存，未来动态接入需把版本登记纳入双方校验。

9. **是否复现 C 的独立检测**

   B 已实际运行 C 原 `run_inspection.py --backend replay`：6 条处理成功，normal/abnormal/unknown 各 2 条；原有 C 巡检测试 10 项通过。回放按图片哈希和类型匹配记录回答，不做模型推理。本轮未复现在线模型，没有读取或请求 API Key；不能称为在线检测复现或识别精度验收。

## 版本与归属

C 的 `NavigationClient` 已改为不可用时失败、等待当前 ActionClient 的结果；这是 C 的既有修改，不计入 B 本轮成果。C 的 PatrolRunner、capture、检测和报告仍是 C 的实现。B 新写兼容层、测试与交接文档，未复制 C 的源码或图片到公开仓库。

实际 patrol.py 哈希为 `9284fbe1a25d8661a900d06972ecf6ae61f76d6fdf625f8bf9f5b2f0c24393ad`，匹配后续 `PATROL_REVIEW_VERSION.json`；旧 `PATROL_VERSION.json` 记录的是较早文件，不能拿旧哈希断言包损坏。需要 C 确认的剩余事项列在 `questions-to-c.md`。
