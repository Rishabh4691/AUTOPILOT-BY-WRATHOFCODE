import { useEffect, useState } from 'react'
import { MailWarning, PackageSearch, PackageX, Plane, ShieldCheck, Send } from 'lucide-react'
import { get } from './api'
import { useLang, useT } from './prefs'

const when = (ts) => (ts ? new Date(ts * 1000).toLocaleString(undefined, { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—')

const KINDS = {
  lost: { color: '#e5484d', Icon: PackageX },
  misplaced: { color: '#8b5cf6', Icon: PackageSearch },
  damaged: { color: '#e0a030', Icon: MailWarning },
}

const COPY = {
  en: {
    empty: 'No claims yet. No customer has reported a problem with a booked shipment.',
    kindsTitle: 'What the bot files',
    kinds: {
      lost: ['Lost', '“never arrived”, “went missing”, “nicht angekommen”, “perdu en transit”'],
      misplaced: ['Misplaced', '“sent to the wrong airport”, “misrouted”, “fehlgeleitet”, “mal acheminé”'],
      damaged: ['Damaged', '“arrived damaged”, “broken”, “crushed”, “beschädigt”, “danneggiato”'],
    },
    flowTitle: 'How a claim runs, with no human in the loop',
    flow: [
      ['Customer reports', 'A reply on a booked shipment, in any of five languages.'],
      ['Bot matches the booking', 'By the BK or WOC reference, or the thread it belongs to.'],
      ['Files with the airline', 'Claim mail to the carrier with the booking and the customer’s words.'],
      ['Confirms to the customer', 'Claim number, airline, and a request for photos or a delivery receipt.'],
    ],
    fieldsTitle: 'Every claim records',
    fields: ['Claim no.', 'Type', '5U booking', 'Our reference', 'Customer', 'Airline', 'Airline email', 'Customer’s description', 'Filed at', 'Status'],
    code: 'In the code: core/agents/claims.py, tested in tests/core/test_updates_claims.py',
  },
  de: {
    empty: 'Noch keine Schäden. Kein Kunde hat ein Problem mit einer gebuchten Sendung gemeldet.',
    kindsTitle: 'Was der Bot meldet',
    kinds: {
      lost: ['Verloren', '„nicht angekommen“, „verloren gegangen“, „never arrived“, „perdu en transit“'],
      misplaced: ['Fehlgeleitet', '„fehlgeleitet“, „falsch zugestellt“, „sent to the wrong airport“, „misrouted“'],
      damaged: ['Beschädigt', '„beschädigt“, „zerbrochen“, „arrived damaged“, „danneggiato“'],
    },
    flowTitle: 'So läuft ein Schaden, ohne Menschen dazwischen',
    flow: [
      ['Kunde meldet', 'Eine Antwort zu einer gebuchten Sendung, in fünf Sprachen.'],
      ['Bot findet die Buchung', 'Über die BK- oder WOC-Referenz oder den Mailverlauf.'],
      ['Meldet bei der Airline', 'Schadensmail an die Airline mit Buchung und Worten des Kunden.'],
      ['Bestätigt dem Kunden', 'Schadensnummer, Airline und Bitte um Fotos oder Ablieferschein.'],
    ],
    fieldsTitle: 'Jeder Schaden enthält',
    fields: ['Schadensnr.', 'Art', '5U-Buchung', 'Unsere Referenz', 'Kunde', 'Airline', 'Airline-Mail', 'Beschreibung des Kunden', 'Gemeldet am', 'Status'],
    code: 'Im Code: core/agents/claims.py, getestet in tests/core/test_updates_claims.py',
  },
}

const FLOW_ICONS = [MailWarning, PackageSearch, Plane, Send]

function Empty({ c }) {
  return (
    <div className="space-y-6">
      <p className="glass lb-rise flex items-center gap-3 rounded-[28px] px-6 py-5 text-zinc-300">
        <ShieldCheck className="size-5 shrink-0 text-[#2fb37a]" aria-hidden /> {c.empty}
      </p>

      <section className="glass lb-rise rounded-[28px] p-6">
        <h3 className="text-[11px] tracking-[0.16em] text-muted uppercase">{c.kindsTitle}</h3>
        <ul className="mt-4 grid gap-3 sm:grid-cols-3">
          {Object.entries(KINDS).map(([k, { color, Icon }]) => (
            <li key={k} className="rounded-2xl border border-[color-mix(in_oklch,var(--color-foreground)_10%,transparent)] p-4">
              <span className="inline-flex items-center gap-2 rounded-full px-3 py-1 text-[12px] font-bold text-[#fff]" style={{ background: color }}>
                <Icon className="size-3.5" aria-hidden /> {c.kinds[k][0]}
              </span>
              <p className="mt-3 text-[13px] text-zinc-400">{c.kinds[k][1]}</p>
            </li>
          ))}
        </ul>
      </section>

      <section className="glass lb-rise rounded-[28px] p-6">
        <h3 className="text-[11px] tracking-[0.16em] text-muted uppercase">{c.flowTitle}</h3>
        <ol className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {c.flow.map(([title, text], i) => {
            const Icon = FLOW_ICONS[i]
            return (
              <li key={title} className="relative rounded-2xl border border-[color-mix(in_oklch,var(--color-foreground)_10%,transparent)] p-4">
                <span className="font-display text-[28px] leading-none text-accent">{i + 1}</span>
                <Icon className="absolute top-4 right-4 size-5 text-zinc-400" aria-hidden />
                <p className="mt-2 font-semibold text-white">{title}</p>
                <p className="mt-1 text-[13px] text-zinc-400">{text}</p>
              </li>
            )
          })}
        </ol>
      </section>

      <section className="glass lb-rise rounded-[28px] p-6">
        <h3 className="text-[11px] tracking-[0.16em] text-muted uppercase">{c.fieldsTitle}</h3>
        <ul className="mt-4 flex flex-wrap gap-2">
          {c.fields.map((f) => (
            <li key={f} className="rounded-full border border-[color-mix(in_oklch,var(--color-foreground)_12%,transparent)] px-3 py-1.5 text-[13px] text-zinc-300">{f}</li>
          ))}
        </ul>
        <p className="mt-4 font-mono text-[12px] text-muted">{c.code}</p>
      </section>
    </div>
  )
}

export default function Claims() {
  const t = useT()
  const [lang] = useLang()
  const c = COPY[lang] ?? COPY.en
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
  if (!rows.length) return <Empty c={c} />

  return (
    <div className="grid gap-4 md:grid-cols-2">
      {rows.map((r) => {
        const k = KINDS[r.kind] ?? KINDS.damaged
        return (
          <article key={r.claim_id} className="glass lb-rise rounded-[28px] p-5">
            <div className="flex items-center justify-between gap-3">
              <span className="font-display text-lg text-white">{r.claim_id.replace(/-\d+$/, '')}</span>
              <span className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[12px] font-bold text-[#fff]" style={{ background: k.color }}>
                <k.Icon className="size-3.5" aria-hidden /> {c.kinds[r.kind]?.[0] ?? r.kind}
              </span>
            </div>
            <dl className="mt-3 grid grid-cols-2 gap-y-1.5 text-[13px]">
              <dt className="text-muted">{t('reference')}</dt><dd className="text-right font-mono text-zinc-200">{r.booking_reference || '—'}</dd>
              <dt className="text-muted">{t('customer')}</dt><dd className="truncate text-right text-zinc-200">{r.customer}</dd>
              <dt className="text-muted">{t('filedWith')}</dt><dd className="truncate text-right text-zinc-200">{r.carrier || '—'}</dd>
              <dt className="text-muted">{t('filed')}</dt><dd className="text-right font-mono text-zinc-200">{when(r.filed_at)}</dd>
              <dt className="text-muted">{t('status')}</dt><dd className="text-right text-zinc-200">{r.status}</dd>
            </dl>
            <div className="mt-3 text-[11px] tracking-[0.12em] text-muted uppercase">{t('description')}</div>
            <p className="mt-1 whitespace-pre-wrap text-[13px] text-zinc-300">{r.description}</p>
          </article>
        )
      })}
    </div>
  )
}
