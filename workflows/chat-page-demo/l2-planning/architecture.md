# System Architecture: Chat Page

## 1. Overview

This document describes the architecture for the chat page demo. The system consists of a React-based SPA frontend, a lightweight Node.js backend, and a PostgreSQL + Redis data layer. The design prioritizes rapid development, clear API contracts, and a path to horizontal scaling.

## 2. High-Level Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                        Client (Browser)                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │  React SPA  │  │  WebSocket  │  │  SSE (AI stream)    │  │
│  │  (Vite)     │  │  Client     │  │  Client             │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘  │
└─────────┼────────────────┼────────────────────┼─────────────┘
          │                │                    │
          ▼                ▼                    ▼
┌─────────────────────────────────────────────────────────────┐
│                      Load Balancer (nginx)                  │
└─────────────────────────────────────────────────────────────┘
          │                │                    │
          ▼                ▼                    ▼
┌─────────────────────────────────────────────────────────────┐
│                     API Gateway / Node.js                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │  REST API   │  │  Socket.io  │  │  SSE Endpoint       │  │
│  │  (Express)  │  │  Server     │  │  (/api/ai/stream)   │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘  │
└─────────┼────────────────┼────────────────────┼─────────────┘
          │                │                    │
          ▼                ▼                    ▼
┌─────────────────────────────────────────────────────────────┐
│                      Data Layer                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │  PostgreSQL │  │    Redis    │  │  (Future: S3/MinIO) │  │
│  │  (messages) │  │  (presence, │  │  (file uploads)     │  │
│  │             │  │  rate limit)│  │                     │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## 3. Tech Stack

| Layer | Technology | Rationale |
|-------|------------|-----------|
| Frontend Framework | React 18 + TypeScript | Mature ecosystem, strong AI/LLM UI tooling |
| Build Tool | Vite | Fast HMR, optimized production bundles |
| Styling | Tailwind CSS + Radix UI | Rapid responsive development, accessible primitives |
| State Management | Zustand | Lightweight, minimal boilerplate |
| Virtualized List | `@tanstack/react-virtual` | Smooth infinite scroll, large datasets |
| Markdown | `react-markdown` + `remark-gfm` | Safe, streaming-friendly markdown |
| Backend Runtime | Node.js 20 + Express | Fastest path to prototype, ubiquitous talent |
| Real-Time | Socket.io | Automatic long-polling fallback, Redis adapter ready |
| AI Streaming | SSE (`/api/ai/stream`) | Simple, unidirectional token streaming |
| Database | PostgreSQL 15 | Reliable, jsonb for metadata, excellent ORM support |
| Cache / PubSub | Redis 7 | Ephemeral state, presence, rate limiting |
| ORM | Prisma | Type-safe migrations and queries |
| Deployment | Docker Compose (demo) | Single-command local/demo deployment |

## 4. Component Diagram (Frontend)

```
┌────────────────────────────────────────┐
│           <ChatPage />                 │
│  ┌──────────────────────────────────┐  │
│  │      <ConversationSidebar />     │  │
│  │  - SearchInput                   │  │
│  │  - ConversationList              │  │
│  └──────────────────────────────────┘  │
│  ┌──────────────────────────────────┐  │
│  │        <ChatMain />              │  │
│  │  ┌────────────────────────────┐  │  │
│  │  │    <MessageList />         │  │  │
│  │  │  - <MessageItem />         │  │  │
│  │  │  - <TypingIndicator />     │  │  │
│  │  │  - Virtualized scroll      │  │  │
│  │  └────────────────────────────┘  │  │
│  │  ┌────────────────────────────┐  │  │
│  │  │    <Composer />            │  │  │
│  │  │  - Auto-resize textarea    │  │  │
│  │  │  - Send / Emoji / Attach   │  │  │
│  │  └────────────────────────────┘  │  │
│  └──────────────────────────────────┘  │
│  ┌──────────────────────────────────┐  │
│  │      <ThreadPane /> (slide-over)│  │
│  │  - <MessageList /> (thread)     │  │
│  │  - <Composer /> (thread reply)  │  │
│  └──────────────────────────────────┘  │
└────────────────────────────────────────┘
```

## 5. Data Flow

### 5.1 Send Message
1. User submits message in `<Composer />`
2. Optimistic update: append to local Zustand store with `status: sending`
3. POST `/api/messages` with `{ conversationId, content, parentId? }`
4. Server persists to PostgreSQL, broadcasts via Socket.io room
5. Client receives `message:created` event, reconciles optimistic update
6. If error, mark `status: failed` with retry UI

### 5.2 Receive Real-Time Message
1. Server emits `message:created` to all Socket.io clients in the conversation room
2. Client Zustand store appends message; `<MessageList />` re-renders virtualized row
3. If user is scrolled to bottom, auto-scroll; otherwise show "New Messages" badge

### 5.3 AI Streaming Response
1. User sends message tagged for AI (e.g., `@assistant` or automatic routing)
2. Server opens SSE stream at `/api/ai/stream?conversationId=...`
3. Frontend renders partial tokens via `react-markdown`
4. On stream end, server persists full AI message to PostgreSQL and emits `message:created`

### 5.4 Typing Indicator
1. On composer input, client emits `typing:start` (throttled 3 s)
2. Server broadcasts `typing:update` to room with active user list
3. Redis TTL key expires typing state after 5 s of inactivity

## 6. API Contracts

### REST Endpoints

#### `GET /api/conversations`
Response:
```json
{
  "conversations": [
    {
      "id": "uuid",
      "title": "string",
      "lastMessageAt": "ISO-8601",
      "unreadCount": 0
    }
  ]
}
```

#### `GET /api/conversations/:id/messages?cursor=&limit=50`
Response:
```json
{
  "messages": [
    {
      "id": "uuid",
      "conversationId": "uuid",
      "parentId": "uuid | null",
      "sender": { "id": "uuid", "name": "string", "avatarUrl": "string" },
      "content": "string (markdown)",
      "createdAt": "ISO-8601",
      "status": "sent | delivered | failed",
      "reactions": [{ "emoji": "👍", "count": 2, "userIds": ["uuid"] }]
    }
  ],
  "nextCursor": "string | null"
}
```

#### `POST /api/messages`
Request:
```json
{
  "conversationId": "uuid",
  "content": "string",
  "parentId": "uuid | null"
}
```
Response: `201 Created` with created message object.

#### `POST /api/messages/:id/reactions`
Request:
```json
{ "emoji": "👍" }
```
Response: `200 OK` with updated reactions.

#### `GET /api/conversations/:id/search?q=keyword`
Response:
```json
{
  "results": [
    { "messageId": "uuid", "snippet": "...keyword..." }
  ]
}
```

### WebSocket (Socket.io) Events

| Event | Direction | Payload |
|-------|-----------|---------|
| `room:join` | C → S | `{ conversationId }` |
| `room:leave` | C → S | `{ conversationId }` |
| `typing:start` | C → S | `{ conversationId }` |
| `typing:stop` | C → S | `{ conversationId }` |
| `message:created` | S → C | Message object |
| `message:updated` | S → C | Message object (reactions, edits) |
| `typing:update` | S → C | `{ conversationId, users: [{id, name}] }` |

### SSE Endpoint

#### `GET /api/ai/stream?conversationId=uuid`
- Headers: `Content-Type: text/event-stream`
- Events:
  - `data: {"token": "..."}` — partial AI token
  - `data: {"done": true, "messageId": "uuid"}` — stream completion

## 7. Database Schema (Prisma)

```prisma
model User {
  id        String   @id @default(uuid())
  name      String
  avatarUrl String?
  createdAt DateTime @default(now())
  messages  Message[]
  reactions Reaction[]
}

model Conversation {
  id        String    @id @default(uuid())
  title     String
  createdAt DateTime  @default(now())
  updatedAt DateTime  @updatedAt
  messages  Message[]
}

model Message {
  id             String        @id @default(uuid())
  conversationId String
  conversation   Conversation  @relation(fields: [conversationId], references: [id])
  parentId       String?
  parent         Message?      @relation("Thread", fields: [parentId], references: [id])
  replies        Message[]     @relation("Thread")
  senderId       String
  sender         User          @relation(fields: [senderId], references: [id])
  content        String
  createdAt      DateTime      @default(now())
  reactions      Reaction[]

  @@index([conversationId, createdAt])
  @@index([parentId])
}

model Reaction {
  id        String   @id @default(uuid())
  messageId String
  message   Message  @relation(fields: [messageId], references: [id], onDelete: Cascade)
  userId    String
  user      User     @relation(fields: [userId], references: [id])
  emoji     String
  createdAt DateTime @default(now())

  @@unique([messageId, userId, emoji])
}
```

## 8. Deployment Approach

### Demo / Local
- Docker Compose with 3 services:
  1. `frontend` — Vite dev server or nginx serving static build
  2. `backend` — Node.js Express + Socket.io
  3. `postgres` — PostgreSQL 15
  4. `redis` — Redis 7

### Production Path (Future)
- Containerize frontend as static assets behind CDN
- Backend deployed as stateless containers behind load balancer
- Redis adapter for Socket.io enables horizontal scaling
- PostgreSQL with read replicas for message history queries
- Object storage (S3/MinIO) for file attachments

## 9. Security Checklist

- Input sanitization via `dompurify` before markdown render
- SameSite `Lax` cookies for session auth
- Helmet.js headers on Express
- Rate limiting: 10 messages/second per user via Redis token bucket
- CORS restricted to known origins
- Prisma query parameterization prevents SQL injection
