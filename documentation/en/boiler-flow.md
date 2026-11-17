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

The added diagnostics are under `power.boiler_flow`: active state, capacity
ratio, reference demand, learning pause and reason. See
`tests/test_boiler_flow.py` for heat-unit and learning invariants. The matching
VTherm repository includes paired multi-room tests. This implementation has
automated tests but has not been commissioned on your physical heating system.
