#!/usr/bin/env python3
"""
Debug script to test InfoMentor authentication flow and identify issues.
"""

import asyncio
import aiohttp
import getpass
import os
import re
import logging
from pathlib import Path

# Try to load environment variables from .env file
try:
	from dotenv import load_dotenv
	load_dotenv(Path(__file__).parent.parent / '.env')
except ImportError:
	print("💡 Tip: Install python-dotenv to use .env file for credentials:")
	print("    pip install python-dotenv")

# Set up detailed logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Constants from the auth module
HUB_BASE_URL = "https://hub.infomentor.se"
LEGACY_BASE_URL = "https://infomentor.se/Swedish/Production/mentor/Oryggi/Login.aspx"

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


async def test_initial_redirect():
	"""Test the initial redirect to get OAuth token."""
	print("\n🔍 Testing initial redirect...")
	
	async with aiohttp.ClientSession() as session:
		try:
			# Get initial redirect
			async with session.get(HUB_BASE_URL, headers=DEFAULT_HEADERS, allow_redirects=False) as resp:
				print(f"   📥 Status: {resp.status}")
				print(f"   📋 Headers: {dict(resp.headers)}")
				
				if resp.status == 302:
					location = resp.headers.get('Location')
					print(f"   🔗 Location: {location}")
					return location
				else:
					text = await resp.text()
					print(f"   📄 Response content (first 500 chars): {text[:500]}")
					
					# Look for JavaScript redirect
					location_match = re.search(r'window\.location\.href\s*=\s*["\']([^"\']+)["\']', text)
					if location_match:
						location = location_match.group(1)
						print(f"   🔗 JS Redirect: {location}")
						return location
					
		except Exception as e:
			print(f"   ❌ Error: {e}")
			return None


async def test_oauth_token_extraction(redirect_url):
	"""Test OAuth token extraction from redirect URL."""
	print(f"\n🔍 Testing OAuth token extraction from: {redirect_url}")
	
	async with aiohttp.ClientSession() as session:
		try:
			async with session.get(redirect_url, headers=DEFAULT_HEADERS) as resp:
				print(f"   📥 Status: {resp.status}")
				
				if resp.status != 200:
					print(f"   ❌ Unexpected status code")
					return None
					
				text = await resp.text()
				
				# Extract OAuth token
				oauth_match = re.search(r'oauth_token"\s+value="([\w+=/]+)"', text)
				if oauth_match:
					token = oauth_match.group(1)
					print(f"   ✅ OAuth token found: {token[:10]}...")
					return token
				else:
					print("   ❌ No OAuth token found")
					print(f"   📄 Response content (first 1000 chars): {text[:1000]}")
					
					# Look for other token patterns
					token_patterns = [
						r'name="oauth_token"\s+value="([^"]+)"',
						r'id="oauth_token"\s+value="([^"]+)"',
						r'oauth_token["\']?\s*[:=]\s*["\']([^"\']+)["\']',
					]
					
					for pattern in token_patterns:
						match = re.search(pattern, text, re.IGNORECASE)
						if match:
							token = match.group(1)
							print(f"   ✅ Alternative token found: {token[:10]}...")
							return token
					
					return None
					
		except Exception as e:
			print(f"   ❌ Error: {e}")
			return None


async def test_legacy_login_page():
	"""Test accessing the legacy login page."""
	print(f"\n🔍 Testing legacy login page: {LEGACY_BASE_URL}")
	
	async with aiohttp.ClientSession() as session:
		try:
			async with session.get(LEGACY_BASE_URL, headers=DEFAULT_HEADERS) as resp:
				print(f"   📥 Status: {resp.status}")
				
				if resp.status == 200:
					text = await resp.text()
					print(f"   📄 Page title: {re.search(r'<title>([^<]+)</title>', text, re.IGNORECASE).group(1) if re.search(r'<title>([^<]+)</title>', text, re.IGNORECASE) else 'No title'}")
					
					# Check for expected form elements
					has_username = 'txtNotandanafn' in text
					has_password = 'txtLykilord' in text
					has_viewstate = '__VIEWSTATE' in text
					
					print(f"   🔍 Has username field: {has_username}")
					print(f"   🔍 Has password field: {has_password}")
					print(f"   🔍 Has ViewState: {has_viewstate}")
					
					if not (has_username and has_password):
						print("   ⚠️  Login form fields not found!")
						print(f"   📄 Content sample: {text[:500]}")
						
				else:
					print(f"   ❌ Unexpected status: {resp.status}")
					text = await resp.text()
					print(f"   📄 Error content: {text[:500]}")
					
		except Exception as e:
			print(f"   ❌ Error: {e}")


async def test_rate_limiting():
	"""Test if there are any rate limiting or blocking mechanisms."""
	print(f"\n🔍 Testing for rate limiting...")
	
	async with aiohttp.ClientSession() as session:
		try:
			# Make multiple rapid requests to see if we get blocked
			for i in range(3):
				print(f"   Request {i+1}...")
				async with session.get(HUB_BASE_URL, headers=DEFAULT_HEADERS, allow_redirects=False) as resp:
					print(f"   📥 Status: {resp.status}")
					
					if resp.status != 302:
						text = await resp.text()
						if any(word in text.lower() for word in ['blocked', 'rate limit', 'too many', 'captcha', 'verification']):
							print("   🚫 Possible rate limiting/blocking detected!")
							print(f"   📄 Content: {text[:500]}")
							return True
				
				await asyncio.sleep(1)  # Small delay between requests
			
			print("   ✅ No obvious rate limiting detected")
			return False
			
		except Exception as e:
			print(f"   ❌ Error: {e}")
			return False


async def test_user_agent_blocking():
	"""Test if our User-Agent is being blocked."""
	print(f"\n🔍 Testing different User-Agent strings...")
	
	user_agents = [
		"Mozilla/5.0 (X11; Linux x86_64; rv:98.0) Gecko/20100101 Firefox/98.0",  # Current
		"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",  # Chrome
		"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",  # Mac Chrome
	]
	
	async with aiohttp.ClientSession() as session:
		for i, ua in enumerate(user_agents, 1):
			print(f"   Testing UA {i}: {ua[:50]}...")
			
			headers = DEFAULT_HEADERS.copy()
			headers["User-Agent"] = ua
			
			try:
				async with session.get(HUB_BASE_URL, headers=headers, allow_redirects=False) as resp:
					print(f"   📥 Status: {resp.status}")
					
					if resp.status == 302:
						location = resp.headers.get('Location')
						print(f"   ✅ Redirect to: {location}")
					else:
						text = await resp.text()
						if 'blocked' in text.lower() or 'forbidden' in text.lower():
							print(f"   🚫 Possible blocking with this UA")
						else:
							print(f"   📄 Unexpected response: {text[:200]}")
							
			except Exception as e:
				print(f"   ❌ Error with UA {i}: {e}")


async def main():
	"""Main diagnostic function."""
	print("🔧 InfoMentor Authentication Diagnostics")
	print("=" * 50)
	
	# Test each step of the authentication flow
	await test_rate_limiting()
	await test_user_agent_blocking()
	
	redirect_url = await test_initial_redirect()
	if redirect_url:
		if not redirect_url.startswith('http'):
			redirect_url = HUB_BASE_URL + redirect_url
		
		oauth_token = await test_oauth_token_extraction(redirect_url)
		if oauth_token:
			print(f"   ✅ OAuth token: {oauth_token[:20]}...")
		else:
			print("   ❌ Failed to extract OAuth token")
	else:
		print("   ❌ Failed to get initial redirect")
	
	await test_legacy_login_page()
	
	print("\n" + "=" * 50)
	print("🏁 Diagnostics complete!")
	print("\nIf you see any '🚫' or '❌' messages above, those indicate potential issues.")
	print("If rate limiting is detected, try waiting 10-15 minutes before testing again.")


if __name__ == "__main__":
	asyncio.run(main()) 