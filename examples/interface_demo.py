"""Offline contract demo. No ROS, network, planner, or motion control."""

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import math


class Status(str, Enum):
    RUNNING = "RUNNING"
    REACHED = "REACHED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"


class PoseSource(str, Enum):
    GROUND_TRUTH = "GROUND_TRUTH"
    ESTIMATED = "ESTIMATED"
    UNKNOWN = "UNKNOWN"


def _text(name, value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _finite(name, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False  # Python integers may exceed the ROS floating-point range.
    if not finite:
        raise ValueError(f"{name} must be a finite number")


@dataclass(frozen=True)
class MoveRequest:
    task_id: str
    frame_id: str
    target_x: float
    target_y: float
    target_yaw: float

    def __post_init__(self):
        _text("task_id", self.task_id)
        _text("frame_id", self.frame_id)
        for name in ("target_x", "target_y", "target_yaw"):
            _finite(name, getattr(self, name))


@dataclass(frozen=True)
class PoseSample:
    frame_id: str
    x: float
    y: float
    yaw: float
    sample_time_s: float  # Same synthetic/monotonic clock as InterfaceDemo.step.
    pose_source: PoseSource = PoseSource.UNKNOWN

    def __post_init__(self):
        _text("frame_id", self.frame_id)
        for name in ("x", "y", "yaw", "sample_time_s"):
            _finite(name, getattr(self, name))
        if not isinstance(self.pose_source, PoseSource):
            raise ValueError("pose_source must be a PoseSource")


@dataclass(frozen=True)
class MoveFeedback:
    task_id: str
    status: Status
    failure_reason: str
    timestamp: str  # UTC ISO 8601; not used to calculate elapsed time.
    pose_source: PoseSource


class InterfaceDemo:
    """Evaluate supplied fixtures only; REACHED is a geometric test outcome.

    Units: metres, radians, seconds. One instance per request. Terminal states
    are immutable. This class is not a navigation backend or safety controller.
    """

    def __init__(self, request, *, start_time_s=0.0, timeout_s=10.0,
                 position_tolerance_m=0.1, yaw_tolerance_rad=0.1,
                 max_pose_age_s=0.5):
        if not isinstance(request, MoveRequest):
            raise ValueError("request must be a MoveRequest")
        _finite("start_time_s", start_time_s)
        for name, value in (("timeout_s", timeout_s),
                            ("position_tolerance_m", position_tolerance_m),
                            ("yaw_tolerance_rad", yaw_tolerance_rad),
                            ("max_pose_age_s", max_pose_age_s)):
            _finite(name, value)
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if yaw_tolerance_rad > math.pi:
            raise ValueError("yaw_tolerance_rad must not exceed pi")
        self.request = request
        self.start = self.last_time = start_time_s
        self.timeout = timeout_s
        self.position_tolerance = position_tolerance_m
        self.yaw_tolerance = yaw_tolerance_rad
        self.max_pose_age = max_pose_age_s
        self.feedback = self._feedback(Status.RUNNING)

    def _feedback(self, status, reason="", source=PoseSource.UNKNOWN):
        return MoveFeedback(self.request.task_id, status, reason,
                            datetime.now(timezone.utc).isoformat(), source)

    def step(self, *, now_s, pose=None):
        if self.feedback.status != Status.RUNNING:
            return self.feedback
        _finite("now_s", now_s)
        if now_s < self.last_time:
            raise ValueError("clock must not move backwards")
        if pose is not None and not isinstance(pose, PoseSample):
            raise ValueError("pose must be a PoseSample or None")
        self.last_time = now_s
        source = pose.pose_source if pose else self.feedback.pose_source
        # A sample at the deadline does not retroactively complete a task.
        if now_s - self.start >= self.timeout:
            self.feedback = self._feedback(Status.TIMEOUT, "deadline_exceeded", source)
        elif pose is not None:
            if pose.frame_id != self.request.frame_id:
                self.feedback = self._feedback(Status.FAILED, "frame_mismatch", source)
            elif pose.sample_time_s > now_s:
                self.feedback = self._feedback(Status.FAILED, "pose_from_future", source)
            elif now_s - pose.sample_time_s > self.max_pose_age:
                self.feedback = self._feedback(Status.FAILED, "stale_pose", source)
            else:
                distance = math.hypot(pose.x - self.request.target_x,
                                      pose.y - self.request.target_y)
                # Reduce each angle before subtraction to avoid finite-float overflow.
                yaw_delta = (math.remainder(pose.yaw, math.tau)
                             - math.remainder(self.request.target_yaw, math.tau))
                yaw_error = abs(math.atan2(math.sin(yaw_delta), math.cos(yaw_delta)))
                reached = distance <= self.position_tolerance and yaw_error <= self.yaw_tolerance
                self.feedback = self._feedback(Status.REACHED if reached else Status.RUNNING,
                                               source=source)
        return self.feedback

    def fail(self, reason):
        _text("failure_reason", reason)
        if self.feedback.status == Status.RUNNING:
            self.feedback = self._feedback(Status.FAILED, reason, self.feedback.pose_source)
        return self.feedback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("reached", "failed", "timeout"), default="reached")
    args = parser.parse_args()
    request = MoveRequest("interface-demo-001", "demo_map", 1.0, 0.0, 0.0)
    demo = InterfaceDemo(request)
    print(json.dumps({"mode": "interface-demo", "validation_scope": "INTERFACE_ONLY",
                      "pose_data": "SYNTHETIC_FIXTURE", "request": asdict(request)}))
    print(json.dumps(asdict(demo.feedback)))
    if args.scenario == "reached":
        # Explicit fixtures supplied to the checker, not robot motion or a simulation.
        result = demo.step(now_s=1.0, pose=PoseSample("demo_map", 1.0, 0.0, 0.0, 1.0))
    elif args.scenario == "failed":
        result = demo.step(now_s=1.0, pose=PoseSample("wrong_frame", 1.0, 0.0, 0.0, 1.0))
    else:
        result = demo.step(now_s=10.0)
    print(json.dumps(asdict(result)))


if __name__ == "__main__":
    main()
