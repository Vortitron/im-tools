#!/usr/bin/env python3
"""
Debug script to examine HTML structure for switch ID extraction.
"""

import asyncio
import sys
from pathlib import Path
import re
import json

# Add the custom components to the path
sys.path.insert(0, str(Path(__file__).parent.parent / 'custom_components' / 'infomentor'))

from infomentor import InfoMentorClient
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv(Path(__file__).parent / '.env')

async def debug_switch_extraction():
    """Debug the switch ID extraction."""
    username = os.getenv("INFOMENTOR_USERNAME")
    password = os.getenv("INFOMENTOR_PASSWORD")
    
    if not username or not password:
        print("❌ Missing credentials")
        return
    
    async with InfoMentorClient() as client:
        print(f"🔐 Authenticating...")
        if not await client.login(username, password):
            print("❌ Authentication failed")
            return
        
        # Get the hub page HTML
        headers = {'User-Agent': 'Mozilla/5.0'}
        hub_url = "https://hub.infomentor.se/#/"
        
        async with client.auth.session.get(hub_url, headers=headers) as resp:
            if resp.status == 200:
                html = await resp.text()
                
                print("🔍 Looking for switch patterns...")
                
                # Try the original pattern
                switch_pattern = r'"switchPupilUrl"\s*:\s*"[^"]*SwitchPupil/(\d+)"[^}]*"name"\s*:\s*"([^"]+)"'
                matches = re.findall(switch_pattern, html, re.IGNORECASE)
                
                print(f"Found {len(matches)} switch URL matches:")
                for switch_id, name in matches:
                    print(f"  - {name}: SwitchPupil/{switch_id}")
                
                # Now let's look for the full JSON objects containing these pupils
                print("\n🔍 Looking for full pupil JSON objects...")
                
                # Find JSON objects that contain switch URLs
                for switch_id, name in matches:
                    print(f"\n📋 Searching for pupil data for {name} (Switch ID: {switch_id})")
                    
                    # Look for JSON object containing this switch URL
                    # Try a broader search pattern
                    patterns_to_try = [
                        rf'{{"[^}}]*"switchPupilUrl"[^}}]*SwitchPupil/{re.escape(switch_id)}[^}}]*}}',
                        rf'{{"[^}}]*SwitchPupil/{re.escape(switch_id)}[^}}]*"hybridMappingId"[^}}]*}}',
                        rf'"hybridMappingId"\s*:\s*"[^"]*"[^}}]*"switchPupilUrl"[^}}]*SwitchPupil/{re.escape(switch_id)}[^}}]*',
                    ]
                    
                    for i, pattern in enumerate(patterns_to_try):
                        try:
                            object_matches = re.findall(pattern, html, re.IGNORECASE | re.DOTALL)
                            print(f"  Pattern {i+1}: Found {len(object_matches)} matches")
                            
                            for j, obj_match in enumerate(object_matches[:2]):  # Show first 2
                                print(f"    Match {j+1}: {obj_match[:200]}...")
                                
                                # Try to extract hybridMappingId from this object
                                hybrid_pattern = r'"hybridMappingId"\s*:\s*"[^|]*\|(\d+)\|'
                                hybrid_matches = re.findall(hybrid_pattern, obj_match)
                                if hybrid_matches:
                                    print(f"      Found pupil ID: {hybrid_matches[0]}")
                                else:
                                    print(f"      No pupil ID found in this match")
                        except Exception as e:
                            print(f"  Pattern {i+1} error: {e}")
                
                # Let's also try to find all hybridMappingId patterns
                print("\n🔍 All hybridMappingId patterns in HTML:")
                hybrid_pattern = r'"hybridMappingId"\s*:\s*"([^"]+)"'
                all_hybrids = re.findall(hybrid_pattern, html, re.IGNORECASE)
                
                print(f"Found {len(all_hybrids)} hybridMappingId entries:")
                for hybrid in all_hybrids[:10]:  # Show first 10
                    print(f"  - {hybrid}")
                    
                    # Extract pupil ID from hybrid format
                    if '|' in hybrid:
                        parts = hybrid.split('|')
                        if len(parts) >= 2 and parts[1].isdigit():
                            print(f"    → Pupil ID: {parts[1]}")

if __name__ == "__main__":
    asyncio.run(debug_switch_extraction()) 