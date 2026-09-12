import de from './de.json'

const sources = import.meta.glob('../**/*.{ts,tsx}', { query: '?raw', import: 'default', eager: true }) as Record<string, string>

function exists(path: string): boolean {
  let node: unknown = de
  for (const part of path.split('.')) {
    if (!node || typeof node !== 'object' || !(part in node)) return false
    node = (node as Record<string, unknown>)[part]
  }
  return typeof node === 'string'
}

/**
 * Jeder woertlich geschriebene Schluessel muss es geben. Zusammengesetzte
 * (`t(\`status.${x}\`)`) prueft dieser Test nicht, die stehen unten einzeln.
 */
describe('translation keys used in the code', () => {
  it('all exist', () => {
    const used = new Set<string>()
    for (const [file, text] of Object.entries(sources)) {
      if (file.endsWith('.test.ts') || file.endsWith('.test.tsx')) continue
      for (const match of text.matchAll(/\bt\(\s*'([a-zA-Z0-9_.]+)'/g)) used.add(match[1])
    }
    // Bodenschwelle, damit ein kaputtes Muster nicht still nichts findet.
    expect(used.size).toBeGreaterThan(150)
    expect([...used].filter((key) => !exists(key))).toEqual([])
  })

  it('cover the composed keys', () => {
    const composed = [
      ...['day', 'week', 'month'].map((period) => `quota.period_${period}`),
      ...['pending_approval', 'approved', 'searching', 'downloaded', 'rejected', 'failed', 'cancelled', 'dry_run'].map(
        (status) => `requestStatus.${status}`,
      ),
      ...['album', 'ep', 'single', 'other', 'all'].map((filter) => `artist.filter_${filter}`),
      ...['waiting', 'underway', 'done', 'problems', 'all'].map((filter) => `adminRequests.filter_${filter}`),
      ...['starttls', 'ssl', 'none'].map((security) => `mail.security_${security}`),
      ...['album', 'ep', 'single', 'broadcast', 'other'].map((type) => `releaseType.${type}`),
      ...['person', 'group', 'orchestra', 'choir', 'character', 'other'].map((type) => `artistType.${type}`),
    ]
    expect(composed.filter((key) => !exists(key))).toEqual([])
  })
})
