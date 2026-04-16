export type User = {
  id: string;
  name: string;
  avatarUrl?: string;
};

export type Reaction = {
  emoji: string;
  count: number;
  userIds: string[];
};

export type MessageStatus = 'sending' | 'sent' | 'delivered' | 'failed';

export type Message = {
  id: string;
  conversationId: string;
  parentId?: string | null;
  sender: User;
  content: string;
  createdAt: string;
  status: MessageStatus;
  reactions: Reaction[];
};

export type Conversation = {
  id: string;
  title: string;
  lastMessageAt: string;
  unreadCount: number;
};

export type TypingUser = {
  id: string;
  name: string;
};
