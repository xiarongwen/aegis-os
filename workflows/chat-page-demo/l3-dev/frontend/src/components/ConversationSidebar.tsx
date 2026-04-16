import { useEffect, useMemo, useRef, useState } from 'react';
import { Search, MessageSquare, X, Menu } from 'lucide-react';
import { useChatStore } from '../store';
import { fetchConversations, searchMessages } from '../mocks/api';
import { formatDateTime } from '../utils/time';
import { ThemeToggle } from './ThemeToggle';

export function ConversationSidebar({ mobileOpen, onClose }: { mobileOpen: boolean; onClose: () => void }) {
  const conversations = useChatStore((s) => s.conversations);
  const setConversations = useChatStore((s) => s.setConversations);
  const activeId = useChatStore((s) => s.activeConversationId);
  const setActiveId = useChatStore((s) => s.setActiveConversationId);
  const searchQuery = useChatStore((s) => s.searchQuery);
  const setSearchQuery = useChatStore((s) => s.setSearchQuery);
  const [searchResults, setSearchResults] = useState<{ messageId: string; snippet: string }[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetchConversations().then(setConversations);
  }, [setConversations]);

  useEffect(() => {
    if (!activeId || !searchQuery.trim()) {
      setSearchResults([]);
      return;
    }
    const t = setTimeout(() => {
      searchMessages(activeId, searchQuery.trim()).then(setSearchResults);
    }, 200);
    return () => clearTimeout(t);
  }, [activeId, searchQuery]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  const filteredConversations = useMemo(() => {
    if (!searchQuery.trim()) return conversations;
    const q = searchQuery.toLowerCase();
    return conversations.filter((c) => c.title.toLowerCase().includes(q));
  }, [conversations, searchQuery]);

  return (
    <>
      {/* Desktop sidebar */}
      <aside className="hidden md:flex w-64 flex-col border-r border-border bg-surface h-full">
        <SidebarContent
          inputRef={inputRef}
          conversations={filteredConversations}
          activeId={activeId}
          setActiveId={setActiveId}
          searchQuery={searchQuery}
          setSearchQuery={setSearchQuery}
          searchResults={searchResults}
          onClose={onClose}
        />
      </aside>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 flex md:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={onClose} />
          <aside className="relative z-50 w-4/5 max-w-xs border-r border-border bg-surface h-full flex flex-col">
            <SidebarContent
              inputRef={inputRef}
              conversations={filteredConversations}
              activeId={activeId}
              setActiveId={(id) => {
                setActiveId(id);
                onClose();
              }}
              searchQuery={searchQuery}
              setSearchQuery={setSearchQuery}
              searchResults={searchResults}
              onClose={onClose}
            />
          </aside>
        </div>
      )}
    </>
  );
}

function SidebarContent({
  inputRef,
  conversations,
  activeId,
  setActiveId,
  searchQuery,
  setSearchQuery,
  searchResults,
  onClose,
}: {
  inputRef: React.RefObject<HTMLInputElement | null>;
  conversations: ReturnType<typeof useChatStore.getState>['conversations'];
  activeId: string | null;
  setActiveId: (id: string | null) => void;
  searchQuery: string;
  setSearchQuery: (q: string) => void;
  searchResults: { messageId: string; snippet: string }[];
  onClose: () => void;
}) {
  return (
    <>
      <div className="flex items-center justify-between gap-2 px-3 py-3 border-b border-border">
        <div className="flex items-center gap-2">
          <button type="button" className="md:hidden p-1 rounded hover:bg-black/5 dark:hover:bg-white/5" onClick={onClose}>
            <Menu className="h-5 w-5 text-muted" />
          </button>
          <span className="font-semibold text-text">聊天</span>
        </div>
        <ThemeToggle />
      </div>
      <div className="px-3 py-2 border-b border-border">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted" />
          <input
            ref={inputRef}
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="搜索消息 (Ctrl+K)"
            className="w-full rounded-md border border-border bg-bg pl-8 pr-7 py-2 text-sm text-text placeholder:text-muted focus:border-primary focus:outline-none"
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => setSearchQuery('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted hover:text-text"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
        {searchResults.length > 0 && (
          <div className="mt-2 space-y-1">
            {searchResults.map((r) => (
              <div key={r.messageId} className="rounded-md bg-bg border border-border px-2 py-1.5 text-xs text-muted truncate">
                {r.snippet}
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="flex-1 overflow-y-auto">
        <div className="px-2 py-2 text-xs font-medium text-muted uppercase tracking-wide">会话</div>
        <ul className="space-y-0.5 px-2">
          {conversations.map((c) => {
            const active = activeId === c.id;
            return (
              <li key={c.id}>
                <button
                  type="button"
                  onClick={() => setActiveId(c.id)}
                  className={[
                    'w-full flex items-center gap-2 rounded-md px-2 py-2 text-left transition-colors',
                    active ? 'bg-primary/10 text-primary' : 'hover:bg-black/5 dark:hover:bg-white/5 text-text',
                  ].join(' ')}
                >
                  <MessageSquare className="h-4 w-4 shrink-0" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">{c.title}</div>
                    <div className="truncate text-xs text-muted">{formatDateTime(c.lastMessageAt)}</div>
                  </div>
                  {c.unreadCount > 0 && (
                    <span className="ml-1 inline-flex h-5 min-w-[1.25rem] items-center justify-center rounded-full bg-primary px-1.5 text-xs font-medium text-primary-text">
                      {c.unreadCount}
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </>
  );
}
