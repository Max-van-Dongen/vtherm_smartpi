# Coordinated boiler flow support

This custom SmartPI fork works with the matching
[VTherm fork](https://github.com/Max-van-Dongen/versatile_thermostat).

**[Installation, configuration, control math, diagnostics and rollback](https://github.com/Max-van-Dongen/versatile_thermostat/blob/main/documentation/en/coordinated-boiler-flow.md)**

Install both forks and enable the feature in VTherm's central boiler settings.
Each participating room needs direct valve control.

## Ordinary coordinated flow

SmartPI continues to calculate room heat demand at the original calibration
water temperature. A temperature-dependent multiplier translates that demand
into a wider valve opening at lower water temperatures. Applied-valve feedback
uses the inverse conversion, including the existing nonlinear valve curve.
The available heat limit is also supplied to the PI anti-windup logic.

The learned A/B values are preserved. A/B learning, dead-time identification,
feed-forward trim and automatic stagnation recalibration pause during modulation
or invalid coordinator context. They resume at a settled reference temperature.
The user's learning-enabled setting is unchanged.

## Full-open heat pulses

In pulse mode the room's temperature band determines when it calls for heat.
VTherm opens a participating valve to 100%, waits for full-open feedback and
requests the configured maximum water temperature for the pulse. It closes
the valve to 0% for the coast. SmartPI continues to calculate room demand
in reference heat units so the coordinator can estimate when to stop heating
and let the radiator's stored heat carry the room toward its target.

SmartPI holds its integral and pauses thermal learning while VTherm controls
the valve. Initial hysteresis and calibration stay under SmartPI's own control.
When a cold room needs to recover, VTherm can request a full opening even
if SmartPI's low-temperature guard has just called for heat. While that guard
is active, SmartPI declines coordinated commands to close the valve.
Calibration, safety mode, the high-temperature cut and valve limits retain
priority. The flow diagnostic reports `boiler_recovery` during an accepted
full-open recovery.

## Diagnostics

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
