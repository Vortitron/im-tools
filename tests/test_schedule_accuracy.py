#!/usr/bin/env python3
"""
Test script to verify schedule accuracy and proper school/preschool detection.
"""

import asyncio
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta

# Add the custom components to the path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve() / 'custom_components' / 'infomentor'))

from infomentor import InfoMentorClient
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv(Path(__file__).parent.parent / '.env')

async def test_schedule_accuracy():
	"""Test the accuracy of schedule data and school detection."""
	print("📅 Testing Schedule Accuracy")
	print("=" * 50)
	
	async with InfoMentorClient() as client:
		username = os.getenv('INFOMENTOR_USERNAME')
		password = os.getenv('INFOMENTOR_PASSWORD')
		
		if not username or not password:
			print("❌ Missing credentials in .env file")
			return
		
		print(f"👤 Testing with username: {username}")
		
		# Authenticate
		if not await client.login(username, password):
			print("❌ Authentication failed")
			return
		
		pupil_ids = await client.get_pupil_ids()
		print(f"📋 Found {len(pupil_ids)} pupils")
		
		for pupil_id in pupil_ids:
			pupil_info = await client.get_pupil_info(pupil_id)
			pupil_name = pupil_info.name if pupil_info else f"Pupil {pupil_id}"
			
			print(f"\n👤 Testing {pupil_name} (ID: {pupil_id})")
			print("-" * 40)
			
			# Switch to this pupil
			await client.switch_pupil(pupil_id)
			
			# Get schedule for the next week
			start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
			end_date = start_date + timedelta(days=7)
			
			schedule_days = await client.get_schedule(pupil_id, start_date, end_date)
			
			print(f"📅 Schedule for next 7 days:")
			
			for day in schedule_days:
				day_name = day.date.strftime('%A')
				date_str = day.date.strftime('%Y-%m-%d')
				
				print(f"  {day_name} {date_str}:")
				print(f"    Has school: {day.has_school}")
				print(f"    Has preschool/fritids: {day.has_preschool_or_fritids}")
				
				if day.timetable_entries:
					print(f"    Timetable entries ({len(day.timetable_entries)}):")
					for entry in day.timetable_entries:
						subject = entry.subject or "Unknown subject"
						start_time = entry.start_time.strftime('%H:%M') if entry.start_time else "No start time"
						end_time = entry.end_time.strftime('%H:%M') if entry.end_time else "No end time"
						teacher = entry.teacher or "No teacher"
						room = entry.room or "No room"
						print(f"      - {subject} ({start_time}-{end_time}) with {teacher} in {room}")
				
				if day.time_registrations:
					print(f"    Time registrations ({len(day.time_registrations)}):")
					for reg in day.time_registrations:
						start_time = reg.start_time.strftime('%H:%M') if reg.start_time else "No start time"
						end_time = reg.end_time.strftime('%H:%M') if reg.end_time else "No end time"
						status = reg.status or "No status"
						print(f"      - {status}: {start_time}-{end_time}")
						if reg.is_school_closed:
							print(f"        (School closed: {reg.school_closed_reason})")
						if reg.on_leave:
							print(f"        (On leave)")
				
				if not day.timetable_entries and not day.time_registrations:
					print(f"    No activities scheduled")
				
				print()
			
			# Test specific logic for today
			today = datetime.now().date()
			today_schedule = None
			for day in schedule_days:
				if day.date.date() == today:
					today_schedule = day
					break
			
			if today_schedule:
				print(f"🎯 Today's analysis:")
				print(f"   Date: {today_schedule.date.strftime('%A, %Y-%m-%d')}")
				print(f"   Has school: {today_schedule.has_school}")
				print(f"   Has preschool/fritids: {today_schedule.has_preschool_or_fritids}")
				
				# Check if the logic makes sense
				has_timetable = len(today_schedule.timetable_entries) > 0
				has_time_reg = len(today_schedule.time_registrations) > 0
				
				print(f"   Timetable entries count: {len(today_schedule.timetable_entries)}")
				print(f"   Time registration count: {len(today_schedule.time_registrations)}")
				
				# Validate logic
				if today_schedule.has_school != has_timetable:
					print(f"   ⚠️  Logic mismatch: has_school={today_schedule.has_school} but timetable_entries={has_timetable}")
				
				if today_schedule.has_preschool_or_fritids != has_time_reg:
					print(f"   ⚠️  Logic mismatch: has_preschool_or_fritids={today_schedule.has_preschool_or_fritids} but time_registrations={has_time_reg}")
				
				# Check if it's a weekend
				weekday = today_schedule.date.weekday()  # 0=Monday, 6=Sunday
				is_weekend = weekday >= 5  # Saturday or Sunday
				
				if is_weekend and (today_schedule.has_school or today_schedule.has_preschool_or_fritids):
					print(f"   ℹ️  Weekend activity detected (weekday={weekday})")
				elif not is_weekend and not today_schedule.has_school and not today_schedule.has_preschool_or_fritids:
					print(f"   ⚠️  No activities on weekday (weekday={weekday})")
			else:
				print(f"🎯 No schedule found for today")

if __name__ == "__main__":
	asyncio.run(test_schedule_accuracy()) 