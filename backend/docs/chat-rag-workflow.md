# AI Chat / RAG Workflow

This document explains how the Restaurant RAG chat system works end to end.

It is written for:

- backend developers
- frontend and mobile developers
- QA and support teams
- product/client explanations

## 1. System Overview

The chat system is a backend-controlled RAG pipeline.

At a high level:

1. user sends a message from web or mobile chat
2. frontend calls the backend chat API
3. backend authenticates the user and loads session context
4. backend uses Qwen first for structured intent extraction
5. backend executes retrieval and business rules using that structured intent
6. backend keeps structured recommendation memory inside the active session
7. backend uses fast deterministic reply paths when grounding is already strong
8. Ollama/Qwen writes the final natural-language reply only when extra reasoning or conversational wording is needed
9. backend saves chat history
10. frontend renders the reply and suggestion cards

Important:

- the backend is the decision-maker
- the LLM is only the wording layer
- the LLM never queries PostgreSQL directly

## 2. Current End-to-End Flow

### Standard request path

1. User types a message.
2. Frontend sends:
   - `POST /api/chat/message`, or
   - `POST /api/chat/message/stream`
3. Backend authenticates the user with JWT.
4. Backend resolves or creates the active chat `session_id`.
5. Backend checks ultra-fast small-talk paths first.
   - greetings such as `hi` and `hello` avoid retrieval entirely
   - acknowledgements such as `thanks` return an instant lightweight reply
6. Backend checks the fast Redis response cache for non-personalized generic queries.
   - this cache uses normalized intent/topic keys, not only raw message text
   - example: `do you have dessert?`, `dessert?`, and `any dessert available?` can reuse the same cache entry
   - example: `which types of soup you have?`, `what soup do you have?`, and `any soup available?` can reuse the same topic cache entry
7. Backend loads lightweight structured session state from Redis first.
   - full recent history is only loaded when a follow-up turn or LLM prompt actually needs it
8. Backend loads:
   - recent chat history for that session when needed
   - user preferences only when the turn really depends on personal context
9. Backend loads structured session state from Redis/history:
   - last intent
   - active intent
   - active topic
   - prior filters
   - seen item IDs
   - prior restaurants
   - last successful user query
   - last recommendation context
10. Backend uses a lightweight backend intent parser first for simple deterministic queries such as:
   - `pizza`
   - `burger`
   - `dessert`
   - `food under 300`
   - `veg food`
   - `restaurant list`
11. Backend only calls Qwen for intent extraction when that lightweight parser is not reliable enough.
12. Qwen returns a compact JSON intent such as:
   - `greeting`
   - `dish_recommendation`
   - `restaurant_list`
   - `recommendation`
   - `show_more`
13. Backend merges that extracted intent with session memory when the turn is a continuation.
    - follow-up turns such as `show me more` and `something else` use the most recent active recommendation context
    - newer topics such as `i like burger` replace older active topics such as `suggest non veg food`
14. Backend builds an effective retrieval query from the structured intent.
15. Backend tries keyword-first retrieval when the structured intent suggests a specific dish, cuisine, category, or restaurant.
16. If the query is about combos, backend checks generated combo rows first.
    - examples: `suggest combos`, `pizza combo`, `combo under 500`, `popular combos`
    - only generated combos from the database are allowed
17. If the query is specifically about new items, backend can switch into a dedicated `new_only` path.
    - examples: `what's new?`, `new spicy food`, `new items for me`, `new Italian dishes`
    - only items still inside the configured launch window are eligible
    - backend can use a DB-first fast path before embeddings/vector search when the query is simple enough
18. If the user includes an explicit budget such as `under 300` or `below ₹250`, backend applies it as a strict price filter.
19. If keyword retrieval is not strong enough, backend generates a query embedding with `nomic-embed-text`.
20. Backend runs pgvector similarity search on menu embeddings only when keyword retrieval is not enough.
21. Backend filters candidates by live business rules:
    - item must be available
    - restaurant must be active
    - restaurant must be approved
    - for `new_only` turns, item must still qualify as new from `launched_at`
    - explicit user budget is enforced strictly
    - preference budget is used as a softer filter when no explicit budget is present
- diet/spice hints are applied when possible
- previously shown items are excluded on continuation turns
- explicit item requests keep only candidates that actually match that dish/topic
- combo queries must use generated combo rows only
- combo budget queries filter by combo price, not individual item price
22. If the query has no exact match, backend falls back to available alternatives from the database.
    - for item queries such as `burger`, backend can keep the unavailable item as the active topic and continue offering different alternative batches on follow-up turns
23. If a follow-up turn has no more unseen matches, backend returns a natural terminal response such as:
    - `These are currently the best burger options available right now.`
24. If grounded keyword candidates already answer the user safely, backend can skip final Qwen generation and return a deterministic fast reply.
25. Otherwise backend builds a compact grounded menu context block from the best candidates.
26. Backend sends that safe context to Qwen for the final user-facing reply.
27. Backend validates the LLM reply:
    - generic/unhelpful replies are replaced with a safe DB-backed reply
    - LLM failure/timeouts fall back to a DB-backed reply
    - contradictory “item unavailable” wording is replaced if grounded matching suggestions already exist
28. Backend saves user + assistant messages plus structured session state in `chat_history` and Redis.
29. Backend returns:
    - reply text
    - session id
    - structured suggestion cards

### Clear chat path

1. Frontend can call `DELETE /api/chat/history`.
2. Backend deletes the authenticated user’s chat history:
   - for one `session_id` when provided
   - or all of the user’s chat history when no `session_id` is provided
3. Backend clears Redis session cache keys for the same scope.
4. Frontend resets the local thread and starts with a fresh chat session.

## 3. Streaming Flow

The system also supports streamed replies.

### Route

- `POST /api/chat/message/stream`

### Behavior

1. Frontend sends the same chat payload.
2. Backend prepares retrieval/context exactly like the normal endpoint.
3. Backend immediately emits an SSE `meta` event containing:
   - `session_id`
   - `suggestions`
4. If there are no grounded candidates, backend can emit a fallback response immediately.
5. Otherwise backend streams token chunks from Ollama as `token` events for the final conversational answer.
6. Backend persists chat history after the full reply is finalized.
7. Backend ends the stream with a `done` event containing the final payload.

### Why streaming matters

Streaming improves perceived speed:

- the UI can create the assistant bubble immediately
- text starts appearing before full generation finishes
- the chat feels much more conversational

## 4. Flow Diagram

```text
User
  |
  v
Web / Mobile Chat UI
  |
  v
POST /api/chat/message
or
POST /api/chat/message/stream
  |
  v
FastAPI chat router
  |
  v
Auth + session resolution
  |
  v
RAG service
  |-- load recent history
  |-- load structured session memory
  |-- ultra-fast greeting / thanks path?
  |-- global Redis response cache?
  |-- load session memory from Redis
  |-- load preferences if needed
  |-- lightweight intent parser?
  |-- intent extraction with Qwen only when needed
  |-- merge with session state
  |-- generated combos first for combo queries?
  |-- keyword-first retrieval?
  |-- extract/apply budget?
  |-- embedding if needed
  |-- pgvector similarity search
  |-- exclude already suggested items
  |-- DB filtering
  |-- fallback to 3 available alternatives if needed
  |-- terminal "no more matches" response if needed
  |-- deterministic reply fast-path?
  |-- prompt build
  |-- Qwen final grounded generation only when needed
  |-- response validation
  |-- save chat history
  |
  v
Return reply + suggestions
or stream tokens + done event
```

Clear chat:

```text
Frontend clear action
  |
  v
DELETE /api/chat/history[?session_id=...]
  |
  v
Delete PostgreSQL chat rows
  |
  v
Delete Redis chat:session:* and chat:session-state:* keys
  |
  v
Return deleted_count
```

## 5. Role of Each Component

### Frontend / Mobile

Clients are responsible for:

- rendering chat UI
- sending the user message
- showing loading / typing state
- rendering the assistant reply
- showing suggestion cards

They do not control grounding or retrieval logic.

### Backend

The backend is the main brain of the system.

It is responsible for:

- auth and session validation
- preferences load when needed
- recent history / session state load
- lightweight intent detection
- intent extraction when needed
- retrieval strategy selection
- vector search
- business-rule filtering
- prompt construction
- fallback behavior
- chat persistence
- structured suggestions

### PostgreSQL

PostgreSQL stores:

- users
- restaurants
- menu items
- menu embeddings
- user preferences
- orders
- chat history

### pgvector

`pgvector` performs semantic retrieval.

It:

- stores menu item embeddings
- compares query embeddings with stored vectors
- returns the closest matching menu candidates

### nomic-embed-text

The embedding model converts text into vectors.

Example queries:

- `"spicy paneer under 300"`
- `"veg dinner ideas"`
- `"show chinese starters"`

### Qwen

Qwen has two roles:

- extract structured intent from natural language
- write the final human-friendly answer from grounded context

It does not:

- access PostgreSQL directly
- know live inventory on its own
- make up authoritative menu facts

It only sees the context selected by the backend.

The backend still remains the source of truth for:

- which items are retrieved
- which filters are applied
- which suggestions are allowed to be shown

### Ollama

Ollama hosts both model types locally:

- embedding model: `nomic-embed-text`
- chat model: `qwen`

## 6. Grounding Rules

These rules are important to the current system:

- the LLM never directly accesses the database
- the backend decides what the LLM can see
- the LLM must not invent menu items, prices, or availability
- replies should stay grounded in real DB rows
- simple deterministic queries should avoid unnecessary LLM work when grounded DB candidates already give a safe answer
- if an exact item is unavailable, backend should suggest up to 3 available alternatives
- follow-up turns should exclude already suggested items from the same active session
- follow-up turns should use the latest active recommendation context, not an older topic
- explicit user budget requests must be enforced strictly
- structured session memory should drive continuation turns like `show me more`
- generic cross-user cache is only allowed for non-personalized, non-follow-up queries
- query normalization should make `Do you have pasta?` and `do you have pasta ?` hit the same Redis key
- semantic topic normalization should make `do you have dessert?`, `dessert?`, and `show me desserts` reuse the same generic cache key
- semantic topic normalization should make `which types of soup you have?`, `what soup do you have?`, and `any soup available?` reuse the same generic cache key
- if retrieval is weak, backend should fall back to popular or keyword-backed items
- if the LLM reply is weak/generic, backend replaces it with a DB-backed safe reply

## 7. Current API Contracts

## `POST /api/chat/message`

Authenticated request/response chat endpoint.

### Example request

```json
{
  "message": "Suggest spicy veg food under 300"
}
```

Optional fields:

```json
{
  "message": "Recommend dinner",
  "restaurant_id": "uuid-or-null",
  "session_id": "uuid-or-null"
}
```

### Example response

```json
{
  "reply": "You can try Chilli Paneer or Paneer Tikka. Both are vegetarian, spicy, and within your budget.",
  "session_id": "9f7d0b8d-1111-2222-3333-444444444444",
  "suggestions": [
    {
      "id": "7e5d0b8d-1111-2222-3333-444444444444",
      "restaurant_id": "1e5d0b8d-1111-2222-3333-444444444444",
      "restaurant_name": "Spice Route",
      "name": "Chilli Paneer",
      "category": "Starters",
      "cuisine_type": "Indian",
      "description": "Paneer tossed in spicy sauce",
      "price": 249,
      "is_veg": true,
      "is_available": true,
      "image_url": null,
      "similarity_score": 0.91
    }
  ]
}
```

## `POST /api/chat/message/stream`

Authenticated SSE endpoint for streamed chat responses.

### Request

Same payload as `POST /api/chat/message`.

### Stream event types

- `meta`
  - contains `session_id` and `suggestions`
- `token`
  - contains incremental reply text
- `done`
  - contains final `reply`, `session_id`, and `suggestions`

## `GET /api/chat/history`

Authenticated endpoint for loading recent chat history.

Optional query:

- `session_id`

### Example

```text
GET /api/chat/history?session_id=<uuid>
```

## `DELETE /api/chat/history`

Authenticated endpoint for clearing chat history.

Optional query:

- `session_id`

Behavior:

- with `session_id`:
  - clears only that active conversation
- without `session_id`:
  - clears all chat history for the authenticated user

Example:

```text
DELETE /api/chat/history?session_id=<uuid>
```

Example response:

```json
{
  "deleted_count": 8,
  "cleared_session_id": "9f7d0b8d-1111-2222-3333-444444444444"
}
```

## 8. Prompt Construction

Prompt building is intentionally backend-controlled and compact.

The prompt includes:

- system rules
- recent history block
- menu context block
- current user question

The current system keeps prompt size smaller by:

- limiting top retrieval count
- limiting context candidates
- trimming long descriptions
- trimming message length
- limiting recent history
- capping max reply tokens

This improves:

- latency
- grounding quality
- reliability

## 9. Performance Design

The current implementation optimizes several latency points.

### Auth / session load

- auth timings are logged in `app.services.auth`
- helps identify JWT decode vs DB lookup cost

### Preferences load

- preferences are loaded only when the turn uses personal/session-dependent context
- timing is logged

### Embedding generation

- embeddings are skipped for strong keyword matches
- query embeddings are cached with `lru_cache`
- long-lived HTTP clients reduce repeated setup cost

### Vector search

- pgvector similarity uses cosine distance
- top-k is capped
- availability and restaurant visibility filters are pushed into SQL
- `ivfflat` index is expected on `menu_embeddings.embedding`

### Prompt size

- only the most relevant candidates are included
- long descriptions are trimmed
- recent history is capped more aggressively for latency
- max response token count is capped

### LLM generation

- shorter generation limits reduce latency
- keep-alive is used to keep the model warm
- read timeouts prevent indefinite waits

### Persistence

- chat history is saved after the reply is finalized
- the response is not left blank if save succeeds but LLM fails
- assistant suggestion IDs are persisted in chat-history context payloads
- Redis-backed session history helps rebuild recent recommendation memory quickly

## 10. Timing Logs

The backend logs timings for latency debugging.

Important stages:

- cache lookup
- session state load
- intent detection / extraction
- auth/session load
- preferences load
- history load
- session recommendation-state rebuild
- keyword retrieval
- DB filtering
- embedding generation
- vector search
- prompt build
- LLM generation
- DB commit
- total request time

Useful log patterns:

- `Auth timings ...`
- `RAG timings ...`
- `Chat API response ... total=...ms`

## 11. Failure and Fallback Behavior

The system should not leave the UI blank.

### If keyword search is strong

- backend may avoid embedding/vector search and continue with the strongest grounded keyword candidates first
- backend may also skip final Qwen generation and return a deterministic fast reply when grounding is already strong

### If the user asks for more options

backend should:

- reuse the latest active recommendation context from the active session
- exclude already suggested item IDs
- fetch the next matching batch when possible
- stop naturally when there are no more unseen matches

### If an exact item is unavailable

- backend should not return an empty or vague response
- it should suggest up to 3 available alternative dishes from the database
- if the user gave an explicit budget, those alternatives must stay within that budget

### If vector search is weak

backend falls back to:

- keyword retrieval
- popular items
- emergency DB-backed candidates

### If the LLM is slow or times out

backend should:

- enforce timeouts
- log the delay
- return a safe DB-backed reply if retrieval succeeded

### If Ollama is unavailable

backend should:

- avoid crashing the chat experience
- still return grounded fallback suggestions when possible

### If the frontend request fails

clients should:

- show a friendly failure state
- keep optimistic user messages visible
- avoid freezing the thread

## 12. Example Scenario

### User

```text
I want spicy paneer under 300
```

### Backend

1. normalize the message
2. inspect it as a likely dish-style query
3. try keyword-first retrieval
4. find menu items such as:
   - Chilli Paneer
   - Paneer Tikka
5. filter by:
   - item availability
   - approved + active restaurants
   - strict budget limit when the message contains one
6. decide whether a direct DB-backed reply is enough
7. if needed, build a prompt and ask Qwen

### Result

Possible reply:

```text
You can try Chilli Paneer or Paneer Tikka. Both are vegetarian, spicy, and within your budget.
```

### Frontend

Frontend renders:

- assistant reply bubble
- structured suggestion cards
- add-to-cart actions from those suggestion cards

### Unavailable item scenario

User:

```text
burger under 200
```

If no burger item is available, backend should:

1. confirm there is no strong available burger match
2. extract the explicit `200` budget
3. fetch up to 3 real available alternative dishes
4. keep only items with `price <= 200`
5. return a short DB-backed reply with those alternatives

### Follow-up scenario

User:

```text
burger
```

Backend:

1. retrieves burger candidates
2. if burger is unavailable, returns grounded alternative suggestions but keeps `burger` as the active topic
3. stores suggested item IDs plus the active recommendation context in chat history/session cache

User:

```text
show me more
```

Backend:

1. reads the active session history
2. reuses the latest active recommendation context (`burger`), not an older topic
3. excludes already suggested burger item IDs
4. fetches the next unseen matching items or the next unseen alternative batch
5. sends those candidates to Qwen when a continuation-style reply is needed

Result:

- the user sees new burger options instead of repeated cards
- if no more unseen matches exist, backend returns a natural “best available right now” reply

### Soup query scenario

User:

```text
which types of soup you have?
```

Backend:

1. normalizes the query and extracts the active topic `soup`
2. runs keyword-first retrieval against real menu items
3. finds soup-category items such as:
   - `Tom Yum Soup`
   - `Chicken Thukpa`
4. keeps those grounded results instead of drifting to unrelated drinks or combos

Result:

- the user gets actual soup suggestions from the menu

### Combo query scenario

User:

```text
combo under 500
```

Backend:

1. detects that the user is asking about generated combos
2. loads only generated combo rows from active + approved restaurants
3. filters by budget against `suggested_combo_price`
4. builds grounded combo context from combo name, included item names, restaurant, and combo price
5. lets Qwen phrase the final reply only from that safe combo context

Result:

- the user gets only real generated combos from the database
- Qwen does not invent combos

### New item query scenario

User:

```text
what's new?
```

Backend:

1. detects a `new_only` recommendation intent
2. limits candidates to menu items still inside the configured launch window
3. applies normal availability, restaurant approval, and active-state rules
4. prefers new items that best fit the user's tastes when the request is personalized
5. returns structured suggestion cards with fields such as:
   - `is_new`
   - `recommendation_label`
   - `recommendation_reason`

Result:

- the user sees only real newly launched dishes from the database
- chat can say `Matches Your Taste`, `Based on Your Orders`, `Trending Now`, or `Just Launched` when backend metadata provides those labels
- the model still does not invent new menu items

## 13. Working Principles

The current system is designed so that:

- retrieval comes from live DB-backed items
- the model writes the wording, not the facts
- the backend owns business rules
- the chat remains grounded even when the model is slow or unstable
- simple queries can reuse Redis response cache and keyword-first retrieval for lower latency
- follow-up recommendation turns should feel like one ongoing conversation, not isolated searches

## 14. Useful Files

- [backend/app/api/chat.py](/Users/imac/Desktop/restaurant-rag/backend/app/api/chat.py)
- [backend/app/services/rag.py](/Users/imac/Desktop/restaurant-rag/backend/app/services/rag.py)
- [backend/app/services/auth.py](/Users/imac/Desktop/restaurant-rag/backend/app/services/auth.py)
- [backend/app/schemas/chat.py](/Users/imac/Desktop/restaurant-rag/backend/app/schemas/chat.py)
- [backend/app/models/menu_embedding.py](/Users/imac/Desktop/restaurant-rag/backend/app/models/menu_embedding.py)
- [backend/app/tasks/embed.py](/Users/imac/Desktop/restaurant-rag/backend/app/tasks/embed.py)
- [backend/alembic/versions/0004_chat_performance_indexes.py](/Users/imac/Desktop/restaurant-rag/backend/alembic/versions/0004_chat_performance_indexes.py)
