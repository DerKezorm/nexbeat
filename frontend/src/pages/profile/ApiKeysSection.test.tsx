import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { api } from '../../api/client'
import i18n, { startI18n } from '../../i18n'
import { ApiKeysSection, type ApiKey } from './ApiKeysSection'

const TOKEN = 'nxb_example-token-only-for-this-test'

const KEY: ApiKey = {
  id: 7,
  name: 'nexdeck',
  preview: 'nxb_exampl',
  read_only: true,
  created_at: '2026-09-28T10:00:00',
  last_used_at: null,
}

function show() {
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={queries}>
      <ApiKeysSection />
    </QueryClientProvider>,
  )
}

beforeAll(async () => {
  await startI18n('de')
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('API tokens in the profile', () => {
  it('show a new token once, with the header it is sent in, and never again', async () => {
    const listed: ApiKey[] = []
    vi.spyOn(api, 'get').mockImplementation((async () => [...listed]) as typeof api.get)
    const post = vi.spyOn(api, 'post').mockImplementation((async () => {
      listed.push(KEY)
      return { ...KEY, token: TOKEN }
    }) as typeof api.post)
    show()

    expect(await screen.findByText(i18n.t('apiKeys.empty'))).toBeInTheDocument()
    const create = screen.getByRole('button', { name: i18n.t('apiKeys.create') })
    expect(create).toBeDisabled()
    fireEvent.change(screen.getByLabelText(i18n.t('apiKeys.nameLabel')), { target: { value: ' nexdeck ' } })
    // Ab Werk nur lesen: das Sichere fuer ein Dashboard.
    expect(screen.getByRole('checkbox')).toBeChecked()
    fireEvent.click(create)

    expect(await screen.findByTestId('new-api-key')).toHaveTextContent(TOKEN)
    expect(screen.getByText(`Authorization: Bearer ${TOKEN}`)).toBeInTheDocument()
    expect(post).toHaveBeenCalledWith('/api/auth/me/keys', { name: 'nexdeck', read_only: true })

    fireEvent.click(screen.getByRole('button', { name: i18n.t('apiKeys.done') }))
    await waitFor(() => expect(screen.queryByTestId('new-api-key')).not.toBeInTheDocument())
    expect(await screen.findByText('nxb_exampl…')).toBeInTheDocument()
    expect(screen.queryByText(new RegExp(TOKEN))).not.toBeInTheDocument()
    expect(screen.getByText(i18n.t('apiKeys.neverUsed'))).toBeInTheDocument()
  })

  it('revoke a token only after asking', async () => {
    vi.spyOn(api, 'get').mockResolvedValue([KEY])
    const remove = vi.spyOn(api, 'delete').mockResolvedValue(undefined)
    show()

    fireEvent.click(await screen.findByRole('button', { name: i18n.t('apiKeys.revoke') }))
    expect(remove).not.toHaveBeenCalled()
    const dialog = screen.getByRole('dialog', { name: i18n.t('apiKeys.revokeTitle') })
    expect(dialog).toHaveTextContent('nexdeck')
    const buttons = screen.getAllByRole('button', { name: i18n.t('apiKeys.revoke') })
    fireEvent.click(buttons[buttons.length - 1])
    await waitFor(() => expect(remove).toHaveBeenCalledWith('/api/auth/me/keys/7'))
  })
})

describe('Connecting a device with a code', () => {
  it('sends the code the app shows and says which device is connected', async () => {
    vi.spyOn(api, 'get').mockImplementation((async () => []) as typeof api.get)
    const post = vi.spyOn(api, 'post').mockImplementation((async () => ({ device_name: 'nextune' })) as typeof api.post)
    show()

    fireEvent.click(await screen.findByRole('button', { name: i18n.t('apiKeys.pairing.open') }))
    fireEvent.change(screen.getByLabelText(i18n.t('apiKeys.pairing.label')), { target: { value: ' abcd-2345 ' } })
    fireEvent.click(screen.getByRole('button', { name: i18n.t('apiKeys.pairing.confirm') }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/pairing/confirm', { code: 'abcd-2345' }))
    expect(await screen.findByText(i18n.t('apiKeys.pairing.done', { name: 'nextune' }))).toBeInTheDocument()
  })

  it('keeps the dialog open with the reason when the code is wrong', async () => {
    vi.spyOn(api, 'get').mockImplementation((async () => []) as typeof api.get)
    vi.spyOn(api, 'post').mockRejectedValue(
      Object.assign(new Error('pairing_unknown'), { code: 'pairing_unknown', status: 404 }),
    )
    show()

    fireEvent.click(await screen.findByRole('button', { name: i18n.t('apiKeys.pairing.open') }))
    fireEvent.change(screen.getByLabelText(i18n.t('apiKeys.pairing.label')), { target: { value: 'WXYZ-2345' } })
    fireEvent.click(screen.getByRole('button', { name: i18n.t('apiKeys.pairing.confirm') }))

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.getByLabelText(i18n.t('apiKeys.pairing.label'))).toBeInTheDocument()
  })
})
