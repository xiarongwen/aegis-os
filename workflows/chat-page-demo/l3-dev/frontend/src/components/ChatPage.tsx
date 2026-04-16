import { useState } from 'react';
import { Menu } from 'lucide-react';
import { ConversationSidebar } from './ConversationSidebar';
import { ChatMain } from './ChatMain';
import { ThreadPane } from './ThreadPane';

export function ChatPage() {
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

  return (
    <div className="flex h-full flex-1 overflow-hidden bg-bg text-text">
      <ConversationSidebar mobileOpen={mobileSidebarOpen} onClose={() => setMobileSidebarOpen(false)} />
      <div className="flex flex-1 flex-col min-w-0">
        <div className="flex items-center gap-2 border-b border-border bg-surface px-4 py-2 md:hidden">
          <button
            type="button"
            onClick={() => setMobileSidebarOpen(true)}
            className="rounded p-1 hover:bg-black/5 dark:hover:bg-white/5"
            aria-label="打开会话列表"
          >
            <Menu className="h-5 w-5" />
          </button>
          <span className="font-medium">聊天</span>
        </div>
        <div className="flex flex-1 min-h-0">
          <ChatMain />
          <ThreadPane />
        </div>
      </div>
    </div>
  );
}
