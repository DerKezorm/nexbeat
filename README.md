# nexbeat

Find music and request it from Lidarr or nexcrate with one click.

![Discover: recommendations based on the library, plus what is trending this week](docs/screenshots/discover.png)

nexbeat is a small, self-hosted companion to Lidarr, built in the spirit of
[Nexview](https://github.com/DerKezorm/nexview): accounts with invitations,
per-user quotas counted by request, optional approval, and a discovery page
that recommends artists based on what the library and each user already have.

> **Status:** stable. Used daily against Lidarr and nexcrate.

The screenshots show a throwaway instance with a few well-known artists as its
library.

## What it does

- **Discover:** "for you" and "because you listen to" rows from ListenBrainz
  similar-artist data, plus weekly trends. Artists already in the library are left out.
- **Genres:** browse twenty main genres. A genre page shows the most played
  artists and albums of that genre and related genres to follow. Artists in
  the library stay in the list, marked as such.
- **Search** artists and releases in MusicBrainz, browse discographies and
  similar artists, listen to 30 second previews.
- **Request** a single album, EP or single. In ARR mode unknown artists are
  added to Lidarr with only the requested album monitored.
- **Whole artists:** one request for every studio album and future ones. Only
  offered when the metadata profile keeps Lidarr to official studio albums.
- **Quotas** count requests per day, week or month. Rejected and failed
  requests do not count.
- **Accounts:** invitations and password reset by email, or as a link to pass
  on when no mail server is set up.
- **Single sign-on:** sign in through authentik, Microsoft Entra ID, Keycloak,
  Authelia, Pocket ID or any other OpenID Connect provider. authentik is set up
  in one click (or with a blueprint).
- **About and updates:** version, source and licence in the footer. After an
  update every account sees once what is new; administrators see when a newer
  version is out.

nexbeat never changes Lidarr settings. It adds and monitors artists and albums
and starts searches, nothing else.

**Two modes.** The administrator picks where requests go. In **ARR mode** it is
Lidarr, as described above. In **NEX mode** it is nexcrate, through its
interface for other programs (`/api/v1`, contract 1 with music): nexbeat asks
for albums and whole artists (studio albums only), reads their state in batches
and listens to nexcrate's event stream, so a change shows up within seconds.
Connecting takes one step: nexbeat asks for a key, nexcrate shows a code, the
owner confirms it there. A key made by hand works too. nexbeat changes nothing
in nexcrate's settings either. Switching modes hands open requests to the new
program once.

![An artist page with discography, most listened albums and similar artists](docs/screenshots/artist.png)

## Running with Docker

```bash
mkdir nexbeat && cd nexbeat
curl -O https://raw.githubusercontent.com/DerKezorm/nexbeat/main/docker-compose.yml
docker compose up -d
```

Open `http://<your-host>:8030` and create the first account. It becomes the
administrator. Then, under **Settings**:

1. **Services, Target:** choose ARR or NEX mode.
   - **Lidarr:** address, API key, root folder, quality and metadata profile. If
     users should be able to request whole artists, pick a metadata profile that
     allows official studio albums only. nexbeat checks this and says why when it
     does not fit.
   - **nexcrate:** enter its address and connect, then confirm the code in
     nexcrate with the rights Read and Request. nexbeat shows whether nexcrate's
     music version is ready (profile, indexer with music categories, download
     client); that is set up in nexcrate, not here.
2. **Mail** (optional): for invitations and password resets. Without a mail
   server, nexbeat hands out the links for you to pass on.
3. **Users:** invite people, set their quota and whether their requests need
   approval.

In ARR mode the tab also shows a webhook address. Entered in Lidarr, it lets nexbeat
notice finished downloads right away; without it, nexbeat checks every two
minutes.

- **Updating:** `docker compose pull && docker compose up -d`
- **Backing up:** the whole data directory, the database and `secret.key`
  together. Without the key, the stored credentials cannot be read.
- **Images** are built for amd64 and arm64. `latest` follows releases, `main`
  the current development state.

![All requests for administrators: approve, reject or send again](docs/screenshots/admin-requests.png)

## Run from source

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

## API for scripts and dashboards

Every account can create API tokens under **Profile > API tokens**. A token
carries exactly the rights of its account; ticked as **read only** it may look
things up and change nothing. The token is shown once, when it is created, and
is sent with every request as a header:

```
Authorization: Bearer nxb_…
```

The promised interface is under `/api/v1` and described at `/api/docs`:

- `GET /api/v1/me`: the account behind the token and what it may do (`may`:
  `request`, `see_all`, `decide`). Build buttons on `may`, not on the role.
- `GET /api/v1/dashboard`: requests by state and the size of the library in one
  call. Administrators get the whole installation, everybody else their own
  requests.
- Search, request, withdraw, and for administrators list, approve and turn down
  requests.

[nexdeck](https://github.com/DerKezorm/nexdeck) uses it for its nexbeat cards.
Administrators see every token of the installation under Settings > Users.
Changing the password leaves tokens working; deactivating an account stops
them.

## Sign-in with OpenID Connect

Under **Settings > System > Sign-in** an administrator adds sign-in providers.
Each one gets a button on the sign-in page. The return address to enter at the
provider is `<public address>/api/auth/oidc/<short name>/callback`, so the
public address under Settings > System > Address has to be set first.

- **authentik in one step:** enter the address of authentik and an API token
  that may create applications. nexbeat creates the signing key, a scope
  mapping, the provider and the application, and adds itself as a sign-in
  provider. The token is not stored. Rather not hand one over? Download the
  blueprint instead and import it in authentik.
- **Microsoft Entra ID:** register a web app, enter the return address (Entra
  only accepts https, except for localhost) and create a client secret. Issuer:
  `https://login.microsoftonline.com/<tenant ID>/v2.0`, or `common` and
  `organizations` for several tenants. Entra sends an email address only as
  the optional claim `email`; nexbeat works without it.
- **Anything else** that speaks OpenID Connect: issuer URL, client ID and
  secret.

Accounts are matched by the provider's subject only, never by email address.
An existing account is linked once under **Profile > Sign-in providers**. Per
provider, accounts can be created on first sign-in with a chosen role; they
start without a password and can set one in their profile.

## Data sources

MusicBrainz, Cover Art Archive and ListenBrainz (open data). Artist images and
previews come from the public Deezer API and can be switched off.

Once a day nexbeat asks GitHub for its newest release to tell administrators
about updates. Nothing but the request itself goes out, and it can be switched
off on the About page.

## Licence

[GNU Affero General Public License v3.0](LICENSE).
