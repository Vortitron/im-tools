#!/usr/bin/env python3
"""
Debug script to examine the session expired page and understand the authentication flow.
"""

import asyncio
import aiohttp
import re
from urllib.parse import urlparse, parse_qs

# Constants
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


async def examine_session_expired_page():
	"""Examine the session expired page in detail."""
	print("🔍 Examining session expired page...")
	
	async with aiohttp.ClientSession() as session:
		async with session.get(LEGACY_BASE_URL, headers=DEFAULT_HEADERS) as resp:
			print(f"   📥 Status: {resp.status}")
			print(f"   📋 Headers: {dict(resp.headers)}")
			
			text = await resp.text()
			
			# Save the full content for analysis
			with open("session_expired_page.html", "w", encoding="utf-8") as f:
				f.write(text)
			print("   💾 Saved full page to: session_expired_page.html")
			
			print(f"   📄 Full content:\n{text}")
			
			# Look for any redirect URLs or instructions
			redirect_patterns = [
				r'window\.location\.href\s*=\s*["\']([^"\']+)["\']',
				r'location\.href\s*=\s*["\']([^"\']+)["\']',
				r'<meta[^>]*http-equiv=["\']refresh["\'][^>]*content=["\'][^;]*;\s*url=([^"\']+)["\']',
				r'href=["\']([^"\']*login[^"\']*)["\']',
			]
			
			for pattern in redirect_patterns:
				matches = re.findall(pattern, text, re.IGNORECASE)
				if matches:
					print(f"   🔗 Found redirect pattern: {pattern}")
					for match in matches:
						print(f"      → {match}")


async def test_oauth_flow_with_session():
	"""Test the complete OAuth flow with session handling."""
	print("\n🔍 Testing complete OAuth flow with session...")
	
	async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar()) as session:
		# Step 1: Get initial redirect
		print("   Step 1: Getting initial redirect...")
		async with session.get(HUB_BASE_URL, headers=DEFAULT_HEADERS, allow_redirects=False) as resp:
			location = resp.headers.get('Location')
			print(f"   📍 Redirect to: {location}")
			
			if location and not location.startswith('http'):
				oauth_url = HUB_BASE_URL + location
			else:
				oauth_url = location
		
		if not oauth_url:
			print("   ❌ No OAuth URL found")
			return
		
		# Step 2: Get OAuth token
		print(f"   Step 2: Getting OAuth token from: {oauth_url}")
		async with session.get(oauth_url, headers=DEFAULT_HEADERS) as resp:
			text = await resp.text()
			
			oauth_match = re.search(r'oauth_token"\s+value="([\w+=/]+)"', text)
			if oauth_match:
				oauth_token = oauth_match.group(1)
				print(f"   ✅ OAuth token: {oauth_token[:20]}...")
			else:
				print("   ❌ No OAuth token found")
				return
		
		# Step 3: Try to send OAuth token to legacy URL
		print("   Step 3: Sending OAuth token to legacy URL...")
		
		headers = DEFAULT_HEADERS.copy()
		headers.update({
			"Content-Type": "application/x-www-form-urlencoded",
			"Origin": HUB_BASE_URL,
			"Referer": oauth_url,
		})
		
		data = f"oauth_token={oauth_token}"
		
		async with session.post(LEGACY_BASE_URL, headers=headers, data=data, allow_redirects=False) as resp:
			print(f"   📥 OAuth POST status: {resp.status}")
			print(f"   📋 Headers: {dict(resp.headers)}")
			
			location = resp.headers.get('Location')
			if location:
				print(f"   🔗 Redirect location: {location}")
			
			text = await resp.text()
			print(f"   📄 Response content (first 500 chars): {text[:500]}")
			
			# Check if this is a session expired message
			if "session expired" in text.lower() or "session" in text.lower():
				print("   ⚠️  Got session expired message")
				
				# Look for any clues about how to proceed
				if "login" in text.lower():
					print("   💡 Page mentions login - might need different approach")
				
				# Try to see what cookies we have
				print(f"   🍪 Current cookies: {session.cookie_jar}")


async def test_different_login_approach():
	"""Test a different approach - going directly to the login page without OAuth."""
	print("\n🔍 Testing direct login page access...")
	
	# Try different login URLs that might work
	login_urls = [
		"https://infomentor.se/Swedish/Production/mentor/Oryggi/Login.aspx",
		"https://infomentor.se/login",
		"https://infomentor.se/",
		"https://hub.infomentor.se/Authentication/Authentication/Login",
	]
	
	async with aiohttp.ClientSession() as session:
		for url in login_urls:
			print(f"   Testing: {url}")
			try:
				async with session.get(url, headers=DEFAULT_HEADERS) as resp:
					print(f"   📥 Status: {resp.status}")
					
					if resp.status == 200:
						text = await resp.text()
						title_match = re.search(r'<title>([^<]+)</title>', text, re.IGNORECASE)
						title = title_match.group(1) if title_match else "No title"
						print(f"   📄 Title: {title}")
						
						# Check for login form
						has_username = 'txtNotandanafn' in text or 'username' in text.lower()
						has_password = 'txtLykilord' in text or 'password' in text.lower()
						
						print(f"   📝 Has login form: username={has_username}, password={has_password}")
						
						if has_username and has_password:
							print(f"   ✅ Found working login page!")
							break
					else:
						print(f"   ❌ HTTP {resp.status}")
						
			except Exception as e:
				print(f"   ❌ Error: {e}")


async def main():
	"""Main function."""
	print("🔧 Session Expired Investigation")
	print("=" * 50)
	
	await examine_session_expired_page()
	await test_oauth_flow_with_session()
	await test_different_login_approach()
	
	print("\n" + "=" * 50)
	print("🏁 Investigation complete!")


if __name__ == "__main__":
	asyncio.run(main()) 