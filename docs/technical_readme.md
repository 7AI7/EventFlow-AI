# JITO Youth Event Bot – README

_Last updated: 26 Nov 2025_  
_Based on: `jito_event_bot_final_v4_2_runtime_ready.md` + earlier implementation plans and notifications addendum_ [attached_file:76][attached_file:74][attached_file:73]

---

## 1. Project Overview

This repository contains the local runtime implementation of the **JITO Youth 3‑Day Event AI Bot**, which assists ~4,000 participants across ~50 events over three days with discovery, registration, hotel/logistics queries, and engagement messages. [attached_file:74]  
The stack is **PostgreSQL** for data, **n8n 1.119.1** for orchestration, **OpenAI gpt‑4o‑mini** for reasoning, and **WhatsApp Cloud API** (planned) for messaging transport. [attached_file:76][attached_file:74]  

The current local state as of v4.2 is: core database schema and constraints are complete; chat + registration + unregistration flows are wired from n8n into Postgres functions; notifications, admin tools, WhatsApp integration, and cloud deployment are specified but not yet implemented. [attached_file:76]

---

## 2. High‑Level Architecture

### 2.1 Components

- **Database layer (PostgreSQL, DB name `jitoevents`)**  
  - Base tables: `users`, `events`, `food_locations`, `registrations`, `admins`, `chat_history`. [attached_file:76]  
  - Derived views: `v_events_public`, `v_my_profile`, `v_my_registrations`, `v_food_public` for participant‑safe access. [attached_file:76]  
  - Business‑logic functions: `register_for_event(phone, event_id)` and `unregister_from_event(phone, event_id)` returning structured JSON with `success` and `error_code`. [attached_file:76]  
  - Constraints and trigger: `check_event_capacity` trigger on `registrations` to enforce capacity; `chk_checkin_consistency` on `registrations`; FK from `events.food_location_id` to `food_locations.id`. [attached_file:76]

- **Orchestration layer (n8n)**  
  - **WF‑001 – Local Chat + Registration Workflow**: Handles inbound chat, loads user + chat context from DB, builds AI prompt, calls OpenAI, parses `reply_text`/`action`, and routes to registration/unregistration DB tools. [attached_file:76]  
  - Future workflows: admin event creation/deletion/postponement, targeted announcements, reminders and engagement are specified as tasks but not wired yet. [attached_file:76][attached_file:75][attached_file:73]

- **AI layer (OpenAI)**  
  - AI agent runs with a system prompt that constrains behavior: event discovery > probing > recommendation > registration/unregistration, using only DB‑backed data and returning JSON with `reply_text` and `action { type, event_id }`. [attached_file:76]  
  - AI currently uses chat context from `chat_history` (summary + recent messages) and participant profile from `users`/views; event and registration details are always fetched through SQL tools or views/functions, never fabricated. [attached_file:76]

- **Notifications and worker model (planned)**  
  - A dedicated `notifications` table acts as an outbox for reminders, hype messages, and food announcements; separate worker (n8n or Python) sends WhatsApp messages based on `notifications.status` and `scheduled_at`. [attached_file:73][attached_file:76]  
  - Design explicitly avoids direct “send now” cron queries in n8n; all automation writes notification rows and a generic worker handles delivery. [attached_file:73]

### 2.2 Data‑flow Summary

- **Participant chat**: WhatsApp → webhook into n8n → WF‑001 loads `users` + `chat_history` → AI decides response and optional action → WF‑001 conditionally calls `register_for_event` / `unregister_from_event` → response sent back to WhatsApp → `chat_history` updated. [attached_file:76]  
- **Registration**: AI never inserts directly; it calls the `register_for_event` SQL function, which checks event status, capacity, uniqueness, and food mapping, then returns JSON for the bot to present. [attached_file:76]  
- **Unregistration**: AI calls `unregister_from_event`, which enforces a 30‑minute cutoff and distinguishes `NOT_REGISTERED` vs `EVENT_NOT_FOUND` vs `TOO_LATE_TO_CANCEL`. [attached_file:76]  
- **Engagement and reminders** (future): registration flows will add rows into `notifications` (templates like `MORNING_REMINDER`, `ONE_HOUR_BEFORE`, `FOOD_ANNOUNCEMENT`, `HYPE`); worker jobs claim due rows and send via WhatsApp. [attached_file:73][attached_file:76]

---

## 3. Database Design

### 3.1 Core Tables

- **`users`** – participant master  
  - Columns: `phone` (PK), `name`, `age`, `email`, `hotel_name`, `hotel_room`, `hotel_gmaps_link`, `coordinator_name`, `coordinator_phone`, `created_at`. [attached_file:76][attached_file:75]  
  - Design: hotel/coordinator fields are nullable (locals have no hotel; out‑of‑city users have an assigned hotel and coordinator); this keeps logistics data in a single table without separate coordinator entities. [attached_file:76]

- **`events`** – event catalog  
  - Columns: `id` (PK), `name`, `date`, `time`, `location`, `gmaps_link`, `description`, optional `agenda`, `contact_person`, `contact_phone`, `capacity`, `food_location_id`, `postponed_to`, `cancelled`, `created_at`. [attached_file:76][attached_file:75]  
  - Indices: `idx_events_date`, `idx_events_cancelled` (partial on `cancelled = false`), `idx_events_date_time`, `idx_events_description_fts` (full‑text search on description/name). [attached_file:72][attached_file:76]  
  - Design choices:  
    - No `topics` array; AI is expected to read `description` semantically. [attached_file:76]  
    - `cancelled` and `postponed_to` support admin actions while preserving history. [attached_file:76]

- **`food_locations`** – counters and sponsors  
  - Columns: `id` (PK), `name`, `location`, `sponsor_name`, `hours`, `created_at`. [attached_file:76]  
  - Note: earlier drafts had `gmaps_link` here; v4.2 explicitly documents that this column is **not** present in the current schema. [attached_file:76]

- **`registrations`** – event sign‑ups and check‑ins  
  - Columns: `id` (PK), `event_id` (FK → `events.id`), `phone` (FK → `users.phone`), `registered_at`, `checked_in`, `checked_in_at`. [attached_file:76]  
  - Constraints:  
    - `UNIQUE(event_id, phone)` prevents duplicate registrations. [attached_file:76]  
    - `chk_checkin_consistency` enforces `checked_in` ↔ `checked_in_at` consistency. [attached_file:76]  
  - Trigger: `enforce_capacity` (via `check_event_capacity`) rejects inserts when `COUNT(registrations) >= events.capacity`. [attached_file:76]  
  - Indices: per‑phone, per‑event, and partial on `checked_in = false` for efficient turn‑up calculations. [attached_file:72]

- **`admins`** – admin whitelist  
  - Columns: `phone` (PK), `name`, `created_at`. [attached_file:76]  
  - Purpose: all admin operations (create/delete/postpone/broadcast/turn‑up query) must first pass an admin‑check function or query against this table. [attached_file:75]

- **`chat_history`** – compressed chat context  
  - Columns: `phone` (PK, FK → `users.phone`), `summary`, `recent_messages` (JSONB), `updated_at`. [attached_file:76]  
  - Indices: `idx_chat_updated` on `updated_at` to help batch processing later. [attached_file:76]  
  - Pattern: hybrid context – a running `summary` plus a bounded window (`recent_messages`, typically last 3–10 turns) to keep token costs under control. [attached_file:76]

- **`notifications`** (planned and partly present in DB)  
  - Table exists with PK + `idx_notifications_due`; v4.2 marks the broader notification pipeline (NOTIF‑001..004) as planned rather than fully implemented. [attached_file:72][attached_file:73]  
  - Intended columns (from notifications addendum): template name, phone, event_id, payload JSON, `scheduled_at`, `status` (e.g., `PENDING`, `CLAIMED`, `SENT`, `FAILED`), timestamps for sending. [attached_file:73]

### 3.2 Participant‑Safe Views

- **`v_events_public`**  
  - Exposes `id`, `name`, `date`, `time`, `location`, `gmaps_link`, `description` for non‑cancelled events. [attached_file:76]  
  - Hides `capacity`, admin contacts, cancellation flags, and metadata; used for event discovery and recommendations. [attached_file:76]

- **`v_my_profile`**  
  - Exposes `phone`, `name`, `hotel_name`, `hotel_room`, `hotel_gmaps_link`, `coordinator_name`, `coordinator_phone`. [attached_file:76]  
  - Used to answer “Where is my room?” and “Who is my coordinator?” without exposing age/email. [attached_file:76]

- **`v_my_registrations`**  
  - Exposes each user’s `event_id`, `event_name`, `date`, `time`, `location`, `gmaps_link`, plus timestamps. [attached_file:76]  
  - Backed by RLS so that a participant only sees their own rows. [attached_file:76]

- **`v_food_public`**  
  - Exposes food location details (name, location, sponsor, hours) without internal IDs. [attached_file:76]

### 3.3 Business Functions

- **`check_event_capacity()` trigger function**  
  - On `registrations` `BEFORE INSERT`, counts existing registrations for the event and compares to `events.capacity`; raises exception if full to prevent overbooking. [attached_file:76]

- **`register_for_event(pphone TEXT, pevent_id INT) RETURNS JSON`**  
  - Logic:  
    1. Load event by `id` where `cancelled = false`; if not found, return `{"success": false, "error_code": "EVENT_NOT_FOUND"}`. [attached_file:76]  
    2. Attempt `INSERT` into `registrations`; if trigger raises, return `{"success": false, "error_code": "EVENT_FULL"}`. [attached_file:76]  
    3. If `ON CONFLICT` prevented insert, return `{"success": false, "error_code": "ALREADY_REGISTERED"}`. [attached_file:76]  
    4. Fetch `food_locations` row for `events.food_location_id`. [attached_file:76]  
    5. Return `{"success": true, "event_name": ..., "location": ..., "gmaps_link": ..., "date": ..., "time": ..., "food_name": ..., "food_location": ..., "sponsor": ...}` as JSON. [attached_file:76]  
  - Downstream: n8n registration workflow and AI layer interpret this JSON to craft user messages and avoid duplicating capacity logic in code. [attached_file:76]

- **`unregister_from_event(pphone TEXT, pevent_id INT) RETURNS JSON`**  
  - Logic:  
    1. Load event date/time + name; if missing, return `EVENT_NOT_FOUND`. [attached_file:76]  
    2. Compute `minutes_until_start`; if within 30 minutes, return `TOO_LATE_TO_CANCEL` with cutoff and remaining minutes. [attached_file:76]  
    3. Delete from `registrations` and inspect `ROWCOUNT`; if 0, return `NOT_REGISTERED`. [attached_file:76]  
    4. Otherwise return `{"success": true, "event_name": ...}`. [attached_file:76]  

### 3.4 Security & RLS

- **RLS policies** and an `event_bot_admin_role` are configured so that:  
  - Participant‑facing workflows primarily read from views (`v_events_public`, `v_my_profile`, `v_my_registrations`, `v_food_public`). [attached_file:76]  
  - Direct table access is restricted; admin workflows run under an elevated role when required. [attached_file:76]

---

## 4. n8n Workflows and Pipelines

### 4.1 WF‑001 – Local Chat + Registration Workflow

This is the main runtime workflow currently implemented and tested locally. [attached_file:76]

**Node sequence (conceptual):**

1. **Webhook – `chat-local`**  
   - Input: WhatsApp payload with `phone` and `message` extracted upstream (or by a small Function node). [attached_file:76]

2. **Load User & Chat (Postgres)**  
   - Query: joins `users` and `chat_history` to fetch `name`, coordinator info, `summary`, `recent_messages`, plus the incoming message text. [attached_file:76]  
   - Purpose: provide AI with minimal stable context but not full DB dumps.

3. **Build LLM Messages / Prompt (Code)**  
   - Constructs a textual prompt string containing:  
     - User label (name).  
     - Conversation summary if present, else marks first‑time conversation.  
     - Short transcript from `recent_messages` (roles `user` / `assistant`).  
     - Current user message appended at the end. [attached_file:76]  
   - Output: `prompt`, `phone`, `userName`, coordinator fields, summary and recent messages.

4. **AI Node (current v4.2 behavior)**  
   - Model: `gpt-4o-mini`. [attached_file:76]  
   - System prompt (older version) describes friendly WhatsApp event assistant; v4.2 notes that this must be updated to **strict JSON output** with `reply_text` and `action` and that this work is partially complete. [attached_file:76]  
   - The AI is instructed (in addendum) to never fabricate capacity or events and to rely on DB tools for registration. [attached_file:76]

5. **Parse AI Action (Code)**  
   - Attempts to `JSON.parse` the AI reply.  
   - Normalizes into: `action_type` ∈ { `chat`, `register`, `unregister` }, `event_id` (or `null`), and human‑readable `reply_text`. [attached_file:76]

6. **Action Router (Switch)**  
   - If `action_type = "register"` → branch into registration tool.  
   - If `action_type = "unregister"` → branch into unregistration tool.  
   - Otherwise → pass straight to formatter and response. [attached_file:76]

7. **Register User for Event (Postgres)**  
   - Calls `SELECT register_for_event(phone, event_id)` and returns JSON with `success` and `error_code`. [attached_file:76]  
   - At this stage, n8n does not re‑implement capacity logic or duplicates; it simply forwards the JSON to the AI or formatter.

8. **Unregister User from Event (Postgres)**  
   - Calls `SELECT unregister_from_event(phone, event_id)` and returns structured JSON. [attached_file:76]

9. **Format Action Result (Code)**  
   - Merges the branches.  
   - Currently mostly passes through `reply_text` plus attaches `functionResponse` for future re‑interpretation by AI; v4.2 suggests a second AI pass could be used later to rewrite user‑visible messages based on function output. [attached_file:76]

10. **(Integration pending)**  
    - WhatsApp send node will replace the current manual testing steps once WA‑001 is implemented. [attached_file:76][attached_file:74]

### 4.2 Planned Tool Workflows (Not Yet Wired)

The documentation defines but has not yet wired these n8n sub‑workflows. They are important for future expansion and rely on existing schema and views. [attached_file:75][attached_file:73][attached_file:74]

- **RECOMMEND‑001 – Event Recommendation Tool**  
  - Will query all non‑cancelled, non‑postponed events with descriptions and capacity info, letting AI perform semantic matching. [attached_file:75]  

- **HOTEL‑001 – Hotel / Coordinator Query Tool**  
  - Simple `SELECT` from `users` or `v_my_profile` to answer hotel room and coordinator queries. [attached_file:75][attached_file:76]  

- **ADMIN‑00x – Admin Operations**  
  - **ADMIN‑001**: admin verification against `admins`.  
  - **ADMIN‑002**: event creation using AI‑parsed messages and `events` + `food_locations`.  
  - **ADMIN‑003/004**: event cancellation/postponement with user notifications.  
  - **ADMIN‑005**: targeted announcements to event‑specific or global audiences.  
  - **ADMIN‑006**: real‑time turn‑up queries using registrations and check‑in data. [attached_file:75][attached_file:74]

- **ENGAGE‑001 / FOOD‑001 / REMIND‑001 / REMIND‑002 – Notifications & Engagement**  
  - All re‑designed in the notifications addendum to write into `notifications` instead of sending directly on cron. [attached_file:73][attached_file:76]

---

## 5. Task Catalogue and Roadmap (v4.2)

### 5.1 Completed

- **SCHEMA‑001** – Base tables (`users`, `events`, `food_locations`, `registrations`, `admins`, `chat_history`). [attached_file:76]  
- **SCHEMA‑002** – Constraints + `check_event_capacity` trigger, unique keys, and cascade deletes. [attached_file:76]  
- **VIEW‑001** – Participant views (`v_events_public`, `v_my_profile`, `v_my_registrations`, `v_food_public`). [attached_file:76]  
- **FUNC‑001 / FUNC‑002** – `register_for_event` and `unregister_from_event` with structured JSON error codes. [attached_file:76]  
- **SEC‑001** – RLS and `event_bot_admin_role` for defense‑in‑depth. [attached_file:76]  
- **INFRA‑001 (local)** – Local Postgres + n8n credentials configured. [attached_file:76]  
- **CHAT‑001** – Webhook‑based chat context handler wired to DB. [attached_file:76]  
- **REG‑001 / REG‑002** – DB registration/unregistration workflows wired from n8n to functions. [attached_file:76]

### 5.2 Partial / In Progress

- **AI‑001** – Final AI system prompt enforcing strict JSON `{ reply_text, action }` and tool usage; v4.2 flags this as partially complete. [attached_file:76]  
- **WF‑001** – Local chat workflow uses AI and DB tools correctly, but WhatsApp Cloud API and some error‑handling/observability remain to be added. [attached_file:76]

### 5.3 Planned (Not Implemented Yet)

- **SCHEMA‑003 + NOTIF‑001..004** – Notifications outbox schema and worker pipelines. [attached_file:76][attached_file:73]  
- **HOTEL‑001 / RECOMMEND‑001** – Dedicated tools for hotel queries and richer recommendation scoring. [attached_file:76][attached_file:75]  
- **ADMIN‑001..006** – Full admin toolkit (create/delete/postpone events, announcements, turn‑up analytics). [attached_file:75][attached_file:74]  
- **WA‑001 / DEPLOY‑001 / OBS‑001** – WhatsApp integration, deployment to cloud DB + n8n, and observability/logging. [attached_file:76][attached_file:74]

---

## 6. Handoff Notes for Future Developers / AI Agents

- Treat this README as the **runtime‑state index**; for full SQL definitions, see `sql.txt` and `jito_event_bot_final_v4_2_runtime_ready.md`. [attached_file:72][attached_file:76]  
- Do **not** bypass `register_for_event` / `unregister_from_event`; all capacity and cutoff logic lives there to keep behavior consistent and auditable. [attached_file:76]  
- When adding new workflows (admin tools, notifications, recommendations), prefer reading from views and calling existing functions rather than touching base tables directly. [attached_file:76]  
- Notifications and engagement must go through the `notifications` outbox pattern; avoid direct send‑on‑cron logic to keep behavior consistent and debuggable. [attached_file:73][attached_file:76]  
- Any future AI changes should maintain the contract: every turn returns a single JSON object `{ "reply_text": string, "action": { "type": "register"|"unregister"|"none", "event_id": int|null } }` to keep n8n routing simple and robust. [attached_file:76]

