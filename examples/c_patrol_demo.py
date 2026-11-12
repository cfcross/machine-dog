"""Explicit synthetic navigation fixtures and optional real C PatrolRunner replay.

Run as a module: python3 -m examples.c_patrol_demo --samples
No ROS, online model, real camera, or robot connection is created.
"""
import argparse
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

from examples.c_patrol_adapter import BackendUpdate, CNavigationRequest, CPatrolNavigator, GoalBinding, MODE
from examples.interface_demo import MoveFeedback, PoseSource, Status
from examples.move_base_adapter import ActionFeedback


@dataclass(frozen=True)
class FixtureStep:
    status: Status
    detail: str = "synthetic_navigation_fixture"
    delay_s: float = 0.0
    identity_overrides: dict = field(default_factory=dict)
    feedback_task_id: str | None = None
    goal_id: str | None = None
    cancel_requested: bool = False
    cancel_acknowledged: bool = False
    action_terminal_received: bool = False


@dataclass
class FixtureBackend:
    """Only emits the supplied test steps; no implicit successful default."""
    scripts: dict
    bound_goal_id: str | None = None
    mode = MODE

    def run(self, request, publish, stop_event):
        if self.bound_goal_id is not None:
            publish(GoalBinding(request.identity, self.bound_goal_id))
        for step in self.scripts.get(request.identity.checkpoint_id, ()):
            if stop_event.wait(step.delay_s):
                return
            identity = replace(request.identity, **step.identity_overrides)
            args = (step.feedback_task_id or request.move.task_id, step.status, step.detail,
                    datetime.now(timezone.utc).isoformat(), PoseSource.UNKNOWN)
            feedback = (ActionFeedback(*args, step.goal_id, step.cancel_requested,
                                       step.cancel_acknowledged, step.action_terminal_received)
                        if step.goal_id is not None else MoveFeedback(*args))
            publish(BackendUpdate(identity, feedback))
        stop_event.wait()  # No terminal supplied: parent deadline, never invented success.


def sample_request(request_id="request-sample-001", checkpoint_id="point-sample-001", timeout=1.0):
    return {"mission_id": "mission-synthetic-001", "task_id": "plan-synthetic-001",
            "checkpoint_id": checkpoint_id, "request_id": request_id, "kind": "navigate",
            "requested_at": datetime.now(timezone.utc).isoformat(), "frame_id": "interface_test_map",
            "goal": {"x": 0.5, "y": 0.25, "yaw": 0.0}, "timeout_seconds": timeout}


def samples():
    request = sample_request()
    parsed = CNavigationRequest.parse(request, expected_frame_id="interface_test_map")
    results = {}
    for name, status in (("arrived", Status.REACHED), ("failed", Status.FAILED), ("timeout", Status.TIMEOUT)):
        backend = FixtureBackend({request["checkpoint_id"]: [FixtureStep(status, "synthetic_" + name)]})
        results[name] = CPatrolNavigator(backend).navigate(request)
    bad = FixtureStep(Status.REACHED, identity_overrides={"request_id": "old-request"})
    results["wrong_request_rejected"] = CPatrolNavigator(
        FixtureBackend({request["checkpoint_id"]: [bad]})).navigate(request)
    return {"data_source": "SYNTHETIC_EXAMPLE", "validation_scope": "INTERFACE_ONLY",
            "c_request": request, "b_move_request": asdict(parsed.move),
            "identity": asdict(parsed.identity), "replies": results}


def load_c_project(project):
    """Import the separately supplied, reviewed C project; never copy its code."""
    project = Path(project).resolve()
    source = project / "src/multi_floor_patrol"
    file = source / "multi_floor_patrol/inspection/patrol.py"
    if not file.is_file():
        raise ValueError("C project must contain src/multi_floor_patrol/.../inspection/patrol.py")
    sys.dont_write_bytecode = True  # Keep the review snapshot unchanged.
    sys.path.insert(0, str(source))
    from multi_floor_patrol.inspection import patrol
    from multi_floor_patrol.inspection.backends import ReplayBackend
    if Path(patrol.__file__).resolve() != file:
        raise ValueError("another C project is already imported in this process")
    return patrol, ReplayBackend, hashlib.sha256(file.read_bytes()).hexdigest()


def run_c_replay(project, output, scenario):
    project = Path(project).resolve()
    patrol, ReplayBackend, source_hash = load_c_project(project)
    fixture_name = "interface_fixture_nav_failed.json" if scenario == "nav_failed" else "interface_fixture.json"
    capture_adapter = patrol.InterfaceTestAdapter(project / "examples/patrol" / fixture_name)
    states = {"arrived": Status.REACHED, "failed": Status.FAILED, "timeout": Status.TIMEOUT}
    scripts = {cid: [FixtureStep(states[row["status"]], "c_fixture_replay")]
               for cid, row in capture_adapter.fixture["navigation"].items()}
    if scenario == "nav_timeout":
        scripts["CP02"] = [FixtureStep(Status.RUNNING)]
    navigator = CPatrolNavigator(FixtureBackend(scripts))
    capture_adapter.navigate = navigator.navigate  # The only C adapter substitution.
    runner = patrol.PatrolRunner(ReplayBackend(project / "examples/road_inspection/responses.json"),
                                capture_adapter, output, navigation_timeout=1.0)
    summary = runner.run(patrol.load_plan(project / "examples/patrol/plan_demo.json"))
    return {"validation_scope": "INTERFACE_ONLY", "c_patrol_sha256": source_hash, **summary}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", action="store_true")
    parser.add_argument("--c-project", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--scenario", choices=("success", "nav_failed", "nav_timeout"), default="success")
    args = parser.parse_args()
    if args.samples and (args.c_project or args.output):
        parser.error("samples does not read a C project")
    if args.samples:
        result = samples()
    elif args.c_project and args.output:
        result = run_c_replay(args.c_project, args.output, args.scenario)
    else:
        parser.error("choose --samples or supply --c-project and --output")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not args.samples:
        expected = "completed" if args.scenario == "success" else "failed"
        if result["mission_status"] != expected:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
