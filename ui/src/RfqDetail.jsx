import { useEffect, useState } from 'react'
import { clock, get, money, secs } from './api'
import { Badge, Countdown } from './RfqList'

const DOT = { ok: 'bg-emerald-400', fail: 'bg-rose-500', start: 'bg-sky-400', info: 'bg-zinc-500' }

const CODE = new RegExp(
  [
    String.raw`(?:EUR|USD|GBP|CHF|PLN|€|\$|£)\s?\d[\d.,]*\d`,
    String.raw`\d[\d.,]*\d?\s?(?:EUR|USD|GBP|CHF|PLN|€)`,
    String.raw`\b(?:WOC|BK|R|TRK)-[A-Za-z0-9_-]+`,
    String.raw`\b\d{4}-\d{2}-\d{2}\b`,
    String.raw`\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*\.? \d{1,2} \w{3,9}\b`,
    String.raw`\b\d[\d.,]*\s?(?:kg|cbm|m³|days?|hours?|pieces?|pcs)\b`,
    String.raw`\b[A-Z]{3}\b`,
  ].join('|'),
  'g',
)

function CodeVsAi({ text }) {
  const parts = []
  let last = 0
  for (const m of text.matchAll(CODE)) {
    if (m.index > last) parts.push(<span key={last}>{text.slice(last, m.index)}</span>)
    parts.push(
      <span key={`c${m.index}`} className="rounded bg-emerald-500/15 px-0.5 font-mono text-[13px] text-emerald-300">
        {m[0]}
      </span>,
    )
    last = m.index + m[0].length
  }
  if (last < text.length) parts.push(<span key={last}>{text.slice(last)}</span>)
  return parts
}

const STAGES = [
  ['Received', () => true],
  ['Read', (e) => /extract|classif/.test(e.step)],
  ['Priced', (e) => /price|source|sheet|portal|bid/.test(e.step)],
  ['Written', (e) => /writ|email|draft|review/.test(e.step)],
  ['Sent', (e) => /send|sent|quote/.test(e.step) && e.status !== 'fail'],
  ['Booked', (e) => e.agent === 'booking' && /book/.test(e.step) && e.status === 'ok'],
]

function Pipeline({ r }) {
  const start = r.received_at
  const events = r.events ?? []
  const reached = STAGES.map(([label, test], i) => {
    if (i === 0) return [label, start]
    const hit = events.find((e) => test({ ...e, step: String(e.step || '').toLowerCase() }))
    return [label, hit ? hit.ts : null]
  })
  return (
    <div className="grid grid-cols-6 gap-1">
      {reached.map(([label, ts], i) => (
        <div key={label} className="min-w-0">
          <div className={`h-1.5 rounded-full ${ts ? 'bg-sky-400' : 'bg-line'} ${i === 0 ? 'rounded-l-full' : ''}`} />
          <div className={`mt-2 truncate text-[11px] ${ts ? 'text-zinc-200' : 'text-muted'}`}>{label}</div>
          <div className="font-mono text-[11px] text-muted">{ts && start ? `+${Math.max(0, Math.round(ts - start))}s` : '—'}</div>
        </div>
      ))}
    </div>
  )
}

function Section({ title, children }) {
  return (
    <section className="border-t border-line px-6 py-5">
      <h4 className="mb-3 text-[11px] font-medium uppercase tracking-wider text-muted">{title}</h4>
      {children}
    </section>
  )
}

export default function RfqDetail({ id, tick, now, operator, onClose }) {
  const [r, setR] = useState(null)
  const [err, setErr] = useState(null)

  useEffect(() => {
    let stale = false
    get(`/rfqs/${id}`)
      .then((d) => !stale && (setR(d), setErr(null)))
      .catch((e) => !stale && setErr(e.message))
    return () => {
      stale = true
    }
  }, [id, tick])

  useEffect(() => {
    setR(null)
  }, [id])

  useEffect(() => {
    const esc = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [onClose])

  if (!r) {
    return (
      <div className="fixed inset-0 z-20 flex justify-end bg-black/50" onClick={onClose}>
        <aside className="h-full w-full max-w-xl border-l border-line bg-panel p-6 text-sm text-muted">
          {err ? `Could not load ${id} (${err}).` : 'Loading...'}
        </aside>
      </div>
    )
  }

  const b = r.breakdown

  return (
    <div className="fixed inset-0 z-20 flex justify-end bg-black/50" onClick={onClose}>
      <aside onClick={(e) => e.stopPropagation()} className="h-full w-full max-w-xl overflow-y-auto border-l border-line bg-panel">
        <header className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-line bg-panel/95 px-6 py-5 backdrop-blur">
          <div>
            <div className="flex items-center gap-2">
              <span className="font-mono text-sm text-white">{r.id}</span>
              <Badge status={r.status} />
              <span className="rounded-md bg-sky-500/15 px-2 py-0.5 text-[11px] text-sky-300">Autonomous</span>
            </div>
            <div className="mt-1 text-sm text-zinc-300">{r.customer}</div>
            <div className="font-mono text-xs text-muted">{r.origin} → {r.destination} · wants {r.preference}</div>
          </div>
          <div className="flex flex-col items-end gap-2">
            <button onClick={onClose} className="text-muted hover:text-white" aria-label="Close">
              <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M6 6l12 12M18 6L6 18" /></svg>
            </button>
            <div className="font-mono text-xs"><Countdown r={r} now={now} /></div>
          </div>
        </header>

        <Section title="Pipeline">
          <Pipeline r={r} />
        </Section>

        <Section title="Price breakdown">
          {b ? (
            <>
              <table className="w-full text-sm">
                <tbody>
                  {(b.lines ?? []).map((l) => (
                    <tr key={l.label}>
                      <td className="py-1 text-zinc-300">{l.label}</td>
                      <td className="py-1 text-right font-mono text-xs">{money(l.amount, b.currency)}</td>
                    </tr>
                  ))}
                  <tr className="border-t border-line font-semibold text-white">
                    <td className="pt-2">All-in total</td>
                    <td className="pt-2 text-right font-mono">{money(b.total, b.currency)}</td>
                  </tr>
                </tbody>
              </table>
              <div className="mt-2 text-xs text-muted">
                {b.chargeable_kg} kg chargeable · from {b.source} · {r.carrier}
              </div>
              {b.candidates?.length > 0 && (
                <div className="mt-4 space-y-1">
                  {b.candidates.map((c) => (
                    <div key={c.carrier} className="flex justify-between text-xs text-muted">
                      <span>{c.carrier} <span className="text-zinc-600">({c.source})</span></span>
                      <span className="font-mono">{money(c.total, b.currency)}</span>
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : (
            <p className="text-sm text-muted">Not priced yet.</p>
          )}
        </Section>

        <Section title="Email sent">
          {r.email_body ? (
            <>
              <div className="mb-2 flex gap-4 text-[11px] text-muted">
                <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-emerald-400" />Set by code: prices, dates, weights, references</span>
                <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-zinc-400" />Written by the model</span>
              </div>
              <pre className="whitespace-pre-wrap rounded-lg bg-ink/70 p-4 font-sans text-sm leading-relaxed text-zinc-200"><CodeVsAi text={r.email_body} /></pre>
            </>
          ) : (
            <p className="text-sm text-muted">Nothing sent yet.</p>
          )}
        </Section>

        <Section title="Timeline">
          <ol className="relative ml-1 border-l border-line">
            {(r.events ?? []).map((e) => (
              <li key={e.id} className="mb-4 ml-4">
                <span className={`absolute -left-[5px] mt-1.5 h-2.5 w-2.5 rounded-full ${DOT[e.status] ?? DOT.info}`} />
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-sm text-zinc-200">{e.message}</span>
                  <span className="shrink-0 font-mono text-[11px] text-muted">{clock(e.ts)}</span>
                </div>
                <div className="font-mono text-[11px] text-muted">
                  {e.agent} · {e.step}
                  {e.duration_ms != null && ` · ${secs(e.duration_ms)}`}
                  {e.llm_cost_usd > 0 && ` · $${e.llm_cost_usd.toFixed(5)}`}
                </div>
              </li>
            ))}
          </ol>
        </Section>
      </aside>
    </div>
  )
}
