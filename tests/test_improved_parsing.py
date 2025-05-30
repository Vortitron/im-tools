#!/usr/bin/env python3
"""
Test script to verify improved pupil ID and name extraction.
"""

import asyncio
import sys
import json
from pathlib import Path

# Add the custom components to the path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve() / 'custom_components' / 'infomentor'))

from infomentor import InfoMentorClient
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv(Path(__file__).parent.parent / '.env')

async def test_improved_parsing():
	"""Test the improved parsing functionality."""
	print("🧪 Testing Improved Pupil Parsing")
	print("=" * 50)
	
	async with InfoMentorClient() as client:
		username = os.getenv('INFOMENTOR_USERNAME')
		password = os.getenv('INFOMENTOR_PASSWORD')
		
		if not username or not password:
			print("❌ Missing credentials in .env file")
			return
		
		print(f"👤 Testing with username: {username}")
		
		# Step 1: Test authentication
		print("\n📍 Step 1: Testing authentication...")
		try:
			if await client.login(username, password):
				print("   ✅ Authentication successful")
			else:
				print("   ❌ Authentication failed")
				return
		except Exception as e:
			print(f"   ❌ Authentication error: {e}")
			return
		
		# Step 2: Test pupil ID extraction
		print("\n📍 Step 2: Testing pupil ID extraction...")
		try:
			pupil_ids = await client.get_pupil_ids()
			print(f"   📋 Found pupil IDs: {pupil_ids}")
			
			if not pupil_ids:
				print("   ❌ No pupil IDs found!")
				return
			elif len(pupil_ids) == 0:
				print("   ⚠️  Zero pupils - this might indicate parent account filtering is too aggressive")
			else:
				print(f"   ✅ Found {len(pupil_ids)} pupils")
		except Exception as e:
			print(f"   ❌ Error getting pupil IDs: {e}")
			return
		
		# Step 3: Test pupil name extraction
		print("\n📍 Step 3: Testing pupil name extraction...")
		valid_pupils = []
		
		for pupil_id in pupil_ids:
			try:
				pupil_info = await client.get_pupil_info(pupil_id)
				if pupil_info:
					print(f"   👤 Pupil {pupil_id}: {pupil_info.name}")
					if pupil_info.name and pupil_info.name != f"Pupil {pupil_id}":
						valid_pupils.append((pupil_id, pupil_info.name))
				else:
					print(f"   ❌ No info found for pupil {pupil_id}")
			except Exception as e:
				print(f"   ❌ Error getting info for pupil {pupil_id}: {e}")
		
		if valid_pupils:
			print(f"   ✅ Successfully extracted names for {len(valid_pupils)} pupils")
		else:
			print("   ❌ No valid pupil names extracted")
		
		# Step 4: Test schedule data for each valid pupil
		print("\n📍 Step 4: Testing schedule data...")
		
		for pupil_id, pupil_name in valid_pupils:
			print(f"   👤 Testing schedule for {pupil_name} (ID: {pupil_id})...")
			
			try:
				# Switch to this pupil's context
				await client.switch_pupil(pupil_id)
				
				# Test schedule retrieval
				from datetime import datetime, timedelta
				start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
				end_date = start_date + timedelta(days=7)
				
				schedule_days = await client.get_schedule(pupil_id, start_date, end_date)
				print(f"      📅 Found {len(schedule_days)} schedule days")
				
				# Check today's schedule specifically
				today = datetime.now().date()
				today_schedule = None
				for day in schedule_days:
					if day.date.date() == today:
						today_schedule = day
						break
				
				if today_schedule:
					print(f"      📅 Today's schedule:")
					print(f"         Has school: {today_schedule.has_school}")
					print(f"         Has preschool/fritids: {today_schedule.has_preschool_or_fritids}")
					
					if today_schedule.timetable_entries:
						print(f"         Timetable entries: {len(today_schedule.timetable_entries)}")
						for entry in today_schedule.timetable_entries[:3]:  # Show first 3
							print(f"           - {entry.subject} ({entry.start_time} - {entry.end_time})")
					
					if today_schedule.time_registrations:
						print(f"         Time registrations: {len(today_schedule.time_registrations)}")
						for reg in today_schedule.time_registrations[:3]:  # Show first 3
							print(f"           - {reg.status}: {reg.start_time} - {reg.end_time}")
				else:
					print(f"      📅 No schedule for today")
					
			except Exception as e:
				print(f"      ❌ Error getting schedule: {e}")
		
		# Step 5: Summary
		print("\n📊 Summary:")
		print(f"   Pupils found: {len(pupil_ids)}")
		print(f"   Valid names extracted: {len(valid_pupils)}")
		
		if len(valid_pupils) == len(pupil_ids):
			print("   ✅ All pupils have valid names")
		elif len(valid_pupils) > 0:
			print("   ⚠️  Some pupils missing names")
		else:
			print("   ❌ No valid pupil names extracted")
		
		# Check for common issues
		issues = []
		
		# Issue 1: No pupils found (might be filtering too aggressively)
		if len(pupil_ids) == 0:
			issues.append("No pupils found - check if parent filtering is too strict")
		
		# Issue 2: No names extracted
		if len(valid_pupils) == 0:
			issues.append("No names extracted - check name parsing patterns")
		
		# Issue 3: Pupil count is 0 (original issue)
		if len(pupil_ids) == 0:
			issues.append("Pupil count is zero (original reported issue)")
		
		if issues:
			print("\n⚠️  Potential issues found:")
			for issue in issues:
				print(f"   - {issue}")
		else:
			print("\n✅ No major issues detected!")

if __name__ == "__main__":
	asyncio.run(test_improved_parsing()) 