// Widget « limites » pour Hermes Desktop : un item de barre d'état et un panneau
// qui lisent l'abonnement Claude, l'abonnement Codex, OpenCode Go et la dépense
// OpenRouter du jour.
//
// ESM chargé sans compilation par la porte « disk plugin » : seuls
// '@hermes/plugin-sdk', 'react' et 'react/jsx-runtime' se résolvent, le JSX est
// une SyntaxError, donc l'arbre s'écrit avec jsx()/jsxs(). Aucun chiffre n'est
// calculé ici : tout vient du backend (plugins/limites/dashboard/plugin_api.py)
// via ctx.rest('/data').
import { host, PANES_AREA, STATUSBAR_AREAS, Tip, useQuery, useValue } from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'

const PLUGIN_ID = 'limites'
const PANE_ID = 'limits'
const POLL_MS = 60_000
const STYLE_ID = 'limites-desktop-style'
const PANE_WIDTH = '300px'

let rest = null

const ORDER = ['claude', 'codex', 'opencode', 'openrouter']

function fetchData() {
  if (!rest) return Promise.reject(new Error('plugin limites non enregistré'))
  return rest('/data')
}

function useLimits() {
  const gateway = useValue(host.state.gateway)
  const query = useQuery({
    queryKey: [PLUGIN_ID, 'data'],
    queryFn: fetchData,
    refetchInterval: POLL_MS,
    enabled: gateway === 'open',
    placeholderData: previous => previous
  })
  return { gateway, data: query.data, error: query.error }
}

// ---------------------------------------------------------------------------
// mise en forme
// ---------------------------------------------------------------------------

function pct(value) {
  return Number.isFinite(value) ? `${Math.round(value)}%` : '—'
}

function tone(percent) {
  if (!Number.isFinite(percent)) return 'muted'
  if (percent >= 95) return 'danger'
  if (percent >= 75) return 'warn'
  return 'ok'
}

function hoursLeft(resetsAt) {
  if (!resetsAt) return ''
  const at = Date.parse(resetsAt)
  if (!Number.isFinite(at)) return ''
  const minutes = Math.max(0, Math.round((at - Date.now()) / 60_000))
  if (minutes < 60) return `${minutes} min`
  if (minutes < 48 * 60) return `${Math.round(minutes / 60)} h`
  return `${Math.round(minutes / 1440)} j`
}

function money(value) {
  return Number.isFinite(value) ? `$${value.toFixed(2)}` : '—'
}

function topWindow(source) {
  const windows = (source && source.windows) || []
  if (!windows.length) return null
  return windows.reduce((worst, w) => (Number(w.percent) > Number(worst.percent) ? w : worst), windows[0])
}

function statusSegments(data) {
  const sources = (data && data.sources) || {}
  const segments = []
  const claude = sources.claude
  if (claude && claude.ok) {
    const worst = topWindow(claude)
    segments.push({ key: 'claude', text: `C ${pct(worst.percent)}`, tone: tone(worst.percent) })
  }
  const codex = sources.codex
  if (codex && codex.ok) {
    const worst = topWindow(codex)
    segments.push({ key: 'codex', text: `X ${pct(worst.percent)}`, tone: tone(worst.percent) })
  }
  const go = sources.opencode
  if (go && go.ok) {
    const worst = topWindow(go)
    segments.push({ key: 'go', text: `Go ${pct(worst.percent)}`, tone: tone(worst.percent) })
  }
  const or = sources.openrouter
  if (or && or.ok) {
    const spent = Number.isFinite(or.window_spend) ? or.window_spend : 0
    const limit = Number.isFinite(or.limit) ? `/${Math.round(or.limit)}` : ''
    segments.push({
      key: 'openrouter',
      text: `OR ${money(spent)}${limit}`,
      tone: Number.isFinite(or.limit) && or.limit > 0 && spent / or.limit >= 0.9 ? 'danger' : 'muted'
    })
  }
  return segments
}

// ---------------------------------------------------------------------------
// rendu
// ---------------------------------------------------------------------------

const present = child => child !== null && child !== undefined && child !== false && child !== ''
function node(type, props, children, key) {
  const list = (Array.isArray(children) ? children : [children]).filter(present)
  if (list.length === 1) return jsx(type, { ...props, children: list[0] }, key)
  return jsxs(type, { ...props, children: list }, key)
}
const div = (className, children, key) => node('div', { className }, children, key)
const span = (className, children, key) => node('span', { className }, children, key)

function WindowRow({ window: win }) {
  const left = hoursLeft(win.resets_at)
  const width = Number.isFinite(win.percent) ? Math.max(0, Math.min(100, win.percent)) : 0
  return div('lim-window', [
    div('lim-window-head', [
      span('lim-window-label', win.label),
      span(`lim-window-value lim-${tone(win.percent)}`, pct(win.percent))
    ], 'head'),
    div('lim-gauge-track', [
      jsx('div', { className: `lim-gauge-fill lim-bg-${tone(win.percent)}`, style: { width: `${width}%` } }, 'fill')
    ], 'track'),
    left ? div('lim-window-reset', `reset dans ${left}`) : null
  ])
}

function SourceBlock({ id, source }) {
  if (!source) return null
  if (!source.ok) {
    return div('lim-source', [
      div('lim-source-head', [
        span('lim-source-name', source.label || id),
        span('lim-badge lim-muted', 'indisponible')
      ]),
      div('lim-error', String(source.error || 'erreur inconnue'))
    ], id)
  }
  const windows = source.windows || []
  const rows = windows.map((win, index) => jsx(WindowRow, { window: win }, `${id}-${index}`))
  return div('lim-source', [
    div('lim-source-head', [
      span('lim-source-name', source.label || id),
      source.plan ? span('lim-badge', String(source.plan)) : null
    ]),
    ...rows
  ], id)
}

function OpenRouterBlock({ source }) {
  if (!source) return null
  if (!source.ok) {
    return div('lim-source', [
      div('lim-source-head', [
        span('lim-source-name', source.label || 'OpenRouter'),
        span('lim-badge lim-muted', 'indisponible')
      ]),
      div('lim-error', String(source.error || 'erreur inconnue'))
    ], 'openrouter')
  }
  const limit = Number.isFinite(source.limit) ? source.limit : null
  const spent = Number.isFinite(source.window_spend) ? source.window_spend : null
  const ratio = limit && spent !== null ? Math.min(100, (spent / limit) * 100) : 0
  const reset = hoursLeft(source.resets_at)
  const byProfile = source.today_by_profile || {}
  const detail = Object.keys(byProfile)
    .filter(name => Number(byProfile[name]) > 0)
    .map(name => `${name} ${money(Number(byProfile[name]))}`)
    .join(' · ')
  return div('lim-source', [
    div('lim-source-head', [
      span('lim-source-name', 'OpenRouter'),
      span('lim-badge', source.reset ? String(source.reset) : 'clé')
    ]),
    div('lim-window', [
      div('lim-window-head', [
        span('lim-window-label', 'Plafond de clé'),
        span(`lim-window-value lim-${tone(ratio)}`, `${money(spent)} / ${money(limit)}`)
      ], 'head'),
      div('lim-gauge-track', [
        jsx('div', { className: `lim-gauge-fill lim-bg-${tone(ratio)}`, style: { width: `${ratio}%` } }, 'fill')
      ], 'track'),
      reset ? div('lim-window-reset', `remise à zéro dans ${reset}`) : null
    ], 'key'),
    div('lim-or-row', [
      span('lim-or-label', 'Dépense du jour'),
      span('lim-or-value', money(source.today_usd))
    ], 'today'),
    detail ? div('lim-or-row lim-or-sub', [
      span('lim-or-label', 'dont'),
      span('lim-or-value', detail)
    ], 'detail') : null,
    div('lim-or-row', [
      span('lim-or-label', 'Reste sur la clé'),
      span('lim-or-value', money(source.remaining))
    ], 'remaining')
  ], 'openrouter-block')
}

function LimitsPane() {
  const { data, error, gateway } = useLimits()
  const sources = (data && data.sources) || {}
  const blocks = []
  for (const id of ORDER) {
    if (id === 'openrouter') {
      if (sources.openrouter) blocks.push(jsx(OpenRouterBlock, { source: sources.openrouter }, 'openrouter'))
    } else if (sources[id]) {
      blocks.push(jsx(SourceBlock, { id, source: sources[id] }, id))
    }
  }
  const stamp = data && data.fetched_at ? new Date(data.fetched_at).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }) : ''
  return div('lim-pane', [
    div('lim-pane-head', [
      span('lim-pane-title', 'Limites & dépenses'),
      span('lim-pane-stamp', stamp)
    ]),
    error ? div('lim-error', `passerelle : ${String(error.message || error)}`) : null,
    !data && gateway !== 'open' ? div('lim-error', 'passerelle déconnectée') : null,
    ...blocks
  ])
}

function StatusItem() {
  const { data } = useLimits()
  const segments = statusSegments(data)
  if (!segments.length) return null
  const reveal = () => {
    if (typeof host.revealPane === 'function') host.revealPane(`${PLUGIN_ID}:${PANE_ID}`)
  }
  return jsx(Tip, {
    label: 'Limites d’abonnement et dépense OpenRouter',
    children: node('button', { type: 'button', className: 'lim-bar', onClick: reveal },
      segments.map(seg => span(`lim-bar-seg lim-${seg.tone}`, seg.text, seg.key)))
  })
}

const PANE_CSS = `
.lim-bar{display:inline-flex;align-items:center;gap:6px;padding:0 4px;background:transparent;border:0;cursor:pointer;font:inherit;color:var(--ui-text-tertiary)}
.lim-bar:hover{color:var(--ui-text-primary)}
.lim-bar-seg{font-variant-numeric:tabular-nums;white-space:nowrap}
.lim-ok{color:var(--ui-text-secondary)}
.lim-warn{color:var(--ui-yellow)}
.lim-danger{color:var(--ui-red)}
.lim-muted{color:var(--ui-text-quaternary)}
.lim-pane{display:flex;flex-direction:column;gap:14px;padding:12px;height:100%;overflow-y:auto;font-size:12px;color:var(--ui-text-secondary)}
.lim-pane-head{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.lim-pane-title{font-weight:600;color:var(--ui-text-primary)}
.lim-pane-stamp{color:var(--ui-text-quaternary);font-variant-numeric:tabular-nums}
.lim-source{display:flex;flex-direction:column;gap:7px}
.lim-source-head{display:flex;justify-content:space-between;align-items:center;gap:8px}
.lim-source-name{color:var(--ui-text-primary);font-weight:600}
.lim-badge{font-size:11px;padding:1px 6px;border-radius:999px;background:var(--ui-bg-tertiary);color:var(--ui-text-tertiary)}
.lim-window{display:flex;flex-direction:column;gap:4px}
.lim-window-head{display:flex;justify-content:space-between;gap:8px;color:var(--ui-text-tertiary)}
.lim-window-value{font-variant-numeric:tabular-nums;color:var(--ui-text-primary)}
.lim-gauge-track{height:5px;border-radius:999px;background:var(--ui-bg-tertiary);overflow:hidden}
.lim-gauge-fill{height:100%;border-radius:999px;background:var(--ui-accent);transition:width .3s ease}
.lim-bg-warn{background:var(--ui-yellow)}
.lim-bg-danger{background:var(--ui-red)}
.lim-bg-ok{background:var(--ui-accent)}
.lim-window-reset{color:var(--ui-text-quaternary);font-size:11px}
.lim-or-row{display:flex;justify-content:space-between;gap:8px;color:var(--ui-text-tertiary)}
.lim-or-value{color:var(--ui-text-primary);font-variant-numeric:tabular-nums}
.lim-or-sub{font-size:11px;color:var(--ui-text-quaternary)}
.lim-error{color:var(--ui-red);font-size:11px;line-height:1.4}
`

function injectStyle() {
  if (typeof document === 'undefined') return () => {}
  const existing = document.getElementById(STYLE_ID)
  if (existing) existing.remove()
  const style = document.createElement('style')
  style.id = STYLE_ID
  style.textContent = PANE_CSS
  document.head.append(style)
  return () => style.remove()
}

export default {
  id: PLUGIN_ID,
  name: 'Limites',
  description: 'Quotas Claude, Codex et OpenCode Go, plafond et dépense OpenRouter du jour.',
  defaultEnabled: true,
  register(ctx) {
    rest = ctx.rest
    const removeStyle = injectStyle()
    ctx.onDispose(() => {
      removeStyle()
      rest = null
    })
    ctx.registerMany([
      {
        id: 'status',
        area: STATUSBAR_AREAS.right,
        order: 200,
        render: () => jsx(StatusItem, {})
      },
      {
        id: PANE_ID,
        area: PANES_AREA,
        title: 'limites',
        data: { placement: 'right', width: PANE_WIDTH },
        render: () => jsx(LimitsPane, {})
      }
    ])
  }
}
