#!/usr/bin/env python3
"""
Comprehensive Test: All Kids Timeregistration and Timetable

This script:
1. Authenticates with InfoMentor
2. Discovers all children
3. Gets timeregistration and timetable data for each child
4. Provides clear output and saves data for analysis

Usage:
	python3 test_all_kids_comprehensive.py
"""

import asyncio
import getpass
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

# Try to load environment variables from .env file
try:
	from dotenv import load_dotenv
	load_dotenv(Path(__file__).parent.parent / '.env')
except ImportError:
	print("💡 Tip: Install python-dotenv to use .env file for credentials:")
print("	pip install python-dotenv")

# Set up logging
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Add the custom_components directory to Python path
sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components" / "infomentor"))

try:
	from infomentor import InfoMentorClient
	from infomentor.exceptions import InfoMentorAuthError, InfoMentorConnectionError
	from infomentor.models import TimetableEntry, TimeRegistrationEntry, ScheduleDay
except ImportError as e:
	print(f"❌ Import error: {e}")
	print("Make sure you're running this script from the repository root directory.")
	sys.exit(1)


class TestResults:
	"""Container for test results and utilities."""
	
	def __init__(self):
		self.output_dir = Path("debug_output")
		self.output_dir.mkdir(exist_ok=True)
		self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
	
	def save_json(self, data: Any, filename: str, description: str = "") -> Path:
		"""Save JSON data to file for analysis."""
		file_path = self.output_dir / f"{self.timestamp}_{filename}"
		with open(file_path, 'w', encoding='utf-8') as f:
			json.dump(data, f, indent=2, ensure_ascii=False, default=str)
		
		print(f"	💾 Saved {description} to: {file_path}")
		return file_path
	
	def print_summary(self, title: str, items: List[Any], max_items: int = 3):
		"""Print a summary of items."""
		print(f"	📊 {title}: {len(items)} items")
		for i, item in enumerate(items[:max_items], 1):
			if hasattr(item, 'date') and hasattr(item, 'title'):
				date_str = item.date.strftime('%Y-%m-%d') if item.date else 'No date'
				print(f"	  {i}. {date_str}: {item.title}")
			elif hasattr(item, 'date') and hasattr(item, 'status'):
				date_str = item.date.strftime('%Y-%m-%d') if item.date else 'No date'
				time_str = f"{item.start_time}-{item.end_time}" if hasattr(item, 'start_time') else ''
				print(f"	  {i}. {date_str} {time_str}: {item.status}")
			else:
				print(f"	  {i}. {str(item)[:100]}")
		
		if len(items) > max_items:
			print(f"	  ... and {len(items) - max_items} more")


async def get_all_pupils(client: InfoMentorClient) -> Dict[str, str]:
	"""Get all pupils from the account."""
	print("👥 Discovering all pupils...")
	
	try:
		pupil_ids = await client.get_pupil_ids()
		pupil_dict = {}
		
		print(f"	✅ Found {len(pupil_ids)} pupil IDs:")
		
		# Get names for each pupil
		for pupil_id in pupil_ids:
			try:
				pupil_info = await client.get_pupil_info(pupil_id)
				if pupil_info and pupil_info.name:
					pupil_dict[pupil_id] = pupil_info.name
					print(f"	  - {pupil_info.name} (ID: {pupil_id})")
				else:
					# Fallback to just using the ID
					pupil_dict[pupil_id] = f"Pupil {pupil_id}"
					print(f"	  - Pupil {pupil_id} (ID: {pupil_id}) [name not found]")
			except Exception as e:
				print(f"	  ⚠️  Error getting info for pupil {pupil_id}: {e}")
				pupil_dict[pupil_id] = f"Pupil {pupil_id}"
		
		return pupil_dict
		
	except Exception as e:
		print(f"	❌ Error getting pupils: {e}")
		return {}


async def test_pupil_timetable(client: InfoMentorClient, pupil_id: str, pupil_name: str, 
							   start_date: datetime, end_date: datetime, 
							   results: TestResults) -> List[TimetableEntry]:
	"""Test timetable retrieval for a specific pupil."""
	print(f"\n📅 Testing timetable for {pupil_name} (ID: {pupil_id})")
	print("-" * 60)
	
	try:
		# Get timetable entries
		timetable_entries = await client.get_timetable(pupil_id, start_date, end_date)
		
		# Save raw data
		timetable_data = [
			{
				'date': entry.date.isoformat() if entry.date else None,
				'start_time': entry.start_time.strftime('%H:%M') if entry.start_time else None,
				'end_time': entry.end_time.strftime('%H:%M') if entry.end_time else None,
				'title': entry.title,
				'subject': entry.subject,
				'teacher': entry.teacher,
				'location': entry.location,
				'description': entry.description
			}
			for entry in timetable_entries
		]
		
		results.save_json(timetable_data, f"timetable_{pupil_id}_{pupil_name.replace(' ', '_')}.json", 
						  f"timetable for {pupil_name}")
		
		results.print_summary(f"Timetable entries for {pupil_name}", timetable_entries)
		
		# Determine child type based on timetable
		if timetable_entries:
			print(f"	🏫 {pupil_name} appears to be a SCHOOL child (has timetable entries)")
		else:
			print(f"	🧸 {pupil_name} appears to be a PRESCHOOL child (no timetable entries)")
		
		return timetable_entries
		
	except Exception as e:
		print(f"	❌ Error getting timetable for {pupil_name}: {e}")
		return []


async def test_pupil_timeregistration(client: InfoMentorClient, pupil_id: str, pupil_name: str,
									   start_date: datetime, end_date: datetime,
									   results: TestResults) -> List[TimeRegistrationEntry]:
	"""Test time registration retrieval for a specific pupil."""
	print(f"\n🕐 Testing time registration for {pupil_name} (ID: {pupil_id})")
	print("-" * 60)
	
	try:
		# Get time registration entries
		time_reg_entries = await client.get_time_registration(pupil_id, start_date, end_date)
		
		# Save raw data
		time_reg_data = [
			{
				'date': entry.date.isoformat() if entry.date else None,
				'start_time': entry.start_time.strftime('%H:%M') if entry.start_time else None,
				'end_time': entry.end_time.strftime('%H:%M') if entry.end_time else None,
				'status': entry.status,
				'type': entry.type,
				'comment': entry.comment
			}
			for entry in time_reg_entries
		]
		
		results.save_json(time_reg_data, f"timeregistration_{pupil_id}_{pupil_name.replace(' ', '_')}.json",
						  f"time registration for {pupil_name}")
		
		results.print_summary(f"Time registration entries for {pupil_name}", time_reg_entries)
		
		return time_reg_entries
		
	except Exception as e:
		print(f"	❌ Error getting time registration for {pupil_name}: {e}")
		return []


async def test_pupil_combined_schedule(client: InfoMentorClient, pupil_id: str, pupil_name: str,
									   start_date: datetime, end_date: datetime,
									   results: TestResults) -> List[ScheduleDay]:
	"""Test combined schedule retrieval for a specific pupil."""
	print(f"\n📋 Testing combined schedule for {pupil_name} (ID: {pupil_id})")
	print("-" * 60)
	
	try:
		# Get combined schedule
		schedule_days = await client.get_schedule(pupil_id, start_date, end_date)
		
		# Save raw data
		schedule_data = []
		for day in schedule_days:
			day_data = {
				'date': day.date.isoformat() if day.date else None,
				'timetable_entries': [
					{
						'start_time': entry.start_time.strftime('%H:%M') if entry.start_time else None,
						'end_time': entry.end_time.strftime('%H:%M') if entry.end_time else None,
						'title': entry.title,
						'subject': entry.subject,
						'teacher': entry.teacher,
						'location': entry.location
					}
					for entry in day.timetable_entries
				],
				'time_registration_entries': [
					{
						'start_time': entry.start_time.strftime('%H:%M') if entry.start_time else None,
						'end_time': entry.end_time.strftime('%H:%M') if entry.end_time else None,
						'status': entry.status,
						'type': entry.type,
						'comment': entry.comment
					}
					for entry in day.time_registrations
				]
			}
			schedule_data.append(day_data)
		
		results.save_json(schedule_data, f"schedule_{pupil_id}_{pupil_name.replace(' ', '_')}.json",
						  f"combined schedule for {pupil_name}")
		
		print(f"	📊 Combined schedule for {pupil_name}: {len(schedule_days)} days")
		for i, day in enumerate(schedule_days[:3], 1):
			date_str = day.date.strftime('%Y-%m-%d') if day.date else 'No date'
			timetable_count = len(day.timetable_entries)
			time_reg_count = len(day.time_registrations)
			print(f"	  {i}. {date_str}: {timetable_count} timetable, {time_reg_count} time reg entries")
		
		if len(schedule_days) > 3:
			print(f"	  ... and {len(schedule_days) - 3} more days")
		
		return schedule_days
		
	except Exception as e:
		print(f"	❌ Error getting combined schedule for {pupil_name}: {e}")
		return []


async def run_comprehensive_test():
	"""Run the comprehensive test for all pupils."""
	print("🚀 InfoMentor Comprehensive Test - All Kids Timeregistration and Timetable")
	print("=" * 80)
	
	# Get credentials
	username = os.getenv('INFOMENTOR_USERNAME')
	password = os.getenv('INFOMENTOR_PASSWORD')
	
	if not username:
		username = input("InfoMentor username: ")
	if not password:
		password = getpass.getpass("InfoMentor password: ")
	
	# Set up date range (current week + next week)
	today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
	start_date = today - timedelta(days=today.weekday())  # Start of current week
	end_date = start_date + timedelta(weeks=2)  # Two weeks from start
	
	print(f"📅 Testing date range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
	
	results = TestResults()
	
	# Authenticate
	print("\n🔐 Authenticating...")
	async with InfoMentorClient() as client:
		try:
			await client.login(username, password)
			print("	✅ Authentication successful")
		except InfoMentorAuthError as e:
			print(f"	❌ Authentication failed: {e}")
			return
		except Exception as e:
			print(f"	❌ Unexpected error during authentication: {e}")
			return
		
		# Get all pupils
		pupils = await get_all_pupils(client)
		
		if not pupils:
			print("❌ No pupils found. Cannot continue.")
			return
		
		# Test each pupil
		all_results = {}
		
		for pupil_id, pupil_name in pupils.items():
			print(f"\n{'='*80}")
			print(f"🧒 Testing {pupil_name} (ID: {pupil_id})")
			print(f"{'='*80}")
			
			pupil_results = {
				'name': pupil_name,
				'id': pupil_id,
				'timetable': [],
				'time_registration': [],
				'combined_schedule': []
			}
			
			# Test timetable
			timetable_entries = await test_pupil_timetable(client, pupil_id, pupil_name, start_date, end_date, results)
			pupil_results['timetable'] = timetable_entries
			
			# Test time registration
			time_reg_entries = await test_pupil_timeregistration(client, pupil_id, pupil_name, start_date, end_date, results)
			pupil_results['time_registration'] = time_reg_entries
			
			# Test combined schedule
			schedule_days = await test_pupil_combined_schedule(client, pupil_id, pupil_name, start_date, end_date, results)
			pupil_results['combined_schedule'] = schedule_days
			
			all_results[pupil_id] = pupil_results
		
		# Save comprehensive results
		summary_data = {
			'test_timestamp': datetime.now().isoformat(),
			'date_range': {
				'start': start_date.isoformat(),
				'end': end_date.isoformat()
			},
			'pupils_tested': len(pupils),
			'results_summary': {
				pupil_id: {
					'name': data['name'],
					'timetable_entries': len(data['timetable']),
					'time_registration_entries': len(data['time_registration']),
					'schedule_days': len(data['combined_schedule']),
					'child_type': 'school' if data['timetable'] else 'preschool'
				}
				for pupil_id, data in all_results.items()
			}
		}
		
		results.save_json(summary_data, "comprehensive_test_summary.json", "comprehensive test summary")
		
		# Print final summary
		print(f"\n{'='*80}")
		print("📊 FINAL SUMMARY")
		print(f"{'='*80}")
		
		for pupil_id, data in all_results.items():
			child_type = 'school' if data['timetable'] else 'preschool'
			print(f"\n👤 {data['name']} ({child_type} child):")
			print(f"	📅 Timetable entries: {len(data['timetable'])}")
			print(f"	🕐 Time registration entries: {len(data['time_registration'])}")
			print(f"	📋 Combined schedule days: {len(data['combined_schedule'])}")
		
		print(f"\n✅ Test completed successfully!")
		print(f"📁 All data saved to: {results.output_dir}")


if __name__ == "__main__":
	asyncio.run(run_comprehensive_test()) 