// A stand-in OpenID Connect provider for the end-to-end run (Pflichttests 33 and 34). Never a real provider, never
// the network: it makes its key at the start, answers discovery, keys, token and userinfo, and sends the browser
// straight back with a code for the person POST /next named. Served at http://localhost:<port>, while nexbeat runs at
// 127.0.0.1: another site, as with a real one (the session cookie, SameSite=Lax, still comes along on the way back).
import { createHash, createSign, generateKeyPairSync, randomBytes } from 'node:crypto'
import http from 'node:http'

const PORT = Number(process.env.FAKE_OIDC_PORT || 8037)
const ISSUER = `http://localhost:${PORT}`
const { privateKey, publicKey } = generateKeyPairSync('rsa', { modulusLength: 2048 })
const jwk = { ...publicKey.export({ format: 'jwk' }), kid: 'e2e', use: 'sig', alg: 'RS256' }
const grants = new Map()
let person = { sub: 'e2e-person', preferred_username: 'owner', email: 'owner@example.com' }

const b64 = (value) => Buffer.from(typeof value === 'string' ? value : JSON.stringify(value)).toString('base64url')

function idToken(claims) {
  const head = b64({ alg: 'RS256', typ: 'JWT', kid: 'e2e' })
  const body = b64(claims)
  const signer = createSign('RSA-SHA256')
  signer.update(`${head}.${body}`)
  return `${head}.${body}.${signer.sign(privateKey).toString('base64url')}`
}

function json(response, status, body) {
  response.writeHead(status, { 'Content-Type': 'application/json' })
  response.end(JSON.stringify(body))
}

async function readBody(request) {
  let text = ''
  for await (const chunk of request) text += chunk
  return text
}

http
  .createServer(async (request, response) => {
    const url = new URL(request.url, ISSUER)
    if (url.pathname === '/health') return json(response, 200, { ok: true })
    if (url.pathname === '/.well-known/openid-configuration') {
      return json(response, 200, {
        issuer: ISSUER,
        authorization_endpoint: `${ISSUER}/authorize`,
        token_endpoint: `${ISSUER}/token`,
        jwks_uri: `${ISSUER}/jwks`,
        userinfo_endpoint: `${ISSUER}/userinfo`,
      })
    }
    if (url.pathname === '/jwks') return json(response, 200, { keys: [jwk] })
    if (url.pathname === '/next' && request.method === 'POST') {
      person = JSON.parse((await readBody(request)) || '{}')
      return json(response, 200, person)
    }
    if (url.pathname === '/authorize') {
      const code = randomBytes(16).toString('base64url')
      grants.set(code, {
        clientId: url.searchParams.get('client_id'),
        nonce: url.searchParams.get('nonce'),
        challenge: url.searchParams.get('code_challenge'),
        redirect: url.searchParams.get('redirect_uri'),
        person,
      })
      const back = new URL(url.searchParams.get('redirect_uri'))
      back.searchParams.set('code', code)
      back.searchParams.set('state', url.searchParams.get('state'))
      response.writeHead(302, { Location: back.toString() })
      return response.end()
    }
    if (url.pathname === '/token' && request.method === 'POST') {
      const form = new URLSearchParams(await readBody(request))
      const grant = grants.get(form.get('code'))
      grants.delete(form.get('code'))
      const verifier = createHash('sha256').update(form.get('code_verifier') || '').digest('base64url')
      if (!grant || verifier !== grant.challenge || form.get('redirect_uri') !== grant.redirect) {
        return json(response, 400, { error: 'invalid_grant' })
      }
      const now = Math.floor(Date.now() / 1000)
      const token = idToken({ iss: ISSUER, aud: grant.clientId, exp: now + 300, iat: now, nonce: grant.nonce, ...grant.person })
      return json(response, 200, { id_token: token, access_token: randomBytes(8).toString('hex'), token_type: 'Bearer' })
    }
    if (url.pathname === '/userinfo') return json(response, 200, person)
    response.writeHead(404)
    response.end()
  })
  .listen(PORT, 'localhost')
