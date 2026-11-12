"""BC_CONTRACT_TEST: original tests, synthetic input, no C/ROS dependencies."""
from dataclasses import asdict
import multiprocessing as mp
import threading
import time
import unittest
from unittest.mock import patch

from examples.c_patrol_adapter import CNavigationRequest, CPatrolNavigator, MODE
from examples.c_patrol_demo import FixtureBackend, FixtureStep, sample_request
from examples.interface_demo import Status


class BlockingBackend:
    mode = MODE
    def run(self, request, publish, stop_event):
        time.sleep(10)  # Deliberately ignores cancellation; only our test child.


class BrokenBackend:
    mode = MODE
    def run(self, request, publish, stop_event):
        raise RuntimeError("private exception content must not be returned")


class CContractTests(unittest.TestCase):
    def setUp(self):
        self.request = sample_request(timeout=0.5)
        self.cid = self.request["checkpoint_id"]

    def navigator(self, *steps, **kwargs):
        return CPatrolNavigator(FixtureBackend({self.cid: list(steps)}, **kwargs))

    def test_identity_and_goal_conversion(self):
        r = CNavigationRequest.parse(self.request, expected_frame_id="interface_test_map")
        self.assertEqual(asdict(r.identity), {k: self.request[k] for k in asdict(r.identity)})
        self.assertEqual(r.move.task_id, self.request["request_id"])
        self.assertNotEqual(r.move.task_id, r.identity.task_id)
        self.assertEqual((r.move.target_x, r.move.target_y, r.move.target_yaw), (0.5, 0.25, 0))
        self.assertIsNone(r.map_version)  # C's current _request does not pass plan versions.
        augmented = {**self.request, "map_version": "synthetic-v1", "scene_version": "fixture-v1"}
        r = CNavigationRequest.parse(augmented, expected_frame_id="interface_test_map")
        self.assertEqual((r.map_version, r.scene_version), ("synthetic-v1", "fixture-v1"))

    def test_status_mapping_and_all_ids_preserved(self):
        for source, target in ((Status.REACHED, "arrived"), (Status.FAILED, "failed"), (Status.TIMEOUT, "timeout")):
            with self.subTest(source=source):
                reply = self.navigator(FixtureStep(source, "test_reason")).navigate(self.request)
                self.assertEqual(reply["status"], target)
                for key in ("mission_id", "task_id", "checkpoint_id", "request_id"):
                    self.assertEqual(reply[key], self.request[key])
                self.assertEqual(reply["detail"], "test_reason")
                self.assertEqual(reply["mode"], "interface_test")
                self.assertEqual(reply["validation_scope"], "INTERFACE_ONLY")
                self.assertIsNone(reply["goal_id"])
                self.assertFalse(reply["stop_confirmed"])

    def test_running_waits_for_explicit_terminal(self):
        result = self.navigator(FixtureStep(Status.RUNNING), FixtureStep(Status.REACHED)).navigate(self.request)
        self.assertEqual(result["status"], "arrived")

    def test_running_without_terminal_expires(self):
        result = self.navigator(FixtureStep(Status.RUNNING)).navigate(self.request)
        self.assertEqual((result["status"], result["cancel_requested"]), ("timeout", True))
        self.assertFalse(result["cancel_acknowledged"])

    def test_all_identity_mismatches_are_ignored(self):
        for key in ("mission_id", "task_id", "request_id", "checkpoint_id"):
            with self.subTest(key=key):
                result = self.navigator(FixtureStep(Status.REACHED, identity_overrides={key: "old"}),
                                        FixtureStep(Status.FAILED, "current_failure")).navigate(self.request)
                self.assertEqual((result["status"], result["detail"], result["rejected_results"]),
                                 ("failed", "current_failure", 1))

    def test_b_feedback_execution_id_is_also_checked(self):
        result = self.navigator(FixtureStep(Status.REACHED, feedback_task_id="old-execution"),
                                FixtureStep(Status.FAILED)).navigate(self.request)
        self.assertEqual((result["status"], result["rejected_results"]), ("failed", 1))

    def test_old_action_goal_cannot_reach_current_goal(self):
        result = self.navigator(FixtureStep(Status.REACHED, goal_id="fixture-old", action_terminal_received=True),
                                FixtureStep(Status.FAILED, goal_id="fixture-new", action_terminal_received=True),
                                bound_goal_id="fixture-new").navigate(self.request)
        self.assertEqual((result["status"], result["goal_id"], result["rejected_results"]),
                         ("failed", "fixture-new", 1))
        self.assertEqual(result["goal_id_source"], "SYNTHETIC_FIXTURE")

    def test_unbound_action_result_is_ignored(self):
        result = self.navigator(FixtureStep(Status.REACHED, goal_id="fixture-unbound", action_terminal_received=True),
                                FixtureStep(Status.FAILED)).navigate(self.request)
        self.assertEqual((result["status"], result["rejected_results"]), ("failed", 1))

    def test_deadline_rejects_late_success_and_repeated_request(self):
        nav = self.navigator(FixtureStep(Status.REACHED, delay_s=1.0))
        first = nav.navigate(self.request)
        self.assertEqual(first["status"], "timeout")
        second = nav.navigate(self.request)
        self.assertEqual(second["detail"], "duplicate_request_id")
        self.assertEqual(first["status"], "timeout")

    def test_backend_terminal_timeout_not_overwritten_by_success(self):
        result = self.navigator(FixtureStep(Status.TIMEOUT), FixtureStep(Status.REACHED)).navigate(self.request)
        self.assertEqual(result["status"], "timeout")

    def test_retry_uses_new_request_id(self):
        nav = self.navigator(FixtureStep(Status.REACHED))
        self.assertEqual(nav.navigate(self.request)["status"], "arrived")
        retry = {**self.request, "request_id": "retry-002"}
        self.assertEqual(nav.navigate(retry)["request_id"], "retry-002")
        self.assertEqual(nav.navigate(self.request)["status"], "failed")

    def test_backend_missing_and_exception_fail_closed(self):
        for backend, detail in ((None, "backend_unavailable"), (BrokenBackend(), "backend_exception")):
            result = CPatrolNavigator(backend).navigate(self.request)
            self.assertEqual((result["status"], result["detail"]), ("failed", detail))
            self.assertNotIn("private", str(result))

    def test_unpicklable_backend_fails_closed(self):
        backend = FixtureBackend({})
        backend.bad_attribute = lambda: None
        result = CPatrolNavigator(backend).navigate(self.request)
        self.assertEqual((result["status"], result["detail"]),
                         ("failed", "backend_start_or_transport_error"))

    def test_ipc_setup_failure_does_not_leave_navigator_busy(self):
        nav = self.navigator(FixtureStep(Status.REACHED))
        with patch("multiprocessing.context.SpawnContext.Pipe", side_effect=OSError("test allocation failure")):
            first = nav.navigate(self.request)
        self.assertEqual(first["status"], "failed")
        result = nav.navigate({**self.request, "request_id": "after-allocation-failure"})
        self.assertEqual(result["status"], "arrived")

    def test_blocking_backend_is_bounded_and_child_is_reaped(self):
        before = {p.pid for p in mp.active_children()}
        start = time.monotonic()
        result = CPatrolNavigator(BlockingBackend()).navigate({**self.request, "timeout_seconds": 0.15})
        self.assertEqual(result["status"], "timeout")
        self.assertLess(time.monotonic() - start, 1.5)
        self.assertEqual({p.pid for p in mp.active_children()}, before)
        self.assertFalse(result["stop_confirmed"])

    def test_invalid_goal_time_frame_and_fields_never_arrive(self):
        cases = [{"goal": {"x": v, "y": 0, "yaw": 0}} for v in (True, float("nan"), float("inf"), 10**1000, "1")]
        cases += [{"timeout_seconds": v} for v in (0, -1, True, float("nan"), 301)]
        cases += [{"frame_id": "map"}, {"requested_at": "2026-11-13T00:00:00"},
                  {"requested_at": "invalid"}, {"kind": "capture"}, {"extra": 1}, {"goal": {"x": 1}}]
        for change in cases:
            with self.subTest(fields=list(change)):
                result = CPatrolNavigator().navigate({**self.request, **change})
                self.assertEqual((result["status"], result["detail"]), ("failed", "invalid_request"))

    def test_missing_identity_is_not_fabricated(self):
        for key in ("mission_id", "task_id", "checkpoint_id", "request_id"):
            raw = dict(self.request); raw.pop(key)
            with self.assertRaises(ValueError): CPatrolNavigator().navigate(raw)

    def test_live_backend_mode_is_refused(self):
        backend = FixtureBackend({});backend.mode = "simulation"
        with self.assertRaises(ValueError): CPatrolNavigator(backend)

    def test_explicit_cancel_matches_request_and_does_not_confirm_stop(self):
        nav = CPatrolNavigator(BlockingBackend())
        answers = []
        thread = threading.Thread(target=lambda: answers.append(nav.navigate(self.request)))
        thread.start()
        try:
            limit = time.monotonic() + 0.3
            while not nav.request_cancel(self.request["request_id"]) and time.monotonic() < limit:
                time.sleep(0.005)
            self.assertFalse(nav.request_cancel("different-request"))
        finally:
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(answers[0]["status"], "failed")
        self.assertEqual(answers[0]["detail"], "cancelled_by_client")
        self.assertTrue(answers[0]["cancel_requested"])
        self.assertFalse(answers[0]["cancel_acknowledged"])
        self.assertFalse(answers[0]["stop_confirmed"])

    def test_cancel_confirmation_is_separate_from_physical_stop(self):
        result = self.navigator(FixtureStep(Status.FAILED, goal_id="fixture-goal", cancel_requested=True,
                                            cancel_acknowledged=True, action_terminal_received=True),
                                bound_goal_id="fixture-goal").navigate(self.request)
        self.assertTrue(result["cancel_acknowledged"])
        self.assertFalse(result["stop_confirmed"])

    def test_unconfirmed_or_cancelled_action_cannot_claim_success(self):
        for step in (FixtureStep(Status.REACHED, goal_id="fixture-goal"),
                     FixtureStep(Status.REACHED, goal_id="fixture-goal", cancel_requested=True, action_terminal_received=True)):
            result = self.navigator(step, bound_goal_id="fixture-goal").navigate(self.request)
            self.assertEqual((result["status"], result["detail"]), ("failed", "backend_protocol_error"))


if __name__ == "__main__":
    unittest.main()
