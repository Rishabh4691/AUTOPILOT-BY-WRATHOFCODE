import { useEffect, useState } from 'react'
import { clock, get } from './api'

const VERDICT = {
  accepted: 'text-emerald-300 bg-emerald-500/15',
  rejected: 'text-rose-300 bg-rose-500/15',
  open: 'text-sky-300 bg-sky-500/15',
  pending: 'text-amber-300 bg-amber-500/15',
  'no answer': 'text-rose-300 bg-rose-500/15',
  voided: 'text-zinc-300 bg-zinc-500/15',
}

const ts = (iso) => (iso ? clock(new Date(iso).getTime() / 1000) : '—')

function Stat({ label, value, tone = 'text-white' }) {
  return (
    <div className="min-w-0 bg-panel px-4 py-3">
      <div className="text-[11px] uppercase tracking-wider text-muted">{label}</div>
      <div className={`mt-1 truncate font-mono text-lg ${tone}`}>{value}</div>
    </div>
  )
}

export default function Scoreboard() {
  const [d, setD] = useState(null)
  const [err, setErr] = useState(null)

  useEffect(() => {
    let alive = true
    const load = () =>
      get('/board')
        .then((x) => alive && (setD(x), setErr(null)))
        .catch((e) => alive && setErr(e.message))
    load()
    const t = setInterval(load, 10000)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [])

  if (!d) return <div className="rounded-xl border border-line bg-panel p-10 text-center text-muted">{err ? `Board unavailable: ${err}` : 'Loading the live board...'}</div>

  const rounds = d.rounds ?? []
  const accepted = rounds.filter((r) => r.verdict === 'accepted').length
  const rejected = rounds.filter((r) => r.verdict === 'rejected').length
  const booked = rounds.filter((r) => r.booked === true).length
  const timeLost = rounds.reduce((s, r) => s + (r.verdict === 'accepted' ? 15 - r.time_points : 0), 0)
  const answered = rounds.filter((r) => r.seconds != null).map((r) => r.seconds).sort((a, b) => a - b)
  const median = answered.length ? answered[Math.floor(answered.length / 2)] : null
  const third = d.ranking?.find((r) => r.rank === 3)

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Rank" value={`#${d.rank}`} tone={d.rank <= 3 ? 'text-emerald-300' : 'text-white'} />
        <Stat label="Points" value={d.total} />
        <Stat label="Gap to #3" value={third && d.rank > 3 ? `${(third.total - d.total).toFixed(1)}` : '—'} tone="text-amber-300" />
        <Stat label="Accepted" value={`${accepted}/${rounds.length}`} />
        <Stat label="Booked" value={booked} />
        <Stat label="Median answer" value={median == null ? '—' : `${Math.round(median)} s`} />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <section className="overflow-x-auto rounded-xl border border-line bg-panel lg:col-span-2">
          <div className="flex items-baseline justify-between border-b border-line px-4 py-3">
            <h3 className="text-sm font-semibold text-white">Rounds</h3>
            <span className="text-xs text-muted">
              {rejected} rejected · {timeLost.toFixed(1)} time points lost · cost points arrive hourly
            </span>
          </div>
          <table className="w-full text-sm">
            <thead className="text-left text-[11px] uppercase tracking-wider text-muted">
              <tr className="border-b border-line">
                <th className="px-4 py-2 font-medium">#</th>
                <th className="px-4 py-2 font-medium">Sent</th>
                <th className="px-4 py-2 font-medium">Answer</th>
                <th className="px-4 py-2 font-medium">Verdict</th>
                <th className="px-4 py-2 font-medium">Booked</th>
                <th className="px-4 py-2 font-medium">Where points went</th>
              </tr>
            </thead>
            <tbody>
              {rounds.map((r) => (
                <tr key={r.round_no} className="border-b border-line/60 last:border-0 align-top">
                  <td className="px-4 py-2 font-mono text-xs">{r.round_no}</td>
                  <td className="px-4 py-2 font-mono text-xs">{ts(r.sent_at)}</td>
                  <td className={`px-4 py-2 font-mono text-xs ${r.seconds == null ? 'text-muted' : r.seconds <= 120 ? 'text-emerald-300' : 'text-amber-300'}`}>
                    {r.seconds == null ? '—' : `${Math.round(r.seconds)} s`}
                  </td>
                  <td className="px-4 py-2">
                    <span className={`rounded-md px-2 py-0.5 text-[11px] font-medium ${VERDICT[r.verdict] ?? VERDICT.voided}`}>
                      {r.verdict}{r.reason ? ` · ${r.reason}` : ''}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-xs">{r.booked === true ? 'yes' : r.booked === false ? <span className="text-rose-300">no</span> : '—'}</td>
                  <td className="px-4 py-2 text-xs text-zinc-300">{r.lost?.length ? r.lost.join('; ') : <span className="text-emerald-300">full time points</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="rounded-xl border border-line bg-panel">
          <h3 className="border-b border-line px-4 py-3 text-sm font-semibold text-white">Leaderboard</h3>
          <ol>
            {(d.ranking ?? []).map((t) => (
              <li
                key={t.name}
                className={`flex items-center justify-between border-b border-line/60 px-4 py-2 text-sm last:border-0 ${t.name === d.team ? 'bg-sky-500/10 text-white' : 'text-zinc-300'}`}
              >
                <span className="flex items-center gap-3">
                  <span className="w-5 font-mono text-xs text-muted">{t.rank}</span>
                  {t.team}
                </span>
                <span className="font-mono text-xs">
                  {t.total} <span className="text-muted">· {t.accepted}/{t.answered} · bk {t.bookings}</span>
                </span>
              </li>
            ))}
          </ol>
        </section>
      </div>
    </div>
  )
}
