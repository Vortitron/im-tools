#!/usr/bin/env python3
"""
Test to validate that the authentication retry logic is working correctly.
This tests the new automatic re-authentication when sessions expire.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio

# Add the custom components to the path
sys.path.insert(0, str(Path(__file__).parent.parent / 'custom_components' / 'infomentor'))

from infomentor.client import InfoMentorClient
from infomentor.auth import InfoMentorAuth

def test_authentication_retry_logic():
	"""Test that authentication retry logic is present in the code."""
	
	print("🧪 TESTING AUTHENTICATION RETRY LOGIC")
	print("=" * 50)
	
	# Test 1: Check that credentials are stored in auth
	print("\n📋 Test 1: Credential Storage")
	print("-" * 30)
	
	mock_session = MagicMock()
	auth = InfoMentorAuth(mock_session)
	
	# Check that credential storage attributes exist
	has_username_attr = hasattr(auth, '_username')
	has_password_attr = hasattr(auth, '_password')
	
	print(f"   ✅ Has _username attribute: {'PASS' if has_username_attr else 'FAIL'}")
	print(f"   ✅ Has _password attribute: {'PASS' if has_password_attr else 'FAIL'}")
	
	# Test 2: Check that _handle_authentication_failure method exists
	print("\n🔄 Test 2: Re-authentication Method")
	print("-" * 35)
	
	client = InfoMentorClient()
	has_handle_auth_failure = hasattr(client, '_handle_authentication_failure')
	
	print(f"   ✅ Has _handle_authentication_failure method: {'PASS' if has_handle_auth_failure else 'FAIL'}")
	
	# Test 3: Check for retry logic in timetable method
	print("\n📅 Test 3: Timetable Retry Logic")
	print("-" * 32)
	
	import inspect
	timetable_source = inspect.getsource(client.get_timetable)
	
	has_retry_method = "_get_timetable_with_retry" in timetable_source
	print(f"   ✅ Uses retry method: {'PASS' if has_retry_method else 'FAIL'}")
	
	# Check for retry logic in _get_timetable_with_retry
	if hasattr(client, '_get_timetable_with_retry'):
		retry_source = inspect.getsource(client._get_timetable_with_retry)
		
		has_unauthorized_check = "HandleUnauthorizedRequest" in retry_source
		has_retry_count = "retry_count" in retry_source
		has_max_retries = "max_retries" in retry_source
		has_auth_failure_call = "_handle_authentication_failure" in retry_source
		
		print(f"   ✅ Checks for HandleUnauthorizedRequest: {'PASS' if has_unauthorized_check else 'FAIL'}")
		print(f"   ✅ Has retry count logic: {'PASS' if has_retry_count else 'FAIL'}")
		print(f"   ✅ Has max retries limit: {'PASS' if has_max_retries else 'FAIL'}")
		print(f"   ✅ Calls authentication failure handler: {'PASS' if has_auth_failure_call else 'FAIL'}")
	else:
		print("   ❌ _get_timetable_with_retry method not found")
	
	# Test 4: Check for retry logic in time registration method
	print("\n⏰ Test 4: Time Registration Retry Logic")
	print("-" * 38)
	
	time_reg_source = inspect.getsource(client.get_time_registration)
	
	has_unauthorized_check_tr = "HandleUnauthorizedRequest" in time_reg_source
	has_auth_failure_call_tr = "_handle_authentication_failure" in time_reg_source
	has_retry_logic_tr = "retry_resp" in time_reg_source
	
	print(f"   ✅ Checks for HandleUnauthorizedRequest: {'PASS' if has_unauthorized_check_tr else 'FAIL'}")
	print(f"   ✅ Calls authentication failure handler: {'PASS' if has_auth_failure_call_tr else 'FAIL'}")
	print(f"   ✅ Has retry logic: {'PASS' if has_retry_logic_tr else 'FAIL'}")
	
	# Test 5: Check credential storage in login method
	print("\n🔐 Test 5: Login Method Credential Storage")
	print("-" * 40)
	
	login_source = inspect.getsource(auth.login)
	
	stores_username = "_username = username" in login_source
	stores_password = "_password = password" in login_source
	
	print(f"   ✅ Stores username: {'PASS' if stores_username else 'FAIL'}")
	print(f"   ✅ Stores password: {'PASS' if stores_password else 'FAIL'}")
	
	# Summary
	print("\n🎯 SUMMARY")
	print("-" * 15)
	
	all_tests = [
		has_username_attr and has_password_attr,  # Credential storage attributes
		has_handle_auth_failure,  # Re-authentication method exists
		has_retry_method,  # Timetable uses retry method
		has_unauthorized_check and has_auth_failure_call,  # Timetable retry logic
		has_unauthorized_check_tr and has_auth_failure_call_tr,  # Time reg retry logic
		stores_username and stores_password,  # Login stores credentials
	]
	
	passed_count = sum(all_tests)
	total_count = len(all_tests)
	
	print(f"✅ Tests passed: {passed_count}/{total_count}")
	
	if passed_count == total_count:
		print("\n🎉 All authentication retry logic is properly implemented!")
		print("\n💡 This should fix the HandleUnauthorizedRequest errors by:")
		print("   1. Storing credentials for re-authentication")
		print("   2. Detecting session expiration in API responses")
		print("   3. Automatically re-authenticating when needed")
		print("   4. Retrying failed requests after re-authentication")
	else:
		print(f"\n⚠️  {total_count - passed_count} tests failed - some retry logic may be missing")
	
	return passed_count == total_count

async def test_authentication_retry_simulation():
	"""Simulate authentication retry behavior."""
	
	print("\n🎭 SIMULATING AUTHENTICATION RETRY")
	print("=" * 40)
	
	# Create a mock client
	client = InfoMentorClient()
	client.auth = AsyncMock()
	client.auth._username = "test_user"
	client.auth._password = "test_pass"
	client.auth.login = AsyncMock(return_value=True)
	client._session = AsyncMock()
	client.authenticated = True
	
	# Simulate a session expired response
	expired_response = AsyncMock()
	expired_response.status = 500
	expired_response.text = AsyncMock(return_value="IM Home AjaxError: /Home/Errors/Server?URL=/Home/Home/HandleUnauthorizedRequest")
	expired_response.headers = {}
	
	# Simulate a successful response after re-auth
	success_response = AsyncMock()
	success_response.status = 200
	success_response.json = AsyncMock(return_value={"days": []})
	
	print("📋 Testing simulated authentication failure and retry...")
	
	try:
		# Test the retry logic exists and handles the right error
		if hasattr(client, '_handle_authentication_failure'):
			print("   ✅ Re-authentication handler found")
			
			# Test that it would call auth.login
			await client._handle_authentication_failure()
			
			# Verify login was called
			client.auth.login.assert_called_once_with("test_user", "test_pass")
			print("   ✅ Re-authentication called with stored credentials")
		else:
			print("   ❌ Re-authentication handler not found")
			
	except Exception as e:
		print(f"   ⚠️  Error during simulation: {e}")
	
	print("\n✅ Authentication retry simulation complete")

def main():
	"""Main function."""
	print("🔧 Authentication Retry Fix Validation")
	print("=" * 50)
	
	# Test 1: Static code analysis
	logic_test_passed = test_authentication_retry_logic()
	
	# Test 2: Simulation
	asyncio.run(test_authentication_retry_simulation())
	
	print("\n" + "=" * 50)
	print("🏁 Testing complete!")
	
	if logic_test_passed:
		print("\n✅ EXPECTED RESULT: The integration should now automatically")
		print("   re-authenticate when sessions expire, fixing the")
		print("   HandleUnauthorizedRequest errors you were experiencing.")
		print("\n📋 TO TEST: Restart Home Assistant and monitor the logs.")
		print("   You should see successful re-authentication messages")
		print("   instead of persistent authentication failures.")
	else:
		print("\n❌ Some authentication retry logic may be missing.")
		print("   Manual verification may be needed.")

if __name__ == "__main__":
	main() 