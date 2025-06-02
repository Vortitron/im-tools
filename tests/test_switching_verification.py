#!/usr/bin/env python3
"""
Pupil Switching Verification Test

This test verifies that switching between pupils actually returns different data.
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


async def make_api_call(client, pupil_name, start_date, end_date):
	"""Make API calls and return the raw responses for comparison."""
	print(f"	📤 Making API calls for {pupil_name}...")
	
	results = {}
	
	# Calendar API call
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
				results['calendar'] = data
				print(f"	  📅 Calendar API: {resp.status} - {len(str(data))} chars")
			else:
				print(f"	  📅 Calendar API: {resp.status} - Failed")
				results['calendar'] = None
	except Exception as e:
		print(f"	  📅 Calendar API: Error - {e}")
		results['calendar'] = None
	
	# Time registration API call
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
				results['time_registration'] = data
				print(f"	  🕐 Time Reg API: {resp.status} - {len(str(data))} chars")
			else:
				print(f"	  🕐 Time Reg API: {resp.status} - Failed")
				results['time_registration'] = None
	except Exception as e:
		print(f"	  🕐 Time Reg API: Error - {e}")
		results['time_registration'] = None
	
	return results


async def test_switching_verification():
	"""Test that switching between pupils returns different data."""
	print("🔍 Pupil Switching Verification Test")
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
		
		# Test each pupil and collect responses
		all_responses = {}
		
		for pupil_id, pupil_name in pupils.items():
			print(f"\n{'='*60}")
			print(f"🧒 Testing {pupil_name} (ID: {pupil_id})")
			print(f"{'='*60}")
			
			# Switch to this pupil
			print(f"🔄 Switching to {pupil_name}...")
			try:
				switch_result = await client.switch_pupil(pupil_id)
				if not switch_result:
					print(f"	❌ Switch failed")
					continue
				print(f"	✅ Switch successful")
				
				# Wait for switch to take effect
				await asyncio.sleep(2.0)
				
			except Exception as e:
				print(f"	❌ Switch error: {e}")
				continue
			
			# Make API calls and collect responses
			responses = await make_api_call(client, pupil_name, start_date, end_date)
			all_responses[pupil_id] = {
				'name': pupil_name,
				'responses': responses
			}
			
			# Brief pause between pupils
			await asyncio.sleep(1.0)
		
		# Compare responses between pupils
		print(f"\n{'='*60}")
		print("📊 COMPARISON ANALYSIS")
		print(f"{'='*60}")
		
		pupil_list = list(all_responses.keys())
		
		if len(pupil_list) >= 2:
			pupil1_id = pupil_list[0]
			pupil2_id = pupil_list[1]
			
			pupil1_data = all_responses[pupil1_id]
			pupil2_data = all_responses[pupil2_id]
			
			print(f"\n🔍 Comparing {pupil1_data['name']} vs {pupil2_data['name']}:")
			
			# Compare calendar responses
			cal1 = pupil1_data['responses'].get('calendar')
			cal2 = pupil2_data['responses'].get('calendar')
			
			if cal1 is not None and cal2 is not None:
				cal1_str = json.dumps(cal1, sort_keys=True)
				cal2_str = json.dumps(cal2, sort_keys=True)
				
				if cal1_str == cal2_str:
					print("	📅 Calendar data: ❌ IDENTICAL (switching not working)")
				else:
					print("	📅 Calendar data: ✅ DIFFERENT (switching working)")
					print(f"	  {pupil1_data['name']}: {len(cal1_str)} chars")
					print(f"	  {pupil2_data['name']}: {len(cal2_str)} chars")
			else:
				print("	📅 Calendar data: ⚠️  One or both failed")
			
			# Compare time registration responses
			tr1 = pupil1_data['responses'].get('time_registration')
			tr2 = pupil2_data['responses'].get('time_registration')
			
			if tr1 is not None and tr2 is not None:
				tr1_str = json.dumps(tr1, sort_keys=True)
				tr2_str = json.dumps(tr2, sort_keys=True)
				
				if tr1_str == tr2_str:
					print("	🕐 Time registration: ❌ IDENTICAL (switching not working)")
				else:
					print("	🕐 Time registration: ✅ DIFFERENT (switching working)")
					print(f"	  {pupil1_data['name']}: {len(tr1_str)} chars")
					print(f"	  {pupil2_data['name']}: {len(tr2_str)} chars")
			else:
				print("	🕐 Time registration: ⚠️  One or both failed")
		
		# Save detailed comparison data
		output_dir = Path("debug_output")
		output_dir.mkdir(exist_ok=True)
		timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
		
		comparison_file = output_dir / f"switching_comparison_{timestamp}.json"
		with open(comparison_file, 'w', encoding='utf-8') as f:
			json.dump(all_responses, f, indent=2, ensure_ascii=False, default=str)
		
		print(f"\n💾 Detailed comparison saved to: {comparison_file}")
		print(f"\n✅ Switching verification test completed!")


if __name__ == "__main__":
	asyncio.run(test_switching_verification()) 