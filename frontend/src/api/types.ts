export type Role = 'admin' | 'user'

export type Quota = {
  limit: number | null
  used: number
  remaining: number | null
  period: 'day' | 'week' | 'month'
  resets_at: string
}

export type User = {
  id: number
  username: string
  email: string
  role: Role
  display_name: string
  language: '' | 'de' | 'en'
  is_active: boolean
  requires_approval: boolean
  quota_limit: number | null
  created_at: string
  last_login_at: string | null
  quota: Quota
}

export type Me = User & { is_admin: boolean }

export type AppConfig = {
  version: string
  needs_setup: boolean
  mail_configured: boolean
  default_language: 'de' | 'en'
  previews_enabled: boolean
  requests_enabled: boolean
}

export type RequestStatus =
  | 'pending_approval'
  | 'approved'
  | 'searching'
  | 'downloaded'
  | 'rejected'
  | 'failed'
  | 'cancelled'

export type RequestState = {
  id: number
  status: RequestStatus
  mine: boolean
  progress: number
  error_code: string
}

export type LibraryState = {
  state: 'available' | 'partial' | 'wanted' | 'known'
  percent: number
  lidarr_id: number | null
}

export type ArtistItem = {
  mbid: string
  name: string
  image: string
  in_library: boolean
  reasons?: string[]
}

export type AlbumItem = {
  mbid: string
  title: string
  artist_mbid?: string
  artist_name?: string
  cover: string
  primary_type?: string
  date?: string
  first_release_date?: string
  request?: RequestState | null
  library?: LibraryState | null
}

export type DiscoverRow = {
  id: string
  kind: 'artists' | 'albums'
  title_key: string
  params?: { name?: string; mbid?: string }
  items: (ArtistItem | AlbumItem)[]
}

export type DiscoverResponse = {
  rows: DiscoverRow[]
  library_size: number
  has_seeds: boolean
  requests_enabled: boolean
}

export type SearchArtist = ArtistItem & {
  type: string
  country: string
  disambiguation: string
  score: number
  tags: string[]
}

export type SearchAlbum = {
  mbid: string
  title: string
  primary_type: string
  secondary_types: string[]
  first_release_date: string
  artist_mbid: string
  artist_name: string
  cover: string
  request: RequestState | null
}

export type TopTrack = {
  title: string
  preview: string
  duration: number
  album_title: string
  cover: string
  explicit: boolean
}

export type DiscographyAlbum = {
  mbid: string
  title: string
  primary_type: string
  secondary_types: string[]
  date: string
  listen_count: number
  cover: string
  library: LibraryState | null
  request: RequestState | null
}

export type ArtistPageData = {
  artist: {
    mbid: string
    name: string
    type: string
    country: string
    disambiguation: string
    begin: string
    end: string
    tags: string[]
    image: string
    in_library: boolean
    track_file_count: number
  }
  sources: { listenbrainz: boolean; deezer: boolean }
  /** Die Anfrage fuer den ganzen Kuenstler, falls es eine zaehlende gibt. */
  request: RequestState | null
  /** Warum sich der ganze Kuenstler nicht anfragen laesst, als Fehlerkennung. Sonst null. */
  blocked: string | null
  requests_enabled: boolean
  requires_approval: boolean
  dry_run: boolean
  quota: Quota
}

/** Die Teile der Kuenstlerseite kommen einzeln, jeder mit eigenem Fehler. */
export type ArtistDiscography = { albums: DiscographyAlbum[] }
export type ArtistPopular = { albums: DiscographyAlbum[] }
export type ArtistSimilar = { artists: ArtistItem[] }
export type ArtistTopTracks = { tracks: TopTrack[] }

export type Track = {
  disc: number
  position: number
  title: string
  length_ms: number | null
  preview: string
  explicit: boolean
}

export type AlbumPageData = {
  album: {
    mbid: string
    title: string
    primary_type: string
    secondary_types: string[]
    date: string
    artist_mbid: string
    artist_name: string
    cover: string
    artist_image: string
  }
  tracks: Track[]
  library: LibraryState | null
  request: RequestState | null
  quota: Quota
  requests_enabled: boolean
  requires_approval: boolean
  dry_run: boolean
  /** Warum sich das Album nicht anfragen laesst, als Fehlerkennung. Sonst null. */
  blocked: string | null
}

export type MusicRequest = {
  id: number
  /** "artist": der ganze Kuenstler. Dann ist release_group_mbid leer und title der Name. */
  kind: 'album' | 'artist'
  release_group_mbid: string
  artist_mbid: string
  title: string
  artist_name: string
  album_type: string
  release_date: string
  cover_url: string
  status: RequestStatus
  requested_at: string
  decided_at: string | null
  rejection_reason: string
  submitted_at: string | null
  completed_at: string | null
  progress: number
  error_code: string
  user?: { id: number; username: string; display_name: string }
  error_message?: string
}

export type CreatedRequest = { request: MusicRequest; quota: Quota }

export type Invitation = {
  id: number
  email: string
  role: Role
  created_at: string
  expires_at: string
}

export type Delivery = { sent: boolean; manual_link: string | null; error_code: string | null }

export type InvitationCreated = { invitation: Invitation; delivery: Delivery }

export type AppSettings = {
  public_url: string
  default_language: 'de' | 'en'
  smtp_host: string
  smtp_port: number | null
  smtp_security: 'none' | 'starttls' | 'ssl'
  smtp_username: string
  smtp_password: string
  smtp_password_set: boolean
  smtp_from_address: string
  smtp_from_name: string
  lidarr_url: string
  lidarr_api_key: string
  lidarr_api_key_set: boolean
  lidarr_root_folder: string
  lidarr_quality_profile_id: number | null
  lidarr_metadata_profile_id: number | null
  lidarr_dry_run: boolean
  source_listenbrainz: boolean
  source_deezer: boolean
  lastfm_api_key: string
  lastfm_api_key_set: boolean
  listenbrainz_token: string
  listenbrainz_token_set: boolean
  quota_default_limit: number | null
  quota_period: 'day' | 'week' | 'month'
}

/** Ein Metadatenprofil mit dem, was es zulaesst, in Lidarrs Namen. */
export type MetadataProfile = {
  id: number
  name: string
  primary: string[]
  secondary: string[]
  statuses: string[]
  /** Nur Studioalben und nur offizielle. Nur dann geht "Ganzer Kuenstler". */
  studio_only: boolean
}

export type LidarrOptions = {
  quality_profiles: { id: number; name: string }[]
  metadata_profiles: MetadataProfile[]
  root_folders: { path: string; free_space: number | null; accessible: boolean }[]
}

export type WebhookInfo = { path: string; username: string; password: string; events: string[] }
