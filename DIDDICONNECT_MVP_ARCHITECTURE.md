# DiddiConnect MVP Architecture

**Status:** Proposed implementation plan  
**Scope:** DiddiFood, DiddiGo, DiddiSend, customer care, and back-office operations  
**Service name:** `DiddiConnect`  
**MVP channels:** durable in-app text chat and logged handoff to the device's external phone dialer

## 1. Decision

DiddiConnect is a separate ecosystem service. It does not live inside DiddiFreeID, DiddiFood,
DiddiGo, or DiddiSend.

- DiddiFreeID owns identity, JWTs, service credentials, status, roles, and global capabilities.
- Food, Go, and Send own the business context and decide who is a legitimate participant.
- DiddiConnect owns conversations, messages, receipts, call attempts, support cases, communication
  policy, audit records, and communication events.
- PostgreSQL is the durable source of truth.
- Redis Streams carry durable, at-least-once business events and worker jobs.
- WebSocket provides live delivery; FCM/APNs provides offline notification.
- The MVP call button opens the operating-system dialer. It does not provide VoIP or number masking.

This boundary preserves the current FreeID architecture: consuming services verify FreeID JWTs
locally through JWKS, while privileged service calls use short-lived, scoped service tokens.

## 2. MVP Outcomes

The MVP must let:

1. A customer and an assigned driver or courier exchange text messages during an eligible task.
2. Either participant tap a call button, have the attempt durably recorded, and open the external
   phone dialer with the counterparty's number.
3. A user open a customer-care conversation, optionally linked to a ride, order, or delivery.
4. An authorized support agent answer, transfer, resolve, and audit a support conversation.
5. Operations reconstruct important actions using durable audit records, correlated application
   logs, metrics, and traces without placing message bodies or phone numbers in logs.

The MVP does not include in-app VoIP, phone-number masking, group chat, attachments, voice notes,
message editing, message deletion, read-aloud, automatic translation, or AI support agents.

## 3. System Context

```text
Mobile/Web clients
      |
      | FreeID user JWT
      v
DiddiConnect API + WebSocket
      |-- PostgreSQL: conversations, messages, calls, support, audit, outbox
      |-- Redis: Streams, rate limits, presence, ephemeral delivery hints
      |-- FCM/APNs: offline notifications
      |
      | scoped service JWTs
      +--> DiddiFood: order participant and state resolver
      +--> DiddiGo: ride participant and state resolver
      +--> DiddiSend: delivery participant and state resolver
      +--> DiddiFreeID: JWKS and service-token issuance

Support agent UI --> DiddiConnect support APIs and WebSocket
Observability   --> Prometheus + OTLP collector + JSON log collector
```

## 4. Ownership by Repository

| Repository | MVP responsibility |
|---|---|
| New `diddi-connect` | API, WebSocket, data model, policy engine, events, workers, support queue, audit, observability |
| `diddi-free-id` | Register DiddiConnect service clients/scopes; expose JWKS; project `diddiconnect/support_agent` capability |
| `diddi-food` | Internal order communication-context resolver; emit relevant order state events; expose chat/call entry points in clients |
| `diddi-go` | Internal ride communication-context resolver; emit relevant ride state events; replace current out-of-app-only contact path |
| `diddi-send` | Internal delivery communication-context resolver; emit assignment/state events; expose courier/customer chat and call entry points |
| `diddi-admin` | Support inbox, assignment, conversation inspection, escalation, and audited agent actions |
| Mobile/web clients | Conversation UI, reconnect/sync, notification routing, and external dialer handoff |

## 5. Conversation Types and Lifecycles

### Task conversation

One conversation is uniquely keyed by `(context_type, context_id)`, where `context_type` is
`food_order`, `ride`, or `delivery`.

```text
pending -> active -> closing -> closed
             |          |
             +------> suspended
```

- `active`: messaging and calls allowed by context policy.
- `closing`: task completed; limited grace period remains.
- `closed`: history readable for the retention window; no new messages or calls.
- `suspended`: safety, abuse, account suspension, or administrative hold.

Initial policy defaults:

| Context | Opens | Enters closing | Grace period |
|---|---|---|---|
| Food order | Courier assigned | Delivered or cancelled | 24 hours after delivery; immediate on pre-assignment cancellation |
| Ride | Driver accepts | Completed or cancelled | 48 hours for lost-item contact |
| Delivery | Courier assigned | Delivered, failed, or cancelled | 24 hours after terminal state |

These values are configuration, not hard-coded domain rules.

### Support conversation

```text
open -> queued -> assigned -> waiting_user/waiting_agent -> resolved -> closed
                    |                                      |
                    +----------------> escalated <---------+
```

A support case may reference one business context but is independently retained and resolved.
Support agents do not silently join task chats. An escalation creates an explicit audited bridge,
and the user sees that support has joined.

## 6. Authorization Model

### User authentication

DiddiConnect verifies the FreeID access token locally using JWKS and validates signature, `kid`,
issuer, audience, expiry, `sub`, role, and status. A service token can never use a human endpoint.
Suspended users may read the minimal support surface required to appeal, but cannot continue task
communications unless a safety policy explicitly permits it.

### Context authorization

Possession of a valid JWT is not enough. For every conversation creation, participant change, call
attempt, and closed-conversation access, DiddiConnect verifies that the user is an eligible
participant in the owning service.

Each owning service exposes an internal endpoint such as:

```http
GET /internal/comms/contexts/{context_id}
Authorization: Bearer <DiddiConnect service JWT>
X-Client-ID: diddiconnect-<environment>
X-Request-ID: <correlation id>
```

The response contains only the communication projection:

```json
{
  "context_type": "ride",
  "context_id": "uuid",
  "state": "driver_assigned",
  "version": 12,
  "participants": [
    {"user_id": "uuid", "role": "customer", "phone_e164": "+237..."},
    {"user_id": "uuid", "role": "driver", "phone_e164": "+237..."}
  ],
  "messaging_allowed": true,
  "calling_allowed": true,
  "closes_at": null
}
```

The phone number is never copied into conversation or audit tables. It is fetched just in time for
an authorized call handoff. Resolver responses must not be logged.

### Service scopes

Recommended scopes:

- DiddiConnect calling Food/Go/Send: `comms:context:read`.
- Food/Go/Send publishing context changes: `comms:context:write` if HTTP ingestion is needed.
- DiddiAdmin support access: `comms:support:read`, `comms:support:write`, `comms:audit:read`.
- Pilotage aggregate reporting: `comms:reporting:read`; never message-content access.

Support-agent authority should be a FreeID capability owned by DiddiConnect, not a new ecosystem-wide
human role. Privileged agent actions must re-check the capability or a fresh projection rather than
trusting a long-lived claim alone.

## 7. External Call MVP

### API flow

```http
POST /comms/v1/conversations/{conversation_id}/call-attempts
Authorization: Bearer <user JWT>
Idempotency-Key: <client generated UUID>
X-Request-ID: <correlation id>

{"target_participant_id":"uuid","mode":"external"}
```

The server:

1. Verifies the JWT and active account status.
2. Loads the conversation and verifies participant membership.
3. Revalidates context state and call permission with the owning service.
4. Applies rate limits and block/safety rules.
5. Writes `call_attempt`, `audit_event`, and `outbox_event` in one database transaction.
6. Returns an opaque attempt ID and a `tel:` action built from the resolver response.

```json
{
  "attempt_id": "uuid",
  "mode": "external",
  "action": "tel:+237...",
  "expires_at": "2026-10-09T12:01:00Z"
}
```

The client immediately invokes the OS dialer. It may report `dialer_opened` or `dialer_failed`, but
those are client-reported facts. The MVP must never label an attempt as connected, answered, missed,
or completed because the external dialer does not provide trustworthy call outcome data.

### Privacy constraint

Direct external calls reveal both parties' phone numbers through the normal telephone network. The
UI must state this before first use, and the privacy terms must cover it. Number masking is the first
post-MVP telephony upgrade. DiddiConnect's API and schema reserve `mode=masked_external` and
`mode=in_app` but reject them until providers are configured.

Suggested rate limits are 5 attempts per conversation per 10 minutes and 20 per user per hour, with
configurable safety overrides. Idempotency prevents a double tap from creating duplicate audits.

## 8. Chat APIs

```text
POST /comms/v1/contexts/{type}/{id}/conversation        ensure/get task conversation
GET  /comms/v1/conversations                            list caller conversations
GET  /comms/v1/conversations/{id}                       conversation metadata
GET  /comms/v1/conversations/{id}/messages?after_seq=   durable incremental sync
POST /comms/v1/conversations/{id}/messages              send text message
POST /comms/v1/conversations/{id}/read                  advance read cursor
POST /comms/v1/conversations/{id}/call-attempts         logged external call handoff
POST /comms/v1/support/cases                            open support conversation
POST /comms/v1/conversations/{id}/report                report abuse/safety issue
GET  /comms/v1/ws                                       multiplexed realtime socket
```

Message creation requires an `Idempotency-Key` or `client_message_id`. The server assigns a monotonic
`sequence` within the conversation. Reconnect always uses HTTP sync from the last sequence; WebSocket
is a low-latency delivery channel, not the source of truth.

MVP WebSocket server events:

- `message.created`
- `message.delivered`
- `conversation.read_cursor_changed`
- `conversation.state_changed`
- `support.assignment_changed`
- `call_attempt.recorded`

Clients send messages over HTTP in the first MVP. This gives straightforward idempotency, response
codes, rate limiting, and audit correlation. The socket carries server-to-client updates only.

## 9. Persistence Model

All mutable business writes and their outbox event commit in one PostgreSQL transaction.

### Core tables

- `conversations`: ID, type, context type/ID, state, context version, closes/closed timestamps,
  last sequence, creation/update timestamps.
- `conversation_participants`: conversation ID, user ID, participant role, permissions, join/leave
  timestamps, read sequence, notification preference.
- `messages`: ID, conversation ID, sequence, sender user ID, client message ID, body, moderation
  status, created timestamp. No edit/delete columns in MVP.
- `message_deliveries`: message ID, participant ID, channel, status, attempted/delivered timestamps,
  bounded provider error code.
- `call_attempts`: ID, conversation ID, actor/target user IDs, mode, server status, client-reported
  outcome, request ID, idempotency key, timestamps. No phone number and no claimed call duration.
- `support_cases`: conversation ID, requester, linked context, category, priority, assignee,
  state, resolution code, SLA timestamps.
- `audit_events`: append-only actor, action, target, outcome, reason code, request ID, idempotency key,
  safe metadata, timestamp.
- `outbox_events`: event ID, aggregate, event type/version, payload, attempts, next attempt, published
  timestamp, terminal failure reason.
- `processed_events`: consumer name and event ID for idempotent inbox handling where side effects need it.

### Important constraints

- Unique task conversation per `(context_type, context_id)`.
- Unique message `(conversation_id, sequence)` and `(sender_user_id, client_message_id)`.
- Unique call attempt `(actor_user_id, idempotency_key)`.
- Audit rows are insert-only at the application role and database-permission levels.
- Message bodies and phone numbers never appear in audit context, outbox metadata intended for
  external consumers, metrics labels, or operational logs.

## 10. Redis Design

Redis is not the source of truth for messages or audits.

### Durable stream

Use one ordered stream for the MVP:

```text
diddiconnect.events
```

Envelope:

```json
{
  "event_id": "uuid",
  "event_type": "comms.message.created",
  "event_version": 1,
  "occurred_at": "RFC3339 timestamp",
  "producer": "diddiconnect",
  "aggregate_type": "conversation",
  "aggregate_id": "uuid",
  "correlation_id": "request-id",
  "causation_id": "optional-event-id",
  "payload": {}
}
```

Consumer groups:

- `diddiconnect-push`: FCM/APNs notification dispatch.
- `diddiconnect-realtime`: publishes ephemeral WebSocket delivery hints.
- `diddiconnect-support-sla`: support timers and escalations.
- `diddiconnect-analytics`: privacy-safe aggregate events.

Consumers acknowledge only after successful handling, are idempotent by `event_id`, retry with
bounded exponential backoff, reclaim abandoned pending entries, and move poison events to
`diddiconnect.events.dlq`. Alert on pending age, retry count, DLQ growth, and outbox age.

The transactional outbox closes the database-write/event-publish gap that exists when application
code commits first and calls `XADD` second. A dispatcher claims unpublished outbox rows, performs
`XADD`, and then records the Redis entry ID. Duplicate publication is acceptable; consumers dedupe.

### Ephemeral Redis uses

- Presence keys with short TTLs: `comms:presence:{user_id}`.
- Socket-instance routing or Pub/Sub delivery hints. Missing a hint is safe because clients resync
  from PostgreSQL by sequence after reconnect.
- Distributed rate-limit counters.
- Short-lived context resolver cache keyed by owner-provided context version.

Stream retention is bounded and monitored. PostgreSQL outbox and domain tables remain the recovery
source; a service offline past stream retention replays from outbox/event archive or runs a backfill.

## 11. Audit, Logs, Metrics, and Traces

These are separate tools with separate promises:

| Signal | Purpose | Durable? | May contain IDs? | May contain content/phone? |
|---|---|---:|---:|---:|
| Audit table | Who performed a security/business action | Yes | Yes | No |
| Application logs | Debugging and incident correlation | Retention policy | Bounded IDs | No |
| Metrics | Aggregate health and SLOs | Time series | No user/context IDs | No |
| Traces | Cross-service latency and failures | Sampling policy | Request/correlation IDs | No |

Required audit actions include conversation opened/closed/suspended, participant access denied,
message reported, call requested/link issued/client result, support assigned/transferred/resolved,
support joined task context, and administrative content access.

Structured JSON logs carry `request_id`, `trace_id`, `event`, safe actor/target IDs, route template,
outcome, error code, and duration. Do not log authorization headers, query-string secrets, message
bodies, push tokens, phone numbers, or full resolver responses.

Prometheus metrics use low-cardinality labels only. Initial metrics:

- HTTP and WebSocket connections, errors, and latency.
- Messages created and delivery latency by channel/outcome.
- Active conversations by type/state.
- Call attempts by context type/outcome, never by user or conversation.
- Context resolver latency/errors by owning service.
- Outbox unpublished count/oldest age.
- Redis consumer pending count/oldest age/retries/DLQ size.
- Support queue depth, first-response time, resolution time, and SLA breaches.
- Authorization denials and rate-limit rejections by reason code.

Use OpenTelemetry for inbound HTTP, outbound resolver calls, PostgreSQL, Redis, and workers. Propagate
`traceparent` plus `X-Request-ID` to Food, Go, and Send. Readiness checks PostgreSQL and Redis; liveness
checks only the process. Protect the metrics endpoint with the same pattern already used by DiddiSend.

## 12. Retention and Data Protection

Proposed defaults, subject to legal review:

| Data | Default retention |
|---|---:|
| Task messages and delivery receipts | 180 days after conversation close |
| Support messages and case history | 365 days after close |
| Call-attempt records | 365 days |
| Security/business audit records | 365 days minimum |
| Operational logs | 30 days hot, up to 90 days archived |
| Metrics | 90 days |
| Traces | 7-14 days with sampling |

Database backups are encrypted. Sensitive columns use storage encryption and tightly scoped database
roles. Support content access is least privilege and itself audited. Deletion/anonymization jobs must
preserve legally required audit facts while removing message content and unnecessary personal data.

## 13. Failure Rules

- PostgreSQL unavailable: reject writes; do not pretend a message or call attempt was recorded.
- Redis unavailable: accept a message only if its database transaction and outbox commit; live and
  push delivery is delayed. Readiness is degraded/unavailable according to backlog policy.
- Context owner unavailable: existing active chat may continue for a short, versioned policy cache;
  creation, participant changes, and call-number release fail closed.
- Push provider unavailable: retain delivery job and retry; chat remains available through sync.
- WebSocket unavailable: clients continue through HTTP send/list and poll with sequence cursors.
- Poison event: bounded retries, DLQ, alert, and manual replay tooling.
- Duplicate requests/events: return prior idempotent result and avoid duplicate user-visible effects.

## 14. Delivery Plan

### Phase 0: contracts and repository foundation

- Create `diddi-connect` using the existing FastAPI/module conventions.
- Freeze REST, WebSocket, event-envelope, error-envelope, and context-resolver contracts.
- Add PostgreSQL migrations, Redis, health/readiness, request correlation, JSON logs, protected
  metrics, OTLP configuration, and deployment settings validation.
- Provision FreeID service clients, audiences, scopes, and support-agent capability ownership.

### Phase 1: durable task chat

- Implement conversations, participants, messages, receipts, audit, and transactional outbox.
- Add resolver endpoints in Food, Go, and Send with service-token authorization.
- Implement Redis dispatcher/consumers, WebSocket fanout, push notifications, and reconnect sync.
- Integrate one vertical slice first, recommended DiddiGo, then reuse the contract for Send and Food.

### Phase 2: external call handoff

- Implement call policy, rate limits, idempotent call-attempt endpoint, audit, and safe `tel:` response.
- Add first-use privacy disclosure and client-reported dialer outcome.
- Add abuse reporting and an operational call-attempt search that never exposes phone numbers.

### Phase 3: customer care

- Implement support cases, queueing, assignment, transfer, SLA timers, resolution, and escalation.
- Build the DiddiAdmin inbox with audited access and agent capability checks.
- Add context snapshots containing safe operational facts, not unrestricted cross-service data.

### Phase 4: hardening and pilot

- Load-test message bursts, reconnect storms, Redis recovery, and worker redelivery.
- Run security tests for broken object-level authorization, token confusion, scope bypass, replay,
  phone disclosure, log leakage, rate-limit bypass, and support privilege escalation.
- Create dashboards, alerts, DLQ replay/runbooks, retention jobs, backup restore test, and incident drill.
- Pilot one city/context, observe SLOs and abuse patterns, then enable the remaining modules by flag.

## 15. Test Strategy

- Domain tests for lifecycle and permission matrices.
- API tests for every actor/context/state combination.
- Contract tests shared by Food, Go, Send, DiddiConnect, and clients.
- Database tests for uniqueness, append-only audit permissions, idempotency, and outbox atomicity.
- Redis tests for redelivery, pending reclaim, duplicate events, retry, and DLQ behavior.
- WebSocket tests for auth, multiplexing, reconnect, ordering, and multi-device sessions.
- End-to-end tests from task assignment through chat, notification, read sync, and external dialer action.
- Observability tests asserting request/trace correlation and proving bodies, phones, tokens, and push
  credentials never enter logs or metric labels.

## 16. MVP Acceptance Criteria

The MVP is ready when:

1. Unauthorized users cannot discover, read, message, or call within another context.
2. Every accepted message survives process/Redis restart and appears exactly once in client history.
3. Every call-button request has one durable call-attempt and audit record before a phone action is returned.
4. The system never claims knowledge of an external call outcome it cannot observe.
5. A missed WebSocket or push event is repaired by sequence-based sync.
6. Redis consumers recover pending work and duplicate delivery causes no duplicate side effect.
7. Support actions are capability-gated and durably audited.
8. Logs, metrics, traces, and audits contain no message body, phone number, token, or push credential.
9. Dashboards and alerts expose API health, delivery latency, outbox/stream lag, DLQ growth, and support SLA.
10. Food, Go, and Send pass the same communication-context contract suite.

## 17. Decisions Still Required Before Coding

1. Confirm the direct-number privacy/legal position for the external-dialer MVP.
2. Confirm retention periods with legal and operations.
3. Choose the first vertical-slice product; DiddiGo is recommended because rider-driver contact is
   already recognized as an out-of-app gap.
4. Decide whether the first support inbox ships inside DiddiAdmin or as a minimal DiddiConnect web UI.
5. Choose push providers per client platform and the initial OTLP/log/metrics backend.
6. Set final task grace periods and call rate limits by product and country.

