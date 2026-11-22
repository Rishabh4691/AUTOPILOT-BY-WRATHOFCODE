import { useEffect, useState } from 'react'
import { get, money } from './api'
import { useT } from './prefs'

const day = (v) => (v ? new Date(`${String(v).slice(0, 10)}T12:00:00`).toLocaleDateString(undefined, { day: '2-digit', month: 'short' }) : '—')

function Table({ rows, t }) {
  if (!rows.length) return <p className="px-4 py-6 text-sm text-muted">{t('noShipments')}</p>
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-[11px] uppercase tracking-wider text-muted">
          <tr>
            <th className="px-4 py-2">{t('reference')}</th>
            <th className="px-4 py-2">{t('lane')}</th>
            <th className="px-4 py-2">{t('airline')}</th>
            <th className="px-4 py-2">{t('arrival')}</th>
            <th className="px-4 py-2 text-right">{t('price')}</th>
            <th className="px-4 py-2 text-right">{t('updatesSent')}</th>
            <th className="px-4 py-2">{t('status')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.rfq_id} className="border-t border-line">
              <td className="px-4 py-2">
                <div className="font-mono text-zinc-200">{r.team_reference}</div>
                <div className="font-mono text-[11px] text-muted">{r.booking_reference || 'pending'}</div>
              </td>
              <td className="px-4 py-2 font-mono text-zinc-300">{r.origin && r.destination ? `${r.origin} → ${r.destination}` : '—'}</td>
              <td className="px-4 py-2 text-zinc-300">{r.carrier || '—'}</td>
              <td className="px-4 py-2 font-mono text-zinc-300">{day(r.eta)}</td>
              <td className="px-4 py-2 text-right font-mono">{r.price ? money(r.price, r.currency || 'EUR') : '—'}</td>
              <td className="px-4 py-2 text-right font-mono text-muted">{r.updates || 0}</td>
              <td className="px-4 py-2">
                <span className={`rounded-md px-2 py-0.5 text-[11px] ${r.delivered ? 'bg-emerald-500/15 text-emerald-300' : 'bg-sky-500/15 text-sky-300'}`}>
                  {r.note || r.status || (r.delivered ? t('delivered') : t('booked'))}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function Shipments() {
  const t = useT()
  const [view, setView] = useState('booked')
  const [data, setData] = useState({ booked: [], delivered: [] })
  const [err, setErr] = useState(null)

  useEffect(() => {
    let alive = true
    const load = () =>
      get('/shipments')
        .then((d) => alive && (setData(d), setErr(null)))
        .catch((e) => alive && setErr(e.message))
    load()
    const timer = setInterval(load, 30000)
    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [])

  return (
    <section className="rounded-xl border border-line bg-panel">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
        <div className="flex overflow-hidden rounded-lg border border-line text-xs">
          {['booked', 'delivered'].map((k) => (
            <button key={k} onClick={() => setView(k)} className={`px-3 py-1.5 ${view === k ? 'bg-sky-500/15 text-sky-300' : 'text-muted hover:text-zinc-200'}`}>
              {t(k)} ({data[k]?.length ?? 0})
            </button>
          ))}
        </div>
        {err && <span className="text-xs text-rose-300">{err}</span>}
      </header>
      <Table rows={data[view] ?? []} t={t} />
    </section>
  )
}
