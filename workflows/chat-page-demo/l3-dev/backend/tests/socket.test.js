const { createServer } = require("http");
const { Server } = require("socket.io");
const Client = require("socket.io-client");
const { Store } = require("../src/lib/store");

describe("Socket.io", () => {
  let io, serverSocket, clientSocket;

  beforeAll((done) => {
    const httpServer = createServer();
    io = new Server(httpServer, {
      cors: { origin: "*" },
      transports: ["websocket"],
    });
    io.on("connection", (socket) => {
      serverSocket = socket;
      socket.on("room:join", ({ conversationId }) => {
        socket.join(conversationId);
      });
      socket.on("room:leave", ({ conversationId }) => {
        socket.leave(conversationId);
      });
      socket.on("typing:start", ({ conversationId }) => {
        const userId = socket.handshake.headers["x-user-id"] || "user-1";
        const user = Store.getUserById(userId);
        Store.setTyping(conversationId, userId, () => {
          broadcastTyping(conversationId);
        });
        broadcastTyping(conversationId);
      });
      socket.on("typing:stop", ({ conversationId }) => {
        const userId = socket.handshake.headers["x-user-id"] || "user-1";
        Store.clearTyping(conversationId, userId);
        broadcastTyping(conversationId);
      });
    });

    function broadcastTyping(conversationId) {
      const userIds = Store.getTypingUsers(conversationId);
      const users = userIds.map((id) => {
        const u = Store.getUserById(id);
        return u ? { id: u.id, name: u.name } : { id, name: "Unknown" };
      });
      io.to(conversationId).emit("typing:update", { conversationId, users });
    }

    httpServer.listen(() => {
      const port = httpServer.address().port;
      clientSocket = Client(`http://localhost:${port}`, {
        transports: ["websocket"],
      });
      clientSocket.on("connect", done);
    });
  });

  afterAll(() => {
    io.close();
    clientSocket.close();
  });

  test("room:join and room:leave", (done) => {
    clientSocket.emit("room:join", { conversationId: "conv-1" });
    setTimeout(() => {
      clientSocket.emit("room:leave", { conversationId: "conv-1" });
      done();
    }, 100);
  });

  test("typing:start and typing:update", (done) => {
    clientSocket.emit("room:join", { conversationId: "conv-1" });
    clientSocket.on("typing:update", (data) => {
      expect(data.conversationId).toBe("conv-1");
      if (data.users.length > 0) {
        expect(data.users[0].id).toBe("user-1");
        clientSocket.off("typing:update");
        done();
      }
    });
    clientSocket.emit("typing:start", { conversationId: "conv-1" });
  });

  test("typing:stop clears typing state", (done) => {
    clientSocket.emit("room:join", { conversationId: "conv-1" });
    clientSocket.emit("typing:start", { conversationId: "conv-1" });
    setTimeout(() => {
      clientSocket.emit("typing:stop", { conversationId: "conv-1" });
      clientSocket.on("typing:update", (data) => {
        if (data.conversationId === "conv-1" && data.users.length === 0) {
          clientSocket.off("typing:update");
          done();
        }
      });
    }, 100);
  });
});
