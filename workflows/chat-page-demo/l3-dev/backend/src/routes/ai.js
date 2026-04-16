const express = require('express');
const { Store } = require('../lib/store');
const { v4: uuidv4 } = require('uuid');

const router = express.Router();

function getCurrentUserId(req) {
  return req.headers['x-user-id'] || 'user-1';
}

router.get('/stream', (req, res) => {
  const { conversationId } = req.query;
  if (!conversationId) {
    return res.status(400).json({ error: 'conversationId is required' });
  }
  const conv = Store.getConversationById(conversationId);
  if (!conv) return res.status(404).json({ error: 'Conversation not found' });

  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');

  const tokens = [
    'Hello! ',
    'This ',
    'is ',
    'a ',
    'mock ',
    'AI ',
    'streaming ',
    'response. ',
    'It ',
    'supports ',
    '**markdown** ',
    'and ',
    '`code` ',
    'formatting.',
  ];

  let index = 0;
  const interval = setInterval(() => {
    if (index >= tokens.length) {
      const aiMessageId = uuidv4();
      const aiUser = Store.getUserById('user-1'); // In real app, use AI assistant user
      const msg = Store.createMessage({
        conversationId,
        parentId: null,
        senderId: 'user-1',
        content: tokens.join(''),
        status: 'sent',
      });

      const enriched = {
        ...msg,
        sender: aiUser
          ? { id: aiUser.id, name: 'AI Assistant', avatarUrl: aiUser.avatarUrl }
          : { id: 'user-1', name: 'AI Assistant', avatarUrl: null },
        reactions: [],
      };

      req.app.get('io').to(conversationId).emit('message:created', enriched);

      res.write(`data: ${JSON.stringify({ done: true, messageId: msg.id })}\n\n`);
      clearInterval(interval);
      res.end();
      return;
    }
    res.write(`data: ${JSON.stringify({ token: tokens[index] })}\n\n`);
    index += 1;
  }, 150);

  req.on('close', () => {
    clearInterval(interval);
  });
});

module.exports = router;
