import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv, type ProxyOptions } from 'vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // Mailpit rejects any cross-origin request by default (confirmed live:
  // "Blocked due to CORS violation" for an Origin header that isn't its
  // own) and range/docker-compose.yml never configures it to allow one -
  // so the browser must never talk to it directly. Proxying same-origin
  // through Vite's own dev server (mailpitSource.ts's calls all become
  // relative, App.tsx's mailpitBaseUrl default) means the actual
  // cross-origin request happens server-side, in Node, where CORS doesn't
  // apply at all - no Mailpit flag to remember, nothing to misconfigure.
  //
  // `changeOrigin` only rewrites the outgoing request's `Host` header, not
  // `Origin` - and browsers attach a real `Origin` header to PUT/DELETE
  // (and any other non-GET/HEAD) requests even when the page's own fetch
  // call is same-origin, which a plain GET does not do. That's why the
  // inbox list (GET) worked while Mark all read/Delete all (PUT/DELETE)
  // got "403: Blocked due to CORS violation" straight from Mailpit itself -
  // the browser's real Origin was reaching it unmodified. `configure`
  // strips the header before the request leaves this process, so Mailpit
  // sees the same shape of request a plain curl call already does (proven
  // to work every time it was tested directly).
  const mailpitTarget = env.VITE_MAILPIT_URL || 'http://localhost:8025'
  const mailpitProxy: ProxyOptions = {
    target: mailpitTarget,
    changeOrigin: true,
    rewrite: (path) => path.replace(/^\/mailpit-api/, ''),
    configure: (proxy) => {
      proxy.on('proxyReq', (proxyReq) => {
        proxyReq.removeHeader('origin')
      })
    },
  }
  return {
    plugins: [react()],
    server: {
      proxy: {
        '/mailpit-api': mailpitProxy,
      },
    },
  }
})
