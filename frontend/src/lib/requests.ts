import type { MusicRequest } from '../api/types'

/**
 * Erneut senden gibt es nur fuer gescheiterte Anfragen und den Probelauf.
 * 12.09.2026: Solange nexbeat noch nachsah, ob Lidarr eine Anfrage bekommen hatte, liess erneutes Senden sie scheitern.
 */
export function canRetry(request: Pick<MusicRequest, 'status' | 'error_code'>): boolean {
  return request.status === 'failed' || (request.status === 'approved' && request.error_code === 'dry_run')
}
