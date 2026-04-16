# Chat Page Demo Backend

Node.js + Express + Socket.io backend for the chat-page-demo workflow.

## Features

- Real-time messaging via Socket.io (join/leave rooms, message broadcast, typing indicators)
- REST APIs for conversations, messages, threaded replies, reactions, and search
- Mock AI SSE streaming endpoint (`/api/ai/stream`)
- In-memory data store with seeded demo data
- Input sanitization (DOMPurify), rate limiting (10 msg/s per user), Helmet headers, and CORS
- Unit/integration tests with Jest + Supertest + Socket.io-client

## Quick Start

```bash
cd workflows/chat-page-demo/l3-dev/backend
npm install
npm run dev
```

The server starts on `http://localhost:4000` by default.

## Environment Variables

| Variable      | Default | Description                |
|---------------|---------|----------------------------|
| `PORT`        | `4000`  | HTTP server port           |
| `CORS_ORIGIN` | `*`     | CORS origin restriction    |

## API Overview

### REST Endpoints

| Method | Endpoint                                      | Description                          |
|--------|-----------------------------------------------|--------------------------------------|
| GET    | `/health`                                     | Health check                         |
| GET    | `/api/conversations`                          | List conversations                   |
| GET    | `/api/conversations/:id`                      | Get conversation                     |
| GET    | `/api/conversations/:id/messages?cursor=&limit=50` | Paginated messages            |
| GET    | `/api/conversations/:id/search?q=keyword`     | Search messages in conversation      |
| POST   | `/api/messages`                               | Create message (or thread reply)     |
| GET    | `/api/messages/:id`                           | Get message                          |
| GET    | `/api/messages/:id/replies`                   | Get thread replies                   |
| POST   | `/api/messages/:id/reactions`                 | Add emoji reaction                   |
| DELETE | `/api/messages/:id/reactions`                 | Remove emoji reaction                |
| GET    | `/api/ai/stream?conversationId=uuid`          | SSE mock AI token stream             |

### Socket.io Events

| Event             | Direction | Payload                              |
|-------------------|-----------|--------------------------------------|
| `room:join`       | C → S     | `{ conversationId }`                 |
| `room:leave`      | C → S     | `{ conversationId }`                 |
| `typing:start`    | C → S     | `{ conversationId }`                 |
| `typing:stop`     | C → S     | `{ conversationId }`                 |
| `message:created` | S → C     | Message object                       |
| `message:updated` | S → C     | Message object (reactions updated)   |
| `typing:update`   | S → C     | `{ conversationId, users: [...] }`   |

### Auth (Demo)

Pass `x-user-id` header in REST requests and Socket.io handshake to identify users. Defaults to the seeded demo user `user-1`.

## Tests

```bash
npm test
```

Runs Jest suites covering REST endpoints and Socket.io real-time events.
