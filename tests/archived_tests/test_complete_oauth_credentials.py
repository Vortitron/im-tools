#!/usr/bin/env python3
"""
Test complete OAuth flow with credential submission.
"""

import asyncio
import sys
import re
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve() / 'custom_components' / 'infomentor'))

import aiohttp
import os
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / '.env')

HUB_BASE_URL = "https://hub.infomentor.se"
MODERN_BASE_URL = "https://im.infomentor.se"
LEGACY_BASE_URL = "https://infomentor.se/swedish/production/mentor/"

DEFAULT_HEADERS = {
	"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:98.0) Gecko/20100101 Firefox/98.0",
	"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
	"Accept-Language": "en-GB,en;q=0.5",
	"Accept-Encoding": "gzip, deflate, br",
	"DNT": "1",
	"Connection": "keep-alive",
	"Upgrade-Insecure-Requests": "1",
}

async def test_complete_flow_with_credentials():
	"""Test complete OAuth flow with credential submission."""
	print("🔐 Testing Complete Two-Stage OAuth + Credentials Flow")
	print("=" * 60)
	
	username = os.getenv('INFOMENTOR_USERNAME')
	password = os.getenv('INFOMENTOR_PASSWORD')
	
	if not username or not password:
		print("❌ Missing credentials")
		return
	
	print(f"📋 Using credentials: {username}")
	
	async with aiohttp.ClientSession(
		cookie_jar=aiohttp.CookieJar(unsafe=True),
		timeout=aiohttp.ClientTimeout(total=60)
	) as session:
		
		try:
			# Step 1: Get OAuth token
			print("\n📍 Step 1: Getting OAuth token...")
			oauth_url = f"{HUB_BASE_URL}/authentication/authentication/login?apitype=im1&forceOAuth=true"
			
			async with session.get(oauth_url, headers=DEFAULT_HEADERS) as resp:
				oauth_text = await resp.text()
				print(f"✅ OAuth page status: {resp.status}")
			
			oauth_match = re.search(r'oauth_token"\s+value="([\w+=/]+)"', oauth_text)
			if not oauth_match:
				print("❌ No OAuth token found")
				return
			
			oauth_token = oauth_match.group(1)
			print(f"✅ OAuth token (stage 1): {oauth_token[:20]}...")
			
			# Step 2: Submit OAuth token to legacy domain
			print("\n📍 Step 2: Submitting OAuth token (stage 1)...")
			
			submit_headers = DEFAULT_HEADERS.copy()
			submit_headers.update({
				"Content-Type": "application/x-www-form-urlencoded",
				"Origin": HUB_BASE_URL,
				"Referer": oauth_url,
				"Sec-Fetch-Site": "cross-site",
			})
			
			oauth_data = f"oauth_token={oauth_token}"
			
			async with session.post(
				LEGACY_BASE_URL,
				headers=submit_headers,
				data=oauth_data,
				allow_redirects=True
			) as resp:
				oauth_resp_text = await resp.text()
				print(f"✅ OAuth submission status: {resp.status}")
				print(f"   Final URL: {resp.url}")
			
			# Step 3: Check if we need to submit credentials
			if any(field in oauth_resp_text.lower() for field in ['txtnotandanafn', 'txtlykilord', 'login']):
				print("\n📍 Step 3: Submitting credentials...")
				
				# Extract form fields
				form_data = {}
				
				# ViewState fields
				for field in ['__VIEWSTATE', '__VIEWSTATEGENERATOR', '__EVENTVALIDATION']:
					pattern = f'{field}["\'][^>]*value=["\']([^"\']+)["\']'
					match = re.search(pattern, oauth_resp_text)
					if match:
						form_data[field] = match.group(1)
				
				# Form submission fields
				form_data.update({
					'__EVENTTARGET': 'login_ascx$btnLogin',
					'__EVENTARGUMENT': '',
					'login_ascx$txtNotandanafn': username,
					'login_ascx$txtLykilord': password,
				})
				
				print(f"   Found {len(form_data)} form fields")
				
				# Submit credentials
				cred_headers = DEFAULT_HEADERS.copy()
				cred_headers.update({
					"Content-Type": "application/x-www-form-urlencoded",
					"Origin": "https://infomentor.se",
					"Referer": str(resp.url),
				})
				
				from urllib.parse import urlencode
				
				async with session.post(
					str(resp.url),
					headers=cred_headers,
					data=urlencode(form_data),
					allow_redirects=True
				) as cred_resp:
					cred_text = await cred_resp.text()
					print(f"✅ Credentials status: {cred_resp.status}")
					print(f"   Final URL: {cred_resp.url}")
					
					# Save for debugging
					import os
					os.makedirs('../debug_output', exist_ok=True)
					with open('../debug_output/credentials_response.html', 'w', encoding='utf-8') as f:
						f.write(cred_text)
					
					# Step 4: Check if we got a second OAuth token (two-stage process)
					second_oauth_match = re.search(r'oauth_token"\s+value="([\w+=/]+)"', cred_text)
					if second_oauth_match:
						second_oauth_token = second_oauth_match.group(1)
						print(f"🔄 Found second OAuth token: {second_oauth_token[:20]}...")
						print("\n📍 Step 4: Submitting second OAuth token...")
						
						# Submit the second OAuth token
						second_oauth_data = f"oauth_token={second_oauth_token}"
						
						async with session.post(
							LEGACY_BASE_URL,
							headers=submit_headers,
							data=second_oauth_data,
							allow_redirects=True
						) as second_resp:
							second_text = await resp.text()
							print(f"✅ Second OAuth status: {second_resp.status}")
							print(f"   Final URL: {second_resp.url}")
							
							# Save for debugging
							with open('../debug_output/second_oauth_response.html', 'w', encoding='utf-8') as f:
								f.write(second_text)
							print("💾 Saved second OAuth response")
							
							# Check if we're now authenticated
							if "login_ascx" not in second_text.lower() and "txtnotandanafn" not in second_text.lower():
								print("🎉 Two-stage authentication completed!")
							else:
								print("❌ Still on login page after second OAuth")
					
					# Check if we're authenticated after credentials
					elif "login_ascx" not in cred_text.lower() and "txtnotandanafn" not in cred_text.lower():
						print("🎉 Credentials accepted!")
					else:
						print("❌ Credentials rejected - still on login page")
						
						# Check for error messages
						error_patterns = [
							r'fel[^<]*',
							r'error[^<]*',
							r'invalid[^<]*',
							r'incorrect[^<]*',
						]
						
						for pattern in error_patterns:
							matches = re.findall(pattern, cred_text, re.IGNORECASE)
							if matches:
								print(f"   Error messages: {matches}")
						return
			
			else:
				print("\n✅ OAuth completed without credential form")
			
			# Step 5: Try to reach the authenticated interface
			print("\n📍 Step 5: Accessing authenticated areas...")
			
			# Try different endpoints
			endpoints_to_try = [
				("Legacy default", "https://infomentor.se/Swedish/Production/mentor/default.aspx"),
				("Modern IM domain", f"{MODERN_BASE_URL}/"),
				("Modern dashboard", f"{MODERN_BASE_URL}/Dashboard"),
				("Hub main", f"{HUB_BASE_URL}/#/"),
				("Hub root", f"{HUB_BASE_URL}/"),
			]
			
			pupil_ids_found = []
			
			for name, url in endpoints_to_try:
				try:
					print(f"\n🔍 Trying {name}: {url}")
					async with session.get(url, headers=DEFAULT_HEADERS) as test_resp:
						test_text = await test_resp.text()
						print(f"   Status: {test_resp.status}")
						
						# Save for debugging
						safe_name = name.lower().replace(" ", "_")
						with open(f'../debug_output/auth_test_{safe_name}.html', 'w', encoding='utf-8') as f:
							f.write(test_text)
						
						# Look for pupil patterns
						pupil_patterns = [
							r'/Account/PupilSwitcher/SwitchPupil/(\d+)',
							r'SwitchPupil/(\d+)',
							r'"pupilId"\s*:\s*"?(\d+)"?',
							r'"id"\s*:\s*"?(\d+)"?[^}]*"name"',
							r'data-pupil-id=["\'](\d+)["\']',
							r'pupil[^0-9]*(\d{4,8})',
							r'elevid[^0-9]*(\d{4,8})',
						]
						
						found_pupils = []
						for pattern in pupil_patterns:
							matches = re.findall(pattern, test_text, re.IGNORECASE)
							if matches:
								found_pupils.extend(matches)
						
						# Remove duplicates and filter reasonable IDs
						found_pupils = list(set([p for p in found_pupils if 4 <= len(p) <= 8]))
						
						if found_pupils:
							print(f"   🎯 Found pupil IDs: {found_pupils}")
							pupil_ids_found.extend(found_pupils)
						else:
							print(f"   ❌ No pupil IDs found")
						
						# Check authentication status
						auth_indicators = ['switchpupil', 'logout', 'välkommen', 'dashboard']
						login_indicators = ['login', 'txtnotandanafn', 'txtlykilord', 'password']
						
						auth_found = [word for word in auth_indicators if word in test_text.lower()]
						login_found = [word for word in login_indicators if word in test_text.lower()]
						
						if auth_found and not login_found:
							print(f"   ✅ Authenticated page (indicators: {auth_found})")
						elif login_found:
							print(f"   ❌ Still on login page (indicators: {login_found})")
						else:
							print(f"   ❓ Unknown page type")
				
				except Exception as e:
					print(f"   ❌ Error accessing {name}: {e}")
			
			# Summary
			print(f"\n📋 Summary:")
			print(f"   Total unique pupil IDs found: {len(set(pupil_ids_found))}")
			if pupil_ids_found:
				print(f"   Pupil IDs: {list(set(pupil_ids_found))}")
			else:
				print(f"   ❌ No pupil IDs found across all endpoints")
		
		except Exception as e:
			print(f"❌ Error: {e}")
			import traceback
			traceback.print_exc()


if __name__ == "__main__":
	asyncio.run(test_complete_flow_with_credentials()) 