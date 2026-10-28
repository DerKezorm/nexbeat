import { useState } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'

import { startI18n } from '../i18n'
import { ConfirmDialog } from './ConfirmDialog'

/** Wie Profil > Anmeldeanbieter: ein Feld im Dialog, onCancel je Rendern neu. */
function AskForPassword({ onCancel }: { onCancel: (password: string) => void }) {
  const [password, setPassword] = useState('')
  return (
    <ConfirmDialog
      open
      title="Link"
      description="Enter your password."
      confirmLabel="Link"
      onCancel={() => onCancel(password)}
      onConfirm={() => {}}
    >
      <input aria-label="Current password" value={password} onChange={(event) => setPassword(event.target.value)} />
    </ConfirmDialog>
  )
}

beforeAll(async () => {
  await startI18n('en')
})

describe('the confirm dialog', () => {
  it('puts the focus on its button when it opens', () => {
    render(<AskForPassword onCancel={() => {}} />)
    expect(screen.getByRole('button', { name: 'Link' })).toHaveFocus()
  })

  // Linking a provider: every keystroke in the password field moved the focus back to "Link".
  it('leaves the focus in a field while someone types', () => {
    render(<AskForPassword onCancel={() => {}} />)
    const field = screen.getByLabelText('Current password')
    field.focus()

    fireEvent.change(field, { target: { value: 's' } })
    fireEvent.change(field, { target: { value: 'se' } })

    expect(field).toHaveValue('se')
    expect(field).toHaveFocus()
  })

  it('cancels with Escape through the newest handler', () => {
    const cancelled: string[] = []
    render(<AskForPassword onCancel={(password) => cancelled.push(password)} />)
    fireEvent.change(screen.getByLabelText('Current password'), { target: { value: 'abc' } })

    fireEvent.keyDown(document, { key: 'Escape' })

    expect(cancelled).toEqual(['abc'])
  })
})
