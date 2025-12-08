#!/usr/bin/env python3
"""Unit tests for schedule completeness guard helpers."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "custom_components" / "infomentor" / "schedule_guard.py"
spec = spec_from_file_location("schedule_guard", MODULE_PATH)
schedule_guard = module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(schedule_guard)  # type: ignore[attr-defined]

SCHEDULE_STATUS_CACHED = schedule_guard.SCHEDULE_STATUS_CACHED
SCHEDULE_STATUS_FRESH = schedule_guard.SCHEDULE_STATUS_FRESH
SCHEDULE_STATUS_MISSING = schedule_guard.SCHEDULE_STATUS_MISSING
evaluate_schedule_completeness = schedule_guard.evaluate_schedule_completeness


def test_all_pupils_fresh_schedule():
	pupil_ids = ["a", "b"]
	data = {
		"a": {"schedule_status": SCHEDULE_STATUS_FRESH, "schedule": [1]},
		"b": {"schedule_status": SCHEDULE_STATUS_FRESH, "schedule": [1]},
	}
	complete, missing, stale = evaluate_schedule_completeness(pupil_ids, data)
	assert complete is True
	assert missing == []
	assert stale == []


def test_missing_and_cached_are_reported():
	pupil_ids = ["a", "b", "c"]
	data = {
		"a": {"schedule_status": SCHEDULE_STATUS_FRESH, "schedule": [1]},
		"b": {"schedule_status": SCHEDULE_STATUS_CACHED, "schedule": [1]},
		"c": {"schedule_status": SCHEDULE_STATUS_MISSING, "schedule": []},
	}
	complete, missing, stale = evaluate_schedule_completeness(pupil_ids, data)
	assert complete is False
	assert missing == ["c"]
	assert stale == ["b"]


def test_legacy_data_without_status_is_treated_as_fresh_when_schedule_present():
	pupil_ids = ["legacy"]
	data = {"legacy": {"schedule": ["anything"]}}
	complete, missing, stale = evaluate_schedule_completeness(pupil_ids, data)
	assert complete is True
	assert missing == []
	assert stale == []
