import { useEffect, useRef, useState } from 'react'

async function call(path, opts) {
  const r = await fetch(`/api${path}`, opts)
  if (!r.ok) throw new Error(`${r.status} ${path}`)
  return r.json()
}

export const get = (path) => call(path)

export const post = (path, body) =>
  call(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

export function useStream(onEvent, onOpen) {
  const [live, setLive] = useState(false)
  const handlers = useRef({ onEvent, onOpen })
  handlers.current = { onEvent, onOpen }

  useEffect(() => {
    const es = new EventSource('/api/stream')
    es.onopen = () => {
      setLive(true)
      handlers.current.onOpen?.()
    }
    es.onerror = () => setLive(false)
    es.onmessage = (m) => {
      try {
        handlers.current.onEvent(JSON.parse(m.data))
      } catch {}
    }
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

export function useOperator() {
  const [name, setName] = useState(() => {
    try {
      return localStorage.getItem('operator') || ''
    } catch {
      return ''
    }
  })
  const save = (v) => {
    setName(v)
    try {
      localStorage.setItem('operator', v)
    } catch {}
  }
  return [name, save]
}

export const money = (v, cur = 'EUR') =>
  v == null ? '—' : `${cur} ${Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

export const secs = (ms) => (ms == null ? '—' : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`)

export const mmss = (s) => (s == null ? '—' : `${Math.floor(s / 60)}:${String(Math.round(s) % 60).padStart(2, '0')}`)

export const clock = (ts) => (ts ? new Date(ts * 1000).toLocaleTimeString('en-GB') : '—')

export const ago = (ts, now) => {
  const s = Math.max(0, Math.round(now - ts))
  return s < 60 ? `${s}s ago` : s < 3600 ? `${Math.floor(s / 60)}m ago` : `${Math.floor(s / 3600)}h ago`
}
