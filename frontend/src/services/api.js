/**
 * API service configuration.
 *
 * WebSocket URL resolution order:
 *   1. VITE_WS_URL env var — highest priority, baked in at build time.
 *
 *   2. ws://localhost:8000 when served from localhost / 127.0.0.1.
 *      Connects DIRECTLY to the FastAPI backend — bypasses the Vite dev-server
 *      proxy.  The Vite proxy performs an HTTP redirect (303) during the
 *      WebSocket upgrade handshake instead of forwarding the upgrade, which
 *      makes the connection fail entirely.  Direct connection is safe because
 *      the backend sets Access-Control-Allow-Origin: * on all responses.
 *      Works for both "npm run dev" and Docker Compose (port 8000 is
 *      host-mapped in both cases).
 *
 *   3. Same-origin /api/* for any other hostname — nginx at port 80 proxies
 *      the WebSocket to the backend container (production).
 */

function resolveWsBaseUrl() {
    // 1. Explicit build-time override always wins
    if (import.meta.env.VITE_WS_URL) return import.meta.env.VITE_WS_URL

    const { hostname, protocol } = window.location
    const wsProtocol = protocol === 'https:' ? 'wss:' : 'ws:'
    const isLocal = hostname === 'localhost' || hostname === '127.0.0.1'

    // 2. Local dev / Docker on localhost: direct connection to the backend port
    if (isLocal) {
        return `${wsProtocol}//localhost:8000`
    }

    // 3. Production / remote server: nginx proxy at the same origin
    return `${wsProtocol}//${window.location.host}`
}

const WS_BASE_URL = resolveWsBaseUrl()

export const CALL_WS_URL = `${WS_BASE_URL}/api/call`
