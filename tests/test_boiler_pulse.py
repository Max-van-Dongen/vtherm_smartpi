"""Coordinated pulses must preserve a room's SmartPI demand and learned model."""

import time
from unittest.mock import patch

import pytest

from custom_components.vtherm_smartpi.handler import SmartPIHandler
from custom_components.vtherm_smartpi.hvac_mode import VThermHvacMode_HEAT
from custom_components.vtherm_smartpi.smartpi.const import AB_MIN_SAMPLES_B
from custom_components.vtherm_smartpi.smartpi.valve_curve import ValveCurveParams
from fakes.fake_cycle_scheduler import FakeReceiptCycleScheduler

from .test_boiler_flow import algorithm, context


@pytest.fixture
def stable_room(hass):
    room = algorithm(hass)
    room.est.learn_ok_count_a = 2
    room.est.b_meas_hist.extend([room.est.b] * AB_MIN_SAMPLES_B)
    room._set_linear_output(0.1)
    return room


def pulse(opening, feedback, *, active=True, **overrides):
    return {
        **context(flow=35, reference=55, allowed=True),
        "pulse_opening": opening,
        "pulse_valve_feedback": feedback,
        "boiler_active": active,
        **overrides,
    }


def test_raw_demand_survives_charge_coast_and_release(stable_room):
    room = stable_room
    assert room.boiler_heat_request(0.9)["pulse_eligible"]
    baseline = room.est.save_state()
    for opening in (1, 0):
        room.set_boiler_context(pulse(opening, opening, active=bool(opening)), 20, VThermHvacMode_HEAT)
        assert room.on_percent == opening
        assert room.boiler_heat_request(0.9)["demand"] == pytest.approx(0.1)
        with patch.object(room.learn_win, "update") as observe:
            room.update_learning(5, 20, 7, 0.5, hvac_mode=VThermHvacMode_HEAT)
        observe.assert_not_called()
    room.set_boiler_context(context(flow=55, reference=55, allowed=True), 20, VThermHvacMode_HEAT)
    assert room.on_percent == pytest.approx(0.1)
    assert room.est.save_state() == baseline
    assert not room._flow_learning_blocked


@pytest.mark.asyncio
async def test_target_jump_recovery_opens_valve_during_guard_kick(stable_room, fake_handler_runtime):
    thermostat = fake_handler_runtime
    thermostat.prop_algorithm = stable_room
    thermostat.current_temperature = thermostat.target_temperature = 20.5
    thermostat.cycle_scheduler = FakeReceiptCycleScheduler()
    thermostat.cycle_scheduler.is_valve_mode = True
    handler = SmartPIHandler(thermostat)
    handler.on_scheduler_ready(thermostat.cycle_scheduler)
    await handler.control_heating()

    # The previous tick was near the old target when the user raised it.
    stable_room.deadband_mgr.in_near_band = True
    thermostat.target_temperature = 30.0
    await handler.control_heating(force=True)
    request = stable_room.boiler_heat_request(0.9)
    assert stable_room.guards.guard_kick_active
    assert request["recovery_eligible"] is True
    assert request["pulse_eligible"] is False
    assert request["reference_required"] is False

    thermostat.boiler_flow_context = pulse(1, 0, active=False, pulse_recovery=True)
    await handler.control_heating()
    start = thermostat.cycle_scheduler.start_cycle.await_args
    assert start.args == (VThermHvacMode_HEAT, 1.0, True)
    assert "request_id" not in start.kwargs
    assert stable_room.pulse_opening == 1.0
    assert stable_room.linear_committed_on_percent == 0.0


@pytest.mark.parametrize(
    "next_directive",
    [
        {"opening": 0, "pulse_recovery": True},
        {"opening": 1},
        {"opening": 1, "pulse_recovery": False},
        {"opening": 1, "pulse_recovery": 1},
        {"opening": True, "pulse_recovery": True},
        None,
    ],
)
def test_only_explicit_full_recovery_overrides_guard_kick(stable_room, next_directive):
    room = stable_room
    room.guards._guard_kick_active = True
    room.set_boiler_context(pulse(1, 0, pulse_recovery=True), 20, VThermHvacMode_HEAT)
    assert room.pulse_opening == 1.0
    assert room.on_percent == 1.0
    assert room.boiler_heat_request(0.9)["demand"] == pytest.approx(0.1)

    message = pulse(feedback=0, **next_directive) if next_directive is not None else None
    room.set_boiler_context(message, 20, VThermHvacMode_HEAT)
    assert room.pulse_opening is None
    assert room.on_percent == room.calculated_on_percent
    assert 0 < room.on_percent < 1
    assert room.boiler_heat_request(0.9)["demand"] == pytest.approx(0.1)


@pytest.mark.parametrize(
    ("feedback", "active", "expected"),
    [(1.0, True, 1.0), (0.5, True, 0.5), (0.0, True, 0), (None, True, 0), (1.0, False, 0)],
)
def test_twin_uses_reported_delivery_during_pulses(stable_room, feedback, active, expected):
    room = stable_room
    room.set_boiler_context(pulse(1, feedback, active=active), 20, VThermHvacMode_HEAT)
    # A scheduler receipt only means that it applied the command. Delivery must
    # wait for valve feedback, water temperature, and the boiler heat request.
    room._set_committed_actuator_output(1.0)
    with patch.object(room.twin, "update_with_eta", return_value={}) as update:
        room._update_twin_diagnostics(20, 7, 20.5, VThermHvacMode_HEAT)
    assert update.call_args.kwargs["on_percent"] == pytest.approx(expected * (15 / 35) ** 1.3)


def test_feedback_refresh_updates_committed_heat_without_a_new_receipt(stable_room):
    room = stable_room
    room.set_boiler_context(pulse(1, None), 20, VThermHvacMode_HEAT)
    room._set_committed_actuator_output(1.0)
    diag = room.get_published_diagnostics()["power"]["boiler_flow"]
    assert diag["pulse_opening_percent"] == 100
    assert diag["reference_demand_percent"] == 10
    assert diag["estimated_pulse_heat_percent"] is None
    assert room.linear_committed_on_percent == 0

    room.set_boiler_context(pulse(1, 0.5), 20, VThermHvacMode_HEAT)
    delivered = 0.5 * (15 / 35) ** 1.3
    assert room.committed_on_percent == 1.0
    assert room.linear_committed_on_percent == pytest.approx(delivered)
    assert room.u_prev == pytest.approx(delivered)
    diag = room.get_published_diagnostics()["power"]
    assert diag["boiler_flow"]["estimated_pulse_heat_percent"] == round(100 * delivered, 1)
    assert diag["linear_current_cycle_percent"] == round(100 * delivered, 1)

    room.set_boiler_context(pulse(1, 0.5, active=False), 20, VThermHvacMode_HEAT)
    assert room.linear_committed_on_percent == 0
    assert room.committed_on_percent == 1


@pytest.mark.parametrize("temperature", [20, 18])
def test_open_valve_with_cold_water_delivers_zero(stable_room, temperature):
    room = stable_room
    room.set_boiler_context(pulse(1, 1, flow_temperature=temperature), 20, VThermHvacMode_HEAT)
    room._set_committed_actuator_output(1)
    assert room.pulse_opening == 1
    assert room.pulse_estimated_delivery == 0
    assert room.linear_committed_on_percent == 0


@pytest.mark.parametrize("invalid", [{"pulse_opening": 2}, {"pulse_opening": True}, {"boiler_active": None}])
def test_malformed_directive_releases_valve(stable_room, invalid):
    room = stable_room
    message = pulse(1, 1)
    room.set_boiler_context(message, 20, VThermHvacMode_HEAT)
    assert room.pulse_opening == 1
    if invalid.get("boiler_active", True) is None:
        del message["boiler_active"]
    else:
        message.update(invalid)
    room.set_boiler_context(message, 20, VThermHvacMode_HEAT)
    assert room.pulse_opening is None
    assert room.on_percent < 1


@pytest.mark.parametrize(
    "fault",
    ["stale", "bootstrap", "safety", "calibration", "limited_valve", "guard_cut", "guard_kick", "valve_curve", "non_valve"],
)
def test_lost_eligibility_releases_full_valve_command(stable_room, fault):
    room = stable_room
    message = pulse(1, 1)
    room.set_boiler_context(message, 20, VThermHvacMode_HEAT)
    assert room.on_percent == 1
    if fault == "stale":
        message["observed_at"] = time.monotonic() - 240
    elif fault == "bootstrap":
        room.est.b_meas_hist.clear()
    elif fault == "safety":
        room.vt_safety_override = True
    elif fault == "calibration":
        room.force_calibration()
    elif fault == "guard_cut":
        room.guards._guard_cut_active = True
    elif fault == "guard_kick":
        room.guards._guard_kick_active = True
    elif fault == "valve_curve":
        room.configure_valve_linearization(True, ValveCurveParams(7, 80, 15, 70), valve_mode=True)
    elif fault == "non_valve":
        room.configure_valve_linearization(False, valve_mode=False)
    else:
        room._max_on_percent = 0.5
    room.set_boiler_context(message, 20, VThermHvacMode_HEAT)
    assert room.on_percent < 1
    if fault != "stale":
        assert not room.boiler_heat_request(0.9)["pulse_eligible"]

    message["pulse_recovery"] = True
    room.set_boiler_context(message, 20, VThermHvacMode_HEAT)
    assert room.pulse_opening == (1.0 if fault == "guard_kick" else None)
    if fault != "stale":
        assert room.boiler_heat_request(0.9)["recovery_eligible"] is (fault == "guard_kick")


@pytest.mark.parametrize("recovery", [False, True])
def test_guard_changes_between_equal_full_open_commands(stable_room, recovery):
    room = stable_room
    room.set_boiler_context(pulse(1, 1, pulse_recovery=not recovery), 20, VThermHvacMode_HEAT)
    room.set_boiler_context(pulse(1, 1, pulse_recovery=recovery), 20, VThermHvacMode_HEAT)
    room.guards._guard_kick_active = True
    assert room.pulse_opening == (1.0 if recovery else None)
    room.guards._guard_cut_active = True
    assert room.pulse_opening is None
    assert room.on_percent < 1


def test_deliberate_coast_holds_integral_across_ticks(stable_room):
    room = stable_room
    room.est.a, room.est.b = 0.015, 0.0002
    with patch("custom_components.vtherm_smartpi.algo.time.monotonic") as clock:
        clock.return_value = 1200
        room.calculate(20.5, 20.1, 7, hvac_mode=VThermHvacMode_HEAT)
        room.ctl.integral = 0.5
        room.set_boiler_context(pulse(0, 0, active=False), 20.1, VThermHvacMode_HEAT)
        for now in (1260, 1320):
            clock.return_value = now
            room.calculate(20.5, 20.1, 7, hvac_mode=VThermHvacMode_HEAT)
            assert room.on_percent == 0
            assert room.ctl.integral == pytest.approx(0.5)
            assert room.boiler_heat_request(0.9)["demand"] > 0
