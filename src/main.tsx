import { Box, ClipboardList, CloudUpload, FolderOpen, Folders, Gauge, Image, ListFilter, Minus, Play, Plus, Server, Settings2, Square, Terminal, Trash2, X } from 'lucide-react'
import { LogDrawer, Menu, Status } from './ui'
import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { getCurrentWindow } from '@tauri-apps/api/window'
import { open } from '@tauri-apps/plugin-dialog'
import { call, type Details, type Message, type Operation, type Project, type RunResult, type Settings } from './backend'
import { checks, fields, hints, pages, phases, type Lang, type Page } from './locale'
import './style.css'

const Models = lazy(() => import('./models').then(module => ({ default: module.Models })))

const Textures = lazy(() => import('./textures').then(module => ({ default: module.Textures })))

type Prefs = { language: Lang; theme: 'dark' | 'light'; projects: string[] }
type Action = 'quick' | 'deploy' | 'launch' | 'retry' | 'build' | 'test' | 'rollback' | 'publish' | 'retry-publish' | 'remote' | 'remote-check' | 'create-workshop'
const quickToggles = ['copy_server', 'copy_client', 'sign']
type Addon = {path: string; name: string; prefix: string; declared: string}
type AddonOptions = Record<string, {name?: string; prefix?: string}>
const addonFolders = (settings: Settings) => String(settings.addons || '').split(/\r?\n/).map(folder => folder.trim()).filter(Boolean)
function getAddonOptions(settings: Settings): AddonOptions {
  try { return JSON.parse(String(settings.addon_options || '{}')) || {} }
  catch { return {} }
}
fields.addon_builder = ['Файл AddonBuilder.exe', 'AddonBuilder.exe path', 'file']
hints.addon_builder = ['Типово використовується Bin/AddonBuilder/AddonBuilder.exe з папки DayZ Tools.',
  'Defaults to Bin/AddonBuilder/AddonBuilder.exe within DayZ Tools.']
fields.copy_server = ['Копіювати на сервер', 'Copy to server', 'bool']
fields.copy_client = ['Копіювати на клієнт', 'Copy to client', 'bool']
fields.sign = ['Підписувати PBO', 'Sign PBO files', 'bool']
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
  { title: ['Джерело й інструменти', 'Source and tools'], basic: ['addons','mod'], advanced: ['pack','addon_builder','addon_name','prefix','metadata','extra','prep_exe','prep_args'] },
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
  const [mediaTool, setMediaTool] = useState<'models' | 'textures'>('models')
  const toolPage = page === 'media'
  const showModels = toolPage && mediaTool === 'models'
  const showTextures = toolPage && mediaTool === 'textures'
  const [modelsVisited, setModelsVisited] = useState(false)
  const [modelStatus, setModelStatus] = useState('')
  const [texturesVisited, setTexturesVisited] = useState(false)
  const [textureStatus, setTextureStatus] = useState('')
  useEffect(() => {
    if (showModels) setModelsVisited(true)
    if (showTextures) setTexturesVisited(true)
  }, [showModels, showTextures])
  const [project, setProject] = useState<Project>()
  const [settings, setSettings] = useState<Settings>({})
  const [operationBusy, setBusy] = useState(false)
  const running = useRef(false)
  const [addons, setAddons] = useState<Addon[]>([])
  const [projectLoading, setProjectLoading] = useState(true)
  const [workspace, setWorkspace] = useState<string>()
  const busy = operationBusy || projectLoading
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

  async function loadProject(root: string, preference = prefs, activate = true) {
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
    if (activate) setPage('overview')
    setWizard(found.configured ? undefined : 0)
    setKeyName(String(found.settings.mod || '').replace(/^@/, '').replace(/[^A-Za-z0-9_-]/g, '').slice(0, 48))
    const next = {...preference, projects: [found.root, ...preference.projects.filter(path => path !== found.root)].slice(0, 30)}
    setPrefs(next)
    await call(next.language, 'preferences', {value: next})
  }
  useEffect(() => {
    call<{interface: Partial<Prefs>; workspace: string; recent: string | null}>('uk', 'hello').then(async data => {
      const next = {...defaultPrefs, ...data.interface}
      setPrefs(next)
      setWorkspace(data.workspace)
      if (data.recent && data.recent !== data.workspace) {
        try {
          await loadProject(data.recent, next, false)
          return
        } catch (error) {
          await loadProject(data.workspace, next, false)
          flagError(error)
          return
        }
      }
      await loadProject(data.workspace, next, false)
    }).catch(flagError).finally(() => setProjectLoading(false))
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
  async function chooseProject(root?: string) {
    if (busy) return
    setProjectLoading(true)
    try {
      const folder = root ?? await open({directory: true, multiple: false, defaultPath: project?.root ?? workspace})
      if (typeof folder === 'string') await loadProject(folder)
    } catch (error) {
      flagError(error)
    } finally {
      setProjectLoading(false)
    }
  }
  async function stopSession(force: boolean) {
    if (!project || busy) return
    if (force && !window.confirm(tr('Примусово завершити сервер? Незбережений прогрес може втратитися.',
                                    'Force stop the server? Unsaved progress may be lost.'))) return
    setBusy(true)
    try {
      await call(lng, force ? 'forceStopServer' : 'stopServer', {root: project.root, settings})
      setNotice(force ? tr('Сервер завершено.','The server has stopped.') : tr('Тестову сесію зупинено.','The test session has stopped.'))
      await refresh()
    } catch (error) { flagError(error) }
    finally { setBusy(false) }
  }
  async function refresh(language = lng, next = settings) {
    if (!project) return
    const details = await call<Details>(language, 'details', {root: project.root, settings: next})
    setProject(previous => previous?.root === project.root ? {...previous, details} : previous)
  }
  async function saveSettings(setup = false) {
    if (!project || busy) return
    setBusy(true)
    try {
      const details = await call<Details>(lng, setup ? 'saveQuick' : 'save', {root: project.root, settings})
      setProject({...project, configured: true, settings, details})
      setNotice(tr('Налаштування збережено.', 'Settings saved.'))
      setWizard(undefined)
      if (setup) setPage('overview')
    } catch (error) { flagError(error) }
    finally { setBusy(false) }
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
    if (busy) return
    setBusy(true)
    try {
      const paths = await call<Settings>(lng, 'detect', {settings})
      const next = {...settings, ...paths}
      setSettings(next)
      setNotice(tr('Інсталяцій знайдено: ', 'Installations found: ') + Object.keys(paths).length)
    } catch (error) { flagError(error) }
    finally { setBusy(false) }
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
    if (!project || busy || running.current) return
    if (action === 'quick' && !project.configured) {
      setWizard(0)
      return
    }
    const buildId = action === 'remote' ? project.details.remoteChoice.buildId : undefined
    if (action === 'remote' && (!settings.remote_host || !buildId)) return
    if (action === 'test' && !ready) {
      setPage('server')
      setNotice(tr('Перевір налаштування тестового середовища.', 'Check the test environment settings.'))
      return
    }
    running.current = true
    setBusy(true)
    setConfirmation(undefined)
    setEntries([])
    setNotice('')
    setSelectedReport(undefined)
    setRun({action, stage: 0})
    if (action === 'quick') setPage('overview')
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
      setSelectedReport(details.currentOperation)
      setRun(previous => previous && {...previous, done: details.currentOperation.status === 'complete'})
      if (action === 'remote') setPage('server')
    } catch (error) {
      flagError(error)
      setEntries(previous => [...previous, {text: error instanceof Error ? error.message : String(error), error: true}])
      setRun(previous => previous && {...previous, done: false})
      await refresh().catch(() => undefined)
    } finally {
      running.current = false
      setBusy(false)
    }
  }
  useEffect(() => {
    const keyboard = (event: KeyboardEvent) => {
      if (event.key === 'F5' || event.key === 'F6') {
        event.preventDefault()
        if (!event.repeat && wizard === undefined && !confirmation) void start(event.key === 'F5' ? 'quick' : 'remote')
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
    if(!project || busy || page!=='server')return
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

  useEffect(() => {
    if (!project) return
    let active = true
    void call<Addon[]>(lng, 'addonInfo', {root: project.root, settings: {
      addons: settings.addons, addon_name: settings.addon_name, prefix: settings.prefix
    }}).then(value => { if (active) setAddons(value) }).catch(() => { if (active) setAddons([]) })
    return () => { active = false }
  }, [project?.root, settings.addons, settings.addon_name, settings.prefix, lng])

  async function scanAddons() {
    if (!project || busy) return
    setBusy(true)
    try {
      const found = await call<Addon[]>(lng, 'scanAddons', {root: project.root, settings})
      setSettings(previous => ({...previous, addons: found.map(item => item.path).join('\n')}))
      setNotice(found.length ? '' : tr('У цій папці не знайдено аддонів із config.cpp.',
                                       'No addons with config.cpp were found in this folder.'))
    } catch (error) { flagError(error) }
    finally { setBusy(false) }
  }

  function addonEditor() {
    const options = getAddonOptions(settings)
    const folders = addonFolders(settings)
    return <>
      {form(['addons', 'mod'])}
      <button type="button" onClick={() => void scanAddons()}>{tr('Знайти аддони', 'Detect addons')}</button>
      <div className="addon-list">
        {folders.map((folder, index) => {
          const info = addons.find(addon => addon.path === folder)
          const key = folder.replace(/\\/g, '/')
          const update = (field: 'name' | 'prefix', value: string) => setSettings(previous => {
            const existing = getAddonOptions(previous)
            return {...previous, addon_options: JSON.stringify({...existing, [key]: {...existing[key], [field]: value}})}
          })
          const inferredPrefix = options[key]?.name && info && !info.declared && info.prefix === info.name && !(folders.length === 1 && settings.prefix)
            ? options[key].name : info?.prefix
          return <div className="addon-row" key={folder + index}>
            <strong title={folder}>{folder}</strong>
            <label>{tr('Назва PBO', 'PBO name')}<input value={options[key]?.name ?? ''} placeholder={info?.name}
              onChange={event => update('name', event.target.value)}/></label>
            <label>{tr('Префікс', 'Prefix')}<input value={options[key]?.prefix ?? ''} placeholder={inferredPrefix}
              onChange={event => update('prefix', event.target.value)}/></label>
          </div>
        })}
      </div>
    </>
  }

  async function toggleQuick(key: string, checked: boolean) {
    if (!project || busy) return
    const next = {...settings, [key]: checked}
    setSettings(next)
    if (!project.configured) return
    try {
      await call(lng, 'saveQuickToggles', {root: project.root, [key]: checked})
      setProject(previous => previous?.root === project.root ? {...previous, settings: {...previous.settings, [key]: checked}} : previous)
    } catch (error) { flagError(error) }
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
    quick:['Швидка збірка','Quick build'], deploy:['Встановлення','Deployment'], launch:['Запуск тесту','Launch test'], test:['Тестування','Test'], retry:['Продовження тесту','Resume test'], build:['Збірка','Build'],
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
  const setupSteps = [
    tr('Вихідні файли та аддони', 'Source files and addons'),
    tr('DayZ Tools і папки встановлення', 'DayZ Tools and installation folders'),
    tr('Цифровий підпис', 'Digital signing')
  ]
  const ready = !!project && project.configured && project.details.checks.length>0 && project.details.checks.every(check=>check.ok)
  const navIcons = [Gauge,Folders,Box,Server,CloudUpload,Settings2,Image]
  const serverState = live==='ready' ? tr('Порт активний','Listening') : live==='offline' ? tr('Не запущено','Stopped') : tr('Немає підтвердження','Unverified')
  const lastBuild=project?.details.operations.find(item=>['test','retry','build','deploy','launch'].includes(item.action))
  const lastQuick=project?.details.operations.find(item=>item.action==='quick')
  const latestPackage=project?.details.builds[0]
  const quickActive = operationBusy && run?.action === 'quick'
  const quickPbos = lastQuick?.files.filter(name => name.toLowerCase().endsWith('.pbo')) ?? []
  const startButton = <button className="primary" disabled={busy || !project} onClick={()=>void start('quick')}>
    <Play size={15}/>{tr('Зібрати та встановити','Build and deploy')} <kbd>F5</kbd></button>
  const projectPaths = [...new Set(workspace ? [workspace, ...prefs.projects] : prefs.projects)]
  return <div className={toolPage ? 'app app-tool' : page === 'overview' ? 'app app-quick' : 'app'}>
    <header className="titlebar" data-tauri-drag-region>
      <span className="brand" data-tauri-drag-region><Box size={15}/> DayZ Mod Studio <small>2.3</small></span>
      <div className="segments" aria-label={tr('Мова','Language')}>
        <button disabled={projectLoading} aria-pressed={lng==='uk'} onClick={()=>void changePrefs({language:'uk'})}>UA</button>
        <button disabled={projectLoading} aria-pressed={lng==='en'} onClick={()=>void changePrefs({language:'en'})}>EN</button>
      </div>
      <div className="window-buttons">
        <button aria-label={tr('Згорнути','Minimize')} onClick={()=>void desktop.minimize()}><Minus size={15}/></button>
        <button aria-label={tr('Розмір вікна','Resize window')} onClick={()=>void desktop.toggleMaximize()}><Square size={13}/></button>
        <button aria-label={tr('Закрити','Close')} disabled={busy} onClick={()=>void desktop.close()}><X size={16}/></button>
      </div>
    </header>
    {!toolPage && page!=='overview' && <div className="toolbar">
      <Menu className="project-switch" disabled={busy} label={<><FolderOpen size={16}/><span className="project-caption" title={project?.root}><strong>{project?nameOf(project.root):tr('Вибрати проєкт','Choose a project')}</strong></span></>}>
        {close=><>{projectPaths.map(path=><button key={path} title={path} onClick={()=>{close();void chooseProject(path)}}><Folders size={15}/><span>{nameOf(path)}</span>{path===project?.root&&<span className="muted"> •</span>}</button>)}
          <button onClick={()=>{close();void chooseProject()}}><Plus size={15}/>{tr('Відкрити папку…','Open folder…')}</button></>}
      </Menu>
      {project&&<Status tone={busy?'active':ready?'good':'warn'}>{busy?tr('Виконується','Working'):ready?tr('Середовище готове','Environment ready'):tr('Потрібне налаштування','Setup needed')}</Status>}
      <div className="toolbar-actions ml-auto"><button disabled={busy} onClick={()=>void chooseProject()}><FolderOpen size={14}/><span>{tr('Відкрити папку','Open folder')}</span></button>
      </div>
    </div>}
    <div className="workspace">
      <nav aria-label={tr('Розділи','Sections')}>{pages.map(([key,uk,en],index)=>{
        const Icon=navIcons[index]
        return <button key={key} aria-current={page===key?'page':undefined} aria-label={tr(uk,en)} title={tr(uk,en)} onClick={()=>setPage(key)}><Icon size={16}/><span>{tr(uk,en)}</span></button>
      })}</nav>
      <main className={page==='build'&&project?'build-main':undefined}>
        {!(page==='build'&&project)&&<h1>{tr(title[1],title[2])}</h1>}
        {!toolPage && wizard === undefined && notice && !(page === 'overview' && run?.action === 'quick' && run.done === false) && <div role="status" className="notice"><span>{notice}</span><button onClick={()=>setNotice('')} aria-label={tr('Закрити повідомлення','Dismiss message')}>×</button></div>}
        {page==='projects' && <div className="grid gap-2">{projectPaths.map(path=><button className="project-card" key={path} disabled={busy} onClick={()=>void chooseProject(path)}><strong>{nameOf(path)}</strong><small>{path}</small></button>)}
          <button className="justify-self-start" disabled={busy} onClick={()=>void chooseProject()}><Plus size={15}/>{tr('Додати проєкт','Add project')}</button></div>}
        {!project && !['projects','settings','media'].includes(page) &&
          <div className="empty">
            <h2>{tr('Збірка мода','Mod build')}</h2>
            <p>{tr('Відкрий проєкт для збірки або перейди до конвертації файлів.', 'Open a project to build a mod, or switch to file conversion.')}</p>
            <div className="flex flex-wrap gap-2">
              <button className="primary" disabled={busy} onClick={()=>void chooseProject()}>{tr('Вибрати проєкт','Choose project')}</button>
              <button onClick={()=>setPage('media')}><Image size={15}/>{tr('Моделі й текстури','Models and textures')}</button>
            </div>
          </div>}
        {toolPage && <div className="media-tools" role="group" aria-label={tr('Інструменти конвертації','Conversion tools')}>
          <button aria-pressed={showModels} onClick={()=>setMediaTool('models')}><Box size={16}/>{tr('3D-моделі','3D models')}</button>
          <button aria-pressed={showTextures} onClick={()=>setMediaTool('textures')}><Image size={16}/>{tr('Конвертація текстур','Texture conversion')}</button>
        </div>}
        {(modelsVisited || showModels) && <div hidden={!showModels}>
          <Suspense fallback={<p role="status">{tr('Завантажую перегляд…', 'Loading preview…')}</p>}>
            <Models language={lng} root={project?.root} settings={settings} onStatus={setModelStatus}/>
          </Suspense>
        </div>}
        {(texturesVisited || showTextures) && <div hidden={!showTextures}>
          <Suspense fallback={<p role="status">{tr('Відкриваю текстури…', 'Loading textures…')}</p>}>
            <Textures language={lng} settings={settings} onStatus={setTextureStatus}/>
          </Suspense>
        </div>}
        {project && page==='overview' && <section className="quick-build">
          <div className="overview-head">
            <div className="min-w-0"><h2>{nameOf(project.root)}</h2><small className="path" title={project.root}>{project.root}</small></div>
            <button disabled={busy} onClick={()=>setPage('projects')}><FolderOpen size={15}/>{tr('Вибрати або створити проєкт','Choose or create project')}</button>
          </div>
          <div className="quick-controls">
            {startButton}
            <fieldset className="quick-options" disabled={busy}>{quickToggles.map(key =>
              <label key={key}><input type="checkbox" checked={Boolean(settings[key])} onChange={event=>void toggleQuick(key, event.target.checked)}/>
                {tr(fields[key][0], fields[key][1])}</label>)}</fieldset>
          </div>
          <div className="quick-result" aria-live="polite">
            {quickActive ? <>
              <strong>{stageText}</strong>
              <progress aria-label={tr('Прогрес швидкої збірки','Quick build progress')} max={settings.copy_client ? 4 : settings.copy_server ? 3 : settings.sign ? 2 : 1} value={run?.stage ?? 0}/>
            </> : run?.action === 'quick' && run.done === false && notice ? <>
              <Status tone="warn">{tr('Помилка','Error')}</Status><p>{notice}</p>
              <button disabled={busy} onClick={()=>setWizard(0)}>{tr('Виправити налаштування','Fix setup')}</button>
            </> : lastQuick ? <>
              <Status tone={lastQuick.status === 'complete' ? 'good' : 'warn'}>{lastQuick.status === 'complete' ? tr('Успішно','Successful') : tr('Помилка','Error')}</Status>
              {lastQuick.error && <p className="bad">{lastQuick.error}</p>}
              {!!quickPbos.length && <p>{quickPbos.map(name => name.split('/').pop()).join(', ')}</p>}
              {!!lastQuick.updated.length && <ul>{lastQuick.updated.map(path => <li key={path}>{path}</li>)}</ul>}
              {lastQuick.status === 'failed' && <button disabled={busy} onClick={()=>{setNotice(lastQuick.error || '');setWizard(0)}}>{tr('Виправити налаштування','Fix setup')}</button>}
            </> : <small>{tr('Збірку ще не запускали','No build yet')}</small>}
          </div>
          {entries.length > 0 && <div className="quick-log">
            <code title={entries[entries.length - 1]?.text}>{entries[entries.length - 1]?.text}</code>
            <button className="subtle" aria-expanded={showLog} onClick={()=>setShowLog(!showLog)}><Terminal size={15}/>{tr('Журнал','Log')}</button>
          </div>}
        </section>}
        {project && page==='build' && <>
          <div className="flex flex-wrap gap-2">
            <button disabled={busy} onClick={()=>void start('build')}>{tr('Лише зібрати пакет','Build package only')}</button>
            <button disabled={busy} onClick={()=>setWizard(0)}>{tr('Майстер налаштування','Setup wizard')}</button>
          </div>
          <details><summary><ClipboardList size={15}/>{tr('Останні операції','Recent operations')}</summary>
            {project.details.operations.map(item=><button className="project-card" key={item.date} onClick={()=>setSelectedReport(item)}>
              {new Date(item.date).toLocaleString(lng==='uk'?'uk-UA':'en-US')} · {local(operationNames[item.action])} · {item.status==='complete'?tr('Завершено','Complete'):tr('Помилка','Failed')}
            </button>)}
          </details>
          {!busy && selectedReport && operation(selectedReport)}
          <details className="terminal-commands">
            <summary><Terminal size={15}/>{tr('Команди PowerShell','PowerShell commands')}</summary>
            {(settingsDirty || !project.configured) &&
              <small>{tr('Під час копіювання налаштування буде збережено для термінала.',
                'Copying saves the current settings for the terminal.')}</small>}
            <label>F5 · {tr('Зібрати та встановити','Build and deploy')}</label>
            {commandLine('quick')}
            <label>F6 · {tr('Розгорнути вибрану збірку','Deploy selected build')}</label>
            {project.details.commands.remote ? commandLine('remote') :
              <small>{tr('Команда з’явиться після підготовки збірки для вибраного джерела.',
                'The command appears when a build is ready for the selected source.')}</small>}
            <label>
              {tr('Інша дія','Other action')}
              <select value={terminalAction} onChange={event=>setTerminalAction(event.target.value)}>
                {Object.keys(project.details.commands).filter(action=>action!=='quick'&&action!=='remote').map(action=>
                  <option key={action} value={action}>{action}</option>)}
              </select>
            </label>
            {commandLine(terminalAction)}
          </details>
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
            <span>{tr('ЧАС','TIME')}: <b>{lastBuild?lastBuild.seconds+' s':'-'}</b></span>
            <span>PBO: <b>{latestPackage?.count??'-'}</b></span>
            <span>{tr('ПОПЕРЕДЖЕННЯ','WARNINGS')}: <b className={lastBuild?.warnings?'warning':''}>{lastBuild?.warnings??'-'}</b></span>
            <span>{tr('ПІДПИС','SIGNATURE')}: <b>{latestPackage?.signed?tr('Перевірено','Verified'):settings.sign?'-':tr('Вимкнено','Disabled')}</b></span>
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
          {!busy && selectedReport && operation(selectedReport)}
          <section>
            <h2>{tr('Локальне тестування','Local testing')}</h2>
            <div className="flex flex-wrap gap-2">
              <button disabled={busy} onClick={()=>void start('test')}>{tr('Зібрати та протестувати','Build and test')}</button>
              <button disabled={busy||!ready||!project.details.packageReady} onClick={()=>void start('deploy')}>{tr('Лише встановити тестовий пакет','Install test package only')}</button>
              <button disabled={busy||!ready||!project.details.deployment} onClick={()=>void start('launch')}>{tr('Запустити встановлений тестовий пакет','Launch installed test package')}</button>
              <button disabled={busy||!project.details.retry} onClick={()=>void start('retry')}>{tr('Продовжити тест','Resume test')}</button>
            </div>
            {readiness()}
            <button className="subtle" onClick={()=>{setSettingsGroup(1);setPage('settings')}}>{tr('Налаштування тесту','Test settings')}</button>
          </section>
          <section>
            <h2>{tr('Віддалений сервер','Remote server')}</h2>
            {project.details.remoteChoice.buildId && <p>{project.details.remoteChoice.buildId}</p>}
            {project.details.remoteChoice.changed && <small>{tr('Є нові зміни у вихідних файлах','Newer source changes are available')}</small>}
            <div className="flex flex-wrap gap-2">
              <button disabled={busy || !settings.remote_host || !project.details.remoteChoice.buildId} onClick={()=>void start('remote')}>
                {settings.remote_files_only ? tr('Завантажити через SFTP','Upload over SFTP') : tr('Розгорнути через SSH','Deploy over SSH')} <kbd>F6</kbd>
              </button>
              <button onClick={()=>{setSettingsGroup(5);setPage('settings')}}>{tr('Налаштування SSH/SFTP','SSH/SFTP settings')}</button>
            </div>
          </section>
          <section><h2>{tr('Зупинка тестової сесії','Stop the test session')}</h2>
            <div className="flex flex-wrap gap-2">
              <button disabled={busy} onClick={()=>void stopSession(false)}>{tr('Зупинити / повторити спробу','Stop / retry')}</button>
              <button disabled={busy} onClick={()=>void stopSession(true)}>{tr('Примусово завершити власний сервер','Force stop own server')}</button>
            </div>
          </section>
          <section><div className="section-header"><h2>{tr('Активний профіль','Active profile')}</h2><Status tone={live==='ready'?'good':'neutral'}>{serverState}</Status></div>
          {['config','profiles','client_profiles','port'].map(key=><div className="check" key={key}><strong>{tr(fields[key][0],fields[key][1])}</strong><small>{String(settings[key] || tr('Типове значення','Default'))}</small></div>)}</section>
          <section><div className="section-header"><h2>{tr('Резервні копії','Backups')}</h2>
            <button disabled={busy||!project.details.rollback} onClick={()=>setConfirmation('rollback')}>{tr('Відновити попереднє встановлення','Restore previous installation')}</button>
          </div>
          {!project.details.backups.length&&<p>{tr('Копії з’являться після першого локального встановлення.','Backups appear after the first local deployment.')}</p>}
          {project.details.backups.map(path=><button className="project-card" key={path} onClick={()=>void reveal(path)}>{nameOf(path)}</button>)}</section>
        </>}
        {project && page==='workshop' && !busy && selectedReport && operation(selectedReport)}
        {project && page==='workshop' && <section><h2>Workshop · {(checkedItem?.input === settings.workshop && checkedItem?.title) || String(settings.workshop_title || settings.workshop || '-')}</h2>
          <p>{project.details.published.buildId ? tr('Остання підтверджена публікація','Last confirmed publication') + ' · ' + project.details.published.buildId : tr('Публікацію ще не підтверджено','Awaiting confirmed publication')}</p>
          <div className="flex flex-wrap gap-2">
            <button disabled={busy||!project.details.localBuild.buildId||project.details.sourcesChanged!==false||!settings.workshop} onClick={()=>setConfirmation('publish')}>{tr('Опублікувати перевірену збірку','Publish tested build')}</button>
            {project.details.publication.status === 'failed' && <button disabled={busy} onClick={()=>void start('retry-publish')}>{tr('Повторити публікацію','Retry publication')}</button>}
            {['pending','uncertain'].includes(project.details.publication.status || '') && <span>{tr('Перевір результат у Steam','Check the result in Steam')}</span>}
          </div>
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
                if (settingsGroup===0) return <>{addonEditor()}{advanced && form(group.advanced)}</>
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
      {!toolPage && <LogDrawer open={showLog} toggle={()=>setShowLog(false)} entries={entries} logs={project?.details.logs||[]} busy={busy} read={path=>void readLog(path)} tr={tr}/>}
      {page!=='overview' && <div className="footer-row"><span aria-live="polite">{showModels ? modelStatus : showTextures ? textureStatus : stageText}</span>
        {!toolPage&&busy&&<progress aria-label={tr('Прогрес операції','Operation progress')} max={5} value={run?.stage??0}/>}
        {!toolPage && <button className="subtle ml-auto" aria-expanded={showLog} onClick={()=>setShowLog(!showLog)}><Terminal size={15}/>{tr('Деталі','Details')}</button>}</div>}
    </footer>
    {(wizard !== undefined || confirmation) && <div className="overlay" onKeyDown={e=>{if(e.key==='Escape'){setWizard(undefined);setConfirmation(undefined)}}}><div role="dialog" aria-modal="true" aria-label={tr('Налаштування або підтвердження','Setup or confirmation')} className="modal">
      {wizard !== undefined ? <>
        <h2>{setupSteps[wizard]}</h2>
        <small>{wizard + 1} / {setupSteps.length}</small>
        <fieldset className="modal-content" disabled={busy}>
          {wizard === 0 && <>
            <label>{tr('Папка вихідних файлів','Source folder')}</label>
            <div className="setup-folder">
              <span className="path" title={project?.root}>{project?.root}</span>
              <button onClick={()=>void chooseProject()}>{tr('Вибрати папку','Choose folder')}</button>
            </div>
            {project && addonEditor()}
          </>}
          {wizard === 1 && <>
            {form(['tools', 'addon_builder', 'copy_server', 'copy_client', ...(settings.copy_server ? ['server'] : []), ...(settings.copy_client ? ['client'] : [])])}
            <button onClick={()=>void detect()}>{tr('Знайти DayZ та AddonBuilder','Detect DayZ and AddonBuilder')}</button>
          </>}
          {wizard === 2 && <>
            {form(settings.sign ? ['sign', 'private', 'public'] : ['sign'])}
            {settings.sign && <div className="flex flex-wrap gap-2">
              <input aria-label={tr('Назва пари ключів','Key pair name')} placeholder={tr('Назва пари ключів','Key pair name')} value={keyName} onChange={event=>setKeyName(event.target.value)}/>
              <button disabled={!keyName.trim()} onClick={()=>void generateKeys()}>{tr('Створити пару ключів','Generate key pair')}</button>
            </div>}
          </>}
          {notice && <p role="status">{notice}</p>}
        </fieldset>
        <div className="modal-actions">
          <button onClick={()=>{setWizard(undefined);setNotice('')}}>{tr('Закрити','Close')}</button>
          {wizard>0 && <button disabled={busy} onClick={()=>{setWizard(wizard-1);setNotice('')}}>{tr('Назад','Back')}</button>}
          {wizard<2 ? <button className="primary" disabled={busy || !project || !addonFolders(settings).length} onClick={()=>{setWizard(wizard+1);setNotice('')}}>{tr('Далі','Next')}</button> :
            <button className="primary" disabled={busy} onClick={()=>void saveSettings(true)}>{tr('Зберегти проєкт','Save project')}</button>}
        </div>
      </> : <>
        <h2>{confirmation && local(operationNames[confirmation])}</h2>
        <p>{confirmation==='publish'? 'Workshop · '+String(settings.workshop) + ' · ' + project?.details.localBuild.buildId
          : confirmation==='create-workshop' ? String(settings.workshop_title || '') + ' · ' + (project?.details.localBuild.buildId || '')
          : tr('Відновити файли з попереднього встановлення?','Restore the files from the previous installation?')}</p>
        <div className="modal-actions"><button autoFocus onClick={()=>setConfirmation(undefined)}>{tr('Скасувати','Cancel')}</button><button className="primary" onClick={()=>confirmation&&void start(confirmation)}>{tr('Підтвердити','Confirm')}</button></div>
      </>}
    </div></div>}
  </div>
}
createRoot(document.getElementById('root')!).render(<App/>)
