import type { Conversation, Message, Reaction, User } from '../types';

const currentUser: User = {
  id: 'u-me',
  name: '我',
  avatarUrl: 'https://api.dicebear.com/7.x/avataaars/svg?seed=me',
};

const assistantUser: User = {
  id: 'u-ai',
  name: 'AI 助手',
  avatarUrl: 'https://api.dicebear.com/7.x/bottts/svg?seed=ai',
};

const otherUsers: User[] = [
  { id: 'u-1', name: 'Alice', avatarUrl: 'https://api.dicebear.com/7.x/avataaars/svg?seed=Alice' },
  { id: 'u-2', name: 'Bob', avatarUrl: 'https://api.dicebear.com/7.x/avataaars/svg?seed=Bob' },
];

let messageIdCounter = 1;

function makeId(prefix: string) {
  return `${prefix}-${Date.now()}-${messageIdCounter++}`;
}

const conversations: Conversation[] = [
  { id: 'c-1', title: '产品设计讨论', lastMessageAt: new Date().toISOString(), unreadCount: 2 },
  { id: 'c-2', title: '前端技术分享', lastMessageAt: new Date(Date.now() - 86400000).toISOString(), unreadCount: 0 },
];

const messagesByConversation: Record<string, Message[]> = {
  'c-1': [
    {
      id: makeId('m'),
      conversationId: 'c-1',
      sender: otherUsers[0],
      content: '大家好，今天我们来讨论一下新功能的交互方案。',
      createdAt: new Date(Date.now() - 1000 * 60 * 60).toISOString(),
      status: 'delivered',
      reactions: [{ emoji: '👍', count: 2, userIds: ['u-me', 'u-2'] }],
    },
    {
      id: makeId('m'),
      conversationId: 'c-1',
      sender: currentUser,
      content: '我已经把 PRD 发在群里了，大家可以先看看。',
      createdAt: new Date(Date.now() - 1000 * 60 * 30).toISOString(),
      status: 'delivered',
      reactions: [],
    },
    {
      id: makeId('m'),
      conversationId: 'c-1',
      sender: assistantUser,
      content: '收到！我可以帮大家总结 PRD 的关键要点，也可以回答关于实现的问题。',
      createdAt: new Date(Date.now() - 1000 * 60 * 25).toISOString(),
      status: 'delivered',
      reactions: [{ emoji: '🎉', count: 1, userIds: ['u-1'] }],
    },
  ],
  'c-2': [
    {
      id: makeId('m'),
      conversationId: 'c-2',
      sender: otherUsers[1],
      content: '有人用过新的 React Compiler 吗？',
      createdAt: new Date(Date.now() - 1000 * 60 * 60 * 2).toISOString(),
      status: 'delivered',
      reactions: [],
    },
  ],
};

const listeners: Record<string, Array<(payload: unknown) => void>> = {};

function emit(event: string, payload: unknown) {
  (listeners[event] || []).forEach((fn) => fn(payload));
}

export function on(event: string, fn: (payload: unknown) => void) {
  if (!listeners[event]) listeners[event] = [];
  listeners[event].push(fn);
  return () => {
    listeners[event] = listeners[event].filter((l) => l !== fn);
  };
}

export async function fetchConversations(): Promise<Conversation[]> {
  await delay(200);
  return conversations;
}

export async function fetchMessages(conversationId: string): Promise<Message[]> {
  await delay(300);
  return messagesByConversation[conversationId] || [];
}

export async function postMessage(
  conversationId: string,
  content: string,
  parentId?: string | null
): Promise<Message> {
  await delay(150);
  const message: Message = {
    id: makeId('m'),
    conversationId,
    parentId: parentId || null,
    sender: currentUser,
    content,
    createdAt: new Date().toISOString(),
    status: 'sent',
    reactions: [],
  };
  if (!messagesByConversation[conversationId]) {
    messagesByConversation[conversationId] = [];
  }
  messagesByConversation[conversationId].push(message);
  emit('message:created', message);

  // Simulate AI reply if message contains @assistant or just randomly in demo
  if (content.includes('@assistant') || Math.random() > 0.5) {
    setTimeout(() => simulateAiReply(conversationId, parentId || null), 800);
  } else {
    // Simulate other user typing
    setTimeout(() => {
      emit('typing:update', { conversationId, users: [otherUsers[0]] });
      setTimeout(() => {
        emit('typing:update', { conversationId, users: [] });
        const reply: Message = {
          id: makeId('m'),
          conversationId,
          parentId: parentId || null,
          sender: otherUsers[0],
          content: '收到，稍后回复你。',
          createdAt: new Date().toISOString(),
          status: 'delivered',
          reactions: [],
        };
        messagesByConversation[conversationId].push(reply);
        emit('message:created', reply);
      }, 1200);
    }, 400);
  }

  return message;
}

function simulateAiReply(conversationId: string, parentId: string | null) {
  const id = makeId('m');
  const message: Message = {
    id,
    conversationId,
    parentId,
    sender: assistantUser,
    content: '',
    createdAt: new Date().toISOString(),
    status: 'delivered',
    reactions: [],
  };
  if (!messagesByConversation[conversationId]) {
    messagesByConversation[conversationId] = [];
  }
  messagesByConversation[conversationId].push(message);
  emit('ai:stream:start', { messageId: id });

  const tokens = ['好的', '，', '这是', '一个', ' **Markdown** ', ' 示例回答。\n\n', '- 要点一\n', '- 要点二\n', '\n```ts\n', 'const x = 1;\n', '```\n'];
  let i = 0;
  const interval = setInterval(() => {
    if (i >= tokens.length) {
      clearInterval(interval);
      emit('ai:stream:end', { messageId: id });
      emit('message:created', message);
      return;
    }
    emit('ai:stream:token', { messageId: id, token: tokens[i] });
    i++;
  }, 300);
}

export async function postReaction(messageId: string, emoji: string): Promise<Reaction[]> {
  await delay(100);
  for (const conv of Object.values(messagesByConversation)) {
    const msg = conv.find((m) => m.id === messageId);
    if (msg) {
      const existing = msg.reactions.find((r) => r.emoji === emoji);
      if (existing) {
        if (!existing.userIds.includes(currentUser.id)) {
          existing.count += 1;
          existing.userIds.push(currentUser.id);
        }
      } else {
        if (msg.reactions.length < 5) {
          msg.reactions.push({ emoji, count: 1, userIds: [currentUser.id] });
        }
      }
      emit('message:updated', msg);
      return msg.reactions;
    }
  }
  return [];
}

export async function searchMessages(conversationId: string, q: string): Promise<{ messageId: string; snippet: string }[]> {
  await delay(100);
  const msgs = messagesByConversation[conversationId] || [];
  const results = msgs
    .filter((m) => m.content.toLowerCase().includes(q.toLowerCase()))
    .map((m) => ({ messageId: m.id, snippet: m.content.slice(0, 80) }));
  return results;
}

function delay(ms: number) {
  return new Promise((res) => setTimeout(res, ms));
}
