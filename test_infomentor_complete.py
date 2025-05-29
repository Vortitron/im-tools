#!/usr/bin/env python3
"""
Complete InfoMentor API Test Script

This script tests the actual API endpoints discovered from the app configuration
to capture real schedule data and validate the parsing implementation.

Usage:
    python3 test_infomentor_complete.py

The script will:
1. Authenticate with InfoMentor
2. Test all discovered API endpoints with real data
3. Capture and save actual schedule data
4. Test the parsing logic with real data
5. Validate the complete integration
"""

import asyncio
import getpass
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional

# Try to load environment variables from .env file
try:
	from dotenv import load_dotenv
	load_dotenv()
except ImportError:
	print("💡 Tip: Install python-dotenv to use .env file for credentials:")
	print("    pip install python-dotenv")

# Set up logging
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Add the custom_components directory to Python path
sys.path.insert(0, str(Path(__file__).parent / "custom_components" / "infomentor"))

try:
	from infomentor import InfoMentorClient
	from infomentor.exceptions import InfoMentorAuthError, InfoMentorConnectionError
	from infomentor.models import TimetableEntry, TimeRegistrationEntry, ScheduleDay
except ImportError as e:
	print(f"❌ Import error: {e}")
	print("Make sure you're running this script from the repository root directory.")
	sys.exit(1)


def save_json_to_file(data: Any, filename: str, description: str = "") -> Path:
	"""Save JSON data to file for analysis."""
	output_dir = Path("debug_output")
	output_dir.mkdir(exist_ok=True)
	
	file_path = output_dir / filename
	with open(file_path, 'w', encoding='utf-8') as f:
		json.dump(data, f, indent=2, ensure_ascii=False)
	
	print(f"   💾 Saved {description} to: {file_path}")
	if isinstance(data, dict):
		print(f"   📊 Data keys: {list(data.keys())}")
	elif isinstance(data, list):
		print(f"   📊 Data items: {len(data)}")
	else:
		print(f"   📊 Data type: {type(data)}")
	
	return file_path


async def test_calendar_api(client: InfoMentorClient, pupil_id: str, start_date: datetime, end_date: datetime) -> Optional[Dict[str, Any]]:
	"""Test the calendar API endpoint to get actual schedule entries."""
	print("\n📅 Testing Calendar API (getentries)")
	print("-" * 40)
	
	try:
		url = "https://hub.infomentor.se/calendarv2/calendarv2/getentries"
		headers = {
			"Accept": "application/json, text/javascript, */*; q=0.01",
			"X-Requested-With": "XMLHttpRequest",
			"Content-Type": "application/json; charset=UTF-8",
		}
		
		payload = {
			"startDate": start_date.strftime('%Y-%m-%d'),
			"endDate": end_date.strftime('%Y-%m-%d'),
		}
		
		print(f"   📤 POST {url}")
		print(f"   📅 Date range: {payload['startDate']} to {payload['endDate']}")
		
		async with client._session.post(url, headers=headers, json=payload) as resp:
			print(f"   📥 Response: HTTP {resp.status}")
			
			if resp.status == 200:
				data = await resp.json()
				timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
				filename = f"calendar_entries_{pupil_id}_{timestamp}.json"
				save_json_to_file(data, filename, "calendar entries data")
				
				# Test parsing with the client's method
				print("   🔍 Testing calendar parsing...")
				try:
					timetable_entries = client._parse_calendar_entries_as_timetable(data, pupil_id, start_date, end_date)
					print(f"   ✅ Parsed {len(timetable_entries)} timetable entries")
					for entry in timetable_entries[:3]:  # Show first 3
						print(f"      - {entry.date.strftime('%Y-%m-%d')} {entry.start_time}: {entry.title}")
				except Exception as e:
					print(f"   ❌ Parsing error: {e}")
				
				return data
			else:
				error_text = await resp.text()
				print(f"   ❌ Failed: {error_text[:200]}...")
				return None
				
	except Exception as e:
		print(f"   ❌ Exception: {e}")
		return None


async def test_time_registration_api(client: InfoMentorClient, pupil_id: str, start_date: datetime, end_date: datetime) -> Optional[Dict[str, Any]]:
	"""Test the time registration API endpoint."""
	print("\n🕐 Testing Time Registration API (GetTimeRegistrations)")
	print("-" * 50)
	
	try:
		url = "https://hub.infomentor.se/TimeRegistration/TimeRegistration/GetTimeRegistrations/"
		headers = {
			"Accept": "application/json, text/javascript, */*; q=0.01",
			"X-Requested-With": "XMLHttpRequest",
			"Content-Type": "application/json; charset=UTF-8",
		}
		
		payload = {
			"startDate": start_date.strftime('%Y-%m-%d'),
			"endDate": end_date.strftime('%Y-%m-%d'),
		}
		
		print(f"   📤 POST {url}")
		print(f"   📅 Date range: {payload['startDate']} to {payload['endDate']}")
		
		async with client._session.post(url, headers=headers, json=payload) as resp:
			print(f"   📥 Response: HTTP {resp.status}")
			
			if resp.status == 200:
				data = await resp.json()
				timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
				filename = f"time_registrations_{pupil_id}_{timestamp}.json"
				save_json_to_file(data, filename, "time registration data")
				
				# Test parsing with the client's method
				print("   🔍 Testing time registration parsing...")
				try:
					time_reg_entries = client._parse_time_registration_from_api(data, pupil_id, start_date, end_date)
					print(f"   ✅ Parsed {len(time_reg_entries)} time registration entries")
					for entry in time_reg_entries[:3]:  # Show first 3
						print(f"      - {entry.date.strftime('%Y-%m-%d')} {entry.start_time}-{entry.end_time}: {entry.status}")
				except Exception as e:
					print(f"   ❌ Parsing error: {e}")
				
				return data
			else:
				error_text = await resp.text()
				print(f"   ❌ Failed: {error_text[:200]}...")
				return None
				
	except Exception as e:
		print(f"   ❌ Exception: {e}")
		return None


async def test_time_registration_calendar_api(client: InfoMentorClient, pupil_id: str, start_date: datetime, end_date: datetime) -> Optional[Dict[str, Any]]:
	"""Test the time registration calendar API endpoint."""
	print("\n📆 Testing Time Registration Calendar API (GetCalendarData)")
	print("-" * 55)
	
	try:
		url = "https://hub.infomentor.se/TimeRegistration/TimeRegistration/GetCalendarData/"
		headers = {
			"Accept": "application/json, text/javascript, */*; q=0.01",
			"X-Requested-With": "XMLHttpRequest",
			"Content-Type": "application/json; charset=UTF-8",
		}
		
		payload = {
			"startDate": start_date.strftime('%Y-%m-%d'),
			"endDate": end_date.strftime('%Y-%m-%d'),
		}
		
		print(f"   📤 POST {url}")
		print(f"   📅 Date range: {payload['startDate']} to {payload['endDate']}")
		
		async with client._session.post(url, headers=headers, json=payload) as resp:
			print(f"   📥 Response: HTTP {resp.status}")
			
			if resp.status == 200:
				data = await resp.json()
				timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
				filename = f"time_reg_calendar_{pupil_id}_{timestamp}.json"
				save_json_to_file(data, filename, "time registration calendar data")
				
				# Test parsing with the client's method
				print("   🔍 Testing time registration calendar parsing...")
				try:
					time_reg_entries = client._parse_time_registration_calendar_from_api(data, pupil_id, start_date, end_date)
					print(f"   ✅ Parsed {len(time_reg_entries)} time registration calendar entries")
					for entry in time_reg_entries[:3]:  # Show first 3
						print(f"      - {entry.date.strftime('%Y-%m-%d')} {entry.start_time}-{entry.end_time}: {entry.status}")
				except Exception as e:
					print(f"   ❌ Parsing error: {e}")
				
				return data
			else:
				error_text = await resp.text()
				print(f"   ❌ Failed: {error_text[:200]}...")
				return None
				
	except Exception as e:
		print(f"   ❌ Exception: {e}")
		return None


async def test_client_methods(client: InfoMentorClient, pupil_id: str, start_date: datetime, end_date: datetime):
	"""Test the high-level client methods."""
	print("\n🧪 Testing Client Methods")
	print("=" * 30)
	
	# Test get_timetable
	print("\n📚 Testing get_timetable()...")
	try:
		timetable = await client.get_timetable(pupil_id, start_date, end_date)
		print(f"   ✅ Got {len(timetable)} timetable entries")
		for entry in timetable[:3]:
			print(f"      - {entry.date.strftime('%Y-%m-%d')} {entry.start_time}: {entry.title}")
	except Exception as e:
		print(f"   ❌ get_timetable error: {e}")
	
	# Test get_time_registration
	print("\n🕐 Testing get_time_registration()...")
	try:
		time_reg = await client.get_time_registration(pupil_id, start_date, end_date)
		print(f"   ✅ Got {len(time_reg)} time registration entries")
		for entry in time_reg[:3]:
			print(f"      - {entry.date.strftime('%Y-%m-%d')} {entry.start_time}-{entry.end_time}: {entry.status}")
	except Exception as e:
		print(f"   ❌ get_time_registration error: {e}")
	
	# Test get_schedule (combined)
	print("\n📅 Testing get_schedule()...")
	try:
		schedule = await client.get_schedule(pupil_id, start_date, end_date)
		print(f"   ✅ Got {len(schedule)} schedule days")
		for day in schedule[:3]:
			print(f"      - {day.date.strftime('%Y-%m-%d')}: {len(day.timetable_entries)} timetable, {len(day.time_registrations)} time reg")
	except Exception as e:
		print(f"   ❌ get_schedule error: {e}")


async def main():
	"""Main test function."""
	print("🧪 InfoMentor Complete API Test")
	print("=" * 40)
	
	# Get credentials
	username = os.getenv('INFOMENTOR_USERNAME')
	password = os.getenv('INFOMENTOR_PASSWORD')
	
	if not username:
		username = input("InfoMentor username/email: ")
	if not password:
		password = getpass.getpass("InfoMentor password: ")
	
	# Define test date range
	today = datetime.now()
	start_date = today - timedelta(days=3)  # 3 days ago
	end_date = today + timedelta(days=10)   # 10 days ahead
	
	print(f"📅 Test date range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
	
	async with InfoMentorClient() as client:
		# Authenticate
		print("\n🔐 Authenticating...")
		success = await client.login(username, password)
		if not success:
			print("❌ Authentication failed!")
			return False
		
		print("✅ Authentication successful!")
		
		# Get pupil IDs
		pupil_ids = await client.get_pupil_ids()
		print(f"👥 Found pupil IDs: {pupil_ids}")
		
		if not pupil_ids:
			print("❌ No pupil IDs found!")
			return False
		
		# Test with each pupil
		for pupil_id in pupil_ids:
			print(f"\n👤 Testing with pupil: {pupil_id}")
			print("=" * 50)
			
			# Switch to pupil
			await client.switch_pupil(pupil_id)
			
			# Test all API endpoints
			calendar_data = await test_calendar_api(client, pupil_id, start_date, end_date)
			time_reg_data = await test_time_registration_api(client, pupil_id, start_date, end_date)
			time_cal_data = await test_time_registration_calendar_api(client, pupil_id, start_date, end_date)
			
			# Test high-level client methods
			await test_client_methods(client, pupil_id, start_date, end_date)
			
			print(f"\n✅ Completed testing for pupil {pupil_id}")
		
		print("\n🎉 All tests completed!")
		print("\nCheck the debug_output/ directory for captured data files.")
		return True


if __name__ == "__main__":
	try:
		success = asyncio.run(main())
		sys.exit(0 if success else 1)
	except KeyboardInterrupt:
		print("\n⚠️ Test interrupted by user")
		sys.exit(1)
	except Exception as e:
		print(f"\n❌ Unexpected error: {e}")
		sys.exit(1)