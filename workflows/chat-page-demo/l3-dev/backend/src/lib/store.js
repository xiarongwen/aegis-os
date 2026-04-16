/**
 * In-memory data store for demo purposes.
 * Keeps users, conversations, messages, and reactions in memory.
 */

const { v4: uuidv4 } = require('uuid');

class Store {
  constructor() {
    this.users = new Map();
    this.conversations = new Map();
    this.messages = new Map();
    this.reactions = new Map();
    this.typing = new Map(); // conversationId -> { userId -> timeoutId }

    // Seed a default user and conversation for quick demo
    const defaultUser = {
      id: 'user-1',
      name: 'Demo User',
      avatarUrl: 'https://api.dicebear.com/7.x/avataaars/svg?seed=Demo',
      createdAt: new Date().toISOString(),
    };
    this.users.set(defaultUser.id, defaultUser);

    const defaultConv = {
      id: 'conv-1',
      title: 'General',
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    this.conversations.set(defaultConv.id, defaultConv);

    const welcomeMsg = {
      id: uuidv4(),
      conversationId: defaultConv.id,
      parentId: null,
      senderId: defaultUser.id,
      content: 'Welcome to the chat page demo! 👋',
      createdAt: new Date().toISOString(),
      status: 'sent',
    };
    this.messages.set(welcomeMsg.id, welcomeMsg);
  }

  // Users
  getUsers() {
    return Array.from(this.users.values());
  }

  getUserById(id) {
    return this.users.get(id) || null;
  }

  createUser(data) {
    const user = {
      id: uuidv4(),
      name: data.name || 'Anonymous',
      avatarUrl: data.avatarUrl || null,
      createdAt: new Date().toISOString(),
    };
    this.users.set(user.id, user);
    return user;
  }

  // Conversations
  getConversations() {
    return Array.from(this.conversations.values()).sort(
      (a, b) => new Date(b.updatedAt) - new Date(a.updatedAt)
    );
  }

  getConversationById(id) {
    return this.conversations.get(id) || null;
  }

  createConversation(data) {
    const conv = {
      id: uuidv4(),
      title: data.title || 'Untitled',
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    this.conversations.set(conv.id, conv);
    return conv;
  }

  touchConversation(id) {
    const conv = this.conversations.get(id);
    if (conv) {
      conv.updatedAt = new Date().toISOString();
    }
  }

  // Messages
  getMessagesForConversation(conversationId, cursor = null, limit = 50) {
    const all = Array.from(this.messages.values()).filter(
      (m) => m.conversationId === conversationId
    );
    all.sort((a, b) => new Date(a.createdAt) - new Date(b.createdAt));

    let startIndex = 0;
    if (cursor) {
      const idx = all.findIndex((m) => m.id === cursor);
      if (idx !== -1) startIndex = idx + 1;
    }

    const page = all.slice(startIndex, startIndex + limit);
    const nextCursor =
      startIndex + limit < all.length ? page[page.length - 1]?.id || null : null;

    return { messages: page, nextCursor };
  }

  getMessageById(id) {
    return this.messages.get(id) || null;
  }

  getThreadReplies(parentId) {
    const all = Array.from(this.messages.values()).filter(
      (m) => m.parentId === parentId
    );
    all.sort((a, b) => new Date(a.createdAt) - new Date(b.createdAt));
    return all;
  }

  createMessage(data) {
    const msg = {
      id: uuidv4(),
      conversationId: data.conversationId,
      parentId: data.parentId || null,
      senderId: data.senderId,
      content: data.content,
      createdAt: new Date().toISOString(),
      status: data.status || 'sent',
    };
    this.messages.set(msg.id, msg);
    this.touchConversation(data.conversationId);
    return msg;
  }

  updateMessage(id, updates) {
    const msg = this.messages.get(id);
    if (!msg) return null;
    Object.assign(msg, updates);
    return msg;
  }

  // Reactions
  getReactionsForMessage(messageId) {
    return Array.from(this.reactions.values()).filter(
      (r) => r.messageId === messageId
    );
  }

  addReaction(messageId, userId, emoji) {
    const existing = Array.from(this.reactions.values()).find(
      (r) => r.messageId === messageId && r.userId === userId && r.emoji === emoji
    );
    if (existing) return existing;

    // Limit 5 reactions per message
    const current = this.getReactionsForMessage(messageId);
    if (current.length >= 5) {
      const err = new Error('Max 5 reactions per message');
      err.code = 'REACTION_LIMIT';
      throw err;
    }

    const reaction = {
      id: uuidv4(),
      messageId,
      userId,
      emoji,
      createdAt: new Date().toISOString(),
    };
    this.reactions.set(reaction.id, reaction);
    return reaction;
  }

  removeReaction(messageId, userId, emoji) {
    const key = Array.from(this.reactions.values()).find(
      (r) => r.messageId === messageId && r.userId === userId && r.emoji === emoji
    )?.id;
    if (key) {
      this.reactions.delete(key);
      return true;
    }
    return false;
  }

  // Search
  searchMessages(conversationId, query) {
    const q = query.toLowerCase();
    const results = Array.from(this.messages.values()).filter(
      (m) => m.conversationId === conversationId && m.content.toLowerCase().includes(q)
    );
    results.sort((a, b) => new Date(a.createdAt) - new Date(b.createdAt));
    return results.map((m) => ({
      messageId: m.id,
      snippet: m.content,
    }));
  }

  // Typing
  setTyping(conversationId, userId, cb, ttlMs = 5000) {
    if (!this.typing.has(conversationId)) {
      this.typing.set(conversationId, new Map());
    }
    const room = this.typing.get(conversationId);
    if (room.has(userId)) {
      clearTimeout(room.get(userId));
    }
    const t = setTimeout(() => {
      room.delete(userId);
      cb();
    }, ttlMs);
    room.set(userId, t);
  }

  clearTyping(conversationId, userId) {
    const room = this.typing.get(conversationId);
    if (room && room.has(userId)) {
      clearTimeout(room.get(userId));
      room.delete(userId);
    }
  }

  getTypingUsers(conversationId) {
    const room = this.typing.get(conversationId);
    if (!room) return [];
    return Array.from(room.keys());
  }
}

module.exports = { Store: new Store() };
