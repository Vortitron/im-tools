#!/usr/bin/env python3
"""
Test the child type sensor logic with the new fritids detection.
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta

# Add the custom component path to sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'custom_components', 'infomentor'))

from infomentor import InfoMentorClient
from infomentor.models import ScheduleDay, TimeRegistrationEntry

def test_child_type_logic():
	"""Test the child type determination logic."""
	
	print("🔍 TESTING CHILD TYPE LOGIC")
	print("=" * 50)
	
	# Create mock schedule days with fritids time registrations
	felix_schedule = []
	isolde_schedule = []
	
	# Create Felix's schedule with fritids (should be school child)
	for i in range(5):  # 5 weekdays
		date = datetime(2025, 6, 2) + timedelta(days=i)
		
		time_reg = TimeRegistrationEntry(
			id=f"felix_reg_{i}",
			date=date,
			start_time=datetime.strptime("12:00", "%H:%M").time(),
			end_time=datetime.strptime("16:00", "%H:%M").time(),
			status="locked"
		)
		
		schedule_day = ScheduleDay(
			date=date,
			pupil_id="1806227557",
			timetable_entries=[],  # No timetable entries
			time_registrations=[time_reg]
		)
		
		felix_schedule.append(schedule_day)
	
	# Create Isolde's schedule with fritids (should also be school child based on new logic)
	for i in range(4):  # 4 weekdays
		date = datetime(2025, 6, 2) + timedelta(days=i)
		
		time_reg = TimeRegistrationEntry(
			id=f"isolde_reg_{i}",
			date=date,
			start_time=datetime.strptime("08:00", "%H:%M").time(),
			end_time=datetime.strptime("16:00", "%H:%M").time(),
			status="locked"
		)
		
		schedule_day = ScheduleDay(
			date=date,
			pupil_id="2104025925",
			timetable_entries=[],  # No timetable entries
			time_registrations=[time_reg]
		)
		
		isolde_schedule.append(schedule_day)
	
	# Test the child type logic
	for name, schedule in [("Felix", felix_schedule), ("Isolde", isolde_schedule)]:
		print(f"\n👤 Testing {name}")
		print("-" * 30)
		
		# Check if child has any timetable entries (school lessons)
		has_any_timetable = any(day.has_school for day in schedule)
		print(f"Has timetable entries: {has_any_timetable}")
		
		if has_any_timetable:
			child_type = "school"
			reason = "Has timetable entries"
		else:
			# Check time registration types
			time_reg_types = set()
			for day in schedule:
				for reg in day.time_registrations:
					time_reg_types.add(reg.type)
			
			print(f"Time registration types: {list(time_reg_types)}")
			
			# If we find fritids registrations, this is a school child
			if "fritids" in time_reg_types:
				child_type = "school"
				reason = "Has fritids time registrations"
			else:
				# Check for preschool types
				preschool_types = {"förskola", "forskola", "preschool"}
				if any(ptype in time_reg_types for ptype in preschool_types):
					child_type = "preschool"
					reason = "Has preschool time registrations"
				else:
					child_type = "preschool"
					reason = "Default (no clear indicators)"
		
		print(f"Child type: {child_type}")
		print(f"Reason: {reason}")
		
		# Test with actual data
		total_time_registrations = sum(len(day.time_registrations) for day in schedule)
		days_with_school = sum(1 for day in schedule if day.has_school)
		days_with_preschool_fritids = sum(1 for day in schedule if day.has_preschool_or_fritids)
		
		print(f"Total time registrations: {total_time_registrations}")
		print(f"Days with school: {days_with_school}")
		print(f"Days with preschool/fritids: {days_with_preschool_fritids}")

if __name__ == "__main__":
	test_child_type_logic() 