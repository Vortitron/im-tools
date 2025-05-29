#!/usr/bin/env python3
"""
Test script for parsing InfoMentor API responses

This script tests the parsing logic for the JSON data we captured
from the InfoMentor APIs.
"""

import json
import sys
from datetime import datetime, time
from pathlib import Path
from typing import List, Dict, Any, Optional

# Add the custom_components directory to Python path
sys.path.insert(0, str(Path(__file__).parent / "custom_components" / "infomentor"))

try:
	from infomentor.models import TimetableEntry, TimeRegistrationEntry
except ImportError as e:
	print(f"❌ Import error: {e}")
	print("Make sure you're running this script from the repository root directory.")
	sys.exit(1)


def load_json_file(filename: str) -> Optional[Dict[str, Any]]:
	"""Load JSON data from a file."""
	file_path = Path("debug_output") / filename
	if not file_path.exists():
		print(f"⚠️ File not found: {file_path}")
		return None
	
	try:
		with open(file_path, 'r', encoding='utf-8') as f:
			return json.load(f)
	except Exception as e:
		print(f"❌ Error loading {filename}: {e}")
		return None


def parse_calendar_entries(data: Dict[str, Any], pupil_id: str) -> List[TimetableEntry]:
	"""Parse calendar entries data into timetable entries."""
	timetable_entries = []
	
	if not isinstance(data, dict):
		print("⚠️ Calendar data is not a dictionary")
		return timetable_entries
	
	print(f"📊 Calendar data structure: {list(data.keys())}")
	
	# Look for entries in various possible keys
	entries = []
	for key in ['entries', 'events', 'items', 'data', 'calendarEntries']:
		if key in data:
			entries = data[key]
			print(f"✅ Found entries in '{key}': {len(entries) if isinstance(entries, list) else 'not a list'}")
			break
	
	if not entries:
		print("⚠️ No entries found in calendar data")
		return timetable_entries
	
	for entry in entries:
		try:
			# Extract common fields
			entry_id = str(entry.get('id', ''))
			title = entry.get('title', entry.get('name', ''))
			description = entry.get('description', entry.get('content', ''))
			
			# Parse date/time information
			start_date = parse_date_time(entry.get('startDate', entry.get('start', entry.get('date'))))
			end_date = parse_date_time(entry.get('endDate', entry.get('end')))
			start_time = parse_time_only(entry.get('startTime', entry.get('start')))
			end_time = parse_time_only(entry.get('endTime', entry.get('end')))
			
			# Extract additional fields
			subject = entry.get('subject', entry.get('course', ''))
			teacher = entry.get('teacher', entry.get('instructor', ''))
			room = entry.get('room', entry.get('location', ''))
			entry_type = entry.get('type', entry.get('entryType', 'unknown'))
			
			# Create timetable entry
			timetable_entry = TimetableEntry(
				id=entry_id,
				title=title,
				description=description,
				date=start_date or datetime.now(),
				start_time=start_time,
				end_time=end_time,
				subject=subject,
				teacher=teacher,
				room=room,
				entry_type=entry_type,
				pupil_id=pupil_id
			)
			
			timetable_entries.append(timetable_entry)
			print(f"✅ Parsed entry: {title} on {start_date}")
			
		except Exception as e:
			print(f"⚠️ Failed to parse entry: {e}")
			print(f"   Entry data: {entry}")
			continue
	
	return timetable_entries


def parse_time_registrations(data: Dict[str, Any], pupil_id: str) -> List[TimeRegistrationEntry]:
	"""Parse time registration data."""
	time_registrations = []
	
	if not isinstance(data, dict):
		print("⚠️ Time registration data is not a dictionary")
		return time_registrations
	
	print(f"📊 Time registration data structure: {list(data.keys())}")
	
	# Look for registrations in various possible keys
	registrations = []
	for key in ['registrations', 'timeRegistrations', 'entries', 'items', 'data']:
		if key in data:
			registrations = data[key]
			print(f"✅ Found registrations in '{key}': {len(registrations) if isinstance(registrations, list) else 'not a list'}")
			break
	
	if not registrations:
		print("⚠️ No registrations found in time registration data")
		return time_registrations
	
	for reg in registrations:
		try:
			# Extract common fields
			reg_id = str(reg.get('id', ''))
			date = parse_date_time(reg.get('date', reg.get('registrationDate')))
			start_time = parse_time_only(reg.get('startTime', reg.get('checkIn')))
			end_time = parse_time_only(reg.get('endTime', reg.get('checkOut')))
			
			# Extract additional fields
			status = reg.get('status', 'unknown')
			comment = reg.get('comment', reg.get('note', ''))
			is_locked = reg.get('isLocked', reg.get('locked', False))
			
			# Create time registration entry
			time_reg_entry = TimeRegistrationEntry(
				id=reg_id,
				date=date or datetime.now(),
				start_time=start_time,
				end_time=end_time,
				status=status,
				comment=comment,
				is_locked=is_locked,
				pupil_id=pupil_id
			)
			
			time_registrations.append(time_reg_entry)
			print(f"✅ Parsed registration: {date} {start_time}-{end_time}")
			
		except Exception as e:
			print(f"⚠️ Failed to parse registration: {e}")
			print(f"   Registration data: {reg}")
			continue
	
	return time_registrations


def parse_date_time(date_str: Optional[str]) -> Optional[datetime]:
	"""Parse date string into datetime object."""
	if not date_str:
		return None
	
	# Try various date formats
	date_formats = [
		"%Y-%m-%dT%H:%M:%S",
		"%Y-%m-%dT%H:%M:%SZ",
		"%Y-%m-%dT%H:%M:%S.%fZ",
		"%Y-%m-%d %H:%M:%S",
		"%Y-%m-%d",
		"%d/%m/%Y",
		"%d.%m.%Y",
		"%Y/%m/%d",
	]
	
	for fmt in date_formats:
		try:
			return datetime.strptime(date_str, fmt)
		except ValueError:
			continue
	
	print(f"⚠️ Failed to parse date: {date_str}")
	return None


def parse_time_only(time_str: Optional[str]) -> Optional[time]:
	"""Parse time string into time object."""
	if not time_str:
		return None
	
	# Try various time formats
	time_formats = [
		"%H:%M:%S",
		"%H:%M",
		"%H.%M",
	]
	
	for fmt in time_formats:
		try:
			parsed_time = datetime.strptime(time_str, fmt)
			return parsed_time.time()
		except ValueError:
			continue
	
	# Try to extract time from datetime string
	if 'T' in time_str:
		try:
			dt = parse_date_time(time_str)
			if dt:
				return dt.time()
		except:
			pass
	
	print(f"⚠️ Failed to parse time: {time_str}")
	return None


def main():
	"""Main test function."""
	print("InfoMentor API Parsing Test")
	print("=" * 40)
	
	# Test with captured JSON files
	debug_files = list(Path("debug_output").glob("*.json"))
	
	if not debug_files:
		print("❌ No JSON files found in debug_output directory")
		print("Run the debug_html_capture.py script first to capture API data")
		return
	
	print(f"📁 Found {len(debug_files)} JSON files:")
	for file in debug_files:
		print(f"   - {file.name}")
	
	# Test calendar entries parsing
	calendar_files = [f for f in debug_files if 'calendar' in f.name]
	for file in calendar_files:
		print(f"\n📅 Testing calendar parsing: {file.name}")
		data = load_json_file(file.name)
		if data:
			pupil_id = "test_pupil"
			entries = parse_calendar_entries(data, pupil_id)
			print(f"   📊 Parsed {len(entries)} timetable entries")
			
			for entry in entries[:3]:  # Show first 3 entries
				print(f"   📝 {entry.title} - {entry.date} {entry.start_time}-{entry.end_time}")
	
	# Test time registration parsing
	time_reg_files = [f for f in debug_files if 'time' in f.name and 'registration' in f.name]
	for file in time_reg_files:
		print(f"\n🕐 Testing time registration parsing: {file.name}")
		data = load_json_file(file.name)
		if data:
			pupil_id = "test_pupil"
			registrations = parse_time_registrations(data, pupil_id)
			print(f"   📊 Parsed {len(registrations)} time registration entries")
			
			for reg in registrations[:3]:  # Show first 3 registrations
				print(f"   📝 {reg.date} {reg.start_time}-{reg.end_time} ({reg.status})")
	
	print("\n✅ Parsing test complete!")


if __name__ == "__main__":
	main() 