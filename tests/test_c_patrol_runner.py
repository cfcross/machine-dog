"""C_PATROL_RUNNER_TEST. Set C_PROJECT_ROOT to the separately supplied project.

Uses C's actual runner, capture fixture, replay detector and reporting. No C
source or images are distributed here. Missing C checkout => explicit skip.
"""
import json
import os
from pathlib import Path
import tempfile
import unittest

from examples.c_patrol_adapter import CPatrolNavigator
from examples.c_patrol_demo import FixtureBackend, FixtureStep, load_c_project
from examples.interface_demo import Status


@unittest.skipUnless(os.environ.get("C_PROJECT_ROOT"), "BLOCKED: set C_PROJECT_ROOT to reviewed C project")
class CPatrolRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project = Path(os.environ["C_PROJECT_ROOT"]).resolve()
        cls.patrol, cls.ReplayBackend, cls.source_hash = load_c_project(cls.project)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.plan = self.patrol.load_plan(self.project / "examples/patrol/plan_demo.json")
        self.capture = self.patrol.InterfaceTestAdapter(self.project / "examples/patrol/interface_fixture.json")
        self.calls = []
        original_capture = self.capture.capture
        def record(request):
            self.calls.append(dict(request))
            return original_capture(request)
        self.capture.capture = record
        self.scripts = {cid: [FixtureStep({"arrived": Status.REACHED, "failed": Status.FAILED,
                                          "timeout": Status.TIMEOUT}[row["status"]])]
                        for cid, row in self.capture.fixture["navigation"].items()}

    def run_patrol(self, navigator=None, inspection_backend=None):
        self.capture.navigate = (navigator or CPatrolNavigator(FixtureBackend(self.scripts))).navigate
        backend = inspection_backend or self.ReplayBackend(self.project / "examples/road_inspection/responses.json")
        runner = self.patrol.PatrolRunner(backend, self.capture, Path(self.temp.name) / "run", navigation_timeout=0.5)
        summary = runner.run(self.plan)
        return runner, summary

    def assert_second_point_stopped(self, runner, summary, error):
        self.assertEqual(summary["mission_status"], "failed")
        self.assertEqual(runner.mission["error"]["code"], error)
        self.assertEqual([p["status"] for p in runner.mission["checkpoints"]], ["completed", "failed", "skipped"])
        self.assertEqual([c["checkpoint_id"] for c in self.calls], ["CP01", "CP01"])
        self.assertEqual(len(runner.records), 2)
        self.assertTrue((runner.root / "mission_summary.json").is_file())

    def test_three_points_six_checks_with_real_c_runner(self):
        runner, summary = self.run_patrol()
        self.assertEqual((summary["mission_status"], summary["checkpoints_completed"], summary["inspections_succeeded"]),
                         ("completed", 3, 6))
        self.assertEqual(summary["judgements"], {"normal": 2, "unknown": 2, "abnormal": 2})
        self.assertEqual(len(self.calls), 6)
        logs = [json.loads(x) for x in (runner.root / "mission_log.jsonl").read_text().splitlines()]
        ids = [r["request"]["request_id"] for r in logs if r["state"] == "navigation_requested"]
        self.assertEqual(len(set(ids)), 3)
        for cid in ("CP01", "CP02", "CP03"):
            arrived = next(i for i,r in enumerate(logs) if r["state"] == "arrived" and r["checkpoint_id"] == cid)
            capture = next(i for i,r in enumerate(logs) if r["state"] == "capture_requested" and r["request"]["checkpoint_id"] == cid)
            self.assertLess(arrived, capture)
        for point in runner.mission["checkpoints"]:
            reply = point["navigation"]
            self.assertEqual(reply["mission_id"], runner.mission["mission_id"])
            self.assertEqual(reply["task_id"], self.plan["task_id"])
            self.assertEqual(reply["checkpoint_id"], point["checkpoint_id"])
            self.assertEqual(reply["validation_scope"], "INTERFACE_ONLY")
            self.assertIsNone(reply["goal_id"])
        self.assertTrue(all(not r["is_model_inference"] and r["context"]["robot_pose"] is None for r in runner.records))

    def test_second_point_failure_stops_capture_and_later_point(self):
        failed = self.patrol.InterfaceTestAdapter(self.project / "examples/patrol/interface_fixture_nav_failed.json")
        self.assertEqual(failed.fixture["navigation"]["CP02"]["status"], "failed")
        self.scripts["CP02"] = [FixtureStep(Status.FAILED)]
        runner, summary = self.run_patrol()
        self.assert_second_point_stopped(runner, summary, "NAVIGATION_FAILED")

    def test_second_point_real_wait_timeout_stops_capture(self):
        self.scripts["CP02"] = [FixtureStep(Status.RUNNING)]
        runner, summary = self.run_patrol()
        self.assert_second_point_stopped(runner, summary, "NAVIGATION_TIMEOUT")
        reply = runner.mission["checkpoints"][1]["navigation"]
        self.assertTrue(reply["cancel_requested"])
        self.assertFalse(reply["cancel_acknowledged"])
        self.assertFalse(reply["stop_confirmed"])

    def test_old_request_success_does_not_trigger_capture(self):
        self.scripts["CP02"] = [FixtureStep(Status.REACHED, identity_overrides={"request_id": "previous-request"}),
                                FixtureStep(Status.FAILED)]
        runner, summary = self.run_patrol()
        self.assert_second_point_stopped(runner, summary, "NAVIGATION_FAILED")
        self.assertEqual(runner.mission["checkpoints"][1]["navigation"]["rejected_results"], 1)

    def test_wrong_checkpoint_success_does_not_trigger_capture(self):
        self.scripts["CP02"] = [FixtureStep(Status.REACHED, identity_overrides={"checkpoint_id": "CP01"}),
                                FixtureStep(Status.FAILED)]
        runner, summary = self.run_patrol()
        self.assert_second_point_stopped(runner, summary, "NAVIGATION_FAILED")

    def test_old_action_goal_does_not_trigger_capture(self):
        self.scripts["CP01"] = [FixtureStep(Status.REACHED, goal_id="fixture-old", action_terminal_received=True),
                                FixtureStep(Status.FAILED, goal_id="fixture-current", action_terminal_received=True)]
        nav = CPatrolNavigator(FixtureBackend(self.scripts, bound_goal_id="fixture-current"))
        runner, summary = self.run_patrol(nav)
        self.assertEqual(summary["mission_status"], "failed")
        self.assertEqual(self.calls, [])
        self.assertEqual(runner.mission["checkpoints"][0]["navigation"]["rejected_results"], 1)

    def test_backend_unavailable_never_captures(self):
        runner, summary = self.run_patrol(CPatrolNavigator())
        self.assertEqual((summary["mission_status"], self.calls), ("failed", []))
        self.assertEqual(runner.mission["checkpoints"][0]["navigation"]["detail"], "backend_unavailable")

    def test_bad_frame_or_goal_stops_without_capture(self):
        self.plan["frame_id"] = "unconfirmed_map"
        runner, summary = self.run_patrol()
        self.assertEqual((summary["mission_status"], self.calls), ("failed", []))
        self.assertEqual(runner.mission["checkpoints"][0]["navigation"]["detail"], "invalid_request")

    def test_invalid_goal_stops_without_capture(self):
        self.plan["checkpoints"][0]["goal"]["x"] = "invalid"
        runner, summary = self.run_patrol()
        self.assertEqual((summary["mission_status"], self.calls), ("failed", []))

    def test_late_success_after_deadline_never_captures(self):
        self.scripts["CP02"] = [FixtureStep(Status.REACHED, delay_s=1.0)]
        runner, summary = self.run_patrol()
        self.assert_second_point_stopped(runner, summary, "NAVIGATION_TIMEOUT")

    def test_unconfirmed_cancellation_stops_c_workflow(self):
        self.scripts["CP01"] = [FixtureStep(Status.FAILED, "cancelled_by_client", goal_id="fixture-goal", cancel_requested=True)]
        runner, summary = self.run_patrol(CPatrolNavigator(FixtureBackend(self.scripts, bound_goal_id="fixture-goal")))
        self.assertEqual((summary["mission_status"], self.calls), ("failed", []))
        self.assertFalse(runner.mission["checkpoints"][0]["navigation"]["stop_confirmed"])

    def test_missing_capture_remains_observation_failure(self):
        self.capture.fixture["observations"]["CP01"]["manhole"]["image_path"] = "missing-image.png"
        runner, summary = self.run_patrol()
        self.assertEqual(summary["mission_status"], "failed")
        self.assertEqual(runner.mission["error"]["code"], "CAPTURE_FAILED")
        self.assertEqual(runner.records, [])
        self.assertEqual(runner.mission["checkpoints"][0]["navigation"]["status"], "arrived")
        self.assertEqual([p["status"] for p in runner.mission["checkpoints"]], ["failed", "skipped", "skipped"])

    def test_detection_failure_is_not_mission_success(self):
        backend = self.ReplayBackend(self.project / "examples/road_inspection/responses.json")
        backend.responses = {key: "not valid JSON" for key in backend.responses}
        runner, summary = self.run_patrol(inspection_backend=backend)
        self.assertEqual((summary["mission_status"], summary["inspections_failed"]), ("failed", 1))
        self.assertEqual(runner.mission["error"]["code"], "INSPECTION_FAILED")
        self.assertEqual([p["status"] for p in runner.mission["checkpoints"]], ["failed", "skipped", "skipped"])


if __name__ == "__main__":
    unittest.main()
