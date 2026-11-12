"""AB field examples only. This is NOT an AB_SIMULATION_TEST."""
import json
from pathlib import Path
import unittest
from examples.interface_demo import MoveRequest, PoseSample, PoseSource


class HandoffExampleTests(unittest.TestCase):
    def setUp(self):
        self.sample = json.loads((Path(__file__).resolve().parents[1] / "examples/ab_simulation_contract.json").read_text())

    def test_synthetic_request_and_reply_identity(self):
        self.assertEqual(self.sample["ab_contract_version"], 1)
        self.assertEqual(self.sample["data_source"], "SYNTHETIC_EXAMPLE")
        r = self.sample["navigation_request"]["payload"]
        move = MoveRequest(r["request_id"], r["frame_id"], r["goal"]["x"], r["goal"]["y"], r["goal"]["yaw"])
        self.assertEqual(move.task_id, "example-request")
        reply = self.sample["terminal_feedback"]["payload"]
        for key in ("mission_id", "task_id", "checkpoint_id", "request_id"):
            self.assertEqual(r[key], reply[key])
        self.assertIsNone(reply["goal_id"])
        self.assertFalse(reply["stop_confirmed"])

    def test_pose_example_uses_explicit_clock_and_source(self):
        p = self.sample["pose_input"]
        self.assertEqual(p["data_source"], "SYNTHETIC_EXAMPLE")
        sample = PoseSample(p["frame_id"], p["x"], p["y"], p["yaw"], p["timestamp"]["seconds"], PoseSource(p["pose_source"]))
        self.assertEqual(p["timestamp"]["clock"], "SIM_TIME")
        self.assertEqual(sample.pose_source, PoseSource.GROUND_TRUTH)

    def test_unknown_control_endpoints_not_invented(self):
        fields = self.sample["velocity_and_odometry"]
        for key in ("command_topic", "command_message_type", "odom_topic", "odom_message_type", "stop_method", "reset_method", "watchdog_seconds"):
            self.assertIsNone(fields[key])
        self.assertEqual(self.sample["transport"], "UNCONFIRMED")


if __name__ == "__main__":
    unittest.main()
