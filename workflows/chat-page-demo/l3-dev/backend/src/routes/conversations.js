const express = require('express');
const { Store } = require('../lib/store');

const router = express.Router();

function enrichConversation(conv) {
  const messages = Array.from(Store.messages.values()).filter(
    (m) => m.conversationId === conv.id
  );
  const lastMessageAt = messages.length
    ? messages.sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt))[0].createdAt
    : conv.updatedAt;
  return {
    id: conv.id,
    title: conv.title,
    lastMessageAt,
    unreadCount: 0,
  };
}

router.get('/', (_req, res) => {
  const conversations = Store.getConversations().map(enrichConversation);
  res.json({ conversations });
});

router.get('/:id', (req, res) => {
  const conv = Store.getConversationById(req.params.id);
  if (!conv) return res.status(404).json({ error: 'Conversation not found' });
  res.json({ conversation: enrichConversation(conv) });
});

router.get('/:id/messages', (req, res) => {
  const { id } = req.params;
  const cursor = req.query.cursor || null;
  const limit = Math.min(parseInt(req.query.limit || '50', 10), 100);
  const conv = Store.getConversationById(id);
  if (!conv) return res.status(404).json({ error: 'Conversation not found' });

  const { messages, nextCursor } = Store.getMessagesForConversation(id, cursor, limit);

  const enriched = messages.map((m) => {
    const sender = Store.getUserById(m.senderId);
    const reactions = Store.getReactionsForMessage(m.id);
    const grouped = reactions.reduce((acc, r) => {
      const existing = acc.find((x) => x.emoji === r.emoji);
      if (existing) {
        existing.count += 1;
        existing.userIds.push(r.userId);
      } else {
        acc.push({ emoji: r.emoji, count: 1, userIds: [r.userId] });
      }
      return acc;
    }, []);
    return {
      ...m,
      sender: sender
        ? { id: sender.id, name: sender.name, avatarUrl: sender.avatarUrl }
        : { id: m.senderId, name: 'Unknown', avatarUrl: null },
      reactions: grouped,
    };
  });

  res.json({ messages: enriched, nextCursor });
});

router.get('/:id/search', (req, res) => {
  const { id } = req.params;
  const q = req.query.q || '';
  if (!q.trim()) return res.json({ results: [] });
  const conv = Store.getConversationById(id);
  if (!conv) return res.status(404).json({ error: 'Conversation not found' });
  const results = Store.searchMessages(id, q.trim());
  res.json({ results });
});

module.exports = router;
