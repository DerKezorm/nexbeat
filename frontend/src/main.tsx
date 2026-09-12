import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import App from './App'
import { AuthProvider } from './auth/AuthProvider'
import { PlayerProvider } from './components/player/PlayerProvider'
import { startI18n } from './i18n'
import './styles/index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 60_000,
    },
  },
})

function startApp(): void {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <AuthProvider>
            <PlayerProvider>
              <App />
            </PlayerProvider>
          </AuthProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </StrictMode>,
  )
}

function startFailed(): void {
  const root = document.getElementById('root')
  if (root) {
    root.innerHTML =
      '<p style="font-family:system-ui;padding:2rem;color:#c3c3ce">nexbeat could not load its texts. Reload the page.</p>'
  }
}

// Erst die Texte, dann die Oberflaeche. Sonst stuende einen Wimpernschlag lang
// die rohe Schluesselliste auf dem Bildschirm.
startI18n().then(startApp, startFailed)
