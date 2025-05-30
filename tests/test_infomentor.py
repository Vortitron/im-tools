#!/usr/bin/env python3
"""
InfoMentor Integration Test Script

This script allows you to test the InfoMentor integration functionality
without installing it in Home Assistant. It will authenticate with your
credentials and retrieve data to verify everything is working correctly.

Usage:
    python3 test_infomentor.py

The script will first try to load credentials from a .env file.
If no .env file is found or credentials are missing, you'll be prompted for them.

Create a .env file with:
    INFOMENTOR_USERNAME=your_username_or_email@example.com
    INFOMENTOR_PASSWORD=your_password_here
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
	# Load from parent directory (root of project)
	load_dotenv(Path(__file__).parent.parent / '.env')
except ImportError:
	print("💡 Tip: Install python-dotenv to use .env file for credentials:")
	print("    pip install python-dotenv")

# Add the custom_components directory to Python path (go up one level from tests/)
sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components" / "infomentor"))

try:
	from infomentor import InfoMentorClient
	from infomentor.models import NewsItem, TimelineEntry, ScheduleDay
	from infomentor.exceptions import InfoMentorAuthError, InfoMentorConnectionError
except ImportError as e:
	print(f"❌ Import error: {e}")
	print("Make sure you're running this script from the repository root directory.")
	sys.exit(1)


class InfoMentorTester:
	"""Test class for InfoMentor integration."""
	
	def __init__(self):
		self.client = None
		self.test_results = {
			"authentication": False,
			"pupil_discovery": False,
			"news_retrieval": False,
			"timeline_retrieval": False,
			"schedule_retrieval": False,
		}
		
	async def run_tests(self, username: str, password: str):
		"""Run all tests."""
		print("🔧 InfoMentor Integration Test Suite")
		print("=" * 50)
		
		try:
			async with InfoMentorClient() as client:
				self.client = client
				
				# Test 1: Authentication
				await self.test_authentication(username, password)
				
				# Test 2: Pupil Discovery
				await self.test_pupil_discovery()
				
				# Test 3: Data Retrieval
				pupil_ids = await client.get_pupil_ids()
				if pupil_ids:
					test_pupil = pupil_ids[0]
					await self.test_news_retrieval(test_pupil)
					await self.test_timeline_retrieval(test_pupil)
					await self.test_schedule_retrieval(test_pupil)
				
				# Summary
				self.print_summary()
				
		except Exception as e:
			print(f"❌ Unexpected error: {e}")
			return False
			
		return all(self.test_results.values())
	
	async def test_authentication(self, username: str, password: str):
		"""Test authentication."""
		print("\n🔐 Testing Authentication...")
		try:
			success = await self.client.login(username, password)
			if success:
				print("✅ Authentication successful!")
				self.test_results["authentication"] = True
			else:
				print("❌ Authentication failed!")
				return False
		except InfoMentorAuthError as e:
			print(f"❌ Authentication error: {e}")
			return False
		except Exception as e:
			print(f"❌ Unexpected authentication error: {e}")
			return False
			
	async def test_pupil_discovery(self):
		"""Test pupil discovery."""
		print("\n👥 Testing Pupil Discovery...")
		try:
			pupil_ids = await self.client.get_pupil_ids()
			if pupil_ids:
				print(f"✅ Found {len(pupil_ids)} pupil(s):")
				for i, pupil_id in enumerate(pupil_ids, 1):
					pupil_info = await self.client.get_pupil_info(pupil_id)
					pupil_name = pupil_info.name if pupil_info and pupil_info.name else f"Pupil {pupil_id}"
					print(f"   {i}. {pupil_name} (ID: {pupil_id})")
				self.test_results["pupil_discovery"] = True
			else:
				print("❌ No pupils found!")
				return False
		except Exception as e:
			print(f"❌ Pupil discovery error: {e}")
			return False
			
	async def test_news_retrieval(self, pupil_id: str):
		"""Test news retrieval."""
		print(f"\n📰 Testing News Retrieval for pupil {pupil_id}...")
		try:
			news_items = await self.client.get_news(pupil_id)
			print(f"✅ Retrieved {len(news_items)} news items")
			
			if news_items:
				print("   Latest news items:")
				for i, item in enumerate(news_items[:3], 1):  # Show first 3
					print(f"   {i}. {item.title} ({item.published_date.strftime('%Y-%m-%d')})")
					if item.content:
						content_preview = item.content[:100] + "..." if len(item.content) > 100 else item.content
						print(f"      Preview: {content_preview}")
			else:
				print("   No news items found")
				
			self.test_results["news_retrieval"] = True
		except Exception as e:
			print(f"❌ News retrieval error: {e}")
			
	async def test_timeline_retrieval(self, pupil_id: str):
		"""Test timeline retrieval."""
		print(f"\n📅 Testing Timeline Retrieval for pupil {pupil_id}...")
		try:
			timeline_entries = await self.client.get_timeline(pupil_id)
			print(f"✅ Retrieved {len(timeline_entries)} timeline entries")
			
			if timeline_entries:
				print("   Latest timeline entries:")
				for i, entry in enumerate(timeline_entries[:3], 1):  # Show first 3
					print(f"   {i}. {entry.title} ({entry.entry_type}) - {entry.date.strftime('%Y-%m-%d')}")
					if entry.content:
						content_preview = entry.content[:100] + "..." if len(entry.content) > 100 else entry.content
						print(f"      Content: {content_preview}")
			else:
				print("   No timeline entries found")
				
			self.test_results["timeline_retrieval"] = True
		except Exception as e:
			print(f"❌ Timeline retrieval error: {e}")
			
	async def test_schedule_retrieval(self, pupil_id: str):
		"""Test schedule retrieval."""
		print(f"\n🗓️  Testing Schedule Retrieval for pupil {pupil_id}...")
		try:
			start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
			end_date = start_date + timedelta(weeks=1)
			
			schedule_days = await self.client.get_schedule(pupil_id, start_date, end_date)
			print(f"✅ Retrieved {len(schedule_days)} schedule days")
			
			if schedule_days:
				print("   Weekly schedule overview:")
				for day in schedule_days[:7]:  # Show first week
					day_str = f"   {day.date.strftime('%A, %Y-%m-%d')}"
					
					if day.has_school:
						day_str += " [SCHOOL]"
					if day.has_preschool_or_fritids:
						day_str += " [PRESCHOOL/FRITIDS]"
					if not day.has_school and not day.has_preschool_or_fritids:
						day_str += " [No activities]"
						
					print(day_str)
					
					if day.earliest_start and day.latest_end:
						print(f"      Times: {day.earliest_start.strftime('%H:%M')} - {day.latest_end.strftime('%H:%M')}")
					
					# Show timetable entries
					if day.timetable_entries:
						print(f"      Timetable ({len(day.timetable_entries)} entries):")
						for entry in day.timetable_entries[:2]:  # Show first 2
							if entry.start_time and entry.end_time:
								time_str = f" ({entry.start_time.strftime('%H:%M')}-{entry.end_time.strftime('%H:%M')})"
							else:
								time_str = " (all day)" if getattr(entry, 'is_all_day', False) else ""
							subject = entry.subject or entry.title
							print(f"        - {subject}{time_str}")
					
					# Show time registrations
					if day.time_registrations:
						print(f"      Time registrations ({len(day.time_registrations)} entries):")
						for reg in day.time_registrations[:2]:  # Show first 2
							times = ""
							if reg.start_time and reg.end_time:
								times = f" ({reg.start_time.strftime('%H:%M')}-{reg.end_time.strftime('%H:%M')})"
							status_str = f" [{reg.status}]" if reg.status else ""
							print(f"        - Registration{times}{status_str}")
			else:
				print("   No schedule data found")
				
			# Note about HTML parsing
			print("\n   ⚠️  Note: Schedule parsing is currently under development.")
			print("   The timetable and time registration parsing may show empty data")
			print("   until the HTML parsing is fully implemented.")
				
			self.test_results["schedule_retrieval"] = True
		except Exception as e:
			print(f"❌ Schedule retrieval error: {e}")
			
	def print_summary(self):
		"""Print test summary."""
		print("\n" + "=" * 50)
		print("📋 Test Summary")
		print("=" * 50)
		
		passed = sum(self.test_results.values())
		total = len(self.test_results)
		
		for test_name, result in self.test_results.items():
			status = "✅ PASS" if result else "❌ FAIL"
			test_display = test_name.replace("_", " ").title()
			print(f"{test_display:.<30} {status}")
			
		print(f"\nOverall: {passed}/{total} tests passed")
		
		if passed == total:
			print("\n🎉 All tests passed! The integration should work correctly in Home Assistant.")
		else:
			print(f"\n⚠️  {total - passed} test(s) failed. Please check the errors above.")
			print("Make sure your InfoMentor credentials are correct and you have access to the pupils.")


async def main():
	"""Main test function."""
	print("InfoMentor Integration Test Script")
	print("This will test the integration functionality with your credentials.\n")
	
	# Try to load credentials from .env file
	username = os.getenv("INFOMENTOR_USERNAME")
	password = os.getenv("INFOMENTOR_PASSWORD")
	
	if username and password:
		print("🔑 Using credentials from .env file")
		print(f"   Username: {username}")
		print("   Password: ********")
	else:
		print("📝 No .env file found or credentials missing, please enter them manually:")
		if username:
			print(f"   Found username in .env: {username}")
		else:
			username = input("InfoMentor Username: ").strip()
			if not username:
				print("❌ Username is required!")
				return False
		
		if not password:
			password = getpass.getpass("InfoMentor Password: ").strip()
			if not password:
				print("❌ Password is required!")
				return False
		
	print("\n🚀 Starting tests...")
	
	# Run tests
	tester = InfoMentorTester()
	success = await tester.run_tests(username, password)
	
	if success:
		print("\n✅ Ready for Home Assistant installation!")
	else:
		print("\n❌ Please fix the issues before installing in Home Assistant.")
	
	return success


if __name__ == "__main__":
	try:
		result = asyncio.run(main())
		sys.exit(0 if result else 1)
	except KeyboardInterrupt:
		print("\n\n⚠️  Test interrupted by user.")
		sys.exit(1)
	except Exception as e:
		print(f"\n\n❌ Unexpected error: {e}")
		sys.exit(1) 