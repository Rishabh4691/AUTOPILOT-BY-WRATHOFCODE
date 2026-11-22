import { useEffect, useState } from 'react'
import { get, post } from './api'
import { useLang, useT, useTheme } from './prefs'

function Switch({ options, value, onChange, title }) {
  return (
    <div title={title} className="flex overflow-hidden rounded-md border border-line text-[11px]">
      {options.map(([k, label]) => (
        <button
          key={String(k)}
          onClick={() => onChange(k)}
          className={`px-2 py-1 ${value === k ? 'bg-sky-500/15 text-sky-300' : 'text-muted hover:text-zinc-200'}`}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

export default function Controls() {
  const t = useT()
  const [theme, setTheme] = useTheme()
  const [lang, setLang] = useLang()
  const [bot, setBot] = useState(null)
  const [err, setErr] = useState(false)

  useEffect(() => {
    get('/settings').then(setBot).catch(() => setErr(true))
  }, [])

  const change = async (patch) => {
    try {
      setBot(await post('/settings', patch))
      setErr(false)
    } catch {
      setErr(true)
    }
  }

  const model = bot?.writer_model || 'gpt-4.1-mini'

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Switch options={[['en', 'EN'], ['de', 'DE']]} value={lang} onChange={setLang} />
      <Switch options={[['dark', t('dark')], ['light', t('light')]]} value={theme} onChange={setTheme} />
      {bot && (
        <>
          <Switch
            title={t('modelNote')}
            options={[['gpt-4.1-mini', '4.1 mini'], ['gpt-4.1', '4.1']]}
            value={model}
            onChange={(m) => change({ writer_model: m })}
          />
          <div title={t('updatesNote')} className="flex items-center gap-1.5 text-[11px] text-muted">
            {t('updates')}
            <Switch options={[[false, t('off')], [true, t('on')]]} value={!!bot.daily_updates} onChange={(v) => change({ daily_updates: v })} />
          </div>
        </>
      )}
      {err && <span className="text-[11px] text-rose-300">settings unavailable</span>}
    </div>
  )
}
