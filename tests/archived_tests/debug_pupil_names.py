#!/usr/bin/env python3
"""
Detailed debug script to trace authentication flow and pupil extraction.
"""

import asyncio
import sys
import re
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve() / 'custom_components' / 'infomentor'))

from infomentor import InfoMentorClient
import os
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / '.env')

async def debug_full_auth_flow():
	"""Debug the complete authentication and pupil extraction flow."""
	print("🔍 Detailed Authentication Flow Debug")
	print("=" * 60)
	
	async with InfoMentorClient() as client:
		username = os.getenv('INFOMENTOR_USERNAME')
		password = os.getenv('INFOMENTOR_PASSWORD')
		
		print(f"📋 Testing with username: {username}")
		
		# Step 1: Check initial hub access (should redirect to login)
		print("\n📍 Step 1: Testing initial hub access...")
		hub_url = 'https://hub.infomentor.se'
		async with client._session.get(hub_url, allow_redirects=False) as resp:
			print(f"   Status: {resp.status}")
			print(f"   Headers: {dict(resp.headers)}")
			if resp.status == 302:
				location = resp.headers.get('Location')
				print(f"   Redirect to: {location}")
		
		# Step 2: Manual authentication debugging
		print("\n📍 Step 2: Manual OAuth token extraction...")
		oauth_url = f"{hub_url}/authentication/authentication/login?apitype=im1&forceOAuth=true"
		async with client._session.get(oauth_url) as resp:
			text = await resp.text()
			print(f"   OAuth page status: {resp.status}")
			
			# Extract token
			oauth_match = re.search(r'oauth_token"\s+value="([\w+=/]+)"', text)
			if oauth_match:
				oauth_token = oauth_match.group(1)
				print(f"   ✅ OAuth token: {oauth_token[:20]}...")
			else:
				print("   ❌ No OAuth token found")
				return
		
		# Step 3: Submit OAuth token manually and trace redirects
		print("\n📍 Step 3: Submitting OAuth token and tracing flow...")
		
		mentor_url = "https://infomentor.se/swedish/production/mentor/"
		headers = {
			"Content-Type": "application/x-www-form-urlencoded",
			"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:98.0) Gecko/20100101 Firefox/98.0",
			"Origin": hub_url,
			"Referer": oauth_url,
		}
		
		data = f"oauth_token={oauth_token}"
		
		print(f"   Submitting to: {mentor_url}")
		
		# Follow the redirects manually to see the complete flow
		redirect_count = 0
		current_url = mentor_url
		
		async with client._session.post(
			current_url,
			headers=headers,
			data=data,
			allow_redirects=False
		) as resp:
			print(f"   Initial response: {resp.status}")
			print(f"   Headers: {dict(resp.headers)}")
			
			# Follow redirects manually
			while resp.status in [301, 302, 303, 307, 308] and redirect_count < 10:
				redirect_count += 1
				location = resp.headers.get('Location')
				if not location:
					break
				
				if not location.startswith('http'):
					if location.startswith('/'):
						location = f"https://infomentor.se{location}"
					else:
						location = f"https://infomentor.se/{location}"
				
				print(f"   Redirect {redirect_count}: {location}")
				
				async with client._session.get(location, allow_redirects=False) as next_resp:
					resp = next_resp
					print(f"   Status: {resp.status}")
					
					if resp.status == 200:
						break
			
			# Check final response
			if resp.status == 200:
				final_text = await resp.text()
				final_url = str(resp.url)
				print(f"   Final URL: {final_url}")
				print(f"   Final content length: {len(final_text)}")
				
				# Save for analysis
				import os
		os.makedirs('../debug_output', exist_ok=True)
		with open('../debug_output/final_auth_page.html', 'w', encoding='utf-8') as f:
					f.write(final_text)
				print("   💾 Saved final page to: final_auth_page.html")
				
				# Check what type of page we got
				if 'hub.infomentor.se' in final_url:
					print("   ✅ Reached hub domain")
				elif 'infomentor.se' in final_url:
					print("   ⚠️  Still on infomentor.se domain")
				
				# Look for signs of authenticated content
				auth_indicators = [
					'switchpupil', 'logout', 'dashboard', 'välkommen',
					'pupil', 'student', 'elev', 'account'
				]
				
				found_indicators = []
				for indicator in auth_indicators:
					if indicator.lower() in final_text.lower():
						found_indicators.append(indicator)
				
				if found_indicators:
					print(f"   ✅ Found auth indicators: {found_indicators}")
				else:
					print("   ❌ No authentication indicators found")
				
				# Look for pupil information specifically
				pupil_patterns = [
					r'/Account/PupilSwitcher/SwitchPupil/(\d+)',
					r'SwitchPupil/(\d+)',
					r'"pupilId"\s*:\s*"?(\d+)"?',
					r'"id"\s*:\s*(\d+)[^}]*"name"',
					r'pupils?\s*:\s*\[([^\]]+)\]',
					r'elever?\s*:\s*\[([^\]]+)\]',
				]
				
				all_pupil_matches = []
				for pattern in pupil_patterns:
					matches = re.findall(pattern, final_text, re.IGNORECASE)
					if matches:
						print(f"   🔍 Pattern '{pattern}' found: {matches}")
						all_pupil_matches.extend(matches)
				
				if all_pupil_matches:
					unique_ids = list(set(all_pupil_matches))
					print(f"   ✅ Found potential pupil IDs: {unique_ids}")
				else:
					print("   ❌ No pupil patterns found")
		
		# Step 4: Try the official authentication method
		print("\n📍 Step 4: Testing official authentication method...")
		
		try:
			if await client.login(username, password):
				print("   ✅ Official auth succeeded")
				pupil_ids = await client.get_pupil_ids()
				print(f"   📋 Official pupil IDs: {pupil_ids}")
				
				# Try different URLs to find pupil info
				test_urls = [
					f"{hub_url}/#/",
					f"{hub_url}/",
					f"{hub_url}/dashboard",
					f"{hub_url}/home",
					"https://infomentor.se/",
				]
				
				for url in test_urls:
					print(f"   🔍 Testing URL: {url}")
					try:
						async with client._session.get(url) as resp:
							print(f"      Status: {resp.status}")
							if resp.status == 200:
								content = await resp.text()
								
								# Look for any pupil references
								if any(word in content.lower() for word in ['pupil', 'elev', 'student', 'switch']):
									print(f"      ✅ Found pupil-related content")
									
									# Save this page too
									filename = f"test_page_{url.replace('://', '_').replace('/', '_')}.html"
									with open(filename, 'w', encoding='utf-8') as f:
										f.write(content)
									print(f"      💾 Saved to: {filename}")
								else:
									print(f"      ❌ No pupil content found")
					except Exception as e:
						print(f"      ❌ Error: {e}")
			else:
				print("   ❌ Official auth failed")
		except Exception as e:
			print(f"   ❌ Exception during official auth: {e}")

if __name__ == "__main__":
	asyncio.run(debug_full_auth_flow()) 