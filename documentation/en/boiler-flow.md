# Coordinated boiler flow support

This custom SmartPI fork works with the matching
[VTherm fork](https://github.com/Max-van-Dongen/versatile_thermostat).

**[Installation, configuration, control math, diagnostics and rollback](https://github.com/Max-van-Dongen/versatile_thermostat/blob/main/documentation/en/coordinated-boiler-flow.md)**

SmartPI continues to calculate room heat demand at the original calibration
water temperature. A temperature-dependent multiplier translates that demand
into a wider valve opening at lower water temperatures. Applied-valve feedback
uses the inverse conversion, including the existing nonlinear valve curve.
The available heat limit is also supplied to the PI anti-windup logic.

The learned A/B values are preserved. A/B learning, dead-time identification,
feed-forward trim and automatic stagnation recalibration pause during modulation
or invalid coordinator context. They resume at a settled reference temperature.
The user's learning-enabled setting is unchanged.

Install both forks and enable the feature in VTherm's central boiler settings.
Without that context, SmartPI retains its existing behavior. Direct valve control
is required; switch-based SmartPI zones request the reference temperature.

When coordinated heat pulses are enabled in VTherm, a stable SmartPI zone
continues to report its room's heat demand at the calibration water temperature.
VTherm can command a 100% valve opening for a pulse and 0% for a coast. SmartPI
holds its integral and pauses thermal learning while VTherm controls the valve.
Calibration, valve limits and local temperature guards take precedence.

Under `power.boiler_flow`, `reference_demand_percent` is the SmartPI demand
and `pulse_opening_percent` is VTherm's valve command. A null valve command
means SmartPI has returned to ordinary control. During a heat call,
`estimated_pulse_heat_percent` uses the reported valve opening and measured
water temperature to estimate delivery relative to full reference output.
It is null when valve feedback is missing during a heat call and zero while
the heat call is off.

The same diagnostics include the flow compensation ratio and the reason
learning is paused. See `tests/test_boiler_flow.py` and
`tests/test_boiler_pulse.py` for heat-unit and learning invariants. The matching
VTherm repository includes paired multi-room tests. This implementation has
automated tests but has not been commissioned on your physical heating system.
