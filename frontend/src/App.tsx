import { Suspense, lazy } from 'react'
import type { ReactElement } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { useAuth } from './auth/useAuth'
import { AppShell } from './components/AppShell'
import { Logo } from './components/Logo'
import { Spinner } from './components/ui'
import { AlbumPage } from './pages/AlbumPage'
import { ArtistPage } from './pages/ArtistPage'
import { GenrePage } from './pages/GenrePage'
import { HomePage } from './pages/HomePage'
import { LoginPage } from './pages/LoginPage'
import { MyRequestsPage } from './pages/MyRequestsPage'
import { SearchPage } from './pages/SearchPage'

/* Seiten, die im Alltag selten gebraucht werden, kommen erst beim Klick. Wie in
   Nexview: Wer nur Musik finden will, traegt das Werkzeug des Betreibers nicht mit. */
const SettingsPage = lazy(() => import('./pages/SettingsPage').then((m) => ({ default: m.SettingsPage })))
const AdminRequestsPage = lazy(() => import('./pages/AdminRequestsPage').then((m) => ({ default: m.AdminRequestsPage })))
const ProfilePage = lazy(() => import('./pages/ProfilePage').then((m) => ({ default: m.ProfilePage })))
const AboutPage = lazy(() => import('./pages/AboutPage').then((m) => ({ default: m.AboutPage })))
const SetupPage = lazy(() => import('./pages/SetupPage').then((m) => ({ default: m.SetupPage })))
const InvitationPage = lazy(() => import('./pages/OnboardingPage').then((m) => ({ default: m.InvitationPage })))
const SetPasswordPage = lazy(() => import('./pages/OnboardingPage').then((m) => ({ default: m.SetPasswordPage })))
const ForgotPasswordPage = lazy(() => import('./pages/OnboardingPage').then((m) => ({ default: m.ForgotPasswordPage })))

function BootScreen() {
  const { t } = useTranslation()
  return (
    <div className="nv-glow flex min-h-dvh flex-col items-center justify-center gap-4">
      <Logo className="h-12 w-12" />
      <p className="flex items-center gap-2 text-sm text-mist-500">
        <Spinner />
        {t('common.loading')}
      </p>
    </div>
  )
}

/** Wege aus einer Mail. Sie stehen vor der Anmeldepruefung, wer den Link oeffnet, hat ja noch kein Passwort. */
const PUBLIC_PREFIXES = ['/einladung/', '/passwort/', '/passwort-vergessen']

export default function App() {
  const { status, user, needsSetup } = useAuth()
  const { pathname } = useLocation()

  if (PUBLIC_PREFIXES.some((prefix) => pathname.startsWith(prefix))) {
    return (
      <Suspense fallback={<BootScreen />}>
        <Routes>
          <Route path="/einladung/:token" element={<InvitationPage />} />
          <Route path="/passwort/:token" element={<SetPasswordPage />} />
          <Route path="/passwort-vergessen" element={<ForgotPasswordPage />} />
        </Routes>
      </Suspense>
    )
  }
  if (status === 'loading') return <BootScreen />
  if (needsSetup) {
    return (
      <Suspense fallback={<BootScreen />}>
        <SetupPage />
      </Suspense>
    )
  }
  if (!user) return <LoginPage />

  // Nur die Ansicht. Geschuetzt ist jede Adresse zusaetzlich im Backend.
  const adminOnly = (element: ReactElement) => (user.is_admin ? element : <Navigate to="/" replace />)

  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<HomePage />} />
        <Route path="suche" element={<SearchPage />} />
        <Route path="kuenstler/:mbid" element={<ArtistPage />} />
        <Route path="album/:mbid" element={<AlbumPage />} />
        <Route path="genre/:tag" element={<GenrePage />} />
        <Route path="anfragen" element={<MyRequestsPage />} />
        <Route path="profil" element={<ProfilePage />} />
        <Route path="ueber" element={<AboutPage />} />
        <Route path="admin/anfragen" element={adminOnly(<AdminRequestsPage />)} />
        <Route path="admin/einstellungen" element={adminOnly(<SettingsPage />)} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
