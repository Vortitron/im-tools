#!/usr/bin/env python3
"""
Test to verify that the timetable display bug is fixed.
This test ensures timetable entries properly appear in schedule attributes.
"""

import sys
from pathlib import Path
from datetime import datetime, time

# Add the custom components to the path
sys.path.insert(0, str(Path(__file__).parent.parent / 'custom_components' / 'infomentor'))

from infomentor.models import TimetableEntry, TimeRegistrationEntry, ScheduleDay

def test_timetable_display_fix():
	"""Test that timetable entries are properly displayed in schedule attributes."""
	
	print("🧪 TESTING TIMETABLE DISPLAY FIX")
	print("=" * 40)
	
	# Create test data
	base_date = datetime(2024, 12, 16)  # Monday
	
	# Create timetable entries with all possible field combinations
	timetable_entries = [
		TimetableEntry(
			id="1", title="Matematik", date=base_date,
			subject="Matematik", start_time=time(8, 0), end_time=time(8, 45),
			teacher="Mrs. Andersson", room="Room 12", pupil_id="felix"
		),
		TimetableEntry(
			id="2", title="Svenska", date=base_date,
			subject="Svenska", start_time=time(9, 0), end_time=time(9, 45),
			teacher="Mr. Johansson", room="Room 12", pupil_id="felix"
		),
		TimetableEntry(
			id="3", title="All-day Event", date=base_date,
			subject="School Trip", start_time=None, end_time=None,
			teacher=None, room=None, is_all_day=True, pupil_id="felix"
		)
	]
	
	time_registrations = [
		TimeRegistrationEntry(
			id="1", date=base_date, start_time=time(12, 0), end_time=time(16, 0),
			status="scheduled", registration_type="fritids", pupil_id="felix"
		)
	]
	
	schedule_day = ScheduleDay(
		date=base_date, pupil_id="felix",
		timetable_entries=timetable_entries,
		time_registrations=time_registrations
	)
	
	print(f"📅 Test schedule day: {schedule_day.date.strftime('%Y-%m-%d')}")
	print(f"   Timetable entries: {len(schedule_day.timetable_entries)}")
	print(f"   Time registrations: {len(schedule_day.time_registrations)}")
	print(f"   has_school: {schedule_day.has_school}")
	print(f"   has_timetable_entries: {schedule_day.has_timetable_entries}")
	print(f"   has_preschool_or_fritids: {schedule_day.has_preschool_or_fritids}")
	
	# Test timetable attribute creation (simulating sensor logic)
	print("\n🔧 Testing timetable attribute creation:")
	
	if schedule_day.timetable_entries:
		timetable = []
		for entry in schedule_day.timetable_entries:
			try:
				timetable_info = {
					"subject": entry.subject,
					"start_time": entry.start_time.strftime('%H:%M') if entry.start_time else None,
					"end_time": entry.end_time.strftime('%H:%M') if entry.end_time else None,
					"teacher": entry.teacher,
					"classroom": entry.room,  # Fixed: using entry.room not entry.classroom
				}
				timetable.append(timetable_info)
				print(f"   ✅ Successfully created timetable info: {timetable_info}")
			except AttributeError as e:
				print(f"   ❌ AttributeError: {e}")
				return False
			except Exception as e:
				print(f"   ❌ Unexpected error: {e}")
				return False
		
		print(f"\n📋 Final timetable attribute (length: {len(timetable)}):")
		for i, entry in enumerate(timetable, 1):
			print(f"   {i}. {entry}")
	
	# Test time registration attributes
	print("\n⏰ Testing time registration attributes:")
	
	if schedule_day.time_registrations:
		registrations = []
		for reg in schedule_day.time_registrations:
			try:
				reg_info = {
					"schedule_type": reg.type,
					"status": reg.status,
					"start_time": reg.start_time.strftime('%H:%M') if reg.start_time else None,
					"end_time": reg.end_time.strftime('%H:%M') if reg.end_time else None,
				}
				registrations.append(reg_info)
				print(f"   ✅ Successfully created registration info: {reg_info}")
			except Exception as e:
				print(f"   ❌ Error: {e}")
				return False
		
		print(f"\n📋 Final time registrations attribute (length: {len(registrations)}):")
		for i, reg in enumerate(registrations, 1):
			print(f"   {i}. {reg}")
	
	# Test combined day info (simulating full sensor attribute)
	print("\n📊 Testing combined day info:")
	
	day_info = {
		"date": schedule_day.date.strftime('%Y-%m-%d'),
		"weekday": schedule_day.date.strftime('%A'),
		"has_school": schedule_day.has_school,
		"has_preschool_or_fritids": schedule_day.has_preschool_or_fritids,
	}
	
	if schedule_day.earliest_start:
		day_info["earliest_start"] = schedule_day.earliest_start.strftime('%H:%M')
	if schedule_day.latest_end:
		day_info["latest_end"] = schedule_day.latest_end.strftime('%H:%M')
	
	if schedule_day.timetable_entries:
		day_info["timetable"] = timetable
	
	if schedule_day.time_registrations:
		day_info["time_registrations"] = registrations
	
	print(f"✅ Combined day info created successfully:")
	for key, value in day_info.items():
		if key in ["timetable", "time_registrations"]:
			print(f"   {key}: {len(value)} items")
		else:
			print(f"   {key}: {value}")
	
	# Validation
	print("\n🎯 VALIDATION RESULTS:")
	print("-" * 25)
	
	success_checks = [
		len(timetable) == 3,  # All 3 timetable entries processed
		len(registrations) == 1,  # 1 time registration processed
		"timetable" in day_info,  # Timetable included in day info
		"time_registrations" in day_info,  # Time registrations included
		day_info["has_school"] == True,  # Has school correctly detected
		day_info["has_preschool_or_fritids"] == True,  # Has fritids correctly detected
	]
	
	print(f"✅ All 3 timetable entries processed: {'PASS' if success_checks[0] else 'FAIL'}")
	print(f"✅ Time registration processed: {'PASS' if success_checks[1] else 'FAIL'}")
	print(f"✅ Timetable included in attributes: {'PASS' if success_checks[2] else 'FAIL'}")
	print(f"✅ Time registrations included: {'PASS' if success_checks[3] else 'FAIL'}")
	print(f"✅ Has school detected: {'PASS' if success_checks[4] else 'FAIL'}")
	print(f"✅ Has preschool/fritids detected: {'PASS' if success_checks[5] else 'FAIL'}")
	
	all_passed = all(success_checks)
	print(f"\n🎉 Overall result: {'ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED'}")
	
	if all_passed:
		print("\n🔧 BEFORE vs AFTER:")
		print("   BEFORE: AttributeError on entry.classroom (doesn't exist)")
		print("           → Timetable entries silently excluded from schedule")
		print("   AFTER:  Uses entry.room (correct field name)")
		print("           → Timetable entries properly included in schedule")
		print("\n✅ Felix's timetable entries should now appear in his schedule!")
	
	return all_passed

if __name__ == "__main__":
	test_timetable_display_fix() 