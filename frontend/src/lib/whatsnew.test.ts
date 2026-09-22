import { FILES, isEntry, latestVersion, unseen } from './whatsnew'

/**
 * Waechter fuer "Was ist neu". In Nexview fehlten zweimal Felder in einem Eintrag, und das Fenster zeigte still den
 * Text der vorigen Fassung. Hier faellt so etwas vor dem Release auf.
 */
describe('whats new entries', () => {
  const versions = Object.keys(FILES.en.entries)

  it('exist, and every one has all four fields and a way to each section', () => {
    expect(versions.length).toBeGreaterThan(0)
    for (const language of ['de', 'en']) {
      for (const [version, entry] of Object.entries(FILES[language].entries)) {
        expect(isEntry(entry), `${language} ${version}`).toBe(true)
      }
    }
  })

  it('say the same in both languages: same versions, same sections, same admin marks', () => {
    expect(Object.keys(FILES.de.entries).sort()).toEqual(versions.sort())
    for (const version of versions) {
      const de = FILES.de.entries[version] as { sections: { admin?: boolean }[]; small: string[] }
      const en = FILES.en.entries[version] as { sections: { admin?: boolean }[]; small: string[] }
      expect(de.sections.map((section) => Boolean(section.admin))).toEqual(en.sections.map((section) => Boolean(section.admin)))
      expect(de.small.length).toBe(en.small.length)
    }
  })

  it('name versions as three numbers', () => {
    for (const version of versions) expect(version).toMatch(/^\d+\.\d+\.\d+$/)
  })

  it('open only for a version the account has not seen, never backwards', () => {
    const newest = latestVersion()
    expect(unseen(null, newest)).toBe(true)
    expect(unseen(newest, newest)).toBe(false)
    expect(unseen('1.0.0', '1.1.0')).toBe(true)
    expect(unseen('1.10.0', '1.9.0')).toBe(false)
    expect(unseen('1.0.0', null)).toBe(false)
  })

  it('drop an entry that lacks a field', () => {
    expect(isEntry({ lead: 'x', sections: [], smallTitle: 'y' })).toBe(false)
    expect(isEntry({ lead: 'x', sections: [], small: [] })).toBe(false)
    expect(isEntry({ sections: [], smallTitle: 'y', small: [] })).toBe(false)
    expect(isEntry({ lead: 'x', smallTitle: 'y', small: [] })).toBe(false)
    expect(isEntry({ lead: 'x', sections: [{ title: 't', body: 'b' }], smallTitle: 'y', small: [] })).toBe(false)
  })
})
