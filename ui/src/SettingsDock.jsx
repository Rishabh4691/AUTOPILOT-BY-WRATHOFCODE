import { useEffect, useRef, useState } from 'react'
import { Cpu, Languages, MailCheck, MailX, Moon, Settings2, Sun, X } from 'lucide-react'
import { GradientMenu } from './components/ui/gradient-menu'
import { get, post } from './api'
import { useLang, useT, useTheme } from './prefs'

const MODELS = { 'gpt-4.1-mini': '4.1 mini', 'gpt-4.1': '4.1' }

/**
 * The floating settings button, bottom right on every screen: theme, language, and the bot's
 * writer model and daily updates (those two change the live bot, as the old switches did).
 */
export default function SettingsDock() {
  const t = useT()
  const [theme, setTheme] = useTheme()
  const [lang, setLang] = useLang()
  const [open, setOpen] = useState(false)
  const [bot, setBot] = useState(null)
  const [err, setErr] = useState(false)
  const box = useRef(null)

  // Load the bot settings on start and again each time the menu opens, so a slow or
  // restarting API never leaves the model and daily mail buttons out.
  useEffect(() => {
    get('/settings')
      .then((s) => (setBot(s), setErr(false)))
      .catch(() => setErr(true))
  }, [open])

  useEffect(() => {
    if (!open) return
    const away = (e) => !box.current?.contains(e.target) && setOpen(false)
    const esc = (e) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('pointerdown', away)
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('pointerdown', away)
      document.removeEventListener('keydown', esc)
    }
  }, [open])

  const change = async (patch) => {
    try {
      setBot(await post('/settings', patch))
      setErr(false)
    } catch {
      setErr(true)
    }
  }

  const model = bot?.writer_model || 'gpt-4.1-mini'
  const daily = !!bot?.daily_updates
  const dark = theme === 'dark'
  const away = bot && !bot.bot_here
  const awayNote = lang === 'de' ? 'Kein Bot auf diesem Rechner: Modell und Updates wirken nur auf den Bot, der hier läuft.' : 'No bot runs on this machine: model and daily mail only steer the bot that runs here.'

  const items = [
    {
      title: dark ? t('dark') : t('light'),
      value: lang === 'de' ? 'Design wechseln' : 'Switch theme',
      badge: dark ? 'D' : 'L',
      icon: dark ? <Moon /> : <Sun />,
      gradientFrom: '#a955ff',
      gradientTo: '#ea51ff',
      onClick: () => setTheme(dark ? 'light' : 'dark'),
    },
    {
      title: lang === 'de' ? 'Sprache' : 'Language',
      value: lang === 'de' ? 'Deutsch' : 'English',
      badge: lang.toUpperCase(),
      icon: <Languages />,
      gradientFrom: '#56ccf2',
      gradientTo: '#2f80ed',
      onClick: () => setLang(lang === 'de' ? 'en' : 'de'),
    },
  ]
  if (bot) {
    items.push(
      {
        title: lang === 'de' ? 'Modell' : 'Model',
        value: MODELS[model] ?? model,
        badge: model === 'gpt-4.1' ? '4.1' : 'mini',
        hint: away ? awayNote : t('modelNote'),
        icon: <Cpu />,
        gradientFrom: '#ff9966',
        gradientTo: '#ff5e62',
        onClick: () => change({ writer_model: model === 'gpt-4.1' ? 'gpt-4.1-mini' : 'gpt-4.1' }),
      },
      {
        title: lang === 'de' ? 'Updates' : 'Daily mail',
        value: daily ? t('on') : t('off'),
        badge: daily ? t('on') : t('off'),
        hint: away ? awayNote : t('updatesNote'),
        icon: daily ? <MailCheck /> : <MailX />,
        gradientFrom: '#80ff72',
        gradientTo: '#7ee8fa',
        onClick: () => change({ daily_updates: !daily }),
      },
    )
  }

  return (
    <div ref={box} className="fixed right-4 bottom-4 z-50 flex flex-col items-end gap-2 sm:right-6 sm:bottom-6">
      {away && open && <span className="glass max-w-xs rounded-2xl px-3 py-2 text-[11px] leading-snug text-zinc-300">{awayNote}</span>}
      {err && open && <span className="glass rounded-full px-3 py-1 text-[11px] text-rose-300">{lang === 'de' ? 'Bot-Einstellungen nicht erreichbar' : 'Bot settings unavailable'}</span>}
      <div className="flex items-center gap-3 sm:gap-6">
      {open && (
        <div id="settings-dock">
          <GradientMenu items={items} />
        </div>
      )}
      <button
        type="button"
        aria-expanded={open}
        aria-controls="settings-dock"
        aria-label={lang === 'de' ? 'Einstellungen' : 'Settings'}
        onClick={() => setOpen((o) => !o)}
        className="glass flex size-[60px] shrink-0 cursor-pointer items-center justify-center rounded-full text-accent transition-transform duration-200 hover:scale-105 active:scale-95"
      >
        {open ? <X className="size-6" aria-hidden /> : <Settings2 className="size-6" aria-hidden />}
      </button>
      </div>
    </div>
  )
}
