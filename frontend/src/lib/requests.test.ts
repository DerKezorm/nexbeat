import type { MusicRequest } from '../api/types'
import { canRetry } from './requests'

function request(status: MusicRequest['status'], errorCode = ''): Pick<MusicRequest, 'status' | 'error_code'> {
  return { status, error_code: errorCode }
}

describe('retry in the admin list', () => {
  it('is offered for failed requests and dry runs only', () => {
    expect(canRetry(request('failed', 'album_not_in_lidarr'))).toBe(true)
    expect(canRetry(request('approved', 'dry_run'))).toBe(true)
    expect(canRetry(request('approved', 'lidarr_timeout'))).toBe(false)
    expect(canRetry(request('approved', 'lidarr_pending'))).toBe(false)
    expect(canRetry(request('searching'))).toBe(false)
  })
})
