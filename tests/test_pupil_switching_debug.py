#!/usr/bin/env python3
"""
Pupil Switching Debug Test

This test focuses specifically on debugging the pupil switching issue
to ensure each child's data is retrieved correctly.
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
	load_dotenv(Path(__file__).parent.parent / '.env')
except ImportError:
	print("💡 Tip: Install python-dotenv to use .env file for credentials:")
	print("	pip install python-dotenv")

# Set up logging
import logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Add the custom_components directory to Python path
sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components" / "infomentor"))

try:
	from infomentor import InfoMentorClient
	from infomentor.exceptions import InfoMentorAuthError, InfoMentorConnectionError
	from infomentor.models import TimetableEntry, TimeRegistrationEntry
except ImportError as e:
	print(f"❌ Import error: {e}")
	print("Make sure you're running this script from the repository root directory.")
	sys.exit(1)


async def test_pupil_switching_detailed():
	"""Test pupil switching with detailed debugging."""
	print("🔍 Pupil Switching Debug Test")
	print("=" * 50)
	
	# Get credentials
	username = os.getenv('INFOMENTOR_USERNAME')
	password = os.getenv('INFOMENTOR_PASSWORD')
	
	if not username:
		username = input("InfoMentor username: ")
	if not password:
		password = getpass.getpass("InfoMentor password: ")
	
	# Set up date range
	today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
	start_date = today - timedelta(days=today.weekday())  # Start of current week
	end_date = start_date + timedelta(weeks=2)  # Two weeks from start
	
	print(f"📅 Testing date range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
	
	async with InfoMentorClient() as client:
		# Authenticate
		print("\n🔐 Authenticating...")
		try:
			await client.login(username, password)
			print("	✅ Authentication successful")
		except Exception as e:
			print(f"	❌ Authentication failed: {e}")
			return
		
		# Get pupil IDs
		print("\n👥 Getting pupil information...")
		pupil_ids = await client.get_pupil_ids()
		print(f"	✅ Found {len(pupil_ids)} pupil IDs: {pupil_ids}")
		
		# Get pupil names
		pupils = {}
		for pupil_id in pupil_ids:
			try:
				pupil_info = await client.get_pupil_info(pupil_id)
				if pupil_info and pupil_info.name:
					pupils[pupil_id] = pupil_info.name
					print(f"	  - {pupil_info.name} (ID: {pupil_id})")
				else:
					pupils[pupil_id] = f"Pupil {pupil_id}"
					print(f"	  - Pupil {pupil_id} (ID: {pupil_id}) [name not found]")
			except Exception as e:
				print(f"	  ⚠️  Error getting info for pupil {pupil_id}: {e}")
				pupils[pupil_id] = f"Pupil {pupil_id}"
		
		# Test each pupil individually with detailed switching verification
		for i, (pupil_id, pupil_name) in enumerate(pupils.items(), 1):
			print(f"\n{'='*80}")
			print(f"🧒 Testing Pupil {i}: {pupil_name} (ID: {pupil_id})")
			print(f"{'='*80}")
			
			# Explicit pupil switch with verification
			print(f"\n🔄 Switching to pupil {pupil_id}...")
			try:
				switch_result = await client.switch_pupil(pupil_id)
				print(f"	✅ Switch result: {switch_result}")
				
				# Add extra delay to ensure switch takes effect
				await asyncio.sleep(2.0)
				
				# Verify the switch by checking current context
				print("	🔍 Verifying switch...")
				
			except Exception as e:
				print(f"	❌ Switch failed: {e}")
				continue
			
			# Test timetable for this specific pupil
			print(f"\n📅 Getting timetable for {pupil_name}...")
			try:
				# Make direct API call to see what we get
				calendar_url = "https://hub.infomentor.se/calendarv2/calendarv2/getentries"
				headers = {
					"Accept": "application/json, text/javascript, */*; q=0.01",
					"X-Requested-With": "XMLHttpRequest",
				}
				params = {
					"startDate": start_date.strftime('%Y-%m-%d'),
					"endDate": end_date.strftime('%Y-%m-%d'),
				}
				
				print(f"	📤 Making direct API call to: {calendar_url}")
				print(f"	📅 Parameters: {params}")
				
				async with client._session.get(calendar_url, headers=headers, params=params) as resp:
					print(f"	📥 Response status: {resp.status}")
					
					if resp.status == 200:
						data = await resp.json()
						
						# Save raw response for analysis
						output_dir = Path("debug_output")
						output_dir.mkdir(exist_ok=True)
						timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
						filename = f"raw_calendar_response_{pupil_id}_{pupil_name.replace(' ', '_')}_{timestamp}.json"
						filepath = output_dir / filename
						
						with open(filepath, 'w', encoding='utf-8') as f:
							json.dump(data, f, indent=2, ensure_ascii=False, default=str)
						
						print(f"	💾 Saved raw response to: {filepath}")
						
						# Analyse the response
						if isinstance(data, dict):
							print(f"	📊 Response keys: {list(data.keys())}")
							
							# Look for entries
							entries = data.get('entries', []) or data.get('data', []) or data.get('items', [])
							if entries:
								print(f"	📅 Found {len(entries)} calendar entries")
								for j, entry in enumerate(entries[:3], 1):
									print(f"	  {j}. {entry}")
							else:
								print("	📭 No calendar entries found in response")
								
								# Check if there are any other data fields
								for key, value in data.items():
									if isinstance(value, list) and value:
										print(f"	  📋 Found data in '{key}': {len(value)} items")
									elif value:
										print(f"	  📋 Found data in '{key}': {type(value)}")
						else:
							print(f"	📊 Response type: {type(data)}")
							if isinstance(data, list):
								print(f"	📊 Response length: {len(data)}")
					else:
						error_text = await resp.text()
						print(f"	❌ API call failed: {error_text[:200]}...")
				
				# Also test using the client method
				print(f"\n	🔧 Testing client.get_timetable() method...")
				timetable_entries = await client.get_timetable(pupil_id, start_date, end_date)
				print(f"	📅 Client method returned {len(timetable_entries)} timetable entries")
				
				for j, entry in enumerate(timetable_entries[:3], 1):
					time_str = ""
					if entry.start_time and entry.end_time:
						time_str = f" ({entry.start_time.strftime('%H:%M')}-{entry.end_time.strftime('%H:%M')})"
					print(f"	  {j}. {entry.date.strftime('%Y-%m-%d')}: {entry.title}{time_str}")
				
			except Exception as e:
				print(f"	❌ Timetable test failed: {e}")
				import traceback
				print(f"	🔍 Traceback: {traceback.format_exc()}")
			
			# Test time registration for this specific pupil
			print(f"\n🕐 Getting time registration for {pupil_name}...")
			try:
				time_reg_entries = await client.get_time_registration(pupil_id, start_date, end_date)
				print(f"	🕐 Found {len(time_reg_entries)} time registration entries")
				
				for j, entry in enumerate(time_reg_entries[:3], 1):
					time_str = f"{entry.start_time}-{entry.end_time}" if entry.start_time and entry.end_time else "No times"
					print(f"	  {j}. {entry.date.strftime('%Y-%m-%d')} {time_str}: {entry.status}")
				
			except Exception as e:
				print(f"	❌ Time registration test failed: {e}")
			
			# Add a pause between pupils
			if i < len(pupils):
				print(f"\n⏸️  Pausing before next pupil...")
				await asyncio.sleep(3.0)
		
		print(f"\n✅ Pupil switching debug test completed!")


if __name__ == "__main__":
	asyncio.run(test_pupil_switching_detailed()) 