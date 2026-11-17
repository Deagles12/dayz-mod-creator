import { useEffect, useState } from 'react'
import { open } from '@tauri-apps/plugin-dialog'
import { Box, FolderOpen, ImagePlus, Play, Square, X } from 'lucide-react'
import { call } from './backend'
import { Preview } from './models'
import { OutputFolder, useExportFolder } from './export-folder'
import type { Lang } from './locale'

type Template = { id: string; uk: string; en: string; dimensions: number[]; material: string;
  capDimensions: number[]; bodyColor: string; materials: {id: string; uk: string; en: string}[] }
type Parameters = {
  name: string; template: string; width: number; height: number; depth: number;
  capWidth: number; capHeight: number; material: string; bodyColor: string; capColor: string;
  resolution: number; referenceConfirmed: boolean
}
type Reference = { path: string; data: string }
type Result = { folder: string; name: string; preview: string; texture: string; validation: {
  mesh: { vertices: number; polygons: number; dimensionsMM: number[] }; handleThroughHole: boolean | null;
  glb: { embeddedPNG: boolean }; blendReopened: boolean
} }
type Job = { id: string; state: 'running' | 'done' | 'error' | 'cancelled'; stage: number; result?: Result; error: string }
const stages = [
  ['Підготовка Blender', 'Preparing Blender'], ['Створення геометрії', 'Building geometry'],
  ['UV-розгортка', 'Unwrapping UVs'], ['Запікання текстури', 'Baking texture'],
  ['Експорт і прев’ю', 'Exporting and rendering'], ['Перевірка GLB та BLEND', 'Validating GLB and BLEND'],
  ['Готово', 'Ready'],
] as const

export function Generator({ language, onStatus }: { language: Lang; onStatus: (text: string) => void }) {
  const tr = (uk: string, en: string) => language === 'uk' ? uk : en
  const [templates, setTemplates] = useState<Template[]>([])
  const [values, setValues] = useState<Parameters>({
    name: 'MV_Catalyst', template: 'bottle', width: 48, height: 110, depth: 48,
    capWidth: 24, capHeight: 14, material: 'amber', bodyColor: '#8a4319', capColor: '#171717',
    resolution: 1024, referenceConfirmed: false,
  })
  const [blender, setBlender] = useState('')
  const [references, setReferences] = useState<Reference[]>([])
  const [job, setJob] = useState<Job>()
  const [submitting, setSubmitting] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [error, setError] = useState('')
  const [replace, setReplace] = useState('')
  const output = useExportFolder(language, 'generator', setError)
  const busy = submitting || job?.state === 'running'
  const step = stages[Math.min(job?.stage ?? 0, job?.state === 'done' ? 6 : 5)]
  const status = job?.state === 'cancelled' ? tr('Скасовано', 'Cancelled')
    : job?.state === 'error' ? tr('Генерація не завершена', 'Generation failed')
    : job ? tr(step[0], step[1]) : ''
  useEffect(() => onStatus(status), [status, onStatus])
  useEffect(() => {
    let active = true
    void call<{ templates: Template[]; blender: string }>(language, 'generatorInfo').then(info => {
      if (active) { setTemplates(info.templates); setBlender(previous => previous || info.blender) }
    }).catch(failure => { if (active) setError(String(failure)) })
    return () => { active = false }
  }, [language])
  useEffect(() => {
    if (job?.state !== 'running') return
    let active = true
    let timer: ReturnType<typeof setTimeout>
    async function poll() {
      try {
        const next = await call<Job>(language, 'generatorStatus', { job: job!.id })
        if (!active) return
        setJob(next)
        if (next.state === 'running') timer = setTimeout(() => void poll(), 400)
      } catch (failure) {
        if (active) {
          setError(String(failure))
          setJob(previous => previous ? {...previous, state: 'error', error: String(failure)} : previous)
        }
      }
    }
    timer = setTimeout(() => void poll(), 200)
    return () => { active = false; clearTimeout(timer) }
  }, [job?.id, job?.state, language])

  function change<K extends keyof Parameters>(key: K, value: Parameters[K]) {
    setValues(previous => ({ ...previous, [key]: value }))
    setReplace('')
  }
  async function chooseReferences() {
    try {
      const paths = await open({ multiple: true, filters: [{ name: 'PNG / JPG', extensions: ['png', 'jpg', 'jpeg'] }] })
      if (!paths) return
      if (references.length + paths.length > 5) throw new Error(tr('Максимум п’ять ракурсів.', 'Maximum five views.'))
      const images = await Promise.all(paths.map(path => call<Reference>(language, 'generatorReference', { path })))
      setReferences(previous => [...previous, ...images])
      change('referenceConfirmed', false)
    } catch (failure) { setError(String(failure)) }
  }
  async function chooseBlender() {
    const path = await open({ multiple: false, filters: [{ name: 'Blender', extensions: ['exe'] }] })
    if (typeof path === 'string') setBlender(path)
  }
  async function generate(overwrite = false) {
    setSubmitting(true)
    setError('')
    setCancelling(false)
    setJob(undefined)
    const request = { ...values, references: references.map(image => image.path), blender, output: output.destination }
    try {
      const destination = await call<{ folder: string; exists: boolean }>(language, 'generatorTarget', request)
      if (destination.exists && (!overwrite || destination.folder !== replace)) {
        setReplace(destination.folder)
        return
      }
      setReplace('')
      setJob(await call<Job>(language, 'generatorStart', { ...request, overwrite }))
    } catch (failure) { setError(String(failure)) }
    finally { setSubmitting(false) }
  }
  async function cancel() {
    if (!job) return
    setCancelling(true)
    try { await call(language, 'generatorCancel', { job: job.id }) }
    catch (failure) { setCancelling(false); setError(String(failure)) }
  }
  async function reveal(inBlender: boolean) {
    try { await call(language, 'generatorReveal', { job: job?.id, blender: inBlender }) }
    catch (failure) { setError(String(failure)) }
  }
  const result = job?.state === 'done' ? job.result : undefined
  return <div className="generator-tool">
    <fieldset disabled={busy} className="generator-input">
      <div className="form-grid">
        <label>{tr('Назва предмета', 'Item name')}<input value={values.name} onChange={event => change('name', event.target.value)}/></label>
        <label>{tr('Тип предмета', 'Item type')}<select value={values.template} onChange={event => {
          const template = templates.find(item => item.id === event.target.value)!
          setValues(previous => ({ ...previous, template: template.id, width: template.dimensions[0],
            height: template.dimensions[1], depth: template.dimensions[2], material: template.material,
            capWidth: template.capDimensions[0], capHeight: template.capDimensions[1],
            bodyColor: template.bodyColor, referenceConfirmed: false }))
          setReplace('')
        }}>{templates.map(item => <option key={item.id} value={item.id}>{tr(item.uk, item.en)}</option>)}</select></label>
      </div>
      <div className="generator-dimensions">{([
        ['width', 'Ширина, мм', 'Width, mm'], ['height', 'Висота, мм', 'Height, mm'], ['depth', 'Глибина, мм', 'Depth, mm'],
        ['capWidth', 'Діаметр кришки, мм', 'Cap diameter, mm'], ['capHeight', 'Висота кришки, мм', 'Cap height, mm'],
      ] as const).map(([key, uk, en]) => <label key={key}>{tr(uk, en)}<input type="number" min="1" max="3000" step="1" value={values[key]}
        onChange={event => change(key, Number(event.target.value))}/></label>)}</div>
      <div className="form-grid">
        <label>{tr('Матеріал', 'Material')}<select value={values.material} onChange={event => change('material', event.target.value)}>
          {templates.find(item => item.id === values.template)?.materials.map(item => <option key={item.id} value={item.id}>{tr(item.uk, item.en)}</option>)}
        </select></label>
        <label>{tr('Роздільність текстури', 'Texture resolution')}<select value={values.resolution} onChange={event => change('resolution', Number(event.target.value))}>
          {[512, 1024, 2048].map(size => <option key={size} value={size}>{size} × {size}</option>)}
        </select></label>
        <label className="generator-color">{tr('Колір корпусу', 'Body colour')}<input type="color" value={values.bodyColor} onChange={event => change('bodyColor', event.target.value)}/></label>
        <label className="generator-color">{tr('Колір кришки', 'Cap colour')}<input type="color" value={values.capColor} onChange={event => change('capColor', event.target.value)}/></label>
      </div>
      <div className="generator-references">
        <button onClick={() => void chooseReferences()}><ImagePlus size={16}/>{tr('Додати фото / ракурси', 'Add photo / views')}</button>
        {!!references.length && <>
          <div className="reference-images">{references.map((image, index) => <div key={image.path + index}>
            <img src={image.data} alt={tr('Референс предмета', 'Item reference')}/>
            <button aria-label={tr('Видалити фото', 'Remove photo')} onClick={() => {
              setReferences(previous => previous.filter((_, item) => item !== index)); change('referenceConfirmed', false)
            }}><X size={14}/></button>
          </div>)}</div>
          <p>{tr('Перевір тип предмета на фото й задай його пропорції та кольори вручну.', 'Check the item type in the photo and set its proportions and colours manually.')}</p>
          <label className="generator-confirm"><input type="checkbox" checked={values.referenceConfirmed}
            onChange={event => change('referenceConfirmed', event.target.checked)}/>{tr('Фото відповідає вибраному шаблону', 'The photo matches the selected template')}</label>
        </>}
      </div>
      <div className="generator-blender"><div><small>Blender</small><code className="model-output-path">{blender || tr('Вибери blender.exe', 'Choose blender.exe')}</code></div>
        <button onClick={() => void chooseBlender().catch(failure => setError(String(failure)))}><FolderOpen size={16}/>{tr('Вибрати Blender', 'Choose Blender')}</button></div>
      <OutputFolder language={language} {...output} disabled={busy}/>
    </fieldset>
    {replace && <section role="alert"><p>{tr('Замінити попередні файли предмета?', 'Replace the existing item files?')}</p>
      <code className="model-output-path">{replace}</code><div className="generator-actions">
        <button disabled={busy} onClick={() => void generate(true)}>{tr('Замінити й згенерувати', 'Replace and generate')}</button>
        <button disabled={busy} onClick={() => setReplace('')}>{tr('Назад', 'Back')}</button>
      </div></section>}
    <div className="generator-actions">
      <button className="primary" disabled={busy || !blender || !templates.length} onClick={() => void generate()}><Play size={16}/>{result ? tr('Згенерувати повторно', 'Regenerate') : tr('Згенерувати', 'Generate')}</button>
      {busy && <button disabled={cancelling || submitting} onClick={() => void cancel()}><Square size={15}/>{cancelling ? tr('Скасовую…', 'Cancelling…') : tr('Скасувати', 'Cancel')}</button>}
    </div>
    {job && <section className="model-status"><strong role="status">{status}</strong>
      {job.state === 'running' && <progress max="6" value={job.stage} aria-label={tr('Прогрес генерації', 'Generation progress')}/>}
      {job.state === 'error' && <details><summary>{tr('Причина помилки', 'Error details')}</summary><pre className="generator-error">{job.error}</pre></details>}
    </section>}
    {error && <p className="model-error" role="alert">{error}</p>}
    {result && <>
      <Preview data={result.preview} fallback={tr('3D-прев’ю недоступне.', '3D preview is unavailable.')}/>
      <section className="model-result"><h2>{tr('UV-текстура', 'UV texture')}</h2>
        <img className="generator-atlas" src={result.texture} alt={tr('Згенерований UV-атлас', 'Generated UV atlas')}/>
        <p>{result.validation.mesh.vertices} {tr('вершин', 'vertices')} · {result.validation.mesh.polygons} {tr('полігонів', 'polygons')} · {result.validation.mesh.dimensionsMM.join(' × ')} {tr('мм', 'mm')}</p>
        <code className="model-output-path">{result.folder}</code>
        <div className="generator-actions">
          <button onClick={() => void reveal(true)}><Box size={16}/>{tr('Відкрити в Blender', 'Open in Blender')}</button>
          <button onClick={() => void reveal(false)}><FolderOpen size={16}/>{tr('Відкрити папку', 'Open folder')}</button>
        </div>
      </section>
    </>}
  </div>
}
