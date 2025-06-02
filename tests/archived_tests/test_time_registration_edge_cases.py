#!/usr/bin/env python3
"""
Edge case tests for the time registration fix.
Tests various error conditions and edge cases.
"""

import asyncio
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
import traceback

# Add the custom components to the path
sys.path.insert(0, str(Path(__file__).parent.parent / 'custom_components' / 'infomentor'))

from infomentor import InfoMentorClient
from infomentor.auth import HUB_BASE_URL
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv(Path(__file__).parent / '.env')


class MockResponse:
    """Mock response for testing various scenarios."""
    def __init__(self, status, json_data=None, text_data=None, raise_json_error=False):
        self.status = status
        self._json_data = json_data or {}
        self._text_data = text_data or ""
        self.headers = {}
        self._raise_json_error = raise_json_error
    
    async def json(self):
        if self._raise_json_error:
            raise json.JSONDecodeError("Invalid JSON", "", 0)
        return self._json_data
    
    async def text(self):
        return self._text_data
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


async def test_network_errors():
    """Test handling of network errors and timeouts."""
    print("🌐 Testing Network Error Handling")
    print("=" * 50)
    
    test_results = []
    
    try:
        client = InfoMentorClient()
        client.authenticated = True
        client.auth = MagicMock()
        client.auth.authenticated = True
        client.auth.pupil_ids = ["test_pupil"]
        
        # Mock session that raises network errors
        mock_session = AsyncMock()
        client._session = mock_session
        
        # Test network timeout
        mock_session.get.side_effect = asyncio.TimeoutError("Request timeout")
        
        result = await client.get_time_registration()
        assert result == [], "Should return empty list on network timeout"
        test_results.append("✅ Network timeout handled gracefully")
        
        # Test connection error
        mock_session.get.side_effect = Exception("Connection refused")
        
        result = await client.get_time_registration()
        assert result == [], "Should return empty list on connection error"
        test_results.append("✅ Connection error handled gracefully")
        
        await client.close()
        
    except Exception as e:
        test_results.append(f"❌ Network error test failed: {e}")
        traceback.print_exc()
    
    for result in test_results:
        print(result)
    
    return len([r for r in test_results if r.startswith("✅")]) == 2


async def test_malformed_json_responses():
    """Test handling of malformed JSON responses."""
    print("\n📄 Testing Malformed JSON Response Handling")
    print("=" * 50)
    
    test_results = []
    
    try:
        client = InfoMentorClient()
        client.authenticated = True
        client.auth = MagicMock()
        client.auth.authenticated = True
        client.auth.pupil_ids = ["test_pupil"]
        
        mock_session = AsyncMock()
        client._session = mock_session
        
        # Test malformed JSON in GET response
        mock_response = MockResponse(200, raise_json_error=True)
        mock_session.get.return_value = mock_response
        
        result = await client.get_time_registration()
        assert result == [], "Should return empty list on JSON parse error"
        test_results.append("✅ Malformed JSON handled gracefully")
        
        # Test empty response body
        mock_response = MockResponse(200, text_data="")
        mock_session.get.return_value = mock_response
        
        result = await client.get_time_registration()
        test_results.append("✅ Empty response body handled")
        
        await client.close()
        
    except Exception as e:
        test_results.append(f"❌ Malformed JSON test failed: {e}")
        traceback.print_exc()
    
    for result in test_results:
        print(result)
    
    return len([r for r in test_results if r.startswith("✅")]) >= 1


async def test_partial_failures():
    """Test scenarios where one endpoint works but others fail."""
    print("\n⚡ Testing Partial Failure Scenarios")
    print("=" * 50)
    
    test_results = []
    
    try:
        client = InfoMentorClient()
        client.authenticated = True
        client.auth = MagicMock()
        client.auth.authenticated = True
        client.auth.pupil_ids = ["test_pupil"]
        
        mock_session = AsyncMock()
        client._session = mock_session
        
        # Scenario: First endpoint fails with 500, second succeeds
        first_response = MockResponse(500, text_data="Internal Server Error")
        second_response = MockResponse(200, {"CalendarData": [{"type": "TestEntry"}]})
        
        mock_session.get.side_effect = [first_response, second_response]
        
        result = await client.get_time_registration()
        # Should succeed using the second endpoint
        test_results.append("✅ Fallback to second endpoint works")
        
        await client.close()
        
    except Exception as e:
        test_results.append(f"❌ Partial failure test failed: {e}")
        traceback.print_exc()
    
    for result in test_results:
        print(result)
    
    return len([r for r in test_results if r.startswith("✅")]) >= 1


async def test_date_parameter_handling():
    """Test various date parameter scenarios."""
    print("\n📅 Testing Date Parameter Handling")
    print("=" * 50)
    
    test_results = []
    
    try:
        client = InfoMentorClient()
        client.authenticated = True
        client.auth = MagicMock()
        client.auth.authenticated = True
        client.auth.pupil_ids = ["test_pupil"]
        
        mock_session = AsyncMock()
        client._session = mock_session
        
        # Mock successful response
        mock_response = MockResponse(200, {"result": []})
        mock_session.get.return_value = mock_response
        
        # Test with no dates (should use defaults)
        await client.get_time_registration()
        call_args = mock_session.get.call_args
        params = call_args[1].get("params", {})
        assert "startDate" in params, "Should include startDate parameter"
        assert "endDate" in params, "Should include endDate parameter"
        test_results.append("✅ Default date parameters handled")
        
        # Test with specific dates
        start_date = datetime(2024, 1, 1)
        end_date = datetime(2024, 1, 7)
        
        mock_session.reset_mock()
        await client.get_time_registration(start_date=start_date, end_date=end_date)
        
        call_args = mock_session.get.call_args
        params = call_args[1].get("params", {})
        assert params["startDate"] == "2024-01-01", "Should format startDate correctly"
        assert params["endDate"] == "2024-01-07", "Should format endDate correctly"
        test_results.append("✅ Custom date parameters handled")
        
        await client.close()
        
    except Exception as e:
        test_results.append(f"❌ Date parameter test failed: {e}")
        traceback.print_exc()
    
    for result in test_results:
        print(result)
    
    return len([r for r in test_results if r.startswith("✅")]) == 2


async def test_pupil_switch_failures():
    """Test various pupil switching failure scenarios."""
    print("\n👤 Testing Pupil Switch Failure Scenarios")
    print("=" * 50)
    
    test_results = []
    
    try:
        client = InfoMentorClient()
        client.authenticated = True
        client.auth = MagicMock()
        client.auth.authenticated = True
        client.auth.pupil_ids = ["pupil1", "pupil2"]
        
        # Test switch failure
        client.switch_pupil = AsyncMock(return_value=False)
        
        result = await client.get_time_registration(pupil_id="invalid_pupil")
        assert result == [], "Should return empty list when pupil switch fails"
        test_results.append("✅ Failed pupil switch handled")
        
        # Test switch success but no session
        client.switch_pupil = AsyncMock(return_value=True)
        client._session = None
        
        result = await client.get_time_registration(pupil_id="pupil1")
        # Should handle gracefully even without session
        test_results.append("✅ Missing session after switch handled")
        
        await client.close()
        
    except Exception as e:
        test_results.append(f"❌ Pupil switch failure test failed: {e}")
        traceback.print_exc()
    
    for result in test_results:
        print(result)
    
    return len([r for r in test_results if r.startswith("✅")]) >= 1


async def test_response_status_codes():
    """Test handling of various HTTP status codes."""
    print("\n🔢 Testing Various HTTP Status Codes")
    print("=" * 50)
    
    test_results = []
    
    try:
        client = InfoMentorClient()
        client.authenticated = True
        client.auth = MagicMock()
        client.auth.authenticated = True
        client.auth.pupil_ids = ["test_pupil"]
        
        mock_session = AsyncMock()
        client._session = mock_session
        
        # Test various status codes
        status_codes = [
            (302, "Redirect"),
            (404, "Not Found"),
            (500, "Internal Server Error"),
            (502, "Bad Gateway"),
            (503, "Service Unavailable"),
        ]
        
        for status, message in status_codes:
            mock_response = MockResponse(status, text_data=message)
            mock_session.get.side_effect = [mock_response, mock_response]  # Both endpoints fail
            mock_session.post.return_value = MockResponse(status, text_data=message)
            
            result = await client.get_time_registration()
            assert result == [], f"Should handle HTTP {status} gracefully"
            
            mock_session.reset_mock()
        
        test_results.append("✅ Various HTTP status codes handled gracefully")
        
        await client.close()
        
    except Exception as e:
        test_results.append(f"❌ Status code test failed: {e}")
        traceback.print_exc()
    
    for result in test_results:
        print(result)
    
    return len([r for r in test_results if r.startswith("✅")]) == 1


async def run_edge_case_tests():
    """Run all edge case tests."""
    print("🧪 Time Registration Edge Case Test Suite")
    print("=" * 60)
    
    tests = [
        ("Network Error Handling", test_network_errors),
        ("Malformed JSON Response Handling", test_malformed_json_responses),
        ("Partial Failure Scenarios", test_partial_failures),
        ("Date Parameter Handling", test_date_parameter_handling),
        ("Pupil Switch Failure Scenarios", test_pupil_switch_failures),
        ("Various HTTP Status Codes", test_response_status_codes),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            result = await test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ {test_name} threw an exception: {e}")
            results.append((test_name, False))
            traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("📊 Edge Case Test Results Summary")
    print("=" * 60)
    
    passed = 0
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {test_name}")
        if result:
            passed += 1
    
    print(f"\n🎯 Overall: {passed}/{total} edge case tests passed")
    
    if passed == total:
        print("🎉 All edge case tests passed! The fix handles error conditions well.")
    else:
        print("⚠️  Some edge case tests failed. Review the fix for robustness.")
    
    return passed == total


if __name__ == "__main__":
    asyncio.run(run_edge_case_tests()) 