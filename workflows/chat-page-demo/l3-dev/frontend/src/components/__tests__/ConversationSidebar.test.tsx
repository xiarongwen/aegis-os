import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { ConversationSidebar } from '../ConversationSidebar'
import { useChatStore } from '../../store'
import * as api from '../../mocks/api'

describe('ConversationSidebar', () => {
  beforeEach(() => {
    vi.spyOn(api, 'fetchConversations').mockResolvedValue([
      { id: 'c-1', title: 'General', lastMessageAt: new Date().toISOString(), unreadCount: 1 },
      { id: 'c-2', title: 'Random', lastMessageAt: new Date().toISOString(), unreadCount: 0 },
    ])
    useChatStore.setState({
      conversations: [],
      activeConversationId: null,
      searchQuery: '',
    })
  })

  it('loads and displays conversations', async () => {
    render(<ConversationSidebar mobileOpen={false} onClose={() => {}} />)
    await waitFor(() => {
      expect(screen.getByText('General')).toBeInTheDocument()
      expect(screen.getByText('Random')).toBeInTheDocument()
    })
  })

  it('filters conversations by search query', async () => {
    render(<ConversationSidebar mobileOpen={false} onClose={() => {}} />)
    await waitFor(() => expect(screen.getByText('General')).toBeInTheDocument())

    const input = screen.getByPlaceholderText('搜索消息 (Ctrl+K)')
    fireEvent.change(input, { target: { value: 'gen' } })

    expect(screen.getByText('General')).toBeInTheDocument()
    expect(screen.queryByText('Random')).not.toBeInTheDocument()
  })

  it('sets active conversation on click', async () => {
    render(<ConversationSidebar mobileOpen={false} onClose={() => {}} />)
    await waitFor(() => expect(screen.getByText('General')).toBeInTheDocument())

    fireEvent.click(screen.getByText('General'))
    expect(useChatStore.getState().activeConversationId).toBe('c-1')
  })
})
