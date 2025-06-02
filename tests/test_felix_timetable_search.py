#!/usr/bin/env python3
"""
Felix Timetable Search Test

This test searches for Felix's timetable data across a broader date range
to determine if he has any school timetable entries.
"""

import asyncio
import getpass
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Try to load environment variables from .env file
try:
	from dotenv import load_dotenv
	load_dotenv(Path(__file__).parent.parent / '.env')
except ImportError:
	print("💡 Tip: Install python-dotenv to use .env file for credentials")

# Set up logging
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Add the custom_components directory to Python path
sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components" / "infomentor"))

try:
	from infomentor import InfoMentorClient
	from infomentor.exceptions import InfoMentorAuthError
except ImportError as e:
	print(f"❌ Import error: {e}")
	sys.exit(1)


async def search_felix_timetable():
	"""Search for Felix's timetable data across multiple date ranges."""
	print("🔍 Felix Timetable Search Test")
	print("=" * 50)
	
	# Get credentials
	username = os.getenv('INFOMENTOR_USERNAME')
	password = os.getenv('INFOMENTOR_PASSWORD')
	
	if not username:
		username = input("InfoMentor username: ")
	if not password:
		password = getpass.getpass("InfoMentor password: ")
	
	async with InfoMentorClient() as client:
		# Authenticate
		print("\n🔐 Authenticating...")
		try:
			await client.login(username, password)
			print("	✅ Authentication successful")
		except Exception as e:
			print(f"	❌ Authentication failed: {e}")
			return
		
		# Get pupil information
		pupil_ids = await client.get_pupil_ids()
		print(f"\n👥 Found {len(pupil_ids)} pupils: {pupil_ids}")
		
		# Find Felix
		felix_id = None
		felix_name = None
		for pupil_id in pupil_ids:
			try:
				pupil_info = await client.get_pupil_info(pupil_id)
				if pupil_info and pupil_info.name and "Felix" in pupil_info.name:
					felix_id = pupil_id
					felix_name = pupil_info.name
					break
			except:
				continue
		
		if not felix_id:
			print("❌ Felix not found")
			return
		
		print(f"🧒 Found Felix: {felix_name} (ID: {felix_id})")
		
		# Switch to Felix
		print(f"\n🔄 Switching to Felix...")
		try:
			switch_result = await client.switch_pupil(felix_id)
			if not switch_result:
				print(f"	❌ Switch failed")
				return
			print(f"	✅ Switch successful")
			await asyncio.sleep(2.0)
		except Exception as e:
			print(f"	❌ Switch error: {e}")
			return
		
		# Test multiple date ranges
		today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
		
		date_ranges = [
			# Current and recent weeks
			("Current week", today - timedelta(days=today.weekday()), today - timedelta(days=today.weekday()) + timedelta(weeks=1)),
			("Last week", today - timedelta(days=today.weekday()) - timedelta(weeks=1), today - timedelta(days=today.weekday())),
			("Next week", today - timedelta(days=today.weekday()) + timedelta(weeks=1), today - timedelta(days=today.weekday()) + timedelta(weeks=2)),
			
			# School term periods (assuming Swedish school year)
			("Autumn term 2024", datetime(2024, 8, 19), datetime(2024, 12, 20)),
			("Spring term 2025", datetime(2025, 1, 13), datetime(2025, 6, 6)),
			("Current month", today.replace(day=1), (today.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)),
			
			# Extended ranges
			("Last 30 days", today - timedelta(days=30), today),
			("Next 30 days", today, today + timedelta(days=30)),
		]
		
		total_entries = 0
		
		for range_name, start_date, end_date in date_ranges:
			print(f"\n📅 Testing {range_name}: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
			
			try:
				# Make direct API call to see raw response
				calendar_url = "https://hub.infomentor.se/calendarv2/calendarv2/getentries"
				headers = {
					"Accept": "application/json, text/javascript, */*; q=0.01",
					"X-Requested-With": "XMLHttpRequest",
				}
				params = {
					"startDate": start_date.strftime('%Y-%m-%d'),
					"endDate": end_date.strftime('%Y-%m-%d'),
				}
				
				async with client._session.get(calendar_url, headers=headers, params=params) as resp:
					if resp.status == 200:
						data = await resp.json()
						
						# Analyse response
						entries_count = 0
						if isinstance(data, dict):
							# Look for entries in various possible keys
							for key in ['entries', 'data', 'items', 'events', 'calendar']:
								if key in data and isinstance(data[key], list):
									entries_count = len(data[key])
									if entries_count > 0:
										print(f"	✅ Found {entries_count} entries in '{key}'")
										
										# Save this data for analysis
										output_dir = Path("debug_output")
										output_dir.mkdir(exist_ok=True)
										timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
										filename = f"felix_timetable_{range_name.replace(' ', '_')}_{timestamp}.json"
										filepath = output_dir / filename
										
										with open(filepath, 'w', encoding='utf-8') as f:
											json.dump(data, f, indent=2, ensure_ascii=False, default=str)
										
										print(f"	💾 Saved to: {filepath}")
										
										# Show first few entries
										for i, entry in enumerate(data[key][:3], 1):
											print(f"	  {i}. {entry}")
										
										total_entries += entries_count
										break
							
							if entries_count == 0:
								print(f"	📭 No entries found")
								# Check what keys are available
								if data:
									print(f"	  Available keys: {list(data.keys())}")
						
						elif isinstance(data, list):
							entries_count = len(data)
							if entries_count > 0:
								print(f"	✅ Found {entries_count} entries (direct list)")
								total_entries += entries_count
							else:
								print(f"	📭 Empty list response")
						else:
							print(f"	⚠️  Unexpected response type: {type(data)}")
					
					else:
						print(f"	❌ API call failed: {resp.status}")
			
			except Exception as e:
				print(f"	❌ Error testing {range_name}: {e}")
			
			# Small delay between requests
			await asyncio.sleep(0.5)
		
		print(f"\n📊 SUMMARY")
		print(f"Total timetable entries found for Felix: {total_entries}")
		
		if total_entries == 0:
			print("🧸 Felix appears to be a preschool child with no school timetable entries")
		else:
			print("🎒 Felix has school timetable entries - switching is working correctly!")
		
		print(f"\n✅ Felix timetable search completed!")


if __name__ == "__main__":
	asyncio.run(search_felix_timetable()) 