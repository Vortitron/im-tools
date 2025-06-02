#!/usr/bin/env python3
"""
OAuth Diagnostics Script for InfoMentor Integration

This script helps diagnose OAuth authentication issues by:
1. Running the authentication process with enhanced logging
2. Performing authentication state verification
3. Providing detailed diagnostic information

Usage:
    python test_oauth_diagnostics.py

Make sure to set your credentials in a .env file or environment variables:
    INFOMENTOR_USERNAME=your_username
    INFOMENTOR_PASSWORD=your_password
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Add the custom components path to sys.path
sys.path.insert(0, str(Path(__file__).parent / "custom_components" / "infomentor"))

from infomentor.client import InfoMentorClient
from infomentor.exceptions import InfoMentorAuthError, InfoMentorConnectionError

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('oauth_diagnostics.log')
    ]
)

_LOGGER = logging.getLogger(__name__)


async def main():
    """Run OAuth diagnostics."""
    print("InfoMentor OAuth Diagnostics Tool")
    print("=" * 40)
    
    # Get credentials
    username = os.getenv('INFOMENTOR_USERNAME')
    password = os.getenv('INFOMENTOR_PASSWORD')
    
    if not username or not password:
        print("Error: Please set INFOMENTOR_USERNAME and INFOMENTOR_PASSWORD environment variables")
        print("You can create a .env file with these variables.")
        return
    
    print(f"Testing authentication for user: {username}")
    print()
    
    # Test authentication
    async with InfoMentorClient() as client:
        try:
            print("Step 1: Attempting login...")
            success = await client.login(username, password)
            print(f"Login result: {'SUCCESS' if success else 'FAILED'}")
            print()
            
            print("Step 2: Running authentication diagnostics...")
            diagnostics = await client.diagnose_authentication()
            
            print("Diagnostic Results:")
            print("-" * 20)
            for key, value in diagnostics.items():
                if key == "endpoints_accessible":
                    print(f"{key}:")
                    for endpoint_name, endpoint_info in value.items():
                        status = endpoint_info.get('status', 'unknown')
                        accessible = endpoint_info.get('accessible', False)
                        has_auth = endpoint_info.get('has_auth_content', False)
                        print(f"  {endpoint_name}: {status} (accessible: {accessible}, auth_content: {has_auth})")
                elif key == "errors":
                    if value:
                        print(f"{key}: {len(value)} errors found")
                        for error in value:
                            print(f"  - {error}")
                    else:
                        print(f"{key}: None")
                else:
                    print(f"{key}: {value}")
            print()
            
            if success:
                print("Step 3: Testing pupil ID retrieval...")
                pupil_ids = await client.get_pupil_ids()
                print(f"Found {len(pupil_ids)} pupil IDs: {pupil_ids}")
                print()
                
                if pupil_ids:
                    print("Step 4: Testing API calls...")
                    try:
                        # Test news retrieval
                        news = await client.get_news(pupil_ids[0])
                        print(f"News retrieval: SUCCESS ({len(news)} items)")
                    except Exception as e:
                        print(f"News retrieval: FAILED - {e}")
                    
                    try:
                        # Test timeline retrieval
                        timeline = await client.get_timeline(pupil_ids[0])
                        print(f"Timeline retrieval: SUCCESS ({len(timeline)} items)")
                    except Exception as e:
                        print(f"Timeline retrieval: FAILED - {e}")
                else:
                    print("Step 4: SKIPPED - No pupil IDs found")
            else:
                print("Step 3-4: SKIPPED - Authentication failed")
                
        except InfoMentorAuthError as e:
            print(f"Authentication Error: {e}")
        except InfoMentorConnectionError as e:
            print(f"Connection Error: {e}")
        except Exception as e:
            print(f"Unexpected Error: {e}")
            _LOGGER.exception("Unexpected error during diagnostics")
    
    print()
    print("Diagnostics complete. Check 'oauth_diagnostics.log' for detailed logs.")
    print()
    
    # Provide recommendations
    print("Recommendations:")
    print("-" * 20)
    print("1. If OAuth warnings appear but authentication succeeds, the integration should work")
    print("2. If no pupil IDs are found, check if your account has access to student data")
    print("3. If endpoints are not accessible, there may be a network or session issue")
    print("4. Check the detailed logs for specific error patterns")
    print("5. If the issue persists, the OAuth completion logic may need adjustment")


if __name__ == "__main__":
    # Load .env file if it exists
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass  # dotenv not available, that's okay
    
    asyncio.run(main()) 