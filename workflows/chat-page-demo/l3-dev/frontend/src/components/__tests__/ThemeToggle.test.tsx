import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ThemeToggle } from '../ThemeToggle'
import { useChatStore } from '../../store'

describe('ThemeToggle', () => {
  beforeEach(() => {
    useChatStore.setState({ theme: 'system' })
    document.documentElement.classList.remove('dark')
  })

  it('renders three theme options', () => {
    render(<ThemeToggle />)
    const buttons = screen.getAllByRole('button')
    expect(buttons).toHaveLength(3)
  })

  it('switches to dark theme', () => {
    render(<ThemeToggle />)
    const darkButton = screen.getAllByRole('button')[1]
    fireEvent.click(darkButton)
    expect(useChatStore.getState().theme).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  it('switches to light theme', () => {
    render(<ThemeToggle />)
    const lightButton = screen.getAllByRole('button')[0]
    fireEvent.click(lightButton)
    expect(useChatStore.getState().theme).toBe('light')
    expect(document.documentElement.classList.contains('dark')).toBe(false)
  })
})
