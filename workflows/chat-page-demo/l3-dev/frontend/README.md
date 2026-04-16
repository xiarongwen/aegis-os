# Chat Page Frontend

A modern, responsive chat page built with React 18, TypeScript, Vite, and Tailwind CSS. This is the frontend implementation for the AEGIS `chat-page-demo` workflow.

## Features

- Real-time messaging UI with optimistic updates
- Responsive three-zone layout (sidebar, main chat, thread pane)
- Mobile-first design with drawer navigation on small screens
- Dark / light / system theme toggle with CSS variable theming
- Message search with client-side filtering and highlighting
- Threaded replies with slide-over thread pane
- Emoji reactions (max 5 per message)
- AI streaming message rendering with markdown support
- Typing indicators
- Mock API / Socket layer for fully demoable UI without a backend

## Tech Stack

- React 18 + TypeScript
- Vite (build + dev server)
- Tailwind CSS + @tailwindcss/forms
- Zustand (state management)
- react-markdown + remark-gfm (markdown rendering)
- Lucide React (icons)
- Vitest + React Testing Library (unit tests)

## Project Structure

```
src/
  components/          # React components
    ChatPage.tsx
    ChatMain.tsx
    ConversationSidebar.tsx
    MessageList.tsx
    MessageItem.tsx
    Composer.tsx
    ThreadPane.tsx
    ThemeToggle.tsx
    TypingIndicator.tsx
  hooks/
    useTheme.ts
  mocks/
    api.ts             # Mock REST + Socket-like event layer
  store/
    index.ts           # Zustand store
  types/
    index.ts           # Shared TypeScript types
  utils/
    time.ts
  test/
    setup.ts           # Test setup (jest-dom, matchMedia mock)
  components/__tests__/# Unit tests
```

## Available Scripts

```bash
# Install dependencies
npm install

# Start dev server
npm run dev

# Build for production
npm run build

# Run unit tests
npm run test

# Run linter
npm run lint

# Preview production build
npm run preview
```

## Getting Started

1. Ensure you are in the frontend directory:
   ```bash
   cd workflows/chat-page-demo/l3-dev/frontend
   ```
2. Install dependencies:
   ```bash
   npm install
   ```
3. Start the dev server:
   ```bash
   npm run dev
   ```
4. Open the URL shown in the terminal (usually `http://localhost:5173`).

## Keyboard Shortcuts

- `Ctrl/Cmd + K` — Focus message search
- `Esc` — Close thread pane
- `Enter` — Send message
- `Shift + Enter` — Insert new line in composer

## Mock Behavior

The mock API layer (`src/mocks/api.ts`) simulates:
- Fetching conversations and messages
- Sending messages with optimistic updates
- Receiving replies from other users or the AI assistant
- AI SSE streaming with token-by-token markdown updates
- Typing indicators
- Emoji reactions
- Message search

No backend server is required to demo the UI.

## Theming

The app supports three theme modes: light, dark, and system. The active theme is applied via a `dark` class on `<html>`, and colors are driven by CSS custom properties defined in `src/index.css`.

## License

Internal demo project for AEGIS.
