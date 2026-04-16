import { useRef, useState } from 'react';
import { Send, Paperclip } from 'lucide-react';
import { postMessage } from '../mocks/api';
import { useChatStore } from '../store';

export function Composer({ parentId, placeholder = '输入消息…' }: { parentId?: string | null; placeholder?: string }) {
  const activeId = useChatStore((s) => s.activeConversationId);
  const appendMessage = useChatStore((s) => s.appendMessage);
  const updateMessage = useChatStore((s) => s.updateMessage);
  const [text, setText] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const send = async () => {
    if (!activeId || !text.trim()) return;
    const content = text.trim();
    setText('');
    const tempId = `temp-${Date.now()}`;
    const optimistic = {
      id: tempId,
      conversationId: activeId,
      parentId: parentId || null,
      sender: { id: 'u-me', name: '我', avatarUrl: 'https://api.dicebear.com/7.x/avataaars/svg?seed=me' },
      content,
      createdAt: new Date().toISOString(),
      status: 'sending' as const,
      reactions: [],
    };
    appendMessage(optimistic);
    try {
      const sent = await postMessage(activeId, content, parentId || null);
      updateMessage(tempId, { id: sent.id, status: sent.status });
    } catch {
      updateMessage(tempId, { status: 'failed' });
    }
    textareaRef.current?.focus();
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  const rows = Math.min(6, text.split('\n').length || 1);

  return (
    <div className="border-t border-border bg-surface px-4 py-3">
      <div className="flex items-end gap-2 rounded-xl border border-border bg-bg px-3 py-2 focus-within:border-primary">
        <button type="button" className="mb-2 text-muted hover:text-text" title="附件">
          <Paperclip className="h-5 w-5" />
        </button>
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={rows}
          placeholder={placeholder}
          className="max-h-40 min-h-[2.5rem] w-full resize-none bg-transparent py-2 text-sm text-text placeholder:text-muted focus:outline-none"
        />
        <button
          type="button"
          onClick={send}
          disabled={!text.trim() || !activeId}
          className="mb-1.5 inline-flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-text disabled:opacity-50 hover:bg-primary/90"
        >
          <Send className="h-4 w-4" />
          <span className="hidden sm:inline">发送</span>
        </button>
      </div>
      <div className="mt-1 text-xs text-muted">按 Enter 发送，Shift+Enter 换行</div>
    </div>
  );
}
