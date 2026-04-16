const request = require('supertest');
const { app, server } = require('../src/index');
const { Store } = require('../src/lib/store');

afterAll(() => {
  server.close();
});

describe('Health', () => {
  test('GET /health returns ok', async () => {
    const res = await request(app).get('/health');
    expect(res.status).toBe(200);
    expect(res.body.status).toBe('ok');
  });
});

describe('Conversations', () => {
  test('GET /api/conversations returns list', async () => {
    const res = await request(app).get('/api/conversations');
    expect(res.status).toBe(200);
    expect(Array.isArray(res.body.conversations)).toBe(true);
    expect(res.body.conversations.length).toBeGreaterThan(0);
  });

  test('GET /api/conversations/:id returns conversation', async () => {
    const conv = Store.getConversations()[0];
    const res = await request(app).get(`/api/conversations/${conv.id}`);
    expect(res.status).toBe(200);
    expect(res.body.conversation.id).toBe(conv.id);
  });

  test('GET /api/conversations/:id/messages returns messages', async () => {
    const conv = Store.getConversations()[0];
    const res = await request(app).get(`/api/conversations/${conv.id}/messages`);
    expect(res.status).toBe(200);
    expect(Array.isArray(res.body.messages)).toBe(true);
  });

  test('GET /api/conversations/:id/search returns results', async () => {
    const conv = Store.getConversations()[0];
    const res = await request(app).get(`/api/conversations/${conv.id}/search?q=Welcome`);
    expect(res.status).toBe(200);
    expect(Array.isArray(res.body.results)).toBe(true);
    expect(res.body.results.length).toBeGreaterThan(0);
  });
});

describe('Messages', () => {
  test('POST /api/messages creates a message', async () => {
    const conv = Store.getConversations()[0];
    const res = await request(app)
      .post('/api/messages')
      .set('x-user-id', 'user-1')
      .send({ conversationId: conv.id, content: 'Hello world' });
    expect(res.status).toBe(201);
    expect(res.body.content).toBe('Hello world');
    expect(res.body.sender.id).toBe('user-1');
  });

  test('POST /api/messages rejects empty content', async () => {
    const conv = Store.getConversations()[0];
    const res = await request(app)
      .post('/api/messages')
      .set('x-user-id', 'user-1')
      .send({ conversationId: conv.id, content: '' });
    expect(res.status).toBe(400);
  });

  test('POST /api/messages with parentId creates thread reply', async () => {
    const conv = Store.getConversations()[0];
    const parent = Store.createMessage({
      conversationId: conv.id,
      senderId: 'user-1',
      content: 'Parent',
      status: 'sent',
    });
    const res = await request(app)
      .post('/api/messages')
      .set('x-user-id', 'user-1')
      .send({ conversationId: conv.id, content: 'Reply', parentId: parent.id });
    expect(res.status).toBe(201);
    expect(res.body.parentId).toBe(parent.id);
  });

  test('GET /api/messages/:id returns message', async () => {
    const conv = Store.getConversations()[0];
    const msg = Store.createMessage({
      conversationId: conv.id,
      senderId: 'user-1',
      content: 'Test msg',
      status: 'sent',
    });
    const res = await request(app).get(`/api/messages/${msg.id}`);
    expect(res.status).toBe(200);
    expect(res.body.id).toBe(msg.id);
  });

  test('GET /api/messages/:id/replies returns thread replies', async () => {
    const conv = Store.getConversations()[0];
    const parent = Store.createMessage({
      conversationId: conv.id,
      senderId: 'user-1',
      content: 'Parent',
      status: 'sent',
    });
    Store.createMessage({
      conversationId: conv.id,
      parentId: parent.id,
      senderId: 'user-1',
      content: 'Reply 1',
      status: 'sent',
    });
    const res = await request(app).get(`/api/messages/${parent.id}/replies`);
    expect(res.status).toBe(200);
    expect(res.body.replies.length).toBe(1);
  });

  test('POST /api/messages/:id/reactions adds reaction', async () => {
    const conv = Store.getConversations()[0];
    const msg = Store.createMessage({
      conversationId: conv.id,
      senderId: 'user-1',
      content: 'React to me',
      status: 'sent',
    });
    const res = await request(app)
      .post(`/api/messages/${msg.id}/reactions`)
      .set('x-user-id', 'user-1')
      .send({ emoji: '👍' });
    expect(res.status).toBe(200);
    expect(res.body.reactions[0].emoji).toBe('👍');
  });

  test('DELETE /api/messages/:id/reactions removes reaction', async () => {
    const conv = Store.getConversations()[0];
    const msg = Store.createMessage({
      conversationId: conv.id,
      senderId: 'user-1',
      content: 'React to me',
      status: 'sent',
    });
    await request(app)
      .post(`/api/messages/${msg.id}/reactions`)
      .set('x-user-id', 'user-1')
      .send({ emoji: '👍' });
    const res = await request(app)
      .delete(`/api/messages/${msg.id}/reactions`)
      .set('x-user-id', 'user-1')
      .send({ emoji: '👍' });
    expect(res.status).toBe(200);
    expect(res.body.reactions.length).toBe(0);
  });
});

describe('AI SSE', () => {
  test('GET /api/ai/stream requires conversationId', async () => {
    const res = await request(app).get('/api/ai/stream');
    expect(res.status).toBe(400);
  });

  test('GET /api/ai/stream returns SSE', (done) => {
    const conv = Store.getConversations()[0];
    const req = request(app).get(`/api/ai/stream?conversationId=${conv.id}`);
    req
      .buffer()
      .parse((res, cb) => {
        res.data = '';
        res.on('data', (chunk) => {
          res.data += chunk;
        });
        res.on('end', () => cb(null, res.data));
      })
      .end((err, res) => {
        expect(res.status).toBe(200);
        expect(res.headers['content-type']).toMatch(/text\/event-stream/);
        expect(res.body).toContain('data:');
        done();
      });
  });
});
