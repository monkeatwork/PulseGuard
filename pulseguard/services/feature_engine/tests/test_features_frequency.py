from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pulseguard_common.features_frequency import (
    burst_duration_seconds,
    device_novelty,
    geo_novelty,
    impossible_travel,
    inter_prompt_mean,
    inter_prompt_std,
    off_hours_flag,
    prompts_per_window,
)

T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _ts_list(offsets: list[float]) -> list[datetime]:
    return [T0 + timedelta(seconds=o) for o in offsets]


def test_prompts_per_window_counts_within_trailing_window():
    prompts = _ts_list([0, 100, 400, 700])
    as_of = T0 + timedelta(seconds=700)
    assert prompts_per_window(prompts, as_of, window_seconds=600) == 3  # 100,400,700 within 600s of 700


def test_prompts_per_window_excludes_future_events():
    prompts = _ts_list([0, 1000])
    as_of = T0
    assert prompts_per_window(prompts, as_of, window_seconds=600) == 1


def test_inter_prompt_mean_and_std():
    prompts = _ts_list([0, 10, 30])  # gaps: 10, 20
    assert inter_prompt_mean(prompts) == 15.0
    assert inter_prompt_std(prompts) > 0


def test_inter_prompt_mean_none_for_single_prompt():
    assert inter_prompt_mean(_ts_list([0])) is None
    assert inter_prompt_std(_ts_list([0])) is None


def test_burst_duration_seconds():
    prompts = _ts_list([0, 30, 90])
    assert burst_duration_seconds(prompts) == 90.0
    assert burst_duration_seconds([]) == 0.0


def test_off_hours_flag():
    assert off_hours_flag(datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc)) is True
    assert off_hours_flag(datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc)) is False


def test_geo_novelty():
    known = {"US", "GB"}
    assert geo_novelty("FR", known) is True
    assert geo_novelty("US", known) is False
    assert geo_novelty(None, known) is False


def test_device_novelty():
    known = {"device-a"}
    assert device_novelty("device-b", known) is True
    assert device_novelty("device-a", known) is False


def test_impossible_travel_with_coordinates_flags_faster_than_flight():
    # New York to London (~5570km) in 10 minutes -> ~33,000 km/h, impossible
    prev_ts = T0
    curr_ts = T0 + timedelta(minutes=10)
    assert impossible_travel(prev_ts, 40.7128, -74.0060, "US", curr_ts, 51.5074, -0.1278, "GB") is True


def test_impossible_travel_with_coordinates_allows_plausible_flight():
    prev_ts = T0
    curr_ts = T0 + timedelta(hours=8)  # 8-hour flight, plenty of time
    assert impossible_travel(prev_ts, 40.7128, -74.0060, "US", curr_ts, 51.5074, -0.1278, "GB") is False


def test_impossible_travel_fallback_without_coordinates():
    prev_ts = T0
    curr_ts = T0 + timedelta(minutes=30)
    assert impossible_travel(prev_ts, None, None, "US", curr_ts, None, None, "AU") is True
    curr_ts_far = T0 + timedelta(hours=5)
    assert impossible_travel(prev_ts, None, None, "US", curr_ts_far, None, None, "AU") is False


def test_impossible_travel_same_country_never_flags():
    prev_ts = T0
    curr_ts = T0 + timedelta(minutes=1)
    assert impossible_travel(prev_ts, None, None, "US", curr_ts, None, None, "US") is False
