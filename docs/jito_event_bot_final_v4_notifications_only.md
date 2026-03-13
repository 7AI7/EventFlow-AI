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
  gmaps_link TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);
```

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
- ⏳ n8n Postgres credential configuration
- ⏳ n8n OpenAI credential configuration
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
3. ⏳ Open n8n (localhost:5678)
4. ⏳ Add Postgres credential
5. ⏳ Add OpenAI credential
6. ⏳ Build `CHAT-001` workflow
7. ⏳ Test with Manual Trigger before WhatsApp integration

---

**Document Version**: 3.0  
**Generated**: November 14, 2025, 6:09 PM IST  
**Schema Completion**: 100%  
**Workflow Completion**: 0%  
**Overall Progress**: 15%
