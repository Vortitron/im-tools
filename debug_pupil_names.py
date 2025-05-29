#!/usr/bin/env python3
"""
Debug script to examine HTML content and extract real pupil names.
"""

import asyncio
import getpass
import os
import sys
import re
from pathlib import Path

# Try to load environment variables from .env file
try:
	from dotenv import load_dotenv
	load_dotenv()
except ImportError:
	print("💡 Tip: Install python-dotenv to use .env file for credentials:")
	print("    pip install python-dotenv")

# Add the custom_components directory to Python path
sys.path.insert(0, str(Path(__file__).parent / "custom_components" / "infomentor"))

try:
	from infomentor import InfoMentorClient
except ImportError as e:
	print(f"❌ Import error: {e}")
	sys.exit(1)


async def debug_html_content(client: InfoMentorClient):
	"""Debug HTML content to find pupil names."""
	print("🔍 Debugging HTML content...")
	
	try:
		hub_url = "https://hub.infomentor.se/#/"
		headers = {
			"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
			"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:98.0) Gecko/20100101 Firefox/98.0",
		}
		
		async with client._session.get(hub_url, headers=headers) as resp:
			if resp.status != 200:
				print(f"   ❌ Failed to get hub page: HTTP {resp.status}")
				return
			
			text = await resp.text()
		
		# Save HTML for analysis
		with open("debug_hub_page.html", "w", encoding="utf-8") as f:
			f.write(text)
		print("   💾 Saved HTML to debug_hub_page.html")
		
		# Look for pupil IDs
		pupil_ids = client.auth.pupil_ids
		print(f"   📊 Known pupil IDs: {pupil_ids}")
		
		# Search for each pupil ID in the HTML
		for pupil_id in pupil_ids:
			print(f"\n   🔍 Searching for pupil ID {pupil_id}:")
			
			# Find all lines containing the pupil ID
			lines = text.split('\n')
			for i, line in enumerate(lines):
				if pupil_id in line:
					print(f"      Line {i+1}: {line.strip()[:100]}...")
			
			# Try to find context around the pupil ID
			matches = list(re.finditer(pupil_id, text))
			for match in matches[:3]:  # Show first 3 matches
				start = max(0, match.start() - 100)
				end = min(len(text), match.end() + 100)
				context = text[start:end]
				print(f"      Context: ...{context}...")
				
		# Look for common name patterns
		print(f"\n   🔍 Looking for name patterns:")
		name_patterns = [
			r'"name"\s*:\s*"([^"]+)"',
			r'data-name="([^"]+)"',
			r'title="([^"]+)"',
			r'>([A-Z][a-z]+ [A-Z][a-z]+)<',  # First Last format
			r'>([A-Z][a-z]+, [A-Z][a-z]+)<',  # Last, First format
		]
		
		for pattern in name_patterns:
			matches = re.findall(pattern, text)
			if matches:
				print(f"      Pattern '{pattern}' found {len(matches)} matches:")
				for match in matches[:5]:  # Show first 5
					if isinstance(match, tuple):
						match = match[0]
					if len(match) > 3 and len(match) < 50:
						print(f"         - {match}")
		
	except Exception as e:
		print(f"   ❌ Error: {e}")


async def main():
	"""Main function."""
	print("🔍 Pupil Names Debug Script")
	print("=" * 40)
	
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
	
	async with InfoMentorClient() as client:
		try:
			print("\n🔐 Authenticating...")
			if not await client.login(username, password):
				print("❌ Authentication failed!")
				return
			
			print("✅ Authentication successful!")
			await debug_html_content(client)
			
		except Exception as e:
			print(f"❌ Error: {e}")
			raise


if __name__ == "__main__":
	asyncio.run(main()) 