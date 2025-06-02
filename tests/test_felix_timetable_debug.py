#!/usr/bin/env python3
"""
Debug test specifically for Felix's timetable data.
This test will check multiple API endpoints to understand why Felix's school lessons aren't being detected.
"""

import asyncio
import aiohttp
import json
import logging
from datetime import datetime, timedelta
import sys
import os

# Add the custom component path to sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'custom_components', 'infomentor'))

from infomentor import InfoMentorClient

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

async def debug_felix_timetable():
	"""Debug Felix's timetable data by checking multiple API endpoints."""
	
	print("🔍 FELIX TIMETABLE DEBUG")
	print("=" * 60)
	
	# Test credentials
	username = "andy@callycode.com"
	password = "Callycode2024!"
	felix_id = "1806227557"
	isolde_id = "2104025925"
	
	async with InfoMentorClient() as client:
		try:
			print("🔐 Authenticating...")
			await client.login(username, password)
			print("✅ Authentication successful!")
			
			# Get pupil IDs
			pupil_ids = await client.get_pupil_ids()
			print(f"📋 Found pupils: {pupil_ids}")
			
			# Test dates
			start_date = datetime(2025, 6, 2)  # Monday
			end_date = datetime(2025, 6, 8)    # Sunday
			
			print(f"\n📅 Testing period: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
			
			# Test both pupils
			for pupil_id, name in [(felix_id, "Felix"), (isolde_id, "Isolde")]:
				print(f"\n👤 TESTING {name} (ID: {pupil_id})")
				print("-" * 40)
				
				# Switch to pupil
				switch_result = await client.switch_pupil(pupil_id)
				print(f"🔄 Pupil switch result: {switch_result}")
				
				# Test 1: Standard timetable API
				print("\n📚 Test 1: Standard timetable API")
				timetable_entries = await client.get_timetable(None, start_date, end_date)
				print(f"   Found {len(timetable_entries)} timetable entries")
				for entry in timetable_entries:
					print(f"   - {entry.date.strftime('%Y-%m-%d')}: {entry.subject} ({entry.start_time}-{entry.end_time})")
				
				# Test 2: Time registration API
				print("\n⏰ Test 2: Time registration API")
				time_registrations = await client.get_time_registration(None, start_date, end_date)
				print(f"   Found {len(time_registrations)} time registrations")
				for reg in time_registrations:
					print(f"   - {reg.date.strftime('%Y-%m-%d')}: {reg.start_time}-{reg.end_time} [{reg.status}] (type: {reg.type})")
				
				# Test 3: Combined schedule API
				print("\n📋 Test 3: Combined schedule API")
				schedule_days = await client.get_schedule(None, start_date, end_date)
				print(f"   Found {len(schedule_days)} schedule days")
				for day in schedule_days:
					print(f"   - {day.date.strftime('%Y-%m-%d')}: school={day.has_school}, preschool/fritids={day.has_preschool_or_fritids}")
					if day.timetable_entries:
						for entry in day.timetable_entries:
							print(f"     📚 {entry.subject} ({entry.start_time}-{entry.end_time})")
					if day.time_registrations:
						for reg in day.time_registrations:
							print(f"     ⏰ {reg.type} ({reg.start_time}-{reg.end_time}) [{reg.status}]")
				
				# Test 4: Raw calendar API calls
				print("\n🌐 Test 4: Raw calendar API calls")
				await test_raw_calendar_apis(client, pupil_id, name, start_date, end_date)
				
				print("\n" + "=" * 40)
			
			# Test 5: Child type determination
			print("\n🎯 Test 5: Child type determination")
			for pupil_id, name in [(felix_id, "Felix"), (isolde_id, "Isolde")]:
				await client.switch_pupil(pupil_id)
				
				# Get schedule for a longer period to check for any timetable entries
				extended_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
				extended_end = extended_start + timedelta(weeks=4)  # Check 4 weeks
				
				schedule_days = await client.get_schedule(None, extended_start, extended_end)
				
				# Check if child has any timetable entries
				has_any_timetable = any(day.has_school for day in schedule_days)
				total_timetable_entries = sum(len(day.timetable_entries) for day in schedule_days)
				total_time_registrations = sum(len(day.time_registrations) for day in schedule_days)
				
				child_type = "school" if has_any_timetable else "preschool"
				
				print(f"   {name}:")
				print(f"     - Child type: {child_type}")
				print(f"     - Total timetable entries (4 weeks): {total_timetable_entries}")
				print(f"     - Total time registrations (4 weeks): {total_time_registrations}")
				print(f"     - Days with school: {sum(1 for day in schedule_days if day.has_school)}")
				print(f"     - Days with preschool/fritids: {sum(1 for day in schedule_days if day.has_preschool_or_fritids)}")
				
				# Show time registration types
				time_reg_types = set()
				for day in schedule_days:
					for reg in day.time_registrations:
						time_reg_types.add(reg.type)
				print(f"     - Time registration types: {list(time_reg_types)}")
		
		except Exception as e:
			print(f"❌ Error: {e}")
			import traceback
			traceback.print_exc()

async def test_raw_calendar_apis(client, pupil_id, name, start_date, end_date):
	"""Test raw calendar API endpoints to see what data is available."""
	
	# Base URL
	base_url = "https://hub.infomentor.se"
	
	# Test different calendar endpoints
	endpoints = [
		"/calendarv2/calendarv2/getentries",
		"/calendar/calendar/getentries", 
		"/timetable/timetable/getentries",
		"/schedule/schedule/getentries",
		"/TimeRegistration/TimeRegistration/GetTimeRegistrations/",
		"/timetable/timetable/gettimetable",
		"/calendar/calendar/getcalendar",
	]
	
	headers = {
		"Accept": "application/json, text/javascript, */*; q=0.01",
		"X-Requested-With": "XMLHttpRequest",
		"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
	}
	
	params = {
		"startDate": start_date.strftime('%Y-%m-%d'),
		"endDate": end_date.strftime('%Y-%m-%d'),
	}
	
	for endpoint in endpoints:
		try:
			url = base_url + endpoint
			print(f"   🌐 Testing {endpoint}")
			
			async with client._session.get(url, headers=headers, params=params) as resp:
				if resp.status == 200:
					try:
						data = await resp.json()
						
						# Analyse the response structure
						if isinstance(data, dict):
							keys = list(data.keys())
							print(f"      ✅ Success - Response keys: {keys}")
							
							# Look for entries/items
							for key in ['entries', 'events', 'items', 'data', 'days', 'calendar', 'timetable']:
								if key in data:
									items = data[key]
									if isinstance(items, list):
										print(f"         📋 {key}: {len(items)} items")
										if items and len(items) > 0:
											# Show sample item structure
											sample = items[0]
											if isinstance(sample, dict):
												sample_keys = list(sample.keys())
												print(f"            Sample keys: {sample_keys[:10]}...")
									elif isinstance(items, dict):
										print(f"         📋 {key}: dict with keys {list(items.keys())[:5]}...")
						elif isinstance(data, list):
							print(f"      ✅ Success - List with {len(data)} items")
						else:
							print(f"      ✅ Success - {type(data)}")
							
					except json.JSONDecodeError:
						text = await resp.text()
						print(f"      ⚠️  Success but not JSON - {len(text)} chars")
				else:
					print(f"      ❌ HTTP {resp.status}")
					
		except Exception as e:
			print(f"      ❌ Error: {e}")

if __name__ == "__main__":
	asyncio.run(debug_felix_timetable()) 