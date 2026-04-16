import { MessageList } from './MessageList';
import { Composer } from './Composer';

export function ChatMain() {
  return (
    <div className="flex flex-1 flex-col min-w-0 bg-bg">
      <MessageList />
      <Composer />
    </div>
  );
}
