# Pupil Switching Fix Required

## Issue Discovered

The InfoMentor integration is **NOT correctly switching between pupils**. Both pupils are showing the same schedule data because the switching mechanism is broken.

### Root Cause

The `switch_pupil` method in `auth.py` is using the **pupil ID** directly in the switch URL:
```python
modern_switch_url = f"{MODERN_BASE_URL}/Account/PupilSwitcher/SwitchPupil/{pupil_id}"
```

However, InfoMentor requires a different **switch ID** for the URL:
- Olle (pupil ID: 1000000001) → Switch ID: **2000001**
- Alva (pupil ID: 1000000002) → Switch ID: **2000002**

### Evidence

From the debug output:
```
✅ Found switch URLs (from JSON):
   - Svensson, Alva: SwitchPupil/2000002
   - Svensson, Olle: SwitchPupil/2000001
```

But when retrieving data, both pupils show identical schedules (8:00-16:00), which is actually Alva's schedule. Olle should have different times (12:00-16:00/17:00) plus Thursday.

### Required Fix

The `InfoMentorAuth` class needs to:

1. **Store a mapping** between pupil IDs and switch IDs:
   ```python
   self.pupil_ids: list[str] = []
   self.pupil_switch_ids: dict[str, str] = {}  # pupil_id -> switch_id
   ```

2. **Extract both IDs** when parsing pupil data in `_extract_pupil_ids_from_json`:
   ```python
   # When finding switch patterns:
   switch_pattern = r'"switchPupilUrl"\s*:\s*"[^"]*SwitchPupil/(\d+)"[^}]*"hybridMappingId"\s*:\s*"[^|]*\|(\d+)\|'
   # This captures both switch_id and pupil_id
   ```

3. **Use the correct switch ID** in `switch_pupil`:
   ```python
   async def switch_pupil(self, pupil_id: str) -> bool:
       if pupil_id not in self.pupil_ids:
           raise InfoMentorAuthError(f"Invalid pupil ID: {pupil_id}")
       
       # Use the switch ID, not the pupil ID
       switch_id = self.pupil_switch_ids.get(pupil_id, pupil_id)  # fallback to pupil_id if no mapping
       
       modern_switch_url = f"{MODERN_BASE_URL}/Account/PupilSwitcher/SwitchPupil/{switch_id}"
   ```

### Impact

Without this fix:
- ❌ All pupils show the same schedule (first pupil's data)
- ❌ Cannot retrieve individual pupil's timetable or time registration
- ❌ Home Assistant will display incorrect data

With this fix:
- ✅ Each pupil will show their correct individual schedule
- ✅ Olle will show school timetable + fritids schedule  
- ✅ Alva will show her 8-16 schedule
- ✅ Home Assistant will display accurate data for each child

### Testing

After implementing the fix, we should see:
- Olle: 12:00-16:00/17:00 fritids + Thursday + timetable entries
- Alva: 8:00-16:00 Mon-Thu

This is a **CRITICAL** fix that must be implemented before the integration can work correctly in Home Assistant. 