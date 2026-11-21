import { useEffect, useState } from 'react'
import { get, post, useOperator } from './api'

const when = (iso) => (iso ? new Date(iso).toLocaleTimeString('en-GB') : '—')

function Mail({ m, tone = 'border-line' }) {
  const [open, setOpen] = useState(false)
  if (!m) return null
  const long = (m.body || '').length > 420
  return (
    <div className={`rounded-lg border ${tone} bg-ink/60 p-3`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2 text-xs">
        <span className="font-mono text-zinc-300">{m.from}</span>
        <span className="font-mono text-muted">{when(m.at)}</span>
      </div>
      <div className="mt-1 text-sm font-medium text-white">{m.subject}</div>
      {m.attachments?.length > 0 && <div className="mt-1 text-xs text-amber-300">Attachments: {m.attachments.join(', ')}</div>}
      <pre className="mt-2 whitespace-pre-wrap font-sans text-sm leading-relaxed text-zinc-200">
        {open || !long ? m.body : `${m.body.slice(0, 420)}…`}
      </pre>
      {long && (
        <button onClick={() => setOpen(!open)} className="mt-1 text-xs text-sky-300 hover:text-sky-200">
          {open ? 'Show less' : 'Show all'}
        </button>
      )}
    </div>
  )
}

function Section({ title, children }) {
  return (
    <section className="border-t border-line px-6 py-5">
      <h4 className="mb-3 text-[11px] font-medium uppercase tracking-wider text-muted">{title}</h4>
      <div className="space-y-3">{children}</div>
    </section>
  )
}

export default function RoundDetail({ round, onClose }) {
  const [d, setD] = useState(null)
  const [err, setErr] = useState(null)
  const [note, setNote] = useState('')
  const [saved, setSaved] = useState(false)
  const [operator] = useOperator()

  useEffect(() => {
    let alive = true
    setD(null)
    get(`/rounds/${round}`)
      .then((x) => alive && (setD(x), setNote((x.note || '').replace(/\n\(by .*\)$/, ''))))
      .catch((e) => alive && setErr(e.message))
    return () => {
      alive = false
    }
  }, [round])

  useEffect(() => {
    const esc = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [onClose])

  const save = async () => {
    await post(`/rounds/${round}/note`, { text: note, by: operator || 'team' })
    setSaved(true)
    setTimeout(() => setSaved(false), 1500)
  }

  const verdictTone =
    d?.verdict === 'accepted' ? 'text-emerald-300' : d?.verdict === 'rejected' ? 'text-rose-300' : 'text-sky-300'
  const others = d?.others_booked ?? []
  const airlines = others.reduce((acc, b) => ({ ...acc, [b.airline]: (acc[b.airline] || 0) + 1 }), {})

  return (
    <div className="fixed inset-0 z-30 flex justify-end bg-black/50" onClick={onClose}>
      <aside onClick={(e) => e.stopPropagation()} className="h-full w-full max-w-2xl overflow-y-auto border-l border-line bg-panel">
        <header className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-line bg-panel/95 px-6 py-5 backdrop-blur">
          <div>
            <div className="text-sm text-muted">Round {round}</div>
            {d && (
              <div className={`mt-1 text-lg font-semibold ${verdictTone}`}>
                {d.verdict}
                {d.reason ? ` · ${d.reason}` : ''}
              </div>
            )}
            {d?.points && Object.keys(d.points).length > 0 && (
              <div className="mt-1 font-mono text-xs text-muted">
                {Object.entries(d.points)
                  .map(([k, v]) => `${k} ${v}`)
                  .join(' · ')}
              </div>
            )}
          </div>
          <button onClick={onClose} className="text-muted hover:text-white" aria-label="Close">
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </header>

        {!d && <div className="p-6 text-sm text-muted">{err ? `Could not load round ${round}: ${err}` : 'Loading the mails for this round...'}</div>}

        {d && (
          <>
            <Section title="Your notes: what was wrong, what should we do">
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                rows={3}
                placeholder="For example: should have used the cheapest trucker within 24 h, airport should be STR..."
                className="w-full rounded-lg border border-line bg-ink p-3 text-sm text-zinc-200 placeholder:text-muted focus:border-sky-500 focus:outline-none"
              />
              <button onClick={save} className="rounded-md bg-sky-500 px-3 py-1.5 text-xs font-semibold text-ink hover:bg-sky-400">
                {saved ? 'Saved' : 'Save note'}
              </button>
            </Section>

            <Section title="What the accepted teams booked">
              {others.length === 0 ? (
                <p className="text-sm text-muted">No bookings by other teams in this round yet.</p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {Object.entries(airlines).map(([a, n]) => (
                    <span key={a} className="rounded-md bg-emerald-500/15 px-2 py-1 text-xs text-emerald-200">
                      {a} · {n} team{n > 1 ? 's' : ''}
                    </span>
                  ))}
                </div>
              )}
            </Section>

            <Section title="Customer request">
              {d.request ? <Mail m={d.request} tone="border-sky-500/30" /> : <p className="text-sm text-muted">Request mail not found.</p>}
            </Section>

            <Section title="Our reply">
              {d.reply ? <Mail m={d.reply} tone="border-emerald-500/30" /> : <p className="text-sm text-muted">No reply from us found.</p>}
            </Section>

            {d.customer?.length > 0 && (
              <Section title="Customer answers">
                {d.customer.map((m) => (
                  <Mail key={m.id} m={m} />
                ))}
              </Section>
            )}

            <Section title={`Trucker, airline and rate desk replies (${d.related?.length ?? 0})`}>
              {d.related?.length ? d.related.map((m) => <Mail key={m.id} m={m} />) : <p className="text-sm text-muted">None for this round.</p>}
            </Section>
          </>
        )}
      </aside>
    </div>
  )
}
