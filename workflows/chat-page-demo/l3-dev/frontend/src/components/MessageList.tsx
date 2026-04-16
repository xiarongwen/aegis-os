import { useEffect, useRef, useState } from 'react';
import { useChatStore } from '../store';
import { fetchMessages, on } from '../mocks/api';
import { MessageItem } from './MessageItem';
import { TypingIndicator } from './TypingIndicator';
import type { Message } from '../types';

export function MessageList() {
  const activeId = useChatStore((s) => s.activeConversationId);
  const messages = useChatStore((s) => s.messages);
  const setMessages = useChatStore((s) => s.setMessages);
  const appendMessage = useChatStore((s) => s.appendMessage);
  const updateMessage = useChatStore((s) => s.updateMessage);
  // prependMessages reserved for future infinite scroll
  const searchQuery = useChatStore((s) => s.searchQuery);
  const setTypingUsers = useChatStore((s) => s.setTypingUsers);
  const setAiStreamingMessageId = useChatStore((s) => s.setAiStreamingMessageId);
  const appendAiToken = useChatStore((s) => s.appendAiToken);
  const listRef = useRef<HTMLDivElement>(null);
  const [atBottom, setAtBottom] = useState(true);
  const [hasNew, setHasNew] = useState(false);

  useEffect(() => {
    if (!activeId) return;
    fetchMessages(activeId).then((msgs) => {
      setMessages(msgs);
      setAtBottom(true);
    });
  }, [activeId, setMessages]);

  useEffect(() => {
    const unsubs: Array<() => void> = [];
    unsubs.push(
      on('message:created', (payload) => {
        const msg = payload as Message;
        if (msg.conversationId !== activeId) return;
        const existing = messages.find((m) => m.id === msg.id);
        if (existing) {
          updateMessage(msg.id, { status: msg.status, reactions: msg.reactions, content: msg.content });
        } else {
          appendMessage(msg);
        }
        if (msg.sender.id !== 'u-me') {
          if (atBottom) {
            scrollToBottom();
          } else {
            setHasNew(true);
          }
        }
      })
    );
    unsubs.push(
      on('typing:update', (payload) => {
        const data = payload as { conversationId: string; users: { id: string; name: string }[] };
        if (data.conversationId !== activeId) return;
        setTypingUsers(data.users);
      })
    );
    unsubs.push(
      on('ai:stream:start', (payload) => {
        const data = payload as { messageId: string };
        setAiStreamingMessageId(data.messageId);
      })
    );
    unsubs.push(
      on('ai:stream:token', (payload) => {
        const data = payload as { messageId: string; token: string };
        appendAiToken(data.token);
      })
    );
    unsubs.push(
      on('ai:stream:end', () => {
        setAiStreamingMessageId(null);
      })
    );
    return () => {
      unsubs.forEach((u) => u());
    };
  }, [activeId, messages, appendMessage, updateMessage, setTypingUsers, setAiStreamingMessageId, appendAiToken, atBottom]);

  useEffect(() => {
    if (atBottom) {
      scrollToBottom();
    }
  }, [messages.length, atBottom]);

  const scrollToBottom = () => {
    const el = listRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
      setHasNew(false);
    }
  };

  const handleScroll = () => {
    const el = listRef.current;
    if (!el) return;
    const bottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
    setAtBottom(bottom);
    if (bottom) setHasNew(false);
  };

  const filteredMessages = searchQuery.trim()
    ? messages.filter((m) => m.content.toLowerCase().includes(searchQuery.toLowerCase()))
    : messages;

  const grouped = groupMessages(filteredMessages);

  if (!activeId) {
    return (
      <div className="flex flex-1 items-center justify-center text-muted">
        请选择一个会话开始聊天
      </div>
    );
  }

  return (
    <div className="relative flex flex-1 flex-col overflow-hidden">
      <div
        ref={listRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto scroll-smooth"
        aria-live="polite"
        aria-atomic="false"
      >
        <div className="py-2">
          {grouped.map((group, gi) => (
            <div key={gi} className="mb-2">
              {group.map((m) => (
                <MessageItem key={m.id} message={m} highlightQuery={searchQuery} />
              ))}
            </div>
          ))}
          <TypingIndicator />
        </div>
      </div>

      {hasNew && (
        <button
          type="button"
          onClick={scrollToBottom}
          className="absolute bottom-4 left-1/2 -translate-x-1/2 rounded-full bg-primary px-3 py-1 text-xs font-medium text-primary-text shadow hover:bg-primary/90"
        >
          新消息
        </button>
      )}
    </div>
  );
}

function groupMessages(messages: Message[]) {
  const groups: Message[][] = [];
  let current: Message[] = [];
  messages.forEach((m, i) => {
    const prev = messages[i - 1];
    if (
      prev &&
      prev.sender.id === m.sender.id &&
      new Date(m.createdAt).getTime() - new Date(prev.createdAt).getTime() < 5 * 60 * 1000
    ) {
      current.push(m);
    } else {
      if (current.length) groups.push(current);
      current = [m];
    }
  });
  if (current.length) groups.push(current);
  return groups;
}
