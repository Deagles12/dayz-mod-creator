import { useEffect, useRef, useState } from 'react'
import { open } from '@tauri-apps/plugin-dialog'
import { FolderOpen, Upload } from 'lucide-react'
import * as THREE from 'three'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { call, type Settings } from './backend'
import type { Lang } from './locale'
import { OutputFolder, useExportFolder } from './export-folder'

type ModelFiles = { folder: string; model: string; texture: string; prefix: string }

function Preview({ data, fallback }: { data: string; fallback: string }) {
  const mount = useRef<HTMLDivElement>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    const host = mount.current
    if (!host) return
    setFailed(false)
    let renderer: THREE.WebGLRenderer
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    } catch {
      setFailed(true)
      return
    }
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2))
    host.append(renderer.domElement)
    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(36, 1, .01, 10000)
    const controls = new OrbitControls(camera, renderer.domElement)
    scene.add(new THREE.HemisphereLight(0xffffff, 0x7a8290, 2.5))
    const key = new THREE.DirectionalLight(0xffffff, 2)
    key.position.set(3, 4, 2)
    scene.add(key)
    const draw = () => renderer.render(scene, camera)
    controls.addEventListener('change', draw)
    const observer = new ResizeObserver(() => {
      const { clientWidth: width, clientHeight: height } = host
      if (!width || !height) return
      renderer.setSize(width, height)
      camera.aspect = width / height
      camera.updateProjectionMatrix()
      draw()
    })
    observer.observe(host)
    let active = true
    let model: THREE.Object3D | undefined
    function dispose(object: THREE.Object3D) {
      object.traverse(node => {
        if (!(node instanceof THREE.Mesh)) return
        node.geometry.dispose()
        for (const material of Array.isArray(node.material) ? node.material : [node.material]) {
          for (const value of Object.values(material)) if (value instanceof THREE.Texture) value.dispose()
          material.dispose()
        }
      })
    }
    function load() {
      const bytes = Uint8Array.from(atob(data), char => char.charCodeAt(0))
      return new GLTFLoader().parseAsync(bytes.buffer, '')
    }
    void Promise.resolve().then(load).then(gltf => {
      if (!active) {
        dispose(gltf.scene)
        return
      }
      model = gltf.scene
      const bounds = new THREE.Box3().setFromObject(model)
      const center = bounds.getCenter(new THREE.Vector3())
      const radius = bounds.getBoundingSphere(new THREE.Sphere()).radius || 1
      camera.near = radius / 100
      camera.far = radius * 100
      const vertical = THREE.MathUtils.degToRad(camera.fov / 2)
      const horizontal = Math.atan(Math.tan(vertical) * camera.aspect)
      const distance = radius / Math.sin(Math.min(horizontal, vertical)) * 1.15
      camera.position.copy(center).addScaledVector(new THREE.Vector3(1, .55, 1.5).normalize(), distance)
      camera.updateProjectionMatrix()
      controls.target.copy(center)
      controls.update()
      scene.add(model)
      draw()
    }).catch(() => { if (active) setFailed(true) })
    return () => {
      active = false
      observer.disconnect()
      controls.dispose()
      if (model) dispose(model)
      renderer.dispose()
      renderer.domElement.remove()
    }
  }, [data])
  return <div className="model-preview" ref={mount}>{failed && <p role="status">{fallback}</p>}</div>
}

type Activity = 'idle' | 'choosing' | 'running' | 'done' | 'error'

const stages = [
  ['Завантаження GLB', 'Loading GLB'],
  ['Підготовка меша в Blender', 'Preparing mesh in Blender'],
  ['Конвертація текстури в PAA', 'Converting texture to PAA'],
  ['Побудова LOD і запис P3D', 'Building LODs and writing P3D'],
  ['Перевірка й збереження файлів', 'Checking and saving files'],
] as const

export function Models({ language, root, settings, onStatus }: {
  language: Lang; root?: string; settings: Settings; onStatus: (status: string) => void
}) {
  const tr = (uk: string, en: string) => language === 'uk' ? uk : en
  const [model, setModel] = useState('')
  const [preview, setPreview] = useState('')
  const [files, setFiles] = useState<ModelFiles>()
  const [activity, setActivity] = useState<Activity>('idle')
  const [stage, setStage] = useState(0)
  const [error, setError] = useState('')
  const output = useExportFolder(language, 'models', setError)
  const busy = activity === 'choosing' || activity === 'running'
  const status = {
    idle: tr('Вибери кольоровий GLB', 'Choose a textured GLB'),
    choosing: tr('Вибір файла', 'Selecting a file'),
    running: tr(stages[stage][0], stages[stage][1]),
    done: tr('P3D і PAA готові', 'P3D and PAA are ready'),
    error: tr('Операцію не завершено', 'Operation did not finish'),
  }[activity]

  useEffect(() => onStatus(status), [status, onStatus])
  async function choose() {
    setActivity('choosing')
    setError('')
    try {
      const path = await open({ filters: [{ name: 'GLB', extensions: ['glb'] }], multiple: false })
      if (typeof path !== 'string') {
        setActivity(activity)
        return
      }
      setModel(path.split(/[\\/]/).pop() || path)
      setPreview('')
      setFiles(undefined)
      setStage(0)
      setActivity('running')
      setPreview(await call<string>(language, 'previewModel', { path }))
      setFiles(await call<ModelFiles>(language, 'exportModel', { path, root, settings, output: output.destination }, message => {
        if (message.event === 'progress' && message.stage !== undefined && message.stage in stages) {
          const next = message.stage
          setStage(current => Math.max(current, next))
        }
      }))
      setActivity('done')
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure))
      setActivity('error')
    }
  }

  async function reveal(path: string) {
    try {
      await call(language, 'revealModel', { path })
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure))
    }
  }

  return <div className="model-tool">
    <button className="primary" disabled={busy} onClick={() => void choose()}><Upload size={16}/>{tr('Вибрати GLB', 'Choose GLB')}</button>
    <OutputFolder language={language} {...output} disabled={busy}/>
    {activity !== 'idle' && <section className="model-status">
      <div className="model-status-head">
        <strong role="status">{status}</strong>
        {activity === 'running' && <span>{stage + 1} / {stages.length}</span>}
      </div>
      {model && <div className="path">{model}</div>}
      <progress aria-label={tr('Завершено етапів експорту', 'Completed export stages')}
        max={stages.length} value={activity === 'done' ? stages.length : activity === 'choosing' ? 0 : stage}/>
      <ol className="model-steps">
        {stages.map(([uk, en], index) => {
          const completed = activity === 'done' || (activity === 'running' || activity === 'error') && index < stage
          const current = (activity === 'running' || activity === 'error') && index === stage
          return <li key={en} data-state={completed ? 'done' : current ? activity : 'pending'}
            aria-current={current ? 'step' : undefined}>
            <span aria-hidden="true">{completed ? '✓' : index + 1}</span>{tr(uk, en)}
          </li>
        })}
      </ol>
      {error && <p role="alert" className="model-error">{error}</p>}
    </section>}
    {activity === 'idle' && error && <p className="model-error" role="alert">{error}</p>}
    {files && <section className="model-result">
      <h2>{tr('Файли результату', 'Output files')}</h2>
      <code className="model-output-path">{files.folder}</code>
      <div className="model-file-list"><code>{files.model}</code><code>data\{files.texture}</code></div>
      <button onClick={() => void reveal(files.folder)}><FolderOpen size={16}/>{tr('Відкрити папку', 'Open folder')}</button>
    </section>}
    {preview && <Preview data={preview} fallback={tr('3D-прев’ю недоступне.', '3D preview is unavailable.')}/>}
  </div>
}
