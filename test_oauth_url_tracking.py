#!/usr/bin/env python3
"""
Test script to track all URLs during OAuth flow to understand where LoginCallback should occur.
"""

import asyncio
import aiohttp
import os
import sys
from urllib.parse import urlparse, parse_qs

# Add the custom_components path to Python path
sys.path.insert(0, '/var/www/im-tools/custom_components/infomentor')

# Get credentials from environment variables
USERNAME = os.getenv("INFOMENTOR_USERNAME")
PASSWORD = os.getenv("INFOMENTOR_PASSWORD")

if not USERNAME or not PASSWORD:
    print("❌ Please set INFOMENTOR_USERNAME and INFOMENTOR_PASSWORD environment variables")
    exit(1)

# Constants
HUB_BASE_URL = "https://hub.infomentor.se"
LEGACY_BASE_URL = "https://infomentor.se/swedish/production/mentor/"

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

class URLTracker:
    """Track all URLs encountered during the OAuth flow."""
    
    def __init__(self):
        self.urls = []
        self.login_callbacks = []
        
    def add_url(self, url, step_description):
        """Add a URL to the tracking list."""
        parsed = urlparse(url)
        query_params = parse_qs(parsed.query)
        
        url_info = {
            'step': step_description,
            'url': url,
            'domain': parsed.netloc,
            'path': parsed.path,
            'query_params': query_params
        }
        
        self.urls.append(url_info)
        
        # Check for LoginCallback specifically
        if 'LoginCallback' in url:
            oauth_token = query_params.get('oauth_token', [None])[0]
            oauth_verifier = query_params.get('oauth_verifier', [None])[0]
            
            callback_info = {
                'step': step_description,
                'url': url,
                'oauth_token': oauth_token,
                'oauth_verifier': oauth_verifier
            }
            
            self.login_callbacks.append(callback_info)
            print(f"🎯 FOUND LOGINCALLBACK: {step_description}")
            print(f"   URL: {url}")
            print(f"   OAuth Token: {oauth_token[:20] if oauth_token else 'None'}...")
            print(f"   OAuth Verifier: {oauth_verifier[:20] if oauth_verifier else 'None'}...")
        
        print(f"📍 {step_description}: {parsed.netloc}{parsed.path}")
        if query_params:
            for key, values in query_params.items():
                print(f"   {key}: {values[0] if values else ''}")
    
    def print_summary(self):
        """Print a summary of all tracked URLs."""
        print("\n" + "="*80)
        print("📋 URL TRACKING SUMMARY")
        print("="*80)
        
        for i, url_info in enumerate(self.urls, 1):
            print(f"{i}. {url_info['step']}")
            print(f"   Domain: {url_info['domain']}")
            print(f"   Path: {url_info['path']}")
            if url_info['query_params']:
                for key, values in url_info['query_params'].items():
                    print(f"   {key}: {values[0] if values else ''}")
            print()
        
        if self.login_callbacks:
            print(f"🎯 FOUND {len(self.login_callbacks)} LOGINCALLBACK(S):")
            for callback in self.login_callbacks:
                print(f"   Step: {callback['step']}")
                print(f"   OAuth Token: {callback['oauth_token'][:20] if callback['oauth_token'] else 'None'}...")
                print(f"   OAuth Verifier: {callback['oauth_verifier'][:20] if callback['oauth_verifier'] else 'None'}...")
                print()
        else:
            print("❌ NO LOGINCALLBACK URLs FOUND")
            print("💡 This suggests the OAuth flow isn't reaching the final callback step")

async def track_oauth_flow():
    """Track the complete OAuth flow to see all URL redirects."""
    print("🔍 Tracking complete OAuth flow URLs...")
    
    tracker = URLTracker()
    
    async with aiohttp.ClientSession() as session:
        
        # Step 1: Initial OAuth request
        oauth_url = f"{HUB_BASE_URL}/Authentication/Authentication/Login?apiType=IM1&forceOAuth=true&apiInstance="
        headers = DEFAULT_HEADERS.copy()
        
        print("🚀 Starting OAuth URL tracking...")
        
        try:
            async with session.get(oauth_url, headers=headers, allow_redirects=True) as resp:
                tracker.add_url(str(resp.url), "Initial OAuth Request")
                
                text = await resp.text()
                
                # Extract OAuth token
                import re
                oauth_match = re.search(r'<input[^>]*name=["\']oauth_token["\'][^>]*value=["\']([^"\']+)["\']', text, re.IGNORECASE)
                if oauth_match:
                    oauth_token = oauth_match.group(1)
                    print(f"🔑 Found OAuth token: {oauth_token[:20]}...")
                    
                    # Step 2: Submit OAuth token
                    oauth_data = f"oauth_token={oauth_token}"
                    headers.update({
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Origin": HUB_BASE_URL,
                        "Referer": str(resp.url),
                    })
                    
                    async with session.post(LEGACY_BASE_URL, headers=headers, data=oauth_data, allow_redirects=True) as stage1_resp:
                        tracker.add_url(str(stage1_resp.url), "OAuth Token Submission")
                        
                        stage1_text = await stage1_resp.text()
                        
                        # Check for credential form
                        if any(field in stage1_text.lower() for field in ['txtnotandanafn', 'txtlykilord']):
                            print("🔍 Found credential form, submitting credentials...")
                            
                            # Extract form fields
                            form_data = {}
                            
                            # ViewState fields for ASP.NET
                            for field in ['__VIEWSTATE', '__VIEWSTATEGENERATOR', '__EVENTVALIDATION']:
                                pattern = f'{field}["\'][^>]*value=["\']([^"\']+)["\']'
                                match = re.search(pattern, stage1_text)
                                if match:
                                    form_data[field] = match.group(1)
                            
                            # Set form submission fields
                            form_data.update({
                                '__EVENTTARGET': 'login_ascx$btnLogin',
                                '__EVENTARGUMENT': '',
                                'login_ascx$txtNotandanafn': USERNAME,
                                'login_ascx$txtLykilord': PASSWORD,
                            })
                            
                            headers.update({
                                "Origin": "https://infomentor.se",
                                "Referer": str(stage1_resp.url),
                            })
                            
                            from urllib.parse import urlencode
                            
                            async with session.post(str(stage1_resp.url), headers=headers, data=urlencode(form_data), allow_redirects=True) as cred_resp:
                                tracker.add_url(str(cred_resp.url), "Credential Submission")
                                
                                cred_text = await cred_resp.text()
                                
                                # Look for second OAuth token
                                second_oauth_match = re.search(r'oauth_token"\s+value="([\w+=/]+)"', cred_text)
                                if second_oauth_match:
                                    second_oauth_token = second_oauth_match.group(1)
                                    print(f"🔑 Found second OAuth token: {second_oauth_token[:20]}...")
                                    
                                    # Step 4: Submit second OAuth token
                                    oauth_data2 = f"oauth_token={second_oauth_token}"
                                    headers.update({
                                        "Origin": HUB_BASE_URL,
                                        "Referer": f"{HUB_BASE_URL}/authentication/authentication/login?apitype=im1&forceOAuth=true",
                                    })
                                    
                                    async with session.post(LEGACY_BASE_URL, headers=headers, data=oauth_data2, allow_redirects=True) as final_resp:
                                        tracker.add_url(str(final_resp.url), "Second OAuth Token Submission")
                                        
                                        final_text = await final_resp.text()
                                        
                                        # Save final response
                                        with open("/tmp/oauth_final_response.html", "w", encoding="utf-8") as f:
                                            f.write(final_text)
                                        
                                        print("💾 Saved final OAuth response to /tmp/oauth_final_response.html")
                                        
                                        # Try accessing dashboard to see where it leads
                                        dashboard_headers = DEFAULT_HEADERS.copy()
                                        dashboard_headers["Referer"] = str(final_resp.url)
                                        
                                        async with session.get(f"{LEGACY_BASE_URL}", headers=dashboard_headers, allow_redirects=True) as dashboard_resp:
                                            tracker.add_url(str(dashboard_resp.url), "Dashboard Access Attempt")
                                            
                                            dashboard_text = await dashboard_resp.text()
                                            
                                            with open("/tmp/oauth_dashboard_attempt.html", "w", encoding="utf-8") as f:
                                                f.write(dashboard_text)
                                            
                                            print("💾 Saved dashboard attempt to /tmp/oauth_dashboard_attempt.html")
                else:
                    print("❌ No OAuth token found in initial response")
                    
        except Exception as e:
            print(f"❌ Error during OAuth tracking: {e}")
            import traceback
            traceback.print_exc()
    
    tracker.print_summary()
    
    return tracker

async def main():
    """Main tracking function."""
    print("🎯 OAuth URL Tracking Test")
    print("=" * 50)
    print(f"👤 Username: {USERNAME}")
    print(f"🔗 User's example LoginCallback: https://hub.infomentor.se/Authentication/Authentication/LoginCallback?apitype=im1&apiinstance=&oauth_verifier=...&oauth_token=...")
    print("=" * 50)
    
    tracker = await track_oauth_flow()
    
    if not tracker.login_callbacks:
        print("\n🤔 ANALYSIS:")
        print("The OAuth flow is not reaching the LoginCallback URL that the user mentioned.")
        print("This suggests we need to investigate why the flow stops before that step.")
        print("Possible reasons:")
        print("1. The OAuth flow is completing but not triggering the callback")
        print("2. We need to make additional requests to trigger the callback")
        print("3. The callback happens in JavaScript that we're not executing")
        print("4. There's a missing step in our OAuth implementation")

if __name__ == "__main__":
    asyncio.run(main())
