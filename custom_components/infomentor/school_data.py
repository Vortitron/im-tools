"""Pure helpers for assignments, calendar events, PE lessons and school lunch.

No Home Assistant or network imports, so these can be unit-tested directly.

The endpoint shapes and several of these helpers are adapted from
https://github.com/c14ym0re/infomentor-homeassistant
Copyright (c) 2026 Claes Hall, used under the MIT License.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

PE_RE = re.compile(r"\b(idh|idr|idrott|gymnastik|gympa|simning)\b", re.IGNORECASE)
# Calendar events that also mean packing sports kit ("Bad" = swimming)
KIT_EVENT_RE = re.compile(r"\b(bad|badhus|simning|skridsko\w*)\b", re.IGNORECASE)
DONE_RE = re.compile(r"done|complete|klar", re.IGNORECASE)
MATEO_UNIT_RE = re.compile(r"(\d+)\s*/?\s*$")

# Until this time the lunch sensor shows today's menu, after it the next day's
LUNCH_SWITCH_HOUR = 13


def to_date(value: Any) -> Optional[date]:
	"""Date from a date/datetime/ISO string ("2026-09-29T00:00:00.000Z" too), else None."""
	if isinstance(value, datetime):
		return value.date()
	if isinstance(value, date):
		return value
	try:
		return date.fromisoformat(str(value or "")[:10])
	except ValueError:
		return None


def is_pe(*texts: Any) -> bool:
	"""True if any text looks like a PE lesson (Idh, Idrott, Gymnastik, …)."""
	return any(PE_RE.search(str(text or "")) for text in texts)


# --------------------------------------------------------------- assignments
def normalize_tasks(payload: Any) -> Optional[Dict[str, Any]]:
	"""task/GetTasks response -> {"items": [...], "total_due", "total_overdue"}.

	Returns None when the payload isn't the expected shape (e.g. a pupil
	without the task app), so callers can tell "no tasks" from "unknown".
	"""
	if not isinstance(payload, Mapping):
		return None
	items = []
	for item in payload.get("items") or []:
		if not isinstance(item, Mapping):
			continue
		items.append({
			"id": str(item.get("id") or ""),
			"title": str(item.get("title") or "").strip(),
			"subject": str(item.get("subject") or ""),
			"due": str(item.get("dueDate") or "")[:10],
			"status": str(item.get("status") or ""),
			"status_text": str(item.get("statusText") or ""),
			"overdue": bool(item.get("isOverdue")),
		})
	return {
		"items": items,
		"total_due": payload.get("totalDue"),
		"total_overdue": payload.get("totalOverdue"),
	}


def tasks_due(items: Iterable[Mapping[str, Any]], today: date, days: int = 7) -> List[Dict[str, Any]]:
	"""Unfinished tasks due within ``days`` days (overdue ones included), soonest first."""
	limit = today + timedelta(days=days)
	due = []
	for task in items or []:
		if DONE_RE.search(str(task.get("status") or "")):
			continue
		due_date = to_date(task.get("due"))
		if due_date is None or due_date > limit:
			continue
		due.append(dict(task))
	return sorted(due, key=lambda task: task.get("due", ""))


# --------------------------------------------------------------- calendar
def normalize_calendar(entries: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
	"""calendarv2/getentries -> events, without the entries that are really tasks."""
	events = []
	for item in entries or []:
		if not isinstance(item, Mapping):
			continue
		if str(item.get("url") or "").startswith("/task/"):
			continue
		subjects = item.get("subjects") or []
		events.append({
			"id": str(item.get("id") or ""),
			"title": str(item.get("title") or "").strip(),
			"start": str(item.get("startDateFull") or item.get("startDate") or ""),
			"end": str(item.get("endDateFull") or item.get("endDate") or ""),
			"start_time": item.get("startTime") or None,
			"all_day": bool(item.get("isAllDayEvent")),
			"subjects": ", ".join(
				str(s.get("title")) for s in subjects if isinstance(s, Mapping) and s.get("title")
			),
			"description": item.get("text") or item.get("description") or "",
		})
	return events


def upcoming_events(events: Iterable[Mapping[str, Any]], today: date) -> List[Dict[str, Any]]:
	"""Events that haven't ended before today, soonest first."""
	upcoming = []
	for event in events or []:
		end = to_date(event.get("end")) or to_date(event.get("start"))
		if end is not None and end >= today:
			upcoming.append(dict(event))
	return sorted(upcoming, key=lambda event: (event.get("start", ""), event.get("start_time") or ""))


# --------------------------------------------------------------- schedule
def next_school_day(schedule: Sequence[Any], today: date) -> Optional[Any]:
	"""First ScheduleDay after ``today`` that has timetable lessons."""
	days = [day for day in schedule or [] if day.timetable_entries and day.date.date() > today]
	return min(days, key=lambda day: day.date) if days else None


def pe_lessons(day: Any) -> List[Any]:
	"""The PE lessons in a ScheduleDay, in time order."""
	if day is None:
		return []
	lessons = [entry for entry in day.timetable_entries if is_pe(entry.title, entry.subject)]
	return sorted(lessons, key=lambda entry: entry.start_time or datetime.min.time())


def kit_events(events: Iterable[Mapping[str, Any]], day: date) -> List[Dict[str, Any]]:
	"""Calendar events on ``day`` about PE or swimming (e.g. "Idrott", "Bad")."""
	matches = []
	for event in events or []:
		start = to_date(event.get("start"))
		end = to_date(event.get("end")) or start
		if start is None or not start <= day <= end:
			continue
		title = event.get("title")
		if is_pe(title) or KIT_EVENT_RE.search(str(title or "")):
			matches.append(dict(event))
	return matches


# --------------------------------------------------------------- lunch (Mateo)
def parse_mateo_unit(value: Any) -> Optional[str]:
	"""Unit id from "123" or a menu link like "https://meny.mateo.se/kommun/123"."""
	match = MATEO_UNIT_RE.search(str(value or "").strip())
	return match.group(1) if match else None


def parse_mateo_days(payload: Any) -> Dict[str, List[Dict[str, str]]]:
	"""Mateo api/v1/days -> {"YYYY-MM-DD": [{"label", "dish"}]}."""
	menu: Dict[str, List[Dict[str, str]]] = {}
	for day in payload if isinstance(payload, list) else []:
		if not isinstance(day, Mapping):
			continue
		day_date = to_date(day.get("date"))
		if day_date is None:
			continue
		menu[day_date.isoformat()] = [
			{"label": str(meal.get("type") or "Lunch"), "dish": str(meal.get("name")).strip()}
			for meal in day.get("meals") or []
			if isinstance(meal, Mapping) and meal.get("name")
		]
	return menu


def lunch_to_show(menu: Mapping[str, Sequence[Mapping[str, str]]], now: datetime) -> Tuple[Optional[str], List[Dict[str, str]]]:
	"""(date, dishes) for today's lunch until early afternoon, then the next day with a menu."""
	today = now.date()
	first = today if now.hour < LUNCH_SWITCH_HOUR else today + timedelta(days=1)
	for day in sorted(menu):
		day_date = to_date(day)
		if day_date is not None and day_date >= first and menu[day]:
			return day, [dict(dish) for dish in menu[day]]
	return None, []
