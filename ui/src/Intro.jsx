import { useEffect, useRef } from 'react'
import { ArrowDown, Trophy } from 'lucide-react'
import { DotField } from './components/ui/dot-field'
import { useLang, useTheme } from './prefs'

const COPY = {
  en: {
    eyebrow: 'START Hack Munich 2026',
    description: 'An air freight forwarder that runs itself. Every request read, priced, answered and booked, with no human in the loop.',
    tour: 'Let’s have a tour',
    board: 'Leaderboard',
    hint: { scatter: 'Scroll to scatter', gather: 'Scroll up to gather' },
  },
  de: {
    eyebrow: 'START Hack München 2026',
    description: 'Ein Luftfracht-Spediteur, der sich selbst steuert. Jede Anfrage gelesen, berechnet, beantwortet und gebucht, ohne Menschen dazwischen.',
    tour: 'Starte die Tour',
    board: 'Rangliste',
    hint: { scatter: 'Scrollen zum Zerstreuen', gather: 'Hochscrollen zum Sammeln' },
  },
}

const pill = 'btn-ink font-sans inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-full px-5 text-[15px] font-bold'


/**
 * A paper-sketch plane that glides straight across the intro, left to right, while the page scrolls
 * and the dots scatter. Scroll sets where it should be; it eases there each frame, so it moves
 * smoothly even with a jumpy mouse wheel. Scrolling back flies it home. Off under reduced motion.
 */
function PlaneFlight({ target }) {
  const plane = useRef(null)

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    let raf = 0
    let shown = 0
    let goal = 0
    const progress = () => {
      const section = target.current?.querySelector('section')
      if (!section) return 0
      // Same scale the dots use to scatter: fully scattered after 70 % of a screen.
      return Math.min(1, Math.max(0, -section.getBoundingClientRect().top / (window.innerHeight * 0.7)))
    }
    const tick = () => {
      shown += (goal - shown) * 0.12
      if (Math.abs(goal - shown) < 0.0005) shown = goal
      const el = plane.current
      if (el) {
        const W = window.innerWidth
        const x = -120 + shown * (W + 240)
        el.style.transform = `translate3d(${x}px, 0, 0)`
        el.style.opacity = shown > 0.005 && shown < 0.995 ? '1' : '0'
      }
      raf = shown === goal ? 0 : requestAnimationFrame(tick)
    }
    const onScroll = () => {
      goal = progress()
      if (!raf) raf = requestAnimationFrame(tick)
    }
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
    }
  }, [target])

  return (
    <div aria-hidden="true" className="pointer-events-none fixed inset-x-0 top-[38vh] z-30 h-0">
      <div ref={plane} className="absolute top-0 left-0 -translate-y-1/2 opacity-0 transition-opacity duration-200 will-change-transform">
        <svg viewBox="-34 -22 68 44" width="84" height="55" className="overflow-visible drop-shadow-[3px_3px_0_var(--color-sketch)]">
          <g className="stroke-sketch" strokeWidth="2.4" strokeLinejoin="round" strokeLinecap="round">
            <path d="M-8 -3 L-20 -18 L-13 -18 L4 -3 Z" className="fill-panel" />
            <path d="M-26 -2 L-31 -13 L-25 -13 L-17 -3 Z" className="fill-panel" />
            <path d="M-28 -3 C-28 -7 -22 -8 -14 -8 L18 -7 C26 -7 32 -4 32 0 C32 4 26 6 18 6 L-14 7 C-22 7 -28 5 -28 2 Z" className="fill-accent" />
            <path d="M-6 3 L-18 19 L-11 19 L6 3 Z" className="fill-panel" />
            <path fill="none" d="M20 -3 h5 M12 -3 h4 M4 -3 h4 M-4 -3 h4" strokeWidth="2" />
          </g>
        </svg>
      </div>
    </div>
  )
}

/** The first screen: WRATHOFCODE drawn by the dot grid, then a tour or the leaderboard. */
export default function Intro({ onTour, onLeaderboard }) {
  const [lang] = useLang()
  const [theme] = useTheme()
  const c = COPY[lang] ?? COPY.en
  const box = useRef(null)
  return (
    <div ref={box} className="dotfield-scope">
      <PlaneFlight target={box} />
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
