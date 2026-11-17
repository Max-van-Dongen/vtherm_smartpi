"""Temperature compensation must preserve reference heat units and learned data."""

import time
from unittest.mock import Mock, patch

import pytest

from custom_components.vtherm_smartpi.algo import SmartPI
from custom_components.vtherm_smartpi.hvac_mode import (
    VThermHvacMode_HEAT,
    VThermHvacMode_COOL,
)
from custom_components.vtherm_smartpi.smartpi.boiler_flow import (
    FlowValveCurve,
    capacity_ratio,
)
from custom_components.vtherm_smartpi.smartpi.valve_curve import (
    IdentityValveCurve,
    TwoSlopeValveCurve,
)


def context(flow=35, reference=50, allowed=False):
    return dict(
        version=1,
        observed_at=time.monotonic(),
        flow_temperature=flow,
        reference_temperature=reference,
        exponent=1.3,
        learning_allowed=allowed,
        reason="test",
    )


def algorithm(hass, linearization=False):
    algo = SmartPI(hass, 5, 0, 0, "Bedroom", enable_valve_linearization=linearization)
    algo.configure_valve_linearization(linearization, valve_mode=True)
    return algo


@pytest.mark.parametrize("base", [IdentityValveCurve(), TwoSlopeValveCurve()])
def test_heat_is_preserved_when_valves_open_further_at_lower_flow(base):
    scale = capacity_ratio(35, 50, 20, 1.3)
    curve = FlowValveCurve(base, scale)
    for heat in (0.05, 0.1, 0.2, 0.35):
        opening = curve.apply(heat)
        assert opening > base.apply(heat)
        assert base.invert(opening) * scale == pytest.approx(heat)
        assert curve.invert(opening) == pytest.approx(heat)
    assert curve.apply(0) == 0
    assert curve.apply(1) == 1
    assert curve.invert(1) == pytest.approx(scale)


def test_example_ten_percent_at_fifty_becomes_twenty_five_percent_at_thirty_five():
    curve = FlowValveCurve(IdentityValveCurve(), capacity_ratio(35, 50, 20, 1.3))
    assert curve.apply(0.1) == pytest.approx(0.2462288827)


@pytest.mark.parametrize("flow", [float("nan"), float("inf")])
def test_non_finite_context_rejected(flow):
    with pytest.raises(ValueError):
        capacity_ratio(flow, 50, 20, 1.3)


def test_zero_temperature_head_saturates_without_dividing_by_zero():
    assert capacity_ratio(18, 50, 20, 1.3) == 0.05


def test_live_algorithm_compensates_receipts_and_preserves_calibration(hass):
    algo = algorithm(hass)
    algo._set_linear_output(0.1)
    algo._set_committed_actuator_output(0.1)
    before = algo.est.save_state()
    algo.set_boiler_context(context(), 20, VThermHvacMode_HEAT)
    assert algo.on_percent == pytest.approx(0.2462288827)
    assert algo._actuator_committed_on_percent == 0.1
    assert algo.linear_committed_on_percent == pytest.approx(0.1 * 0.5**1.3)
    algo._set_committed_actuator_output(algo.on_percent)
    assert algo.linear_committed_on_percent == pytest.approx(0.1)
    assert algo.est.save_state() == before
    assert algo._linear_max_on() == pytest.approx(0.5**1.3)


def test_modulation_freezes_model_and_feedforward_trim(hass):
    algo = algorithm(hass)
    algo.set_boiler_context(context(), 20, VThermHvacMode_HEAT)
    with patch.object(algo.learn_win, "update") as update:
        algo.update_learning(1, 20, 5, 0.1)
        update.assert_not_called()
    result = Mock()
    assert not algo.fftrim_coord.apply_observer_result(result, count_window=True)
    assert algo.fftrim_coord.last_reject_reason == "boiler_flow"
    algo.set_boiler_context(context(50, allowed=True), 20, VThermHvacMode_HEAT)
    assert not algo._flow_learning_blocked
    assert (
        algo.learning_enabled
    )  # The user's persisted learning preference is untouched.


def test_expired_or_invalid_context_holds_last_mapping_and_freezes_learning(hass):
    algo = algorithm(hass)
    algo.set_boiler_context(context(), 20, VThermHvacMode_HEAT)
    scale = algo.valve_curve.scale
    for invalid in [
        dict(context(), observed_at=0),
        dict(context(), flow_temperature=None),
        dict(context(), flow_temperature=float("nan")),
    ]:
        algo.set_boiler_context(invalid, 20, VThermHvacMode_HEAT)
        assert algo.valve_curve.scale == scale
        assert algo._flow_learning_blocked


def test_disabled_feature_and_cooling_keep_existing_mapping(hass):
    algo = algorithm(hass, True)
    algo._set_linear_output(0.4)
    original = algo.on_percent
    algo.set_boiler_context(context(), 20, VThermHvacMode_COOL)
    assert algo.on_percent == original
    algo.set_boiler_context(context(), 20, VThermHvacMode_HEAT)
    assert algo.on_percent > original
    algo.set_boiler_context(None, 20, VThermHvacMode_HEAT)
    assert algo.on_percent == original


def test_heat_request_uses_uncompensated_curve_and_respects_actuator_cap(hass):
    algo = algorithm(hass, True)
    algo._set_linear_output(0.3)
    before = algo.boiler_heat_request(0.7)
    algo.set_boiler_context(context(), 20, VThermHvacMode_HEAT)
    assert algo.boiler_heat_request(0.7) == before
    assert before["reference_required"]  # Bootstrap stays at reference flow.
    algo._max_on_percent = 0.12
    assert algo.boiler_heat_request(0.7)["target_capacity"] == pytest.approx(0.5)
