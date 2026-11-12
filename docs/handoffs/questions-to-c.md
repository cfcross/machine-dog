# 请 C 确认的剩余事项

现有源码已确认：只有当前请求 arrived 后取图；导航失败/超时停止；unknown 是待复核，不等于执行失败。以下不重复询问这些已实现规则。

| 项目 | 请填写或选择 |
| --- | --- |
| 兼容层 | 是否接受 bc_contract_version=1，先将 adapter.navigate 指向 B 的 CPatrolNavigator.navigate？接受 / 需调整：____ |
| 唯一性与重试 | 当前 UUID 请求已可区分。是否约定重试必须新 request_id，沿用业务 task_id/checkpoint_id，重新运行整轮时新 mission_id？____ |
| 实际目标登记 | 由谁维护 A 的实际地图中的检查点与 map_version/scene_version？B登记/C引用，或其他：____ |
| 失败后的操作 | 当前立即停止保持不变。后续是否增加人工重试/取消入口？由 C 调度还是操作者触发：____ |
| 取消与安全 | 是否接受“取消意图/确认均不是停车证明”，未确认安全前不自动开启新任务？____ |
| 实际调用环境 | Python版本、C工作空间和入口脚本；可否使用模块顶层后端与 main 保护（spawn）？____ |
| 最小接入位置 | 测试阶段仅替换 navigate，复用原 capture 与 ReplayBackend；需要 B 协助接入哪个脚本？____ |
| 图片与位姿 | A 给图像和对应位姿后，哪一侧维护 capture request_id、图像时间、pose时间的关联？____ |
| 草案版本 | 包内未发现 task_list_draft.json / feedback_draft.json。是否以后以当前 PatrolRunner 请求及 B/C v1 为准？____ |

不需要发送模型凭据、内网连接信息或整套源码。接口需要变更时，请指出具体字段、原因与期望行为。
