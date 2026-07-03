"""Tests for the portrait->chart coordinate transform used to migrate the
airport ground coordinates onto the cropped, 90-deg-CW-rotated diagram."""

from __future__ import annotations

import math

import pytest

from server.chart_geometry import NEATLINE, PAGE_H, PAGE_W, portrait_to_chart


def _neatline_norm(px: float, py: float) -> tuple[float, float]:
    """A portrait PDF point expressed in full-page normalized coords."""
    return px / PAGE_W, py / PAGE_H


def test_neatline_corners_map_to_unit_corners():
    x0, y0, x1, y1 = NEATLINE
    # 90 CW: portrait top-left -> chart top-right, etc.
    tl = portrait_to_chart(*_neatline_norm(x0, y0))
    tr = portrait_to_chart(*_neatline_norm(x1, y0))
    bl = portrait_to_chart(*_neatline_norm(x0, y1))
    br = portrait_to_chart(*_neatline_norm(x1, y1))
    assert tl == pytest.approx((1.0, 0.0), abs=1e-9)
    assert tr == pytest.approx((1.0, 1.0), abs=1e-9)
    assert bl == pytest.approx((0.0, 0.0), abs=1e-9)
    assert br == pytest.approx((0.0, 1.0), abs=1e-9)


def test_neatline_center_maps_to_center():
    x0, y0, x1, y1 = NEATLINE
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    assert portrait_to_chart(*_neatline_norm(cx, cy)) == pytest.approx((0.5, 0.5))


def test_rotation_is_isometric_up_to_aspect():
    # Two points offset purely in portrait-y should differ purely in chart-x
    # (a 90-degree rotation maps the y axis onto the x axis).
    a = portrait_to_chart(*_neatline_norm(200.0, 100.0))
    b = portrait_to_chart(*_neatline_norm(200.0, 300.0))
    assert a[1] == pytest.approx(b[1])  # same chart-y
    assert a[0] != b[0]


def test_runway_25_threshold_is_east_of_its_rollout():
    # rwy25_thr (0.469, 0.253) sits at the runway-25 (east) end; the rollout
    # point rwy25_exit (0.480, 0.535) is further west. After rotation, "east"
    # is larger chart-x.
    thr = portrait_to_chart(0.469, 0.253)
    exit_ = portrait_to_chart(0.480, 0.535)
    assert thr[0] > exit_[0]


def test_runway_7_25_becomes_horizontal():
    # The 7-25 runway runs near-vertical on the portrait page; after a 90-deg
    # rotation the threshold points should share nearly the same chart-y.
    thr = portrait_to_chart(0.469, 0.253)  # 25 end
    rollout = portrait_to_chart(0.480, 0.535)
    assert abs(thr[1] - rollout[1]) < 0.05


def test_outputs_stay_in_unit_square_for_airfield_nodes():
    from server.airport import NODES  # migrated values, must remain normalized
    for name, (x, y) in NODES.items():
        assert 0.0 <= x <= 1.0, name
        assert 0.0 <= y <= 1.0, name
