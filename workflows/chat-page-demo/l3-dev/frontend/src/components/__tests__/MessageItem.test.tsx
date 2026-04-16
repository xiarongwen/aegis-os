import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MessageItem } from '../MessageItem'
import { useChatStore } from '../../store'
import * as api from '../../mocks/api'
import type { Message } from '../../types'

describe('MessageItem', () => {
  const message: Message = {
    id: 'm-1',
    conversationId: 'c-1',
    parentId: null,
    sender: { id: 'u-1', name: 'Alice', avatarUrl: '' },
    content: 'Hello there',
    createdAt: new Date().toISOString(),
    status: 'delivered',
    reactions: [{ emoji: '👍', count: 1, userIds: ['u-me'] }],
  }

  beforeEach(() => {
    useChatStore.setState({ messages: [message] })
    vi.spyOn(api, 'postReaction').mockResolvedValue([
      { emoji: '👍', count: 2, userIds: ['u-me', 'u-2'] },
    ])
  })

  it('renders sender name and content', () => {
    render(<MessageItem message={message} />)
    expect(screen.getByText('Alice')).toBeInTheDocument()
    expect(screen.getByText('Hello there')).toBeInTheDocument()
  })

  it('opens thread on reply click', () => {
    render(<MessageItem message={message} />)
    fireEvent.click(screen.getByText('回复'))
    expect(useChatStore.getState().threadParentId).toBe('m-1')
  })

  it('toggles emoji picker', () => {
    render(<MessageItem message={message} />)
    fireEvent.click(screen.getByText('表情'))
    expect(screen.getAllByText('👍').length).toBeGreaterThanOrEqual(1)
  })

  it('highlights search query', () => {
    render(<MessageItem message={message} highlightQuery="there" />)
    expect(screen.getByText('there').tagName).toBe('MARK')
  })
})
