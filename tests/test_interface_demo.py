"""Contract tests with synthetic fixtures; no navigation integration tests."""

from dataclasses import asdict
from datetime import datetime
import json
import math
import unittest

from examples.interface_demo import InterfaceDemo, MoveRequest, PoseSample, PoseSource, Status


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.request = MoveRequest("task-1", "demo_map", 1.0, 2.0, 0.0)
        self.demo = InterfaceDemo(self.request)

    def pose(self, **overrides):
        fields = dict(frame_id="demo_map", x=1.0, y=2.0, yaw=0.0, sample_time_s=1.0)
        fields.update(overrides)
        return PoseSample(**fields)

    def test_request_validation(self):
        for field, value in [("task_id", " "), ("frame_id", ""), ("target_x", math.nan),
                             ("target_y", math.inf), ("target_yaw", "0"), ("target_x", True)]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                MoveRequest(**{**asdict(self.request), field: value})

    def test_configuration_validation(self):
        for fields in [dict(timeout_s=0), dict(max_pose_age_s=-1),
                       dict(position_tolerance_m=math.inf), dict(yaw_tolerance_rad=4)]:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                InterfaceDemo(self.request, **fields)

    def test_pose_validation(self):
        for fields in [dict(x=math.nan), dict(sample_time_s=math.inf),
                       dict(pose_source="invalid"), dict(frame_id="")]:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.pose(**fields)

    def test_missing_pose_does_not_reach(self):
        self.assertEqual(self.demo.step(now_s=9.0).status, Status.RUNNING)
        result = self.demo.step(now_s=10.0)
        self.assertEqual(result.status, Status.TIMEOUT)
        self.assertEqual(result.failure_reason, "deadline_exceeded")

    def test_position_and_heading_both_required(self):
        self.assertEqual(self.demo.step(now_s=1.0, pose=self.pose(x=0)).status, Status.RUNNING)
        self.assertEqual(self.demo.step(now_s=1.0, pose=self.pose(yaw=0.2)).status, Status.RUNNING)
        self.assertEqual(self.demo.step(now_s=1.0, pose=self.pose()).status, Status.REACHED)

    def test_angle_wraparound(self):
        demo = InterfaceDemo(MoveRequest("angle", "demo_map", 1, 2, math.pi - 0.02))
        self.assertEqual(demo.step(now_s=1, pose=self.pose(yaw=-math.pi + 0.02)).status, Status.REACHED)

    def test_frame_mismatch(self):
        result = self.demo.step(now_s=1, pose=self.pose(frame_id="odom"))
        self.assertEqual((result.status, result.failure_reason), (Status.FAILED, "frame_mismatch"))

    def test_stale_and_future_pose(self):
        for stamp, reason in [(0.0, "stale_pose"), (2.0, "pose_from_future")]:
            demo = InterfaceDemo(self.request)
            result = demo.step(now_s=1, pose=self.pose(sample_time_s=stamp))
            self.assertEqual((result.status, result.failure_reason), (Status.FAILED, reason))

    def test_deadline_has_priority(self):
        self.assertEqual(self.demo.step(now_s=10, pose=self.pose(sample_time_s=10)).status, Status.TIMEOUT)

    def test_terminal_states_are_immutable(self):
        for state in (Status.REACHED, Status.FAILED, Status.TIMEOUT):
            demo = InterfaceDemo(self.request)
            if state == Status.REACHED:
                first = demo.step(now_s=1, pose=self.pose())
            elif state == Status.FAILED:
                first = demo.fail("backend_unavailable")
            else:
                first = demo.step(now_s=10)
            self.assertIs(demo.step(now_s=11, pose=self.pose(sample_time_s=11)), first)
            self.assertIs(demo.fail("later_error"), first)

    def test_invalid_clock_does_not_change_state(self):
        self.demo.step(now_s=2)
        for now in (1, math.nan, math.inf, True):
            with self.subTest(now=now), self.assertRaises(ValueError):
                self.demo.step(now_s=now)
        self.assertEqual(self.demo.feedback.status, Status.RUNNING)

    def test_failure_reason_required(self):
        with self.assertRaises(ValueError):
            self.demo.fail("")
        result = self.demo.fail("backend_unavailable")
        self.assertEqual(result.status, Status.FAILED)
        self.assertEqual(result.failure_reason, "backend_unavailable")

    def test_feedback_serialization_and_provenance(self):
        for source in PoseSource:
            demo = InterfaceDemo(self.request)
            feedback = demo.step(now_s=1, pose=self.pose(pose_source=source))
            payload = json.loads(json.dumps(asdict(feedback)))
            self.assertEqual(payload["task_id"], "task-1")
            self.assertEqual(payload["pose_source"], source.value)
            self.assertEqual(payload["failure_reason"], "")
            self.assertIsNotNone(datetime.fromisoformat(payload["timestamp"]).utcoffset())


if __name__ == "__main__":
    unittest.main()
