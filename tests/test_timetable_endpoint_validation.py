#!/usr/bin/env python3
"""
Test script to validate timetable endpoint and child type detection.
Tests that children with timetable entries are marked as school children,
and those without are marked as preschool children.
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta
import os

# Add the custom components to the path
sys.path.insert(0, str(Path(__file__).parent.parent / 'custom_components' / 'infomentor'))

from infomentor import InfoMentorClient

async def test_timetable_child_detection():
	"""Test that timetable endpoint correctly identifies school vs preschool children."""
	username = os.getenv("INFOMENTOR_USERNAME")
	password = os.getenv("INFOMENTOR_PASSWORD")
	
	if not username or not password:
		print("❌ Missing credentials in environment variables")
		print("   Please set INFOMENTOR_USERNAME and INFOMENTOR_PASSWORD")
		return False
	
	print("🧪 Testing Timetable Endpoint & Child Type Detection")
	print("=" * 60)
	
	async with InfoMentorClient() as client:
		try:
			# Authenticate
			print("🔐 Authenticating...")
			if not await client.login(username, password):
				print("❌ Authentication failed")
				return False
			
			print("✅ Authentication successful!")
			
			# Get all pupils
			pupil_ids = await client.get_pupil_ids()
			print(f"📋 Found {len(pupil_ids)} pupils: {pupil_ids}")
			
			if not pupil_ids:
				print("❌ No pupils found")
				return False
			
			# Test period - check a month to get good data
			start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
			end_date = start_date + timedelta(weeks=4)
			
			print(f"\n📅 Testing period: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
			print("=" * 60)
			
			child_analysis = {}
			all_tests_passed = True
			
			for pupil_id in pupil_ids:
				print(f"\n👤 Testing pupil: {pupil_id}")
				print("-" * 40)
				
				# Get pupil info for name
				pupil_info = await client.get_pupil_info(pupil_id)
				pupil_name = pupil_info.name if pupil_info else f"Pupil {pupil_id}"
				print(f"📝 Name: {pupil_name}")
				
				# Test the NEW timetable endpoint
				print("📚 Testing timetable endpoint...")
				try:
					timetable_entries = await client.get_timetable(pupil_id, start_date, end_date)
					print(f"   ✅ Found {len(timetable_entries)} timetable entries")
					
					# Show sample entries
					if timetable_entries:
						print("   📋 Sample timetable entries:")
						for i, entry in enumerate(timetable_entries[:3]):
							date_str = entry.date.strftime('%Y-%m-%d')
							subject = entry.subject or entry.title or 'No subject'
							if entry.start_time and entry.end_time:
								time_str = f" ({entry.start_time.strftime('%H:%M')}-{entry.end_time.strftime('%H:%M')})"
							else:
								time_str = " (All day)" if getattr(entry, 'is_all_day', False) else " (No times)"
							print(f"      {i+1}. {date_str}: {subject}{time_str}")
					
				except Exception as e:
					print(f"   ❌ Timetable error: {e}")
					timetable_entries = []
					all_tests_passed = False
				
				# Test time registration for comparison
				print("⏰ Testing time registration...")
				try:
					time_registrations = await client.get_time_registration(pupil_id, start_date, end_date)
					print(f"   ✅ Found {len(time_registrations)} time registration entries")
					
					# Show sample registrations
					if time_registrations:
						print("   📋 Sample time registrations:")
						for i, reg in enumerate(time_registrations[:3]):
							date_str = reg.date.strftime('%Y-%m-%d')
							if reg.start_time and reg.end_time:
								time_str = f" ({reg.start_time.strftime('%H:%M')}-{reg.end_time.strftime('%H:%M')})"
							else:
								time_str = " (Times TBD)"
							status = f" [{reg.status}]" if hasattr(reg, 'status') else ""
							print(f"      {i+1}. {date_str}: {time_str}{status}")
				
				except Exception as e:
					print(f"   ❌ Time registration error: {e}")
					time_registrations = []
					all_tests_passed = False
				
				# Determine child type based on timetable entries
				has_timetable = len(timetable_entries) > 0
				has_time_registration = len(time_registrations) > 0
				
				if has_timetable:
					child_type = "SCHOOL"
					print(f"🏫 Classification: {child_type} CHILD")
					print(f"   Reason: Has {len(timetable_entries)} timetable entries")
				else:
					child_type = "PRESCHOOL"
					print(f"🧸 Classification: {child_type} CHILD")
					print(f"   Reason: No timetable entries found")
				
				# Store analysis
				child_analysis[pupil_id] = {
					'name': pupil_name,
					'child_type': child_type,
					'timetable_count': len(timetable_entries),
					'time_registration_count': len(time_registrations),
					'has_timetable': has_timetable,
					'has_time_registration': has_time_registration
				}
				
				# Additional validation
				if has_time_registration:
					print(f"📝 Additional info: Has {len(time_registrations)} time registration entries")
				
			# Summary analysis
			print(f"\n{'='*60}")
			print("📊 CHILD TYPE DETECTION SUMMARY")
			print(f"{'='*60}")
			
			school_children = [p for p in child_analysis.values() if p['child_type'] == 'SCHOOL']
			preschool_children = [p for p in child_analysis.values() if p['child_type'] == 'PRESCHOOL']
			
			print(f"🏫 School children: {len(school_children)}")
			for child in school_children:
				print(f"   - {child['name']}: {child['timetable_count']} timetable entries")
			
			print(f"\n🧸 Preschool children: {len(preschool_children)}")
			for child in preschool_children:
				print(f"   - {child['name']}: {child['time_registration_count']} time registrations")
			
			# Validation checks
			print(f"\n🔍 VALIDATION CHECKS")
			print("-" * 30)
			
			# Check 1: School children should have timetable entries
			school_with_timetable = all(child['has_timetable'] for child in school_children)
			print(f"✅ All school children have timetable entries: {school_with_timetable}")
			
			# Check 2: Preschool children should NOT have timetable entries
			preschool_without_timetable = all(not child['has_timetable'] for child in preschool_children)
			print(f"✅ All preschool children lack timetable entries: {preschool_without_timetable}")
			
			# Check 3: Both types can have time registrations (fritids/preschool)
			children_with_time_reg = [child for child in child_analysis.values() if child['has_time_registration']]
			print(f"📝 Children with time registrations: {len(children_with_time_reg)}")
			
			# Overall result
			detection_working = school_with_timetable and preschool_without_timetable and all_tests_passed
			
			print(f"\n{'='*60}")
			if detection_working:
				print("🎉 SUCCESS: Child type detection is working correctly!")
				print("✅ Timetable endpoint properly identifies school vs preschool children")
			else:
				print("❌ ISSUES DETECTED in child type detection")
				if not all_tests_passed:
					print("   - Some API calls failed")
				if not school_with_timetable:
					print("   - School children missing timetable entries")
				if not preschool_without_timetable:
					print("   - Preschool children have unexpected timetable entries")
			
			return detection_working
			
		except Exception as e:
			print(f"❌ Test failed with error: {e}")
			import traceback
			traceback.print_exc()
			return False

if __name__ == "__main__":
	result = asyncio.run(test_timetable_child_detection())
	sys.exit(0 if result else 1) 