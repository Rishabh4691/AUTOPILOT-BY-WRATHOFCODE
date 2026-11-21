import { useEffect, useState } from 'react'
import { clock, get, money, post, secs } from './api'
import { Badge, Countdown } from './RfqList'

const DOT = { ok: 'bg-emerald-400', fail: 'bg-rose-500', start: 'bg-sky-400', info: 'bg-zinc-500' }

function Section({ title, children }) {
  return (
    <section className="border-t border-line px-6 py-5">
      <h4 className="mb-3 text-[11px] font-medium uppercase tracking-wider text-muted">{title}</h4>
      {children}
    </section>
  )
}

export default function RfqDetail({ id, tick, now, onClose }) {
  const [r, setR] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    get(`/rfqs/${id}`).then(setR)
  }, [id, tick])

  useEffect(() => {
    const esc = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [onClose])

  if (!r) return null
  const b = r.breakdown
  const human = !!r.human_takeover

  const toggle = async () => {
    setBusy(true)
    await post(`/rfqs/${id}/takeover`, { on: !human, by: 'Rishabh' })
    setR(await get(`/rfqs/${id}`))
    setBusy(false)
  }

  return (
    <div className="fixed inset-0 z-20 flex justify-end bg-black/50" onClick={onClose}>
      <aside onClick={(e) => e.stopPropagation()} className="h-full w-full max-w-xl overflow-y-auto border-l border-line bg-panel">
        <header className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-line bg-panel/95 px-6 py-5 backdrop-blur">
          <div>
            <div className="flex items-center gap-2">
              <span className="font-mono text-sm text-white">{r.id}</span>
              <Badge status={r.status} />
            </div>
            <div className="mt-1 text-sm text-zinc-300">{r.customer}</div>
            <div className="font-mono text-xs text-muted">{r.origin} → {r.destination} · wants {r.preference}</div>
          </div>
          <div className="flex flex-col items-end gap-2">
            <button onClick={onClose} className="text-muted hover:text-white" aria-label="Close">✕</button>
            <div className="font-mono text-xs"><Countdown r={r} now={now} /></div>
          </div>
        </header>

        <div className="px-6 py-4">
          <button
            onClick={toggle}
            disabled={busy}
            className={`w-full rounded-lg px-4 py-2.5 text-sm font-semibold transition ${
              human ? 'bg-zinc-200 text-ink hover:bg-white' : 'bg-amber-500 text-ink hover:bg-amber-400'
            } disabled:opacity-50`}
          >
            {human ? 'Hand back to autopilot' : 'Take over'}
          </button>
          {human && <p className="mt-2 text-xs text-amber-300">You have the controls. The bot won't send anything on this thread.</p>}
        </div>

        <Section title="Price breakdown">
          {b ? (
            <>
              <table className="w-full text-sm">
                <tbody>
                  {b.lines.map((l) => (
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
            <pre className="whitespace-pre-wrap rounded-lg bg-ink/70 p-4 font-sans text-sm leading-relaxed text-zinc-200">{r.email_body}</pre>
          ) : (
            <p className="text-sm text-muted">Nothing sent yet.</p>
          )}
        </Section>

        <Section title="Timeline">
          <ol className="relative ml-1 border-l border-line">
            {r.events.map((e) => (
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
