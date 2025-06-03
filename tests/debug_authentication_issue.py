#!/usr/bin/env python3
"""
Debug script to investigate the authentication issue causing HandleUnauthorizedRequest errors.
This script will test the authentication flow and identify where it's failing.
"""

import asyncio
import os
import sys
import aiohttp
import logging
from pathlib import Path
from datetime import datetime

# Setup path
sys.path.insert(0, str(Path(__file__).parent.parent / 'custom_components' / 'infomentor'))

from infomentor.client import InfoMentorClient
from infomentor.auth import HUB_BASE_URL, DEFAULT_HEADERS

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
_LOGGER = logging.getLogger(__name__)

async def test_authentication_flow():
	"""Test the current authentication flow to identify issues."""
	
	print("🔧 DEBUGGING AUTHENTICATION ISSUE")
	print("=" * 50)
	
	username = os.getenv('INFOMENTOR_USERNAME')
	password = os.getenv('INFOMENTOR_PASSWORD')
	
	if not username or not password:
		print("❌ Missing environment variables: INFOMENTOR_USERNAME, INFOMENTOR_PASSWORD")
		return False
	
	print(f"📋 Testing with username: {username}")
	
	async with InfoMentorClient() as client:
		try:
			# Step 1: Test authentication
			print("\n🔐 Step 1: Testing authentication...")
			login_success = await client.login(username, password)
			print(f"   Login result: {'✅ SUCCESS' if login_success else '❌ FAILED'}")
			
			if not login_success:
				print("   Authentication failed - cannot proceed")
				return False
			
			# Step 2: Get pupil IDs
			print("\n👥 Step 2: Getting pupil IDs...")
			pupil_ids = await client.get_pupil_ids()
			print(f"   Found {len(pupil_ids)} pupils: {pupil_ids}")
			
			if not pupil_ids:
				print("   No pupils found - authentication may not be complete")
				return False
			
			# Step 3: Test pupil switching
			print("\n🔄 Step 3: Testing pupil switching...")
			for pupil_id in pupil_ids:
				print(f"   Attempting to switch to pupil {pupil_id}...")
				switch_result = await client.switch_pupil(pupil_id)
				print(f"   Switch result: {'✅ SUCCESS' if switch_result else '❌ FAILED'}")
				
				if not switch_result:
					print(f"   ⚠️  Failed to switch to pupil {pupil_id}")
					
				# Brief delay between switches
				await asyncio.sleep(1.0)
			
			# Step 4: Test timetable retrieval (the failing endpoint)
			print("\n📅 Step 4: Testing timetable retrieval...")
			for pupil_id in pupil_ids[:1]:  # Test with first pupil only
				print(f"   Testing timetable for pupil {pupil_id}...")
				
				try:
					timetable_entries = await client.get_timetable(pupil_id)
					print(f"   Timetable result: {len(timetable_entries)} entries")
					
					if timetable_entries:
						sample = timetable_entries[0]
						print(f"   Sample entry: {sample.title} on {sample.date}")
					else:
						print("   ⚠️  No timetable entries returned (may be normal)")
						
				except Exception as e:
					print(f"   ❌ Timetable retrieval failed: {e}")
			
			# Step 5: Test time registration retrieval
			print("\n⏰ Step 5: Testing time registration retrieval...")
			for pupil_id in pupil_ids[:1]:  # Test with first pupil only
				print(f"   Testing time registration for pupil {pupil_id}...")
				
				try:
					time_reg_entries = await client.get_time_registration(pupil_id)
					print(f"   Time registration result: {len(time_reg_entries)} entries")
					
					if time_reg_entries:
						sample = time_reg_entries[0]
						print(f"   Sample entry: {sample.type} on {sample.date}")
					else:
						print("   ⚠️  No time registration entries returned (may be normal)")
						
				except Exception as e:
					print(f"   ❌ Time registration retrieval failed: {e}")
			
			# Step 6: Test direct API calls to diagnose the exact error
			print("\n🔍 Step 6: Testing direct API calls...")
			await test_direct_api_calls(client)
			
			return True
			
		except Exception as e:
			print(f"❌ Authentication test failed: {e}")
			import traceback
			traceback.print_exc()
			return False

async def test_direct_api_calls(client):
	"""Test direct API calls to see the exact error responses."""
	
	timetable_url = f"{HUB_BASE_URL}/timetable/timetable/gettimetablelist"
	time_reg_url = f"{HUB_BASE_URL}/TimeRegistration/TimeRegistration/GetTimeRegistrations/"
	
	headers = DEFAULT_HEADERS.copy()
	headers.update({
		"Accept": "application/json, text/javascript, */*; q=0.01",
		"X-Requested-With": "XMLHttpRequest",
	})
	
	params = {
		"startDate": "2025-06-01",
		"endDate": "2025-06-08",
	}
	
	# Test timetable endpoint
	print(f"   🔗 Testing direct call to: {timetable_url}")
	try:
		async with client._session.get(timetable_url, headers=headers, params=params) as resp:
			print(f"      Status: {resp.status}")
			print(f"      Headers: {dict(resp.headers)}")
			
			response_text = await resp.text()
			print(f"      Response: {response_text[:200]}...")
			
			if "HandleUnauthorizedRequest" in response_text:
				print("      🚨 Found HandleUnauthorizedRequest - session expired!")
			elif "AjaxError" in response_text:
				print("      🚨 Found AjaxError - API error!")
			elif resp.status == 500:
				print("      🚨 HTTP 500 - server error!")
				
	except Exception as e:
		print(f"      ❌ Direct timetable call failed: {e}")
	
	# Test time registration endpoint
	print(f"   🔗 Testing direct call to: {time_reg_url}")
	try:
		async with client._session.get(time_reg_url, headers=headers, params=params) as resp:
			print(f"      Status: {resp.status}")
			print(f"      Headers: {dict(resp.headers)}")
			
			response_text = await resp.text()
			print(f"      Response: {response_text[:200]}...")
			
			if "HandleUnauthorizedRequest" in response_text:
				print("      🚨 Found HandleUnauthorizedRequest - session expired!")
			elif "AjaxError" in response_text:
				print("      🚨 Found AjaxError - API error!")
			elif resp.status == 500:
				print("      🚨 HTTP 500 - server error!")
				
	except Exception as e:
		print(f"      ❌ Direct time registration call failed: {e}")

async def test_session_persistence():
	"""Test if the session is maintaining authentication across requests."""
	
	print("\n🔍 TESTING SESSION PERSISTENCE")
	print("=" * 40)
	
	username = os.getenv('INFOMENTOR_USERNAME')
	password = os.getenv('INFOMENTOR_PASSWORD')
	
	if not username or not password:
		print("❌ Missing credentials")
		return False
	
	async with InfoMentorClient() as client:
		# Authenticate
		print("🔐 Authenticating...")
		login_success = await client.login(username, password)
		if not login_success:
			print("❌ Authentication failed")
			return False
		
		# Check session cookies
		if hasattr(client._session, 'cookie_jar'):
			cookies = list(client._session.cookie_jar)
			print(f"🍪 Session has {len(cookies)} cookies")
			
			for cookie in cookies:
				print(f"   Cookie: {cookie.key}={cookie.value[:20]}... (domain: {cookie.get('domain', 'unknown')})")
		
		# Test multiple API calls to see if session persists
		test_urls = [
			f"{HUB_BASE_URL}/",
			f"{HUB_BASE_URL}/#/",
			f"{HUB_BASE_URL}/timetable/timetable/gettimetablelist?startDate=2025-06-01&endDate=2025-06-08",
		]
		
		for i, url in enumerate(test_urls, 1):
			print(f"\n   Test {i}: {url}")
			try:
				headers = DEFAULT_HEADERS.copy()
				if "timetable" in url:
					headers.update({
						"Accept": "application/json, text/javascript, */*; q=0.01",
						"X-Requested-With": "XMLHttpRequest",
					})
				
				async with client._session.get(url, headers=headers) as resp:
					print(f"      Status: {resp.status}")
					
					if resp.status == 200:
						text = await resp.text()
						if "logout" in text.lower() or "pupil" in text.lower():
							print("      ✅ Session appears valid (authenticated content)")
						elif "HandleUnauthorizedRequest" in text:
							print("      ❌ Session expired (HandleUnauthorizedRequest)")
						elif "login" in text.lower():
							print("      ❌ Session expired (login page)")
						else:
							print(f"      ? Unknown response: {text[:100]}...")
					else:
						print(f"      ❌ HTTP {resp.status}")
						
			except Exception as e:
				print(f"      ❌ Error: {e}")
			
			# Small delay between requests
			await asyncio.sleep(0.5)

async def main():
	"""Main function."""
	print("🔧 InfoMentor Authentication Debug Script")
	print("=" * 60)
	
	# Test 1: Authentication flow
	auth_success = await test_authentication_flow()
	
	if auth_success:
		# Test 2: Session persistence
		await test_session_persistence()
		
		print("\n🎯 RECOMMENDATIONS:")
		print("-" * 25)
		print("✅ If authentication succeeds but API calls fail:")
		print("   → Session may be expiring too quickly")
		print("   → Try increasing delays or re-authenticating before API calls")
		print()
		print("✅ If HandleUnauthorizedRequest appears:")
		print("   → Session has expired - need to re-authenticate")
		print("   → May need to implement session refresh logic")
		print()
		print("✅ If pupil switching fails:")
		print("   → Check switch ID mapping")
		print("   → Try alternative switch endpoints")
	else:
		print("\n❌ Authentication failed - check credentials and network connectivity")

if __name__ == "__main__":
	asyncio.run(main()) 