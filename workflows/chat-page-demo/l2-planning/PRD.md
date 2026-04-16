# Product Requirements Document: Chat Page

## 1. Overview

This document defines the requirements for a modern, AI-ready chat page (聊天页面) designed as a reusable, embeddable module. The product targets SaaS teams, internal tooling groups, and startups that need a lightweight, self-hostable messaging UI with real-time capabilities and native AI streaming support.

## 2. Vision

Build a professional-grade chat page that combines:
- Discord-like real-time performance and UX patterns
- Twilio-like embeddability and API flexibility
- Native AI streaming UI (markdown rendering, thinking indicators, citation chips)

## 3. User Stories

### US-1: Send and Receive Messages
As a user, I want to send text messages and see them appear instantly in the conversation so that I can communicate in real time.

### US-2: View Message History
As a user, I want to scroll through past messages with smooth infinite scroll so that I can catch up on conversations without performance degradation.

### US-3: Mobile-First Access
As a mobile user, I want the chat page to be fully responsive and touch-optimized so that I can chat on any device.

### US-4: AI Assistant Interaction
As a user, I want to receive streaming AI responses with markdown formatting and source citations so that I can interact with an AI copilot inside the chat.

### US-5: Typing Awareness
As a user, I want to see when another participant is typing so that I know a response is coming.

### US-6: Threaded Replies
As a user, I want to reply to a specific message in a thread so that side conversations do not clutter the main channel.

### US-7: Message Reactions
As a user, I want to add emoji reactions to messages so that I can quickly acknowledge or express sentiment.

### US-8: Search History
As a user, I want to search for keywords in message history so that I can find past information quickly.

### US-9: Embed as Module
As a developer, I want to embed the chat page into my existing React application with minimal configuration so that I can ship faster.

## 4. Features

| ID | Feature | Priority | Notes |
|----|---------|----------|-------|
| F-1 | Real-time messaging | P0 | WebSocket-based send/receive with <150 ms p99 latency |
| F-2 | Infinite scroll history | P0 | Virtualized list supporting 10k+ messages |
| F-3 | Responsive layout | P0 | Mobile-first, breakpoints 320px–1920px |
| F-4 | AI streaming responses | P0 | SSE-based markdown token streaming |
| F-5 | Typing indicators | P1 | Per-conversation ephemeral state |
| F-6 | Threaded replies | P1 | 1-level threading with thread pane |
| F-7 | Emoji reactions | P1 | Unicode emoji picker, limited to 5 per message |
| F-8 | Message search | P1 | Client-side keyword search for demo; API contract for server-side |
| F-9 | Rich media previews | P2 | URL unfurling (open-graph) for links |
| F-10 | Dark / light theme | P2 | CSS variable-based theming |

## 5. UI/UX Requirements

### 5.1 Layout
- Three-zone layout on desktop:
  1. **Sidebar** (collapsible): conversation list, search input
  2. **Main Chat Area**: message list, composer
  3. **Thread Pane** (slide-over): replies to selected message
- On mobile (<768px): bottom navigation or drawer pattern for conversations

### 5.2 Message List
- Newest message at the bottom
- Auto-scroll to bottom on new messages unless user has scrolled up
- Bubble style with avatar, display name, timestamp, and status indicator
- Group consecutive messages from the same sender (within 5 minutes)

### 5.3 Composer
- Multi-line textarea with auto-resize (max 6 lines)
- Send on Enter; Shift+Enter for new line
- Attachment button (file upload stub for demo)
- Emoji button (native picker or lightweight library)

### 5.4 AI Message Rendering
- Streaming markdown with syntax-highlighted code blocks
- Inline citation chips linking to sources
- Thinking / loading indicator during generation
- Error state with retry button

### 5.5 Accessibility
- WCAG 2.1 AA compliance
- ARIA live region for new messages
- Keyboard shortcuts: Ctrl/Cmd+K for search, Esc to close thread pane
- Focus management in composer and modals

## 6. Acceptance Criteria

### AC-1: Message Send
Given a connected user, when they type a message and press Enter, then the message appears in the message list within 150 ms with a "sent" status indicator.

### AC-2: History Load
Given a conversation with 1,000 messages, when the user scrolls to the top, then the next batch of 50 older messages loads in <100 ms without jank.

### AC-3: Mobile Responsiveness
Given a viewport width of 375 px, when the chat page loads, then all interactive elements are reachable, readable (font size >=16 px for inputs), and the layout does not overflow horizontally.

### AC-4: AI Streaming
Given an active AI assistant, when the backend streams tokens via SSE, then the UI renders partial markdown incrementally and completes within 2 s of the final token.

### AC-5: Threading
Given a message with replies, when the user clicks the reply count, then the thread pane opens showing all threaded messages in chronological order.

### AC-6: Search
Given a conversation with 500 messages, when the user searches for a keyword, then matching messages are highlighted and filtered within 300 ms.

### AC-7: Theming
Given the theme toggle, when the user switches from light to dark, then the entire UI updates without a page reload and respects `prefers-color-scheme` on first load.

## 7. Non-Functional Requirements

- **Performance**: FCP < 1.2 s, TTI < 2.5 s on 4G
- **Security**: XSS prevention via sanitized markdown, CSRF tokens on state-changing APIs, rate limiting (10 msg/s per user)
- **Browser Support**: Latest 2 versions of Chrome, Firefox, Safari, Edge
- **i18n**: UI strings externalized for future translation (default Simplified Chinese and English)
