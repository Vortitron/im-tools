#!/usr/bin/env python3
"""
Test script to investigate OAuth flow mimicry for InfoMentor.
"""

import asyncio
import aiohttp
import re
import os
from urllib.parse import urljoin, urlparse, parse_qs

# Get credentials from environment variables
USERNAME = os.getenv("INFOMENTOR_USERNAME")
PASSWORD = os.getenv("INFOMENTOR_PASSWORD")

if not USERNAME or not PASSWORD:
    print("❌ Please set INFOMENTOR_USERNAME and INFOMENTOR_PASSWORD environment variables")
    exit(1)

# Constants
HUB_BASE_URL = "https://hub.infomentor.se"

DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "sv-SE,sv;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "Pragma": "no-cache",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
}

async def investigate_oauth_flow():
    """Investigate the OAuth flow to understand the complete process."""
    print("🔍 Investigating OAuth flow...")
    
    async with aiohttp.ClientSession() as session:
        # Start with the OAuth login URL
        oauth_url = f"{HUB_BASE_URL}/Authentication/Authentication/Login?apiType=IM1&forceOAuth=true&apiInstance="
        print(f"📍 Starting OAuth investigation at: {oauth_url}")
        
        headers = DEFAULT_HEADERS.copy()
        
        try:
            async with session.get(oauth_url, headers=headers, allow_redirects=True) as resp:
                print(f"📊 OAuth request status: {resp.status}")
                print(f"📍 Final URL after redirects: {resp.url}")
                print(f"🍪 Response cookies: {list(session.cookie_jar)}")
                
                # Parse final URL to understand OAuth parameters
                parsed_url = urlparse(str(resp.url))
                query_params = parse_qs(parsed_url.query)
                
                print(f"📋 URL path: {parsed_url.path}")
                print(f"📋 Query parameters: {query_params}")
                
                text = await resp.text()
                print(f"📄 Response content length: {len(text)}")
                
                # Save for analysis
                with open("/tmp/oauth_investigation.html", "w", encoding="utf-8") as f:
                    f.write(text)
                print("💾 Saved response to /tmp/oauth_investigation.html")
                
                # Look for OAuth tokens and verifiers
                oauth_tokens = re.findall(r'oauth_token["\']?\s*[:=]\s*["\']?([^"\'&\s<>]+)', text, re.IGNORECASE)
                oauth_verifiers = re.findall(r'oauth_verifier["\']?\s*[:=]\s*["\']?([^"\'&\s<>]+)', text, re.IGNORECASE)
                
                print(f"🔑 Found OAuth tokens: {oauth_tokens}")
                print(f"🔑 Found OAuth verifiers: {oauth_verifiers}")
                
                # Check for forms that might contain OAuth data
                forms = re.findall(r'<form[^>]*>(.*?)</form>', text, re.DOTALL | re.IGNORECASE)
                print(f"📝 Found {len(forms)} forms")
                
                for i, form in enumerate(forms):
                    print(f"📝 Form {i+1}:")
                    # Extract form action
                    action_match = re.search(r'action=["\']([^"\']+)["\']', form, re.IGNORECASE)
                    if action_match:
                        print(f"   Action: {action_match.group(1)}")
                    
                    # Extract hidden inputs
                    hidden_inputs = re.findall(r'<input[^>]*type=["\']hidden["\'][^>]*>', form, re.IGNORECASE)
                    for hidden in hidden_inputs:
                        name_match = re.search(r'name=["\']([^"\']+)["\']', hidden, re.IGNORECASE)
                        value_match = re.search(r'value=["\']([^"\']+)["\']', hidden, re.IGNORECASE)
                        if name_match and value_match:
                            print(f"   Hidden: {name_match.group(1)} = {value_match.group(1)}")
                
                # Look for JavaScript that might handle OAuth
                scripts = re.findall(r'<script[^>]*>(.*?)</script>', text, re.DOTALL | re.IGNORECASE)
                oauth_js = []
                for script in scripts:
                    if 'oauth' in script.lower() or 'token' in script.lower():
                        oauth_js.append(script.strip())
                
                if oauth_js:
                    print(f"🔧 Found {len(oauth_js)} scripts with OAuth/token references")
                    for i, js in enumerate(oauth_js[:2]):  # Show first 2
                        print(f"🔧 Script {i+1} (first 200 chars): {js[:200]}...")
                
                # Check if this is a LoginCallback URL (like user's example)
                if 'LoginCallback' in str(resp.url):
                    print("✅ This is a LoginCallback URL!")
                    
                    # Extract oauth_token and oauth_verifier from URL
                    url_oauth_token = query_params.get('oauth_token', [None])[0]
                    url_oauth_verifier = query_params.get('oauth_verifier', [None])[0]
                    
                    if url_oauth_token:
                        print(f"🔑 URL OAuth token: {url_oauth_token}")
                    if url_oauth_verifier:
                        print(f"🔑 URL OAuth verifier: {url_oauth_verifier}")
                        
                elif 'Authentication/Login' in str(resp.url):
                    print("📍 This is still a Login URL - might need manual interaction")
                    
                    # Check for login forms
                    login_forms = re.findall(r'<form[^>]*(?:login|credential)[^>]*>(.*?)</form>', text, re.DOTALL | re.IGNORECASE)
                    if login_forms:
                        print(f"📝 Found {len(login_forms)} potential login forms")
                
        except Exception as e:
            print(f"❌ Error during OAuth investigation: {e}")
            raise

async def test_manual_oauth_callback():
    """Test manually constructing an OAuth callback URL like the user's example."""
    print("\n🔧 Testing manual OAuth callback construction...")
    
    # Example from user: oauth_verifier=TddqUs0%3D&oauth_token=xWbMplBxk7HKHFkP09fcQclMFZk%3D
    # Let's try to understand the format
    
    # These are URL-encoded. Let's decode them:
    import urllib.parse
    
    example_verifier = "TddqUs0%3D"  # URL encoded
    example_token = "xWbMplBxk7HKHFkP09fcQclMFZk%3D"  # URL encoded
    
    decoded_verifier = urllib.parse.unquote(example_verifier)
    decoded_token = urllib.parse.unquote(example_token)
    
    print(f"🔑 Example OAuth verifier (decoded): {decoded_verifier}")
    print(f"🔑 Example OAuth token (decoded): {decoded_token}")
    
    # Notice both end with '=' which suggests base64 encoding
    print("💡 Both values end with '=' suggesting base64 encoding")
    
    # Try to construct a similar callback URL
    callback_url = f"{HUB_BASE_URL}/Authentication/Authentication/LoginCallback?apitype=im1&apiinstance=&oauth_verifier={example_verifier}&oauth_token={example_token}"
    
    print(f"🔗 Constructed callback URL: {callback_url}")
    
    async with aiohttp.ClientSession() as session:
        headers = DEFAULT_HEADERS.copy()
        headers["Referer"] = f"{HUB_BASE_URL}/Authentication/Authentication/Login"
        
        try:
            print("📡 Testing callback URL...")
            async with session.get(callback_url, headers=headers, allow_redirects=True) as resp:
                print(f"📊 Callback response status: {resp.status}")
                print(f"📍 Final URL: {resp.url}")
                
                text = await resp.text()
                print(f"📄 Response content length: {len(text)}")
                
                # Save for analysis
                with open("/tmp/oauth_callback_test.html", "w", encoding="utf-8") as f:
                    f.write(text)
                print("💾 Saved callback response to /tmp/oauth_callback_test.html")
                
                # Check if we get a meaningful response
                if "infomentor" in text.lower():
                    print("✅ Response contains InfoMentor content")
                else:
                    print("❌ Response doesn't seem to contain InfoMentor content")
                    
                # Look for error messages
                if "error" in text.lower() or "fel" in text.lower():
                    print("⚠️ Response may contain error messages")
                    
        except Exception as e:
            print(f"❌ Error testing callback URL: {e}")

async def main():
    """Main test function."""
    print("🚀 Starting OAuth flow investigation...")
    print(f"👤 Testing with username: {USERNAME}")
    
    await investigate_oauth_flow()
    await test_manual_oauth_callback()
    
    print("\n✅ OAuth investigation completed!")
    print("📁 Check /tmp/oauth_investigation.html and /tmp/oauth_callback_test.html for detailed responses")

if __name__ == "__main__":
    asyncio.run(main())
