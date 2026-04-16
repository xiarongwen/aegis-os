const express = require('express');
const { Store } = require('../lib/store');
const { sanitizeMarkdown } = require('../lib/sanitize');
const { CreateMessageSchema, ReactionSchema } = require('../lib/validators');

const router = express.Router();

function getCurrentUserId(req) {
  // Demo auth: use x-user-id header or fallback to seeded user
  return req.headers['x-user-id'] || 'user-1';
}

router.post('/', (req, res) => {
  const parsed = CreateMessageSchema.safeParse(req.body);
  if (!parsed.success) {
    return res.status(400).json({ error: parsed.error.errors });
  }

  const { conversationId, content, parentId } = parsed.data;
  const senderId = getCurrentUserId(req);

  const conv = Store.getConversationById(conversationId);
  if (!conv) return res.status(404).json({ error: 'Conversation not found' });

  if (parentId) {
    const parent = Store.getMessageById(parentId);
    if (!parent || parent.conversationId !== conversationId) {
      return res.status(404).json({ error: 'Parent message not found' });
    }
  }

  const cleanContent = sanitizeMarkdown(content);
  const msg = Store.createMessage({
    conversationId,
    parentId: parentId || null,
    senderId,
    content: cleanContent,
    status: 'sent',
  });

  const sender = Store.getUserById(senderId);
  const enriched = {
    ...msg,
    sender: sender
      ? { id: sender.id, name: sender.name, avatarUrl: sender.avatarUrl }
      : { id: senderId, name: 'Unknown', avatarUrl: null },
    reactions: [],
  };

  req.app.get('io').to(conversationId).emit('message:created', enriched);

  res.status(201).json(enriched);
});

router.get('/:id', (req, res) => {
  const msg = Store.getMessageById(req.params.id);
  if (!msg) return res.status(404).json({ error: 'Message not found' });
  const sender = Store.getUserById(msg.senderId);
  const reactions = Store.getReactionsForMessage(msg.id);
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
  res.json({
    ...msg,
    sender: sender
      ? { id: sender.id, name: sender.name, avatarUrl: sender.avatarUrl }
      : { id: msg.senderId, name: 'Unknown', avatarUrl: null },
    reactions: grouped,
  });
});

router.get('/:id/replies', (req, res) => {
  const parent = Store.getMessageById(req.params.id);
  if (!parent) return res.status(404).json({ error: 'Message not found' });
  const replies = Store.getThreadReplies(req.params.id).map((m) => {
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
  res.json({ replies });
});

router.post('/:id/reactions', (req, res) => {
  const parsed = ReactionSchema.safeParse(req.body);
  if (!parsed.success) {
    return res.status(400).json({ error: parsed.error.errors });
  }
  const { emoji } = parsed.data;
  const userId = getCurrentUserId(req);
  const message = Store.getMessageById(req.params.id);
  if (!message) return res.status(404).json({ error: 'Message not found' });

  try {
    Store.addReaction(message.id, userId, emoji);
  } catch (err) {
    if (err.code === 'REACTION_LIMIT') {
      return res.status(400).json({ error: err.message });
    }
    throw err;
  }

  const reactions = Store.getReactionsForMessage(message.id);
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

  const updated = { ...message, reactions: grouped };
  req.app.get('io').to(message.conversationId).emit('message:updated', updated);

  res.json({ reactions: grouped });
});

router.delete('/:id/reactions', (req, res) => {
  const { emoji } = req.body || {};
  if (!emoji) return res.status(400).json({ error: 'emoji is required' });
  const userId = getCurrentUserId(req);
  const message = Store.getMessageById(req.params.id);
  if (!message) return res.status(404).json({ error: 'Message not found' });

  Store.removeReaction(message.id, userId, emoji);

  const reactions = Store.getReactionsForMessage(message.id);
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

  const updated = { ...message, reactions: grouped };
  req.app.get('io').to(message.conversationId).emit('message:updated', updated);

  res.json({ reactions: grouped });
});

module.exports = router;
