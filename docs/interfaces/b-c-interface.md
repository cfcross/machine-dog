# B/C 导航接口 v1

`bc_contract_version = 1`。当前 **INTERFACE_ONLY**；没有 ROS、仿真运动或真实拍照。C 的 `PatrolRunner` 不用改状态机，只替换传入 adapter 的 `navigate` 方法。

## 入口与请求

`examples/c_patrol_adapter.py::CPatrolNavigator.navigate(request: dict) -> dict` 同步返回终态。依赖 Python 3.10+ 标准库。`CNavigationRequest.parse` 校验并转换为原有 `MoveRequest`，原接口不变。

| 字段 | 类型 | 含义 | 必填 | 合成示例 |
| --- | --- | --- | --- | --- |
| mission_id | str | 一次巡检运行实例 | 是 | mission-example |
| task_id | str | 业务计划编号 | 是 | plan-example |
| checkpoint_id | str | 当前检查点 | 是 | point-example |
| request_id | str | 本次调用唯一编号 | 是 | request-example |
| kind | str | 请求类型，固定 navigate | 是 | navigate |
| requested_at | str | 带时区 ISO 8601 请求时间 | 是 | 2026-11-13T00:00:00+08:00 |
| frame_id | str | 必须与实例配置一致；不自动变换 | 是 | interface_test_map |
| goal | dict | 严格包含有限数值 x/y/yaw，拒绝 bool | 是 | x=0.5、y=0.25、yaw=0 |
| timeout_seconds | number | 正数，默认允许上限 300 秒 | 是 | 1.0 |
| map_version / scene_version | str | 可选版本标签；保存但不验证实际地图 | 否 | synthetic-v1 |

位置单位 m，yaw 单位 rad。`interface_test_map` 与上述坐标都是测试值，不是已知可达点。当前 C 在 mission 中保存地图/场景版本，但 `_request` 不把这两个字段传给 navigate；B 接受可选字段，不要求 C 改动。未来动态接入前需要登记一致的版本。

五类编号分别保留。B 原 `MoveRequest.task_id` 在兼容层内部使用 **request_id** 标识一次执行；原业务 task_id 等四项保存在 `RequestIdentity`，原样返回。真实 **goal_id** 必须由 ROS 客户端绑定；本轮普通夹具为 null，Action 边界测试的 ID 显式标为 SYNTHETIC_FIXTURE，不能当作真实 Action ID。

无效字段返回当前身份的 `failed / invalid_request`。身份本身缺失或无效时抛 ValueError，不编造编号；C 会记录 ADAPTER_ERROR 并停止。C 当前请求字段不变；新增回包字段不会影响其 `_reply` 校验。

## 回包与状态

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| 四项业务 ID | str | 原样返回，不能换成其他检查点或请求 |
| mode | str | 固定 interface_test，拒绝 simulation/real 后端 |
| status | str | REACHED→arrived，FAILED→failed，TIMEOUT→timeout |
| detail | str | 后端原因或明确错误码；异常不带私有配置文本 |
| bc_contract_version | int | 1 |
| goal_id / goal_id_source | str或null / str | 未绑定为 null/UNASSIGNED；本轮绑定仅 SYNTHETIC_FIXTURE |
| validation_scope / data_source | str | INTERFACE_ONLY / SYNTHETIC_FIXTURE |
| pose_source | str | UNKNOWN，没有运行位姿 |
| timestamp | str | B 生成回包的 UTC 时间，不是拍摄时间 |
| rejected_results | int | 被忽略的身份或目标不匹配反馈数 |
| cancel_requested / cancel_acknowledged | bool | 取消意图与确认，分别记录 |
| action_terminal_received / stop_confirmed | bool | Action 结束确认与物理停车不同；本轮 stop_confirmed 始终 false |

RUNNING 继续等待，不能返回 arrived。四项身份、内部执行 ID 和已绑定 goal_id 都需匹配。超时优先于迟到成功；返回后不再接收后台结果。一个实例不重复执行同一 request_id，重复调用返回 failed；重试沿用业务任务编号，但创建新的 request_id，真实后端还需新 goal_id。实例只允许一个活动请求，并发调用返回 navigator_busy。

## 等待、取消与后端边界

导航后端实现 `run(CNavigationRequest, publish, stop_event)`，发送 `GoalBinding` 或 `BackendUpdate`。`FixtureBackend` 只发送明确提供的测试序列，没有默认到达。缺后端返回 backend_unavailable；错误、提前退出或非法消息返回 failed。

每次请求使用一个由 B 创建的 spawn 子进程。单调时钟从 B 接收校验后的请求开始计时，包含启动；不拿 requested_at 或 ROS 时间计算期限。后端阻塞时，父进程返回 timeout 并清理自己的子进程。清理最多三次 0.1 秒 join，另有操作系统调度开销，不承诺硬实时。后端须可序列化、在模块顶层定义；入口放在 `if __name__ == "__main__":` 下，不能直接把 Notebook 局部函数当后端。

`navigator.request_cancel(request_id)` 只对当前请求生效，返回是否登记意图；navigate 返回 failed/cancelled_by_client。没有 ROS 取消发送，也不等候物理停车。子进程终止不是机器人停止。真实 ROS1/ROS2 后端需独立审查持久连接、单目标取消、反馈、watchdog 与停止确认，不能直接把本离线 worker 用作真机控制器。

## C 接入的最小改动

已有 C 工程保持在仓库之外。可直接运行 B 提供的入口：

```bash
python3 -m examples.c_patrol_demo --samples
python3 -m examples.c_patrol_demo --c-project /path/to/C/project --output logs/bc-success --scenario success
```

第二条中的 C 路径需替换，输出目录不能已有 mission.json。它真正调用 C 的 `PatrolRunner`、`InterfaceTestAdapter.capture`、`ReplayBackend` 和报告，不复制 C 的状态机。C 环境另需已有 Pillow；本轮使用 9.0.1，未安装新依赖。

最小 Python 接线（放入可导入脚本并加 main 保护）：

```python
from examples.c_patrol_adapter import CPatrolNavigator
from examples.c_patrol_demo import FixtureBackend, FixtureStep
from examples.interface_demo import Status
# c_adapter 是 C 已有 InterfaceTestAdapter；仅用于文件回放。
nav = CPatrolNavigator(FixtureBackend({"CP01": [FixtureStep(Status.REACHED)]}))
c_adapter.navigate = nav.navigate
# 原 PatrolRunner(inspection_backend, c_adapter, output_dir) 保持不变。
```

例中只给 CP01 测试终态，未配置点会等待至超时；完整三点夹具由上述 CLI 从 C 原 fixture 读取。capture 的文件读取和检测仍归 C，本层不为 capture 或在线模型调用实现强制中断。C 的实际 `_reply` 已检查 request_id/checkpoint_id/mode，导航失败后停止取图，这些是 C 的既有工作。

完整测试命令及分层结果见 `docs/handoffs/validation-2026-11-13.md`。目前可以做 B/C 离线接口联调；实际移动、实时取图、位姿同步仍待 A。
