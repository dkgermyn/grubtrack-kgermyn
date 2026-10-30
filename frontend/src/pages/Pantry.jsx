import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Search } from 'lucide-react'
import { get, post, patch } from '../lib/api'
import { cap, plural, qtyText } from '../lib/format'
import { useSheet } from '../components/Sheet'
import { useToast } from '../components/Toasts'
import { DateStamp, Empty, ErrorBox, Loading, Money } from '../components/bits'

const STORAGE_ORDER = ['fridge', 'freezer', 'pantry', 'cupboard', 'counter', 'other']
const STATE_RANK = { expired: 0, today: 1, soon: 2, week: 3, ok: 4, none: 5 }

function byFreshness(a, b) {
  const da = a.daysLeft ?? 99999
  const db = b.daysLeft ?? 99999
  return da - db || (a.name || '').localeCompare(b.name || '')
}

export function usePantryActions() {
  const qc = useQueryClient()
  const toast = useToast()
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['pantry'] })
    qc.invalidateQueries({ queryKey: ['prices'] })
    qc.invalidateQueries({ queryKey: ['spend'] })
  }
  const consume = async (item, fate) => {
    await post(`/items/${item.id}/consume`, { fate })
    refresh()
    toast(`${item.name}: ${fate === 'eaten' ? 'marked eaten' : 'marked tossed'}`, {
      label: 'Undo',
      run: async () => { await post(`/items/${item.id}/restore`); refresh() },
    })
  }
  const keep = async (item, days = 7) => {
    const d = new Date()
    d.setDate(d.getDate() + days)
    const iso = d.toISOString().slice(0, 10)
    const prev = item.expirationDate
    await patch(`/items/${item.id}`, { expirationDate: iso })
    refresh()
    toast(`${item.name}: good for ${days} more days`, {
      label: 'Undo',
      run: async () => { await patch(`/items/${item.id}`, { expirationDate: prev || '' }); refresh() },
    })
  }
  const consumeAll = async (list, fate, label) => {
    if (!window.confirm(`Mark all ${list.length} ${label} as ${fate}?`)) return
    await post('/items/batch', { ids: list.map((i) => i.id), fate })
    refresh()
    toast(`${list.length} marked ${fate}`, {
      label: 'Undo',
      run: async () => { for (const i of list) await post(`/items/${i.id}/restore`); refresh() },
    })
  }
  return { consume, consumeAll, keep, refresh }
}

function ItemRow({ item, triage, onOpen, actions }) {
  const meta = [item.brand, qtyText(item.quantity, item.unit) || item.size,
    cap(item.location && item.location !== item.storage ? item.location : item.storage)].filter(Boolean)
  return (
    <div className="row-wrap">
      <button type="button" onClick={onOpen} className="row">
        <span style={{ minWidth: 0 }}>
          <span className="row__title">{item.name}</span>
          <span className="row__meta" style={{ display: 'block' }}>{meta.join(', ')}</span>
        </span>
        <span className="row__aside">
          {item.lastPaid && <Money value={item.lastPaid.price} size="xs" title={`Last paid at ${item.lastPaid.store || 'unknown store'}`} />}
          <DateStamp date={item.expirationDate} daysLeft={item.daysLeft} state={item.state}
            estimated={item.expirationSource === 'estimated'} />
        </span>
      </button>
      {triage && (
        <div className="btn-row" style={{ padding: '0 14px 12px' }}>
          <button className="btn btn--sm" onClick={() => actions.consume(item, 'eaten')}>Ate it</button>
          <button className="btn btn--sm" onClick={() => actions.consume(item, 'tossed')}>Tossed</button>
          <button className="btn btn--sm btn--ghost" onClick={() => actions.keep(item, 7)}>Still good, +7 days</button>
        </div>
      )}
    </div>
  )
}

export default function Pantry() {
  const { open } = useSheet()
  const actions = usePantryActions()
  const { data, error, isLoading } = useQuery({ queryKey: ['pantry'], queryFn: () => get('/pantry') })
  const [q, setQ] = useState('')
  const [storage, setStorage] = useState('all')
  const [dept, setDept] = useState('all')
  const [view, setView] = useState('stock') // stock | past

  const taxonomy = data?.taxonomy?.departments || []
  const deptLabel = Object.fromEntries(taxonomy.map((d) => [d.key, d.label]))
  const deptOrder = Object.fromEntries(taxonomy.map((d, i) => [d.key, i]))
  const catOrder = Object.fromEntries(taxonomy.flatMap((d) => d.cats.map((c, i) => [c.key, i])))

  const items = data?.items || []
  const past = items.filter((i) => i.state === 'expired')
  const useFirst = items.filter((i) => ['today', 'soon'].includes(i.state)).sort(byFreshness)

  const filtered = useMemo(() => {
    const qn = q.trim().toLowerCase()
    return items.filter((i) => {
      if (view === 'past' ? i.state !== 'expired' : i.state === 'expired') return false
      if (storage !== 'all' && (i.storage || 'other') !== storage) return false
      if (dept !== 'all' && i.dept !== dept) return false
      if (qn && !`${i.name} ${i.brand || ''} ${i.catLabel} ${i.notes || ''} ${i.location || ''}`.toLowerCase().includes(qn)) return false
      return true
    })
  }, [items, q, storage, dept, view])

  const groups = useMemo(() => {
    const g = {}
    for (const i of filtered) {
      const d = i.dept || 'other'
      g[d] ||= {}
      ;(g[d][i.cat || 'other.other'] ||= []).push(i)
    }
    return Object.entries(g)
      .sort(([a], [b]) => (deptOrder[a] ?? 99) - (deptOrder[b] ?? 99))
      .map(([d, cats]) => ({
        dept: d,
        n: Object.values(cats).reduce((s, x) => s + x.length, 0),
        cats: Object.entries(cats)
          .sort(([a], [b]) => (catOrder[a] ?? 99) - (catOrder[b] ?? 99))
          .map(([c, xs]) => ({ cat: c, label: xs[0].catLabel, items: xs.sort(byFreshness) })),
      }))
  }, [filtered, data])

  if (isLoading) return <Loading label="Opening the pantry" />
  if (error) return <ErrorBox error={error} />

  const st = {}
  for (const i of items) if (view === 'past' ? i.state === 'expired' : i.state !== 'expired') st[i.storage || 'other'] = (st[i.storage || 'other'] || 0) + 1
  const deptCounts = {}
  for (const i of items) if (view === 'past' ? i.state === 'expired' : i.state !== 'expired') deptCounts[i.dept || 'other'] = (deptCounts[i.dept || 'other'] || 0) + 1
  const ov = data.overview

  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">Pantry</h1>
        <button className="btn btn--ink" onClick={() => open('add')}><Plus aria-hidden="true" />Add item</button>
      </div>
      <p className="lede">
        <b>{plural(items.length, 'thing')}</b> in the house{past.length > 0 && <>, <b>{past.length}</b> of them past their date</>}.{' '}
        {useFirst.length > 0 && <>Use <b>{useFirst.length}</b> in the next three days.</>}
        {ov.stock.priced > 0 && <> The {ov.stock.priced} with a known price come to <b>${Math.round(ov.stock.value).toLocaleString()}</b>.</>}
      </p>

      {view === 'stock' && useFirst.length > 0 && (
        <section className="section" aria-labelledby="usefirst">
          <div className="section-head">
            <h2 className="section-title" id="usefirst">Use first</h2>
            <span className="section-sub">dated today through the next three days</span>
          </div>
          <div className="chips--scroll" style={{ display: 'flex', gap: 10 }}>
            {useFirst.map((i) => (
              <button key={i.id} type="button" className="tag" onClick={() => open('item', i.id)}
                style={{ minWidth: 190, maxWidth: 230, flex: 'none', textAlign: 'left', cursor: 'pointer', font: 'inherit', color: 'inherit', alignItems: 'start', gridTemplateColumns: '1fr' }}>
                <div className="tag__desc">
                  <div className="tag__name">{i.name}</div>
                  <div className="tag__meta">{cap(i.storage)}</div>
                </div>
                <DateStamp date={i.expirationDate} daysLeft={i.daysLeft} state={i.state}
                  estimated={i.expirationSource === 'estimated'} />
              </button>
            ))}
          </div>
        </section>
      )}

      <section className="section">
        <div className="toolbar">
          <label className="search">
            <Search aria-hidden="true" />
            <span className="sr-only">Search the pantry</span>
            <input className="input" type="search" placeholder="Search the pantry" value={q} onChange={(e) => setQ(e.target.value)} />
          </label>
          <div className="seg" role="group" aria-label="Which items">
            <button aria-pressed={view === 'stock'} onClick={() => setView('stock')}>In date</button>
            <button aria-pressed={view === 'past'} onClick={() => { setView('past'); setDept('all') }}>Past date{past.length ? ` (${past.length})` : ''}</button>
          </div>
        </div>
        <div className="chips chips--scroll" role="group" aria-label="Storage" style={{ marginBottom: 8 }}>
          <button className="chip" aria-pressed={storage === 'all'} onClick={() => setStorage('all')}>Everywhere</button>
          {STORAGE_ORDER.filter((s) => st[s]).map((s) => (
            <button key={s} className="chip" aria-pressed={storage === s} onClick={() => setStorage(s)}>{cap(s)} <span className="n">{st[s]}</span></button>
          ))}
        </div>
        <div className="chips chips--scroll" role="group" aria-label="Department">
          <button className="chip" aria-pressed={dept === 'all'} onClick={() => setDept('all')}>All departments</button>
          {taxonomy.filter((d) => deptCounts[d.key]).map((d) => (
            <button key={d.key} className="chip" aria-pressed={dept === d.key} onClick={() => setDept(d.key)}>{d.label} <span className="n">{deptCounts[d.key]}</span></button>
          ))}
        </div>
        {view === 'past' && past.length > 0 && (
          <p className="note" style={{ marginTop: 14 }}>
            Past their date and still on record. Nothing leaves unless you mark it, and marking keeps the record:{' '}
            <b>Ate it</b> and <b>Tossed</b> feed the restock ideas and the waste numbers.
          </p>
        )}
      </section>

      {groups.length === 0 ? (
        <Empty title={view === 'past' ? 'Nothing past its date' : 'Nothing matches'}>
          {view === 'past' ? 'Every dated item is still good.' : 'Try another storage spot or clear the search.'}
        </Empty>
      ) : groups.map((g) => (
        <section key={g.dept} aria-label={deptLabel[g.dept]}>
          <div className="group-head">
            <h3>{deptLabel[g.dept] || 'Other'}</h3>
            {view === 'past' ? (
              <span className="hstack" style={{ gap: 6 }}>
                <span>{g.n}</span>
                {['eaten', 'tossed'].map((fate) => (
                  <button key={fate} className="btn btn--sm btn--ghost" onClick={() => actions.consumeAll(g.cats.flatMap((c) => c.items), fate, `past-date ${(deptLabel[g.dept] || 'other').toLowerCase()}`)}>
                    All {fate}
                  </button>
                ))}
              </span>
            ) : <span>{g.n}</span>}
          </div>
          <div className="list list--panel">
            {g.cats.map((c) => (
              <div key={c.cat}>
                <div className="subgroup">{c.label}</div>
                {c.items.map((i) => (
                  <ItemRow key={i.id} item={i} triage={view === 'past'} actions={actions} onOpen={() => open('item', i.id)} />
                ))}
              </div>
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}
