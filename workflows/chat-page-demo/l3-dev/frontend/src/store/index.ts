import { create } from 'zustand';
import type { Conversation, Message, TypingUser } from '../types';

export type Theme = 'light' | 'dark' | 'system';

export type ChatStore = {
  theme: Theme;
  setTheme: (theme: Theme) => void;

  conversations: Conversation[];
  setConversations: (conversations: Conversation[]) => void;
  activeConversationId: string | null;
  setActiveConversationId: (id: string | null) => void;

  messages: Message[];
  setMessages: (messages: Message[]) => void;
  appendMessage: (message: Message) => void;
  updateMessage: (id: string, patch: Partial<Message>) => void;
  prependMessages: (messages: Message[]) => void;

  searchQuery: string;
  setSearchQuery: (q: string) => void;

  typingUsers: TypingUser[];
  setTypingUsers: (users: TypingUser[]) => void;

  threadParentId: string | null;
  setThreadParentId: (id: string | null) => void;

  aiStreamingMessageId: string | null;
  setAiStreamingMessageId: (id: string | null) => void;
  appendAiToken: (token: string) => void;
};

export const useChatStore = create<ChatStore>((set) => ({
  theme: 'system',
  setTheme: (theme) => set({ theme }),

  conversations: [],
  setConversations: (conversations) => set({ conversations }),
  activeConversationId: null,
  setActiveConversationId: (id) => set({ activeConversationId: id }),

  messages: [],
  setMessages: (messages) => set({ messages }),
  appendMessage: (message) =>
    set((state) => {
      const exists = state.messages.find((m) => m.id === message.id);
      if (exists) return state;
      return { messages: [...state.messages, message] };
    }),
  updateMessage: (id, patch) =>
    set((state) => ({
      messages: state.messages.map((m) => (m.id === id ? { ...m, ...patch } : m)),
    })),
  prependMessages: (messages) =>
    set((state) => {
      const existingIds = new Set(state.messages.map((m) => m.id));
      const newMessages = messages.filter((m) => !existingIds.has(m.id));
      return { messages: [...newMessages, ...state.messages] };
    }),

  searchQuery: '',
  setSearchQuery: (q) => set({ searchQuery: q }),

  typingUsers: [],
  setTypingUsers: (users) => set({ typingUsers: users }),

  threadParentId: null,
  setThreadParentId: (id) => set({ threadParentId: id }),

  aiStreamingMessageId: null,
  setAiStreamingMessageId: (id) => set({ aiStreamingMessageId: id }),
  appendAiToken: (token) =>
    set((state) => {
      if (!state.aiStreamingMessageId) return state;
      return {
        messages: state.messages.map((m) =>
          m.id === state.aiStreamingMessageId
            ? { ...m, content: m.content + token }
            : m
        ),
      };
    }),
}));
