#!/usr/bin/env python3
"""
Test runner for all time registration fix tests.
Runs the comprehensive test suite and provides a summary.
"""

import asyncio
import subprocess
import sys
from pathlib import Path
import time

def run_test_file(test_file):
    """Run a single test file and capture results."""
    print(f"\n{'='*60}")
    print(f"🧪 Running {test_file}")
    print(f"{'='*60}")
    
    start_time = time.time()
    
    try:
        # Run the test file
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent / test_file)],
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )
        
        end_time = time.time()
        duration = end_time - start_time
        
        print(result.stdout)
        
        if result.stderr:
            print("STDERR:")
            print(result.stderr)
        
        success = result.returncode == 0
        if success:
            print(f"✅ {test_file} completed successfully in {duration:.2f}s")
        else:
            print(f"❌ {test_file} failed with return code {result.returncode} in {duration:.2f}s")
        
        return success, duration, result.stdout, result.stderr
        
    except subprocess.TimeoutExpired:
        print(f"⏰ {test_file} timed out after 5 minutes")
        return False, 300, "", "Test timed out"
    except Exception as e:
        print(f"💥 {test_file} crashed: {e}")
        return False, 0, "", str(e)


async def main():
    """Run all time registration fix tests."""
    print("🚀 Time Registration Fix Test Suite Runner")
    print("=" * 60)
    print("This will run all tests to validate the time registration fix:")
    print("1. Basic functionality tests")
    print("2. Edge case and error handling tests")
    print("3. Real authentication test (if credentials available)")
    print("=" * 60)
    
    # List of test files to run
    test_files = [
        "test_time_registration_fix_focused.py",  # Main validation test
        "test_time_registration_fix_simple.py",   # Detailed mock tests (may have issues)
        "test_time_registration_edge_cases.py",   # Edge case tests (may have issues)
    ]
    
    results = []
    total_duration = 0
    overall_start = time.time()
    
    for test_file in test_files:
        test_path = Path(__file__).parent / test_file
        if test_path.exists():
            success, duration, stdout, stderr = run_test_file(test_file)
            results.append((test_file, success, duration, stdout, stderr))
            total_duration += duration
        else:
            print(f"⚠️  Test file {test_file} not found, skipping...")
            results.append((test_file, False, 0, "", "File not found"))
    
    overall_duration = time.time() - overall_start
    
    # Print summary
    print("\n" + "=" * 60)
    print("📊 FINAL TEST RESULTS SUMMARY")
    print("=" * 60)
    
    passed = 0
    total = len(results)
    
    for test_file, success, duration, stdout, stderr in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} - {test_file:<40} ({duration:.2f}s)")
        if success:
            passed += 1
    
    print(f"\n🎯 Overall Results: {passed}/{total} test files passed")
    print(f"⏱️  Total execution time: {overall_duration:.2f}s")
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED!")
        print("✅ The time registration fix appears to be working correctly.")
        print("✅ All error handling scenarios are properly managed.")
        print("✅ Ready for deployment to Home Assistant!")
    else:
        print(f"\n⚠️  {total - passed} test file(s) failed.")
        print("❌ Please review the test output above for details.")
        print("❌ Consider fixing issues before deploying to Home Assistant.")
    
    # Print key features tested
    print("\n📋 Key Features Tested:")
    print("▪️  GET-first approach for time registration endpoints")
    print("▪️  POST fallback mechanism for 'Invalid Verb' errors")
    print("▪️  Enhanced authentication validation")
    print("▪️  Proper handling of HTTP 401/403 authentication errors")
    print("▪️  Fallback to GetCalendarData endpoint when GetTimeRegistrations fails")
    print("▪️  Pupil switching integration")
    print("▪️  Network error and timeout handling")
    print("▪️  Malformed JSON response handling")
    print("▪️  Various HTTP status code scenarios")
    print("▪️  Date parameter formatting and validation")
    
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1) 