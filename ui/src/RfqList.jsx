import { clock, mmss, money } from './api'

export const STATUS = {
  NEW: 'text-zinc-300 bg-zinc-500/15',
  EXTRACTED: 'text-sky-300 bg-sky-500/15',
  SOURCING: 'text-sky-300 bg-sky-500/15',
  PRICED: 'text-violet-300 bg-violet-500/15',
  QUOTED: 'text-emerald-300 bg-emerald-500/15',
  ACCEPTED: 'text-emerald-300 bg-emerald-500/15',
  BOOKED: 'text-emerald-200 bg-emerald-500/25',
  TRACKING: 'text-emerald-200 bg-emerald-500/25',
  FAILED: 'text-rose-300 bg-rose-500/15',
}

const OPEN = ['NEW', 'EXTRACTED', 'SOURCING', 'PRICED']

export function Countdown({ r, now }) {
  if (r.quoted_at && r.received_at) {
    const s = Math.round(r.quoted_at - r.received_at)
    return <span className={s <= 120 ? 'text-emerald-300' : 'text-amber-300'}>in {mmss(s)}</span>
  }
  if (!OPEN.includes(String(r.status).toUpperCase()) || !r.deadline) return <span className="text-muted">—</span>
  if (r.human_takeover) return <span className="text-amber-300">Human</span>
  const left = Math.max(0, Math.round(r.deadline - now))
  if (left === 0) return <span className="text-rose-400">Missed</span>
  const color = left > 240 ? 'text-emerald-300' : left > 120 ? 'text-amber-300' : 'text-rose-400 blip'
  const pct = (left / 360) * 100
  return (
    <div className="w-24">
      <span className={color}>{mmss(left)}</span>
      <div className="mt-1 h-1 rounded-full bg-line">
        <div className={`h-full rounded-full ${left > 240 ? 'bg-emerald-400' : left > 120 ? 'bg-amber-400' : 'bg-rose-500'}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

export function Badge({ status }) {
  const s = String(status ?? 'NEW').toUpperCase()
  return <span className={`rounded-md px-2 py-0.5 text-[11px] font-medium ${STATUS[s] ?? STATUS.NEW}`}>{s}</span>
}

export default function RfqList({ rfqs, now, selected, onOpen }) {
  if (!rfqs.length) {
    return <div className="rounded-xl border border-line bg-panel p-10 text-center text-muted">No RFQs yet. First one lands at 16:00.</div>
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-line bg-panel">
      <table className="w-full text-sm">
        <thead className="text-left text-[11px] uppercase tracking-wider text-muted">
          <tr className="border-b border-line">
            <th className="px-4 py-3 font-medium">RFQ</th>
            <th className="px-4 py-3 font-medium">Customer</th>
            <th className="px-4 py-3 font-medium">Route</th>
            <th className="px-4 py-3 font-medium">Wants</th>
            <th className="px-4 py-3 font-medium">Status</th>
            <th className="px-4 py-3 font-medium">Time left</th>
            <th className="px-4 py-3 text-right font-medium">Total</th>
          </tr>
        </thead>
        <tbody>
          {rfqs.map((r) => (
            <tr
              key={r.id}
              onClick={() => onOpen(r.id)}
              className={`cursor-pointer border-b border-line/60 last:border-0 hover:bg-white/[0.03] ${selected === r.id ? 'bg-white/[0.05]' : ''}`}
            >
              <td className="px-4 py-3 font-mono text-xs">
                {r.id}
                {r.human_takeover ? <span className="ml-2 rounded bg-amber-500/20 px-1.5 text-[10px] text-amber-300">HUMAN</span> : null}
                <div className="text-[11px] text-muted">{clock(r.received_at)}</div>
              </td>
              <td className="px-4 py-3">{r.customer}</td>
              <td className="px-4 py-3 font-mono text-xs">{r.origin} → {r.destination}</td>
              <td className="px-4 py-3 capitalize text-zinc-300">{r.preference ?? '—'}</td>
              <td className="px-4 py-3"><Badge status={r.status} /></td>
              <td className="px-4 py-3 font-mono text-xs"><Countdown r={r} now={now} /></td>
              <td className="px-4 py-3 text-right font-mono text-xs">{money(r.total, r.currency ?? 'EUR')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
