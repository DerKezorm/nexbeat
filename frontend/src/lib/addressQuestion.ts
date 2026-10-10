import { ApiError } from '../api/client'

/**
 * Was der Server mit 409 `public_url_change` sagt, bevor er eine neue oeffentliche Adresse speichert: Eintraege des
 * authentik-Knopfs, die authentik unter der alten Adresse kennt (`count`, die Adresse des ersten), und aktive Eintraege
 * von Hand, deren Rueckleitadresse sich mit aendert (`hand`). Sonst null.
 */
export type AddressQuestionValues = { count: number; address: string; hand: number }

export function questionOf(error: unknown): AddressQuestionValues | null {
  if (!(error instanceof ApiError) || error.code !== 'public_url_change') return null
  const values = error.data ?? {}
  return { count: Number(values.count ?? 0), address: String(values.address ?? ''), hand: Number(values.hand ?? 0) }
}
