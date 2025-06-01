#!/usr/bin/env python3
"""
Comprehensive test to find the correct authentication path to InfoMentor.
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
DEFAULT_HEADERS = {
	"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:98.0) Gecko/20100101 Firefox/98.0",
	"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
	"Accept-Language": "en-GB,en;q=0.5",
	"Accept-Encoding": "gzip, deflate, br",
	"DNT": "1",
	"Connection": "keep-alive",
	"Upgrade-Insecure-Requests": "1",
}

async def test_complete_oauth_flow():
	"""Test a complete OAuth flow that follows all redirects properly."""
	print("🔐 Testing Complete OAuth Authentication Flow")
	print("=" * 60)
	
	username = os.getenv('INFOMENTOR_USERNAME')
	password = os.getenv('INFOMENTOR_PASSWORD')
	
	if not username or not password:
		print("❌ Missing credentials")
		return
	
	async with aiohttp.ClientSession(
		cookie_jar=aiohttp.CookieJar(unsafe=True),
		timeout=aiohttp.ClientTimeout(total=30)
	) as session:
		
		try:
			# Step 1: Get the OAuth login URL
			print("\n📍 Step 1: Getting OAuth login URL...")
			oauth_url = f"{HUB_BASE_URL}/authentication/authentication/login?apitype=im1&forceOAuth=true"
			
			async with session.get(oauth_url, headers=DEFAULT_HEADERS) as resp:
				if resp.status != 200:
					print(f"❌ Failed to get OAuth page: {resp.status}")
					return
				
							text = await resp.text()
			print(f"✅ Got OAuth page")
			
			# Save for debugging
			import os
			os.makedirs('../debug_output', exist_ok=True)
			with open('../debug_output/oauth_page.html', 'w', encoding='utf-8') as f:
				f.write(text)
			
			# Step 2: Extract OAuth token and submission URL
			print("\n📍 Step 2: Extracting OAuth token and form details...")
			
			oauth_match = re.search(r'oauth_token"\s+value="([\w+=/]+)"', text)
			if not oauth_match:
				print("❌ No OAuth token found")
				return
			
			oauth_token = oauth_match.group(1)
			print(f"✅ OAuth token: {oauth_token[:20]}...")
			
			# Look for the form action URL
			form_action = None
			action_patterns = [
				r'<form[^>]*action="([^"]+)"',
				r'<form[^>]*action=\'([^\']+)\'',
				r'action\s*=\s*["\']([^"\']+)["\']',
			]
			
			for pattern in action_patterns:
				match = re.search(pattern, text)
				if match:
					form_action = match.group(1)
					break
			
			if form_action:
				print(f"✅ Form action: {form_action}")
				if not form_action.startswith('http'):
					form_action = "https://infomentor.se" + form_action
			else:
				form_action = "https://infomentor.se/swedish/production/mentor/"
				print(f"⚠️  Using default form action: {form_action}")
			
			# Step 3: Submit OAuth token with proper headers
			print(f"\n📍 Step 3: Submitting OAuth token to {form_action}...")
			
			# Prepare headers that mimic the form submission
			submit_headers = DEFAULT_HEADERS.copy()
			submit_headers.update({
				"Content-Type": "application/x-www-form-urlencoded",
				"Origin": HUB_BASE_URL,
				"Referer": oauth_url,
				"Cache-Control": "max-age=0",
				"Sec-Fetch-Dest": "document",
				"Sec-Fetch-Mode": "navigate",
				"Sec-Fetch-Site": "cross-site",
				"Sec-Fetch-User": "?1",
			})
			
			data = f"oauth_token={oauth_token}"
			
			# Don't follow redirects automatically so we can see the flow
			async with session.post(
				form_action,
				headers=submit_headers,
				data=data,
				allow_redirects=False
			) as resp:
				print(f"✅ OAuth submission status: {resp.status}")
				
				if resp.status in [301, 302, 303, 307, 308]:
					location = resp.headers.get('Location')
					print(f"🔄 Redirect to: {location}")
					
					# Follow the redirect chain manually
					redirect_count = 0
					current_url = location
					
					while current_url and redirect_count < 10:
						if not current_url.startswith('http'):
							if current_url.startswith('/'):
								current_url = "https://infomentor.se" + current_url
							else:
								current_url = "https://infomentor.se/" + current_url
						
						print(f"🔄 Following redirect {redirect_count + 1}: {current_url}")
						
						headers = DEFAULT_HEADERS.copy()
						headers["Referer"] = form_action if redirect_count == 0 else prev_url
						prev_url = current_url
						
						async with session.get(current_url, headers=headers, allow_redirects=False) as redirect_resp:
							print(f"   Status: {redirect_resp.status}")
							
							if redirect_resp.status == 200:
								# We've reached a final page
								final_text = await redirect_resp.text()
								final_url = str(redirect_resp.url)
								
								print(f"✅ Final destination: {final_url}")
								print(f"   Content length: {len(final_text)}")
								
								# Save the final page
								with open('../debug_output/final_authenticated_page.html', 'w', encoding='utf-8') as f:
									f.write(final_text)
								print("💾 Saved final page")
								
								# Check what we got
								await analyze_final_page(final_text, final_url)
								break
								
							elif redirect_resp.status in [301, 302, 303, 307, 308]:
								current_url = redirect_resp.headers.get('Location')
								redirect_count += 1
							else:
								print(f"❌ Unexpected status: {redirect_resp.status}")
								error_text = await redirect_resp.text()
								print(f"   Error content: {error_text[:200]}...")
								break
					
					if redirect_count >= 10:
						print("❌ Too many redirects")
				
				elif resp.status == 200:
					# Direct response without redirect
					text = await resp.text()
					final_url = str(resp.url)
					
					print(f"✅ Direct response to: {final_url}")
					
					with open('../debug_output/direct_auth_response.html', 'w', encoding='utf-8') as f:
						f.write(text)
					print("💾 Saved direct response")
					
					await analyze_final_page(text, final_url)
				
				else:
					print(f"❌ OAuth submission failed: {resp.status}")
					error_text = await resp.text()
					print(f"Error: {error_text[:200]}...")
		
		except Exception as e:
			print(f"❌ Error: {e}")
			import traceback
			traceback.print_exc()


async def analyze_final_page(content: str, url: str):
	"""Analyze the final page to determine what we got."""
	print(f"\n📋 Analyzing final page...")
	
	# Check if we're on an authenticated page
	auth_indicators = {
		'positive': ['switchpupil', 'logout', 'välkommen', 'dashboard', 'account', 'pupilswitcher'],
		'negative': ['login', 'txtnotandanafn', 'txtlykilord', 'oauth_token', 'password', 'username']
	}
	
	content_lower = content.lower()
	
	positive_matches = [word for word in auth_indicators['positive'] if word in content_lower]
	negative_matches = [word for word in auth_indicators['negative'] if word in content_lower]
	
	print(f"✅ Positive indicators found: {positive_matches}")
	print(f"❌ Negative indicators found: {negative_matches}")
	
	if positive_matches and not negative_matches:
		print("🎉 Looks like we reached an authenticated page!")
		
		# Look for pupil information
		pupil_patterns = [
			r'/Account/PupilSwitcher/SwitchPupil/(\d+)',
			r'SwitchPupil/(\d+)',
			r'"pupilId"\s*:\s*"?(\d+)"?',
			r'"id"\s*:\s*(\d+)[^}]*"name"\s*:\s*"([^"]+)"',
			r'pupils?\s*:\s*\[([^\]]+)\]',
		]
		
		all_pupil_data = []
		for pattern in pupil_patterns:
			matches = re.findall(pattern, content)
			if matches:
				print(f"🔍 Pattern '{pattern}' found: {matches}")
				all_pupil_data.extend(matches)
		
		if all_pupil_data:
			unique_data = list(set(all_pupil_data))
			print(f"🎯 Found pupil data: {unique_data}")
		else:
			print("⚠️  No pupil patterns found - checking for JavaScript data...")
			
			# Look for JavaScript objects with pupil data
			js_patterns = [
				r'var\s+\w+\s*=\s*({[^}]*pupil[^}]*})',
				r'window\.\w+\s*=\s*({[^}]*pupils?[^}]*})',
				r'data-\w*pupil\w*\s*=\s*["\']([^"\']+)["\']',
			]
			
			for pattern in js_patterns:
				matches = re.findall(pattern, content, re.IGNORECASE)
				if matches:
					print(f"🔍 JS pattern found: {matches}")
	
	elif negative_matches:
		print("❌ Still on a login/authentication page")
		
		# Check what type of login page
		if 'oauth_token' in content_lower:
			print("   → OAuth login page")
		elif any(field in content_lower for field in ['txtnotandanafn', 'txtlykilord']):
			print("   → Legacy ASP.NET login page")
		else:
			print("   → Generic login page")
	
	else:
		print("❓ Unclear what type of page this is")
	
	# Check domain
	if 'hub.infomentor.se' in url:
		print("✅ On hub domain")
	elif 'infomentor.se' in url:
		print("⚠️  On legacy infomentor.se domain")
	else:
		print(f"❓ Unknown domain: {url}")


if __name__ == "__main__":
	asyncio.run(test_complete_oauth_flow()) 