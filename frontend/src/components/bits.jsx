// Small shared pieces: money, the unit-price box, date stamps, deltas, store keys, empties.
import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react'
import { dollars, freshnessText, perLabel, shortDate, splitPrice, unitText, pct } from '../lib/format'
import { useStores } from '../lib/stores'

export function Money({ value, size = 'sm', className = '', title }) {
  if (value === null || value === undefined) return <span className={`price price--${size} muted ${className}`}>–</span>
  // raised cents only where the figure is big enough to read them; small figures stay plain
  if (size === 'xs') return <span className={`num row-price ${className}`} title={title}>{dollars(value)}</span>
  const [whole, cents] = splitPrice(value)
  return (
    <span className={`money price price--${size} ${className}`} title={title || dollars(value)} aria-label={dollars(value)}>
      <span className="cur" aria-hidden="true">$</span>
      <span aria-hidden="true">{whole}</span>
      <sup aria-hidden="true">{cents}</sup>
    </span>
  )
}

export function UnitBox({ value, label, size, none = 'size?' }) {
  if (value === null || value === undefined || !label) {
    return (
      <span className={`unitbox unitbox--none ${size === 'lg' ? 'unitbox--lg' : ''}`} title="Unit price unknown: the package size isn't recorded">
        <b>{none}</b>
        <span>unit price</span>
      </span>
    )
  }
  return (
    <span className={`unitbox ${size === 'lg' ? 'unitbox--lg' : ''}`} aria-label={`${unitText(value)} ${perLabel(label)}`}>
      <b>{unitText(value)}</b>
      <span>{perLabel(label)}</span>
    </span>
  )
}

export function DateStamp({ date, daysLeft, state, estimated = false }) {
  return (
    <span className={`stamp stamp--${state || 'none'}`}>
      <b>{date ? shortDate(date) : 'No date'}</b>
      <span>{date ? `${estimated ? 'est. · ' : ''}${freshnessText(daysLeft)}` : 'add one'}</span>
    </span>
  )
}

export function Delta({ value, digits = 0, upIsBad = true, title }) {
  if (value === null || value === undefined) return null
  const dir = value > 0 ? 'up' : value < 0 ? 'down' : 'flat'
  const Icon = dir === 'up' ? ArrowUpRight : dir === 'down' ? ArrowDownRight : Minus
  const tone = dir === 'flat' ? 'flat' : (dir === 'up') === upIsBad ? 'up' : 'down'
  return (
    <span className={`delta delta--${tone}`} title={title}>
      <Icon aria-hidden="true" />
      {dir === 'flat' ? 'no change' : pct(value, { digits })}
    </span>
  )
}

export function StoreKey({ id, name }) {
  const { color, byId } = useStores()
  const label = name || byId[id]?.name || 'No receipt'
  return (
    <span className="storekey">
      <i style={{ background: id ? color(id) : 'var(--ink-3)' }} aria-hidden="true" />
      {label}
    </span>
  )
}

export function Empty({ title, children, action }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {action}
    </div>
  )
}

export function Loading({ label = 'Loading' }) {
  return <div className="loading" role="status">{label}…</div>
}

export function ErrorBox({ error }) {
  if (!error) return null
  return <div className="error-box" role="alert">{error.message || String(error)}</div>
}

export function Meter({ have, known }) {
  if (!known) return null
  const n = Math.min(known, 10)
  const on = Math.round((have / known) * n)
  return (
    <span className="meter" title={`${have} of ${known} ingredients in the house`}>
      <i aria-hidden="true">{Array.from({ length: n }, (_, i) => <u key={i} className={i < on ? 'on' : ''} />)}</i>
      {have} of {known}
    </span>
  )
}
