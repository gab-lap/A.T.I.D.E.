"""Optional operating context for the A.T.I.D.E. diagnostics agent. DRAFT, untested with ROS.

The agent normally sees only the fault severity. This module defines a small, validated "fault context"
(nearest obstacle, speed, distance to goal, how long the fault has lasted) that can be added to the prompt, so
the decision can depend on the situation and not only on the severity word. Pure Python, no ROS.

Safety note: the context arrives on a ROS topic and ends up in an LLM prompt, so ONLY validated numbers are
ever formatted into the prompt. Free text (including the optional "scenario" label) is never included.
"""
import json
import math
from dataclasses import dataclass, fields
from typing import Optional, Sequence

# field -> (min, max); values outside are clamped, NaN/inf/non-numbers are dropped
LIMITS = {
    "nearest_obstacle_m": (0.0, 30.0),
    "sensor_range_m": (0.0, 100.0),
    "obstacle_data_age_s": (0.0, 3600.0),
    "speed_mps": (0.0, 2.0),
    "distance_to_goal_m": (0.0, 1000.0),
    "fault_duration_s": (0.0, 3600.0),
}

CONTEXT_INSTRUCTION = "Use this operating context when choosing the action."


@dataclass(frozen=True)
class FaultContext:
    nearest_obstacle_m: Optional[float] = None
    sensor_range_m: Optional[float] = None
    obstacle_data_age_s: Optional[float] = None
    speed_mps: Optional[float] = None
    distance_to_goal_m: Optional[float] = None
    fault_duration_s: Optional[float] = None

    def is_empty(self) -> bool:
        return all(getattr(self, f.name) is None for f in fields(self))


def _clean(value, lo, hi):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = float(value)
    if math.isnan(v) or math.isinf(v):
        return None
    return max(lo, min(hi, v))


def parse_context(text) -> Optional[FaultContext]:
    """Parse a JSON string. Returns None for invalid JSON, a non-object, or when no valid field is present."""
    try:
        raw = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    kwargs = {}
    for name, (lo, hi) in LIMITS.items():
        if name in raw:
            v = _clean(raw[name], lo, hi)
            if v is not None:
                kwargs[name] = v
    ctx = FaultContext(**kwargs)
    return None if ctx.is_empty() else ctx


def format_context_block(ctx: Optional[FaultContext], with_instruction: bool = True) -> str:
    """Prompt text for the context, or "" when there is nothing to say."""
    if ctx is None or ctx.is_empty():
        return ""
    lines = ["Operating context (measured by the robot; the LiDAR data may now be unreliable):"]
    if ctx.nearest_obstacle_m is not None:
        age = ""
        if ctx.obstacle_data_age_s is not None and ctx.obstacle_data_age_s > 0.5:
            age = f" (this reading is {ctx.obstacle_data_age_s:.0f} s old)"
        if ctx.sensor_range_m is not None and ctx.nearest_obstacle_m >= ctx.sensor_range_m - 0.05:
            lines.append(f"- No obstacle was detected ahead within the sensor range of {ctx.sensor_range_m:.1f} m "
                         f"when the LiDAR was last reliable{age}")
        else:
            lines.append(f"- Nearest obstacle ahead when the LiDAR was last reliable: {ctx.nearest_obstacle_m:.1f} m{age}")
    if ctx.speed_mps is not None:
        lines.append(f"- Current speed: {ctx.speed_mps:.2f} m/s")
    if ctx.distance_to_goal_m is not None:
        lines.append(f"- Distance to the navigation goal: {ctx.distance_to_goal_m:.1f} m")
    if ctx.fault_duration_s is not None:
        lines.append(f"- The fault has lasted: {ctx.fault_duration_s:.0f} s")
    if with_instruction:
        lines.append(CONTEXT_INSTRUCTION)
    return "\n".join(lines)


def front_min_range(ranges: Sequence[float], angle_min: float, angle_increment: float,
                    range_min: float, range_max: float, half_width_deg: float = 30.0) -> Optional[float]:
    """Smallest valid range within +-half_width_deg of straight ahead (0 rad), or None if there is none."""
    half = math.radians(half_width_deg)
    best = None
    for i, r in enumerate(ranges):
        angle = angle_min + i * angle_increment
        angle = (angle + math.pi) % (2.0 * math.pi) - math.pi  # wrap to [-pi, pi)
        if abs(angle) > half:
            continue
        if r is None or math.isnan(r) or math.isinf(r) or r < range_min or r > range_max:
            continue
        if best is None or r < best:
            best = r
    return best


class ContextTracker:
    """Keeps the last reliable obstacle distance and the fault timing; builds the context dict to publish."""

    def __init__(self, goal=None, half_width_deg: float = 15.0):
        self.goal = goal                  # (x, y) in the odom/map frame, or None
        self.half_width_deg = half_width_deg
        self.severity = "none"
        self._fault_start = None
        self._front = None                # last reliable front distance
        self._front_time = None
        self._range_max = None
        self._speed = None
        self._pose = None

    def on_scan(self, now, ranges, angle_min, angle_increment, range_min, range_max):
        if self.severity != "none":
            return  # only trust scans while there is no fault
        if not len(ranges) or range_max is None or math.isnan(range_max) or math.isinf(range_max):
            return  # malformed scan: learn nothing
        d = front_min_range(ranges, angle_min, angle_increment, range_min, range_max, self.half_width_deg)
        if d is None:
            d = range_max  # a healthy scan with no return ahead means: clear up to the sensor range
        self._front, self._front_time, self._range_max = d, now, range_max

    def on_odom(self, x, y, vx, vy=0.0):
        self._pose = (x, y)
        self._speed = math.hypot(vx, vy)

    def on_severity(self, now, severity: str):
        sev = (severity or "none").strip().lower()
        if sev != "none" and self.severity == "none":
            self._fault_start = now
        elif sev == "none":
            self._fault_start = None
        self.severity = sev

    def snapshot(self, now) -> dict:
        out = {}
        if self._front is not None:
            out["nearest_obstacle_m"] = round(self._front, 2)
            out["sensor_range_m"] = round(self._range_max, 2)
            out["obstacle_data_age_s"] = 0.0 if self.severity == "none" else round(max(0.0, now - self._front_time), 1)
        if self._speed is not None:
            out["speed_mps"] = round(self._speed, 3)
        if self._pose is not None and self.goal is not None:
            out["distance_to_goal_m"] = round(math.hypot(self.goal[0] - self._pose[0], self.goal[1] - self._pose[1]), 2)
        out["fault_duration_s"] = 0.0 if self._fault_start is None else round(max(0.0, now - self._fault_start), 1)
        return out