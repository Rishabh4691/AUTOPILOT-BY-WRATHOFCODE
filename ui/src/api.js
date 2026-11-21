import { useEffect, useRef, useState } from 'react'

export const get = (path) => fetch(`/api${path}`).then((r) => r.json())

export const post = (path, body) =>
  fetch(`/api${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then((r) => r.json())

export function useStream(onEvent) {
  const [live, setLive] = useState(false)
  const handler = useRef(onEvent)
  handler.current = onEvent

  useEffect(() => {
    const es = new EventSource('/api/stream')
    es.onopen = () => setLive(true)
    es.onerror = () => setLive(false)
    es.onmessage = (m) => handler.current(JSON.parse(m.data))
    return () => es.close()
  }, [])

  return live
}

export function useNow(ms = 1000) {
  const [now, setNow] = useState(Date.now() / 1000)
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now() / 1000), ms)
    return () => clearInterval(t)
  }, [ms])
  return now
}

export const money = (v, cur = 'EUR') =>
  v == null ? '—' : `${cur} ${v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

export const secs = (ms) => (ms == null ? '—' : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`)

export const clock = (ts) => new Date(ts * 1000).toLocaleTimeString('en-GB')

export const ago = (ts, now) => {
  const s = Math.max(0, Math.round(now - ts))
  return s < 60 ? `${s}s ago` : s < 3600 ? `${Math.floor(s / 60)}m ago` : `${Math.floor(s / 3600)}h ago`
}
