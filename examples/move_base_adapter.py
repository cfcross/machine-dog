"""ROS1 move_base message boundary; no ROS import, publisher or motion command.

Only the codec and result handling are tested here (INTERFACE_ONLY). A future
transport must supply the real Action goal_id and serialize events by a monotonic
clock. Cancellation intent is not proof of cancellation or physical stopping.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import IntEnum
import math

from examples.interface_demo import MoveFeedback, MoveRequest, PoseSource, Status, _finite, _text


class GoalStatusCode(IntEnum):
    """Numeric wire values from actionlib_msgs/GoalStatus.msg."""

    PENDING = 0
    ACTIVE = 1
    PREEMPTED = 2
    SUCCEEDED = 3
    ABORTED = 4
    REJECTED = 5
    PREEMPTING = 6
    RECALLING = 7
    RECALLED = 8
    LOST = 9


@dataclass(frozen=True)
class ActionFeedback(MoveFeedback):
    goal_id: str
    cancel_requested: bool = False
    cancel_acknowledged: bool = False
    action_terminal_received: bool = False


def make_move_base_goal(request, goal_factory, stamp):
    """Fill a MoveBaseGoal supplied by its ROS message factory; never send it.

    Use move_base_msgs.msg.MoveBaseGoal and rospy.Time.now() after the actual
    ROS environment is verified. actionlib owns the wire goal_id, not this codec.
    """
    if not isinstance(request, MoveRequest):
        raise ValueError("request must be a MoveRequest")
    goal = goal_factory()
    goal.target_pose.header.frame_id = request.frame_id
    goal.target_pose.header.stamp = stamp
    pose = goal.target_pose.pose
    pose.position.x, pose.position.y, pose.position.z = request.target_x, request.target_y, 0.0
    pose.orientation.x = pose.orientation.y = 0.0
    pose.orientation.z = math.sin(request.target_yaw / 2.0)
    pose.orientation.w = math.cos(request.target_yaw / 2.0)
    return goal


class MoveBaseResultAdapter:
    """Track one submitted goal; transport/server availability is not implemented.

    Create a separate instance for each attempt. Only a matching terminal result
    can report REACHED. Never use this class to infer that a robot has stopped.
    """

    def __init__(self, request, *, goal_id, expected_frame_id, timeout_s,
                 now_s, pose_source=PoseSource.UNKNOWN):
        if not isinstance(request, MoveRequest):
            raise ValueError("request must be a MoveRequest")
        _text("goal_id", goal_id)
        _text("expected_frame_id", expected_frame_id)
        if request.frame_id != expected_frame_id:
            raise ValueError("frame_mismatch: no implicit coordinate transform")
        _finite("timeout_s", timeout_s)
        _finite("now_s", now_s)
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        if not isinstance(pose_source, PoseSource):
            raise ValueError("pose_source must be a PoseSource")
        self.start_time = self.last_time = now_s
        self.timeout = timeout_s
        self.feedback = ActionFeedback(request.task_id, Status.RUNNING, "",
                                       self._timestamp(), pose_source, goal_id)

    @staticmethod
    def _timestamp():
        return datetime.now(timezone.utc).isoformat()

    def _update(self, **fields):
        self.feedback = replace(self.feedback, timestamp=self._timestamp(), **fields)
        return self.feedback

    def poll(self, *, now_s):
        """Wall/monotonic deadline; independent of a paused ROS simulation clock."""
        _finite("now_s", now_s)
        if now_s < self.last_time:
            raise ValueError("clock must not move backwards")
        self.last_time = now_s
        if self.feedback.status == Status.RUNNING and now_s - self.start_time >= self.timeout:
            self._update(status=Status.TIMEOUT, failure_reason="deadline_exceeded",
                         cancel_requested=True)
        return self.feedback

    def request_cancel(self, *, now_s):
        self.poll(now_s=now_s)
        if self.feedback.status == Status.RUNNING:
            self._update(status=Status.FAILED, failure_reason="cancelled_by_client",
                         cancel_requested=True)
        return self.feedback

    @property
    def pending_cancel_goal_id(self):
        """Intent for this exact goal only; the caller must actually cancel it."""
        if self.feedback.cancel_requested and not self.feedback.action_terminal_received:
            return self.feedback.goal_id
        return None

    def on_result(self, message, *, now_s):
        """Consume MoveBaseActionResult.status, including its exact goal_id.

        Wrong-goal results are ignored. Terminal task status never changes; a
        later result may only confirm that the action ended/cancellation arrived.
        A LOST report is not a positive acknowledgement from the action server.
        """
        try:
            goal_id = message.status.goal_id.id
            code = message.status.status
            detail = message.status.text
        except AttributeError as exc:
            raise ValueError("expected MoveBaseActionResult fields") from exc
        self.poll(now_s=now_s)
        if goal_id != self.feedback.goal_id:
            return self.feedback
        if self.feedback.action_terminal_received:
            return self.feedback
        if isinstance(code, bool) or not isinstance(code, int):
            raise ValueError("GoalStatus.status must be an integer")
        terminal = {2, 3, 4, 5, 8, 9}
        if code not in terminal or not isinstance(detail, str):
            raise ValueError("expected a terminal Action result")
        if code == GoalStatusCode.LOST:
            if self.feedback.status == Status.RUNNING:
                self._update(status=Status.FAILED, failure_reason="action_lost",
                             cancel_requested=True)
            return self.feedback
        fields = {"action_terminal_received": True,
                  "cancel_acknowledged": self.feedback.cancel_requested and code in (2, 8)}
        if self.feedback.status == Status.RUNNING:
            if code == GoalStatusCode.SUCCEEDED:
                fields.update(status=Status.REACHED, failure_reason="")
            else:
                reason = "action_" + GoalStatusCode(code).name.lower()
                fields.update(status=Status.FAILED,
                              failure_reason=reason + (": " + detail if detail else ""))
        return self._update(**fields)
