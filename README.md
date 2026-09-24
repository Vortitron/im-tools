# InfoMentor Home Assistant Integration

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Vortitron&repository=im-tools&category=integration)

This custom component integrates InfoMentor school communication platform with Home Assistant, providing real-time access to school schedules, news, and timeline entries for your children.

## Features

### Core Functionality
- **Multiple Children Support**: Manage multiple pupils/children from one or more schools
- **Real-time Schedule Data**: Access current and upcoming school schedules
- **News & Timeline**: Get school news and timeline entries
- **Child Type Detection**: Automatically distinguish between school and preschool children
- **Robust Authentication**: Secure login with session management
- **Push Notifications**: Alternative to the broken InfoMentor Android push — sends new notices to your phone via HA

### Sensors Created

For each pupil, the integration creates several sensors:

#### Schedule Sensors
- **Dashboard**: Overview of all children's schedules for today and tomorrow
- **Today Schedule**: Current day's schedule status (school/preschool_fritids/no_activities)
- **Tomorrow Schedule**: Next day's schedule status and details
- **Schedule**: Complete upcoming schedule (7 days) with detailed breakdown
- **Needs Preparation Today**: Binary sensor indicating if child needs preparation (school OR preschool/fritids)
- **Has School Tomorrow**: Binary sensor indicating if child needs preparation tomorrow
- **Has Preschool Today**: Binary sensor for preschool/fritids activities today (kept for compatibility)
- **Child Type**: Determines if child is "school" or "preschool" based on timetable data

#### Communication Sensors
- **News**: Count and details of unread school news
- **Timeline**: Count and details of timeline entries

#### Notification Sensors
- **Notifications**: Unread notification count; attributes include the latest 20 notifications with title, date, type, pupil, URL, and state

#### System Sensors
- **Pupil Count**: Total number of children in the account
- **Data Freshness**: Now only marks data as fresh after every pupil receives a fully refreshed schedule and exposes which pupils are still missing or using cached schedules

### Schedule Properties Clarification

The integration uses different properties to accurately represent activities:

- **`has_school`**: Any scheduled activity (timetable entries OR time registrations)
- **`has_timetable_entries`**: Only actual school lessons from the timetable
- **`has_preschool_or_fritids`**: Time registrations for preschool/after-school care

### Child Type Detection Logic

The integration correctly distinguishes between school and preschool children:

1. **Primary**: Children with timetable entries → **School child**
2. **Fallback**: Children with "fritids" time registrations → **School child** 
3. **Fallback**: Children with "förskola" time registrations → **Preschool child**
4. **Default**: No clear indicators → **Preschool child**

This ensures accurate classification even when timetable data is temporarily unavailable.

## Installation

### Option 1: HACS (Recommended)
1. Install HACS if you haven't already
2. Add this repository as a custom repository in HACS
3. Install "InfoMentor" from HACS
4. Restart Home Assistant

### Option 2: Manual Installation
1. Download the latest release
2. Copy the `custom_components/infomentor` folder to your Home Assistant `custom_components` directory
3. Restart Home Assistant

## Configuration

### Initial Setup
1. Go to **Settings** → **Devices & Services**
2. Click **Add Integration** 
3. Search for "InfoMentor"
4. Enter your InfoMentor credentials
5. The integration will discover all your children automatically

### Important Notes
- **Credentials**: Use the same username/password you use for the InfoMentor website
- **Multiple Children**: All children associated with your account are automatically added
- **Updates**: Schedule, news and timeline data refresh every 12 hours (sooner while data is incomplete); notifications are polled every 5 minutes
- **Day rollover**: Today/tomorrow sensors switch over just after midnight (in Home Assistant's time zone) without waiting for the next refresh
- **Closed days and leave**: Days InfoMentor marks as school closed (e.g. studiedag) or on leave don't count as preschool/fritids attendance, even though InfoMentor keeps the planned times on them
- **Two-week window**: Timetable and time registrations are fetched through the end of next week, so "tomorrow" is correct on weekends too
- **Authentication**: Sessions are managed automatically with re-authentication as needed
- **Restart Resilience**: On Home Assistant restarts the integration shows cached data (up to 72 hours old) immediately, verifies credentials in the background and fetches fresh data when the cached data would normally be due. The login session is saved too, so a restart usually doesn't need a full InfoMentor login

### Updating Credentials and Testing Login

- You can update your InfoMentor username/password via the integration's Options (**Configure**). Leave the password empty to keep the current one.
- Changed credentials are validated against InfoMentor before saving; on success the integration reloads with them.
- If InfoMentor starts rejecting the stored password, Home Assistant shows a **Re-authenticate** prompt asking for the new one.

### Diagnostics (manual retry)

When the integration is stuck on hourly retries, notifications stay at `0 / 0`, or you see HTTP 500 / timetable HTML errors, use the device buttons or the service for an immediate attempt:

- **InfoMentor run diagnostics** (button): full re-login with your stored credentials, clears auth/notification backoff timers, then runs a normal coordinator refresh. Check the log for lines starting with `Diagnostics poke:`.
- **InfoMentor full refresh (clears schedule cache)** (button): same as above, plus clears the in-memory today/tomorrow schedule cache before refreshing (your logs will show `clear_cache=True`).
- **Service** (automations, Developer tools): `infomentor.diagnostic_poke` with optional `clear_cache: true` (defaults to `false`). Target your InfoMentor device or pass `config_entry_id`.

#### Viewing what the integration is doing (no SSH required)

If Home Assistant runs in a VM and you don't want to tail `home-assistant.log`, you have three UI‑only options:

- **InfoMentor Diagnostic Log** sensor — appears under the InfoMentor device. Its state shows the most recent event; open it in **Developer Tools → States** and you'll see the last ~50 events (`Session refresh OK`, `Hub warmup ok=true`, `Notification probe items=24`, etc.) as the `events` attribute.
- **Download diagnostics** — on **Settings → Devices & services → InfoMentor**, click the three‑dot menu on the device and choose "Download diagnostics". You get a JSON bundle with pupil IDs, cookie counts per domain, the diagnostic event ring buffer, and the current notification buffer (credentials are redacted).
- **Settings → System → Logs** — filter for `custom_components.infomentor` to see `WARNING`‑level lines including `Diagnostics poke: …`.

### Push Notifications (InfoMentor App Replacement)

The InfoMentor Android app has a known issue where it fails to register push notifications.  This integration provides a reliable alternative using Home Assistant's notification system.

#### Setup
1. Install the Home Assistant Companion app on the phone(s) and log in, so each phone has a `notify.mobile_app_<phone>` service.
2. Go to **Settings → Devices & Services → InfoMentor → Configure**.
3. Under "Send notifications to", pick the phones from the list (you can also type any other notify service name). Optionally tick "Also show them in Home Assistant's notification list". No password is needed to change these settings.
4. Press the **InfoMentor send test notification** button on the InfoMentor device. It pushes the most recent InfoMentor notification, marked "(Test)", so you can check it arrives and opens correctly.

Notifications are checked every 5 minutes, and only ones InfoMentor marks as new are pushed. The first check after installing only records the notifications that already exist (so you aren't flooded with old ones), and handled notification IDs are stored so nothing is pushed twice after a restart. If the notification endpoint keeps failing, polling backs off (up to every 2 hours) instead of logging in repeatedly.

#### What Gets Sent
InfoMentor's own notification text is generic ("Kommande kalenderhändelse"), so the integration looks up what it refers to:

| InfoMentor notification | Push title | Push message (example) |
|---|---|---|
| Calendar event (upcoming) | `Felix: Kommande kalenderhändelse` | `Läsläxa · fre 25 sep (heldag) — Läsläxan lämnas in idag …` |
| New calendar events | `Felix: Nya kalenderhändelser` | `v.39: Läsläxa, Studiedag, Idrott (+1)` |
| News | `Felix: Nyhet publicerad` | `Höstens utvecklingssamtal — Hej alla vårdnadshavare! …` |
| Learning log | `Isolde: Nytt inlägg i lärloggen` | `Skogen — Naturvetenskap och teknik` |

If a lookup fails, the push falls back to InfoMentor's own text and the date. Tapping the notification opens the page in InfoMentor's web app (you may need to log in to InfoMentor in the phone's browser once). On Android, pushes use a notification channel called **InfoMentor**, so you can give them their own sound or priority in the phone's notification settings.

#### Advanced: HA Event Automation
Every new notification also fires an `infomentor_new_notification` event (including `pupil_name`, `detail` and `url`), which you can use in automations:

```yaml
automation:
  - alias: "InfoMentor → custom push"
    trigger:
      - platform: event
        event_type: infomentor_new_notification
    action:
      - service: notify.mobile_app_my_phone
        data:
          title: "{{ trigger.event.data.title }}"
          message: "{{ trigger.event.data.pupil_name }}: {{ trigger.event.data.detail or trigger.event.data.sub_title }}"
          data:
            url: "{{ trigger.event.data.url }}"
            clickAction: "{{ trigger.event.data.url }}"
```

### Debugging Authentication

- When authentication fails, the integration logs a short, truncated snippet of the server response for visibility.
- For deeper inspection, full HTML responses are written to debug files without blocking Home Assistant:
  - /tmp/infomentor_debug_initial.html
  - /tmp/infomentor_debug_oauth.html
  - /tmp/infomentor_debug_dashboard.html
- These can help detect changes in InfoMentor's login process.
- Login form submission now parses and submits the exact form fields (including selects, checkboxes, and submit buttons) and refreshes the login page when fields are missing, improving resilience to portal changes.
- If the live form includes the embedded school list or encoded viewstate, those hidden fields are now merged into the payload and the login postback target is set explicitly.

### School Selection Heuristics

- The integration stores both the URL and name of the successful school/IdP choice, reusing it automatically on future logins.
- We also mirror the browser cookie (`Im1_Ck_LastUsedIdp`) that InfoMentor uses, so new sessions immediately jump to the correct municipality instead of falling back to the first entry in the list.
- When no cached choice exists, it scores every option, prioritising InfoMentor-operated endpoints, entries containing "elever", and options matching the domain of your username or e-mail address.
- Options that do not match any clues are penalised, preventing the workflow from choosing the first municipality in the list (e.g. Avesta) by mistake.
- These heuristics eliminate the previous behaviour where the integration consistently picked the first entry instead of the correct school.

### Manual Authentication Retry

When InfoMentor servers are unreliable and authentication fails, you can manually retry:

**Service**: `infomentor.retry_authentication`
- **clear_cache** (optional): Set to `true` to clear cached data and force fresh authentication
- **Example**: Call this service when you see authentication failures in the logs

This service resets authentication failure tracking and attempts immediate re-authentication, useful when InfoMentor servers are temporarily unstable.

### Session Reuse & Stale Data Retries

- **Cookie reuse**: The integration now persists the InfoMentor session cookies to Home Assistant storage. On restart (or after temporary network hiccups) we attempt to restore the previous session before running the full OAuth dance, so successful logins stay alive much longer.
- **Stale data handling**: When the last successful data pull is older than 24 hours we automatically move into an hourly retry cadence with a randomly offset start time (between +3 and +17 minutes past the hour). This avoids colliding with InfoMentor’s on-the-hour maintenance jobs and keeps trying until fresh data arrives.

### Manual Actions (Developer Tools → Actions)

All InfoMentor services now expose a `target` selector, so you can choose the specific InfoMentor device (account) when running an action from the Developer Tools UI or automations. When no target is provided the action runs for every configured account.

| Action | What it does | Notes |
| --- | --- | --- |
| `infomentor.refresh_data` | Runs the standard coordinator refresh or a single-pupil refresh when `pupil_id` is provided. | Respects retry/backoff logic and logs a clear success/failure message. |
| `infomentor.force_refresh` | Forces an immediate update, optionally clearing cached data first. | Useful when HA cached data has gone stale. |
| `infomentor.switch_pupil` | Calls the InfoMentor API to switch context to a specific pupil. | Requires an active session; action warns if the client is not initialised yet. |
| `infomentor.debug_authentication` | Runs the extended OAuth/pupil extraction diagnostics and logs the resulting payload. | Results are logged at `INFO` level for quick copy/paste in bug reports. |
| `infomentor.cleanup_duplicate_entities` | Removes duplicate entities, with optional `dry_run` and `aggressive_cleanup` flags. | Dry-run mode now reports exactly which entities would be removed. |
| `infomentor.retry_authentication` | Clears auth backoff counters and re-establishes the client (optionally clearing cached data). | Handy after password changes or school-side fixes. |

Advanced automations can also pass `config_entry_id` in the service data to scope an action programmatically (for example, when you store the entry id in an input text). This mirrors the device selector but keeps YAML automations tidy.

## Usage Examples

### Automations
```yaml
# Notify when child needs preparation today
- alias: "School Day Notification"
  trigger:
    - platform: state
      entity_id: binary_sensor.felix_needs_preparation_today
      to: "on"
  action:
    - service: notify.mobile_app
      data:
        message: "Felix needs preparation today!"

# Different actions for school vs preschool
- alias: "Morning Routine"
  trigger:
    - platform: time
      at: "07:00:00"
  condition:
    - condition: state
      entity_id: binary_sensor.felix_needs_preparation_today
      state: "on"
  action:
    - choose:
        - conditions:
            - condition: state
              entity_id: sensor.felix_child_type
              state: "school"
          sequence:
            - service: tts.speak
              data:
                message: "Time to get ready for school!"
        - conditions:
            - condition: state
              entity_id: sensor.felix_child_type
              state: "preschool"
          sequence:
            - service: tts.speak
              data:
                message: "Time to get ready for preschool!"

# Dashboard-based automation for all kids
- alias: "Any Child Needs Preparation Tomorrow"
  trigger:
    - platform: template
      value_template: >
        {% set kids = state_attr('sensor.infomentor_dashboard', 'kids') %}
        {% if kids %}
          {{ kids | selectattr('tomorrow.needs_preparation', 'equalto', true) | list | length > 0 }}
        {% else %}
          false
        {% endif %}
  action:
    - service: notify.mobile_app
      data:
        title: "Tomorrow's School Schedule"
        message: >
          {% set kids = state_attr('sensor.infomentor_dashboard', 'kids') %}
          {% set tomorrow_kids = kids | selectattr('tomorrow.needs_preparation', 'equalto', true) | list %}
          {% for kid in tomorrow_kids %}
            {{ kid.name }}: {{ kid.tomorrow.summary }}
          {% endfor %}
```

### Dashboard Cards
```yaml
# New unified dashboard - shows all kids at once
type: custom:mushroom-template-card
primary: "{{ states('sensor.infomentor_dashboard') }}"
secondary: |
  {% for kid in state_attr('sensor.infomentor_dashboard', 'kids') %}
    {{ kid.name }}: {{ kid.today.summary }}
    {% if kid.tomorrow.needs_preparation %}📚 Tomorrow: {{ kid.tomorrow.summary }}{% endif %}
  {% endfor %}
icon: mdi:view-dashboard
badge_icon: |
  {% set needs_prep_today = state_attr('sensor.infomentor_dashboard', 'kids') | selectattr('today.needs_preparation', 'equalto', true) | list | length %}
  {% if needs_prep_today > 0 %}mdi:school{% endif %}

# Traditional individual sensors
type: entities
title: Today's Schedule
entities:
  - sensor.felix_today_schedule
  - sensor.isolde_today_schedule
  - binary_sensor.felix_needs_preparation_today
  - binary_sensor.isolde_needs_preparation_today

# Tomorrow preparation check
type: entities
title: Tomorrow's Schedule
entities:
  - sensor.felix_tomorrow_schedule
  - sensor.isolde_tomorrow_schedule
  - binary_sensor.felix_has_school_tomorrow
  - binary_sensor.isolde_has_school_tomorrow
```

## Recent Improvements

### Schedule Freshness Gate (v1.6)
- **Complete-schedule requirement**: Data freshness now updates only when every pupil returns a fresh schedule payload in the same cycle.
- **Per-pupil diagnostics**: Sensors expose which pupils are missing data and which ones rely on cached schedules, making troubleshooting easier.
- **Storage compatibility**: The integration stores a dedicated `last_complete_schedule_update` timestamp, falling back to the legacy field for existing installations.
- **Smarter retries**: The coordinator keeps retrying quickly until the schedule is complete, preventing false "<1 day" freshness claims when the upstream API stalls mid-fetch.

### Dashboard Enhancement (v1.3)
- **Unified Dashboard**: New dashboard sensor showing all children's schedules for today and tomorrow
- **Tomorrow Schedule Support**: Added sensors for tomorrow's schedule and preparation needs
- **Merged Preparation Logic**: "Needs Preparation Today" sensor now includes both school and preschool/fritids
- **Comprehensive Attributes**: Dashboard provides detailed schedule summaries with times and activity types
- **Enhanced Automation Support**: New dashboard-based automations can monitor all children at once

### Child Type Detection Enhancement (v1.2)
- **Fixed Logic**: Corrected child type detection to properly distinguish school vs preschool children
- **Timetable Focus**: Now primarily uses actual timetable entries for school child detection
- **Better Properties**: Added `has_timetable_entries` property for clearer logic
- **Improved Fallback**: Enhanced fallback logic using time registration types

### Timetable Endpoint Migration
- **Better Data Source**: Switched from calendar endpoint to dedicated timetable endpoint
- **More Accurate**: School timetables now retrieved from proper `/timetable/timetable/gettimetablelist` endpoint
- **Reliable Classification**: Improved accuracy in distinguishing educational content from general calendar events

## Troubleshooting

### Common Issues

#### Child Appears as Wrong Type
- **Issue**: School child shows as preschool or vice versa
- **Solution**: Check the `sensor.child_name_child_type` attributes for detailed reasoning
- **Data**: The `description` attribute explains the classification logic used

#### No Schedule Data
- **Check Authentication**: Verify credentials in the integration configuration
- **Check Pupils**: Ensure pupil IDs are correctly retrieved
- **Check Logs**: Look for authentication or API errors in Home Assistant logs

#### Missing Timetable Entries
- **School System**: Some schools may not publish timetables through the API
- **Timing**: Timetables might not be available far in advance
- **Fallback**: The system uses time registration data as fallback for classification

### Debug Information

Enable debug logging to troubleshoot issues:

```yaml
logger:
  default: warning
  logs:
    custom_components.infomentor: debug
```

## Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add/update tests as needed
5. Submit a pull request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Disclaimer

This is an unofficial integration. InfoMentor is a trademark of its respective owners. This integration is not affiliated with or endorsed by InfoMentor.

## Recent Fixes

### Timetable Display Bug (RESOLVED ✅)

**Problem**: Felix was correctly identified as a school child, but his timetable entries were not appearing in his schedule attributes - only fritids time registrations were visible.

**Root Cause**: The sensor code was trying to access `entry.classroom` but the `TimetableEntry` model uses `entry.room`. This caused an `AttributeError` that silently prevented timetable entries from being included in the schedule display.

**Final Fix Applied**:
1. **Corrected Field Name**: Changed `entry.classroom` to `entry.room` in both schedule sensors  
2. **Added Null Safety**: Added null checks for `start_time` and `end_time` in display logic
3. **Fixed Time Comparison**: Fixed `earliest_start` and `latest_end` properties to filter out `None` values

**Verification**: Testing confirms that timetable entries now properly appear in schedule attributes alongside time registrations.

### Child Type Detection Enhancement (RESOLVED ✅)

**Problem**: School children were appearing as preschool children because the classification logic was flawed.

**Root Cause**: The `has_school` property included both timetable entries and time registrations, making preschool children appear as school children.

**Final Fix Applied**:
1. **New Property**: Added `has_timetable_entries` property for precise school lesson detection
2. **Improved Logic**: Child type sensor now uses `has_timetable_entries` for primary classification
3. **Better Properties**: Clarified semantics of `has_school` vs `has_timetable_entries` vs `has_preschool_or_fritids`
4. **Enhanced Fallback**: Added fallback logic using time registration types

**Verification**: Testing confirms accurate school vs preschool distinction.

### Pupil Switching Issue (RESOLVED ✅)

**Problem**: Both pupils were showing identical schedule data because the pupil switching mechanism wasn't working correctly.

**Root Cause**: The pupil switching was incorrectly treating the server's `302 Found` redirect response as a failure, when it's actually the correct response for a successful pupil switch.

**Final Fix Applied**:
1. **Correct HTTP Status Handling**: Modified `switch_pupil()` to accept both `200 OK` and `302 Found` as successful responses
2. **Proper Redirect Handling**: Added `allow_redirects=True` to handle server-side redirects correctly
3. **Increased Switch Delay**: Extended delay to 2.0 seconds to ensure server-side session changes take effect
4. **Endpoint Prioritisation**: Prioritised the hub endpoint (`hub.infomentor.se`) as the primary switching endpoint

**Verification**: Testing confirms that Felix and Isolde now return different data:
- Felix: 12:00-16:00 time registration, 35 timetable entries across various date ranges
- Isolde: 08:00-16:00 time registration, different schedule pattern

## Troubleshooting

### Both pupils showing the same schedule
This issue has been fixed in the latest version. If you still experience it:
1. Check the logs for switch ID mapping (should show different switch IDs for each pupil)
2. Ensure the integration has been restarted after the update
3. Look for debug messages showing successful pupil switching

### Authentication failures
- Verify your credentials are correct
- Check if you can log in to InfoMentor directly
- Look for OAuth-related errors in the logs

## Debug Logging

To enable debug logging, add this to your `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.infomentor: debug
```

## Support

For issues and feature requests, please check the logs first and include relevant debug information when reporting problems. 