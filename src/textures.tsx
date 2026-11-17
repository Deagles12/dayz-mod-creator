import { useEffect, useState } from 'react'
import { FolderOpen, Upload } from 'lucide-react'
import { open } from '@tauri-apps/plugin-dialog'
import { call, type Settings } from './backend'
import type { Lang } from './locale'
import { OutputFolder, useExportFolder } from './export-folder'

type Conversion = {
  folder: string;
  files: { source: string; output: string }[];
  errors: { source: string; error: string }[];
}

export function Textures({ language, settings, onStatus }: {
  language: Lang; settings: Settings; onStatus: (status: string) => void
}) {
  const tr = (uk: string, en: string) => language === 'uk' ? uk : en
  const [result, setResult] = useState<Conversion>()
  const [total, setTotal] = useState(0)
  const [current, setCurrent] = useState({ step: 0, name: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const output = useExportFolder(language, 'textures', setError)
  const status = busy
    ? total ? tr('Конвертую текстури…', 'Converting textures…') : tr('Вибір файлів', 'Selecting files')
    : error ? tr('Конвертацію не завершено', 'Conversion did not finish')
    : result ? result.errors.length
      ? tr('Є файли з помилками', 'Some files failed')
      : tr('Текстури готові', 'Textures are ready')
    : tr('Вибери зображення або PAA', 'Choose images or PAA files')

  useEffect(() => onStatus(status), [status, onStatus])
  async function choose() {
    setBusy(true)
    setTotal(0)
    setError('')
    try {
      const paths = await open({ multiple: true, filters: [
        { name: 'PNG, JPG, TGA, PAA', extensions: ['png', 'jpg', 'jpeg', 'tga', 'paa'] },
      ] })
      if (!paths?.length) return
      setResult(undefined)
      setCurrent({ step: 0, name: '' })
      setTotal(paths.length)
      setResult(await call<Conversion>(language, 'convertTextures', { paths, settings, output: output.destination }, message => {
        if (message.event === 'progress' && message.stage !== undefined) {
          setCurrent({ step: message.stage, name: message.text || '' })
        }
      }))
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure))
    } finally {
      setBusy(false)
    }
  }

  async function reveal() {
    try {
      if (result) await call(language, 'revealTextures', { path: result.folder })
    } catch (failure) {
      setError(String(failure))
    }
  }

  return <div className="model-tool">
    <section className="tool-input">
      <div className="tool-file-picker">
        <p><code>PNG / JPG / TGA → PAA</code><code>PAA → PNG</code></p>
        <button className="primary" disabled={busy} onClick={() => void choose()}>
          <Upload size={16}/>{tr('Вибрати файли', 'Choose files')}
        </button>
      </div>
      <OutputFolder language={language} {...output} disabled={busy}/>
    </section>
    {(busy || result || error) && <section className="model-status">
      <div className="model-status-head">
        <strong role="status">{status}</strong>
        {busy && total > 0 && <span>{current.step} / {total}</span>}
      </div>
      {busy && current.name && <code className="model-output-path">{current.name}</code>}
      {total > 0 && <progress aria-label={tr('Оброблено файлів', 'Files processed')} max={total}
        value={result ? total : Math.max(0, current.step - 1)}/>}
      {error && <p role="alert" className="model-error">{error}</p>}
    </section>}
    {result && <section className="model-result">
      <h2>{tr('Файли результату', 'Output files')}</h2>
      <code className="model-output-path">{result.folder}</code>
      {result?.files.length ? <ul className="texture-list">
        {result.files.map(file => <li key={file.output}><code>{file.source}</code> → <code>{file.output}</code></li>)}
      </ul> : null}
      {result?.errors.length ? <ul className="texture-list model-error" role="alert">
        {result.errors.map((failure, index) => <li key={index}><strong>{failure.source}</strong> · {failure.error}</li>)}
      </ul> : null}
      {result.files.length > 0 && <button onClick={() => void reveal()}><FolderOpen size={16}/>{tr('Відкрити папку', 'Open folder')}</button>}
    </section>}
  </div>
}
