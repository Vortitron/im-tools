"""Helpers to evaluate InfoMentor schedule completeness."""

from typing import Any, Dict, List, Tuple

# Named constants keep state handling explicit and testable.
SCHEDULE_STATUS_FRESH = "fresh"
SCHEDULE_STATUS_CACHED = "cached"
SCHEDULE_STATUS_MISSING = "missing"


def evaluate_schedule_completeness(
	pupil_ids: List[str],
	data: Dict[str, Any],
) -> Tuple[bool, List[str], List[str]]:
	"""Return completeness flag together with missing and stale pupil lists."""
	missing: List[str] = []
	stale: List[str] = []
	
	for pupil_id in pupil_ids:
		pupil_data = data.get(pupil_id)
		if not pupil_data:
			missing.append(pupil_id)
			continue
		
		status = pupil_data.get("schedule_status")
		
		# Backwards compatibility: treat populated schedules as fresh when status absent.
		if not status:
			status = SCHEDULE_STATUS_FRESH if pupil_data.get("schedule") else SCHEDULE_STATUS_MISSING
		
		if status == SCHEDULE_STATUS_FRESH:
			continue
		
		if status == SCHEDULE_STATUS_CACHED:
			stale.append(pupil_id)
			continue
		
		missing.append(pupil_id)
	
	is_complete = not missing and not stale
	return is_complete, missing, stale
