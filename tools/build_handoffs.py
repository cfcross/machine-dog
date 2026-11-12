"""Build B-only handoffs from a clean Git commit; test each extracted ZIP.

Usage: python3 tools/build_handoffs.py --output-dir /own/exports --c-project /reviewed/C/project
C code/images remain external. No network, ROS, package installation or git push.
"""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

REPO = Path(__file__).resolve().parents[1]
COMMON = ["examples/interface_demo.py", "examples/move_base_adapter.py",
          "tests/test_interface_demo.py", "tests/test_move_base_adapter.py"]
REPORT = "docs/handoffs/validation-2026-11-13.md"
FILES = {
    "C": COMMON + ["examples/c_patrol_adapter.py", "examples/c_patrol_demo.py",
                   "tests/test_c_patrol_adapter.py", "tests/test_c_patrol_runner.py",
                   "docs/interfaces/b-c-interface.md", "docs/handoffs/reply-to-c.md",
                   "docs/handoffs/questions-to-c.md", REPORT],
    "A": COMMON + ["examples/ab_simulation_contract.json", "tests/test_handoff_examples.py",
                   "docs/interfaces/a-b-interface.md", "docs/handoffs/questions-to-a.md", REPORT],
}


def git(*args):
    return subprocess.check_output(["git", *args], cwd=REPO)


def execute(cmd, root, env):
    result = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError("package verification failed:\n" + result.stdout + result.stderr)
    return result


def verify(root, c_project):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env.pop("C_PROJECT_ROOT", None)
    if c_project:
        env["C_PROJECT_ROOT"] = str(c_project)
    result = execute([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], root, env)
    output = result.stdout + result.stderr
    counts = {"B_UNIT_TEST": 0, "BC_CONTRACT_TEST": 0, "C_PATROL_RUNNER_TEST": 0}
    for line in output.splitlines():
        match = re.search(r"\((test_[a-z_]+)\.", line)
        if match and line.endswith("... ok"):
            module = match.group(1)
            category = ("BC_CONTRACT_TEST" if module == "test_c_patrol_adapter" else
                        "C_PATROL_RUNNER_TEST" if module == "test_c_patrol_runner" else "B_UNIT_TEST")
            counts[category] += 1
    ran = re.search(r"Ran (\d+) tests?", output)
    if ran is None or not counts["B_UNIT_TEST"]:
        raise RuntimeError("unittest output did not include verified B tests")
    skipped = int(re.search(r"skipped=(\d+)", output).group(1)) if "skipped=" in output else 0
    if sum(counts.values()) + skipped != int(ran.group(1)):
        raise RuntimeError("test count mismatch")
    execute([sys.executable, "-m", "compileall", "-q", "examples", "tests"], root, env)
    return {"passed": sum(counts.values()), "skipped": skipped, "by_category": counts,
            "syntax": "PASS", "scope": "INTERFACE_ONLY"}, env


def package_readme(recipient):
    shared = """\n运行环境：Python 3.10+。在解压目录执行：\n\n```bash\npython3 -m unittest discover -s tests -v\npython3 -m compileall -q examples tests\n```\n\n来源、Git SHA、接口版本及包内实测数量见 version.json；阶段报告见 docs/handoffs/validation-2026-11-13.md。没有 ROS、仿真运动、真机或在线模型验证。\n"""
    if recipient == "C":
        return """# B → C 导航接口交接

B 提供同步 navigate 兼容层、合成例子与测试。先看 docs/handoffs/reply-to-c.md（九项回复），再看 docs/interfaces/b-c-interface.md。请回复 docs/handoffs/questions-to-c.md。

```bash
python3 -m examples.c_patrol_demo --samples
```

examples/contract_samples.json 是该入口实际生成的合成请求、B目标、arrived/failed/timeout和错误编号样例。

接入只需把 C 已有 adapter.navigate 指向 CPatrolNavigator.navigate；capture/检测/报告继续用 C 的实现。真实C联调须自带已审核代码和Pillow，包内不包含C源码、图片或模型。

```bash
export C_PROJECT_ROOT=/path/to/C/project
python3 -m unittest discover -s tests -v
python3 -m examples.c_patrol_demo --c-project "$C_PROJECT_ROOT" --output logs/new-success --scenario success
```

未设置C路径时，13项集成测试明确跳过；这不代表已联调。Windows可用 `$env:C_PROJECT_ROOT="C:\\path\\to\\project"`。后端类要定义在可导入模块顶层，调用入口用main保护。
""" + shared
    return """# B → A 最小仿真接口交接

B负责地图、定位、规划、目标执行与反馈。当前有离线接口和C流程联调，缺可使用的ROS/场景、位姿、控制以及停止复位条件。

请先填写 docs/handoffs/questions-to-a.md 的P0，详细输入输出在 docs/interfaces/a-b-interface.md。先提供一个获准、独立、可复位的平地场景和一处已验证可达点；停止/复位确认后才发送单点目标。

examples/ab_simulation_contract.json 全部标为 SYNTHETIC_EXAMPLE，包含目标、终态、位姿、速度/里程计字段。空接口待A填写，不能直接当作真实API。

b-current-status.md概述B现状，b-c-interface-summary.md解释三人如何接线。本包不依赖C源码或Pillow，也不会执行运动。
""" + shared


def build(recipient, commit, output_dir, c_project, day):
    target = output_dir / f"machine-dog_B-to-{recipient}_{day}.zip"
    if target.exists():
        raise FileExistsError(f"refusing to overwrite {target}")
    with tempfile.TemporaryDirectory(prefix="handoff-build-", dir=output_dir) as temp:
        root = Path(temp) / "source"
        root.mkdir()
        payload = {path: git("show", f"{commit}:{path}") for path in FILES[recipient]}
        payload["README.md"] = package_readme(recipient).encode()
        if recipient == "A":
            payload["b-current-status.md"] = (
                "# B 当前状态\n\n已有 MoveRequest/MoveFeedback、位姿与终态检查、move_base 消息和结果关联；新兼容层可接C的同步navigate。"
                "原29项测试保留，完整阶段测试66项通过，分层记录见随包报告。"
                "本A包只复测其中29项原测试与3项合成字段检查，不包含C流程测试。\n\n"
                "当前无实际地图/可达点、ROS通信、仿真轨迹、实时相机位姿或停车验证。"
                "优先需要A的P0条件，再由B接入真实导航传输。\n").encode()
            payload["b-c-interface-summary.md"] = (
                "# C → B → A 接线摘要\n\nC的PatrolRunner提交mission_id、业务task_id、checkpoint_id、request_id、frame_id、goal与timeout_seconds。"
                "B保留所有编号，把request_id用于内部单次执行；实际Action goal_id由将来后端独立绑定。"
                "B只在当前目标终态时返回arrived/failed/timeout；失败或超时后C不取图。\n\n"
                "A提供场景、地图/位姿、传感器、底层控制、停止和复位；若没有现成规划器，由B接规划。"
                "相机观测继续走C的capture请求，真实图像/位姿的时钟与编号关联需共同确认。"
                "当前只完成INTERFACE_ONLY，不能把测试坐标、取消意图或机器人位姿当作实测目标/停车/目标物坐标。\n").encode()
        for name, data in payload.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        tests, env = verify(root, c_project if recipient == "C" else None)
        if recipient == "C":
            samples = execute([sys.executable, "-m", "examples.c_patrol_demo", "--samples"], root, env)
            doc = json.loads(samples.stdout)
            assert [doc["replies"][key]["status"] for key in ("arrived", "failed", "timeout")] == ["arrived", "failed", "timeout"]
            assert doc["replies"]["wrong_request_rejected"]["rejected_results"] == 1
            payload["examples/contract_samples.json"] = samples.stdout.encode()
        version = {"project_git_sha": commit, "packed_at": datetime.now().astimezone().isoformat(),
                   "recipient": recipient, "bc_contract_version": 1, "ab_contract_version": 1,
                   "data_source": "SYNTHETIC_EXAMPLE", "package_tests": tests,
                   "AB_SIMULATION_TEST": "BLOCKED", "ABC_END_TO_END_TEST": "BLOCKED",
                   "dependencies": ["Python >=3.10 standard library"] +
                       (["C project + Pillow for optional actual PatrolRunner tests"] if recipient == "C" else []),
                   "third_party_source_included": False,
                   "payload_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(payload.items())}}
        if recipient == "C" and c_project:
            version["tested_c_patrol_sha256"] = hashlib.sha256(
                (c_project / "src/multi_floor_patrol/multi_floor_patrol/inspection/patrol.py").read_bytes()).hexdigest()
        payload["version.json"] = (json.dumps(version, ensure_ascii=False, indent=2) + "\n").encode()
        candidate = Path(temp) / target.name
        with zipfile.ZipFile(candidate, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in sorted(payload.items()):
                z.writestr(name, data)
        unpacked = Path(temp) / "unpacked"
        with zipfile.ZipFile(candidate) as z:
            assert z.testzip() is None and set(z.namelist()) == set(payload)
            for name, data in payload.items():
                assert z.read(name) == data
            z.extractall(unpacked)  # All entries come from the fixed whitelist above.
        extracted_tests, extracted_env = verify(unpacked, c_project if recipient == "C" else None)
        assert extracted_tests == tests
        if recipient == "C":
            replay = execute([sys.executable, "-m", "examples.c_patrol_demo", "--samples"], unpacked, extracted_env)
            assert json.loads(replay.stdout)["replies"]["wrong_request_rejected"]["status"] == "timeout"
        # Exclusive create; never overwrite an earlier handoff or partial file.
        with target.open("xb") as handle:
            handle.write(candidate.read_bytes())
        return {"path": str(target), "bytes": target.stat().st_size, "files": len(payload),
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "git_sha": commit,
                "zip_integrity": "PASS", "extracted_tests": tests}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--c-project", type=Path)
    args = parser.parse_args()
    if git("status", "--porcelain").strip():
        parser.error("commit reviewed files first; only a clean Git snapshot may be packaged")
    commit = git("rev-parse", "HEAD").decode().strip()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    day = datetime.now().astimezone().date().isoformat()
    c_project = args.c_project.resolve() if args.c_project else None
    results = [build(recipient, commit, output, c_project, day) for recipient in ("C", "A")]
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
