import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { Composer } from '../Composer'
import { useChatStore } from '../../store'
import * as api from '../../mocks/api'

describe('Composer', () => {
  beforeEach(() => {
    useChatStore.setState({
      activeConversationId: 'c-test',
      messages: [],
    })
    vi.spyOn(api, 'postMessage').mockResolvedValue({
      id: 'm-real',
      conversationId: 'c-test',
      parentId: null,
      sender: { id: 'u-me', name: '我' },
      content: 'hello',
      createdAt: new Date().toISOString(),
      status: 'sent',
      reactions: [],
    })
  })

  it('renders textarea and send button', () => {
    render(<Composer />)
    expect(screen.getByPlaceholderText('输入消息…')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /发送/i })).toBeDisabled()
  })

  it('sends message on Enter', async () => {
    render(<Composer />)
    const textarea = screen.getByPlaceholderText('输入消息…')
    fireEvent.change(textarea, { target: { value: 'hello world' } })
    fireEvent.keyDown(textarea, { key: 'Enter', code: 'Enter' })

    await waitFor(() => {
      const state = useChatStore.getState()
      expect(state.messages.some((m) => m.content === 'hello world')).toBe(true)
    })
  })

  it('does not send on Shift+Enter', () => {
    render(<Composer />)
    const textarea = screen.getByPlaceholderText('输入消息…')
    fireEvent.change(textarea, { target: { value: 'hello world' } })
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: true })

    const state = useChatStore.getState()
    expect(state.messages).toHaveLength(0)
  })
})
