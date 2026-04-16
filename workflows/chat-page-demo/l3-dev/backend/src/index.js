const express = require('express');
const http = require('http');
const { Server } = require('socket.io');
const cors = require('cors');
const helmet = require('helmet');
const rateLimit = require('express-rate-limit');

const conversationRoutes = require('./routes/conversations');
const messageRoutes = require('./routes/messages');
const aiRoutes = require('./routes/ai');
const { Store } = require('./lib/store');

const PORT = process.env.PORT || 4000;
const CORS_ORIGIN = process.env.CORS_ORIGIN || '*';

const app = express();
const server = http.createServer(app);
const io = new Server(server, {
  cors: { origin: CORS_ORIGIN },
  transports: ['websocket', 'polling'],
});

app.set('io', io);

app.use(helmet());
app.use(cors({ origin: CORS_ORIGIN }));
app.use(express.json({ limit: '1mb' }));

const generalLimiter = rateLimit({
  windowMs: 60 * 1000,
  max: 120,
  standardHeaders: true,
  legacyHeaders: false,
});
app.use(generalLimiter);

const messageLimiter = rateLimit({
  windowMs: 1000,
  max: 10,
  standardHeaders: true,
  legacyHeaders: false,
  keyGenerator: (req) => req.headers['x-user-id'] || req.ip,
  handler: (_req, res) => res.status(429).json({ error: 'Too many messages, please slow down.' }),
});
app.use('/api/messages', messageLimiter);

app.use('/api/conversations', conversationRoutes);
app.use('/api/messages', messageRoutes);
app.use('/api/ai', aiRoutes);

app.get('/health', (_req, res) => res.json({ status: 'ok' }));

io.on('connection', (socket) => {
  socket.on('room:join', ({ conversationId }) => {
    if (!conversationId) return;
    socket.join(conversationId);
  });

  socket.on('room:leave', ({ conversationId }) => {
    if (!conversationId) return;
    socket.leave(conversationId);
  });

  socket.on('typing:start', ({ conversationId }) => {
    if (!conversationId) return;
    const userId = socket.handshake.headers['x-user-id'] || 'user-1';
    const user = Store.getUserById(userId);
    Store.setTyping(conversationId, userId, () => {
      broadcastTyping(conversationId);
    });
    broadcastTyping(conversationId);
  });

  socket.on('typing:stop', ({ conversationId }) => {
    if (!conversationId) return;
    const userId = socket.handshake.headers['x-user-id'] || 'user-1';
    Store.clearTyping(conversationId, userId);
    broadcastTyping(conversationId);
  });

  socket.on('disconnect', () => {
    // No per-socket cleanup needed for in-memory demo
  });
});

function broadcastTyping(conversationId) {
  const userIds = Store.getTypingUsers(conversationId);
  const users = userIds.map((id) => {
    const u = Store.getUserById(id);
    return u ? { id: u.id, name: u.name } : { id, name: 'Unknown' };
  });
  io.to(conversationId).emit('typing:update', { conversationId, users });
}

server.listen(PORT, () => {
  console.log(`Server listening on port ${PORT}`);
});

module.exports = { app, server, io };
