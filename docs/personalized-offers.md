# Offers & Campaigns

## Overview
The offer system now has two production paths:

- Instant welcome onboarding:
  - one reusable `WELCOME_FIRST_ORDER` generated offer
  - no cron dependency
  - no Qwen/Ollama call
  - one `generated_offer_user_matches` row per eligible new user
- Personalized AI offers:
  - generated only for customers with at least one paid order
  - created by the 5:00 PM Celery cron or the admin manual trigger
  - validated by backend guardrails before persistence

Checkout, cart validation, discount math, scope checks, and audience checks remain backend-controlled.

## Current Runtime Flow

### 1. Global Welcome Offer
New customer
↓
Backend checks paid-order history
↓
Attach reusable `WELCOME_FIRST_ORDER` match
↓
Offer appears on Home / Cart immediately

Key rules:

- the reusable welcome offer is stored once in `generated_offers`
- it is restaurant-level
- it is deterministic
- it is not LLM-generated
- new users do not create duplicate welcome-offer rows

### 2. Personalized AI Offers
Customer with paid-order history
↓
5:00 PM cron or admin manual trigger
↓
Behavior and preference signals
↓
Qwen / Ollama
↓
Backend validation + fallback
↓
`generated_offers`
↓
`generated_offer_user_matches`
↓
Home / Cart offer surfaces

## Welcome Offer Lifecycle

### Attach
The backend attaches the reusable welcome offer when:

- a customer registers, or
- an eligible zero-order customer loads offer surfaces and the match is missing

### Remove
The backend removes the welcome match when:

- the customer completes the first paid order, or
- the customer is no longer first-order eligible

This cleanup does not delete the reusable welcome offer itself. It only deactivates the user’s match.

## Why This Split Exists

The welcome offer is intentionally separate from AI generation because it:

- gives instant onboarding without waiting for cron
- avoids unnecessary LLM usage for cold-start users
- avoids duplicate first-order rows in `generated_offers`
- improves analytics because all first-order conversions point to the same reusable offer

AI is only used after the customer has meaningful behavior data.

## AI Offer Eligibility
Personalized AI offers now start only after at least one paid order exists.

Eligible signals include:

- repeated items
- favorite restaurant
- cuisine affinity
- inactivity / win-back state
- average spend behavior
- stored preferences

Cold-start users are excluded from the AI cron path.

## Supported Strategy Directions
The current architecture cleanly supports multiple strategies without changing checkout:

- first-order welcome
- repeated-item / favorite-item offers
- favorite-restaurant offers
- inactive win-back offers
- cuisine-affinity offers
- spend-based offers
- generic safe fallback offers

Future strategies can reuse the same persistence and validation model.

## LLM Responsibility
The LLM can generate:

- title
- subtitle
- CTA
- discount type proposal
- discount value proposal
- minimum order proposal
- short reason

The LLM cannot:

- bypass checkout
- bypass eligibility
- bypass restaurant or branch scope
- invent unsupported discount types
- exceed backend caps
- write directly to the database

## Fallback Behavior
If Qwen/Ollama:

- times out
- is unavailable
- returns invalid JSON
- returns unsafe values

the backend:

- persists a deterministic safe fallback offer, or
- skips generation safely

Customer APIs never fail because of AI generation issues.

## Persistence
No new tables are required.

Existing tables:

- `generated_offers`
  - reusable welcome offer
  - AI-native personalized offers
  - template-derived generated campaigns
- `generated_offer_user_matches`
  - active per-user matches
  - current rank / score / target metadata
- `personalized_offer_events`
  - view / click / conversion analytics

Manual templates in `personalized_offers` still exist for backward compatibility and deterministic fallback inventory.

## Checkout Authority
Offer generation does not change order validation.

The backend still validates:

- first-order eligibility
- audience eligibility
- restaurant / branch / item scope
- current generated-offer match validity
- minimum order amount
- discount calculation

## Manual Trigger and Cron

- scheduled task: `app.tasks.ai_offers.generate_ai_offers_task`
- default cron: `5:00 PM`
- admin manual trigger reuses the same shared generation service

The cron only targets customers with paid-order history.

## Key Files

- [backend/app/services/personalized_offers.py](/Users/imac/Desktop/restaurant-rag/backend/app/services/personalized_offers.py)
  - reusable welcome offer creation
  - user-match sync
  - offer feed serialization
  - checkout validation
- [backend/app/services/ai_offer_generation.py](/Users/imac/Desktop/restaurant-rag/backend/app/services/ai_offer_generation.py)
  - AI candidate building
  - Qwen/Ollama prompt + fallback handling
  - scheduled AI persistence
- [backend/app/api/auth.py](/Users/imac/Desktop/restaurant-rag/backend/app/api/auth.py)
  - registration-time welcome attach
- [backend/app/services/orders.py](/Users/imac/Desktop/restaurant-rag/backend/app/services/orders.py)
  - post-first-paid-order welcome cleanup
