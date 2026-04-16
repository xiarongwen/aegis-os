import { useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { MessageCircle, Smile } from 'lucide-react';
import { useChatStore } from '../store';
import { postReaction } from '../mocks/api';
import { formatTime } from '../utils/time';
import type { Message } from '../types';

const currentUserId = 'u-me';

export function MessageItem({
  message,
  isThread = false,
  highlightQuery = '',
}: {
  message: Message;
  isThread?: boolean;
  highlightQuery?: string;
}) {
  const isSelf = message.sender.id === currentUserId;
  const setThreadParentId = useChatStore((s) => s.setThreadParentId);
  const updateMessage = useChatStore((s) => s.updateMessage);
  const [showEmoji, setShowEmoji] = useState(false);

  const emojis = ['👍', '❤️', '😂', '🎉', '🤔'];

  const contentHtml = useMemo(() => {
    if (!highlightQuery.trim()) return message.content;
    const q = highlightQuery.trim();
    const parts = message.content.split(new RegExp(`(${escapeRegExp(q)})`, 'gi'));
    return parts.map((part, i) =>
      part.toLowerCase() === q.toLowerCase() ? (
        <mark key={i} className="rounded bg-yellow-300/60 px-0.5 dark:bg-yellow-500/40">
          {part}
        </mark>
      ) : (
        part
      )
    );
  }, [message.content, highlightQuery]);

  const handleReact = async (emoji: string) => {
    const reactions = await postReaction(message.id, emoji);
    updateMessage(message.id, { reactions });
    setShowEmoji(false);
  };

  return (
    <div
      className={[
        'group relative flex gap-3 px-4 py-2 hover:bg-black/[0.02] dark:hover:bg-white/[0.02]',
        isSelf ? 'flex-row-reverse' : 'flex-row',
      ].join(' ')}
    >
      <img
        src={message.sender.avatarUrl || `https://api.dicebear.com/7.x/avataaars/svg?seed=${message.sender.id}`}
        alt={message.sender.name}
        className="h-9 w-9 rounded-full bg-surface object-cover"
      />
      <div className={['flex max-w-[80%] flex-col', isSelf ? 'items-end' : 'items-start'].join(' ')}>
        <div className="flex items-center gap-2 text-xs text-muted">
          <span className="font-medium text-text">{message.sender.name}</span>
          <span>{formatTime(message.createdAt)}</span>
          {message.status === 'sending' && <span className="text-muted">发送中…</span>}
          {message.status === 'failed' && <span className="text-red-500">发送失败</span>}
        </div>
        <div
          className={[
            'mt-1 rounded-2xl px-4 py-2 text-sm leading-relaxed',
            isSelf ? 'rounded-tr-sm bg-bubble-self text-text' : 'rounded-tl-sm bg-bubble text-text',
          ].join(' ')}
        >
          {message.sender.id === 'u-ai' && !highlightQuery ? (
            <div className="prose prose-sm dark:prose-invert max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
            </div>
          ) : (
            <div className="whitespace-pre-wrap">{contentHtml}</div>
          )}
        </div>

        {message.reactions.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-1">
            {message.reactions.map((r) => (
              <button
                key={r.emoji}
                type="button"
                onClick={() => handleReact(r.emoji)}
                className={[
                  'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs transition-colors',
                  r.userIds.includes(currentUserId)
                    ? 'border-primary bg-primary/10 text-primary'
                    : 'border-border bg-surface text-text hover:bg-black/5 dark:hover:bg-white/5',
                ].join(' ')}
              >
                <span>{r.emoji}</span>
                <span>{r.count}</span>
              </button>
            ))}
          </div>
        )}

        <div className="mt-1 flex items-center gap-2 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
          {!isThread && (
            <button
              type="button"
              onClick={() => setThreadParentId(message.id)}
              className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-muted hover:bg-black/5 dark:hover:bg-white/5"
            >
              <MessageCircle className="h-3.5 w-3.5" />
              <span>回复</span>
            </button>
          )}
          <div className="relative">
            <button
              type="button"
              onClick={() => setShowEmoji((v) => !v)}
              className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-muted hover:bg-black/5 dark:hover:bg-white/5"
            >
              <Smile className="h-3.5 w-3.5" />
              <span>表情</span>
            </button>
            {showEmoji && (
              <div className="absolute left-0 top-full z-10 mt-1 flex gap-1 rounded-lg border border-border bg-surface p-1 shadow">
                {emojis.map((emoji) => (
                  <button
                    key={emoji}
                    type="button"
                    onClick={() => handleReact(emoji)}
                    className="rounded px-1.5 py-1 text-base hover:bg-black/5 dark:hover:bg-white/5"
                  >
                    {emoji}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {showEmoji && (
        <button
          type="button"
          className="fixed inset-0 z-0"
          aria-label="关闭表情选择"
          onClick={() => setShowEmoji(false)}
        />
      )}
    </div>
  );
}

function escapeRegExp(str: string) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
