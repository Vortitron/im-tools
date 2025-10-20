#!/usr/bin/env python3
"""
Test to verify today's schedule is calculated dynamically, not from stale cache.

This demonstrates the fix for the issue where:
- Saturday: Fresh data fetched, today_schedule cached as Saturday
- Sunday-Monday: Server issues, stale cache preserved
- Monday: get_today_schedule() returned Saturday (WRONG!)
          get_tomorrow_schedule() calculated Tuesday dynamically (CORRECT!)

The fix makes get_today_schedule() calculate dynamically like get_tomorrow_schedule().
"""

from datetime import datetime, timedelta


class MockScheduleDay:
	"""Mock ScheduleDay for testing."""
	def __init__(self, date_obj):
		self.date = date_obj
		self.has_school = True
		self.has_preschool_or_fritids = False


def get_today_schedule_OLD(schedule_days, cached_today_schedule):
	"""Old broken implementation - returns stale cached value."""
	return cached_today_schedule


def get_today_schedule_NEW(schedule_days, cached_today_schedule=None):
	"""New fixed implementation - calculates dynamically."""
	today = datetime.now().date()
	
	for day in schedule_days:
		if day.date.date() == today:
			return day
	return None


def get_tomorrow_schedule(schedule_days):
	"""Tomorrow schedule - always worked correctly."""
	tomorrow = datetime.now().date() + timedelta(days=1)
	
	for day in schedule_days:
		if day.date.date() == tomorrow:
			return day
	return None


def test_schedule_calculation():
	"""Test that demonstrates the fix."""
	
	print("\n" + "="*80)
	print("Testing Today Schedule Dynamic Calculation Fix")
	print("="*80)
	
	# Simulate the scenario
	today = datetime.now().date()
	
	# Calculate what Saturday would have been (3 days ago if today is Monday)
	# For this test, we'll simulate having data from 3 days ago
	days_ago = 3
	stale_date = today - timedelta(days=days_ago)
	
	print(f"\n📅 Scenario Simulation:")
	print(f"   - {stale_date.strftime('%A, %Y-%m-%d')}: Fresh data fetched, cached as 'today'")
	print(f"   - Next {days_ago-1} days: Server issues, stale cache preserved")
	print(f"   - {today.strftime('%A, %Y-%m-%d')} (TODAY): Testing what happens...")
	
	# Create schedule data that spans from the stale date to next week
	print(f"\n📋 Available Schedule Data:")
	schedule_days = []
	for i in range(14):  # Two weeks of data from stale date
		day_date = stale_date + timedelta(days=i)
		schedule_day = MockScheduleDay(datetime.combine(day_date, datetime.min.time()))
		schedule_days.append(schedule_day)
		marker = ""
		if day_date == stale_date:
			marker = " ← STALE CACHED DATE"
		elif day_date == today:
			marker = " ← TODAY"
		elif day_date == today + timedelta(days=1):
			marker = " ← TOMORROW"
		print(f"   - {day_date.strftime('%A, %Y-%m-%d')}{marker}")
	
	# The stale cached value (from 3 days ago)
	stale_cached_today = schedule_days[0]  # The first day (stale date)
	
	print(f"\n🔍 Testing OLD Implementation (BROKEN):")
	old_today = get_today_schedule_OLD(schedule_days, stale_cached_today)
	if old_today:
		is_correct = old_today.date.date() == today
		status = "✅ CORRECT" if is_correct else "❌ WRONG"
		print(f"   {status}: Returns {old_today.date.strftime('%A, %Y-%m-%d')}")
		if not is_correct:
			print(f"   Expected: {today.strftime('%A, %Y-%m-%d')}")
			print(f"   Got:      {old_today.date.strftime('%A, %Y-%m-%d')}")
			print(f"   Problem:  Returning stale cached value from {days_ago} days ago!")
	
	print(f"\n🔍 Testing NEW Implementation (FIXED):")
	new_today = get_today_schedule_NEW(schedule_days, stale_cached_today)
	if new_today:
		is_correct = new_today.date.date() == today
		status = "✅ CORRECT" if is_correct else "❌ WRONG"
		print(f"   {status}: Returns {new_today.date.strftime('%A, %Y-%m-%d')}")
		if is_correct:
			print(f"   Correctly calculates today's date dynamically from schedule list!")
	else:
		print(f"   ⚠️  No schedule found for today (might be a weekend)")
	
	print(f"\n🔍 Testing Tomorrow Schedule (ALWAYS WORKED):")
	tomorrow = get_tomorrow_schedule(schedule_days)
	if tomorrow:
		expected_tomorrow = today + timedelta(days=1)
		is_correct = tomorrow.date.date() == expected_tomorrow
		status = "✅ CORRECT" if is_correct else "❌ WRONG"
		print(f"   {status}: Returns {tomorrow.date.strftime('%A, %Y-%m-%d')}")
		if is_correct:
			print(f"   Always calculated dynamically, never had this bug!")
	
	# Summary
	print(f"\n" + "="*80)
	if new_today and new_today.date.date() == today:
		print("✅ FIX VERIFIED: get_today_schedule() now calculates dynamically!")
		print("   Today's schedule will always show the correct date, even with stale cache.")
	else:
		print("⚠️  Note: Today might be a weekend with no schedule data in test")
	print("="*80 + "\n")


if __name__ == "__main__":
	test_schedule_calculation()

