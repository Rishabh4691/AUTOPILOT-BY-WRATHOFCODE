import { useEffect, useState } from 'react'
import { get } from './api'
import { useT } from './prefs'

const when = (ts) => (ts ? new Date(ts * 1000).toLocaleString(undefined, { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—')

export default function Claims() {
  const t = useT()
  const [rows, setRows] = useState([])
  const [err, setErr] = useState(null)

  useEffect(() => {
    let alive = true
    const load = () =>
      get('/claims')
        .then((d) => alive && (setRows(d), setErr(null)))
        .catch((e) => alive && setErr(e.message))
    load()
    const timer = setInterval(load, 30000)
    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [])

  if (err) return <p className="text-sm text-rose-300">{err}</p>
  if (!rows.length) return <p className="rounded-xl border border-line bg-panel px-4 py-6 text-sm text-muted">{t('noClaims')}</p>

  return (
    <div className="grid gap-3 md:grid-cols-2">
      {rows.map((c) => (
        <article key={c.claim_id} className="rounded-xl border border-line bg-panel p-4">
          <div className="flex items-center justify-between gap-3">
            <span className="font-mono text-sm text-white">{c.claim_id.replace(/-\d+$/, '')}</span>
            <span className={`rounded-md px-2 py-0.5 text-[11px] ${c.kind === 'lost' ? 'bg-rose-500/15 text-rose-300' : 'bg-amber-500/15 text-amber-300'}`}>
              {t(c.kind)}
            </span>
          </div>
          <div className="mt-2 grid grid-cols-2 gap-y-1 text-xs text-muted">
            <span>{t('reference')}</span><span className="text-right font-mono text-zinc-300">{c.booking_reference}</span>
            <span>{t('customer')}</span><span className="truncate text-right text-zinc-300">{c.customer}</span>
            <span>{t('filedWith')}</span><span className="truncate text-right text-zinc-300">{c.carrier || '—'}</span>
            <span>{t('filed')}</span><span className="text-right font-mono text-zinc-300">{when(c.filed_at)}</span>
          </div>
          <div className="mt-3 text-[11px] uppercase tracking-wider text-muted">{t('description')}</div>
          <p className="mt-1 whitespace-pre-wrap text-sm text-zinc-300">{c.description}</p>
        </article>
      ))}
    </div>
  )
}
