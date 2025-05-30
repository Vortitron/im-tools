#!/usr/bin/env python3
"""
Test runner for InfoMentor integration tests.
Organises test execution and captures output to debug_output directory.
"""

import os
import sys
import subprocess
import datetime
from pathlib import Path

# Ensure we can import from the project root
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Test categories and their scripts
TEST_CATEGORIES = {
	'authentication': [
		'test_auth_debug.py',
		'test_modern_auth.py',
		'test_complete_oauth_credentials.py',
	],
	'api': [
		'test_api_parsing.py',
		'test_infomentor.py',
		'test_infomentor_complete.py',
		'test_kids_info.py',
		'quick_api_test.py',
	],
	'debug': [
		'debug_auth_flow.py',
		'debug_infomentor.py',
		'debug_pupil_names.py',
		'debug_session_expired.py',
		'trace_oauth_flow.py',
	],
	'utilities': [
		'check_error_page.py',
		'debug_html_capture.py',
	]
}

def ensure_debug_output_dir():
	"""Ensure debug_output directory exists."""
	debug_dir = Path('debug_output')
	debug_dir.mkdir(exist_ok=True)
	return debug_dir

def run_test(test_script, category, debug_dir):
	"""Run a single test script and capture its output."""
	test_path = Path('tests') / test_script
	
	if not test_path.exists():
		print(f"❌ Test not found: {test_path}")
		return False
	
	print(f"🔄 Running {category}/{test_script}...")
	
	# Create output file for this test
	timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
	output_file = debug_dir / f"{category}_{test_script.replace('.py', '')}_{timestamp}.log"
	
	try:
		# Run the test and capture output
		result = subprocess.run(
			[sys.executable, str(test_path)],
			capture_output=True,
			text=True,
			timeout=300  # 5 minute timeout
		)
		
		# Write output to log file
		with open(output_file, 'w') as f:
			f.write(f"Test: {test_script}\n")
			f.write(f"Category: {category}\n")
			f.write(f"Timestamp: {timestamp}\n")
			f.write(f"Return code: {result.returncode}\n")
			f.write("=" * 50 + "\n")
			f.write("STDOUT:\n")
			f.write(result.stdout)
			f.write("\n" + "=" * 50 + "\n")
			f.write("STDERR:\n")
			f.write(result.stderr)
		
		if result.returncode == 0:
			print(f"✅ {test_script} completed successfully")
			return True
		else:
			print(f"❌ {test_script} failed (exit code: {result.returncode})")
			return False
			
	except subprocess.TimeoutExpired:
		print(f"⏰ {test_script} timed out")
		return False
	except Exception as e:
		print(f"💥 Error running {test_script}: {e}")
		return False

def main():
	"""Main test runner function."""
	print("🧪 InfoMentor Integration Test Runner")
	print("=" * 40)
	
	# Ensure debug output directory exists
	debug_dir = ensure_debug_output_dir()
	print(f"📁 Debug output will be saved to: {debug_dir}")
	
	# Check if .env file exists
	if not Path('.env').exists():
		print("⚠️  Warning: .env file not found. Some tests may fail.")
		print("   Create .env file with IM_USERNAME and IM_PASSWORD")
	
	total_tests = 0
	passed_tests = 0
	
	# Run tests by category
	for category, tests in TEST_CATEGORIES.items():
		print(f"\n📂 Category: {category}")
		print("-" * 30)
		
		for test_script in tests:
			total_tests += 1
			if run_test(test_script, category, debug_dir):
				passed_tests += 1
	
	# Summary
	print("\n" + "=" * 40)
	print(f"📊 Test Summary:")
	print(f"   Total tests: {total_tests}")
	print(f"   Passed: {passed_tests}")
	print(f"   Failed: {total_tests - passed_tests}")
	print(f"   Success rate: {passed_tests/total_tests*100:.1f}%")
	
	if passed_tests == total_tests:
		print("🎉 All tests passed!")
		return 0
	else:
		print("⚠️  Some tests failed. Check debug output for details.")
		return 1

if __name__ == '__main__':
	sys.exit(main()) 