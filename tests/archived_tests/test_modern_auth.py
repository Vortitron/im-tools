#!/usr/bin/env python3
"""
Test modern InfoMentor authentication bypassing the legacy endpoint.
"""

import asyncio
import aiohttp
import getpass
import os
import re
import json
from urllib.parse import urlparse, parse_qs

# Try to load environment variables from .env file
try:
	from dotenv import load_dotenv
	load_dotenv(Path(__file__).parent.parent / '.env')
except ImportError:
	pass

HUB_BASE_URL = "https://hub.infomentor.se"

DEFAULT_HEADERS = {
	"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:98.0) Gecko/20100101 Firefox/98.0",
	"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
	"Accept-Language": "en-GB,en;q=0.5",
	"Accept-Encoding": "gzip, deflate, br",
	"DNT": "1",
	"Connection": "keep-alive",
	"Upgrade-Insecure-Requests": "1",
	"Sec-Fetch-Dest": "document",
	"Sec-Fetch-Mode": "navigate",
	"Sec-Fetch-Site": "none",
	"Sec-Fetch-User": "?1",
}


async def test_modern_auth_flow(username: str, password: str):
	"""Test a modern authentication flow that bypasses the legacy endpoint."""
	print("🔐 Testing modern authentication flow...")
	
	async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar()) as session:
		try:
			# Step 1: Get the OAuth login page
			print("   Step 1: Getting OAuth login page...")
			login_url = f"{HUB_BASE_URL}/authentication/authentication/login?apitype=im1&forceOAuth=true"
			
			async with session.get(login_url, headers=DEFAULT_HEADERS) as resp:
				print(f"   📥 Login page status: {resp.status}")
				
				if resp.status != 200:
					print(f"   ❌ Failed to get login page")
					return False
				
				text = await resp.text()
				
				# Save page for debugging
				import os
		os.makedirs('../debug_output', exist_ok=True)
		with open("../debug_output/modern_login_page.html", "w", encoding="utf-8") as f:
					f.write(text)
				print("   💾 Saved login page to: modern_login_page.html")
			
			# Look for modern login form or API endpoints
			# Check if there are any form submission endpoints
			form_patterns = [
				r'action=[\'"](.*?)[\'"]',
				r'action\s*=\s*[\'"](.*?)[\'"]',
				r'data-action=[\'"](.*?)[\'"]',
				r'formAction\s*[:=]\s*[\'"](.*?)[\'"]',
			]
			
			potential_endpoints = []
			for pattern in form_patterns:
				matches = re.findall(pattern, text, re.IGNORECASE)
				potential_endpoints.extend(matches)
			
			print(f"   🔍 Found potential form endpoints: {potential_endpoints}")
			
			# Look for any API endpoints in JavaScript
			api_patterns = [
				r'[\'"](/api/[^\'\"]+)[\'"]',
				r'[\'"](/Authentication/[^\'\"]+)[\'"]',
				r'[\'"]([^\'\"]*login[^\'\"]*)[\'"]',
				r'url\s*:\s*[\'"]([^\'\"]+)[\'"]',
			]
			
			api_endpoints = []
			for pattern in api_patterns:
				matches = re.findall(pattern, text, re.IGNORECASE)
				api_endpoints.extend(matches)
			
			# Remove duplicates and filter relevant endpoints
			api_endpoints = list(set([ep for ep in api_endpoints if 'login' in ep.lower() or 'auth' in ep.lower()]))
			print(f"   🔍 Found potential API endpoints: {api_endpoints}")
			
			# Look for CSRF tokens or other form fields
			csrf_patterns = [
				r'name=[\'"]__RequestVerificationToken[\'"][^>]*value=[\'"]([^\'\"]+)[\'"]',
				r'name=[\'"]authenticity_token[\'"][^>]*value=[\'"]([^\'\"]+)[\'"]',
				r'csrf[\'"]?\s*[:=]\s*[\'"]([^\'\"]+)[\'"]',
			]
			
			csrf_token = None
			for pattern in csrf_patterns:
				match = re.search(pattern, text, re.IGNORECASE)
				if match:
					csrf_token = match.group(1)
					print(f"   🔒 Found CSRF token: {csrf_token[:20]}...")
					break
			
			# Try to find if there's a modern login form
			if 'username' in text.lower() and 'password' in text.lower():
				print("   ✅ Found modern login form!")
				
				# Extract form fields
				username_field = None
				password_field = None
				
				username_patterns = [
					r'name=[\'"]username[\'"]',
					r'name=[\'"]email[\'"]',
					r'id=[\'"]username[\'"]',
					r'id=[\'"]email[\'"]',
				]
				
				password_patterns = [
					r'name=[\'"]password[\'"]',
					r'id=[\'"]password[\'"]',
				]
				
				for pattern in username_patterns:
					if re.search(pattern, text, re.IGNORECASE):
						username_field = pattern.split('"')[1]
						break
				
				for pattern in password_patterns:
					if re.search(pattern, text, re.IGNORECASE):
						password_field = pattern.split('"')[1]
						break
				
				print(f"   📝 Username field: {username_field}")
				print(f"   📝 Password field: {password_field}")
				
				# Try to submit the form
				if username_field and password_field:
					print("   📤 Attempting form submission...")
					
					# Try different possible action URLs
					action_urls = [
						f"{HUB_BASE_URL}/authentication/authentication/login",
						f"{HUB_BASE_URL}/api/auth/login",
						f"{HUB_BASE_URL}/login",
					]
					
					for action_url in action_urls:
						print(f"   🎯 Trying: {action_url}")
						
						form_data = {
							username_field: username,
							password_field: password,
						}
						
						if csrf_token:
							form_data['__RequestVerificationToken'] = csrf_token
						
						headers = DEFAULT_HEADERS.copy()
						headers.update({
							"Content-Type": "application/x-www-form-urlencoded",
							"Origin": HUB_BASE_URL,
							"Referer": login_url,
						})
						
						async with session.post(action_url, headers=headers, data=form_data, allow_redirects=False) as resp:
							print(f"      📥 Status: {resp.status}")
							print(f"      📋 Headers: {dict(resp.headers)}")
							
							location = resp.headers.get('Location')
							if location:
								print(f"      🔗 Redirect: {location}")
								
								# If we get redirected to the hub, we're probably authenticated
								if 'hub.infomentor.se' in location and '#' in location:
									print("      ✅ Looks like authentication succeeded!")
									
									# Follow the redirect to complete authentication
									if not location.startswith('http'):
										location = HUB_BASE_URL + location
									
									async with session.get(location, headers=DEFAULT_HEADERS) as final_resp:
										final_text = await final_resp.text()
										
										# Check for pupil switcher (sign of successful auth)
										if 'SwitchPupil' in final_text:
											print("      🎉 Authentication successful! Found pupil switcher.")
											return True
								
							response_text = await resp.text()
							if resp.status == 200 and 'error' not in response_text.lower():
								print(f"      📄 Response: {response_text[:200]}...")
			
			return False
			
		except Exception as e:
			print(f"   ❌ Error: {e}")
			return False


async def main():
	"""Main function."""
	print("🔧 Modern InfoMentor Authentication Test")
	print("=" * 50)
	
	# Get credentials
	username = os.getenv("INFOMENTOR_USERNAME")
	password = os.getenv("INFOMENTOR_PASSWORD")
	
	if username and password:
		print("🔑 Using credentials from .env file")
	else:
		print("📝 Please enter your InfoMentor credentials:")
		if not username:
			username = input("Username: ").strip()
		if not password:
			password = getpass.getpass("Password: ").strip()
	
	if not username or not password:
		print("❌ Credentials required!")
		return
	
	success = await test_modern_auth_flow(username, password)
	
	if success:
		print("\n✅ Modern authentication approach works!")
		print("💡 We can update the auth module to use this approach.")
	else:
		print("\n❌ Modern authentication approach failed.")
		print("💡 InfoMentor may have additional security measures.")


if __name__ == "__main__":
	asyncio.run(main()) 