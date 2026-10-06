"""Hardware fixtures shared by the brewing tests. TEST FIXTURE ONLY.

K6 is a Kingrinder K6 (16 um per click, lower is finer; docs/science.md#k6-caps)
with the dial limited to 0-90 clicks. Test files that use the full 0-180 range
keep their own local copy and say so.
"""

from __future__ import annotations

from core.brewing import GrinderCaps, MachineCaps

K6 = GrinderCaps(
    min_clicks=0.0,
    max_clicks=90.0,
    step_clicks=1.0,
    um_per_click=16.0,
    finer_direction="lower_is_finer",
)
MACHINE_18G = MachineCaps(basket_size_g=18.0)
