import { Activity, ArrowUpRight, Box, ChevronRight, CircleHelp, ClipboardList, CloudUpload, FolderOpen, Folders, Gauge, ListFilter, Minus, Monitor, Play, Plus, RefreshCw, Server, Settings2, Square, Terminal, Trash2, X } from 'lucide-react'
import { LogDrawer, Menu, Status } from './ui'
import { lazy, Suspense, useEffect, useState, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { getCurrentWindow } from '@tauri-apps/api/window'
import { open } from '@tauri-apps/plugin-dialog'
import { call, type Details, type Message, type Operation, type Project, type RunResult, type Settings } from './backend'
import { checks, fields, hints, pages, phases, type Lang, type Page } from './locale'
import './style.css'

const Models = lazy(() => import('./models').then(module => ({ default: module.Models })))

type Prefs = { language: Lang; theme: 'dark' | 'light'; projects: string[] }
type Action = 'deploy' | 'launch' | 'retry' | 'build' | 'test' | 'rollback' | 'publish' | 'retry-publish' | 'remote' | 'remote-check' | 'create-workshop'
fields.client_mods_root = ['Локальна папка тестових модів', 'Local test mod folder', 'folder']
fields.open_dayz = ['Відкрити DayZ після оновлення', 'Open DayZ after updating', 'bool']
fields.publish_workshop = ['Публікувати у Workshop', 'Publish to Workshop', 'bool']
fields.workshop = ['Посилання або ID Steam Workshop', 'Steam Workshop URL or ID', '']
fields.workshop_title = ['Назва нового item', 'New item title', '']
fields.workshop_description = ['Опис', 'Description', 'text']
fields.workshop_preview = ['Обкладинка PNG або JPEG', 'PNG or JPEG preview', 'file']
fields.workshop_visibility = ['Видимість (public, friends, private, unlisted)', 'Visibility (public, friends, private, unlisted)', '']
fields.remote_host = ['Адреса SSH', 'SSH host', '']
fields.remote_port = ['Порт SSH (типово 22)', 'SSH port (default 22)', '']
fields.remote_user = ['Користувач SSH', 'SSH username', '']
fields.remote_root = ['Папка DayZ на сервері', 'Remote DayZ directory', '']
fields.remote_mod = ['Папка мода (@Mod)', 'Mod directory (@Mod)', '']
fields.remote_keys = ['Папка публічних ключів', 'Remote public keys directory', '']
fields.remote_service = ['Служба systemd (.service)', 'systemd unit (.service)', '']
fields.remote_readiness = ['Команда перевірки готовності', 'Readiness command', '']
fields.remote_files_only = ['Лише завантаження через SFTP', 'SFTP upload only', 'bool']
hints.remote_user = ['Авторизація ключем через OpenSSH або ssh-agent.', 'Authenticate with an OpenSSH key or ssh-agent.']
hints.remote_readiness = ['Команда виконується через SSH. Код 0 означає готовність. Зберігай облікові дані на сервері.',
  'Runs over SSH. Exit code 0 means ready. Keep credentials on the server.']
fields.environment_override = ['Окреме середовище лише для цього проєкту', 'Use a different environment for this project', 'bool']
hints.client_mods_root = ['Вибери папку поза каталогом завантажень Steam. Порожнє поле використовує локальне сховище Studio.',
  'Choose a folder outside Steam downloads. Leaving this blank uses Studio’s local storage.']
hints.base = ['Одна папка або Workshop ID на рядок. Сервер і клієнт завантажують ту саму локальну версію.',
  'One directory or Workshop ID per line. The server and client load the same local version.']
const groups = [
  { title: ['Джерело й інструменти', 'Source and tools'], basic: ['addons','mod'], advanced: ['pack','addon_name','prefix','metadata','extra','prep_exe','prep_args'] },
  { title: ['Тестове середовище', 'Test environment'], basic: ['tools','server','client','config','base','open_dayz'], advanced: ['profiles','client_profiles','port','server_only','server_exe','client_exe','address','timeout','shared','server_args','client_args','client_mods_root','environment_override'] },
  { title: ['Підпис', 'Signing'], basic: ['sign','private','public'], advanced: [] },
  { title: ['Steam Workshop', 'Steam Workshop'], basic: ['publish_workshop','workshop','steam_owner','notes'], advanced: [] },
  { title: ['Віддалений сервер', 'Remote server'], basic: ['remote_host','remote_port','remote_user','remote_root','remote_mod','remote_files_only','remote_keys','remote_service','remote_readiness'], advanced: [] },
] as const

const defaultPrefs: Prefs = { language: 'uk', theme: 'dark', projects: [] }
const nameOf = (path: string) => path.split(/[\\/]/).pop() || path
const isError = (line: string) => /\[ERROR\]|\(E\):|can't compile|\b(error|fatal|failed)\s*:/i.test(line)
const desktop = getCurrentWindow()

async function writeClipboard(text: string) {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const active = document.activeElement
    const field = document.createElement('textarea')
    field.value = text
    field.style.position = 'fixed'
    field.style.opacity = '0'
    document.body.append(field)
    try {
      field.select()
      if (!document.execCommand('copy')) throw new Error('Clipboard write failed')
    } finally {
      field.remove()
      if (active instanceof HTMLElement) active.focus()
    }
  }
}

function App() {
  const [prefs, setPrefs] = useState(defaultPrefs)
  const [page, setPage] = useState<Page>('overview')
  const [project, setProject] = useState<Project>()
  const [settings, setSettings] = useState<Settings>({})
  const [busy, setBusy] = useState(false)
  const [advanced, setAdvanced] = useState(false)
  const [wizard, setWizard] = useState<number>()
  const [confirmation, setConfirmation] = useState<Action>()
  const [run, setRun] = useState<{ action: Action; stage: number; label?: Message['label']; done?: boolean }>()
  const [entries, setEntries] = useState<{ text: string; error: boolean }[]>([])
  const [dependency, setDependency] = useState('')
  const [dependencyType, setDependencyType] = useState('base')
  const [settingsGroup,setSettingsGroup] = useState(1)
  const [live,setLive] = useState<'ready'|'offline'|'unknown'>('unknown')
  const [showLog, setShowLog] = useState(false)
  const [hasEnvironment, setHasEnvironment] = useState(false)
  const [selectedReport, setSelectedReport] = useState<Operation>()
  const [notice, setNotice] = useState('')
  const [terminalAction, setTerminalAction] = useState('status')
  const [keyName, setKeyName] = useState('')
  const [checkedItem, setCheckedItem] = useState<{ input: string; title?: string; status: 'owner' | 'mismatch' | 'unknown' }>()
  const lng = prefs.language
  const settingsDirty = !!project && Object.entries(settings).some(([key, value]) => project.settings[key] !== value)
  const tr = (uk: string, en: string) => lng === 'en' ? en : uk
  const local = (pair: readonly [string, string]) => tr(...pair)
  const flagError = (error: unknown) => {
    setNotice(String(error instanceof Error ? error.message : error))
  }

  async function loadProject(root: string, preference = prefs, setup = true, environment = hasEnvironment) {
    const found = await call<Project>(preference.language, 'open', {root})
    setProject(found)
    setSettings(found.settings)
    setEntries([])
    setSelectedReport(undefined)
    setRun(undefined)
    setNotice('')
    const log=found.details.logs[0]
    if(log) {
      const text=await call<string>(preference.language,'readLog',{root:found.root,path:log}).catch(()=>'')
      setEntries(text.split(/\r?\n/).filter(Boolean).map(text=>({text,error:isError(text)})))
    }
    setPage('overview')
    if (setup && !found.configured && !environment) setWizard(0)
    const next = {...preference, projects: [found.root, ...preference.projects.filter(path => path !== found.root)].slice(0, 30)}
    setPrefs(next)
    await call(next.language, 'preferences', {value: next})
  }
  useEffect(() => {
    call<{hasEnvironment: boolean; interface: Partial<Prefs>; recent: {project?: string}}>('uk', 'hello').then(async data => {
      const next = {...defaultPrefs, ...data.interface}
      setPrefs(next)
      setHasEnvironment(data.hasEnvironment)
      if (data.recent.project) await loadProject(data.recent.project, next, !data.hasEnvironment, data.hasEnvironment)
    }).catch(flagError)
  }, [])
  useEffect(() => {
    document.documentElement.dataset.theme = prefs.theme
    document.documentElement.lang = lng
  }, [prefs.theme, lng])
  async function changePrefs(change: Partial<Prefs>) {
    const next = {...prefs, ...change}
    setPrefs(next)
    try {
      await call(next.language, 'preferences', {value: next})
      if (project && !busy) await refresh(next.language)
    } catch (error) { flagError(error) }
  }
  async function chooseProject() {
    try {
      const folder = await open({directory: true, multiple: false})
      if (typeof folder === 'string') await loadProject(folder)
    } catch (error) { flagError(error) }
  }
  async function refresh(language = lng, next = settings) {
    if (!project) return
    const details = await call<Details>(language, 'details', {root: project.root, settings: next})
    setProject(previous => previous?.root === project.root ? {...previous, details} : previous)
  }
  async function saveSettings() {
    if (!project) return
    try {
      const details = await call<Details>(lng, 'save', {root: project.root, settings})
      setProject({...project, configured: true, settings, details})
      setHasEnvironment(true)
      setNotice(tr('Налаштування збережено.', 'Settings saved.'))
      setWizard(undefined)
    } catch (error) { flagError(error) }
  }
  async function copyCommand(action: string) {
    if (!project || busy) return
    const shown = project.details.commands[action]
    if (!shown) return
    setBusy(true)
    try {
      let command = shown
      if (settingsDirty || !project.configured) {
        const details = await call<Details>(lng, 'save', {root: project.root, settings})
        setProject({...project, configured: true, settings, details})
        setHasEnvironment(true)
        command = details.commands[action]
        if (action === 'remote' && command !== shown) {
          setNotice(tr('Налаштування збережено. Звір вибрану збірку F6 і скопіюй оновлену команду.',
            'Settings saved. Review the selected F6 build and copy the updated command.'))
          return
        }
      }
      if (command) await writeClipboard(command)
      setNotice(tr('Команду скопійовано для PowerShell.', 'PowerShell command copied.'))
    } catch (error) { flagError(error) }
    finally { setBusy(false) }
  }
  async function detect() {
    try {
      const paths = await call<Settings>(lng, 'detect', {settings})
      const next = {...settings, ...paths}
      setSettings(next)
      await refresh(lng, next)
      setNotice(tr('Інсталяцій знайдено: ', 'Installations found: ') + Object.keys(paths).length)
    } catch (error) { flagError(error) }
  }
  async function steamOwner() {
    if (!project || busy) return
    setBusy(true)
    try {
      const owner = await call<string>(lng, 'steamOwner', {root: project.root, settings})
      setSettings(previous => ({...previous, steam_owner: owner}))
    } catch (error) { flagError(error) }
    finally { setBusy(false) }
  }
  async function checkWorkshop() {
    if (!project || busy) return
    setBusy(true)
    try {
      const result = await call<{owner: string; title?: string; status: 'owner' | 'mismatch' | 'unknown'}>(
        lng, 'workshopCheck', {root: project.root, settings})
      setCheckedItem({input: String(settings.workshop), title: result.title, status: result.status})
      setSettings(previous => ({...previous, steam_owner: result.owner}))
      setNotice(result.status === 'owner'
        ? tr('Активний акаунт є власником DayZ item.', 'The active Steam account owns this DayZ item.')
        : result.status === 'mismatch'
        ? tr('Item належить іншому акаунту або грі.', 'The item belongs to another account or game.')
        : tr('Steam не надав публічних даних item.', 'Steam did not return public item details.'))
    } catch (error) { flagError(error) }
    finally { setBusy(false) }
  }
  async function generateKeys() {
    if (!project || busy) return
    setBusy(true)
    try {
      const keys = await call<Settings>(lng, 'generateKeys', {root: project.root, settings, name: keyName.trim()})
      const next = {...settings, ...keys}
      setSettings(next)
      await refresh(lng, next)
      setNotice(tr('Пару ключів створено. Збережи налаштування, щоб її використовувати.', 'Key pair created. Save settings to use it.'))
    } catch (error) { flagError(error) }
    finally { setBusy(false) }
  }
  async function start(action: Action) {
    if (!project || busy) return
    const buildId = action === 'remote' ? project.details.remoteChoice.buildId : undefined
    if (action === 'remote' && (!settings.remote_host || !buildId)) return
    if (action === 'test' && ((!project.configured && !hasEnvironment) || project.details.checks.some(check=>!check.ok))) {
      setWizard(0)
      return
    }
    setBusy(true)
    setConfirmation(undefined)
    setEntries([])
    setNotice('')
    setSelectedReport(undefined)
    setRun({action, stage: 0})
    try {
      const details = await call<RunResult>(lng, 'run', {root: project.root, settings, action, buildId}, message => {
        if (message.event === 'log' && message.text) {
          const text = message.text
          setEntries(previous => [...previous.slice(-2999), {text, error: isError(text)}])
        }
        if (message.event === 'progress') setRun({action, stage: message.stage ?? 0, label: message.label})
      })
      const saved = {...settings, workshop: details.workshopItem}
      setProject({...project, configured: true, settings: saved, details})
      setSettings(saved)
      setHasEnvironment(true)
      setSelectedReport(details.currentOperation)
      setRun(previous => previous && {...previous, done: details.currentOperation.status === 'complete'})
      setPage('overview')
    } catch (error) {
      flagError(error)
      setEntries(previous => [...previous, {text: error instanceof Error ? error.message : String(error), error: true}])
      setRun(previous => previous && {...previous, done: false})
      await refresh().catch(() => undefined)
    } finally { setBusy(false) }
  }
  useEffect(() => {
    const keyboard = (event: KeyboardEvent) => {
      if (event.key === 'F5' || event.key === 'F6') {
        event.preventDefault()
        if (!event.repeat && wizard === undefined && !confirmation) void start(event.key === 'F5' ? 'test' : 'remote')
      }
    }
    window.addEventListener('keydown', keyboard)
    return () => window.removeEventListener('keydown', keyboard)
  })
  useEffect(() => {
    if (!project || busy || settingsDirty || page !== 'overview') return
    let active = true
    const onFocus = () => {
      void call<Project>(lng, 'snapshot', {root: project.root}).then(found => {
        if (!active) return
        if (found.details.operations[0]?.date !== project.details.operations[0]?.date) {
          setSelectedReport(undefined)
          setRun(undefined)
        }
        setProject(found)
        setSettings(found.settings)
      }).catch(error => { if (active) flagError(error) })
    }
    window.addEventListener('focus', onFocus)
    return () => {
      active = false
      window.removeEventListener('focus', onFocus)
    }
  })
  async function reveal(path: string) {
    if (project) await call(lng, 'reveal', {root: project.root, path}).catch(flagError)
  }
  async function readLog(path: string) {
    if (!project || busy) return
    try {
      const text = await call<string>(lng, 'readLog', {root: project.root, path})
      setEntries(text.split(/\r?\n/).map(text => ({text,error:isError(text)})))
      setShowLog(true)
    } catch (error) { flagError(error) }
  }

  useEffect(()=>{
    setLive('unknown')
    if(!project || busy || (page!=='overview' && page!=='server'))return
    let cancelled=false
    const peek=()=>void call<'ready'|'offline'|'unknown'>(lng,'serverStatus',{root:project.root,settings})
      .then(value=>{if(!cancelled)setLive(value)}).catch(()=>{if(!cancelled)setLive('unknown')})
    peek()
    const timer=window.setInterval(peek,12000)
    return ()=>{cancelled=true;window.clearInterval(timer)}
  },[project?.root,project?.details.operations[0]?.date,busy,page,lng,settings.server,settings.port,settings.profiles,settings.server_exe])

  function dependencies() {
    const rows=['base','server_only'].flatMap(key=>String(settings[key]||'').split(/\r?\n/).map(path=>path.trim()).filter(Boolean).map((path,index)=>({path,key,order:index+1})))
    const required = project?.details.dependencies.filter(name => !name.toUpperCase().startsWith('DZ_')) || []
    function change(key:string, value:string, remove=false) {
      const items=String(settings[key]||'').split(/\r?\n/).map(path=>path.trim()).filter(Boolean)
      const normalized=value.trim()
      if(!normalized)return
      const next={...settings,[key]: (remove ? items.filter(path=>path!==normalized) : [...new Set([...items,normalized])]).join('\n')}
      setSettings(next)
      setDependency('')
      void refresh(lng,next).catch(flagError)
    }
    return <div className="dependency-list">
      {rows.length ? rows.map(({path,key,order})=>{
        const match = project?.details.dependencyState.find(row => row.entry===path && row.kind===key)
        return <div className="data-row" key={key+order}>
        <Box size={15}/><div className="min-w-0 grow"><strong title={path}>{order}. {nameOf(path)}</strong><small title={match?.error}>{match?.path || path}</small></div>
        {match && <Status tone={match.available?'good':'warn'}>{match.available ? tr('Файли є','Files available') : tr('Потрібна перевірка','Check required')}</Status>}
        <span className="muted nowrap">{key==='base'?tr('Спільна','Shared'):tr('Серверна','Server only')}</span>
        <button className="icon-button" title={tr('Видалити','Remove')} aria-label={tr('Видалити','Remove')} onClick={()=>change(key,path,true)}><Trash2 size={15}/></button>
      </div>}) : <p className="muted">{tr('Додаткових модів у запуску немає.','No additional mods in the launch list.')}</p>}
      {required.length > 0 && <p className="muted">{tr('Звір вручну класи requiredAddons із потрібними модами','Check these requiredAddons classes against the required mods')} · {required.join(', ')}</p>}
      <div className="dependency-add">
        <Menu label={dependencyType==='base'?tr('Спільна','Shared'):tr('Серверна','Server only')}>
          {close=>['base','server_only'].map(key=><button key={key} onClick={()=>{setDependencyType(key);close()}}>{key==='base'?tr('Спільна','Shared'):tr('Серверна','Server only')}</button>)}
        </Menu>
        <input aria-label={tr('Папка або Workshop ID','Folder or Workshop ID')} placeholder={tr('Папка або Workshop ID','Folder or Workshop ID')}
          value={dependency} onChange={e=>setDependency(e.target.value)} onKeyDown={e=>{if(e.key==='Enter')change(dependencyType,dependency)}}/>
        <button title={tr('Вибрати папку','Browse folder')} aria-label={tr('Вибрати папку','Browse folder')} onClick={async()=>{
          try{const path=await open({directory:true,multiple:false});if(typeof path==='string')change(dependencyType,path)}catch(error){flagError(error)}
        }}><FolderOpen size={15}/></button>
        <button title={tr('Додати','Add')} aria-label={tr('Додати','Add')} disabled={!dependency.trim()} onClick={()=>change(dependencyType,dependency)}><Plus size={15}/></button>
      </div>
      <small>{tr('Зміни застосовуються після збереження або запуску тесту.','Changes apply when you save or start a test.')}</small>
    </div>
  }

  function form(keys: readonly string[]) {
    return <div className="form-grid">{keys.filter(key=>key!=='server_only').map(key => {
      if(key==='base')return <div key={key} className="wide">{dependencies()}</div>
      const [uk, en, kind] = fields[key]
      const value = settings[key] ?? ''
      const update = (value: string | boolean) => setSettings(previous => ({...previous, [key]:value}))
      if (kind === 'bool') return <label className="flex items-center gap-2" key={key}><input type="checkbox" checked={Boolean(value)} onChange={e=>update(e.target.checked)}/>{tr(uk,en)}</label>
      return <div key={key} className={kind==='text'?'wide':undefined}><label htmlFor={key}>{tr(uk,en)}</label>
        <div className="flex gap-2 mt-1">
          {kind === 'text' ? <textarea id={key} rows={key === 'base' ? 5 : 3} value={String(value)} onChange={e=>update(e.target.value)}/> :
            <input id={key} value={String(value)} onChange={e=>update(e.target.value)}/>}
          {(kind === 'file' || kind === 'folder') && <button onClick={async () => {
            try { const path = await open({directory:kind === 'folder', multiple:false}); if (typeof path === 'string') update(path) } catch(error) {flagError(error)}
          }}>{tr('Огляд…','Browse…')}</button>}
        </div>{hints[key] && <small>{local(hints[key])}</small>}
      </div>
    })}</div>
  }
  function readiness() {
    return <div className="readiness">{project?.details.checks.map(check => {
      const disabled=check.key==='signing' && check.ok && !settings.sign
      return <div className="data-row" key={check.key}>
        <div className="min-w-0 grow"><strong>{checks[check.key] ? local(checks[check.key]) : check.key}</strong>
          <small title={check.detail}>{check.detail}</small></div>
        <Status tone={disabled?'neutral':check.ok?'good':'warn'}>{disabled?tr('Вимкнено','Disabled'):check.ok?tr('Перевірено','Verified'):tr('Потрібна увага','Needs attention')}</Status>
      </div>
    })}</div>
  }

  const operationNames: Record<string, [string,string]> = {
    deploy:['Встановлення','Deployment'], launch:['Запуск тесту','Launch test'], test:['Тестування','Test'], retry:['Продовження тесту','Resume test'], build:['Збірка','Build'],
    rollback:['Відкат','Rollback'], publish:['Оновлення Workshop','Workshop update'],
    'retry-publish':['Повторна публікація','Retry publication'],
    remote:['Віддалене встановлення','Remote deployment'], 'remote-check':['Перевірка SSH/SFTP','SSH/SFTP check'],
    'create-workshop':['Перша публікація Workshop','First Workshop publication']
  }
  function operation(report: Operation) {
    const test = ['test','retry','deploy','launch'].includes(report.action)
    const failed = report.status==='failed'
    const phase = report.phase > 0 ? local(phases[report.phase-1]) : tr('Підготовка','Preflight')
    return <section className="report">
      <h2>{local(operationNames[report.action])} · {failed?(report.attention?tr('Потребує уваги','Needs attention'):tr('Помилка','Error')):tr('Завершено','Complete')}</h2>
      <p>{report.buildId && report.buildId + ' · '}{report.seconds} {tr('с','s')} · {tr('Попереджень у журналі','Warnings in log')}: {report.warnings}</p>
      {report.built && <p>{tr('Пакет перевірено','Package verified')} · {report.signed?tr('підпис перевірено','signature verified'):tr('без підпису','unsigned')}</p>}
      {test && <div className="grid gap-1 mb-3">
        <div>{tr('Мод','Mod')}: {report.installed?tr('копії перевірено','copies verified'):tr('оновлення не підтверджено','update not verified')}</div>
        <div>{tr('Сервер','Server')}: {report.serverReady?tr('місія й порт підтверджені','mission and port confirmed'):tr('готовність не підтверджена','readiness not confirmed')}</div>
        <div>{tr('Клієнт','Client')}: {report.connected?tr('сервер підтвердив підключення','connection confirmed by the server'):
          report.clientLaunched?tr('запущено, підключення не підтверджене','launched, connection not confirmed'):tr('не запускали','not launched')}</div>
      </div>}
      {failed && <p className="bad">{test && !report.workshopStatus ? phase + ' · ' : ''}{report.error}</p>}
      {report.workshopStatus === 'confirmed' && <p>{tr('Steam підтвердив публікацію.','Steam confirmed the publication.')}</p>}
      {report.clientError && <p>{tr('Помилка запуску DayZ','DayZ launch error')} · {report.clientError}</p>}
      {report.serverReady && <p>{tr('Перевір поведінку мода у грі.','Check the mod’s behavior in game.')}</p>}
      {report.remote?.staging && <small title={report.remote.staging}>{tr('Проміжна папка','Staging directory')} · {report.remote.staging}</small>}
      {report.remote?.status === 'uploaded' && <p>{tr('Файли завантажено; потрібне ручне встановлення й перезапуск.',
        'Files uploaded. Manual installation and restart required.')}</p>}
      {!!report.updated.length && <details><summary>{tr('Оновлені папки та ключі','Updated folders and keys')}</summary>
        {report.updated.map(path=><small key={path}>{path}</small>)}</details>}
      {!!report.files.length && <details><summary>{tr('Файли пакета','Package files')} ({report.files.length})</summary>
        {report.files.map(path=><small key={path}>{path}</small>)}</details>}
      <div className="flex flex-wrap gap-2 mt-3">
        <button disabled={busy} onClick={()=>void readLog(report.log)}>{tr('Технічний журнал','Technical log')}</button>
        {failed && test && project?.details.retry && report.date===project.details.operations[0]?.date &&
          <button disabled={busy} onClick={()=>void start('retry')}>{tr('Продовжити без збірки','Resume without rebuilding')}</button>}
        {failed && <button onClick={()=>setWizard(0)}>{tr('Перевірити налаштування','Check setup')}</button>}
        {failed && report.action==='deploy' && <button disabled={busy} onClick={()=>void start('deploy')}>{tr('Повторити встановлення','Retry deployment')}</button>}
        {failed && report.action==='build' && <button disabled={busy} onClick={()=>void start('build')}>{tr('Повторити збірку','Retry build')}</button>}
      </div>
      {failed && report.next && project?.details.operations[0]?.date === report.date && commandLine(report.next.action)}
    </section>
  }
  function commandLine(action: string) {
    const command = project?.details.commands[action]
    if (!command) return null
    return <div className="command-line">
      <code>{command}</code>
      <button disabled={busy} onClick={()=>void copyCommand(action)}>{tr('Скопіювати команду','Copy command')}</button>
    </div>
  }
  const title = pages.find(item=>item[0]===page)!
  const stageText = !run ? tr('Готово', 'Ready') : run.done === false ? tr('Операція завершилася помилкою', 'Operation failed') :
    run.done ? tr('Операцію завершено', 'Operation complete') : Array.isArray(run.label) ? local(run.label) :
    run.label || tr('Перевірка середовища…', 'Checking environment…')
  const setupGroup = wizard === undefined ? undefined : groups[wizard]
  const ready = !!project && (project.configured || hasEnvironment) && project.details.checks.length>0 && project.details.checks.every(check=>check.ok)
  const lastTest = project?.details.operations.find(item=>['test','retry','launch'].includes(item.action))
  const navIcons = [Gauge,Folders,Box,Server,CloudUpload,Settings2,Box]
  const serverState = live==='ready' ? tr('Порт активний','Listening') : live==='offline' ? tr('Не запущено','Stopped') : tr('Немає підтвердження','Unverified')
  const clientState = lastTest?.connected ? tr('Вхід підтверджено в останньому тесті','Connected in last test') :
    lastTest?.clientLaunched ? tr('Вхід не підтверджено','Connection unverified') : tr('Ще не перевірено','Not tested')
  const hasSetup = project?.configured || hasEnvironment
  const lastBuild=project?.details.operations.find(item=>['test','retry','build','deploy','launch'].includes(item.action))
  const latestPackage=project?.details.builds[0]
  function workflowRow(title:string, description:string, state:string, action?:ReactNode) {
    const labels: Record<string,[string,string]> = {pending:['Очікує','Pending'],running:['Виконується','Running'],
      ready:['Готово','Ready'],known:['Останній відомий','Last known'],confirmed:['Підтверджено Steam','Confirmed by Steam'],skipped:['Пропущено','Skipped'],error:['Помилка','Error'],attention:['Потребує уваги','Needs attention']}
    return <div className="workflow-row" key={title}><div><strong>{title}</strong><small>{description}</small></div>
      <Status tone={state==='ready'?'good':state==='running'?'active':state==='error'||state==='attention'?'warn':'neutral'}>{local(labels[state])}</Status>
      <div>{action}</div></div>
  }
  const startButton = <button className="primary" disabled={busy || !project} onClick={()=>void start('test')}>
    <Play size={15}/>{!hasSetup || !ready ? tr('Налаштувати тест','Set up test') : settings.publish_workshop
      ? tr('Оновити локально + Workshop','Update locally + Workshop') : tr('Оновити локально','Update locally')}<kbd>F5</kbd></button>
  return <div className="app">
    <header className="titlebar" data-tauri-drag-region>
      <span className="brand" data-tauri-drag-region><Box size={15}/> DayZ Mod Studio <small>2.2</small></span>
      {project&&<span className="title-context" data-tauri-drag-region>{nameOf(project.root)} · {ready?tr('Готовий до збірки','Ready to build'):tr('Потрібне налаштування','Setup needed')}</span>}
      <div className="segments" aria-label={tr('Мова','Language')}>
        <button aria-pressed={lng==='uk'} onClick={()=>void changePrefs({language:'uk'})}>UA</button>
        <button aria-pressed={lng==='en'} onClick={()=>void changePrefs({language:'en'})}>EN</button>
      </div>
      <div className="window-buttons">
        <button aria-label={tr('Згорнути','Minimize')} onClick={()=>void desktop.minimize()}><Minus size={15}/></button>
        <button aria-label={tr('Розмір вікна','Resize window')} onClick={()=>void desktop.toggleMaximize()}><Square size={13}/></button>
        <button aria-label={tr('Закрити','Close')} disabled={busy} onClick={()=>void desktop.close()}><X size={16}/></button>
      </div>
    </header>
    <div className="toolbar">
      <Menu className="project-switch" disabled={busy} label={<><FolderOpen size={16}/><span className="project-caption" title={project?.root}><strong>{project?nameOf(project.root):tr('Вибрати проєкт','Choose a project')}</strong>{project&&<small>{project.root}</small>}</span></>}>
        {close=><>{prefs.projects.map(path=><button key={path} title={path} onClick={()=>{close();void loadProject(path).catch(flagError)}}><Folders size={15}/><span>{nameOf(path)}</span>{path===project?.root&&<span className="muted"> •</span>}</button>)}
          <button onClick={()=>{close();void chooseProject()}}><Plus size={15}/>{tr('Відкрити папку…','Open folder…')}</button></>}
      </Menu>
      {project&&<Status tone={busy?'active':ready?'good':'warn'}>{busy?tr('Виконується','Working'):ready?tr('Середовище готове','Environment ready'):tr('Потрібне налаштування','Setup needed')}</Status>}
      <div className="toolbar-actions ml-auto"><button disabled={busy} onClick={()=>void chooseProject()}><FolderOpen size={14}/><span>{tr('Відкрити папку','Open folder')}</span></button>
      </div>
    </div>
    <div className="workspace">
      <nav aria-label={tr('Розділи','Sections')}>{pages.map(([key,uk,en],index)=>{
        const Icon=navIcons[index]
        return <button key={key} aria-current={page===key?'page':undefined} title={tr(uk,en)} onClick={()=>setPage(key)}><Icon size={16}/><span>{tr(uk,en)}</span></button>
      })}</nav>
      <main key={page} className={page==='build'&&project?'build-main':undefined}>
        {!(page==='build'&&project)&&<h1>{tr(title[1],title[2])}</h1>}
        {notice && <div role="status" className="notice"><span>{notice}</span><button onClick={()=>setNotice('')} aria-label={tr('Закрити повідомлення','Dismiss message')}>×</button></div>}
        {page==='projects' && <div className="grid gap-2">{prefs.projects.map(path=><button className="project-card" key={path} disabled={busy} onClick={()=>void loadProject(path).catch(flagError)}><strong>{nameOf(path)}</strong><small>{path}</small></button>)}
          <button className="justify-self-start" disabled={busy} onClick={()=>void chooseProject()}><Plus size={15}/>{tr('Додати проєкт','Add project')}</button></div>}
        {!project && !['projects','settings','models'].includes(page) && <div className="empty"><h2>{tr('Відкрий папку мода','Open a mod folder')}</h2><p>{tr('Майстер допоможе підготувати першу збірку.','The setup wizard will prepare your first build.')}</p><button className="primary" onClick={()=>void chooseProject()}>{tr('Вибрати папку','Choose folder')}</button></div>}
        {page==='models' && <Suspense fallback={<p role="status">{tr('Завантажую перегляд…', 'Loading preview…')}</p>}><Models language={lng} root={project?.root} settings={settings}/></Suspense>}
        {project && page==='overview' && <>
          <div className="overview-head">
            <div className="min-w-0"><h2>{nameOf(project.root)}</h2><small className="path" title={project.root}>{project.root}</small></div>
            <div className="flex flex-wrap gap-2">
              {startButton}
              <button className="primary" disabled={busy || !settings.remote_host || !project.details.remoteChoice.buildId} onClick={()=>void start('remote')}>
                <Server size={15}/>{settings.remote_files_only ? tr('Завантажити пакет через SFTP','Upload package via SFTP') : tr('Оновити віддалений сервер','Update remote server')}<kbd>F6</kbd>
              </button>
            </div>
          </div>
          <details className="terminal-commands" open>
            <summary><Terminal size={15}/>{tr('Команди PowerShell','PowerShell commands')}</summary>
            {(settingsDirty || !project.configured) &&
              <small>{tr('Під час копіювання налаштування буде збережено для термінала.',
                'Copying saves the current settings for the terminal.')}</small>}
            <label>F5 · {tr('Оновити локально','Update locally')}{settings.publish_workshop && ' + Workshop'}</label>
            {commandLine('update')}
            <label>F6 · {tr('Розгорнути вибрану збірку','Deploy selected build')}</label>
            {project.details.commands.remote ? commandLine('remote') :
              <small>{tr('Команда з’явиться після перевірки першої збірки через F5.',
                'The command appears after F5 verifies the first build.')}</small>}
            <label>
              {tr('Інша дія','Other action')}
              <select value={terminalAction} onChange={event=>setTerminalAction(event.target.value)}>
                {Object.keys(project.details.commands).filter(action=>action!=='update'&&action!=='remote').map(action=>
                  <option key={action} value={action}>{action}</option>)}
              </select>
            </label>
            {commandLine(terminalAction)}
          </details>
          <div className="workflow-next">
            <strong>{tr('Далі','Next')}</strong>
            <span>{busy?stageText:!ready?tr('Перевір середовище й виправ позначені налаштування.','Review the environment and fix the flagged settings.'):
              project.details.operations[0]?.status==='failed'
                ? project.details.retry?tr('Переглянь причину й продовж з перевіреного пакета.','Review the cause and resume from the verified package.'):tr('Переглянь причину помилки та повтори дію.','Review the error and retry.')
                : project.details.operations[0]?.connected?tr('Перевір зміни у грі. Після редагування знову натисни F5.','Check your changes in game. Press F5 again after editing.')
                : project.details.deployment?tr('Запусти тест із уже встановленої збірки або натисни F5 для нового циклу.','Launch the deployed build or press F5 for a new cycle.')
                : tr('F5 збере мод, оновить локальні копії та перевірить запуск сервера.','F5 builds the mod, updates its local copies and checks that the server starts.')}</span>
          </div>
          <div className="build-stages">
            {workflowRow(tr('Вихідні файли','Sources'), project.details.sourcesChanged === true
              ? tr('Є нові зміни','Changes since the last local build') : project.details.sourcesChanged === false
              ? tr('Відповідають локальній збірці','Match the last local build') : tr('Відбиток ще не звірено','Fingerprint unavailable'),
              project.details.sourcesChanged === false ? 'ready' : 'pending')}
            {workflowRow(tr('Локальний сервер','Local server'),
              project.details.localBuild.buildId ? [tr('Остання відома збірка','Last known build'), project.details.localBuild.buildId, project.details.localBuild.date && new Date(project.details.localBuild.date).toLocaleString()].filter(Boolean).join(' · ') : '—',
              project.details.localBuild.buildId ? 'known' : 'pending')}
            {workflowRow('Workshop',
              [project.details.published.buildId, project.details.published.date && new Date(project.details.published.date).toLocaleString(), project.details.published.changed && tr('Є нові зміни','Newer source changes')].filter(Boolean).join(' · ') || '—',
              project.details.published.buildId ? 'confirmed' : 'pending',
              project.details.publication.status === 'failed' ? <button disabled={busy} onClick={()=>void start('retry-publish')}>{tr('Повторити публікацію','Retry publication')} · {project.details.publication.buildId}</button>
                : ['pending','uncertain'].includes(project.details.publication.status || '') ? <span>{tr('Перевір результат у Steam','Check the result in Steam')} · {project.details.publication.buildId}</span> : undefined)}
            {workflowRow(tr('Віддалений сервер','Remote server'),
              project.details.remoteBuild.buildId ? [project.details.remoteBuild.buildId, project.details.remoteBuild.date && new Date(project.details.remoteBuild.date).toLocaleString(), project.details.remoteBuild.changed && tr('Є нові зміни','Newer source changes')].filter(Boolean).join(' · ') : '—',
              project.details.remoteBuild.buildId ? 'known' : 'pending',
              project.details.remoteChoice.buildId ? <span>F6 · {project.details.remoteChoice.buildId}
                {project.details.remoteChoice.changed && <small>{tr('Для нових змін натисни F5','Use F5 to include newer changes')}</small>}</span>
                : <button disabled={busy} onClick={()=>{setSettingsGroup(5);setPage('settings')}}>{tr('Налаштування','Settings')}</button>)}
          </div>
          <details><summary>{tr('Додаткові дії','Additional actions')}</summary>
            <div className="flex flex-wrap gap-2">
              <button disabled={busy} onClick={()=>void start('build')}>{tr('Лише зібрати','Build only')}</button>
              <button disabled={busy||!ready||!project.details.packageReady} onClick={()=>void start('deploy')}>{tr('Лише встановити','Install only')}</button>
              <button disabled={busy||!ready||!project.details.deployment} onClick={()=>void start('launch')}>{tr('Лише запустити','Launch only')}</button>
              <button disabled={busy||!project.details.localBuild.buildId||project.details.sourcesChanged!==false||!settings.workshop} onClick={()=>setConfirmation('publish')}>{tr('Опублікувати вручну','Publish manually')} · {project.details.localBuild.buildId || '—'}</button>
              <button disabled={busy||!project.details.rollback} onClick={()=>setConfirmation('rollback')}>{tr('Відкотити','Roll back')}</button>
            </div>
          </details>
          <div className="overview-grid">
            <section><div className="section-header"><h2><Activity size={16}/>{tr('Готовність середовища','Environment readiness')}</h2>
              <button className="icon-button" aria-label={tr('Перевірити','Refresh')} title={tr('Перевірити','Refresh')} disabled={busy} onClick={()=>void refresh().catch(flagError)}><RefreshCw size={15}/></button></div>{readiness()}</section>
            <section><div className="section-header"><h2><Gauge size={16}/>{tr('Локальне тестування','Local testing')}</h2></div>
              <div className="data-row"><Server size={15}/><div className="grow"><strong>{tr('Сервер','Server')}</strong><small>{serverState}</small></div><i className={'dot '+(live==='ready'?'online':'')}/></div>
              <div className="data-row"><Monitor size={15}/><div className="grow"><strong>{tr('Клієнт','Client')}</strong><small>{clientState}</small></div></div>
              <div className="data-row"><Box size={15}/><div className="grow"><strong>{tr('Остання збірка','Latest build')}</strong><small>{project.details.builds[0]?.name||tr('Ще немає','None yet')}</small></div>
                <button className="icon-button" aria-label={tr('Збірки','Builds')} onClick={()=>setPage('build')}><ChevronRight size={16}/></button></div>
            </section>
          </div>
          {!busy && (selectedReport ? operation(selectedReport) : project.details.operations[0] && operation(project.details.operations[0]))}
          <div className="section-header mt-3"><button className="subtle" disabled={busy} onClick={()=>setWizard(0)}><CircleHelp size={15}/>{tr('Майстер налаштування','Setup wizard')}</button>
            <button className="subtle" onClick={()=>{setSettingsGroup(2);setPage('settings')}}>{tr('Залежності','Dependencies')}<ArrowUpRight size={14}/></button></div>
          {!!project.details.operations.length && <details><summary><ClipboardList size={15}/>{tr('Останні операції','Recent operations')}</summary>
            {project.details.operations.map(item=><button className="project-card" key={item.date} onClick={()=>setSelectedReport(item)}>
              {new Date(item.date).toLocaleString(lng==='uk'?'uk-UA':'en-US')} · {local(operationNames[item.action])} · {item.status==='complete'?tr('Завершено','Complete'):tr('Помилка','Failed')}
            </button>)}</details>}
        </>}
        {project && page==='build' && <>
          <div className="build-heading">
            <div className="min-w-0">
              <h1>{tr('Конвеєр збірки','Build pipeline')}: {nameOf(project.root)}</h1>
              <div className="build-tags">
                <Status tone={busy?'active':lastBuild?.status==='complete'?'good':lastBuild?'warn':'neutral'}>
                  {busy?stageText:lastBuild?lastBuild.status==='complete'?tr('Операцію завершено','Operation complete'):tr('Потрібна увага','Needs attention'):tr('Збірку ще не запускали','No build yet')}
                </Status>
                <span title={String(settings.tools)}>{tr('Збирач','Builder')} · AddonBuilder</span>
              </div>
              <p>{tr('Папка мода','Mod folder')}: {String(settings.mod)} · {tr('Тестовий порт','Test port')}: {String(settings.port)}</p>
            </div>
            <div className="build-actions">
              <button className="icon-button" title={tr('Параметри збірки','Build settings')} aria-label={tr('Параметри збірки','Build settings')} onClick={()=>{setSettingsGroup(0);setPage('settings')}}><ListFilter size={16}/></button>
            </div>
          </div>
          <div className="build-metrics">
            <span>{tr('ЧАС','TIME')}: <b>{lastBuild?lastBuild.seconds+' s':'—'}</b></span>
            <span>PBO: <b>{latestPackage?.count??'—'}</b></span>
            <span>{tr('ПОПЕРЕДЖЕННЯ','WARNINGS')}: <b className={lastBuild?.warnings?'warning':''}>{lastBuild?.warnings??'—'}</b></span>
            <span>{tr('ПІДПИС','SIGNATURE')}: <b>{latestPackage?.signed?tr('Перевірено','Verified'):settings.sign?'—':tr('Вимкнено','Disabled')}</b></span>
          </div>
          <div className="build-stages">{[[tr('Підготовка й пакування PBO','Preflight and PBO packaging'),tr('Перевірка джерел і збірка AddonBuilder','Source checks and AddonBuilder')],
            [tr('Цифровий підпис','Digital signature'),'DSSignFile · DSCheckSignatures'],
            [tr('Розгортання в тестове середовище','Deploy to the test environment'),tr('Резервні копії, сервер і клієнт','Backups, server and client')],
            [tr('Запуск і перевірка сервера','Start and verify the server'),tr('Місія й ігровий порт','Mission and game port')],
            [tr('Запуск клієнта','Launch client'),tr('Опціональний запуск DayZ','Optional DayZ launch')]].map(([title,hint],index)=>{
            const number=index+1
            const verified=lastBuild&&[lastBuild.built,lastBuild.signed,lastBuild.installed,lastBuild.serverReady,lastBuild.clientLaunched][index]
            const running=busy&&run?.stage===number
            const disabled=number===2&&!settings.sign
            const failure=!busy&&!verified&&lastBuild?.status==='failed'&&lastBuild.phase===number
            const complete=!busy&&!disabled&&verified
            return <div className="build-stage" key={title}>
              <span className={'step '+(complete?'done':'')}>{number}</span><strong>{title}</strong><small title={hint}>{hint}</small>
              <Status tone={running?'active':disabled?'neutral':complete?'good':failure?'warn':'neutral'}>
                {running?tr('Виконується','Running'):disabled?tr('Вимкнено','Disabled'):complete?tr('Підтверджено','Verified'):failure?tr('Зупинилося тут','Stopped here'):tr('Очікує','Pending')}
              </Status>
            </div>
          })}</div>
          {!!lastBuild?.error&&!busy&&<div className="notice bad">{lastBuild.error}{project.details.retry&&<button onClick={()=>void start('retry')}>{tr('Продовжити','Resume')}</button>}</div>}
          <button className="subtle" onClick={()=>setShowLog(!showLog)}><Terminal size={15}/>{tr('Журнал операцій','Operation log')}</button>
          <details className="build-history"><summary>{tr('Історія збірок','Build history')} ({project.details.builds.length})</summary>
            {project.details.builds.map(build=><button key={build.path} className="project-card" onClick={()=>void reveal(build.path)}><strong>{build.name}</strong><small>{build.count} PBO · {build.signed?tr('Підписано','Signed'):tr('Без підпису','Unsigned')}</small></button>)}
          </details>
        </>}
        {project && page==='server' && <>
          <section><div className="section-header"><h2>{tr('Активний профіль','Active profile')}</h2><Status tone={live==='ready'?'good':'neutral'}>{serverState}</Status></div>
          {['config','profiles','client_profiles','port'].map(key=><div className="check" key={key}><strong>{tr(fields[key][0],fields[key][1])}</strong><small>{String(settings[key] || tr('Типове значення','Default'))}</small></div>)}</section>
          <section><div className="section-header"><h2>{tr('Резервні копії','Backups')}</h2></div>
          {!project.details.backups.length&&<p>{tr('Копії з’являться після першого локального встановлення.','Backups appear after the first local deployment.')}</p>}
          {project.details.backups.map(path=><button className="project-card" key={path} onClick={()=>void reveal(path)}>{nameOf(path)}</button>)}</section>
        </>}
        {project && page==='workshop' && <section><h2>Workshop · {(checkedItem?.input === settings.workshop && checkedItem?.title) || String(settings.workshop_title || settings.workshop || '—')}</h2>
          <p>{project.details.published.buildId ? tr('Остання підтверджена публікація','Last confirmed publication') + ' · ' + project.details.published.buildId : tr('Публікацію ще не підтверджено','Awaiting confirmed publication')}</p>
          {(!settings.workshop || project.details.workshopDraft.status) && <fieldset disabled={busy}>
            {form(['workshop_title','workshop_description','workshop_preview','workshop_visibility'])}
            <button className="primary" disabled={project.details.sourcesChanged !== false || !settings.steam_owner
              || (!!project.details.workshopDraft.status && !project.details.workshopDraft.item && !settings.workshop)} onClick={()=>setConfirmation('create-workshop')}>
              {project.details.workshopDraft.status ? tr('Завершити першу публікацію','Finish first publication') : tr('Створити item і опублікувати','Create and publish item')}
            </button>
            {project.details.workshopDraft.status && !project.details.workshopDraft.item &&
              <p>{tr('Перевір у Steam, чи створено item, і збережи його ID в налаштуваннях.','Check Steam for the created item and save its ID in settings.')}</p>}
          </fieldset>}
          <button className="subtle" onClick={()=>{setSettingsGroup(4);setPage('settings')}}><Settings2 size={15}/>{tr('Налаштування Workshop','Workshop settings')}</button>
        </section>}
        {page==='settings' && <>
          <div className="settings-top">
            <div className="segments">
              <button aria-pressed={prefs.theme==='dark'} onClick={()=>void changePrefs({theme:'dark'})}>{tr('Темна','Dark')}</button>
              <button aria-pressed={prefs.theme==='light'} onClick={()=>void changePrefs({theme:'light'})}>{tr('Світла','Light')}</button>
            </div>
            {project&&<button className="primary" disabled={busy} onClick={()=>void saveSettings()}>{tr('Зберегти','Save')}</button>}
          </div>
          {project&&<fieldset disabled={busy}>
            <div className="setting-tabs" aria-label={tr('Групи налаштувань','Settings groups')}>
              {[groups[0].title,groups[1].title,[tr('Залежності','Dependencies'),tr('Залежності','Dependencies')] as const,groups[2].title,groups[3].title,groups[4].title].map((title,index)=>
                <button key={index} aria-pressed={settingsGroup===index} onClick={()=>setSettingsGroup(index)}>{local(title)}</button>)}
            </div>
            <section>
              {settingsGroup===2 ? dependencies() : (()=>{const group=groups[settingsGroup>2?settingsGroup-1:settingsGroup]
                const keys=group.basic.filter(key=>key!=='base' && !(settings.remote_files_only && ['remote_keys','remote_service','remote_readiness'].includes(key)))
                return form(advanced?[...keys,...group.advanced]:keys)})()}
            </section>
            <div className="settings-top">
              <label className="flex gap-2 items-center"><input type="checkbox" checked={advanced} onChange={e=>setAdvanced(e.target.checked)}/>{tr('Розширені параметри','Advanced settings')}</label>
              {settingsGroup===1&&<button onClick={()=>void detect()}>{tr('Знайти DayZ','Detect DayZ')}</button>}
              {settingsGroup===3&&<div className="flex flex-wrap gap-2">
                <input aria-label={tr('Назва нової пари ключів','New key pair name')} placeholder={tr('Назва нової пари ключів','New key pair name')} value={keyName} onChange={e=>setKeyName(e.target.value)}/>
                <button disabled={!keyName.trim()} onClick={()=>void generateKeys()}>{tr('Створити пару ключів','Generate key pair')}</button>
              </div>}
              {settingsGroup===4&&<button onClick={()=>void steamOwner()}>{tr('Визначити SteamID64','Get active SteamID64')}</button>}
              {settingsGroup===4&&<button disabled={!settings.workshop} onClick={()=>void checkWorkshop()}>{tr('Перевірити item','Check item')}</button>}
              {settingsGroup===4&&checkedItem?.input===settings.workshop&&checkedItem?.title&&<strong>{checkedItem.title}</strong>}
              {settingsGroup===5&&<button disabled={busy} onClick={()=>void start('remote-check')}>{tr('Перевірити підключення','Check connection')}</button>}
            </div>
            {settingsGroup===4&&commandLine('workshop-check')}
            {settingsGroup===5&&commandLine('remote-check')}
          </fieldset>}
        </>}
      </main>
    </div>
    <footer>
      <LogDrawer open={showLog} toggle={()=>setShowLog(false)} entries={entries} logs={project?.details.logs||[]} busy={busy} read={path=>void readLog(path)} tr={tr}/>
      <div className="footer-row"><span aria-live="polite">{stageText}</span>
        {busy&&<progress aria-label={tr('Прогрес операції','Operation progress')} max={5} value={run?.stage??0}/>}
        <button className="subtle ml-auto" aria-expanded={showLog} onClick={()=>setShowLog(!showLog)}><Terminal size={15}/>{tr('Деталі','Details')}</button></div>
    </footer>
    {(wizard !== undefined || confirmation) && <div className="overlay" onKeyDown={e=>{if(e.key==='Escape'){setWizard(undefined);setConfirmation(undefined)}}}><div role="dialog" aria-modal="true" aria-label={tr('Налаштування або підтвердження','Setup or confirmation')} className="modal">
      {wizard !== undefined ? <>
        <p>{tr('Це середовище можна використовувати для всіх проєктів.','Reuse this environment for all your projects.')}</p>
        <h2>{wizard+1}/4 · {setupGroup && wizard<3 ? local(setupGroup.title) : tr('Перевірка готовності','Readiness check')}</h2>
        <div className="modal-content">{wizard<3 && setupGroup ? form(wizard===1 ? [...setupGroup.basic,'client_mods_root'] : setupGroup.basic) : readiness()}</div>
        <div className="modal-actions"><button autoFocus onClick={()=>setWizard(undefined)}>{tr('Скасувати','Cancel')}</button>{wizard===0 && <button onClick={()=>void detect()}>{tr('Знайти DayZ','Detect DayZ')}</button>}
          {wizard>0 && <button onClick={()=>setWizard(wizard-1)}>{tr('Назад','Back')}</button>}
          {wizard<3 ? <button className="primary" onClick={()=>{setWizard(wizard+1);if(wizard===2)void refresh().catch(flagError)}}>{tr('Далі','Next')}</button> :
          <button className="primary" disabled={project?.details.checks.some(check=>!check.ok)} onClick={()=>void saveSettings()}>{tr('Зберегти','Save')}</button>}</div>
      </> : <>
        <h2>{confirmation && local(operationNames[confirmation])}</h2>
        <p>{confirmation==='publish'? 'Workshop · '+String(settings.workshop) + ' · ' + project?.details.localBuild.buildId
          : confirmation==='create-workshop' ? String(settings.workshop_title || '') + ' · ' + (project?.details.localBuild.buildId || '')
          : tr('Тестове середовище зупиниться, щоб відновити файли мода.','The test environment will stop before the previous mod files are restored.')}</p>
        <div className="modal-actions"><button autoFocus onClick={()=>setConfirmation(undefined)}>{tr('Скасувати','Cancel')}</button><button className="primary" onClick={()=>confirmation&&void start(confirmation)}>{tr('Підтвердити','Confirm')}</button></div>
      </>}
    </div></div>}
  </div>
}
createRoot(document.getElementById('root')!).render(<App/>)
