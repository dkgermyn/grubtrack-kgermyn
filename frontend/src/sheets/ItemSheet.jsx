import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Pencil } from 'lucide-react'
import { get, img, patch, post } from '../lib/api'
import { ago, cap, dollars, perLabel, qtyText, shortDate, unitText } from '../lib/format'
import Sheet, { useSheet } from '../components/Sheet'
import PriceTag, { lastMeta } from '../components/PriceTag'
import { PriceHistory } from '../components/charts'
import { DateStamp, ErrorBox, Loading, StoreKey } from '../components/bits'
import { useToast } from '../components/Toasts'
import { usePantryActions } from '../pages/Pantry'

const FIELDS = [
  ['name', 'Name'], ['brand', 'Brand'], ['storage', 'Stored in'], ['location', 'Spot'], ['expirationDate', 'Use by', 'date'],
  ['quantity', 'Quantity', 'number'], ['unit', 'Unit'], ['size', 'Package size'], ['price', 'Price paid', 'number'],
  ['notes', 'Notes', 'textarea'],
]

function EditForm({ item, onDone }) {
  const [f, setF] = useState(() => Object.fromEntries(FIELDS.map(([k]) => [k, item[k] ?? ''])))
  const [err, setErr] = useState(null)
  const qc = useQueryClient()
  const save = async (e) => {
    e.preventDefault()
    const changed = Object.fromEntries(Object.entries(f).filter(([k, v]) => String(item[k] ?? '') !== String(v)))
    if (!Object.keys(changed).length) return onDone()
    try {
      if ('quantity' in changed) changed.quantity = changed.quantity === '' ? '' : Number(changed.quantity)
      if ('price' in changed) changed.price = changed.price === '' ? '' : Number(changed.price)
      await patch(`/items/${item.id}`, changed)
      qc.invalidateQueries()
      onDone()
    } catch (x) { setErr(x) }
  }
  return (
    <form onSubmit={save} className="stack" style={{ gap: 14 }}>
      <div className="field-grid">
        {FIELDS.filter(([, , t]) => t !== 'textarea').map(([k, label, type]) => (
          <label key={k} className="field">
            <span>{label}</span>
            {k === 'storage' ? (
              <select className="select" value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })}>
                {['fridge', 'freezer', 'pantry', 'cupboard', 'counter', 'other'].map((s) => <option key={s} value={s}>{cap(s)}</option>)}
              </select>
            ) : (
              <input className="input" type={type || 'text'} step={type === 'number' ? 'any' : undefined} value={f[k]}
                onChange={(e) => setF({ ...f, [k]: e.target.value })} />
            )}
          </label>
        ))}
      </div>
      <label className="field"><span>Notes</span>
        <textarea className="textarea" value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} />
      </label>
      <p className="note">The category follows the product. Change it from the product's price page.</p>
      <ErrorBox error={err} />
      <div className="btn-row"><button className="btn btn--ink" type="submit">Save changes</button><button className="btn btn--ghost" type="button" onClick={onDone}>Cancel</button></div>
    </form>
  )
}

export default function ItemSheet({ id, onClose }) {
  const { open } = useSheet()
  const toast = useToast()
  const qc = useQueryClient()
  const actions = usePantryActions()
  const [editing, setEditing] = useState(false)
  const { data: it, error, isLoading } = useQuery({ queryKey: ['item', id], queryFn: () => get(`/items/${id}`) })

  const addToList = async () => {
    const r = await post('/shopping', { name: it.product?.name || it.name })
    qc.invalidateQueries({ queryKey: ['shopping'] })
    toast(r.added ? `${r.name} is on the list` : `${r.name} was already on the list`)
  }
  const gone = it?.deletedAt
  const p = it?.product
  return (
    <Sheet title={it?.name || 'Item'} onClose={onClose}
      actions={it && !gone && !editing && <button className="iconbtn" onClick={() => setEditing(true)} aria-label="Edit item"><Pencil /></button>}
      footer={it && !editing && (gone ? (
        <button className="btn" onClick={async () => { await post(`/items/${id}/restore`); qc.invalidateQueries(); }}>Put it back</button>
      ) : (
        <>
          <button className="btn btn--ink" onClick={async () => { await actions.consume(it, 'eaten'); onClose() }}>Ate it</button>
          <button className="btn" onClick={async () => { await actions.consume(it, 'tossed'); onClose() }}>Tossed</button>
          <button className="btn btn--ghost" onClick={addToList}>Add to list</button>
        </>
      ))}>
      {isLoading && <Loading />}
      <ErrorBox error={error} />
      {it && editing && <EditForm item={it} onDone={() => setEditing(false)} />}
      {it && !editing && (
        <>
          <div className="block spread" style={{ alignItems: 'flex-start' }}>
            <dl className="kv">
              <dt>Stored in</dt><dd>{cap(it.storage) || 'Not set'}{it.location && it.location !== it.storage ? `, ${it.location}` : ''}</dd>
              <dt>Category</dt><dd>{it.catLabel}</dd>
              {(it.quantity || it.size) && <><dt>Amount</dt><dd>{[qtyText(it.quantity, it.unit), it.size].filter(Boolean).join(', ')}</dd></>}
              {it.brand && <><dt>Brand</dt><dd>{it.brand}</dd></>}
              {it.bottleState && <><dt>Bottle</dt><dd>{cap(it.bottleState)}{it.abv ? `, ${it.abv}% ABV` : ''}</dd></>}
              <dt>Logged</dt><dd>{ago(it.createdAt)}{it.createdByName ? ` by ${it.createdByName}` : ''}</dd>
              {gone && <><dt>Gone</dt><dd>{shortDate(it.deletedAt)}</dd></>}
            </dl>
            <DateStamp date={it.expirationDate} daysLeft={it.daysLeft} state={it.state}
              estimated={it.expirationSource === 'estimated'} />
          </div>
          {!gone && it.state === 'expired' && (
            <div className="btn-row block">
              <button className="btn btn--sm" onClick={() => actions.keep(it, 7)}>Still good, +7 days</button>
            </div>
          )}
          {it.notes && <p className="block soft" style={{ whiteSpace: 'pre-wrap' }}>{it.notes}</p>}
          {it.images?.length > 0 && (
            <div className="block hstack">
              {it.images.map((x) => <img key={x.path} src={img(x.path)} alt="" style={{ width: 120, height: 120, objectFit: 'cover', borderRadius: 6 }} loading="lazy" />)}
            </div>
          )}

          {p && p.last && (
            <div className="block">
              <div className="block-title"><span>What it costs</span>
                <button className="btn btn--sm btn--ghost" onClick={() => open('product', p.id)}>Price history</button></div>
              <PriceTag name={p.name} meta={lastMeta(p.last)} price={p.last.price} unit={p.last.unit} unitLabel={p.last.unitLabel}
                saved={p.last.saved} regular={p.last.regular} />
              {p.spark?.length > 1 && <div style={{ marginTop: 14 }}><PriceHistory points={p.spark} basis={p.basis} /></div>}
              {p.storeGap && (
                <p className="note" style={{ marginTop: 10 }}>
                  Cheapest at <b>{p.storeGap.cheap}</b> ({p.basis.label === 'pkg' || p.basis.label === 'ea' ? dollars(p.storeGap.cheapV) : unitText(p.storeGap.cheapV)} {perLabel(p.basis.label)}), {p.storeGap.pct}% under {p.storeGap.dear}.
                </p>
              )}
            </div>
          )}
          {p && !p.last && (
            <div className="block note">No price on record for {p.name} yet. Receipts fill this in once they're recorded.</div>
          )}

          {it.purchases?.length > 0 && (
            <div className="block">
              <div className="block-title">This row's purchases</div>
              <div className="list list--panel">
                {it.purchases.map((x) => (
                  <button key={x.id} className="row" onClick={() => x.receiptId && open('receipt', x.receiptId)} disabled={!x.receiptId}>
                    <span>
                      <span className="row__title">{shortDate(x.date, { year: true })}</span>
                      <span className="row__meta" style={{ display: 'block' }}>
                        <StoreKey id={x.storeId} name={x.store || 'No receipt'} />
                        {x.source === 'receipt' ? ', off the receipt' : ', logged without a receipt'}{x.raw ? `: ${x.raw}` : ''}
                      </span>
                    </span>
                    <span className="num lead">{dollars(x.price)}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
          {it.audit?.length > 0 && (
            <div className="block note">
              {it.audit.map((a, i) => (
                <div key={i}>Price corrected from {a.oldPrice != null ? dollars(a.oldPrice) : 'none'} to {dollars(a.newPrice)} {a.reason === 'receipt line' ? 'by the receipt' : 'when relinked'}, {shortDate(a.at)}.</div>
              ))}
            </div>
          )}
        </>
      )}
    </Sheet>
  )
}
