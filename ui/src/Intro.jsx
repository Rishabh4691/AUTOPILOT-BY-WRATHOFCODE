import { ArrowDown, Trophy } from 'lucide-react'
import { DotField } from './components/ui/dot-field'
import { useLang, useTheme } from './prefs'

const COPY = {
  en: {
    eyebrow: 'START Hack Munich 2026',
    description: 'An air freight forwarder that runs itself. Every request read, priced, answered and booked, with no human in the loop.',
    tour: 'Let’s have a tour',
    board: 'Leaderboard',
    hint: { scatter: 'Ready for take off? Scroll', gather: 'Scroll up to land' },
  },
  de: {
    eyebrow: 'START Hack München 2026',
    description: 'Ein Luftfracht-Spediteur, der sich selbst steuert. Jede Anfrage gelesen, berechnet, beantwortet und gebucht, ohne Menschen dazwischen.',
    tour: 'Starte die Tour',
    board: 'Rangliste',
    hint: { scatter: 'Bereit zum Abheben? Scrollen', gather: 'Hochscrollen zum Landen' },
  },
}

const pill = 'btn-ink font-sans inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-full px-5 text-[15px] font-bold'

/** The first screen: WRATHOFCODE drawn by the dot grid, then a tour or the leaderboard. */
export default function Intro({ onTour, onLeaderboard }) {
  const [lang] = useLang()
  const [theme] = useTheme()
  const c = COPY[lang] ?? COPY.en
  return (
    <div className="dotfield-scope">
      <DotField
        headline="WRATHOFCODE"
        eyebrow={<span className="font-sans">{c.eyebrow}</span>}
        description={<span className="font-serif text-[18px] text-zinc-300">{c.description}</span>}
        accent={theme === 'dark' ? '#ff8a3d' : '#ff6b2c'}
        fontFamily='"Archivo Black", "Arial Black", Helvetica, sans-serif'
        fontWeight={400}
        scrollHint={c.hint}
        style={{ height: 'calc(100svh + 35vh)' }}
        actions={
          <>
            <button type="button" onClick={onTour} className={`${pill} bg-accent text-[#0d0d0d]`}>
              {c.tour} <ArrowDown className="size-4" aria-hidden />
            </button>
            <button type="button" onClick={onLeaderboard} className={`${pill} bg-panel text-white`}>
              <Trophy className="size-4" aria-hidden /> {c.board}
            </button>
          </>
        }
      />
    </div>
  )
}
