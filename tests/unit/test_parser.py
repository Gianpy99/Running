"""Unit tests: parser + geo conversions (PRD §19)."""

from __future__ import annotations

from app.ingestion.geo import haversine_m
from app.ingestion.tcx_parser import parse_tcx

MINIMAL_TCX = """<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
  <Activities><Activity Sport="Running">
    <Id>2026-08-29T07:00:00.000+00:00</Id>
    <Lap StartTime="2026-08-29T07:00:00.000+00:00">
      <TotalTimeSeconds>4.0</TotalTimeSeconds>
      <DistanceMeters>10.0</DistanceMeters>
      <TriggerMethod>Manual</TriggerMethod>
      <Track>
        <Trackpoint><Time>2026-08-29T07:00:00.000+00:00</Time>
          <DistanceMeters>0.0</DistanceMeters><HeartRateBpm><Value>100</Value></HeartRateBpm></Trackpoint>
        <Trackpoint><Time>2026-08-29T07:00:01.000+00:00</Time>
          <DistanceMeters>3.0</DistanceMeters><HeartRateBpm><Value>110</Value></HeartRateBpm></Trackpoint>
        <Trackpoint><Time>2026-08-29T07:00:02.000+00:00</Time>
          <DistanceMeters>6.0</DistanceMeters><HeartRateBpm><Value>115</Value></HeartRateBpm></Trackpoint>
        <Trackpoint><Time>2026-08-29T07:00:03.000+00:00</Time>
          <DistanceMeters>10.0</DistanceMeters><HeartRateBpm><Value>118</Value></HeartRateBpm></Trackpoint>
      </Track>
    </Lap>
  </Activity></Activities>
</TrainingCenterDatabase>"""


def test_parse_minimal_tcx():
    w = parse_tcx(MINIMAL_TCX, source_file="minimal.tcx")
    assert len(w.trackpoints) == 4
    assert w.distance_m == 10.0
    assert w.duration_s == 4.0
    assert w.source_file == "minimal.tcx"
    # Speed derived from distance/time deltas when not present in the file.
    assert w.trackpoints[1].speed_mps == 3.0
    assert w.trackpoints[0].elapsed_s == 0.0
    assert w.trackpoints[-1].elapsed_s == 3.0


def test_haversine_known_distance():
    # ~111.19 m per 0.001 deg latitude at the equator.
    d = haversine_m(0.0, 0.0, 0.001, 0.0)
    assert 110 < d < 112


def test_pace_property():
    w = parse_tcx(MINIMAL_TCX)
    tp = w.trackpoints[1]
    assert tp.pace_s_per_km is not None
    assert abs(tp.pace_s_per_km - 1000.0 / 3.0) < 0.01
