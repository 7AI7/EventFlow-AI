# JITO Youth 3-Day Event AI Bot - Implementation Plan

## Project Overview
**Duration**: 3-day event (Nov 20-22, 2025)  
**Scale**: 50 events, 4000 participants  
**Tech Stack**: n8n, Postgres, OpenAI gpt-4o-mini, WhatsApp Cloud API  
**Budget**: $500 approved for OpenAI + WhatsApp costs

---

## Revised Architecture (Based on Feedback)

### Key Changes
1. ✅ Removed Google Drive migration (start fresh with Postgres)
2. ✅ 2 hardcoded admin phone numbers
3. ✅ Unified hotel room queries (participants + speakers)
4. ✅ Removed pickup/drop logistics - replaced with coordinator handoff
5. ✅ Event-food location mapping for proximity recommendations
6. ✅ Admin event postpone feature
7. ✅ Real-time turnup rate tracking per event

### Out of Scope
- ❌ Pickup/drop coordination
- ❌ PDF uploads
- ❌ Post-event surveys
- ❌ Sales/payments
- ❌ Timezone handling (all IST)

---

## Database Schema (Updated)

```sql
-- Users table (pre-populated with 4000 users)
CREATE TABLE users (
  phone TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  age INT,
  email TEXT,
  hotel_name TEXT,              -- NEW: Hotel assignment
  hotel_room TEXT,              -- NEW: Room number
  created_at TIMESTAMP DEFAULT NOW()
);

-- Events table
CREATE TABLE events (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  date DATE NOT NULL,
  time TIME NOT NULL,
  location TEXT NOT NULL,       -- e.g., "ABC Hall, 1st Floor"
  gmaps_link TEXT NOT NULL,     -- Google Maps URL
  topics TEXT[] NOT NULL,
  description TEXT NOT NULL,    -- Full event description for AI
  agenda TEXT,
  contact_person TEXT,
  contact_phone TEXT,
  capacity INT DEFAULT 100,
  food_location_id INT,         -- NEW: Linked food counter
  postponed_to TIMESTAMP,       -- NEW: NULL if not postponed
  created_at TIMESTAMP DEFAULT NOW()
);

-- Registrations table
CREATE TABLE registrations (
  id SERIAL PRIMARY KEY,
  event_id INT REFERENCES events(id) ON DELETE CASCADE,
  phone TEXT REFERENCES users(phone),
  registered_at TIMESTAMP DEFAULT NOW(),
  checked_in BOOLEAN DEFAULT false,  -- NEW: For turnup tracking
  checked_in_at TIMESTAMP,           -- NEW: Timestamp of check-in
  UNIQUE(event_id, phone)
);

-- Chat history table
CREATE TABLE chat_history (
  phone TEXT PRIMARY KEY REFERENCES users(phone),
  messages JSONB NOT NULL DEFAULT '[]'::jsonb,
  updated_at TIMESTAMP DEFAULT NOW()
);

-- Food locations table (updated)
CREATE TABLE food_locations (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  location TEXT NOT NULL,
  sponsor_name TEXT,            -- NEW: Sponsor info
  hours TEXT,
  gmaps_link TEXT
);

-- Admin whitelist (hardcoded)
CREATE TABLE admins (
  phone TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Insert 2 admin phone numbers
INSERT INTO admins (phone, name) VALUES
('+919876543210', 'Admin 1'),
('+919876543211', 'Admin 2');

-- Event check-in log (for turnup rate)
CREATE TABLE event_checkins (
  id SERIAL PRIMARY KEY,
  event_id INT REFERENCES events(id),
  phone TEXT REFERENCES users(phone),
  checked_in_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_registrations_phone ON registrations(phone);
CREATE INDEX idx_registrations_event ON registrations(event_id);
CREATE INDEX idx_events_date ON events(date);
CREATE INDEX idx_events_topics ON events USING GIN(topics);
CREATE INDEX idx_chat_updated ON chat_history(updated_at);
CREATE INDEX idx_checkins_event ON event_checkins(event_id);
```

---

## Connection Pooling: Alternatives to PgBouncer

### Option 1: Native Postgres max_connections Tuning
**Method**: Increase Postgres `max_connections` directly
```ini
# postgresql.conf
max_connections = 200        # Default is 100
shared_buffers = 2GB         # 25% of RAM
work_mem = 16MB              # Per-connection work memory
```

**Pros**:
- No external service needed
- Simple configuration
- Native Postgres feature

**Cons**:
- Each connection uses ~10MB RAM → 200 conns = 2GB RAM overhead
- Context switching overhead with >100 active connections
- Doesn't solve burst queue management

**Verdict**: Use if you have 8GB+ RAM and <100 concurrent workflows

---

### Option 2: n8n Built-in Connection Pooling
**Method**: Configure n8n Postgres credential with pool settings
```javascript
// In n8n Postgres credential config
{
  "host": "localhost",
  "database": "events_db",
  "user": "postgres",
  "password": "***",
  "ssl": false,
  "connectionPool": {
    "min": 5,
    "max": 20,
    "idleTimeoutMillis": 30000
  }
}
```

**Pros**:
- Built into n8n, no extra service
- Automatic connection reuse
- Per-credential pool (isolate admin vs user queries)

**Cons**:
- Limited to 20 connections per credential (n8n default)
- No cross-workflow pool sharing
- Can't tune queue behavior (FIFO vs priority)

**Verdict**: **Use this for MVP** - simplest option, good enough for 4000 users

---

### Option 3: Redis as Last Resort
**When to use**: Only if n8n pooling causes >2s latency during burst

**Setup**: Cache event catalog in Redis
```python
# Cache events for 5 minutes
redis.setex('events_catalog', 300, json.dumps(events_list))

# n8n workflow checks cache first
cached = redis.get('events_catalog')
if cached:
    return json.loads(cached)
else:
    events = postgres.query("SELECT * FROM events")
    redis.setex('events_catalog', 300, json.dumps(events))
    return events
```

**Pros**:
- Offloads 80% of reads from Postgres
- Sub-1ms response time for cached data

**Cons**:
- Another service to manage
- Cache invalidation complexity (admin creates event → must bust cache)

**Verdict**: Skip for Phase 1; add only if latency monitoring shows >1s P95

---

## Recommended Approach
**Phase 1**: Use n8n native pooling (max=20) + Postgres max_connections=100  
**If problems arise**: Increase Postgres max_connections to 200  
**Last resort**: Add Redis caching layer

---

## Updated Task Breakdown

### GROUP A: FOUNDATION [Priority: P0]

#### [A1-INFRA] Deploy Core Infrastructure
**Tag**: `INFRA-001`  
**Dependencies**: None  
**Tasks**:
- Deploy Postgres (Supabase or Docker: `docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=*** postgres:15`)
- Deploy n8n (`docker run -d -p 5678:5678 n8nio/n8n`)
- Configure WhatsApp Cloud API (get phone_number_id + permanent token)
- Configure n8n credentials:
  - Postgres with connection pool: `{"max": 20, "min": 5}`
  - WhatsApp Cloud API
  - OpenAI API key

**Acceptance Criteria**:
- n8n accessible at `http://localhost:5678`
- Postgres accepts connections
- WhatsApp webhook verified
- Test OpenAI call succeeds

**Time**: 2-3 hours

---

#### [A2-SCHEMA] Create Database Schema
**Tag**: `SCHEMA-001`  
**Dependencies**: `INFRA-001`  
**Tasks**:
- Run updated schema SQL (includes hotel fields, postponed_to, food_location_id)
- Insert 2 admin phone numbers into `admins` table
- Insert 50 sample events with gmaps_link, food_location_id
- Insert 7-8 food locations with sponsor info

**Sample Data**:
```sql
-- Events with food mapping
INSERT INTO events (name, date, time, location, gmaps_link, topics, description, food_location_id, capacity) VALUES
('Book Club', '2025-11-20', '18:00', 'ABC Hall, 1st Floor', 
 'https://maps.google.com/?q=19.0760,72.8777', 
 ARRAY['Books', 'Thriller'], 
 'Deep dive into thriller novels. Discuss Agatha Christie, Gillian Flynn. Interactive Q&A with author.', 
 1, 100),
('AI Summit', '2025-11-22', '10:00', 'Tech Center, Ground Floor', 
 'https://maps.google.com/?q=19.0761,72.8778', 
 ARRAY['AI', 'LLM', 'Machine Learning'], 
 'Hands-on LLM workshop. Build chatbot with OpenAI API. Fine-tuning demos.', 
 2, 150);

-- Food locations with sponsors
INSERT INTO food_locations (name, location, sponsor_name, hours, gmaps_link) VALUES
('Main Cafeteria', 'Building A, Ground Floor', 'Sponsor Corp', '11 AM - 8 PM', 'https://maps.google.com/?q=19.0762,72.8779'),
('Rooftop Lounge', 'Building B, 5th Floor', 'Tech Sponsors Inc', '12 PM - 10 PM', 'https://maps.google.com/?q=19.0763,72.8780');
```

**Time**: 1 hour

---

### GROUP B: PARTICIPANT EXPERIENCE [Priority: P0]

#### [B1-CHAT] Chat Context Management
**Tag**: `CHAT-001`  
**Dependencies**: `SCHEMA-001`  
**Description**: Handle user initiation ("Hi") and load/save context

**n8n Workflow: "WhatsApp Message Handler"**
```
Trigger: Webhook (WhatsApp POST)

Nodes:
1. Function: Extract phone and message
   phone = $json.entry[0].changes[0].value.contacts[0].wa_id
   text = $json.entry[0].changes[0].value.messages[0].text.body

2. Postgres Query: Load user + chat history
   SELECT u.name, u.hotel_room, u.hotel_name, 
          ch.messages
   FROM users u
   LEFT JOIN chat_history ch ON u.phone = ch.phone
   WHERE u.phone = :phone

3. Function: Build conversation array
   history = existing_messages || []

   # Handle first-time user (says "Hi")
   if history.length == 0:
     greeting = f"Hi {user.name}! 👋 Welcome to JITO Youth Event. I'm here to help with event recommendations, registration, and logistics. What can I help you with?"
     history.push({role: 'assistant', content: greeting})
     # Save greeting, return it, skip AI call

   history.push({role: 'user', content: text})

4. AI Agent Node (skip if greeting returned above)
5. Function: Append AI reply to history
6. Postgres Upsert: Save updated history
   INSERT INTO chat_history (phone, messages, updated_at)
   VALUES (:phone, :history::jsonb, NOW())
   ON CONFLICT (phone) DO UPDATE SET messages = :history::jsonb
7. WhatsApp Send: Reply to user
```

**First-time User Flow**:
- User: "Hi"
- Bot: "Hi Rahul! 👋 Welcome to JITO Youth Event. I'm here to help with event recommendations, registration, and logistics. What can I help you with?"
- User: "I love AI"
- Bot: [AI processes recommendation...]

**Time**: 2 hours

---

#### [B2-AI] AI Agent Configuration
**Tag**: `AI-001`  
**Dependencies**: `CHAT-001`  
**Updated System Prompt**:
```
You are a friendly WhatsApp AI assistant for JITO Youth's 3-day event (Nov 20-22, 2025).

ROLE:
- Recommend events by reading full event descriptions and matching user interests
- Register users for events (capacity check included)
- Answer hotel room queries for participants and speakers
- Provide event location with Google Maps link after registration
- Share food counter locations with sponsor info
- Redirect logistics queries to coordinator

CAPABILITIES:
- fetch_events_detailed(interest: string) → Returns events with full description for smart matching
- register_user(event_id: int, phone: string) → Registers and returns location + gmaps_link
- get_user_hotel(phone: string) → Returns hotel name + room number
- get_food_location(event_id: int) → Returns nearest food counter with sponsor
- check_admin(phone: string) → Verifies if user is admin (for admin commands)

RULES:
1. Read full event.description when recommending (not just topics)
2. For "Where is my room?": fetch from users table, return hotel + room
3. For "I want to go to my room": Reply "Please wait near the logistics area. Coordinator: {coordinator_phone}"
4. After registration: Auto-share event location + Google Maps link
5. Block off-topic queries: "I'm here for event assistance only!"
6. Tone: Friendly, 1-2 emojis, concise (<100 words)

COORDINATOR INFO:
Phone: +919876543299
Name: Logistics Team
```

**AI Model Config**:
- Model: `gpt-4o-mini`
- Temperature: 0.7
- Max tokens: 200
- Memory: Window buffer (last 10 messages)

**Time**: 1 hour

---

#### [B3-REG] Event Registration with Auto-Location Share
**Tag**: `REG-001`  
**Dependencies**: `AI-001`, `SCHEMA-001`  
**n8n Sub-Workflow: "Register User Tool"**
```
Input: event_id, phone (from AI)

Nodes:
1. Postgres: Check capacity
   SELECT e.*, 
          (SELECT COUNT(*) FROM registrations WHERE event_id = :event_id) as current
   FROM events e
   WHERE e.id = :event_id

2. IF current < capacity:
   → Postgres Insert:
     INSERT INTO registrations (event_id, phone)
     VALUES (:event_id, :phone)
     ON CONFLICT DO NOTHING

   → Fetch event details:
     SELECT name, location, gmaps_link, time, date, food_location_id
     FROM events WHERE id = :event_id

   → Fetch food location:
     SELECT f.name, f.location, f.sponsor_name, f.gmaps_link
     FROM food_locations f WHERE f.id = :food_location_id

   → Return JSON:
     {
       "success": true,
       "message": "Registered for {event.name}!",
       "location": "{event.location}",
       "gmaps_link": "{event.gmaps_link}",
       "time": "{event.date} at {event.time}",
       "food_counter": "{food.name} - {food.location} (Sponsored by {food.sponsor_name})",
       "food_map": "{food.gmaps_link}"
     }

3. ELSE:
   → Return: {"success": false, "message": "Event is full"}
```

**AI formats response**:
```
✅ You're registered for AI Summit!

📍 Location: Tech Center, Ground Floor
🗺️ Map: https://maps.google.com/?q=...
🕐 Time: Nov 22, 10 AM

🍽️ Nearest Food: Main Cafeteria - Building A (Sponsored by Sponsor Corp)
🗺️ Food Map: https://maps.google.com/?q=...

See you there! 🎉
```

**Time**: 2.5 hours

---

#### [B4-RECOMMEND] Detailed Event Search
**Tag**: `RECOMMEND-001`  
**Dependencies**: `AI-001`  
**n8n Sub-Workflow: "Fetch Events Tool"**
```
Input: interest (string, e.g., "artificial intelligence and coding")

Nodes:
1. Postgres: Fetch ALL events with full descriptions
   SELECT id, name, date, time, location, topics, description, capacity,
          (SELECT COUNT(*) FROM registrations WHERE event_id = events.id) as registered
   FROM events
   WHERE postponed_to IS NULL  -- Exclude postponed events
   ORDER BY date, time

2. Return to AI: Full event list with descriptions
   AI will read descriptions and match semantically to user interest
```

**AI Smart Matching Example**:
- User: "I'm into machine learning and neural networks"
- AI reads: Event ID 5 description = "Deep dive into neural network architectures. CNNs, RNNs, transformers explained."
- AI recommends Event 5 even though topics array is just `["AI", "ML"]`

**Time**: 1.5 hours

---

#### [B5-HOTEL] Hotel Room Query
**Tag**: `HOTEL-001`  
**Dependencies**: `SCHEMA-001`  
**n8n Sub-Workflow: "Get Hotel Info Tool"**
```
Input: phone

Nodes:
1. Postgres Query:
   SELECT hotel_name, hotel_room, name
   FROM users
   WHERE phone = :phone

2. IF hotel_room IS NULL:
   → Return: "No hotel assigned yet. Contact admin."

3. ELSE:
   → Return: {
       "name": "{name}",
       "hotel": "{hotel_name}",
       "room": "{hotel_room}"
     }
```

**AI Response**:
```
🏨 Your hotel: Grand Plaza
🚪 Room: 305
Need directions? Reply "directions to hotel"
```

**Time**: 1 hour

---

### GROUP C: ADMIN OPERATIONS [Priority: P1]

#### [C1-ADMIN-AUTH] Admin Verification
**Tag**: `ADMIN-001`  
**Dependencies**: `SCHEMA-001`  
**n8n Function Node: "Check If Admin"**
```javascript
const phone = $input.item.json.phone;
const adminQuery = await $query(`
  SELECT phone FROM admins WHERE phone = '${phone}'
`);

if (adminQuery.length === 0) {
  return {
    isAdmin: false,
    message: "⛔ Admin access required"
  };
}
return {isAdmin: true};
```

**Usage**: All admin workflows start with this check

**Time**: 30 minutes

---

#### [C2-ADMIN-CREATE] Event Creation
**Tag**: `ADMIN-002`  
**Dependencies**: `ADMIN-001`  
**Admin Message Format**:
```
Create event:
Name: Blockchain Workshop
Date: Nov 21
Time: 2 PM
Location: Hall C, 2nd Floor
Map: https://maps.google.com/?q=19.0764,72.8781
Topics: Blockchain, Crypto, Web3
Description: Hands-on smart contract development. Deploy on Ethereum testnet. Expert Q&A.
Food: Main Cafeteria
Contact: Priya +919876543211
Capacity: 80
```

**n8n Workflow**:
```
1. Admin Auth Check
2. AI Structured Extraction (schema with all fields)
3. Postgres: Lookup food_location_id by name
4. Postgres Insert event
5. WhatsApp Confirm: "✅ Event created: {name} (ID: {id})"
```

**Time**: 2 hours

---

#### [C3-ADMIN-DELETE] Event Deletion
**Tag**: `ADMIN-003`  
**Dependencies**: `ADMIN-001`, `REG-001`  
**Admin Command**: "Delete event: Book Club"

**Workflow**:
```
1. Admin Auth
2. Postgres: Fetch event + registered users
3. WhatsApp to Admin: "⚠️ Delete {name}? {count} users. Reply YES"
4. Wait for YES
5. Postgres: DELETE FROM events WHERE id = :id (CASCADE removes registrations)
6. Loop: Notify each user
7. Admin Confirm: "Event deleted, {count} notified"
```

**Time**: 2 hours

---

#### [C4-ADMIN-POSTPONE] Event Postponement
**Tag**: `ADMIN-004`  
**Dependencies**: `ADMIN-001`  
**Admin Command**: "Postpone Book Club to Nov 21 6 PM"

**Workflow**:
```
1. Admin Auth
2. AI Extract: event_name, new_date, new_time
3. Postgres Update:
   UPDATE events 
   SET postponed_to = :new_datetime, date = :new_date, time = :new_time
   WHERE name ILIKE :event_name
4. Postgres: Get registered users
5. Loop: WhatsApp notify
   "⏰ {event_name} has been rescheduled to {new_date} at {new_time}. 
    Location remains: {location}. See you there!"
6. Admin Confirm
```

**Time**: 2 hours

---

#### [C5-ADMIN-ANNOUNCE] Targeted Broadcast
**Tag**: `ADMIN-005`  
**Dependencies**: `ADMIN-001`  
**Admin Command**: "Announce to AI Summit: Lunch break extended 30 mins"

**Workflow**:
```
1. Admin Auth
2. AI Parse: audience (all/event/speakers), message
3. Postgres Query (dynamic):
   - all: SELECT phone FROM users
   - event: SELECT phone FROM registrations r JOIN events e ... WHERE e.name ILIKE :name
4. Loop: WhatsApp send (rate limit: 10/sec)
5. Admin Confirm: "📢 Sent to {count} users"
```

**Time**: 2 hours

---

#### [C6-ADMIN-TURNUP] Real-Time Turnup Rate
**Tag**: `ADMIN-006`  
**Dependencies**: `SCHEMA-001`  
**Admin Query**: "Turnup rate for AI Summit"

**Workflow**:
```
1. Admin Auth
2. AI Extract: event_name
3. Postgres Query:
   SELECT e.name, e.capacity,
          COUNT(DISTINCT r.phone) as registered,
          COUNT(DISTINCT ec.phone) as checked_in,
          ROUND(100.0 * COUNT(DISTINCT ec.phone) / COUNT(DISTINCT r.phone), 1) as turnup_rate
   FROM events e
   LEFT JOIN registrations r ON e.id = r.event_id
   LEFT JOIN event_checkins ec ON e.id = ec.event_id
   WHERE e.name ILIKE :event_name
   GROUP BY e.id

4. WhatsApp to Admin:
   "📊 AI Summit Turnup:
   Registered: {registered}
   Checked In: {checked_in}
   Rate: {turnup_rate}%
   Capacity: {capacity}"
```

**Check-in Mechanism** (separate workflow):
```
# QR code scanner at event entrance logs check-in
INSERT INTO event_checkins (event_id, phone)
VALUES (:event_id, :phone)
ON CONFLICT DO NOTHING
```

**Time**: 2 hours

---

### GROUP D: ENGAGEMENT AUTOMATION [Priority: P2]

#### [D1-ENGAGE] Daily Themed Messages
**Tag**: `ENGAGE-001`  
**Dependencies**: `REG-001`, `AI-001`  
**Trigger**: Schedule - Daily 9 AM IST

**Workflow**:
```
1. Postgres: Users with events 1-3 days away
   SELECT DISTINCT u.phone, u.name, e.name, e.description, e.date
   FROM users u
   JOIN registrations r ON u.phone = r.phone
   JOIN events e ON r.event_id = e.id
   WHERE e.date BETWEEN CURRENT_DATE + 1 AND CURRENT_DATE + 3

2. Loop: For each user
   a. OpenAI Generate:
      Prompt: "Based on event: {e.name} - {e.description}, 
               write a 2-sentence exciting fact or case study. 
               Keep it engaging and relevant."

   b. WhatsApp Send:
      "Good morning {name}! 🌅
      {generated_content}

      Can't wait to see you at {event_name} on {date}! 🎉"

3. Rate Limit: 10 msgs/sec
```

**Time**: 3 hours

---

#### [D2-FOOD] Food Counter Announcements
**Tag**: `FOOD-001`  
**Dependencies**: `REG-001`, `SCHEMA-001`  
**Triggers**: 
- 11:30 AM (lunch)
- 3:00 PM (snacks)
- 6:30 PM (dinner)

**Workflow**:
```
1. Postgres: Get current/upcoming events
   SELECT DISTINCT e.id, e.food_location_id
   FROM events e
   WHERE e.date = CURRENT_DATE
     AND e.time BETWEEN NOW() - INTERVAL '30 minutes' 
                    AND NOW() + INTERVAL '1 hour'

2. Postgres: Get food locations + attendees
   SELECT DISTINCT u.phone, f.name, f.location, f.sponsor_name, f.gmaps_link
   FROM users u
   JOIN registrations r ON u.phone = r.phone
   JOIN events e ON r.event_id = e.id
   JOIN food_locations f ON e.food_location_id = f.id
   WHERE e.id IN (:current_event_ids)

3. Loop: WhatsApp Send
   "🍽️ {meal} is ready!
   📍 {food.name} - {food.location}
   💼 Sponsored by {sponsor_name}
   🗺️ Map: {gmaps_link}

   Enjoy! 😊"
```

**Time**: 2 hours

---

#### [D3-REMIND] Morning Event Reminder
**Tag**: `REMIND-001`  
**Dependencies**: `REG-001`  
**Trigger**: Daily 9 AM

**Workflow**:
```
1. Postgres: Today's events + attendees
   SELECT u.phone, u.name, e.name, e.time, e.location, e.gmaps_link, 
          e.agenda, e.contact_person, e.contact_phone
   FROM users u
   JOIN registrations r ON u.phone = r.phone
   JOIN events e ON r.event_id = e.id
   WHERE e.date = CURRENT_DATE

2. Loop: WhatsApp Send
   "Good morning {name}! 🌅

   📅 {event_name} today at {time}
   📍 {location}
   🗺️ Map: {gmaps_link}
   📋 Agenda: {agenda}
   📞 Contact: {contact_person} ({contact_phone})

   See you there! 🎉"
```

**Time**: 1.5 hours

---

## Monitoring & Alerts (Added per feedback)

### [M1-MONITOR] Execution Monitoring
**Tag**: `MONITOR-001`  
**n8n Workflow: "Daily Health Check"**
```
Trigger: Schedule - Every 4 hours

Nodes:
1. Postgres Queries:
   - Total registrations today
   - Failed workflow executions (n8n logs)
   - WhatsApp send failures

2. IF failures > 10 OR registrations < expected:
   → WhatsApp to Admins:
     "⚠️ System alert:
     Registrations: {count}
     Failed workflows: {failures}
     Check n8n immediately."
```

**Time**: 2 hours

---

### [M2-RETRY] OpenAI Retry Logic
**Tag**: `RETRY-001`  
**n8n Error Trigger**:
```
1. On AI Agent node error (timeout, 503, rate limit):
   → Wait 5 seconds
   → Retry (max 3 attempts)
   → If all fail:
     - Log to Postgres error_log table
     - Send fallback response: "I'm having trouble. Please try again in 1 minute."
```

**Time**: 1.5 hours

---

## Updated Task Checklist

### Sprint 1: Foundation (Days 1-2)
- [ ] `INFRA-001` Deploy Postgres + n8n + WhatsApp API
- [ ] `SCHEMA-001` Create updated schema (hotel fields, postponed_to, food mapping)
- [ ] `CHAT-001` Chat context + first-time user greeting
- [ ] `AI-001` Configure AI Agent with updated prompt

### Sprint 2: Core Features (Days 3-4)
- [ ] `RECOMMEND-001` Detailed event search with description matching
- [ ] `REG-001` Registration + auto-location share
- [ ] `HOTEL-001` Hotel room query tool
- [ ] Test: User registers and gets location + food info

### Sprint 3: Admin Tools (Days 5-7)
- [ ] `ADMIN-001` Admin phone verification
- [ ] `ADMIN-002` Event creation
- [ ] `ADMIN-003` Event deletion + notifications
- [ ] `ADMIN-004` Event postponement
- [ ] `ADMIN-005` Targeted announcements
- [ ] `ADMIN-006` Real-time turnup rate tracking

### Sprint 4: Engagement (Days 8-9)
- [ ] `ENGAGE-001` Daily themed content
- [ ] `FOOD-001` Food counter broadcasts
- [ ] `REMIND-001` Morning reminders

### Sprint 5: Reliability (Day 10)
- [ ] `MONITOR-001` Health check alerts
- [ ] `RETRY-001` OpenAI retry logic
- [ ] Load test with 100 concurrent users

### Sprint 6: Deploy (Days 11-12)
- [ ] Production deployment
- [ ] Admin training
- [ ] Go-live monitoring

---

## Critical Path
```
INFRA-001 → SCHEMA-001 → CHAT-001 → AI-001 
    ↓
┌───┴────┬──────────────────┬────────────────┐
│        │                  │                │
RECOMMEND REG-001   ADMIN-001(Auth)    ENGAGE-001
          ↓                 ↓                ↓
       HOTEL-001    ADMIN-002 thru 006   FOOD-001
                                          REMIND-001
```

**Team**: 1-2 developers  
**Timeline**: 10-12 days to production-ready

---

## Cost Estimate (Updated)

### OpenAI (gpt-4o-mini)
- Chat: 4000 users × 5 msgs × 3 days × 650 tokens avg = 39M tokens = **$9**
- Recommendations (full descriptions): 4000 × 3 queries × 1200 tokens = 14.4M tokens = **$3**
- Engagement content: 4000 × 3 days × 150 tokens = 1.8M tokens = **$0.50**
- **Total OpenAI: ~$12.50**

### WhatsApp Cloud API
- Conversations: 4000 users × 5 convos × $0.01 = **$200**
- Broadcasts (engagement + reminders): 20K sends × $0.01 = **$200**
- **Total WhatsApp: ~$400**

### Infrastructure
- n8n self-hosted: $0 (Docker on existing VPS)
- Postgres: $0 (Docker or Supabase free tier)

**Grand Total: $412.50 for 3-day event**

---

## Risk Mitigation

### High-Priority Risks
1. **WhatsApp Rate Limits**: Pre-verify phone number to Tier 3 (10K/day) 2 weeks before event
2. **Burst Traffic**: Enable n8n queue mode if >100 concurrent users expected
3. **OpenAI Downtime**: Implement 3-retry logic + fallback responses
4. **Database Connection Exhaustion**: Monitor Postgres active connections; increase max_connections if >80% utilization

### Medium-Priority Risks
1. **Admin Mistakes**: Implement confirmation prompts for delete/postpone
2. **Long Chat Contexts**: Implement summarization after 20 messages
3. **Food Counter Mapping Errors**: Validate food_location_id exists during event creation

### Low-Priority Risks
1. **Duplicate Registrations**: Handled by UNIQUE constraint
2. **Timezone Issues**: Not applicable (all IST)

---

## Success Metrics

### Functional
- ✅ 4000 users successfully register for events
- ✅ <5% registration failures due to technical issues
- ✅ Admins can create/delete/postpone events without developer help

### Performance
- ✅ 95th percentile chat latency <1 second
- ✅ Event recommendations returned in <2 seconds
- ✅ Broadcasts complete within 10 minutes (6.7 msgs/sec)

### User Experience
- ✅ <1% off-topic queries (good AI guardrails)
- ✅ Hotel room queries answered correctly 100% of time
- ✅ Food location recommendations accurate (linked to event)

---

## Deployment Checklist

### Pre-Event (2 weeks before)
- [ ] WhatsApp phone number verified to Tier 3
- [ ] All 50 events loaded with gmaps_link + food mapping
- [ ] 4000 users imported with hotel assignments
- [ ] 2 admin phone numbers configured
- [ ] Load test with 200 concurrent simulated users

### Event Week
- [ ] Daily execution monitoring enabled
- [ ] Admin training completed (event creation, postpone, turnup rate)
- [ ] On-call developer assigned for 3 days
- [ ] Backup admin phone numbers added

### During Event
- [ ] Monitor n8n dashboard every 2 hours
- [ ] Check Postgres connection pool utilization
- [ ] Respond to admin queries within 10 minutes
- [ ] Log any bugs for post-event retrospective

---

## Next Steps

1. **Approve this plan** or provide feedback
2. **Start Sprint 1**: Deploy infrastructure + schema
3. **Daily standups**: 15-min sync on progress/blockers
4. **Demo at end of Sprint 2**: Show working registration flow to stakeholders

---

## Appendix: Sample Conversations

### Scenario 1: First-Time Participant
**User**: Hi  
**Bot**: Hi Rahul! 👋 Welcome to JITO Youth Event. I'm here to help with event recommendations, registration, and logistics. What can I help you with?

**User**: I'm into AI and machine learning  
**Bot**: Perfect! I recommend the **AI Summit** on Nov 22 at 10 AM. It's a hands-on workshop where you'll build chatbots with OpenAI API and see fine-tuning demos. Want to register?

**User**: Yes  
**Bot**: ✅ You're registered for AI Summit!

📍 Location: Tech Center, Ground Floor  
🗺️ Map: https://maps.google.com/?q=...  
🕐 Time: Nov 22, 10 AM

🍽️ Nearest Food: Main Cafeteria - Building A (Sponsored by Sponsor Corp)  
🗺️ Food Map: https://maps.google.com/?q=...

See you there! 🎉

---

### Scenario 2: Hotel Query
**User**: Where is my room?  
**Bot**: 🏨 Your hotel: Grand Plaza  
🚪 Room: 305  
Need directions? Reply "directions to hotel"

---

### Scenario 3: Logistics Handoff
**User**: I want to go to my room  
**Bot**: Please wait near the logistics area. Our coordinator will assist you!  
📞 Logistics Team: +919876543299

---

### Scenario 4: Admin Event Postponement
**Admin**: Postpone Book Club to Nov 21 7 PM  
**Bot**: ⚠️ Postpone Book Club from Nov 20 6 PM to Nov 21 7 PM? 85 users registered. Reply YES to confirm.

**Admin**: YES  
**Bot**: ✅ Event postponed. Notifying 85 users...  
📢 Notifications sent.

---

### Scenario 5: Admin Turnup Rate
**Admin**: Turnup rate for AI Summit  
**Bot**: 📊 AI Summit Turnup:  
Registered: 150  
Checked In: 87  
Rate: 58.0%  
Capacity: 150

---

**END OF DOCUMENT**

Generated: November 12, 2025  
Version: 2.0 (Updated based on client feedback)
