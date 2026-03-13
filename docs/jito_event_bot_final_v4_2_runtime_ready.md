# JITO Youth 3-Day Event AI Bot - Implementation Plan v3.0
**Status**: Database Schema Complete | n8n Workflows Pending  
**Last Updated**: November 14, 2025, 6:09 PM IST  
**Environment**: Local Development (PostgreSQL + n8n 1.119.1)

---

## **PROJECT OVERVIEW**

**Duration**: 3-day event (Nov 20-22, 2025)  
**Scale**: 50 events, 4000 participants  
**Tech Stack**: 
- Database: PostgreSQL (local, migrates to Supabase/Docker later)
- Orchestration: n8n 1.119.1 (self-hosted)
- AI: OpenAI gpt-4o-mini
- Messaging: WhatsApp Cloud API (integration pending)

**Budget**: $412.50 approved (OpenAI ~$12, WhatsApp ~$400)

---

## **COMPLETED WORK (Database Layer)**

### ✅ **SCHEMA-001: Database Schema Design**
**Status**: COMPLETE  
**Completed On**: Nov 14, 2025

#### **Tables Created (6 total)**

##### **1. `users` Table**
```sql
CREATE TABLE users (
  phone TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  age INT,
  email TEXT,
  hotel_name TEXT,                    -- NULL for local city residents
  hotel_room TEXT,                    -- NULL for local city residents
  hotel_gmaps_link TEXT,              -- Google Maps URL to hotel
  coordinator_name TEXT,              -- NULL for local residents
  coordinator_phone TEXT,             -- NULL for local residents
  created_at TIMESTAMP DEFAULT NOW()
);
```

**Key Decisions**:
- ✅ `hotel_*` columns nullable (local residents don't need hotels)
- ✅ `coordinator_*` inline (no separate coordinators table)
- ✅ Local residents: all hotel/coordinator fields = NULL
- ✅ Out-of-city users: hotel + coordinator assigned

**Sample Data**: 5 test users inserted (3 with hotels, 2 local)

---

##### **2. `events` Table**
```sql
CREATE TABLE events (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  date DATE NOT NULL,
  time TIME NOT NULL,
  location TEXT NOT NULL,
  gmaps_link TEXT NOT NULL,
  description TEXT NOT NULL,          -- AI reads this for semantic matching
  agenda TEXT,                        -- Optional time schedule
  contact_person TEXT NOT NULL,
  contact_phone TEXT NOT NULL,
  capacity INT NOT NULL DEFAULT 100,
  food_location_id INT,
  postponed_to TIMESTAMP,             -- NULL = active, NOT NULL = rescheduled
  cancelled BOOLEAN DEFAULT false,
  created_at TIMESTAMP DEFAULT NOW(),
  CONSTRAINT fk_food_location FOREIGN KEY (food_location_id) 
    REFERENCES food_locations(id)
);

CREATE INDEX idx_events_date ON events(date);
CREATE INDEX idx_events_cancelled ON events(cancelled) WHERE cancelled = false;
```

**Key Decisions**:
- ❌ **No `topics` column** (admin won't provide; AI reads description instead)
- ✅ `cancelled` boolean for admin cancellations
- ✅ `postponed_to` stores when postponement happened
- ✅ When postponing: UPDATE `date` and `time` columns directly
- ✅ Foreign key to `food_locations` enforced

**Sample Data**: 3 test events inserted (Book Club, AI Summit, Startup Mixer)

---

##### **3. `food_locations` Table**
```sql
CREATE TABLE food_locations (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  location TEXT NOT NULL,
  sponsor_name TEXT NOT NULL,
  hours TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);
```

**Key Decisions**:
- ✅ Each event maps to ONE food location via `events.food_location_id`
- ✅ Sponsor info displayed in registration confirmation message
- ⛔ Earlier drafts mentioned a `gmaps_link` column; this column does NOT exist in the current schema.

**Key Decisions**:
- ✅ Each event maps to ONE food location via `events.food_location_id`
- ✅ Sponsor info displayed in registration confirmation message

**Sample Data**: 7 food counters inserted with sponsor info

---

##### **4. `registrations` Table**
```sql
CREATE TABLE registrations (
  id SERIAL PRIMARY KEY,
  event_id INT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  phone TEXT NOT NULL REFERENCES users(phone),
  registered_at TIMESTAMP DEFAULT NOW(),
  checked_in BOOLEAN DEFAULT false,
  checked_in_at TIMESTAMP,
  UNIQUE(event_id, phone),
  CONSTRAINT chk_checkin_consistency CHECK (
    (checked_in = true AND checked_in_at IS NOT NULL) 
    OR 
    (checked_in = false AND checked_in_at IS NULL)
  )
);

CREATE INDEX idx_registrations_phone ON registrations(phone);
CREATE INDEX idx_registrations_event ON registrations(event_id);
CREATE INDEX idx_registrations_checkin ON registrations(checked_in) WHERE checked_in = false;

-- Capacity enforcement trigger
CREATE OR REPLACE FUNCTION check_event_capacity()
RETURNS TRIGGER AS $function$
BEGIN
  IF (SELECT COUNT(*) FROM registrations WHERE event_id = NEW.event_id) >= 
     (SELECT capacity FROM events WHERE id = NEW.event_id) THEN
    RAISE EXCEPTION 'Event is full';
  END IF;
  RETURN NEW;
END;
$function$ LANGUAGE plpgsql;

CREATE TRIGGER enforce_capacity
BEFORE INSERT ON registrations
FOR EACH ROW EXECUTE FUNCTION check_event_capacity();
```

**Key Decisions**:
- ✅ `UNIQUE(event_id, phone)` prevents duplicate registrations
- ✅ `CASCADE DELETE` when event deleted
- ✅ `chk_checkin_consistency` ensures `checked_in` and `checked_in_at` stay in sync
- ✅ `check_event_capacity()` trigger prevents overbooking
- ✅ Check-in tracking for turnup rate calculation (no separate `event_checkins` table needed)

**Sample Data**: 4 test registrations inserted

**Turnup Rate Query** (admin feature):
```sql
SELECT 
  e.name,
  e.capacity,
  COUNT(r.id) as registered,
  COUNT(CASE WHEN r.checked_in = true THEN 1 END) as checked_in,
  ROUND(100.0 * COUNT(CASE WHEN r.checked_in = true THEN 1 END) / COUNT(r.id), 1) as turnup_rate
FROM events e
LEFT JOIN registrations r ON e.id = r.event_id
WHERE e.name = 'AI Summit'
GROUP BY e.id;
```

---

##### **5. `admins` Table**
```sql
CREATE TABLE admins (
  phone TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);
```

**Key Decisions**:
- ✅ 2 hardcoded admin phone numbers
- ✅ No phone changes allowed (manual DB update if needed)
- ✅ Used to verify admin commands in n8n workflows

**Sample Data**: 2 placeholder admin numbers (MUST BE REPLACED with real numbers)

---

##### **6. `chat_history` Table**
```sql
CREATE TABLE chat_history (
  phone TEXT PRIMARY KEY REFERENCES users(phone) ON DELETE CASCADE,
  summary TEXT,                       -- AI-generated summary of conversation
  recent_messages JSONB NOT NULL DEFAULT '[]'::jsonb,
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_chat_updated ON chat_history(updated_at);
```

**Key Decisions**:
- ❌ **No full message history** (token waste)
- ✅ **Hybrid approach**: `summary` (cumulative context) + `recent_messages` (last 3 messages)
- ✅ `recent_messages` format: `[{"role":"user","content":"text"},{"role":"assistant","content":"reply"}]`
- ✅ OpenAI-compatible JSONB structure
- ✅ Cumulative summary regeneration: includes old summary + new messages when updating

**Summary Regeneration Logic** (n8n implementation pending):
```javascript
// When recent_messages exceeds 10 interactions
const oldSummary = db.summary || '';
const recentContext = JSON.stringify(recentMsgs);

const newSummary = await openai.chat.completions.create({
  messages: [{
    role: 'user',
    content: `Previous summary: ${oldSummary}\n\nNew conversations: ${recentContext}\n\nUpdate the summary to include both old and new information in 2 sentences.`
  }]
});
```

**Sample Data**: 2 test chat histories with summary + messages

---

### ✅ **SCHEMA-002: Database Constraints & Triggers**
**Status**: COMPLETE

**Applied Constraints**:
1. ✅ Foreign key: `events.food_location_id` → `food_locations(id)`
2. ✅ Check constraint: `registrations.chk_checkin_consistency`
3. ✅ Trigger: `check_event_capacity()` prevents overbooking
4. ✅ Cascade delete: `chat_history` deleted when user deleted

---

## **PENDING WORK (Application Layer)**

### ⏳ **INFRA-001: Local Development Setup**
**Status**: PARTIALLY COMPLETE  
**Completed**:
- ✅ PostgreSQL installed locally
- ✅ pgAdmin 4 connected
- ✅ Database `jito_events` created
- ✅ n8n 1.119.1 installed and running (localhost:5678)

**Pending**:
- ⏳ WhatsApp Cloud API account setup (deferred until workflows ready)

---

### ⏳ **CHAT-001: Conversation Context Management**
**Status**: NOT STARTED  
**Dependencies**: `INFRA-001` (Postgres credential in n8n)

**n8n Workflow: "Chat Context Handler"**

**Nodes to Build**:
1. **Manual Trigger** (for local testing without WhatsApp)
2. **Set Node**: Define test user phone + message
3. **Postgres Query**: Load user + chat context
   ```sql
   SELECT u.name, u.hotel_room, u.hotel_name, ch.summary, ch.recent_messages
   FROM users u
   LEFT JOIN chat_history ch ON u.phone = ch.phone
   WHERE u.phone = :phone
   ```
4. **Code Node**: Build messages array for OpenAI
   ```javascript
   const summary = $('Postgres').first().json.summary;
   const recentMsgs = $('Postgres').first().json.recent_messages || [];
   const userMsg = $input.item.json.message;

   const messages = [
     {
       role: 'system',
       content: `You are a friendly event AI assistant.\nContext: ${summary || 'First-time user'}`
     },
     ...recentMsgs,
     { role: 'user', content: userMsg }
   ];

   return { messages, phone, userName: $('Postgres').first().json.name };
   ```
5. **IF Node**: Check if first-time user (send greeting, skip AI)
6. **OpenAI Chat Node**: Generate reply
7. **Code Node**: Append AI reply to recent_messages, keep last 3
8. **Postgres Upsert**: Save updated context
   ```sql
   INSERT INTO chat_history (phone, summary, recent_messages, updated_at)
   VALUES (:phone, :summary, :recent_messages::jsonb, NOW())
   ON CONFLICT (phone) DO UPDATE 
   SET recent_messages = :recent_messages::jsonb, updated_at = NOW()
   ```
9. **Display Node**: Show bot reply (for testing)

**Test Cases**:
- ⏳ First-time user says "Hi" → greeting returned
- ⏳ User says "I love AI" → AI recommends AI Summit
- ⏳ Context persists across multiple messages

---

### ⏳ **AI-001: AI Agent System Prompt Configuration**
**Status**: NOT STARTED  
**Dependencies**: `CHAT-001`

**System Prompt** (to be configured in OpenAI Chat node):
```
You are a friendly WhatsApp AI assistant for JITO Youth's 3-day event (Nov 20-22, 2025).

USER CONTEXT:
- Name: {{$json.userName}}
- Hotel: {{$json.hotelName}}, Room {{$json.hotelRoom}} (NULL if local resident)
- Coordinator: {{$json.coordinatorName}} ({{$json.coordinatorPhone}}) (NULL if local)

YOUR ROLE:
1. Recommend events by reading full event descriptions (semantic matching)
2. Register users for events (check capacity via tool)
3. Answer hotel room queries
4. Share event locations with Google Maps links after registration
5. Provide food counter info with sponsor names
6. Redirect logistics queries to coordinator

TOOLS AVAILABLE:
- fetch_events_detailed() → Returns all active events with full descriptions
- register_user(event_id, phone) → Registers user, returns location + food info
- get_user_hotel(phone) → Returns hotel name + room + map link
- get_food_location(event_id) → Returns food counter details

RESPONSE RULES:
- Read full event.description for recommendations (not just topics)
- For "Where is my room?": Query users table, return hotel + room + gmaps_link
- For "I want to go to my room": "Please wait near logistics area. Coordinator: {{coordinatorPhone}}"
- After registration: Auto-share event location + Google Maps + food counter + sponsor
- Block off-topic: "I'm here for event assistance only!"
- Tone: Friendly, 1-2 emojis, <100 words
- NEVER recommend cancelled events (WHERE cancelled = false)

COORDINATOR HANDOFF:
If query can't be handled, say: "For personalized help, contact your coordinator {{coordinatorName}}: {{coordinatorPhone}}"
(If coordinator = NULL, say: "For queries, contact event help desk: +919876543200")
```

---

### ⏳ **REG-001: Event Registration Tool**
**Status**: NOT STARTED  
**Dependencies**: `AI-001`, `SCHEMA-001`

**n8n Sub-Workflow: "Register User"**

**Input Parameters** (from AI Agent):
- `event_id` (integer)
- `phone` (text)

**Logic**:
```sql
-- Step 1: Fetch event + capacity check (trigger handles this, but return user-friendly message)
SELECT e.name, e.location, e.gmaps_link, e.time, e.date, e.food_location_id,
       e.capacity, COUNT(r.id) as current
FROM events e
LEFT JOIN registrations r ON e.id = r.event_id
WHERE e.id = :event_id AND e.cancelled = false
GROUP BY e.id;

-- Step 2: Register (trigger will raise exception if full)
INSERT INTO registrations (event_id, phone) 
VALUES (:event_id, :phone)
ON CONFLICT (event_id, phone) DO NOTHING
RETURNING id;

-- Step 3: Fetch food location
SELECT f.name, f.location, f.sponsor_name, f.gmaps_link
FROM food_locations f WHERE f.id = :food_location_id;

-- Step 4: Return success message with all details
RETURN {
  success: true,
  event_name: ...,
  location: ...,
  gmaps_link: ...,
  date: ...,
  time: ...,
  food_name: ...,
  food_location: ...,
  sponsor: ...,
  food_map: ...
}
```

**AI Formats Response**:
```
✅ You're registered for {{event_name}}!

📍 Location: {{location}}
🗺️ Map: {{gmaps_link}}
🕐 Time: {{date}} at {{time}}

🍽️ Nearest Food: {{food_name}} - {{food_location}}
💼 Sponsored by {{sponsor}}
🗺️ Food Map: {{food_map}}

See you there! 🎉
```

**Error Handling**:
- Capacity exception → "Event is full. Check other events?"
- Duplicate registration → "You're already registered for this event"
- Cancelled event → "This event has been cancelled"

---

### ⏳ **RECOMMEND-001: Event Recommendation Tool**
**Status**: NOT STARTED  
**Dependencies**: `AI-001`

**n8n Sub-Workflow: "Fetch Events"**

**Query**:
```sql
SELECT id, name, date, time, location, gmaps_link, description, 
       capacity, (SELECT COUNT(*) FROM registrations WHERE event_id = events.id) as registered
FROM events
WHERE cancelled = false AND postponed_to IS NULL
ORDER BY date, time;
```

**Return to AI**: Full event list with descriptions

**AI Behavior**:
- User: "I love thrillers"
- AI reads descriptions, finds: "Discuss Agatha Christie, Gillian Flynn..."
- AI: "Perfect! I recommend Book Club on Nov 20. Want to register?"

---

### ⏳ **HOTEL-001: Hotel Query Tool**
**Status**: NOT STARTED  
**Dependencies**: `AI-001`

**Query**:
```sql
SELECT hotel_name, hotel_room, hotel_gmaps_link, coordinator_name, coordinator_phone
FROM users
WHERE phone = :phone;
```

**AI Response Logic**:
```javascript
if (hotel_name === null) {
  return "You're a local resident, no hotel assigned.";
} else {
  return `🏨 Your hotel: ${hotel_name}\n🚪 Room: ${hotel_room}\n🗺️ Map: ${hotel_gmaps_link}`;
}
```

---

### ⏳ **ADMIN-001: Admin Verification**
**Status**: NOT STARTED  
**Dependencies**: `SCHEMA-001`

**n8n Function Node** (used in all admin workflows):
```javascript
const phone = $input.item.json.phone;
const adminCheck = await $query(`SELECT phone FROM admins WHERE phone = '${phone}'`);

if (adminCheck.length === 0) {
  return { isAdmin: false, message: "⛔ Admin access required" };
}
return { isAdmin: true };
```

---

### ⏳ **ADMIN-002: Admin Event Creation**
**Status**: NOT STARTED  
**Dependencies**: `ADMIN-001`

**Admin Message Format**:
```
Create event:
Name: Blockchain Workshop
Date: Nov 21
Time: 2 PM
Location: Hall C, 2nd Floor
Map: https://maps.google.com/?q=...
Description: Hands-on smart contract development...
Agenda: 2-3 PM Intro, 3-4 PM Coding
Food: Main Cafeteria
Contact: Priya +919876543211
Capacity: 80
```

**n8n Workflow**:
1. Admin auth check
2. AI structured extraction (parse admin message)
3. Postgres: Lookup `food_location_id` by name
4. Postgres: INSERT event
5. WhatsApp confirm: "✅ Event created: {name} (ID: {id})"

---

### ⏳ **ADMIN-003: Event Deletion + Notifications**
**Status**: NOT STARTED  
**Dependencies**: `ADMIN-001`, `REG-001`

**Admin Command**: "Delete event: Book Club"

**Workflow**:
1. Admin auth
2. Fetch event + registered users
3. Confirm with admin (send "Reply YES")
4. On YES: UPDATE `cancelled = true` (soft delete, keep data)
5. Loop: Notify all registered users
6. Admin confirm: "Event cancelled, {count} users notified"

**Why soft delete**: Preserves registration history, turnup data

---

### ⏳ **ADMIN-004: Event Postponement + Notifications**
**Status**: NOT STARTED  
**Dependencies**: `ADMIN-001`

**Admin Command**: "Postpone Book Club to Nov 21 7 PM"

**Workflow**:
1. Admin auth
2. AI extract: event_name, new_date, new_time
3. Postgres:
   ```sql
   UPDATE events 
   SET date = :new_date, time = :new_time, postponed_to = NOW()
   WHERE name ILIKE :event_name;
   ```
4. Fetch registered users
5. Loop: Notify users with new date/time
6. Admin confirm

---

### ⏳ **ADMIN-005: Targeted Announcements**
**Status**: NOT STARTED  
**Dependencies**: `ADMIN-001`

**Admin Command**: "Announce to AI Summit: Lunch extended 30 mins"

**Workflow**:
1. Admin auth
2. AI parse: audience (all/event), message
3. Query:
   ```sql
   -- For event-specific
   SELECT u.phone FROM users u
   JOIN registrations r ON u.phone = r.phone
   JOIN events e ON r.event_id = e.id
   WHERE e.name ILIKE :event_name;
   ```
4. Loop: Send WhatsApp (rate limit: 10/sec)
5. Confirm: "📢 Sent to {count} users"

---

### ⏳ **ADMIN-006: Turnup Rate Query**
**Status**: NOT STARTED (Query ready)  
**Dependencies**: `ADMIN-001`, `REG-001`

**Admin Query**: "Turnup rate for AI Summit"

**Workflow**: Execute turnup query (documented above in registrations section), format result

---

### ⏳ **ENGAGE-001: Daily Themed Engagement**
**Status**: NOT STARTED  \
**Dependencies**: `REG-001`, `AI-001`, `SCHEMA-003`, `NOTIF-001`\
\n**Behavior (REPLACED WITH NOTIFICATIONS PIPELINE)**:
- Instead of n8n Schedule querying `registrations` live, engagement messages are created as rows in `notifications` with `template = 'HYPE'` and appropriate `scheduled_at` values.\
- A worker (`NOTIF-004`) sends them according to `notifications.status`/`scheduled_at`.\
\n**Input**:
- From DB: `event_id`, `event_name`, `description`, `date`, `time` from `events` table.\
- From registration context: target `phone` numbers via `registrations` table.\
\n**Output**:
- One or more `notifications` rows per user/event with `template='HYPE'`.\
- Actual WhatsApp sends performed by `NOTIF-004` (not by this task).\n\n---\n\n### ⏳ **FOOD-001: Food Counter Announcements**\n**Status**: NOT STARTED  \
**Dependencies**: `REG-001`, `SCHEMA-001`, `SCHEMA-003`, `NOTIF-001`\
\n**Behavior (REPLACED WITH NOTIFICATIONS PIPELINE)**:
- Food announcements are inserted into `notifications` with `template='FOOD_ANNOUNCEMENT'` for the relevant `phone` numbers and `scheduled_at` tied to meal times (11:30, 15:00, 18:30).\
- No n8n Schedule should compute this at send time; all timing is encoded in `scheduled_at`.\
\n**Input**:
- `event_id` and its `food_location_id` from `events`.\
- Audience phones from `registrations` joined to `users`.\
\n**Output**:
- `notifications` rows with `template='FOOD_ANNOUNCEMENT'` and payload containing food location + sponsor fields.\n\n---\n\n### ⏳ **REMIND-001: Morning Event Reminder**\n**Status**: NOT STARTED  \
**Dependencies**: `REG-001`, `SCHEMA-003`, `NOTIF-001`, `NOTIF-003`\
\n**Behavior (NOW USING NOTIFICATIONS TABLE)**:
- Morning reminders are NOT driven by a direct n8n cron query on `registrations`.\
- Instead, `NOTIF-001` creates `notifications` rows with `template='MORNING_REMINDER'` and `scheduled_at = event_date + 09:00`.\
- `NOTIF-003`/pg_cron and `NOTIF-004` handle sending.\
\n**Input**:
- `event_id`, `phone`, `event_name`, `date`, `time`, `location`, `gmaps_link` at registration time.\
\n**Output**:
- `notifications` rows only. No direct WhatsApp sends from this task.\n\n---\n\n### ⏳ **REMIND-002: 1-Hour-Before Reminder**\n**Status**: NOT STARTED  \
**Dependencies**: `REG-001`, `SCHEMA-003`, `NOTIF-001`, `NOTIF-003`\
\n**Behavior (NOW USING NOTIFICATIONS TABLE)**:
- 1-hour reminders are NOT computed via `WHERE e.time BETWEEN NOW()+55min AND NOW()+65min`.\
- The exact `scheduled_at` is computed when the user registers and stored in `notifications` rows with `template='ONE_HOUR_BEFORE'`.\
- Sending is done by `NOTIF-004` using the generic notification worker.\
\n**Input**:
- Same as `REMIND-001`.\
\n**Output**:
- `notifications` rows; sending logic is centralized in the notification worker.\n\n---\n\n## **IMPLEMENTATION CHECKLIST**


### **Foundation Layer** [Sprint 1: Days 1-2]
- [x] `SCHEMA-001` Create all 6 database tables
- [x] `SCHEMA-002` Apply constraints + triggers
- [ ] `INFRA-001` Configure n8n credentials (Postgres + OpenAI)
- [ ] `CHAT-001` Build chat context handler workflow
- [ ] `AI-001` Configure AI Agent system prompt

### **Core User Features** [Sprint 2: Days 3-4]
- [ ] `RECOMMEND-001` Event recommendation tool
- [ ] `REG-001` Registration tool with auto-location share
- [ ] `HOTEL-001` Hotel query tool
- [ ] Test: End-to-end user registration flow

### **Admin Features** [Sprint 3: Days 5-7]
- [ ] `ADMIN-001` Admin verification function
- [ ] `ADMIN-002` Event creation workflow
- [ ] `ADMIN-003` Event deletion workflow
- [ ] `ADMIN-004` Event postponement workflow
- [ ] `ADMIN-005` Targeted announcements
- [ ] `ADMIN-006` Turnup rate query

### **Automation Features** [Sprint 4: Days 8-9]
- [ ] `ENGAGE-001` Daily engagement messages
- [ ] `FOOD-001` Food counter announcements
- [ ] `REMIND-001` Morning reminders
- [ ] `REMIND-002` 1-hour-before reminders

### **Integration & Testing** [Sprint 5: Days 10-11]
- [ ] WhatsApp Cloud API setup
- [ ] Webhook integration (replace Manual Trigger)
- [ ] Load test with 100 concurrent simulated users
- [ ] Fix performance bottlenecks

### **Deployment** [Sprint 6: Day 12]
- [ ] Migrate Postgres to Supabase/Docker (if needed)
- [ ] Deploy n8n workflows to production
- [ ] Admin training session
- [ ] Go-live monitoring

---

## **DATABASE SCHEMA REFERENCE**

### **Table Relationships**
```
users (phone PK)
  ↓ 1:N
registrations (event_id FK, phone FK)
  ↑ N:1
events (id PK, food_location_id FK)
  ↑ N:1
food_locations (id PK)

admins (phone PK) -- standalone

chat_history (phone PK FK to users)
```

### **Key Queries for n8n Workflows**

**User Registration**:
```sql
INSERT INTO registrations (event_id, phone) VALUES (:event_id, :phone)
ON CONFLICT DO NOTHING RETURNING id;
```

**Load Chat Context**:
```sql
SELECT u.name, u.hotel_room, ch.summary, ch.recent_messages
FROM users u LEFT JOIN chat_history ch ON u.phone = ch.phone
WHERE u.phone = :phone;
```

**Fetch Active Events**:
```sql
SELECT * FROM events WHERE cancelled = false ORDER BY date, time;
```

**Admin Verification**:
```sql
SELECT phone FROM admins WHERE phone = :phone;
```

**Turnup Rate**:
```sql
SELECT e.name, COUNT(r.id) as registered, 
       COUNT(CASE WHEN r.checked_in THEN 1 END) as checked_in
FROM events e LEFT JOIN registrations r ON e.id = r.event_id
WHERE e.name = :event_name GROUP BY e.id;
```

---

## **COST ESTIMATE (Updated)**

### **OpenAI (gpt-4o-mini)**
- Chat: 4000 users × 5 msgs × 3 days × 650 tokens = **$9**
- Recommendations: 4000 × 3 queries × 1200 tokens = **$3**
- Engagement: 4000 × 3 days × 150 tokens = **$0.50**
- **Total OpenAI**: ~$12.50

### **WhatsApp Cloud API**
- Conversations: 4000 × 5 × $0.01 = **$200**
- Broadcasts: 20K × $0.01 = **$200**
- **Total WhatsApp**: ~$400

### **Infrastructure**
- PostgreSQL: $0 (local/Supabase free tier)
- n8n: $0 (self-hosted)

**Grand Total**: $412.50

---

## **MIGRATION PATH TO PRODUCTION**

### **Database Export** (when ready):
```bash
pg_dump -U postgres -d jito_events > jito_events_backup.sql
```

### **Import to Supabase**:
1. Create Supabase project
2. SQL Editor → Paste schema + data
3. Update n8n Postgres credential with Supabase connection string

### **Import to Docker**:
```bash
docker run -d --name jito-postgres -e POSTGRES_PASSWORD=*** -p 5432:5432 postgres:15
docker exec -i jito-postgres psql -U postgres < jito_events_backup.sql
```

---

## **NEXT IMMEDIATE STEPS**

1. ✅ Verify all 6 tables exist in pgAdmin
2. ✅ Verify triggers are active (try inserting 101st registration, should fail)
3. ⏳ Build `CHAT-001` workflow
4. ⏳ Test with Manual Trigger before WhatsApp integration

---

**Document Version**: 3.0  
**Generated**: November 14, 2025, 6:09 PM IST  
**Schema Completion**: 100%  
**Workflow Completion**: 0%  
**Overall Progress**: 15%

---

## ADDENDUM v4.2: Runtime Security, Registration Pipeline & Task Catalog

This addendum captures the **current live state** of the project after local implementation work in PostgreSQL and n8n. It does not remove earlier design decisions; where behavior has changed, notes are explicit.

### ✅ VIEW-001: Participant-Safe Database Views

These views expose only the columns that participant-facing logic needs, while hiding sensitive fields (age, email, capacity, admin contacts, etc.). They are intended to be used by backend workflows and tools, not directly by users.

#### 1. `v_events_public`

```sql
CREATE VIEW v_events_public AS
SELECT 
  id,
  name,
  date,
  time,
  location,
  gmaps_link,
  description
FROM events
WHERE cancelled = false;
```

- Exposes: `id`, `name`, `date`, `time`, `location`, `gmaps_link`, `description`.
- Hides: `capacity`, `food_location_id`, `contact_person`, `contact_phone`, `postponed_to`, `cancelled`, `created_at`.
- Purpose: Event discovery, detailed explanations, recommendation logic.
- Contract: Tools/AI may use `id` internally but must never show raw IDs to users.

#### 2. `v_my_profile`

```sql
CREATE VIEW v_my_profile AS
SELECT
  phone,
  name,
  hotel_name,
  hotel_room,
  hotel_gmaps_link,
  coordinator_name,
  coordinator_phone
FROM users;
```

- Exposes: `phone`, `name`, `hotel_name`, `hotel_room`, `hotel_gmaps_link`, `coordinator_name`, `coordinator_phone`.
- Hides: `age`, `email`, `created_at`.
- Purpose: Answer questions like "Where is my room?" and "Who is my coordinator?".

#### 3. `v_my_registrations`

```sql
CREATE VIEW v_my_registrations AS
SELECT 
  r.id         AS registration_id,
  r.event_id   AS event_id,
  r.phone      AS phone,
  r.registered_at,
  e.name       AS event_name,
  e.date,
  e.time,
  e.location,
  e.gmaps_link
FROM registrations r
JOIN events e ON e.id = r.event_id
WHERE e.cancelled = false;
```

- Exposes: `registration_id`, `event_id`, `phone`, `registered_at`, `event_name`, `date`, `time`, `location`, `gmaps_link`.
- Hides: `checked_in`, `checked_in_at`.
- Purpose: Let backend answer "What am I registered for?" for a given phone.
- Note: Combined with function parameters, the view is always filtered by the current user's `phone`.

#### 4. `v_food_public`

```sql
CREATE VIEW v_food_public AS
SELECT 
  id,
  name,
  location,
  sponsor_name,
  hours
FROM food_locations;
```

- Exposes: all existing `food_locations` columns.
- Purpose: Answer questions like "Where do I eat after this event?" and "Who is sponsoring the food counter?".

---

### ✅ FUNC-001: `register_for_event(p_phone TEXT, p_event_id INT)`

This function performs **safe registration** of a user for an event, enforcing capacity and returning structured JSON for the AI to interpret.

```sql
CREATE OR REPLACE FUNCTION register_for_event(
  p_phone TEXT,
  p_event_id INT
)
RETURNS JSON AS $$
DECLARE
  v_event_name     TEXT;
  v_location       TEXT;
  v_gmaps_link     TEXT;
  v_date           DATE;
  v_time           TIME;
  v_food_id        INT;
  v_food_name      TEXT;
  v_food_location  TEXT;
  v_sponsor        TEXT;
  v_reg_id         INT;
BEGIN
  -- Check if event exists and is active
  SELECT name, location, gmaps_link, date, time, food_location_id
  INTO   v_event_name, v_location, v_gmaps_link, v_date, v_time, v_food_id
  FROM   events
  WHERE  id = p_event_id AND cancelled = false;

  IF v_event_name IS NULL THEN
    RETURN json_build_object(
      'success',    false,
      'error_code', 'EVENT_NOT_FOUND'
    );
  END IF;

  -- Insert registration (capacity trigger will fire if full)
  BEGIN
    INSERT INTO registrations (event_id, phone)
    VALUES (p_event_id, p_phone)
    ON CONFLICT (event_id, phone) DO NOTHING
    RETURNING id INTO v_reg_id;
  EXCEPTION
    WHEN OTHERS THEN
      -- Capacity trigger raised exception (event full)
      RETURN json_build_object(
        'success',    false,
        'error_code', 'EVENT_FULL',
        'event_name', v_event_name
      );
  END;

  -- If ON CONFLICT did nothing (already registered)
  IF v_reg_id IS NULL THEN
    RETURN json_build_object(
      'success',    false,
      'error_code', 'ALREADY_REGISTERED',
      'event_name', v_event_name
    );
  END IF;

  -- Fetch food location details
  SELECT name, location, sponsor_name
  INTO   v_food_name, v_food_location, v_sponsor
  FROM   food_locations
  WHERE  id = v_food_id;

  -- Return success with full details
  RETURN json_build_object(
    'success',        true,
    'event_name',     v_event_name,
    'location',       v_location,
    'gmaps_link',     v_gmaps_link,
    'date',           v_date,
    'time',           v_time,
    'food_name',      COALESCE(v_food_name, 'Not assigned'),
    'food_location',  COALESCE(v_food_location, ''),
    'sponsor',        COALESCE(v_sponsor, '')
  );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
```

**Error codes** returned:
- `EVENT_NOT_FOUND` – event does not exist or is cancelled.
- `EVENT_FULL` – capacity trigger fired, event is full.
- `ALREADY_REGISTERED` – user already has a registration for this event.

**Success payload** includes:
- `event_name`, `location`, `gmaps_link`, `date`, `time`, `food_name`, `food_location`, `sponsor`.

Upstream dependencies:
- `events` table (SCHEMA-001).
- `registrations` table + `check_event_capacity()` trigger (SCHEMA-002).
- `food_locations` table.

Downstream usage:
- n8n workflow `Event Bot – Local Chat` calls this via PostgreSQL node when AI decides to register the user.
- AI uses structured JSON (`success`, `error_code`, fields) to craft user-visible messages.

---

### ✅ FUNC-002: `unregister_from_event(p_phone TEXT, p_event_id INT)`

This function cancels a user's registration **only if** there are more than 30 minutes before the event start. It also uses structured error codes.

```sql
CREATE OR REPLACE FUNCTION unregister_from_event(
  p_phone   TEXT,
  p_event_id INT
)
RETURNS JSON AS $$
DECLARE
  v_event_start        TIMESTAMP;
  v_event_name         TEXT;
  v_cutoff_minutes     INT := 30;  -- configurable via future schema change
  v_deleted_count      INT;
  v_minutes_until_start NUMERIC;
BEGIN
  -- Get event start time and name
  SELECT (date + time), name
  INTO   v_event_start, v_event_name
  FROM   events
  WHERE  id = p_event_id;

  IF v_event_start IS NULL THEN
    RETURN json_build_object(
      'success',    false,
      'error_code', 'EVENT_NOT_FOUND'
    );
  END IF;

  -- Calculate minutes until event starts
  v_minutes_until_start := EXTRACT(EPOCH FROM (v_event_start - NOW())) / 60;

  -- Check if within cutoff window
  IF NOW() >= (v_event_start - (v_cutoff_minutes || ' minutes')::INTERVAL) THEN
    RETURN json_build_object(
      'success',            false,
      'error_code',         'TOO_LATE_TO_CANCEL',
      'cutoff_minutes',     v_cutoff_minutes,
      'event_name',         v_event_name,
      'minutes_until_start', ROUND(v_minutes_until_start)
    );
  END IF;

  -- Delete registration (hard delete, frees capacity)
  DELETE FROM registrations
  WHERE event_id = p_event_id AND phone = p_phone;

  GET DIAGNOSTICS v_deleted_count = ROW_COUNT;

  IF v_deleted_count = 0 THEN
    RETURN json_build_object(
      'success',    false,
      'error_code', 'NOT_REGISTERED',
      'event_name', v_event_name
    );
  END IF;

  RETURN json_build_object(
    'success',    true,
    'event_name', v_event_name
  );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
```

**Error codes** returned:
- `EVENT_NOT_FOUND` – event id invalid.
- `TOO_LATE_TO_CANCEL` – within 30 minutes of event start.
- `NOT_REGISTERED` – user attempted to cancel without a registration.

Upstream dependencies:
- `events` table for `date` + `time`.
- `registrations` table.

Downstream usage:
- n8n workflow calls this when AI decides to unregister the user.
- AI reads error codes to explain why cancellation failed/succeeded.

---

### ✅ SEC-001: Row-Level Security (RLS) & Admin Role

RLS is enabled as a **defense-in-depth** mechanism. The primary enforcement of per-user access is via function parameters (`p_phone`), but RLS protects against direct table queries with leaked credentials.

```sql
-- Enable RLS
ALTER TABLE users         ENABLE ROW LEVEL SECURITY;
ALTER TABLE registrations ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_history  ENABLE ROW LEVEL SECURITY;
ALTER TABLE admins        ENABLE ROW LEVEL SECURITY;

-- Users: only see their own profile
CREATE POLICY user_view_own_profile
ON users
FOR SELECT
USING (phone = current_setting('app.current_phone', true));

-- Registrations: only see/delete own rows
CREATE POLICY user_view_own_registrations
ON registrations
FOR SELECT
USING (phone = current_setting('app.current_phone', true));

CREATE POLICY user_delete_own_registrations
ON registrations
FOR DELETE
USING (phone = current_setting('app.current_phone', true));

-- chat_history: no participant access (backend-only)
CREATE POLICY no_participant_access_to_chat_history
ON chat_history
FOR ALL
USING (false);

-- admins: no participant access
CREATE POLICY no_participant_access_to_admins
ON admins
FOR ALL
USING (false);

-- Admin/dev role that bypasses RLS
CREATE ROLE event_bot_admin_role LOGIN PASSWORD '***';
ALTER ROLE event_bot_admin_role BYPASSRLS;
```

Notes:
- The bot runtime does **not** rely on `SET app.current_phone` inside n8n; per-user filtering is enforced in functions by passing `p_phone` explicitly.
- RLS remains active to protect against direct SQL access outside of the controlled functions.

---

### ✅ WF-001: Local Chat + Registration Workflow (n8n)

Workflow file: **`Event_Bot_With_Registration_v5.json`** (imported into n8n).

High-level node flow:

1. **Webhook** (`/chat-local`)
   - Input: `{ "phone": "+91...", "message": "text" }`.

2. **Parse Input** (Code)
   - Extracts `phone` and `message` from webhook body.

3. **Load User & Chat** (Postgres)
   - Query joins `users` + `chat_history` to get `name`, hotel info, `summary`, `recent_messages`.

4. **Build LLM Messages** (Code)
   - Constructs OpenAI `messages` array with system context + previous summary + recent messages + current user message.

5. **AI Reply** (OpenAI Chat)
   - Currently returns text; Step 6 will update it to return JSON: `{ reply_text, action }`.

6. **Parse AI Action** (Code)
   - Attempts to `JSON.parse` the AI reply.
   - Output:
     - `action_type`: `'chat' | 'register' | 'unregister'` (defaults to `'chat'`).
     - `event_id`: integer or `null`.
     - `reply_text`: human-readable suggestion/answer.

7. **Action Router** (Switch)
   - Branch 0: `action_type == 'register'` → **Register User for Event**.
   - Branch 1: `action_type == 'unregister'` → **Unregister User from Event**.
   - Branch 2 (fallback): anything else → goes directly to **Format Action Result**.

8. **Register User for Event** (Postgres)
   - Calls `SELECT register_for_event(:phone, :event_id);`.
   - Returns JSON: `{ success, error_code?, event_name?, ... }`.

9. **Unregister User from Event** (Postgres)
   - Calls `SELECT unregister_from_event(:phone, :event_id);`.
   - Returns JSON: `{ success, error_code?, event_name?, cutoff_minutes?, minutes_until_start? }`.

10. **Format Action Result** (Code)
    - Merges branches.
    - For now, passes through `reply_text` unchanged.
    - Makes `functionResponse` available for future AI interpretation.

11. **Update chat context** (Code)
    - Uses `finalReply` as assistant message.
    - Appends `{role: 'user', content: userMsg}` and `{role: 'assistant', content: finalReply}` to `recent_messages`.
    - Keeps only last 3 messages and preserves existing `summary`.

12. **save chat history** (Postgres)
    - Upserts `chat_history(phone, summary, recent_messages, updated_at)`.

13. **Return Reply** (Webhook response)
    - Returns `{ reply: finalReply }` to the HTTP client (Python CLI now, WhatsApp later).

Upstream dependencies:
- `SCHEMA-001`, `SCHEMA-002`, `VIEW-001`, `FUNC-001`, `FUNC-002`.

Downstream roadmap:
- Step 6: Update AI system prompt to output JSON `{reply_text, action}` consistently and to interpret `error_code` and function results.
- Future: integrate WhatsApp webhook instead of manual/curl testing.

---

## Unified Task Catalog & Dependencies (v4.2)

Each task has a **tag**, status, dependencies (upstream), and dependents (downstream). This section is the handover map for any future agent.

### Foundation & Schema

- **SCHEMA-001** – Base Tables (`users`, `events`, `food_locations`, `registrations`, `admins`, `chat_history`)
  - Status: ✅ COMPLETE
  - Upstream: None
  - Downstream: `SCHEMA-002`, `VIEW-001`, `FUNC-001`, `FUNC-002`, `INFRA-001`, all workflows.

- **SCHEMA-002** – Constraints & Triggers (`check_event_capacity`, `chk_checkin_consistency`)
  - Status: ✅ COMPLETE
  - Upstream: `SCHEMA-001`
  - Downstream: `FUNC-001`, `ADMIN-006` (turnup rate), all registration flows.

- **VIEW-001** – Participant Views (`v_events_public`, `v_my_profile`, `v_my_registrations`, `v_food_public`)
  - Status: ✅ COMPLETE (SQL provided and executed locally)
  - Upstream: `SCHEMA-001`
  - Downstream: future tools if views are used directly in tools (currently functions handle most filtering).

- **SEC-001** – RLS & Admin Role (`event_bot_admin_role`)
  - Status: ✅ COMPLETE (RLS enabled, policies created, admin role defined)
  - Upstream: `SCHEMA-001`
  - Downstream: protects against direct table access outside controlled functions.

### Functions & Business Logic

- **FUNC-001** – `register_for_event(p_phone, p_event_id)`
  - Status: ✅ COMPLETE
  - Upstream: `SCHEMA-001`, `SCHEMA-002`
  - Downstream: `REG-001`, `WF-001`, future notification insertion (`NOTIF-001`).

- **FUNC-002** – `unregister_from_event(p_phone, p_event_id)`
  - Status: ✅ COMPLETE
  - Upstream: `SCHEMA-001`, `SCHEMA-002`
  - Downstream: `REG-002`, `WF-001`, future capacity-based FOMO notification pipeline.

### Infrastructure & Chat

- **INFRA-001** – Local Dev Setup (Postgres + n8n + credentials)
  - Status: ⏳ PARTIALLY COMPLETE
  - Completed: local Postgres, n8n running, DB created, workflows imported.
  - Pending: final confirmation of credential naming and production-equivalent configuration.

- **CHAT-001** – Conversation Context Management
  - Status: ✅ COMPLETE (Local)
  - Upstream: `INFRA-001`, `SCHEMA-001`
  - Downstream: `AI-001`, `WF-001`.

- **AI-001** – AI System Prompt & Behavior
  - Status: ⏳ PARTIAL
  - Current: basic system prompt implemented for chat; not yet updated to strict JSON `{reply_text, action}` format.
  - Upstream: `CHAT-001`
  - Downstream: `WF-001`, all tool usage.

### Registration & User Tools

- **REG-001** – Registration Tool (DB + Workflow)
  - Status: ✅ COMPLETE (DB function + n8n call path wired)
  - Upstream: `SCHEMA-001`, `SCHEMA-002`, `FUNC-001`, `WF-001`
  - Downstream: `NOTIF-001` (notifications), recommendation flows, admin stats.

- **REG-002** – Unregistration Tool (DB + Workflow)
  - Status: ✅ COMPLETE (DB function + n8n call path wired)
  - Upstream: `SCHEMA-001`, `SCHEMA-002`, `FUNC-002`, `WF-001`
  - Downstream: capacity-based FOMO notifications (later), admin reporting.

- **HOTEL-001** – Hotel & Coordinator Query Tool
  - Status: ⏳ NOT STARTED (logic trivial, but no separate tool node yet)
  - Upstream: `SCHEMA-001`, `VIEW-001`
  - Downstream: chat flows answering logistics questions.

- **RECOMMEND-001** – Event Recommendation Logic
  - Status: ⏳ NOT STARTED (AI currently has descriptions but no explicit ranking logic implemented)
  - Upstream: `SCHEMA-001`, `VIEW-001`, `AI-001`
  - Downstream: `REG-001`.

### Notifications & Engagement

- **SCHEMA-003** – `notifications` Table (Outbox)
  - Status: ⏳ PLANNED (SQL defined earlier, not applied yet in this addendum)
  - Upstream: `SCHEMA-001`
  - Downstream: `NOTIF-001`..`NOTIF-004`, `ENGAGE-001`, `FOOD-001`, `REMIND-001`, `REMIND-002`.

- **NOTIF-001** – Create Notifications on Registration
  - Status: ⏳ NOT STARTED
  - Upstream: `SCHEMA-003`, `REG-001`
  - Downstream: `REMIND-001`, `REMIND-002`, `ENGAGE-001`, `FOOD-001`.

- **NOTIF-002** – Cancel/Postpone Notification Updates
  - Status: ⏳ NOT STARTED
  - Upstream: `SCHEMA-003`, `ADMIN-003`, `ADMIN-004`
  - Downstream: reminder delivery logic.

- **NOTIF-003** – `claim_due_notifications()` + pg_cron
  - Status: ⏳ NOT STARTED
  - Upstream: `SCHEMA-003`
  - Downstream: `NOTIF-004`.

- **NOTIF-004** – Notification Sender Worker (n8n or Python)
  - Status: ⏳ NOT STARTED
  - Upstream: `SCHEMA-003`, `NOTIF-003`
  - Downstream: actual WhatsApp sends.

- **ENGAGE-001**, **FOOD-001**, **REMIND-001**, **REMIND-002**
  - Status: ⏳ NOT STARTED (design updated to use `notifications` outbox instead of direct n8n Schedule)
  - Upstream: `SCHEMA-003`, `NOTIF-001`..`NOTIF-004`
  - Downstream: participant engagement and reminders.

### Admin Workflows

- **ADMIN-001** – Admin Verification
  - Status: ⏳ NOT STARTED (logic defined, not wired into workflows)

- **ADMIN-002** – Event Creation
  - Status: ⏳ NOT STARTED

- **ADMIN-003** – Event Cancellation + Notifications
  - Status: ⏳ NOT STARTED

- **ADMIN-004** – Event Postponement + Notifications
  - Status: ⏳ NOT STARTED

- **ADMIN-005** – Targeted Announcements
  - Status: ⏳ NOT STARTED

- **ADMIN-006** – Turnup Rate Query
  - Status: ⏳ NOT STARTED (SQL ready)

### Integration & Deployment

- **WA-001** – WhatsApp Cloud API Integration
  - Status: ⏳ NOT STARTED
  - Upstream: `WF-001`, `AI-001`, `REG-001`, `REG-002`

- **DEPLOY-001** – Cloud Database & n8n Deployment
  - Status: ⏳ NOT STARTED

- **OBS-001** – Logging / Observability / Error Alerts
  - Status: ⏳ NOT STARTED (intentionally deferred until core functionality stable)

---

## Updated Implementation Checklist (v4.2)

### Foundation Layer
- [x] `SCHEMA-001` Base tables
- [x] `SCHEMA-002` Constraints & triggers
- [x] `VIEW-001` Participant views (`v_events_public`, `v_my_profile`, `v_my_registrations`, `v_food_public`)
- [x] `FUNC-001` `register_for_event()`
- [x] `FUNC-002` `unregister_from_event()`
- [x] `SEC-001` RLS policies & admin role (defense-in-depth)

### Core Chat & Registration (Local)
- [x] `INFRA-001` Local Postgres + n8n + credentials
- [x] `CHAT-001` Chat context handler (webhook-based)
- [ ] `AI-001` Final JSON-based system prompt (`reply_text` + `action`) – **PENDING**
- [x] `REG-001` Registration tool (DB + n8n workflow call)
- [x] `REG-002` Unregistration tool (DB + n8n workflow call)
- [ ] `RECOMMEND-001` Rich recommendation behavior – **PENDING**
- [ ] `HOTEL-001` Dedicated hotel/coordinator tool – **PENDING** (can be simple SELECT via existing workflow)

### Notifications & Engagement (Planned)
- [ ] `SCHEMA-003` `notifications` table & index
- [ ] `NOTIF-001` Insert notifications on registration
- [ ] `NOTIF-002` Update/cancel notifications on admin actions
- [ ] `NOTIF-003` pg_cron claim function + schedule
- [ ] `NOTIF-004` Worker to send notifications (n8n/Python)
- [ ] `ENGAGE-001` Daily engagement
- [ ] `FOOD-001` Food announcements
- [ ] `REMIND-001` Morning reminders
- [ ] `REMIND-002` 1-hour-before reminders

### Admin & Analytics
- [ ] `ADMIN-001` Admin verification
- [ ] `ADMIN-002` Admin event creation
- [ ] `ADMIN-003` Admin event cancellation
- [ ] `ADMIN-004` Admin event postponement
- [ ] `ADMIN-005` Targeted announcements
- [ ] `ADMIN-006` Turnup rate query wiring

### Integration & Deployment
- [ ] `WA-001` WhatsApp webhook integration (replace curl/Python CLI)
- [ ] `DEPLOY-001` Cloud DB + n8n deployment
- [ ] `OBS-001` Observability/logging

---

**Document Version**: 4.2 (Local Runtime & Registration Ready)  
**Generated**: November 25, 2025  
**Baseline**: v3.0 / v4.0 + notifications addendum  
**Current State**: Database + Local Chat+Registration Workflow COMPLETE; Notifications, Admin, WhatsApp, and Deployment PENDING.
