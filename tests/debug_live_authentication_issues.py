#!/usr/bin/env python3
"""
Live authentication diagnostics for InfoMentor integration.
This script helps troubleshoot auth and API issues happening in Home Assistant.
"""

import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
import json

# Add the custom components to the path
sys.path.insert(0, str(Path(__file__).parent.parent / 'custom_components' / 'infomentor'))

from infomentor.client import InfoMentorClient
from infomentor.auth import InfoMentorAuth
import aiohttp

async def diagnose_live_issues():
	"""Diagnose the live authentication and API issues."""
	
	print("🚨 DIAGNOSING LIVE AUTHENTICATION ISSUES")
	print("=" * 55)
	
	# Load credentials
	try:
		username = os.getenv('INFOMENTOR_USERNAME')
		password = os.getenv('INFOMENTOR_PASSWORD')
		
		if not username or not password:
			print("❌ No credentials found in environment variables")
			print("   Set INFOMENTOR_USERNAME and INFOMENTOR_PASSWORD")
			return False
			
	except Exception as e:
		print(f"❌ Error loading credentials: {e}")
		return False
	
	# Create client and test authentication
	async with aiohttp.ClientSession() as session:
		async with InfoMentorClient(session) as client:
			
			print("\n🔐 STEP 1: Testing Basic Authentication")
			print("-" * 40)
			
			try:
				login_success = await client.login(username, password)
				print(f"   Login attempt: {'✅ SUCCESS' if login_success else '❌ FAILED'}")
				
				if not login_success:
					print("   ❌ Cannot proceed without authentication")
					return False
					
			except Exception as e:
				print(f"   ❌ Login exception: {e}")
				return False
			
			print("\n📊 STEP 2: Authentication Status Diagnosis")
			print("-" * 45)
			
			try:
				auth_diag = await client.auth.diagnose_auth_state()
				
				print(f"   Authenticated: {auth_diag['authenticated']}")
				print(f"   Pupil IDs found: {auth_diag['pupil_ids_found']}")
				print(f"   Pupil IDs: {auth_diag['pupil_ids']}")
				print(f"   Session cookies: {auth_diag['session_cookies']}")
				
				if auth_diag['errors']:
					print(f"   Errors: {len(auth_diag['errors'])}")
					for error in auth_diag['errors'][:3]:  # Show first 3 errors
						print(f"     - {error}")
				
			except Exception as e:
				print(f"   ❌ Diagnosis failed: {e}")
			
			print("\n🔄 STEP 3: Testing Pupil Switching")
			print("-" * 35)
			
			try:
				pupil_ids = client.auth.pupil_ids
				if not pupil_ids:
					print("   ❌ No pupil IDs available for testing")
					return False
				
				print(f"   Available pupils: {pupil_ids}")
				print(f"   Switch ID mapping: {client.auth.pupil_switch_ids}")
				
				# Test switching to each pupil
				for pupil_id in pupil_ids[:2]:  # Test first 2 pupils only
					print(f"\n   Testing switch to pupil {pupil_id}:")
					
					try:
						switch_success = await client.switch_pupil(pupil_id)
						print(f"     Switch result: {'✅ SUCCESS' if switch_success else '❌ FAILED'}")
						
						if switch_success:
							# Quick test of API access after switch
							try:
								news = await client.get_news(None)  # Don't switch again
								print(f"     News API after switch: ✅ {len(news)} items")
							except Exception as e:
								print(f"     News API after switch: ❌ {e}")
								
						await asyncio.sleep(1)  # Brief pause between tests
						
					except Exception as e:
						print(f"     Switch exception: ❌ {e}")
				
			except Exception as e:
				print(f"   ❌ Pupil switching test failed: {e}")
			
			print("\n📅 STEP 4: Testing Timetable API")
			print("-" * 32)
			
			try:
				pupil_ids = client.auth.pupil_ids
				test_pupil = pupil_ids[0] if pupil_ids else None
				
				if not test_pupil:
					print("   ❌ No pupil available for timetable testing")
					return False
				
				print(f"   Testing timetable for pupil {test_pupil}")
				
				# Test date range (next week)
				start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
				end_date = start_date + timedelta(weeks=1)
				
				print(f"   Date range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
				
				try:
					timetable = await client.get_timetable(test_pupil, start_date, end_date)
					print(f"   Timetable result: ✅ {len(timetable)} entries")
					
					if timetable:
						sample_entry = timetable[0]
						print(f"   Sample entry: {sample_entry.title} on {sample_entry.date.strftime('%Y-%m-%d')}")
					else:
						print("   ⚠️  No timetable entries found (might be normal)")
						
				except Exception as e:
					print(f"   Timetable API: ❌ {e}")
					
					# Let's try to get more details about the error
					import traceback
					print(f"   Exception details: {traceback.format_exc()}")
				
			except Exception as e:
				print(f"   ❌ Timetable testing failed: {e}")
			
			print("\n⏰ STEP 5: Testing Time Registration API")
			print("-" * 42)
			
			try:
				pupil_ids = client.auth.pupil_ids
				test_pupil = pupil_ids[0] if pupil_ids else None
				
				if not test_pupil:
					print("   ❌ No pupil available for time registration testing")
					return False
				
				print(f"   Testing time registration for pupil {test_pupil}")
				
				# Test date range (this week)
				start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
				end_date = start_date + timedelta(weeks=1)
				
				try:
					time_regs = await client.get_time_registration(test_pupil, start_date, end_date)
					print(f"   Time registration result: ✅ {len(time_regs)} entries")
					
					if time_regs:
						sample_reg = time_regs[0]
						print(f"   Sample entry: {sample_reg.type} on {sample_reg.date.strftime('%Y-%m-%d')}")
					else:
						print("   ⚠️  No time registration entries found")
						
				except Exception as e:
					print(f"   Time registration API: ❌ {e}")
				
			except Exception as e:
				print(f"   ❌ Time registration testing failed: {e}")
			
			print("\n🔍 STEP 6: Testing Complete Schedule Integration")
			print("-" * 48)
			
			try:
				pupil_ids = client.auth.pupil_ids
				
				for pupil_id in pupil_ids:
					print(f"\n   Testing complete schedule for pupil {pupil_id}:")
					
					try:
						# Test the get_schedule method that combines timetable + time registration
						start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
						end_date = start_date + timedelta(days=7)
						
						schedule = await client.get_schedule(pupil_id, start_date, end_date)
						print(f"     Schedule days: ✅ {len(schedule)} days")
						
						# Count activities
						total_timetable = sum(len(day.timetable_entries) for day in schedule)
						total_time_reg = sum(len(day.time_registrations) for day in schedule)
						days_with_school = sum(1 for day in schedule if day.has_school)
						days_with_timetable = sum(1 for day in schedule if day.has_timetable_entries)
						
						print(f"     Total timetable entries: {total_timetable}")
						print(f"     Total time registrations: {total_time_reg}")
						print(f"     Days with any activity: {days_with_school}")
						print(f"     Days with timetable entries: {days_with_timetable}")
						
						# Show today's schedule if available
						today_schedule = next((day for day in schedule if day.date.date() == datetime.now().date()), None)
						if today_schedule:
							print(f"     Today: {len(today_schedule.timetable_entries)} timetable + {len(today_schedule.time_registrations)} registrations")
						else:
							print("     Today: No schedule data")
							
					except Exception as e:
						print(f"     Schedule test: ❌ {e}")
				
			except Exception as e:
				print(f"   ❌ Complete schedule testing failed: {e}")
			
			print("\n🎯 DIAGNOSIS SUMMARY")
			print("=" * 25)
			
			# Final recommendations
			auth_status = getattr(client.auth, 'authenticated', False)
			pupil_count = len(getattr(client.auth, 'pupil_ids', []))
			
			if not auth_status:
				print("🚨 CRITICAL: Authentication failure")
				print("   - Check username/password")
				print("   - Verify InfoMentor service status")
				print("   - Check network connectivity")
			elif pupil_count == 0:
				print("🚨 CRITICAL: No pupils found")
				print("   - Check account has associated children")
				print("   - Verify account permissions")
			else:
				print("✅ Authentication appears successful")
				print(f"   - Found {pupil_count} pupils")
				print("   - If still having issues, check:")
				print("     * Session timeouts in HA")
				print("     * Coordinator update frequency")
				print("     * Network stability")
			
			return True

if __name__ == "__main__":
	asyncio.run(diagnose_live_issues()) 