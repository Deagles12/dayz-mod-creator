import { Command, type Child } from '@tauri-apps/plugin-shell'
export type Settings = Record<string, string | boolean>
export type Check = { key: string; ok: boolean; detail: string }
export type Operation = { action: string; date: string; phase: number; status: 'failed' | 'complete'; warnings: number; seconds: number; built: boolean; signed: boolean; installed: boolean; serverReady: boolean; clientLaunched: boolean; connected: boolean; updated: string[]; files: string[]; log: string; error?: string; attention?: boolean }
export type Details = { operations: Operation[]; packageReady: boolean; deployment: boolean; retry: boolean; checks: Check[]; dependencies: string[]; builds: { name: string; path: string; signed: boolean; tested: boolean; count: number }[]; backups: string[]; logs: string[]; rollback: boolean; tested: boolean }
export type Project = { root: string; configured: boolean; settings: Settings; details: Details }
export type Message = { event: string; id: number; stage?: number; label?: string | [string, string]; text?: string; value?: unknown }
type Pending = { resolve: (value: unknown) => void; reject: (error: Error) => void; event?: (message: Message) => void }
let process: Promise<Child> | undefined
let sequence = 0
const pending = new Map<number, Pending>()

function launch() {
  const command = Command.sidecar('binaries/dayz-backend', [], { encoding: 'raw' })
  const decoder = new TextDecoder()
  let buffer = ''
  const disconnect = (reason: string) => {
    for (const request of pending.values()) request.reject(new Error(reason))
    pending.clear()
    process = undefined
  }
  command.on('close', ({code}) => disconnect('DayZ backend exited (' + code + ')'))
  command.on('error', disconnect)
  command.stdout.on('data', (data) => {
    buffer += typeof data === 'string' ? data : decoder.decode(Uint8Array.from(data), {stream: true})
    let newline = buffer.indexOf('\n')
    while (newline >= 0) {
      const line = buffer.slice(0, newline)
      buffer = buffer.slice(newline + 1)
      newline = buffer.indexOf('\n')
      try {
        const message: Message = JSON.parse(line)
        const request = pending.get(message.id)
        if (!request) continue
        if (message.event === 'result' || message.event === 'error') {
          pending.delete(message.id)
          if (message.event === 'error') request.reject(new Error(message.text))
          else request.resolve(message.value)
        } else request.event?.(message)
      } catch (error) {
        console.error(error)
      }
    }
  })
  return command.spawn().catch(error => { process = undefined; throw error })
}

export async function call<T>(language: string, command: string, input = {}, event?: Pending['event']): Promise<T> {
  const child = await (process ??= launch())
  const id = ++sequence
  return new Promise<T>((resolve, reject) => {
    pending.set(id, {resolve: value => resolve(value as T), reject, event})
    child.write(JSON.stringify({id, command, language, ...input}) + '\n').catch(error => {
      pending.delete(id)
      reject(error)
    })
  })
}
