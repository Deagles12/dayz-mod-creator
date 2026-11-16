import { useEffect, useRef, useState } from 'react'
import { open } from '@tauri-apps/plugin-dialog'
import { FolderOpen, Upload } from 'lucide-react'
import * as THREE from 'three'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { call, type Settings } from './backend'
import type { Lang } from './locale'

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

export function Models({ language, root, settings }: { language: Lang; root?: string; settings: Settings }) {
  const tr = (uk: string, en: string) => language === 'uk' ? uk : en
  const [model, setModel] = useState('')
  const [preview, setPreview] = useState('')
  const [files, setFiles] = useState<ModelFiles>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function choose() {
    setBusy(true)
    setError('')
    try {
      const path = await open({ filters: [{ name: 'GLB', extensions: ['glb'] }], multiple: false })
      if (typeof path !== 'string') return
      setModel(path.split(/[\\/]/).pop() || path)
      setFiles(undefined)
      setPreview('')
      setPreview(await call<string>(language, 'previewModel', { path }))
      setFiles(await call<ModelFiles>(language, 'exportModel', { path, root, settings }))
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure))
    } finally {
      setBusy(false)
    }
  }

  async function reveal() {
    if (!files) return
    try {
      await call(language, 'revealModel', { path: files.folder })
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure))
    }
  }

  return <div className="model-tool">
    <button className="primary" disabled={busy} onClick={() => void choose()}><Upload size={16}/>{tr('Вибрати GLB', 'Choose GLB')}</button>
    {model && <p className="path">{model}</p>}
    {preview && <Preview data={preview} fallback={tr('3D-прев’ю недоступне.', '3D preview is unavailable.')}/>}
    {busy && <p role="status">{tr('Готую P3D і PAA…', 'Preparing P3D and PAA…')}</p>}
    {error && <p role="alert" className="model-error">{error}</p>}
    {files && <div className="model-result">
      <div><strong>{files.model}</strong><p>{files.texture}</p></div>
      <button onClick={() => void reveal()}><FolderOpen size={16}/>{tr('Відкрити результат', 'Open output folder')}</button>
    </div>}
  </div>
}
