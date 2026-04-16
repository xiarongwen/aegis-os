import { useChatStore } from '../store';

export function TypingIndicator() {
  const users = useChatStore((s) => s.typingUsers);
  if (users.length === 0) return null;

  const text = users.length === 1 ? `${users[0].name} 正在输入…` : '多人正在输入…';

  return (
    <div className="flex items-center gap-2 px-4 py-2 text-sm text-muted">
      <span className="inline-flex gap-0.5">
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted [animation-delay:0ms]" />
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted [animation-delay:150ms]" />
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted [animation-delay:300ms]" />
      </span>
      <span>{text}</span>
    </div>
  );
}
