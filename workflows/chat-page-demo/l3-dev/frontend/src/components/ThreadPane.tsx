import { useEffect, useMemo } from 'react';
import { X } from 'lucide-react';
import { useChatStore } from '../store';
import { MessageItem } from './MessageItem';
import { Composer } from './Composer';

export function ThreadPane() {
  const parentId = useChatStore((s) => s.threadParentId);
  const setThreadParentId = useChatStore((s) => s.setThreadParentId);
  const messages = useChatStore((s) => s.messages);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setThreadParentId(null);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [setThreadParentId]);

  const parent = useMemo(() => messages.find((m) => m.id === parentId) || null, [messages, parentId]);
  const threadMessages = useMemo(
    () => messages.filter((m) => m.parentId === parentId).sort((a, b) => +new Date(a.createdAt) - +new Date(b.createdAt)),
    [messages, parentId]
  );

  if (!parentId || !parent) return null;

  return (
    <div className="fixed inset-y-0 right-0 z-30 w-full max-w-md border-l border-border bg-bg shadow-xl md:relative md:inset-auto md:z-auto md:w-80 lg:w-96">
      <div className="flex h-full flex-col">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div className="font-medium text-text">线程回复</div>
          <button
            type="button"
            onClick={() => setThreadParentId(null)}
            className="rounded p-1 text-muted hover:bg-black/5 dark:hover:bg-white/5"
            aria-label="关闭线程"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="border-b border-border bg-surface/50 px-4 py-3">
          <MessageItem message={parent} isThread />
        </div>

        <div className="flex-1 overflow-y-auto px-2 py-2">
          {threadMessages.length === 0 && (
            <div className="py-6 text-center text-sm text-muted">暂无回复，来说点什么吧</div>
          )}
          {threadMessages.map((m) => (
            <MessageItem key={m.id} message={m} isThread />
          ))}
        </div>

        <div className="border-t border-border">
          <Composer parentId={parentId} placeholder="回复线程…" />
        </div>
      </div>
    </div>
  );
}
