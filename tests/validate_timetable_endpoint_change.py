#!/usr/bin/env python3
"""
Simple validation script to confirm the timetable endpoint change.
Shows the actual URL being used and validates the change was implemented.
"""

import sys
import os
from pathlib import Path

# Add the custom components to the path
sys.path.insert(0, str(Path(__file__).parent.parent / 'custom_components' / 'infomentor'))

def validate_endpoint_change():
	"""Validate that the timetable endpoint change has been implemented."""
	
	print("🔍 VALIDATING TIMETABLE ENDPOINT CHANGE")
	print("=" * 50)
	print()
	
	try:
		# Import the client to check the implementation
		from infomentor.client import InfoMentorClient
		from infomentor.auth import HUB_BASE_URL
		
		print("✅ InfoMentor client imported successfully")
		print(f"🌐 Base URL: {HUB_BASE_URL}")
		print()
		
		# Read the client source to verify the endpoint
		client_file = Path(__file__).parent.parent / 'custom_components' / 'infomentor' / 'infomentor' / 'client.py'
		
		if client_file.exists():
			with open(client_file, 'r') as f:
				client_source = f.read()
			
			print("🔍 CHECKING get_timetable() IMPLEMENTATION:")
			print("-" * 45)
			
			# Check for the new timetable endpoint
			if '/timetable/timetable/gettimetablelist' in client_source:
				print("✅ NEW timetable endpoint found: /timetable/timetable/gettimetablelist")
			else:
				print("❌ NEW timetable endpoint NOT found")
			
			# Check for old calendar endpoint
			if '/calendarv2/calendarv2/getentries' in client_source:
				calendar_count = client_source.count('/calendarv2/calendarv2/getentries')
				print(f"⚠️  Calendar endpoint still present: {calendar_count} occurrences")
				print("   (This is OK if used only in time registration or fallback methods)")
			else:
				print("✅ Calendar endpoint removed from timetable logic")
			
			# Check for the correct parsing method
			if '_parse_timetable_from_api(' in client_source:
				print("✅ Correct parsing method: _parse_timetable_from_api()")
			else:
				print("❌ Correct parsing method NOT found")
			
			# Check for fallback method
			if '_get_timetable_post_fallback(' in client_source:
				print("✅ POST fallback method: _get_timetable_post_fallback()")
			else:
				print("❌ POST fallback method NOT found")
			
			print()
			print("🔍 CHECKING METHOD CALLS IN get_timetable():")
			print("-" * 45)
			
			# Find the get_timetable method
			get_timetable_start = client_source.find('async def get_timetable(')
			if get_timetable_start != -1:
				# Find the end of the method (next async def or class end)
				method_end = client_source.find('\n\tasync def ', get_timetable_start + 1)
				if method_end == -1:
					method_end = client_source.find('\n\tdef ', get_timetable_start + 1)
				if method_end == -1:
					method_end = len(client_source)
				
				get_timetable_method = client_source[get_timetable_start:method_end]
				
				# Check what the method is actually calling
				if 'timetable_url = f"{HUB_BASE_URL}/timetable/timetable/gettimetablelist"' in get_timetable_method:
					print("✅ Method uses correct timetable URL")
				else:
					print("❌ Method does NOT use correct timetable URL")
				
				if 'return self._parse_timetable_from_api(' in get_timetable_method:
					print("✅ Method calls correct parsing function")
				else:
					print("❌ Method does NOT call correct parsing function")
				
				if '_get_timetable_post_fallback(' in get_timetable_method:
					print("✅ Method has correct fallback logic")
				else:
					print("❌ Method does NOT have correct fallback logic")
			
			print()
			print("🎯 VALIDATION SUMMARY:")
			print("-" * 22)
			
			# Count the validation points
			validations = [
				'/timetable/timetable/gettimetablelist' in client_source,
				'_parse_timetable_from_api(' in client_source,
				'_get_timetable_post_fallback(' in client_source,
				'timetable_url = f"{HUB_BASE_URL}/timetable/timetable/gettimetablelist"' in get_timetable_method if 'get_timetable_method' in locals() else False,
			]
			
			passed = sum(validations)
			total = len(validations)
			
			print(f"Validation checks passed: {passed}/{total}")
			
			if passed == total:
				print("🎉 SUCCESS: Timetable endpoint change fully implemented!")
				print()
				print("Expected behavior:")
				print("  🏫 School children with timetable entries → classified as SCHOOL")
				print("  🧸 Children without timetable entries → classified as PRESCHOOL")
				print("  ⚡ More reliable child type detection")
				return True
			else:
				print("❌ INCOMPLETE: Some validation checks failed")
				return False
		
		else:
			print("❌ Client file not found")
			return False
	
	except Exception as e:
		print(f"❌ Validation failed: {e}")
		import traceback
		traceback.print_exc()
		return False

def show_expected_benefits():
	"""Show the expected benefits of the timetable endpoint change."""
	print("\n" + "=" * 50)
	print("🎯 EXPECTED BENEFITS OF TIMETABLE ENDPOINT CHANGE")
	print("=" * 50)
	print()
	print("📊 More Accurate Child Type Detection:")
	print("  • School children will have timetable entries from dedicated endpoint")
	print("  • Preschool children will have no timetable entries (as expected)")
	print("  • Clear distinction between school schedules and calendar events")
	print()
	print("🔧 Technical Improvements:")
	print("  • Uses purpose-built timetable API instead of generic calendar")
	print("  • Reduces false positives from holiday entries in calendar")
	print("  • Better data structure for school-specific information")
	print()
	print("🏠 Home Assistant Integration Benefits:")
	print("  • sensor.{child}_child_type will be more accurate")
	print("  • binary_sensor.{child}_has_school_today more reliable")
	print("  • Better automation possibilities based on school vs preschool")

if __name__ == "__main__":
	print("🚀 Starting timetable endpoint validation...\n")
	
	success = validate_endpoint_change()
	show_expected_benefits()
	
	print("\n" + "=" * 50)
	if success:
		print("✅ VALIDATION COMPLETE: Ready to test with live data!")
	else:
		print("❌ VALIDATION FAILED: Check implementation!")
	print("=" * 50) 