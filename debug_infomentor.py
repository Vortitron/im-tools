#!/usr/bin/env python3
"""
InfoMentor Debug Script

This script provides detailed debugging information for the InfoMentor integration.
It shows step-by-step authentication flow and raw API responses.

Usage:
    python3 debug_infomentor.py

The script will first try to load credentials from a .env file.
If no .env file is found or credentials are missing, you'll be prompted for them.

Create a .env file with:
    INFOMENTOR_USERNAME=your_username_or_email@example.com
    INFOMENTOR_PASSWORD=your_password_here
"""

import asyncio
import getpass
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Try to load environment variables from .env file
try:
	from dotenv import load_dotenv
	load_dotenv()
except ImportError:
	print("💡 Tip: Install python-dotenv to use .env file for credentials:")
	print("    pip install python-dotenv")

# Set up detailed logging
logging.basicConfig(
	level=logging.DEBUG,
	format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Add the custom_components directory to Python path
sys.path.insert(0, str(Path(__file__).parent / "custom_components" / "infomentor"))

try:
	from infomentor import InfoMentorClient
	from infomentor.auth import InfoMentorAuth
	from infomentor.exceptions import InfoMentorAuthError, InfoMentorConnectionError
except ImportError as e:
	print(f"❌ Import error: {e}")
	print("Make sure you're running this script from the repository root directory.")
	sys.exit(1)


async def debug_authentication_flow(username: str, password: str):
	"""Debug the authentication flow step by step."""
	print("🔍 Debugging Authentication Flow")
	print("=" * 50)
	
	async with InfoMentorClient() as client:
		auth = client.auth
		
		print("\n1️⃣ Testing initial connection to InfoMentor hub...")
		try:
			# Test basic connectivity
			async with client._session.get("https://hub.infomentor.se", allow_redirects=False) as resp:
				print(f"   Status: {resp.status}")
				print(f"   Headers: {dict(resp.headers)}")
				if resp.status in [301, 302, 307, 308]:
					print(f"   Redirect to: {resp.headers.get('Location', 'Unknown')}")
		except Exception as e:
			print(f"   ❌ Connection failed: {e}")
			return False
			
		print("\n2️⃣ Testing authentication flow...")
		try:
			success = await auth.login(username, password)
			if success:
				print("   ✅ Authentication successful!")
				
				print("\n3️⃣ Testing pupil discovery...")
				pupil_ids = auth.pupil_ids
				print(f"   Found pupil IDs: {pupil_ids}")
				
				if pupil_ids:
					print("\n4️⃣ Testing pupil switching...")
					for pupil_id in pupil_ids:
						switch_success = await auth.switch_pupil(pupil_id)
						print(f"   Pupil {pupil_id}: {'✅ Success' if switch_success else '❌ Failed'}")
						
				print("\n5️⃣ Testing data endpoints...")
				
				# Test news endpoint
				try:
					news_url = "https://hub.infomentor.se/Communication/News/GetNewsList"
					async with client._session.get(news_url) as resp:
						print(f"   News endpoint: {resp.status}")
						if resp.status == 200:
							data = await resp.json()
							print(f"   News data keys: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
				except Exception as e:
					print(f"   News endpoint error: {e}")
					
				# Test timeline endpoint
				try:
					timeline_url = "https://hub.infomentor.se/GroupTimeline/GroupTimeline/GetGroupTimelineEntries"
					payload = {"page": 1, "pageSize": 10, "groupId": -1, "returnTimelineConfig": True}
					async with client._session.post(timeline_url, json=payload) as resp:
						print(f"   Timeline endpoint: {resp.status}")
						if resp.status == 200:
							data = await resp.json()
							print(f"   Timeline data keys: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
				except Exception as e:
					print(f"   Timeline endpoint error: {e}")
					
				return True
			else:
				print("   ❌ Authentication failed!")
				return False
				
		except InfoMentorAuthError as e:
			print(f"   ❌ Authentication error: {e}")
			return False
		except Exception as e:
			print(f"   ❌ Unexpected error: {e}")
			return False


async def debug_schedule_endpoints(username: str, password: str):
	"""Debug the schedule endpoints (timetable and time registration)."""
	print("\n🗓️ Debugging Schedule Endpoints")
	print("=" * 50)
	
	async with InfoMentorClient() as client:
		await client.login(username, password)
		
		# Test timetable endpoint
		print("\n📚 Testing timetable endpoint...")
		try:
			timetable_url = "https://hub.infomentor.se/timetable"
			async with client._session.get(timetable_url) as resp:
				print(f"   Status: {resp.status}")
				print(f"   Content-Type: {resp.headers.get('Content-Type', 'Unknown')}")
				print(f"   Content-Length: {resp.headers.get('Content-Length', 'Unknown')}")
				
				if resp.status == 200:
					content = await resp.text()
					print(f"   Content preview (first 200 chars): {content[:200]}...")
					
					# Look for common elements
					if "<title>" in content:
						title_start = content.find("<title>") + 7
						title_end = content.find("</title>", title_start)
						title = content[title_start:title_end] if title_end > title_start else "Unknown"
						print(f"   Page title: {title}")
						
					if "timetable" in content.lower():
						print("   ✅ Page contains 'timetable' content")
					else:
						print("   ⚠️ Page does not contain 'timetable' content")
						
		except Exception as e:
			print(f"   ❌ Timetable endpoint error: {e}")
			
		# Test time registration endpoint
		print("\n🕐 Testing time registration endpoint...")
		try:
			timeregistration_url = "https://hub.infomentor.se/timeregistration"
			async with client._session.get(timeregistration_url) as resp:
				print(f"   Status: {resp.status}")
				print(f"   Content-Type: {resp.headers.get('Content-Type', 'Unknown')}")
				print(f"   Content-Length: {resp.headers.get('Content-Length', 'Unknown')}")
				
				if resp.status == 200:
					content = await resp.text()
					print(f"   Content preview (first 200 chars): {content[:200]}...")
					
					# Look for common elements
					if "<title>" in content:
						title_start = content.find("<title>") + 7
						title_end = content.find("</title>", title_start)
						title = content[title_start:title_end] if title_end > title_start else "Unknown"
						print(f"   Page title: {title}")
						
					if "time" in content.lower() or "registration" in content.lower():
						print("   ✅ Page contains time/registration content")
					else:
						print("   ⚠️ Page does not contain time/registration content")
						
		except Exception as e:
			print(f"   ❌ Time registration endpoint error: {e}")


async def main():
	"""Main debug function."""
	print("InfoMentor Integration Debug Script")
	print("This will debug the integration with detailed logging.\n")
	
	# Try to load credentials from .env file
	username = os.getenv("INFOMENTOR_USERNAME")
	password = os.getenv("INFOMENTOR_PASSWORD")
	
	if not username or not password:
		# If no .env file is found or credentials are missing, prompt for them
		username = input("InfoMentor Username: ").strip()
		if not username:
			print("❌ Username is required!")
			return
		
		password = getpass.getpass("InfoMentor Password: ").strip()
		if not password:
			print("❌ Password is required!")
			return
	
	print("\n🚀 Starting debug analysis...")
	
	# Debug authentication
	auth_success = await debug_authentication_flow(username, password)
	
	if auth_success:
		# Debug schedule endpoints
		await debug_schedule_endpoints(username, password)
		
		print("\n✅ Debug complete! Check the output above for any issues.")
	else:
		print("\n❌ Authentication failed. Please check your credentials and try again.")


if __name__ == "__main__":
	try:
		asyncio.run(main())
	except KeyboardInterrupt:
		print("\n\n⚠️ Debug interrupted by user.")
		sys.exit(1)
	except Exception as e:
		print(f"\n\n❌ Unexpected error: {e}")
		sys.exit(1) 