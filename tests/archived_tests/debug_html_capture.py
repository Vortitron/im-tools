#!/usr/bin/env python3
"""
InfoMentor HTML Capture and Analysis Script

This script captures the raw HTML from InfoMentor schedule pages for analysis 
and development of proper parsing logic.

Usage:
    python3 debug_html_capture.py

The script will capture HTML from:
- Timetable page
- Time registration page
- Any other schedule-related pages

HTML files will be saved to debug_output/ directory for analysis.
"""

import asyncio
import getpass
import os
import sys
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

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
except ImportError as e:
	print(f"❌ Import error: {e}")
	print("Make sure you're running this script from the repository root directory.")
	sys.exit(1)


def save_html_to_file(content: str, filename: str, description: str = ""):
	"""Save HTML content to file for analysis."""
	output_dir = Path("debug_output")
	output_dir.mkdir(exist_ok=True)
	
	file_path = output_dir / filename
	with open(file_path, 'w', encoding='utf-8') as f:
		f.write(content)
	
	print(f"   💾 Saved {description} to: {file_path}")
	print(f"   📊 Content length: {len(content)} characters")
	
	return file_path


def save_json_to_file(data: dict, filename: str, description: str = ""):
	"""Save JSON data to file for analysis."""
	output_dir = Path("debug_output")
	output_dir.mkdir(exist_ok=True)
	
	file_path = output_dir / filename
	with open(file_path, 'w', encoding='utf-8') as f:
		json.dump(data, f, indent=2, ensure_ascii=False)
	
	print(f"   💾 Saved {description} to: {file_path}")
	print(f"   📊 Data keys: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
	
	return file_path


async def capture_all_data(username: str, password: str):
	"""Capture HTML and test all endpoints in one authenticated session."""
	print("🗓️ Capturing All InfoMentor Data")
	print("=" * 50)
	
	async with InfoMentorClient() as client:
		# Single authentication
		print("\n🔐 Authenticating...")
		success = await client.login(username, password)
		if not success:
			print("❌ Authentication failed!")
			return False
		
		print("✅ Authentication successful!")
		
		# Get pupil IDs
		pupil_ids = await client.get_pupil_ids()
		print(f"📋 Found pupil IDs: {pupil_ids}")
		
		if not pupil_ids:
			print("⚠️ No pupil IDs found!")
			return False
		
		# Test with first pupil
		first_pupil = pupil_ids[0]
		await client.switch_pupil(first_pupil)
		print(f"👤 Switched to pupil: {first_pupil}")
		
		# Define date ranges for testing
		today = datetime.now()
		start_date = today - timedelta(days=7)  # Week ago
		end_date = today + timedelta(days=14)   # Two weeks ahead
		
		print(f"📅 Date range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
		
		timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
		
		# Test news endpoint first (we know this works)
		print("\n📰 Testing news endpoint...")
		try:
			news = await client.get_news()
			print(f"   ✅ Got {len(news)} news items")
		except Exception as e:
			print(f"   ❌ News error: {e}")
		
		# Test timeline endpoint
		print("\n📝 Testing timeline endpoint...")
		try:
			timeline = await client.get_timeline()
			print(f"   ✅ Got {len(timeline)} timeline entries")
		except Exception as e:
			print(f"   ❌ Timeline error: {e}")
		
		# Capture home page to extract app information
		print("\n🏠 Capturing home page...")
		try:
			home_url = "https://hub.infomentor.se/"
			async with client._session.get(home_url) as resp:
				print(f"   Status: {resp.status}")
				if resp.status == 200:
					content = await resp.text()
					filename = f"home_{first_pupil}_{timestamp}.html"
					save_html_to_file(content, filename, "home page HTML")
					
					# Extract app information from JavaScript
					apps = extract_app_info(content)
					if apps:
						print(f"   📱 Found {len(apps)} apps: {[app['codeName'] for app in apps]}")
					
		except Exception as e:
			print(f"   ❌ Error capturing home page: {e}")
		
		# Try specific app endpoints based on what we found
		app_endpoints = [
			("calendarv2", "https://hub.infomentor.se/calendarv2"),
			("timeregistration", "https://hub.infomentor.se/timeregistration"),
			("attendance", "https://hub.infomentor.se/attendance"),
			("timetable", "https://hub.infomentor.se/timetable"),
		]
		
		for app_name, url in app_endpoints:
			print(f"\n📅 Trying {app_name} app...")
			try:
				async with client._session.get(url) as resp:
					print(f"   Status: {resp.status}")
					if resp.status == 200:
						content = await resp.text()
						filename = f"{app_name}_app_{first_pupil}_{timestamp}.html"
						save_html_to_file(content, filename, f"{app_name} app HTML")
						analyse_html_content(content, app_name.title())
					elif resp.status == 404:
						print(f"   ❌ {app_name.title()} app not found")
					else:
						print(f"   ❌ Failed to get {app_name}: HTTP {resp.status}")
			except Exception as e:
				print(f"   ❌ Error capturing {app_name}: {e}")
		
		# Try potential API endpoints for schedule data
		api_endpoints = [
			("calendar_events", "https://hub.infomentor.se/api/calendar/events"),
			("calendar_data", "https://hub.infomentor.se/calendarv2/api/events"),
			("timetable_data", "https://hub.infomentor.se/timetable/api/data"),
			("timeregistration_data", "https://hub.infomentor.se/timeregistration/api/data"),
			("schedule_api", "https://hub.infomentor.se/api/schedule"),
		]
		
		for api_name, url in api_endpoints:
			print(f"\n🔌 Trying {api_name} API...")
			try:
				headers = {
					"Accept": "application/json, text/javascript, */*; q=0.01",
					"X-Requested-With": "XMLHttpRequest",
				}
				async with client._session.get(url, headers=headers) as resp:
					print(f"   Status: {resp.status}")
					if resp.status == 200:
						content_type = resp.headers.get('Content-Type', '')
						if 'application/json' in content_type:
							data = await resp.json()
							filename = f"{api_name}_{first_pupil}_{timestamp}.json"
							save_json_to_file(data, filename, f"{api_name} JSON data")
						else:
							content = await resp.text()
							filename = f"{api_name}_{first_pupil}_{timestamp}.html"
							save_html_to_file(content, filename, f"{api_name} response")
					elif resp.status == 404:
						print(f"   ❌ {api_name} API not found")
					else:
						print(f"   ❌ Failed to get {api_name}: HTTP {resp.status}")
			except Exception as e:
				print(f"   ❌ Error trying {api_name}: {e}")
		
		# Try calendar with date parameters
		print(f"\n📅 Trying calendar with date parameters...")
		try:
			calendar_url = f"https://hub.infomentor.se/calendarv2"
			params = {
				'start': start_date.strftime('%Y-%m-%d'),
				'end': end_date.strftime('%Y-%m-%d'),
			}
			async with client._session.get(calendar_url, params=params) as resp:
				print(f"   Status: {resp.status}")
				if resp.status == 200:
					content = await resp.text()
					filename = f"calendar_with_dates_{first_pupil}_{timestamp}.html"
					save_html_to_file(content, filename, "calendar with date parameters")
					analyse_html_content(content, "Calendar with dates")
		except Exception as e:
			print(f"   ❌ Error trying calendar with dates: {e}")
		
		# Try to capture JavaScript files that might contain API endpoints
		print(f"\n📜 Capturing JavaScript files...")
		js_files = [
			("scripts", "https://hub.infomentor.se/dist/scripts/scripts.js"),
			("locale", "https://hub.infomentor.se/dist/locale/sv-se.js"),
		]
		
		for js_name, js_url in js_files:
			try:
				async with client._session.get(js_url) as resp:
					print(f"   📜 {js_name}.js: {resp.status}")
					if resp.status == 200:
						content = await resp.text()
						filename = f"{js_name}_{timestamp}.js"
						save_html_to_file(content, filename, f"{js_name} JavaScript")
						
						# Look for API endpoints in the JavaScript
						api_patterns = re.findall(r'["\']([^"\']*(?:api|Api)[^"\']*)["\']', content)
						if api_patterns:
							print(f"   🔌 Found API patterns: {api_patterns[:5]}...")
			except Exception as e:
				print(f"   ❌ Error capturing {js_name}: {e}")
		
		# Try some common InfoMentor API patterns based on what we've seen
		print(f"\n🔍 Trying InfoMentor-specific API patterns...")
		im_api_endpoints = [
			("pupil_switch", f"https://hub.infomentor.se/Account/PupilSwitcher/SwitchPupil/{first_pupil}"),
			("avatar", f"https://hub.infomentor.se/Account/Avatar/GetAvatar/{first_pupil}?api=IM1"),
			("calendar_app_data", "https://hub.infomentor.se/calendarv2/calendarv2/appData"),
			("timeregistration_app_data", "https://hub.infomentor.se/timeregistration/timeregistration/appData"),
			("attendance_app_data", "https://hub.infomentor.se/attendance/attendance/appData"),
		]
		
		for api_name, url in im_api_endpoints:
			print(f"\n🔌 Trying {api_name}...")
			try:
				headers = {
					"Accept": "application/json, text/javascript, */*; q=0.01",
					"X-Requested-With": "XMLHttpRequest",
					"Content-Type": "application/json; charset=UTF-8",
				}
				
				# Some endpoints might need POST with empty body
				if "appData" in api_name:
					async with client._session.post(url, headers=headers, json={}) as resp:
						print(f"   Status: {resp.status}")
						if resp.status == 200:
							content_type = resp.headers.get('Content-Type', '')
							if 'application/json' in content_type:
								data = await resp.json()
								filename = f"{api_name}_{first_pupil}_{timestamp}.json"
								save_json_to_file(data, filename, f"{api_name} JSON data")
							else:
								content = await resp.text()
								filename = f"{api_name}_{first_pupil}_{timestamp}.html"
								save_html_to_file(content, filename, f"{api_name} response")
				else:
					async with client._session.get(url, headers=headers) as resp:
						print(f"   Status: {resp.status}")
						if resp.status == 200:
							content_type = resp.headers.get('Content-Type', '')
							if 'application/json' in content_type:
								data = await resp.json()
								filename = f"{api_name}_{first_pupil}_{timestamp}.json"
								save_json_to_file(data, filename, f"{api_name} JSON data")
							else:
								content = await resp.text()
								filename = f"{api_name}_{first_pupil}_{timestamp}.html"
								save_html_to_file(content, filename, f"{api_name} response")
			except Exception as e:
				print(f"   ❌ Error trying {api_name}: {e}")
		
		# Now try the actual schedule API endpoints we discovered!
		print(f"\n🎯 Trying discovered schedule API endpoints...")
		
		# Calendar entries endpoint
		print(f"\n📅 Trying calendar entries API...")
		try:
			calendar_entries_url = "https://hub.infomentor.se/calendarv2/calendarv2/getentries"
			headers = {
				"Accept": "application/json, text/javascript, */*; q=0.01",
				"X-Requested-With": "XMLHttpRequest",
				"Content-Type": "application/json; charset=UTF-8",
			}
			
			# Try with date parameters
			payload = {
				"startDate": start_date.strftime('%Y-%m-%d'),
				"endDate": end_date.strftime('%Y-%m-%d'),
			}
			
			async with client._session.post(calendar_entries_url, headers=headers, json=payload) as resp:
				print(f"   Status: {resp.status}")
				if resp.status == 200:
					data = await resp.json()
					filename = f"calendar_entries_{first_pupil}_{timestamp}.json"
					save_json_to_file(data, filename, "calendar entries JSON data")
					print(f"   🎉 SUCCESS! Got calendar entries data!")
				else:
					print(f"   ❌ Failed: HTTP {resp.status}")
					error_text = await resp.text()
					print(f"   Error: {error_text[:200]}...")
		except Exception as e:
			print(f"   ❌ Error trying calendar entries: {e}")
		
		# Time registration endpoint
		print(f"\n🕐 Trying time registration API...")
		try:
			time_reg_url = "https://hub.infomentor.se/TimeRegistration/TimeRegistration/GetTimeRegistrations/"
			headers = {
				"Accept": "application/json, text/javascript, */*; q=0.01",
				"X-Requested-With": "XMLHttpRequest",
				"Content-Type": "application/json; charset=UTF-8",
			}
			
			# Try with date parameters
			payload = {
				"startDate": start_date.strftime('%Y-%m-%d'),
				"endDate": end_date.strftime('%Y-%m-%d'),
			}
			
			async with client._session.post(time_reg_url, headers=headers, json=payload) as resp:
				print(f"   Status: {resp.status}")
				if resp.status == 200:
					data = await resp.json()
					filename = f"time_registrations_{first_pupil}_{timestamp}.json"
					save_json_to_file(data, filename, "time registrations JSON data")
					print(f"   🎉 SUCCESS! Got time registration data!")
				else:
					print(f"   ❌ Failed: HTTP {resp.status}")
					error_text = await resp.text()
					print(f"   Error: {error_text[:200]}...")
		except Exception as e:
			print(f"   ❌ Error trying time registration: {e}")
		
		# Try time registration calendar data
		print(f"\n📅 Trying time registration calendar data...")
		try:
			time_cal_url = "https://hub.infomentor.se/TimeRegistration/TimeRegistration/GetCalendarData/"
			headers = {
				"Accept": "application/json, text/javascript, */*; q=0.01",
				"X-Requested-With": "XMLHttpRequest",
				"Content-Type": "application/json; charset=UTF-8",
			}
			
			# Try with date parameters
			payload = {
				"startDate": start_date.strftime('%Y-%m-%d'),
				"endDate": end_date.strftime('%Y-%m-%d'),
			}
			
			async with client._session.post(time_cal_url, headers=headers, json=payload) as resp:
				print(f"   Status: {resp.status}")
				if resp.status == 200:
					data = await resp.json()
					filename = f"time_calendar_data_{first_pupil}_{timestamp}.json"
					save_json_to_file(data, filename, "time registration calendar JSON data")
					print(f"   🎉 SUCCESS! Got time registration calendar data!")
				else:
					print(f"   ❌ Failed: HTTP {resp.status}")
					error_text = await resp.text()
					print(f"   Error: {error_text[:200]}...")
		except Exception as e:
			print(f"   ❌ Error trying time registration calendar: {e}")
		
		# Try to find timetable API if it exists
		print(f"\n📚 Trying to find timetable API...")
		try:
			# First try to get timetable app data
			timetable_app_url = "https://hub.infomentor.se/timetable/timetable/appData"
			headers = {
				"Accept": "application/json, text/javascript, */*; q=0.01",
				"X-Requested-With": "XMLHttpRequest",
				"Content-Type": "application/json; charset=UTF-8",
			}
			
			async with client._session.post(timetable_app_url, headers=headers, json={}) as resp:
				print(f"   Timetable app data status: {resp.status}")
				if resp.status == 200:
					data = await resp.json()
					filename = f"timetable_app_data_{first_pupil}_{timestamp}.json"
					save_json_to_file(data, filename, "timetable app data JSON")
					print(f"   🎉 SUCCESS! Got timetable app data!")
					
					# Look for URLs in the timetable app data
					if 'urls' in data:
						print(f"   📋 Timetable URLs found: {list(data['urls'].keys())}")
				else:
					print(f"   ❌ Failed: HTTP {resp.status}")
		except Exception as e:
			print(f"   ❌ Error trying timetable app data: {e}")
		
		return True


def extract_app_info(html_content: str) -> list:
	"""Extract app information from the home page JavaScript."""
	try:
		# Look for IMHome.home.homeData pattern
		match = re.search(r'IMHome\.home\.homeData\s*=\s*({.*?});', html_content, re.DOTALL)
		if match:
			json_str = match.group(1)
			data = json.loads(json_str)
			return data.get('apps', [])
	except Exception as e:
		print(f"   ⚠️ Failed to extract app info: {e}")
	return []


def analyse_html_content(content: str, page_type: str):
	"""Perform quick analysis of HTML content."""
	print(f"   🔍 Quick analysis of {page_type} HTML:")
	
	# Basic structure analysis
	if "<table" in content:
		table_count = content.count("<table")
		print(f"   📊 Found {table_count} table(s)")
	
	if "<div" in content:
		div_count = content.count("<div")
		print(f"   📦 Found {div_count} div(s)")
	
	# Look for schedule-related keywords
	keywords = [
		"timetable", "schedule", "time", "class", "lesson", "period",
		"subject", "teacher", "room", "date", "calendar", "appointment",
		"timeslot", "hour", "minute", "week", "day"
	]
	
	found_keywords = []
	for keyword in keywords:
		if keyword.lower() in content.lower():
			count = content.lower().count(keyword.lower())
			found_keywords.append(f"{keyword}({count})")
	
	if found_keywords:
		print(f"   🔑 Keywords found: {', '.join(found_keywords)}")
	else:
		print(f"   ⚠️ No schedule-related keywords found")
	
	# Look for data structures (JSON, arrays, etc.)
	if "var " in content and ("{" in content or "[" in content):
		print(f"   💾 Possible JavaScript data structures found")
	
	# Look for specific InfoMentor patterns
	if "infomentor" in content.lower():
		im_count = content.lower().count("infomentor")
		print(f"   🏫 'InfoMentor' appears {im_count} times")
	
	# Look for form inputs that might indicate interactive elements
	if "<input" in content:
		input_count = content.count("<input")
		print(f"   📝 Found {input_count} input field(s)")
	
	# Look for specific schedule table structures
	if 'class="table' in content or 'id="table' in content:
		print(f"   📋 Found table with class/id attributes (likely schedule data)")
	
	# Look for time patterns
	import re
	time_patterns = re.findall(r'\b\d{1,2}:\d{2}\b', content)
	if time_patterns:
		print(f"   🕐 Found {len(time_patterns)} time patterns: {time_patterns[:5]}...")


async def main():
	"""Main function."""
	print("InfoMentor HTML Capture Script")
	print("This will capture HTML content from schedule pages for analysis.\n")
	
	# Try to load credentials from .env file
	username = os.getenv("INFOMENTOR_USERNAME")
	password = os.getenv("INFOMENTOR_PASSWORD")
	
	if not username:
		username = input("InfoMentor Username: ").strip()
		if not username:
			print("❌ Username is required!")
			return
	
	if not password:
		password = getpass.getpass("InfoMentor Password: ").strip()
		if not password:
			print("❌ Password is required!")
			return
	
	print(f"\n🚀 Starting capture for user: {username}")
	
	success = await capture_all_data(username, password)
	
	if success:
		print("\n✅ Data capture complete!")
		print("📁 Check the debug_output/ directory for captured HTML files.")
		print("💡 Next step: Analyse the HTML structure to implement proper parsing.")
	else:
		print("\n❌ Data capture failed.")


if __name__ == "__main__":
	try:
		asyncio.run(main())
	except KeyboardInterrupt:
		print("\n\n⚠️ Capture interrupted by user.")
		sys.exit(1)
	except Exception as e:
		print(f"\n\n❌ Unexpected error: {e}")
		sys.exit(1) 