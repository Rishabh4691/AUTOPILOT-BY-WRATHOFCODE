/**
 * Project Deck. Designed & built by Aakash Mehra (aakashmehra.com).
 *
 * A scroll-dealt deck of cards. As you scroll, the next card rises from below leaning toward you in
 * 3D and out of focus, and flattens and sharpens as it lands; the cards beneath lean back, sink and
 * dim. The bottom-right corner of each card is cut away to hold its button. Still under
 * prefers-reduced-motion.
 *
 * Adapted for AUTOPILOT: JavaScript, an in-app `onOpen` action instead of an external link, and an
 * `ink` colour so the cut-out button reads on a dark ground.
 */
import { useRef } from 'react'
import { MotionConfig, motion, useReducedMotion, useScroll, useSpring, useTransform } from 'motion/react'
import { ArrowUpRight } from 'lucide-react'
import { cn } from '@/lib/utils'

const host = (url) => (url || '').replace(/^https?:\/\//, '').replace(/\/$/, '')
const clamp01 = (v) => Math.min(1, Math.max(0, v))
const easeOut = (t) => 1 - (1 - t) ** 3
const ENTER = 0.72

function arrived(j, v, count) {
  if (j <= 0) return 1
  const span = Math.max(1, count - 1)
  return easeOut(clamp01((v * span - (j - 1)) / ENTER))
}

/**
 * projects: [{ name, summary, image, accent, url?, display?, onOpen? }]
 * ground: the page colour, used for the cut-out corner; ink / muted: its text colours.
 */
export function ProjectDeck({ projects = [], ground = '#E7E8EA', ink = '#111318', muted = '#3B3F48', className, children }) {
  const deck = useRef(null)
  const reduce = useReducedMotion() ?? false
  const count = projects.length
  const { scrollYProgress } = useScroll({ target: deck, offset: ['start start', 'end end'] })
  const progress = useSpring(scrollYProgress, { stiffness: 380, damping: 48, mass: 0.35 })

  return (
    <MotionConfig reducedMotion="user">
      <section ref={deck} className={cn('relative w-full', className)} style={{ height: `${Math.max(1, count) * 100}svh` }} aria-label="Overview">
        <div className="sticky top-0 grid h-[100svh] items-start justify-items-center overflow-hidden pt-[3svh] px-2 [perspective:1800px] sm:px-6">
          {projects.map((p, i) => (
            <Card key={p.name} p={p} i={i} count={count} progress={progress} still={reduce} ground={ground} ink={ink} muted={muted} />
          ))}
        </div>
      </section>
      {children}
    </MotionConfig>
  )
}

function Card({ p, i, count, progress, still, ground, ink, muted }) {
  const above = (v) => {
    let n = 0
    for (let j = i + 1; j < count; j++) n += arrived(j, v, count)
    return Math.min(3, n)
  }
  const y = useTransform(progress, (v) => `${(1 - arrived(i, v, count)) * 108 - above(v) * 5}svh`)
  const rotateX = useTransform(progress, (v) => -(1 - arrived(i, v, count)) * 30 + above(v) * 5)
  const scale = useTransform(progress, (v) => 0.9 + 0.1 * arrived(i, v, count) - above(v) * 0.05)
  const filter = useTransform(progress, (v) => `blur(${((1 - arrived(i, v, count)) ** 2 * 12 + above(v) * 1.1).toFixed(2)}px)`)
  const dim = useTransform(progress, (v) => above(v) * 0.15)
  const stillY = useTransform(progress, (v) => (arrived(i, v, count) >= 0.5 ? '0svh' : '110svh'))

  return (
    <motion.article
      aria-label={`${p.name}: ${p.summary}`}
      className="col-start-1 row-start-1 w-[min(100%,calc(62svh*16/9),1180px)] origin-[50%_25%] will-change-[transform,filter] max-sm:w-full"
      style={{ zIndex: i + 1, ...(still ? { y: stillY } : { y, rotateX, scale, filter }) }}
    >
      <div className="relative overflow-hidden rounded-[24px] border border-line shadow-[0_50px_90px_-35px_rgba(10,12,20,0.5)]" style={{ background: ground }}>
        <img
          src={p.image}
          alt={`${p.name} screen`}
          loading={i < 2 ? 'eager' : 'lazy'}
          decoding="async"
          className="block aspect-[16/9] w-full object-cover object-top max-sm:aspect-[4/5]"
        />
        <Visit p={p} ground={ground} ink={ink} muted={muted} />
        <motion.div aria-hidden className="pointer-events-none absolute inset-0 bg-[#0A0C14]" style={{ opacity: still ? 0 : dim }} />
      </div>
    </motion.article>
  )
}

function Visit({ p, ground, ink, muted }) {
  const R = 18
  const corner = (
    <svg aria-hidden width={R} height={R} viewBox={`0 0 ${R} ${R}`} className="block">
      <path d={`M${R} 0 V${R} H0 A${R} ${R} 0 0 0 ${R} 0 Z`} fill={ground} />
    </svg>
  )
  const inner = (
    <>
      <span className="flex flex-col text-left leading-tight">
        <span className="text-[16px] font-semibold tracking-[-0.015em] sm:text-[19px]" style={{ color: ink }}>{p.name}</span>
        <span className="text-[13px] underline-offset-4 group-hover:underline group-focus-visible:underline sm:text-[15px]" style={{ color: muted }}>
          {p.display ?? host(p.url)}
        </span>
      </span>
      <span
        className="grid size-11 place-items-center rounded-full text-white transition-transform duration-200 ease-out group-hover:rotate-45 group-active:scale-90 group-focus-visible:outline-2 group-focus-visible:outline-offset-2 sm:size-[52px]"
        style={{ background: p.accent, outlineColor: p.accent }}
      >
        <ArrowUpRight className="size-5 sm:size-6" strokeWidth={2.2} />
      </span>
    </>
  )
  const cls = 'group flex items-center gap-4 rounded-tl-[20px] py-3 pr-1 pl-5 outline-none sm:gap-5 sm:py-4 sm:pl-7'
  return (
    <div className="absolute right-0 bottom-0 z-10">
      <div className="absolute right-0 bottom-full">{corner}</div>
      <div className="absolute right-full bottom-0">{corner}</div>
      {p.onOpen ? (
        <button type="button" onClick={p.onOpen} aria-label={`Open ${p.name}`} className={cls} style={{ background: ground }}>
          {inner}
        </button>
      ) : (
        <a href={p.url} target="_blank" rel="noopener noreferrer" aria-label={`Visit ${p.name} (opens in a new tab)`} className={cls} style={{ background: ground }}>
          {inner}
        </a>
      )}
    </div>
  )
}
