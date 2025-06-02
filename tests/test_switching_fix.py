#!/usr/bin/env python3
"""
Pupil Switching Fix Test

This test implements and tests a more robust pupil switching mechanism.
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


async def enhanced_pupil_switch(client, pupil_id, pupil_name):
	"""Enhanced pupil switching with verification."""
	print(f"🔄 Enhanced switching to {pupil_name} (ID: {pupil_id})...")
	
	# Step 1: Use the standard switch method
	try:
		switch_result = await client.switch_pupil(pupil_id)
		print(f"	✅ Standard switch result: {switch_result}")
	except Exception as e:
		print(f"	❌ Standard switch failed: {e}")
		return False
	
	# Step 2: Add longer delay
	await asyncio.sleep(3.0)
	
	# Step 3: Try to verify the switch by making a test API call
	try:
		# Make a simple API call that should be pupil-specific
		test_url = "https://hub.infomentor.se/TimeRegistration/TimeRegistration/GetTimeRegistrations/"
		headers = {
			"Accept": "application/json, text/javascript, */*; q=0.01",
			"X-Requested-With": "XMLHttpRequest",
			"Content-Type": "application/json; charset=UTF-8",
		}
		
		# Use a small date range for verification
		today = datetime.now()
		payload = {
			"startDate": today.strftime('%Y-%m-%d'),
			"endDate": today.strftime('%Y-%m-%d'),
		}
		
		async with client._session.post(test_url, headers=headers, json=payload) as resp:
			if resp.status == 200:
				data = await resp.json()
				print(f"	✅ Verification API call successful - got {len(str(data))} chars")
				return True
			else:
				print(f"	⚠️  Verification API call failed: {resp.status}")
				return False
	except Exception as e:
		print(f"	⚠️  Verification API call error: {e}")
		return False


async def test_enhanced_switching():
	"""Test enhanced pupil switching."""
	print("🔧 Enhanced Pupil Switching Test")
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
	start_date = today - timedelta(days=today.weekday())
	end_date = start_date + timedelta(weeks=2)
	
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
		
		# Get pupil information
		pupil_ids = await client.get_pupil_ids()
		print(f"\n👥 Found {len(pupil_ids)} pupils: {pupil_ids}")
		
		if len(pupil_ids) < 2:
			print("❌ Need at least 2 pupils to test switching")
			return
		
		# Get pupil names
		pupils = {}
		for pupil_id in pupil_ids:
			try:
				pupil_info = await client.get_pupil_info(pupil_id)
				pupils[pupil_id] = pupil_info.name if pupil_info and pupil_info.name else f"Pupil {pupil_id}"
			except:
				pupils[pupil_id] = f"Pupil {pupil_id}"
		
		print("	Pupils:")
		for pupil_id, name in pupils.items():
			print(f"	  - {name} (ID: {pupil_id})")
		
		# Test enhanced switching and data collection
		all_data = {}
		
		for pupil_id, pupil_name in pupils.items():
			print(f"\n{'='*70}")
			print(f"🧒 Testing {pupil_name} (ID: {pupil_id})")
			print(f"{'='*70}")
			
			# Enhanced pupil switch
			switch_success = await enhanced_pupil_switch(client, pupil_id, pupil_name)
			if not switch_success:
				print(f"	❌ Enhanced switch failed for {pupil_name}")
				continue
			
			# Collect data with multiple API calls
			pupil_data = {}
			
			# Time registration data
			print(f"\n🕐 Getting time registration for {pupil_name}...")
			try:
				time_reg_url = "https://hub.infomentor.se/TimeRegistration/TimeRegistration/GetTimeRegistrations/"
				headers = {
					"Accept": "application/json, text/javascript, */*; q=0.01",
					"X-Requested-With": "XMLHttpRequest",
					"Content-Type": "application/json; charset=UTF-8",
				}
				payload = {
					"startDate": start_date.strftime('%Y-%m-%d'),
					"endDate": end_date.strftime('%Y-%m-%d'),
				}
				
				async with client._session.post(time_reg_url, headers=headers, json=payload) as resp:
					if resp.status == 200:
						data = await resp.json()
						pupil_data['time_registration'] = data
						print(f"	✅ Time registration: {len(str(data))} chars")
					else:
						print(f"	❌ Time registration failed: {resp.status}")
						pupil_data['time_registration'] = None
			except Exception as e:
				print(f"	❌ Time registration error: {e}")
				pupil_data['time_registration'] = None
			
			# Calendar data
			print(f"\n📅 Getting calendar data for {pupil_name}...")
			try:
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
						pupil_data['calendar'] = data
						print(f"	✅ Calendar: {len(str(data))} chars")
					else:
						print(f"	❌ Calendar failed: {resp.status}")
						pupil_data['calendar'] = None
			except Exception as e:
				print(f"	❌ Calendar error: {e}")
				pupil_data['calendar'] = None
			
			all_data[pupil_id] = {
				'name': pupil_name,
				'data': pupil_data
			}
			
			# Pause between pupils
			await asyncio.sleep(2.0)
		
		# Compare data between pupils
		print(f"\n{'='*70}")
		print("📊 DATA COMPARISON")
		print(f"{'='*70}")
		
		pupil_list = list(all_data.keys())
		if len(pupil_list) >= 2:
			pupil1_id = pupil_list[0]
			pupil2_id = pupil_list[1]
			
			pupil1_data = all_data[pupil1_id]
			pupil2_data = all_data[pupil2_id]
			
			print(f"\n🔍 Comparing {pupil1_data['name']} vs {pupil2_data['name']}:")
			
			# Compare time registration
			tr1 = pupil1_data['data'].get('time_registration')
			tr2 = pupil2_data['data'].get('time_registration')
			
			if tr1 is not None and tr2 is not None:
				tr1_str = json.dumps(tr1, sort_keys=True)
				tr2_str = json.dumps(tr2, sort_keys=True)
				
				if tr1_str == tr2_str:
					print("	🕐 Time registration: ❌ IDENTICAL (switching still not working)")
				else:
					print("	🕐 Time registration: ✅ DIFFERENT (switching working!)")
					print(f"	  {pupil1_data['name']}: {len(tr1_str)} chars")
					print(f"	  {pupil2_data['name']}: {len(tr2_str)} chars")
			
			# Compare calendar
			cal1 = pupil1_data['data'].get('calendar')
			cal2 = pupil2_data['data'].get('calendar')
			
			if cal1 is not None and cal2 is not None:
				cal1_str = json.dumps(cal1, sort_keys=True)
				cal2_str = json.dumps(cal2, sort_keys=True)
				
				if cal1_str == cal2_str:
					print("	📅 Calendar: ❌ IDENTICAL (switching still not working)")
				else:
					print("	📅 Calendar: ✅ DIFFERENT (switching working!)")
					print(f"	  {pupil1_data['name']}: {len(cal1_str)} chars")
					print(f"	  {pupil2_data['name']}: {len(cal2_str)} chars")
		
		# Save comparison data
		output_dir = Path("debug_output")
		output_dir.mkdir(exist_ok=True)
		timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
		
		comparison_file = output_dir / f"enhanced_switching_test_{timestamp}.json"
		with open(comparison_file, 'w', encoding='utf-8') as f:
			json.dump(all_data, f, indent=2, ensure_ascii=False, default=str)
		
		print(f"\n💾 Test data saved to: {comparison_file}")
		print(f"\n✅ Enhanced switching test completed!")


if __name__ == "__main__":
	asyncio.run(test_enhanced_switching()) 