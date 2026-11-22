import { useEffect, useState } from 'react'
import { ArrowLeft } from 'lucide-react'
import { clock, get, money } from './api'
import PageBackdrop from './PageBackdrop'
import { useLang } from './prefs'

const COPY = {
  en: {
    home: 'Home',
    live: 'Live',
    updated: 'updated',
    eyebrow: 'START Hack Munich 2026 · 5U AI challenge',
    title: 'Our results',
    sub: 'What AUTOPILOT achieved on its own, live from the 5U board.',
    finished: 'Our rank', of: 'of', teams: 'teams', points: 'points', sold: 'We sold', in: 'in', bookings: 'confirmed bookings',
    tiles: ['Requests answered', 'Accepted quotes', 'Median answer', 'AI spend in total'],
    all: 'All teams',
    you: 'You',
    accepted: 'accepted',
    booked: 'booked',
    pts: 'pts',
    loading: 'Loading the live board…',
    down: 'Board unavailable',
  },
  de: {
    home: 'Start',
    live: 'Live',
    updated: 'aktualisiert',
    eyebrow: 'START Hack München 2026 · 5U AI Challenge',
    title: 'Unsere Ergebnisse',
    sub: 'Was AUTOPILOT allein erreicht hat, live vom 5U-Board.',
    finished: 'Unser Platz', of: 'von', teams: 'Teams', points: 'Punkte', sold: 'Verkauft', in: 'in', bookings: 'bestätigten Buchungen',
    tiles: ['Anfragen beantwortet', 'Angenommene Angebote', 'Median-Antwort', 'KI-Kosten gesamt'],
    all: 'Alle Teams',
    you: 'Wir',
    accepted: 'angenommen',
    booked: 'gebucht',
    pts: 'Pkt.',
    loading: 'Lade die Live-Rangliste…',
    down: 'Rangliste nicht erreichbar',
  },
}

const fmt = (n, d = 0) => (n == null ? '—' : Number(n).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d }))

/** The standalone leaderboard, opened from the home page. Refreshes every 10 s. */
export default function Leaderboard({ onHome }) {
  const [lang] = useLang()
  const c = COPY[lang] ?? COPY.en
  const [d, setD] = useState(null)
  const [err, setErr] = useState(null)
  const [sum, setSum] = useState(null)

  useEffect(() => {
    let alive = true
    const load = () =>
      Promise.all([get('/board'), get('/summary').catch(() => null)])
        .then(([x, s]) => alive && (setD(x), setSum(s), setErr(null)))
        .catch((e) => alive && setErr(e.message))
    load()
    const t = setInterval(load, 10000)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [])

  const ranking = d?.ranking ?? []
  const rounds = d?.rounds ?? []
  const top = ranking[0]?.total ?? 0
  const low = ranking.length ? Math.min(...ranking.map((r) => r.total)) : 0
  // Bars run from the lowest score to the leader, so close scores still look different.
  const bar = (v) => (top > low ? 8 + 92 * ((v - low) / (top - low)) : 100)
  const answered = rounds.filter((r) => r.seconds != null).map((r) => r.seconds).sort((a, b) => a - b)
  const median = answered.length ? answered[Math.floor(answered.length / 2)] : null
  const accepted = rounds.filter((r) => r.verdict === 'accepted').length
  const isUs = (t) => t.name === d?.team


  return (
    <main className="relative isolate min-h-screen overflow-hidden px-4 pt-5 pb-24 sm:px-6">
      <PageBackdrop />

      <div className="mx-auto max-w-5xl">
        <div className="flex items-center justify-between gap-3">
          <button
            type="button"
            onClick={onHome}
            className="glass inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-full px-5 text-sm font-semibold text-white transition-transform duration-200 hover:-translate-x-0.5"
          >
            <ArrowLeft className="size-4" aria-hidden /> {c.home}
          </button>
          <span className="glass inline-flex min-h-9 items-center gap-2 rounded-full px-4 text-[12px] text-zinc-300">
            <i className={`size-2 rounded-full ${err ? 'bg-rose-400' : 'blip bg-emerald-400'}`} aria-hidden />
            {err ? c.down : `${c.live}${d?.fetched_at ? ` · ${c.updated} ${clock(new Date(d.fetched_at).getTime() / 1000)}` : ''}`}
          </span>
        </div>

        <header className="mt-14 text-center sm:mt-20">
          <span className="glass inline-flex h-[30px] items-center gap-2 rounded-full px-3 text-[13px] text-zinc-300">
            <i className="size-1.5 rounded-full bg-accent shadow-[0_0_10px_var(--color-accent)]" aria-hidden />
            {c.eyebrow}
          </span>
          <h1 className="lb-glow font-display mt-6 text-[clamp(3rem,11vw,7.5rem)] leading-[0.9]">{c.title}</h1>
          <p className="mt-4 font-serif text-xl text-zinc-300 italic">{c.sub}</p>
        </header>

        {!d ? (
          <p className="glass mx-auto mt-14 max-w-md rounded-3xl p-8 text-center text-zinc-300">{err ? `${c.down}: ${err}` : c.loading}</p>
        ) : (
          <>
            <section className="glass lb-rise lb-us mt-12 grid gap-8 rounded-[32px] p-7 sm:p-10 lg:grid-cols-2">
              <div className="text-center lg:text-left">
                <p className="text-[11px] tracking-[0.16em] text-muted uppercase">{c.finished}</p>
                <p className="mt-2 flex items-baseline justify-center gap-3 lg:justify-start">
                  <span className="lb-gold font-display text-[clamp(4.5rem,12vw,8rem)] leading-none">#{d.rank}</span>
                  <span className="text-xl text-zinc-300">{c.of} {ranking.length} {c.teams}</span>
                </p>
                <p className="mt-3 font-mono text-zinc-300">{fmt(d.total, 2)} {c.points}</p>
              </div>
              <div className="text-center lg:border-l lg:border-[color-mix(in_oklch,var(--color-foreground)_12%,transparent)] lg:pl-10 lg:text-left">
                <p className="text-[11px] tracking-[0.16em] text-muted uppercase">{c.sold}</p>
                <p className="font-display mt-2 text-[clamp(2.4rem,6vw,4rem)] leading-none text-white">
                  {sum?.booked?.length ? sum.booked.map((b) => (b.currency === 'EUR' ? `€${Math.round(b.total).toLocaleString('en-US')}` : money(b.total, b.currency))).join(' + ') : '—'}
                </p>
                <p className="mt-3 text-zinc-300">
                  {c.in} <span className="font-semibold text-white">{sum?.booked_count ?? (d.bookings ?? []).length}</span> {c.bookings}
                </p>
              </div>
            </section>

            <dl className="mt-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
              {[
                `${rounds.filter((r) => r.seconds != null).length}/${rounds.length}`,
                `${accepted} · ${rounds.length ? Math.round((accepted / rounds.length) * 100) : 0} %`,
                median == null ? '—' : `${Math.round(median)} s`,
                sum?.llm_total_eur != null ? `€${sum.llm_total_eur.toFixed(2)}` : '—',
              ].map((v, i) => (
                <div key={c.tiles[i]} className="glass lb-rise rounded-[24px] px-5 py-5 text-center" style={{ animationDelay: `${(i + 1) * 80}ms` }}>
                  <dt className="text-[11px] tracking-[0.12em] text-muted uppercase">{c.tiles[i]}</dt>
                  <dd className="font-display mt-2 text-[clamp(1.3rem,2.6vw,1.9rem)] text-white">{v}</dd>
                </div>
              ))}
            </dl>

            <section className="mt-14" aria-label={c.all}>
              <h2 className="mb-5 text-center text-[11px] tracking-[0.18em] text-muted uppercase">{c.all}</h2>
              <ol className="space-y-2.5">
                {ranking.map((t, i) => (
                  <li
                    key={t.name}
                    className={`glass lb-rise relative flex items-center gap-4 overflow-hidden rounded-2xl px-4 py-3 sm:px-5 ${isUs(t) ? 'lb-us' : ''}`}
                    style={{ animationDelay: `${Math.min(i, 14) * 40}ms` }}
                  >
                    <span
                      aria-hidden="true"
                      className={`absolute inset-y-0 left-0 -z-10 ${isUs(t) ? 'bg-accent/25' : 'bg-white/[0.06]'}`}
                      style={{ width: `${bar(t.total)}%` }}
                    />
                    <span className={`font-display w-8 shrink-0 text-center text-xl ${t.rank <= 3 ? 'text-accent' : 'text-zinc-400'}`}>{t.rank}</span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className="truncate font-semibold text-white">{t.team}</span>
                        {isUs(t) && <span className="shrink-0 rounded-full bg-accent px-2 py-0.5 text-[10px] font-bold uppercase text-[#0d0d0d]">{c.you}</span>}
                      </span>
                      <span className="block text-[12px] text-muted">
                        {t.accepted}/{t.answered} {c.accepted} · {t.bookings} {c.booked}
                      </span>
                    </span>
                    <span className="shrink-0 text-right font-mono text-sm text-white tabular-nums sm:text-base">{fmt(t.total, 2)}</span>
                  </li>
                ))}
              </ol>
            </section>
          </>
        )}
      </div>
    </main>
  )
}
