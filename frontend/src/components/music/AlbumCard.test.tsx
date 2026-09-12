import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import { startI18n } from '../../i18n'
import { AlbumCard } from './AlbumCard'

beforeAll(async () => {
  await startI18n('de')
})

describe('album card', () => {
  it('names extra kinds next to the main kind', () => {
    // 12.09.2026: Live-Alben und Sammlungen standen nur als "Album" da.
    render(
      <MemoryRouter>
        <AlbumCard mbid="a" title="Live at Home" cover="" date="2024-12-06" type="Album" secondaryTypes={['Live']} />
      </MemoryRouter>,
    )
    expect(screen.getByText('2024 · Album · Live')).toBeInTheDocument()
  })
})
