import { Activity, ArrowUpRight, Box, ChevronRight, CircleHelp, ClipboardList, CloudUpload, FolderOpen, Folders, Gauge, ListFilter, Minus, Monitor, Play, Plus, RefreshCw, Server, Settings2, Square, Terminal, Trash2, X } from 'lucide-react'
import { LogDrawer, Menu, Status } from './ui'
import { useEffect, useState, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { getCurrentWindow } from '@tauri-apps/api/window'
import { open } from '@tauri-apps/plugin-dialog'
import { call, type Details, type Message, type Operation, type Project, type Settings } from './backend'
import { checks, fields, hints, pages, phases, type Lang, type Page } from './locale'
import './style.css'

type Prefs = { language: Lang; theme: 'dark' | 'light'; projects: string[] }
type Action = 'deploy' | 'launch' | 'retry' | 'build' | 'test' | 'rollback' | 'publish'
fields.client_mods_root = ['Локальна папка тестових модів', 'Local test mod folder', 'folder']
fields.connection_timeout = ['Час очікування підключення, с', 'Connection timeout, seconds', '']
fields.environment_override = ['Окреме середовище лише для цього проєкту', 'Use a different environment for this project', 'bool']
hints.client_mods_root = ['Вибери папку поза каталогом завантажень Steam. Порожнє поле використовує папку клієнта.',
  'Choose a folder outside Steam downloads. Leaving this blank uses the client folder.']
hints.base = ['Одна папка або Workshop ID на рядок. Сервер і клієнт завантажують ту саму локальну версію.',
  'One directory or Workshop ID per line. The server and client load the same local version.']
const groups = [
  { title: ['Джерело й інструменти', 'Source and tools'], basic: ['addons','mod'], advanced: ['pack','addon_name','prefix','metadata','extra','prep_exe','prep_args'] },
  { title: ['Тестове середовище', 'Test environment'], basic: ['tools','server','client','config','base'], advanced: ['profiles','client_profiles','port','server_only','server_exe','client_exe','address','timeout','shared','separate','server_args','client_args','client_mods_root','connection_timeout','environment_override'] },
  { title: ['Підпис', 'Signing'], basic: ['sign','private','public'], advanced: [] },
  { title: ['Steam Workshop', 'Steam Workshop'], basic: ['workshop','steam_owner','notes'], advanced: [] },
] as const

const defaultPrefs: Prefs = { language: 'uk', theme: 'dark', projects: [] }
const nameOf = (path: string) => path.split(/[\\/]/).pop() || path
const isError = (line: string) => /\[ERROR\]|\(E\):|can't compile|\b(error|fatal|failed)\s*:/i.test(line)
const desktop = getCurrentWindow()

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
  const lng = prefs.language
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
      setProject({...project, configured: true, details})
      setHasEnvironment(true)
      setNotice(tr('Налаштування збережено.', 'Settings saved.'))
      setWizard(undefined)
    } catch (error) { flagError(error) }
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
  async function start(action: Action) {
    if (!project || busy) return
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
      const details = await call<Details>(lng, 'run', {root: project.root, settings, action}, message => {
        if (message.event === 'log' && message.text) {
          const text = message.text
          setEntries(previous => [...previous.slice(-2999), {text, error: isError(text)}])
        }
        if (message.event === 'progress') setRun({action, stage: message.stage ?? 0, label: message.label})
      })
      setProject({...project, configured: true, details})
      setHasEnvironment(true)
      setSelectedReport(details.operations[0])
      setRun(previous => previous && {...previous, done: details.operations[0]?.status === 'complete'})
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
      if (event.key === 'F5') {
        event.preventDefault()
        if (!event.repeat && wizard === undefined && !confirmation) void start('test')
      }
    }
    window.addEventListener('keydown', keyboard)
    return () => window.removeEventListener('keydown', keyboard)
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
    const rows=['base','server_only'].flatMap(key=>String(settings[key]||'').split(/\r?\n/).map(path=>path.trim()).filter(Boolean).map(path=>({path,key})))
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
      {rows.length ? rows.map(({path,key})=><div className="data-row" key={key+path}>
        <Box size={15}/><div className="min-w-0 grow"><strong title={path}>{nameOf(path)}</strong><small>{path}</small></div>
        <span className="muted nowrap">{key==='base'?tr('Спільна','Shared'):tr('Серверна','Server only')}</span>
        <button className="icon-button" title={tr('Видалити','Remove')} aria-label={tr('Видалити','Remove')} onClick={()=>change(key,path,true)}><Trash2 size={15}/></button>
      </div>) : <p className="muted">{tr('Додаткових модів у запуску немає.','No additional mods in the launch list.')}</p>}
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
    rollback:['Відкат','Rollback'], publish:['Оновлення Workshop','Workshop update']
  }
  function operation(report: Operation) {
    const test = ['test','retry','deploy','launch'].includes(report.action)
    const failed = report.status==='failed'
    const phase = report.phase > 0 ? local(phases[report.phase-1]) : tr('Підготовка','Preflight')
    return <section className="report">
      <h2>{local(operationNames[report.action])} · {failed?(report.attention?tr('Потребує уваги','Needs attention'):tr('Помилка','Error')):tr('Завершено','Complete')}</h2>
      <p>{report.seconds} {tr('с','s')} · {tr('Попереджень у журналі','Warnings in log')}: {report.warnings}</p>
      {report.built && <p>{tr('Пакет перевірено','Package verified')} · {report.signed?tr('підпис перевірено','signature verified'):tr('без підпису','unsigned')}</p>}
      {test && <div className="grid gap-1 mb-3">
        <div>{tr('Мод','Mod')}: {report.installed?tr('копії перевірено','copies verified'):tr('оновлення не підтверджено','update not verified')}</div>
        <div>{tr('Сервер','Server')}: {report.serverReady?tr('місія й порт підтверджені','mission and port confirmed'):tr('готовність не підтверджена','readiness not confirmed')}</div>
        <div>{tr('Клієнт','Client')}: {report.connected?tr('сервер підтвердив підключення','connection confirmed by the server'):
          report.clientLaunched?tr('запущено, підключення не підтверджене','launched, connection not confirmed'):tr('не запускали','not launched')}</div>
      </div>}
      {failed && <p className="bad">{test ? phase + ' · ' : ''}{report.error}</p>}
      {test && report.connected && <p>{tr('Перейди в гру та перевір поведінку мода.','Switch to the game and check how the mod behaves.')}</p>}
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
    </section>
  }
  const title = pages.find(item=>item[0]===page)!
  const stageText = !run ? tr('Готово', 'Ready') : run.done === false ? tr('Операція завершилася помилкою', 'Operation failed') :
    run.done ? tr('Операцію завершено', 'Operation complete') : Array.isArray(run.label) ? local(run.label) :
    run.label || tr('Перевірка середовища…', 'Checking environment…')
  const setupGroup = wizard === undefined ? undefined : groups[wizard]
  const ready = !!project && (project.configured || hasEnvironment) && project.details.checks.length>0 && project.details.checks.every(check=>check.ok)
  const lastTest = project?.details.operations.find(item=>['test','retry','launch'].includes(item.action))
  const navIcons = [Gauge,Folders,Box,Server,CloudUpload,Settings2]
  const serverState = live==='ready' ? tr('Порт активний','Listening') : live==='offline' ? tr('Не запущено','Stopped') : tr('Немає підтвердження','Unverified')
  const clientState = lastTest?.connected ? tr('Вхід підтверджено в останньому тесті','Connected in last test') :
    lastTest?.clientLaunched ? tr('Вхід не підтверджено','Connection unverified') : tr('Ще не перевірено','Not tested')
  const hasSetup = project?.configured || hasEnvironment
  const lastBuild=project?.details.operations.find(item=>['test','retry','build','deploy','launch'].includes(item.action))
  const latestPackage=project?.details.builds[0]
  function workflowRow(title:string, description:string, state:string, action?:ReactNode) {
    const labels: Record<string,[string,string]> = {pending:['Очікує','Pending'],running:['Виконується','Running'],
      ready:['Готово','Ready'],skipped:['Пропущено','Skipped'],error:['Помилка','Error'],attention:['Потребує уваги','Needs attention']}
    return <div className="workflow-row" key={title}><div><strong>{title}</strong><small>{description}</small></div>
      <Status tone={state==='ready'?'good':state==='running'?'active':state==='error'||state==='attention'?'warn':'neutral'}>{local(labels[state])}</Status>
      <div>{action}</div></div>
  }
  const startButton = <button className="primary" disabled={busy || !project} onClick={()=>void start('test')}>
    <Play size={15}/>{!hasSetup || !ready ? tr('Налаштувати тест','Set up test') : tr('Зібрати та протестувати','Build and test')}<kbd>F5</kbd></button>
  return <div className="app">
    <header className="titlebar" data-tauri-drag-region>
      <span className="brand" data-tauri-drag-region><Box size={15}/> DayZ Mod Studio <small>2.1</small></span>
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
      {project&&page!=='overview'&&startButton}</div>
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
        {!project && !['projects','settings'].includes(page) && <div className="empty"><h2>{tr('Відкрий папку мода','Open a mod folder')}</h2><p>{tr('Майстер допоможе підготувати першу збірку.','The setup wizard will prepare your first build.')}</p><button className="primary" onClick={()=>void chooseProject()}>{tr('Вибрати папку','Choose folder')}</button></div>}
        {project && page==='overview' && <>
          <div className="overview-head">
            <div className="min-w-0"><h2>{nameOf(project.root)}</h2><small className="path" title={project.root}>{project.root}</small></div>
            {startButton}
          </div>
          <div className="workflow-next">
            <strong>{tr('Далі','Next')}</strong>
            <span>{busy?stageText:!ready?tr('Перевір середовище й виправ позначені налаштування.','Review the environment and fix the flagged settings.'):
              project.details.operations[0]?.status==='failed'
                ? project.details.retry?tr('Переглянь причину й продовж з перевіреного пакета.','Review the cause and resume from the verified package.'):tr('Переглянь причину помилки та повтори дію.','Review the error and retry.')
                : project.details.operations[0]?.connected?tr('Перевір зміни у грі. Після редагування знову натисни F5.','Check your changes in game. Press F5 again after editing.')
                : project.details.deployment?tr('Запусти тест із уже встановленої збірки або натисни F5 для нового циклу.','Launch the deployed build or press F5 for a new cycle.')
                : tr('F5 збере мод, оновить локальні копії й запустить гру.','F5 builds the mod, updates its local copies and launches the game.')}</span>
          </div>
          <div className="build-stages" aria-label={tr('Робочий процес','Workflow')}>
            {workflowRow(tr('Проєкт','Project'),nameOf(project.root),'ready')}
            {workflowRow(tr('Перевірка готовності','Readiness check'),tr('Джерела, інструменти, ключі та локальні шляхи','Sources, tools, keys and local paths'),ready?'ready':'attention',
              <button disabled={busy} onClick={()=>ready?void refresh().catch(flagError):setWizard(0)}>{ready?tr('Перевірити','Refresh'):tr('Виправити','Fix setup')}</button>)}
            {phases.map((pair,index)=>{
              const number=index+1
              const check=lastBuild&&[lastBuild.built,lastBuild.signed,lastBuild.installed,lastBuild.serverReady,lastBuild.connected][index]
              const skipped=(number===2&&!settings.sign)||(!busy&&lastBuild?.status==='complete'&&(
                lastBuild.action==='build'&&number>=3||lastBuild.action==='deploy'&&number>=4))
              const applies=run&&['test','retry','build','deploy','launch'].includes(run.action)
              const status=skipped?'skipped':busy&&applies&&number===run.stage?'running':
                !busy&&check?'ready':!busy&&lastBuild?.status==='failed'&&lastBuild.phase===number?
                  lastBuild.attention?'attention':'error':'pending'
              const descriptions=[[tr('Пакує вихідні аддони.','Packages source addons.')],
                [tr('Перевіряє цифрові підписи.','Verifies digital signatures.')],
                [tr('Оновлює локальні копії з резервуванням.','Updates local copies with backups.')],
                [tr('Чекає на місію та UDP-порт.','Waits for the mission and UDP port.')],
                [tr('Перевіряє вхід за журналом сервера.','Checks connection in the server log.')]]
              const action=number===1?<button disabled={busy} onClick={()=>void start('build')}>{tr('Лише збірка','Build only')}</button>:
                number===3&&project.details.packageReady?<button disabled={busy||!ready} onClick={()=>void start('deploy')}>{tr('Встановити','Deploy')}</button>:
                number===4&&project.details.deployment?<button disabled={busy||!ready} onClick={()=>void start('launch')}>{tr('Запустити тест','Launch test')}</button>:null
              return workflowRow(local(pair),descriptions[index][0],status,action)
            })}
          </div>
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
              <button disabled={busy} onClick={()=>void start('build')}><Box size={15}/>{tr('Лише зібрати PBO','Build PBO only')}</button>
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
            [tr('Запуск клієнта й перевірка входу','Launch client and verify connection'),tr('Підтвердження за журналом сервера','Confirmation from the server log')]].map(([title,hint],index)=>{
            const number=index+1
            const verified=lastBuild&&[lastBuild.built,lastBuild.signed,lastBuild.installed,lastBuild.serverReady,lastBuild.connected][index]
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
          <div className="flex flex-wrap gap-2 mb-3">
            <button disabled={busy||!ready||!project.details.packageReady} onClick={()=>void start('deploy')}>{tr('Встановити перевірену збірку','Deploy verified build')}</button>
            <button disabled={busy||!ready||!project.details.deployment} onClick={()=>void start('launch')}>{tr('Запустити встановлену збірку','Launch installed build')}</button>
          </div>
          <section><div className="section-header"><h2>{tr('Резервні копії','Backups')}</h2><button disabled={busy || !project.details.rollback} onClick={()=>setConfirmation('rollback')}>{tr('Відкотити','Roll back')}</button></div>
          {!project.details.backups.length&&<p>{tr('Копії з’являться після першого локального встановлення.','Backups appear after the first local deployment.')}</p>}
          {project.details.backups.map(path=><button className="project-card" key={path} onClick={()=>void reveal(path)}>{nameOf(path)}</button>)}</section>
        </>}
        {project && page==='workshop' && <section><h2>Workshop ID · {String(settings.workshop || '—')}</h2>
          <p>{tr('Першу публікацію зроби вручну. Тут можна завантажити збірку, яка пройшла запуск сервера.','Publish the first release manually. Here you can upload a build that passed server startup.')}</p>
          {!settings.workshop&&<button className="subtle" onClick={()=>{setSettingsGroup(4);setPage('settings')}}><Settings2 size={15}/>{tr('Вказати Workshop ID','Set Workshop ID')}</button>}
          <button className="primary" disabled={busy || !project.details.tested || !/^\d+$/.test(String(settings.workshop)) || !/^\d+$/.test(String(settings.steam_owner))} onClick={()=>setConfirmation('publish')}>{tr('Оновити Workshop','Update Workshop')}</button>
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
              {[groups[0].title,groups[1].title,[tr('Залежності','Dependencies'),tr('Залежності','Dependencies')] as const,groups[2].title,groups[3].title].map((title,index)=>
                <button key={index} aria-pressed={settingsGroup===index} onClick={()=>setSettingsGroup(index)}>{local(title)}</button>)}
            </div>
            <section>
              {settingsGroup===2 ? dependencies() : (()=>{const group=groups[settingsGroup>2?settingsGroup-1:settingsGroup]
                const keys=group.basic.filter(key=>key!=='base')
                return form(advanced?[...keys,...group.advanced]:keys)})()}
            </section>
            <div className="settings-top">
              <label className="flex gap-2 items-center"><input type="checkbox" checked={advanced} onChange={e=>setAdvanced(e.target.checked)}/>{tr('Розширені параметри','Advanced settings')}</label>
              {settingsGroup===1&&<button onClick={()=>void detect()}>{tr('Знайти DayZ','Detect DayZ')}</button>}
            </div>
          </fieldset>}
        </>}
      </main>
    </div>
    <footer>
      <LogDrawer open={showLog} toggle={()=>setShowLog(false)} entries={entries} logs={project?.details.logs||[]} busy={busy} read={path=>void readLog(path)} tr={tr}/>
      <div className="footer-row"><span aria-live="polite">{stageText}</span>
        {busy&&<progress aria-label={tr('Прогрес операції','Operation progress')} max={5} value={run?.stage??0}/>}
        <button className="subtle ml-auto" aria-expanded={showLog} onClick={()=>setShowLog(!showLog)}><Terminal size={15}/>{tr('Журнал','Log')}</button></div>
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
        <h2>{confirmation==='publish'?tr('Оновити наявний item','Update existing item'):tr('Відновити попередню версію','Restore previous version')}</h2>
        <p>{confirmation==='publish'? 'Workshop ID · '+String(settings.workshop) : tr('Тестове середовище зупиниться, щоб відновити файли мода.','The test environment will stop before the previous mod files are restored.')}</p>
        <div className="modal-actions"><button autoFocus onClick={()=>setConfirmation(undefined)}>{tr('Скасувати','Cancel')}</button><button className="primary" onClick={()=>confirmation&&void start(confirmation)}>{tr('Підтвердити','Confirm')}</button></div>
      </>}
    </div></div>}
  </div>
}
createRoot(document.getElementById('root')!).render(<App/>)
