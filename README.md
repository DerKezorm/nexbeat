# nexbeat

Find music and request it from Lidarr with one click.

nexbeat is a small, self-hosted companion to Lidarr, built in the spirit of
[Nexview](https://github.com/DerKezorm/nexview): accounts with invitations,
per-user quotas counted by request, optional approval, and a discovery page
that recommends artists based on what the library and each user already have.

> **Status:** concept test. Not released, no images, no support.

## What it does

- **Discover:** "for you" and "because you listen to" rows from ListenBrainz
  similar-artist data, plus weekly trends. Artists already in Lidarr are left out.
- **Search** artists and releases in MusicBrainz, browse discographies and
  similar artists, listen to 30 second previews.
- **Request** a single album, EP or single. Unknown artists are added to Lidarr
  with only the requested album monitored.
- **Whole artists:** one request for every studio album and future ones. Only
  offered when the metadata profile keeps Lidarr to official studio albums.
- **Quotas** count requests per day, week or month. Rejected and failed
  requests do not count.
- **Accounts:** invitations and password reset by email, or as a link to pass
  on when no mail server is set up.

nexbeat never changes Lidarr settings. It adds and monitors artists and albums
and starts searches, nothing else.

## Run locally

```bash
cd backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m uvicorn app.main:app --port 8030
```

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5182 and create the first account.

## Data sources

MusicBrainz, Cover Art Archive and ListenBrainz (open data). Artist images and
previews come from the public Deezer API and can be switched off.
