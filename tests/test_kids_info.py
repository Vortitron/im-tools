#!/usr/bin/env python3
"""
Kids Information Test Script

This script:
1. Extracts children's names from InfoMentor
2. Determines if each child is school or preschool based on timetable
3. Shows the correct time registration type based on your logic
4. Tests news access and other features

Usage:
    python3 test_kids_info.py
"""

import asyncio
import getpass
import json
import os
import sys
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional

# Try to load environment variables from .env file
try:
	from dotenv import load_dotenv
	load_dotenv(Path(__file__).parent.parent / '.env')
except ImportError:
	print("💡 Tip: Install python-dotenv to use .env file for credentials:")
	print("    pip install python-dotenv")

# Set up logging
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Add the custom_components directory to Python path
sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components" / "infomentor"))

try:
	from infomentor import InfoMentorClient
	from infomentor.exceptions import InfoMentorAuthError, InfoMentorConnectionError
	from infomentor.models import TimetableEntry, TimeRegistrationEntry, ScheduleDay, PupilInfo
except ImportError as e:
	print(f"❌ Import error: {e}")
	print("Make sure you're running this script from the repository root directory.")
	sys.exit(1)


async def get_pupil_names_from_hub(client: InfoMentorClient) -> Dict[str, str]:
	"""Extract pupil names from the hub page HTML."""
	print("🔍 Extracting pupil names from hub page...")
	
	try:
		hub_url = "https://hub.infomentor.se/#/"
		headers = {
			"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
			"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:98.0) Gecko/20100101 Firefox/98.0",
		}
		
		async with client._session.get(hub_url, headers=headers) as resp:
			if resp.status != 200:
				print(f"   ❌ Failed to get hub page: HTTP {resp.status}")
				return {}
			
			text = await resp.text()
			
		# Look for pupil data in the JSON structure
		pupil_names = {}
		
		# Extract the JSON data from the JavaScript
		json_match = re.search(r'IMHome\.home\.homeData = ({.*?});', text, re.DOTALL)
		if json_match:
			try:
				home_data = json.loads(json_match.group(1))
				pupils = home_data.get('account', {}).get('pupils', [])
				
				print(f"   📊 Found {len(pupils)} pupils in JSON data:")
				for pupil in pupils:
					pupil_name = pupil.get('name', '').strip()
					pupil_internal_id = pupil.get('id', '')
					switch_url = pupil.get('switchPupilUrl', '')
					
					# Extract the API pupil ID from the switch URL
					api_id_match = re.search(r'/SwitchPupil/(\d+)', switch_url)
					if api_id_match:
						api_pupil_id = api_id_match.group(1)
						if pupil_name and api_pupil_id:
							pupil_names[api_pupil_id] = pupil_name
							print(f"   ✅ Found: {pupil_name} (API ID: {api_pupil_id}, Internal ID: {pupil_internal_id})")
				
			except json.JSONDecodeError as e:
				print(f"   ❌ Failed to parse JSON data: {e}")
		
		# Fallback to regex patterns if JSON parsing fails
		if not pupil_names:
			print("   🔍 Trying regex patterns as fallback...")
			patterns = [
				# Pattern 1: Look for pupil switcher links with names (more precise)
				r'/Account/PupilSwitcher/SwitchPupil/(\d+)[^>]*>([^<]+)</a>',
				# Pattern 2: JavaScript pupil data
				r'"pupilId"\s*:\s*"?(\d+)"?[^}]*"name"\s*:\s*"([^"]+)"',
				r'"id"\s*:\s*"?(\d+)"?[^}]*"name"\s*:\s*"([^"]+)"',
				# Pattern 3: Select options (if any)
				r'<option[^>]*value="(\d+)"[^>]*>([^<]+)</option>',
			]
			
			for pattern in patterns:
				matches = re.findall(pattern, text, re.IGNORECASE | re.DOTALL)
				for match in matches:
					if len(match) == 2:
						pupil_id, name = match
						# Clean up the name and filter out invalid names
						name = name.strip()
						if (name and len(name) > 1 and len(name) < 50 and 
						    not name.isdigit() and 
						    "kontrollera" not in name.lower() and
						    "vänligen" not in name.lower() and
						    not name.startswith("Vänligen")):
							pupil_names[pupil_id] = name
							print(f"   ✅ Found: {name} (ID: {pupil_id})")
		
		if pupil_names:
			print(f"   📊 Total names extracted: {len(pupil_names)}")
		else:
			print("   ⚠️  No names could be extracted from hub page")
			
		return pupil_names
		
	except Exception as e:
		print(f"   ❌ Error extracting names: {e}")
		return {}


async def determine_child_type(client: InfoMentorClient, pupil_id: str, pupil_name: str) -> str:
	"""Determine if child is school or preschool based on timetable entries."""
	print(f"\n🎒 Analysing {pupil_name} (ID: {pupil_id})...")
	
	try:
		# Get next week's schedule to check for timetable entries
		start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
		end_date = start_date + timedelta(weeks=2)  # Check two weeks
		
		# Get timetable entries
		timetable_entries = await client.get_timetable(pupil_id, start_date, end_date)
		
		print(f"   📅 Found {len(timetable_entries)} timetable entries")
		
		if len(timetable_entries) > 0:
			print("   🏫 Child has timetable entries → SCHOOL CHILD")
			print("   📝 Time registration type: Fritidsschema")
			
			# Show some example timetable entries
			print("   📋 Sample timetable entries:")
			for entry in timetable_entries[:3]:
				time_str = ""
				if entry.start_time and entry.end_time:
					time_str = f" ({entry.start_time.strftime('%H:%M')}-{entry.end_time.strftime('%H:%M')})"
				subject = entry.subject or entry.title
				print(f"      - {entry.date.strftime('%Y-%m-%d')}: {subject}{time_str}")
			
			return "school"
		else:
			print("   🧸 No timetable entries → PRESCHOOL CHILD")
			print("   📝 Time registration type: Förskola")
			return "preschool"
			
	except Exception as e:
		print(f"   ❌ Error determining child type: {e}")
		return "unknown"


async def test_news_access(client: InfoMentorClient, pupil_id: str, pupil_name: str):
	"""Test news access and diagnose issues."""
	print(f"\n📰 Testing news access for {pupil_name}...")
	
	try:
		news_items = await client.get_news(pupil_id)
		
		if news_items:
			print(f"   ✅ Successfully retrieved {len(news_items)} news items")
			for i, item in enumerate(news_items[:3], 1):
				print(f"   {i}. {item.title} ({item.published_date.strftime('%Y-%m-%d')})")
		else:
			print("   📭 No news items found")
			
	except Exception as e:
		print(f"   ❌ News access error: {e}")
		
		# Try to diagnose the issue
		print("   🔍 Diagnosing news access issue...")
		
		# Test if we can access the news endpoint directly
		try:
			url = "https://hub.infomentor.se/Communication/News/GetNewsList"
			headers = {
				"Accept": "application/json, text/javascript, */*; q=0.01",
				"X-Requested-With": "XMLHttpRequest",
			}
			
			async with client._session.get(url, headers=headers) as resp:
				print(f"   📊 Direct news endpoint status: HTTP {resp.status}")
				
				if resp.status == 200:
					data = await resp.json()
					print(f"   📊 Response data keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
				else:
					text = await resp.text()
					print(f"   📊 Error response: {text[:200]}...")
					
		except Exception as diag_e:
			print(f"   ❌ Diagnostic error: {diag_e}")


async def test_schedule_analysis(client: InfoMentorClient, pupil_id: str, pupil_name: str, child_type: str):
	"""Test and analyse schedule data for the coming week."""
	print(f"\n📅 Analysing schedule for {pupil_name}...")
	
	try:
		# Get schedule for next week (starting Monday 2nd June 2025)
		monday_date = datetime(2025, 6, 2)  # Next Monday as mentioned
		end_date = monday_date + timedelta(days=7)
		
		schedule_days = await client.get_schedule(pupil_id, monday_date, end_date)
		
		if not schedule_days:
			print("   📭 No schedule data found for next week")
			return
			
		print(f"   📊 Schedule for week starting {monday_date.strftime('%Y-%m-%d')}:")
		
		for day in schedule_days:
			day_name = day.date.strftime('%A, %Y-%m-%d')
			
			if child_type == "school":
				# For school children, show both school lessons and fritids
				if day.has_school:
					print(f"   🏫 {day_name}: School lessons")
					for entry in day.timetable_entries:
						time_str = f" ({entry.start_time.strftime('%H:%M')}-{entry.end_time.strftime('%H:%M')})" if entry.start_time and entry.end_time else ""
						subject = entry.subject or entry.title
						print(f"       - {subject}{time_str}")
				
				if day.has_preschool_or_fritids:
					print(f"   🎯 {day_name}: Fritids time registration")
					for reg in day.time_registrations:
						time_str = f" ({reg.start_time.strftime('%H:%M')}-{reg.end_time.strftime('%H:%M')})" if reg.start_time and reg.end_time else ""
						status_str = f" [{reg.status}]" if reg.status else ""
						print(f"       - Registration{time_str}{status_str}")
				
				if not day.has_school and not day.has_preschool_or_fritids:
					print(f"   🏠 {day_name}: No activities (holiday/weekend)")
					
			else:  # preschool
				if day.has_preschool_or_fritids:
					print(f"   🧸 {day_name}: Förskola")
					for reg in day.time_registrations:
						time_str = f" ({reg.start_time.strftime('%H:%M')}-{reg.end_time.strftime('%H:%M')})" if reg.start_time and reg.end_time else ""
						status_str = f" [{reg.status}]" if reg.status else ""
						print(f"       - {status_str}{time_str}")
				else:
					print(f"   🏠 {day_name}: No preschool (holiday/weekend)")
		
	except Exception as e:
		print(f"   ❌ Schedule analysis error: {e}")


async def main():
	"""Main function to test kids information extraction."""
	print("🧒 InfoMentor Kids Information Test")
	print("=" * 50)
	
	# Try to load credentials from .env file
	username = os.getenv("INFOMENTOR_USERNAME")
	password = os.getenv("INFOMENTOR_PASSWORD")
	
	if username and password:
		print("🔑 Using credentials from .env file")
		print(f"   Username: {username}")
		print("   Password: ********")
	else:
		print("📝 Please enter your InfoMentor credentials:")
		if not username:
			username = input("Username: ").strip()
		if not password:
			password = getpass.getpass("Password: ").strip()
	
	if not username or not password:
		print("❌ Credentials required!")
		return
	
	async with InfoMentorClient() as client:
		try:
			print("\n🔐 Authenticating...")
			if not await client.login(username, password):
				print("❌ Authentication failed!")
				return
			
			print("✅ Authentication successful!")
			
			# Get pupil IDs
			pupil_ids = await client.get_pupil_ids()
			if not pupil_ids:
				print("❌ No pupils found!")
				return
			
			print(f"\n👥 Found {len(pupil_ids)} pupil(s)")
			
			# Extract names from hub page
			pupil_names = await get_pupil_names_from_hub(client)
			
			# Analyse each child
			kids_info = {}
			
			for pupil_id in pupil_ids:
				pupil_name = pupil_names.get(pupil_id, f"Child {pupil_id}")
				
				# Determine child type
				child_type = await determine_child_type(client, pupil_id, pupil_name)
				
				# Test news access
				await test_news_access(client, pupil_id, pupil_name)
				
				# Analyse schedule
				await test_schedule_analysis(client, pupil_id, pupil_name, child_type)
				
				kids_info[pupil_id] = {
					"name": pupil_name,
					"type": child_type,
					"registration_type": "Fritidsschema" if child_type == "school" else "Förskola"
				}
			
			# Summary
			print("\n" + "=" * 50)
			print("📋 SUMMARY")
			print("=" * 50)
			
			for pupil_id, info in kids_info.items():
				print(f"👤 {info['name']} (ID: {pupil_id})")
				print(f"   📚 Type: {info['type'].title()}")
				print(f"   📝 Time registration: {info['registration_type']}")
				print()
			
			# Red day info
			print("🔴 Red Day Information:")
			print("   Today is a red day in Sweden - no school activities")
			print("   This explains why there might be limited timetable data for today")
			print()
			
			print("✅ Analysis complete!")
			
		except Exception as e:
			print(f"❌ Error: {e}")
			raise


if __name__ == "__main__":
	asyncio.run(main()) 