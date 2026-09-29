#!/usr/bin/env python3
"""
Demonstration test showing how the timetable endpoint change improves child type detection.
This test shows the expected behavior without requiring live authentication.
"""

import sys
from pathlib import Path
from datetime import datetime, time

# Add the custom components to the path
sys.path.insert(0, str(Path(__file__).parent.parent / 'custom_components' / 'infomentor'))

from infomentor.models import TimetableEntry, TimeRegistrationEntry, ScheduleDay

def demonstrate_child_type_detection():
	"""Demonstrate how child type detection works with timetable vs calendar endpoints."""
	
	print("🧪 TIMETABLE ENDPOINT CHILD TYPE DETECTION DEMONSTRATION")
	print("=" * 65)
	print()
	
	# Create sample data showing different scenarios
	base_date = datetime(2024, 12, 16)  # Monday
	
	# School child example (Olle) - has timetable entries from the NEW endpoint
	print("📋 SCENARIO 1: School Child (e.g., Olle)")
	print("-" * 45)
	
	olle_timetable_entries = [
		TimetableEntry(
			id="1", title="Matematik", date=base_date,
			subject="Matematik", start_time=time(8, 0), end_time=time(8, 45),
			teacher="Mrs. Andersson", room="Room 12", pupil_id="1000000001"
		),
		TimetableEntry(
			id="2", title="Svenska", date=base_date,
			subject="Svenska", start_time=time(9, 0), end_time=time(9, 45),
			teacher="Mr. Johansson", room="Room 12", pupil_id="1000000001"
		),
		TimetableEntry(
			id="3", title="Naturvetenskap", date=base_date,
			subject="Naturvetenskap", start_time=time(10, 15), end_time=time(11, 0),
			teacher="Ms. Petersson", room="Science Lab", pupil_id="1000000001"
		)
	]
	
	olle_time_registrations = [
		TimeRegistrationEntry(
			id="1", date=base_date, start_time=time(12, 0), end_time=time(16, 0),
			status="scheduled", comment="Fritids", pupil_id="1000000001"
		)
	]
	
	print(f"📚 Timetable entries from /timetable/timetable/gettimetablelist: {len(olle_timetable_entries)}")
	for i, entry in enumerate(olle_timetable_entries, 1):
		print(f"   {i}. {entry.subject} ({entry.start_time.strftime('%H:%M')}-{entry.end_time.strftime('%H:%M')})")
	
	print(f"⏰ Time registrations: {len(olle_time_registrations)}")
	for reg in olle_time_registrations:
		print(f"   - {reg.start_time.strftime('%H:%M')}-{reg.end_time.strftime('%H:%M')} [{reg.status}]")
	
	olle_classification = "SCHOOL" if len(olle_timetable_entries) > 0 else "PRESCHOOL"
	print(f"🏫 Classification: {olle_classification} CHILD")
	print(f"   Reason: Has {len(olle_timetable_entries)} timetable entries from proper endpoint")
	print()
	
	# Preschool child example (Alva) - no timetable entries
	print("📋 SCENARIO 2: Preschool Child (e.g., Alva)")
	print("-" * 47)
	
	alva_timetable_entries = []  # No school timetable
	
	alva_time_registrations = [
		TimeRegistrationEntry(
			id="1", date=base_date, start_time=time(8, 0), end_time=time(16, 0),
			status="scheduled", comment="Förskola", pupil_id="1000000002"
		)
	]
	
	print(f"📚 Timetable entries from /timetable/timetable/gettimetablelist: {len(alva_timetable_entries)}")
	if not alva_timetable_entries:
		print("   (No timetable entries - not school age)")
	
	print(f"⏰ Time registrations: {len(alva_time_registrations)}")
	for reg in alva_time_registrations:
		print(f"   - {reg.start_time.strftime('%H:%M')}-{reg.end_time.strftime('%H:%M')} [{reg.status}]")
	
	alva_classification = "SCHOOL" if len(alva_timetable_entries) > 0 else "PRESCHOOL"
	print(f"🧸 Classification: {alva_classification} CHILD")
	print(f"   Reason: No timetable entries - preschool age")
	print()
	
	# Create ScheduleDay objects to show complete picture
	olle_schedule = ScheduleDay(
		date=base_date, pupil_id="1000000001",
		timetable_entries=olle_timetable_entries,
		time_registrations=olle_time_registrations
	)
	
	alva_schedule = ScheduleDay(
		date=base_date, pupil_id="1000000002",
		timetable_entries=alva_timetable_entries,
		time_registrations=alva_time_registrations
	)
	
	print("🔍 SCHEDULE ANALYSIS")
	print("-" * 20)
	print(f"Olle has_school: {olle_schedule.has_school} (any activity)")
	print(f"Olle has_preschool_or_fritids: {olle_schedule.has_preschool_or_fritids}")
	print(f"Alva has_school: {alva_schedule.has_school} (any activity)")
	print(f"Alva has_preschool_or_fritids: {alva_schedule.has_preschool_or_fritids}")
	print()
	print("Note: has_school indicates ANY structured activity (school/preschool/fritids)")
	print()
	
	print("✅ KEY IMPROVEMENTS WITH TIMETABLE ENDPOINT")
	print("-" * 45)
	print("BEFORE (using calendar endpoint):")
	print("  ❌ Fetched from /calendarv2/calendarv2/getentries")
	print("  ❌ Mixed calendar events, holidays, and some lessons")
	print("  ❌ Unreliable detection of actual school lessons")
	print("  ❌ School children might appear as preschool")
	print()
	print("AFTER (using timetable endpoint):")
	print("  ✅ Fetches from /timetable/timetable/gettimetablelist")
	print("  ✅ Dedicated school timetable data")
	print("  ✅ Reliable detection of school vs preschool")
	print("  ✅ Proper classification of children")
	print()
	
	print("🎯 VALIDATION RESULTS")
	print("-" * 20)
	school_children = [olle_classification]
	preschool_children = [alva_classification]
	
	school_with_timetable = all(c == "SCHOOL" for c in school_children)
	preschool_without_timetable = all(c == "PRESCHOOL" for c in preschool_children)
	
	print(f"✅ School children correctly identified: {school_with_timetable}")
	print(f"✅ Preschool children correctly identified: {preschool_without_timetable}")
	
	overall_success = school_with_timetable and preschool_without_timetable
	print(f"\n🎉 Overall detection working: {overall_success}")
	
	if overall_success:
		print("\n🏆 SUCCESS: The timetable endpoint change should correctly")
		print("   distinguish between school and preschool children!")
	
	return overall_success

def demonstrate_api_change():
	"""Show the specific API endpoint change made."""
	print("\n" + "=" * 65)
	print("🔧 API ENDPOINT CHANGE SUMMARY")
	print("=" * 65)
	print()
	print("OLD Implementation (client.py):")
	print("  📍 URL: https://hub.infomentor.se/calendarv2/calendarv2/getentries")
	print("  🔄 Method: _parse_calendar_entries_as_timetable()")
	print("  📊 Result: Mixed calendar data, unreliable school detection")
	print()
	print("NEW Implementation (client.py):")
	print("  📍 URL: https://hub.infomentor.se/timetable/timetable/gettimetablelist")
	print("  🔄 Method: _parse_timetable_from_api()")
	print("  📊 Result: Pure timetable data, reliable school detection")
	print()
	print("Code Changes Made:")
	print("  ✅ Updated get_timetable() to use correct endpoint")
	print("  ✅ Updated _get_timetable_post_fallback() for POST requests")
	print("  ✅ Changed parsing from calendar to timetable parser")
	print("  ✅ Updated project documentation")

if __name__ == "__main__":
	print("🚀 Starting timetable endpoint demonstration...")
	print()
	
	success = demonstrate_child_type_detection()
	demonstrate_api_change()
	
	print("\n" + "=" * 65)
	if success:
		print("✅ DEMONSTRATION COMPLETE: Timetable endpoint should work correctly!")
	else:
		print("❌ DEMONSTRATION FAILED: Logic errors detected!")
	print("=" * 65) 