"""C PatrolRunner navigation boundary. INTERFACE_ONLY; no ROS or motion transport.

A trusted, picklable backend implements run(request, publish, stop_event). It runs
in an owned child process so a blocking backend cannot hold navigate forever.
Process cleanup is NOT robot cancellation or proof of stopping. Only test mode is
accepted; a live ROS transport needs a separately reviewed lifetime/safety design.
"""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import multiprocessing as mp
import threading
import time
from typing import Protocol

from examples.interface_demo import MoveFeedback, MoveRequest, PoseSource, Status, _finite, _text
from examples.move_base_adapter import ActionFeedback

BC_CONTRACT_VERSION = 1
MODE = "interface_test"


def _timestamp(value):
    _text("timestamp", value)
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp must be ISO 8601") from exc
    if stamp.utcoffset() is None:
        raise ValueError("timestamp requires a timezone")


@dataclass(frozen=True)
class RequestIdentity:
    mission_id: str
    task_id: str
    checkpoint_id: str
    request_id: str

    @classmethod
    def parse(cls, raw):
        if not isinstance(raw, dict):
            raise ValueError("request must be an object")
        values = {name: raw.get(name) for name in cls.__dataclass_fields__}
        for name, value in values.items():
            _text(name, value)
            if len(value) > 256:
                raise ValueError("identifier too long")
        return cls(**values)


@dataclass(frozen=True)
class CNavigationRequest:
    identity: RequestIdentity
    move: MoveRequest
    requested_at: str
    timeout_seconds: float
    map_version: str | None = None
    scene_version: str | None = None

    @classmethod
    def parse(cls, raw, *, expected_frame_id, max_timeout_seconds=300.0):
        identity = RequestIdentity.parse(raw)
        allowed = set(RequestIdentity.__dataclass_fields__) | {
            "kind", "requested_at", "goal", "frame_id", "timeout_seconds", "map_version", "scene_version"}
        if set(raw) - allowed or raw.get("kind") != "navigate":
            raise ValueError("invalid navigation fields or kind")
        _timestamp(raw.get("requested_at"))
        if raw.get("frame_id") != expected_frame_id:
            raise ValueError("frame_mismatch")
        goal = raw.get("goal")
        if not isinstance(goal, dict) or set(goal) != {"x", "y", "yaw"}:
            raise ValueError("goal requires x/y/yaw")
        timeout = raw.get("timeout_seconds")
        _finite("timeout_seconds", timeout)
        if not 0 < timeout <= max_timeout_seconds:
            raise ValueError("timeout outside configured limit")
        for key in ("map_version", "scene_version"):
            if key in raw:
                _text(key, raw[key])
        # B's old task_id field identifies one execution here. The business task
        # remains in identity.task_id; no request_id is passed off as a ROS goal_id.
        move = MoveRequest(identity.request_id, expected_frame_id, goal["x"], goal["y"], goal["yaw"])
        return cls(identity, move, raw["requested_at"], float(timeout),
                   raw.get("map_version"), raw.get("scene_version"))


@dataclass(frozen=True)
class GoalBinding:
    identity: RequestIdentity
    goal_id: str  # In this test-only transport, explicitly synthetic.


@dataclass(frozen=True)
class BackendUpdate:
    identity: RequestIdentity
    feedback: MoveFeedback


class NavigationBackend(Protocol):
    mode: str

    def run(self, request: CNavigationRequest, publish, stop_event) -> None:
        """Publish GoalBinding/BackendUpdate; honour stop_event when possible."""


@dataclass(frozen=True)
class _BackendError:
    code: str


def _worker(backend, request, connection, stop_event):
    try:
        backend.run(request, connection.send, stop_event)
    except Exception:
        # Exception strings may include private configuration. Never forward them.
        try:
            connection.send(_BackendError("backend_exception"))
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        connection.close()


class CPatrolNavigator:
    """Synchronous terminal reply for C; single active request, unique request IDs.

    The wall deadline includes child startup. OS scheduling/owned-process cleanup
    adds small overhead (up to three 0.1s joins), so this is not a hard real-time
    guarantee. A backend's external side effects cannot be undone by killing it.
    """
    mode = MODE

    def __init__(self, backend=None, *, expected_frame_id="interface_test_map", max_timeout_seconds=300.0):
        _text("expected_frame_id", expected_frame_id)
        _finite("max_timeout_seconds", max_timeout_seconds)
        if max_timeout_seconds <= 0:
            raise ValueError("max_timeout_seconds must be positive")
        if backend is not None and getattr(backend, "mode", None) != MODE:
            raise ValueError("only an explicit interface_test backend is allowed")
        self.backend = backend
        self.expected_frame_id = expected_frame_id
        self.max_timeout_seconds = max_timeout_seconds
        self._lock = threading.Lock()
        self._seen = set()
        self._active = None
        self._cancel = None

    def request_cancel(self, request_id):
        """Signal only the matching in-flight request. Not a stop confirmation."""
        with self._lock:
            if self._active != request_id:
                return False
            self._cancel.set()
            return True

    @staticmethod
    def _reply(identity, status, detail, *, goal_id=None, rejected=0,
               cancel_requested=False, cancel_acknowledged=False, action_terminal_received=False):
        return {**asdict(identity), "mode": MODE, "status": status, "detail": detail,
                "bc_contract_version": BC_CONTRACT_VERSION, "goal_id": goal_id,
                "goal_id_source": "SYNTHETIC_FIXTURE" if goal_id else "UNASSIGNED",
                "validation_scope": "INTERFACE_ONLY", "data_source": "SYNTHETIC_FIXTURE",
                "pose_source": "UNKNOWN", "timestamp": datetime.now(timezone.utc).isoformat(),
                "rejected_results": rejected, "cancel_requested": cancel_requested,
                "cancel_acknowledged": cancel_acknowledged,
                "action_terminal_received": action_terminal_received, "stop_confirmed": False}

    def navigate(self, raw):
        # If identity itself is unusable, do not fabricate identifiers in a reply.
        identity = RequestIdentity.parse(raw)
        try:
            request = CNavigationRequest.parse(raw, expected_frame_id=self.expected_frame_id,
                                               max_timeout_seconds=self.max_timeout_seconds)
        except ValueError:
            return self._reply(identity, "failed", "invalid_request")
        deadline = time.monotonic() + request.timeout_seconds
        with self._lock:
            if identity.request_id in self._seen:
                return self._reply(identity, "failed", "duplicate_request_id")
            if self._active is not None:
                return self._reply(identity, "failed", "navigator_busy")
            self._seen.add(identity.request_id)
            if self.backend is None:
                return self._reply(identity, "failed", "backend_unavailable")
            parent = child = None
            try:
                ctx = mp.get_context("spawn")
                stop_event = ctx.Event()
                parent, child = ctx.Pipe(duplex=False)
                process = ctx.Process(target=_worker, args=(self.backend, request, child, stop_event), daemon=True)
            except Exception:
                for handle in (parent, child):
                    if handle is not None:
                        handle.close()
                return self._reply(identity, "failed", "backend_start_or_transport_error")
            self._active, self._cancel = identity.request_id, stop_event
        rejected = 0
        goal_id = None
        def reply(status, detail, **flags):
            return self._reply(identity, status, detail, goal_id=goal_id, rejected=rejected, **flags)
        try:
            process.start()
            child.close()
            while True:
                if time.monotonic() >= deadline:
                    return reply("timeout", "deadline_exceeded", cancel_requested=True)
                if stop_event.is_set():
                    return reply("failed", "cancelled_by_client", cancel_requested=True)
                if not parent.poll(min(0.02, max(0.0, deadline - time.monotonic()))):
                    continue
                try:
                    update = parent.recv()
                except EOFError:
                    return reply("failed", "backend_ended_without_terminal", cancel_requested=True)
                # Never accept a late success, even if it was queued before timeout.
                if time.monotonic() >= deadline:
                    return reply("timeout", "deadline_exceeded", cancel_requested=True)
                if stop_event.is_set():
                    return reply("failed", "cancelled_by_client", cancel_requested=True)
                if isinstance(update, _BackendError):
                    return reply("failed", update.code, cancel_requested=True)
                if not isinstance(update, (BackendUpdate, GoalBinding)):
                    return reply("failed", "backend_protocol_error", cancel_requested=True)
                if update.identity != identity:
                    rejected += 1
                    continue
                if isinstance(update, GoalBinding):
                    if not isinstance(update.goal_id, str) or not update.goal_id.strip() or goal_id is not None:
                        return reply("failed", "invalid_goal_binding", cancel_requested=True)
                    goal_id = update.goal_id
                    continue
                f = update.feedback
                if not isinstance(f, MoveFeedback):
                    return reply("failed", "backend_protocol_error", cancel_requested=True)
                if f.task_id != identity.request_id:
                    rejected += 1
                    continue
                flags = {}
                if isinstance(f, ActionFeedback):
                    if goal_id is None or f.goal_id != goal_id:
                        rejected += 1
                        continue
                    flags = {key: getattr(f, key) for key in (
                        "cancel_requested", "cancel_acknowledged", "action_terminal_received")}
                    if (any(type(v) is not bool for v in flags.values())
                        or (f.cancel_acknowledged and not (f.cancel_requested and f.action_terminal_received))
                        or (f.status == Status.REACHED and (f.cancel_requested or not f.action_terminal_received))):
                        return reply("failed", "backend_protocol_error", cancel_requested=True)
                if not isinstance(f.status, Status) or not isinstance(f.failure_reason, str) or f.pose_source != PoseSource.UNKNOWN:
                    return reply("failed", "backend_protocol_error", cancel_requested=True)
                try:
                    _timestamp(f.timestamp)
                except ValueError:
                    return reply("failed", "backend_protocol_error", cancel_requested=True)
                if f.status == Status.RUNNING:
                    continue
                if f.status == Status.TIMEOUT:
                    flags["cancel_requested"] = True
                status = {Status.REACHED: "arrived", Status.FAILED: "failed", Status.TIMEOUT: "timeout"}[f.status]
                return reply(status, f.failure_reason or ("fixture_reached" if status == "arrived" else "backend_terminal"), **flags)
        except Exception:
            return reply("failed", "backend_start_or_transport_error", cancel_requested=True)
        finally:
            stop_event.set()
            child.close()
            parent.close()
            if process.pid is not None:
                process.join(0.1)
                if process.is_alive():
                    process.terminate()  # Only our offline child, never a ROS/robot process.
                    process.join(0.1)
                if process.is_alive():
                    process.kill()
                    process.join(0.1)
                if not process.is_alive():
                    process.close()
            with self._lock:
                self._active = self._cancel = None
