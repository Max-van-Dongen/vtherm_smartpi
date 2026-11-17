"""Reference-temperature heat units at the valve actuator boundary.

This is an approximate radiator emission model, not a measurement of flow or
watts. Keep thermal identification at the original calibration temperature.
"""

from math import isfinite

from .valve_curve import clamp_unit


MIN_COMMAND_CAPACITY = 0.05


def emission_ratio(
    flow: float, reference: float, room: float, exponent: float
) -> float:
    """Approximate relative heat capacity using the supply-to-room temperature head."""
    if not all(isfinite(v) for v in (flow, reference, room, exponent)):
        raise ValueError("Non-finite boiler context")
    if reference <= room + 1 or not 1 <= exponent <= 2:
        raise ValueError("Invalid boiler reference or exponent")
    # The controller never selects a flow above its reference. A hot overshoot
    # uses scale=1 conservatively rather than expanding SmartPI's 0..1 model.
    return min(1.0, (max(0.0, flow - room) / (reference - room)) ** exponent)


def capacity_ratio(flow: float, reference: float, room: float, exponent: float) -> float:
    """Keep the command mapping invertible even when the radiator is cold."""
    return max(MIN_COMMAND_CAPACITY, emission_ratio(flow, reference, room, exponent))


class FlowValveCurve:
    """Compose the existing valve characteristic with a heat-capacity multiplier."""

    def __init__(self, base, scale=1.0):
        self.base = base
        self.scale = scale

    @property
    def params(self):
        return self.base.params

    def apply(self, demand_unit):
        return self.base.apply(clamp_unit(demand_unit / self.scale))

    def invert(self, actuator_unit):
        return clamp_unit(self.base.invert(actuator_unit) * self.scale)
