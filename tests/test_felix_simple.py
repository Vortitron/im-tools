#!/usr/bin/env python3
"""
Simple test to debug Felix's timetable data using the same pattern as the working test.
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta

# Add the custom component path to sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'custom_components', 'infomentor'))

from infomentor import InfoMentorClient

async def test_felix_simple():
	"""Simple test to debug Felix's timetable data."""
	
	print("🔍 FELIX SIMPLE DEBUG")
	print("=" * 50)
	
	# Load credentials from .env file
	username = os.getenv("INFOMENTOR_USERNAME")
	password = os.getenv("INFOMENTOR_PASSWORD")
	
	if not username or not password:
		print("❌ Missing credentials in .env file")
		return
		
	print(f"👤 Testing with username: {username}")
	
	async with InfoMentorClient() as client:
		try:
			# Authenticate
			print("🔐 Authenticating...")
			if not await client.login(username, password):
				print("❌ Authentication failed")
				return
			
			print("✅ Authentication successful!")
			
			pupil_ids = await client.get_pupil_ids()
			print(f"📋 Found {len(pupil_ids)} pupils: {pupil_ids}")
			
			felix_id = "1806227557"
			isolde_id = "2104025925"
			
			# Test dates - check a longer period to see if there are any timetable entries
			start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
			end_date = start_date + timedelta(weeks=4)  # Check 4 weeks
			
			print(f"\n📅 Testing period: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
			
			for pupil_id, name in [(felix_id, "Felix"), (isolde_id, "Isolde")]:
				print(f"\n👤 TESTING {name} (ID: {pupil_id})")
				print("-" * 40)
				
				# Get schedule for this pupil
				schedule_days = await client.get_schedule(pupil_id, start_date, end_date)
				print(f"📅 Found {len(schedule_days)} schedule days")
				
				# Count timetable entries and time registrations
				total_timetable_entries = sum(len(day.timetable_entries) for day in schedule_days)
				total_time_registrations = sum(len(day.time_registrations) for day in schedule_days)
				days_with_school = sum(1 for day in schedule_days if day.has_school)
				days_with_preschool_fritids = sum(1 for day in schedule_days if day.has_preschool_or_fritids)
				
				print(f"📊 Summary:")
				print(f"   - Total timetable entries: {total_timetable_entries}")
				print(f"   - Total time registrations: {total_time_registrations}")
				print(f"   - Days with school: {days_with_school}")
				print(f"   - Days with preschool/fritids: {days_with_preschool_fritids}")
				
				# Determine child type
				child_type = "school" if total_timetable_entries > 0 else "preschool"
				print(f"   - Child type: {child_type}")
				
				# Show time registration types
				time_reg_types = set()
				for day in schedule_days:
					for reg in day.time_registrations:
						time_reg_types.add(reg.type)
				print(f"   - Time registration types: {list(time_reg_types)}")
				
				# Show some sample days
				print(f"\n📋 Sample days:")
				for i, day in enumerate(schedule_days[:7]):  # Show first 7 days
					print(f"   {day.date.strftime('%Y-%m-%d')} ({day.date.strftime('%A')}):")
					print(f"     - Has school: {day.has_school}")
					print(f"     - Has preschool/fritids: {day.has_preschool_or_fritids}")
					print(f"     - Timetable entries: {len(day.timetable_entries)}")
					print(f"     - Time registrations: {len(day.time_registrations)}")
					
					# Show details if there are entries
					if day.timetable_entries:
						for entry in day.timetable_entries:
							print(f"       📚 {entry.subject} ({entry.start_time}-{entry.end_time})")
					if day.time_registrations:
						for reg in day.time_registrations:
							print(f"       ⏰ {reg.type} ({reg.start_time}-{reg.end_time}) [{reg.status}]")
				
				print()
			
			# Final comparison
			print("🎯 FINAL ANALYSIS")
			print("=" * 50)
			print("Based on the data retrieved:")
			print("- Felix should be a school child (has fritids time registrations)")
			print("- But if he has 0 timetable entries, the system thinks he's preschool")
			print("- This suggests either:")
			print("  1. Felix doesn't have school timetable entries published yet")
			print("  2. The timetable API isn't returning the right data")
			print("  3. There's a different API endpoint for school timetables")
			
		except Exception as e:
			print(f"❌ Error: {e}")
			import traceback
			traceback.print_exc()

if __name__ == "__main__":
	asyncio.run(test_felix_simple()) 