#!/usr/bin/env python3
"""
Final Pupil Switching Verification Test

This test demonstrates that the pupil switching fix is working correctly
by showing different data for each child.
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


async def verify_switching_fix():
	"""Verify that the pupil switching fix is working correctly."""
	print("✅ Final Pupil Switching Verification Test")
	print("=" * 60)
	print("This test demonstrates that the 302 redirect fix is working")
	print("=" * 60)
	
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
		print(f"\n👥 Found {len(pupil_ids)} pupils")
		
		if len(pupil_ids) < 2:
			print("❌ Need at least 2 pupils to verify switching")
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
		
		# Test each pupil and collect time registration data
		time_reg_data = {}
		
		for pupil_id, pupil_name in pupils.items():
			print(f"\n{'='*50}")
			print(f"🧒 Testing {pupil_name}")
			print(f"{'='*50}")
			
			# Switch to this pupil
			print(f"🔄 Switching to {pupil_name}...")
			try:
				switch_result = await client.switch_pupil(pupil_id)
				if not switch_result:
					print(f"	❌ Switch failed")
					continue
				print(f"	✅ Switch successful")
				await asyncio.sleep(2.0)
			except Exception as e:
				print(f"	❌ Switch error: {e}")
				continue
			
			# Get time registration data
			print(f"🕐 Getting time registration...")
			try:
				time_reg_entries = await client.get_time_registration(pupil_id, start_date, end_date)
				time_reg_data[pupil_id] = {
					'name': pupil_name,
					'entries': time_reg_entries,
					'count': len(time_reg_entries)
				}
				
				print(f"	✅ Found {len(time_reg_entries)} time registration entries")
				
				# Show first few entries with times
				for i, entry in enumerate(time_reg_entries[:3], 1):
					time_str = f"{entry.start_time}-{entry.end_time}" if entry.start_time and entry.end_time else "No times"
					print(f"	  {i}. {entry.date.strftime('%Y-%m-%d')} {time_str}: {entry.status}")
				
				if len(time_reg_entries) > 3:
					print(f"	  ... and {len(time_reg_entries) - 3} more")
				
			except Exception as e:
				print(f"	❌ Time registration error: {e}")
				time_reg_data[pupil_id] = {
					'name': pupil_name,
					'entries': [],
					'count': 0,
					'error': str(e)
				}
		
		# Verify that data is different
		print(f"\n{'='*60}")
		print("🔍 VERIFICATION RESULTS")
		print(f"{'='*60}")
		
		pupil_list = list(time_reg_data.keys())
		if len(pupil_list) >= 2:
			pupil1_id = pupil_list[0]
			pupil2_id = pupil_list[1]
			
			pupil1_data = time_reg_data[pupil1_id]
			pupil2_data = time_reg_data[pupil2_id]
			
			print(f"\n📊 Comparing {pupil1_data['name']} vs {pupil2_data['name']}:")
			print(f"	{pupil1_data['name']}: {pupil1_data['count']} entries")
			print(f"	{pupil2_data['name']}: {pupil2_data['count']} entries")
			
			# Compare the actual data
			if pupil1_data['count'] > 0 and pupil2_data['count'] > 0:
				# Compare first entry times
				entry1 = pupil1_data['entries'][0]
				entry2 = pupil2_data['entries'][0]
				
				time1 = f"{entry1.start_time}-{entry1.end_time}" if entry1.start_time and entry1.end_time else "No times"
				time2 = f"{entry2.start_time}-{entry2.end_time}" if entry2.start_time and entry2.end_time else "No times"
				
				print(f"	{pupil1_data['name']} first entry: {time1}")
				print(f"	{pupil2_data['name']} first entry: {time2}")
				
				if time1 != time2:
					print(f"\n🎉 SUCCESS: Pupil switching is working correctly!")
					print(f"	✅ Different time registration data for each child")
					print(f"	✅ 302 redirect fix is working")
				else:
					print(f"\n⚠️  WARNING: Time registration data appears identical")
					print(f"	This might indicate the children have the same schedule")
			else:
				print(f"\n⚠️  Cannot compare - insufficient data")
		
		# Save verification results
		output_dir = Path("debug_output")
		output_dir.mkdir(exist_ok=True)
		timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
		
		verification_file = output_dir / f"switching_verification_final_{timestamp}.json"
		with open(verification_file, 'w', encoding='utf-8') as f:
			# Convert entries to serializable format
			serializable_data = {}
			for pupil_id, data in time_reg_data.items():
				serializable_data[pupil_id] = {
					'name': data['name'],
					'count': data['count'],
					'entries': [
						{
							'date': entry.date.isoformat(),
							'start_time': entry.start_time,
							'end_time': entry.end_time,
							'status': entry.status,
							'type': entry.type,
							'comment': entry.comment
						} for entry in data['entries']
					] if 'entries' in data else [],
					'error': data.get('error')
				}
			
			json.dump(serializable_data, f, indent=2, ensure_ascii=False)
		
		print(f"\n💾 Verification results saved to: {verification_file}")
		print(f"\n✅ Final verification test completed!")


if __name__ == "__main__":
	asyncio.run(verify_switching_fix()) 