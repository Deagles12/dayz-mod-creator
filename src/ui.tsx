import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { Check, ChevronDown, Circle, CircleAlert, Search, Terminal, X } from 'lucide-react'

export type Tone = 'good' | 'warn' | 'neutral' | 'active'
export function Status({ tone, children }: { tone: Tone; children: ReactNode }) {
  const Icon = tone === 'good' ? Check : tone === 'warn' ? CircleAlert : Circle
  return <span className={'status '+tone}><Icon size={13} aria-hidden="true"/>{children}</span>
}
export function Menu({ label, children, disabled, className = '' }: {
  label: ReactNode; children: (close: () => void) => ReactNode; disabled?: boolean; className?: string
}) {
  const [open, setOpen] = useState(false)
  const wrapper = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const id = useId()
  useEffect(() => {
    if (!open) return
    const outside = (event: PointerEvent) => {
      if (!wrapper.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', outside)
    return () => document.removeEventListener('pointerdown', outside)
  },[open])
  function close() {setOpen(false);trigger.current?.focus()}
  return <div ref={wrapper} className={'menu '+className} onKeyDown={e=>{
    if(e.key==='Escape' && open){ e.stopPropagation();close() }
    if(e.key==='ArrowDown' || e.key==='ArrowUp'){
      e.preventDefault()
      if(!open){setOpen(true);return}
      const options=Array.from(wrapper.current?.querySelectorAll<HTMLButtonElement>('.menu-body button:not(:disabled)') ?? [])
      const index=options.indexOf(document.activeElement as HTMLButtonElement)
      options[(index+(e.key==='ArrowDown'?1:options.length-1))%options.length]?.focus()
    }
  }}>
    <button ref={trigger} className="menu-trigger" disabled={disabled} aria-expanded={open} aria-controls={id} onClick={()=>setOpen(!open)}>
      {label}<ChevronDown size={14} aria-hidden="true"/>
    </button>
    {open && <div className="menu-body" id={id}>{children(close)}</div>}
  </div>
}

export function LogDrawer({ open, toggle, entries, logs, busy, read, tr }: {
  open: boolean; toggle: () => void; entries: {text:string;error:boolean}[]; logs: string[];
  busy:boolean; read:(path:string)=>void; tr:(uk:string,en:string)=>string
}) {
  const [height,setHeight]=useState(220)
  const [query,setQuery]=useState('')
  const [filter,setFilter]=useState('all')
  const viewport=useRef<HTMLDivElement>(null)
  const follow=useRef(true)
  const visible=entries.filter(entry=>(filter==='all' || (filter==='errors'?entry.error:/warning|\(W\):/i.test(entry.text))) &&
    entry.text.toLocaleLowerCase().includes(query.toLocaleLowerCase()))
  useEffect(()=>{
    if(follow.current && viewport.current) viewport.current.scrollTop=viewport.current.scrollHeight
  },[entries,open])
  const resize=(value:number)=>setHeight(Math.max(125,Math.min(value,Math.floor(window.innerHeight*.52))))
  if(!open)return null
  return <section className="drawer" style={{height}}>
    <div className="splitter" role="separator" aria-orientation="horizontal" aria-label={tr('Висота журналу','Log height')} tabIndex={0}
      onKeyDown={e=>{if(e.key==='ArrowUp'||e.key==='ArrowDown'){e.preventDefault();resize(height+(e.key==='ArrowUp'?16:-16))}}}
      onPointerDown={e=>{e.preventDefault();e.currentTarget.setPointerCapture(e.pointerId);e.currentTarget.dataset.start=String(e.clientY);e.currentTarget.dataset.height=String(height)}}
      onPointerMove={e=>{if(e.currentTarget.hasPointerCapture(e.pointerId))resize(Number(e.currentTarget.dataset.height)+Number(e.currentTarget.dataset.start)-e.clientY)}}/>
    <div className="drawer-tools">
      <strong><Terminal size={15}/>{tr('Журнал','Log')}</strong>
      <label className="search"><Search size={14}/><input aria-label={tr('Пошук у журналі','Search the log')} placeholder={tr('Пошук…','Search…')} value={query} onChange={e=>setQuery(e.target.value)}/></label>
      <div className="segments">{[['all',tr('Усі','All')],['errors',tr('Помилки','Errors')],['warnings',tr('Попередження','Warnings')]].map(([key,label])=>
        <button key={key} aria-pressed={filter===key} onClick={()=>setFilter(key)}>{label}</button>)}</div>
      <Menu label={tr('Історія','History')} disabled={busy||!logs.length} className="up">
        {close=>logs.map(path=><button key={path} onClick={()=>{read(path);close()}}>{path.split(/[\\/]/).pop()}</button>)}
      </Menu>
      <button className="icon-button" title={tr('Закрити журнал','Close log')} aria-label={tr('Закрити журнал','Close log')} onClick={toggle}><X size={16}/></button>
    </div>
    <div ref={viewport} className="terminal" tabIndex={0} onScroll={e=>{const node=e.currentTarget;follow.current=node.scrollHeight-node.scrollTop-node.clientHeight<24}}>
      {visible.length ? visible.map((entry,index)=><div key={index} className={entry.error?'bad':''}>{entry.text}</div>):
        <span className="muted">{entries.length?tr('Збігів немає.','No matches.'):tr('Журнал поки порожній.','The log is empty.')}</span>}
    </div>
  </section>
}
