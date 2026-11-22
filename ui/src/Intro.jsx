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


/* The flight path, in a 1000 x 600 box stretched over the screen: low on the left, a gentle climb to the right. */
const PATH = 'M -60 430 C 220 470, 420 300, 600 290 S 900 140, 1080 120'

/**
 * A paper-sketch plane that flies left to right across the intro while the page scrolls and the
 * dots scatter, leaving a dotted trail. Its position follows scroll, so scrolling back flies it home.
 * Hidden at rest and under reduced motion.
 */
function PlaneFlight({ target }) {
  const wrap = useRef(null)
  const plane = useRef(null)
  const route = useRef(null)
  const reveal = useRef(null)

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    let raf = 0
    const draw = () => {
      raf = 0
      const section = target.current?.querySelector('section')
      const path = route.current
      if (!section || !path || !wrap.current) return
      const top = section.getBoundingClientRect().top
      // Same scale the dots use to scatter: fully scattered after 70 % of a screen.
      const p = Math.min(1, Math.max(0, -top / (window.innerHeight * 0.7)))
      const len = path.getTotalLength()
      const at = path.getPointAtLength(p * len)
      const ahead = path.getPointAtLength(Math.min(len, p * len + 4))
      const W = window.innerWidth
      const H = window.innerHeight
      const angle = (Math.atan2((ahead.y - at.y) * (H / 600), (ahead.x - at.x) * (W / 1000)) * 180) / Math.PI
      wrap.current.style.opacity = p > 0.01 && p < 0.995 ? '1' : '0'
      plane.current.style.transform = `translate(${(at.x / 1000) * W}px, ${(at.y / 600) * H}px) translate(-50%, -50%) rotate(${angle}deg)`
      reveal.current.style.strokeDashoffset = String(len * (1 - p))
      reveal.current.style.strokeDasharray = String(len)
    }
    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(draw)
    }
    draw()
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
    }
  }, [target])

  return (
    <div ref={wrap} aria-hidden="true" className="pointer-events-none fixed inset-0 z-30 opacity-0 transition-opacity duration-300">
      <svg viewBox="0 0 1000 600" preserveAspectRatio="none" className="absolute inset-0 h-full w-full overflow-visible">
        <defs>
          <mask id="flight-reveal" maskUnits="userSpaceOnUse" x="-100" y="-100" width="1300" height="800">
            <path ref={reveal} d={PATH} fill="none" stroke="#fff" strokeWidth="40" />
          </mask>
        </defs>
        <path ref={route} d={PATH} fill="none" stroke="none" />
        <path
          d={PATH}
          fill="none"
          mask="url(#flight-reveal)"
          className="stroke-sketch"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeDasharray="1 11"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <div ref={plane} className="absolute top-0 left-0 will-change-transform">
        <svg viewBox="-34 -22 68 44" width="76" height="50" className="overflow-visible drop-shadow-[3px_3px_0_var(--color-sketch)]">
          <g className="stroke-sketch" strokeWidth="2.4" strokeLinejoin="round" strokeLinecap="round">
            <path d="M-8 -3 L-20 -18 L-13 -18 L4 -3 Z" className="fill-panel" />
            <path d="M-26 -2 L-31 -13 L-25 -13 L-17 -3 Z" className="fill-panel" />
            <path d="M-28 -3 C-28 -7 -22 -8 -14 -8 L18 -7 C26 -7 32 -4 32 0 C32 4 26 6 18 6 L-14 7 C-22 7 -28 5 -28 2 Z" className="fill-accent" />
            <path d="M-6 3 L-18 19 L-11 19 L6 3 Z" className="fill-panel" />
            <path fill="none" d="M20 -3 h5 M12 -3 h4 M4 -3 h4 M-4 -3 h4" strokeWidth="2" />
            <path fill="none" d="M-34 -1 l-9 -2 M-35 3 l-11 1" strokeWidth="1.6" />
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
