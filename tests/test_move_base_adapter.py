"""Synthetic message fixtures only; not ROS or simulation integration tests."""

from dataclasses import asdict
import json
import math
from types import SimpleNamespace as NS
import unittest

from examples.interface_demo import MoveRequest, PoseSource, Status
from examples.move_base_adapter import MoveBaseResultAdapter, make_move_base_goal


def result(goal_id="current-goal", code=3, text=""):
    return NS(status=NS(goal_id=NS(id=goal_id), status=code, text=text))


def goal_factory():
    return NS(target_pose=NS(header=NS(), pose=NS(position=NS(), orientation=NS())))


class MoveBaseAdapterTests(unittest.TestCase):
    def setUp(self):
        self.request = MoveRequest("task-current", "demo_map", 1, 2, math.pi / 2)
        self.adapter = self.make_adapter()

    def make_adapter(self, **overrides):
        fields = dict(goal_id="current-goal", expected_frame_id="demo_map",
                      timeout_s=10.0, now_s=0.0)
        fields.update(overrides)
        return MoveBaseResultAdapter(self.request, **fields)

    def test_goal_message_codec(self):
        stamp = object()
        goal = make_move_base_goal(self.request, goal_factory, stamp)
        self.assertEqual(goal.target_pose.header.frame_id, "demo_map")
        self.assertIs(goal.target_pose.header.stamp, stamp)
        pose = goal.target_pose.pose
        self.assertEqual((pose.position.x, pose.position.y, pose.position.z), (1, 2, 0))
        self.assertEqual((pose.orientation.x, pose.orientation.y), (0, 0))
        self.assertAlmostEqual(pose.orientation.z, math.sqrt(0.5))
        self.assertAlmostEqual(pose.orientation.w, math.sqrt(0.5))
        self.assertFalse(hasattr(goal, "goal_id"))  # ActionClient supplies it.

    def test_invalid_contract_rejected(self):
        for fields in [dict(goal_id=""), dict(expected_frame_id="odom"),
                       dict(timeout_s=0), dict(timeout_s=math.inf),
                       dict(now_s=math.nan), dict(pose_source="GROUND_TRUTH")]:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.make_adapter(**fields)

    def test_submission_is_not_arrival(self):
        self.assertEqual(self.adapter.poll(now_s=1).status, Status.RUNNING)
        self.assertFalse(self.adapter.feedback.action_terminal_received)

    def test_old_goal_cannot_complete_current_task(self):
        current = self.adapter.on_result(result("old-goal"), now_s=1)
        self.assertEqual(current.status, Status.RUNNING)
        self.assertEqual(current.goal_id, "current-goal")
        self.assertEqual(current.task_id, "task-current")
        accepted = self.adapter.on_result(result(), now_s=2)
        self.assertEqual(accepted.status, Status.REACHED)
        self.assertTrue(accepted.action_terminal_received)

    def test_action_failure_states(self):
        for code, reason in [(2, "preempted"), (4, "aborted"), (5, "rejected"), (8, "recalled")]:
            adapter = self.make_adapter()
            feedback = adapter.on_result(result(code=code, text="backend detail"), now_s=1)
            self.assertEqual(feedback.status, Status.FAILED)
            self.assertEqual(feedback.failure_reason, "action_" + reason + ": backend detail")

    def test_timeout_requests_exact_goal_cancellation(self):
        feedback = self.adapter.poll(now_s=10)
        self.assertEqual(feedback.status, Status.TIMEOUT)
        self.assertEqual(self.adapter.pending_cancel_goal_id, "current-goal")
        self.assertFalse(feedback.cancel_acknowledged)
        self.assertFalse(feedback.action_terminal_received)

    def test_late_success_cannot_overwrite_timeout(self):
        feedback = self.adapter.on_result(result(), now_s=10)
        self.assertEqual(feedback.status, Status.TIMEOUT)
        self.assertTrue(feedback.action_terminal_received)
        self.assertFalse(feedback.cancel_acknowledged)
        self.assertIsNone(self.adapter.pending_cancel_goal_id)

    def test_cancel_intent_and_ack_are_separate(self):
        feedback = self.adapter.request_cancel(now_s=1)
        self.assertEqual(feedback.status, Status.FAILED)
        self.assertEqual(feedback.failure_reason, "cancelled_by_client")
        self.assertFalse(feedback.cancel_acknowledged)
        self.adapter.on_result(result("old-goal", code=2), now_s=2)
        self.assertEqual(self.adapter.pending_cancel_goal_id, "current-goal")
        feedback = self.adapter.on_result(result(code=2), now_s=3)
        self.assertTrue(feedback.cancel_acknowledged)
        self.assertIsNone(self.adapter.pending_cancel_goal_id)
        self.assertEqual(feedback.failure_reason, "cancelled_by_client")

    def test_timeout_remains_after_cancel_ack(self):
        self.adapter.poll(now_s=10)
        feedback = self.adapter.on_result(result(code=8), now_s=11)
        self.assertEqual(feedback.status, Status.TIMEOUT)
        self.assertEqual(feedback.failure_reason, "deadline_exceeded")
        self.assertTrue(feedback.cancel_acknowledged)

    def test_lost_is_not_stop_confirmation(self):
        feedback = self.adapter.on_result(result(code=9), now_s=1)
        self.assertEqual(feedback.failure_reason, "action_lost")
        self.assertFalse(feedback.action_terminal_received)
        self.assertEqual(self.adapter.pending_cancel_goal_id, "current-goal")

    def test_completed_state_does_not_change(self):
        first = self.adapter.on_result(result(), now_s=1)
        self.assertIs(self.adapter.on_result(result(code=4), now_s=2), first)
        self.assertIs(self.adapter.request_cancel(now_s=3), first)
        self.assertIs(self.adapter.poll(now_s=11), first)

    def test_nonterminal_or_malformed_result_does_not_succeed(self):
        for message in [None, result(code=1), result(code=6), result(code=True), result(code=99)]:
            adapter = self.make_adapter()
            with self.subTest(message=message), self.assertRaises(ValueError):
                adapter.on_result(message, now_s=1)
            self.assertEqual(adapter.feedback.status, Status.RUNNING)

    def test_clock_validation(self):
        self.adapter.poll(now_s=2)
        for now in [1, math.nan, True]:
            with self.subTest(now=now), self.assertRaises(ValueError):
                self.adapter.poll(now_s=now)

    def test_feedback_identity_and_source_are_serializable(self):
        for source in PoseSource:
            adapter = self.make_adapter(pose_source=source)
            feedback = adapter.on_result(result(), now_s=1)
            payload = json.loads(json.dumps(asdict(feedback)))
            self.assertEqual(payload["goal_id"], "current-goal")
            self.assertEqual(payload["task_id"], "task-current")
            self.assertEqual(payload["pose_source"], source.value)
            self.assertTrue(payload["timestamp"].endswith("+00:00"))


if __name__ == "__main__":
    unittest.main()
