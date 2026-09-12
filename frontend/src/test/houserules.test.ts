const sources = import.meta.glob('../**/*.{ts,tsx}', { query: '?raw', import: 'default', eager: true }) as Record<string, string>

/** Wie in Nexview: Browser-Popups sehen ueberall anders aus und erklaeren nichts. */
describe('house rules', () => {
  it('use no browser popups', () => {
    const offenders = Object.entries(sources)
      .filter(([file]) => !file.includes('houserules.test'))
      .filter(([, text]) => /\b(window\.)?(confirm|alert|prompt)\(/.test(text))
      .map(([file]) => file)
    expect(Object.keys(sources).length).toBeGreaterThan(30)
    expect(offenders).toEqual([])
  })
})
