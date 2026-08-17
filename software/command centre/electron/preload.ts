import { contextBridge, ipcRenderer } from 'electron'

type Listener<T> = (payload: T) => void

function subscribe<T>(channel: string, listener: Listener<T>) {
  const wrapped = (_event: Electron.IpcRendererEvent, payload: T) => listener(payload)
  ipcRenderer.on(channel, wrapped)
  return () => ipcRenderer.removeListener(channel, wrapped)
}

contextBridge.exposeInMainWorld('t1os', {
  runCommand: (id: string, input?: unknown) => ipcRenderer.invoke('command:run', id, input),
  cancelCommand: () => ipcRenderer.invoke('command:cancel'),
  getDiskStatus: () => ipcRenderer.invoke('disk:get-status'),
  getDiskHealth: () => ipcRenderer.invoke('disk:get-health'),
  getDiskUser: () => ipcRenderer.invoke('disk:get-user'),
  getDebugMode: () => ipcRenderer.invoke('disk:get-debug-mode'),
  openDisk: () => ipcRenderer.invoke('disk:open'),
  getUsbTargets: () => ipcRenderer.invoke('usb:get-targets'),
  getLastPush: () => ipcRenderer.invoke('push:get-last'),
  getCurrentVersion: () => ipcRenderer.invoke('version:get'),
  setCurrentVersion: (version: string) => ipcRenderer.invoke('version:set', version),
  onDiskStatus: (listener: Listener<string>) => subscribe('disk:status', listener),
  onDiskHealth: (listener: Listener<string>) => subscribe('disk:health', listener),
  onDiskUser: (listener: Listener<unknown>) => subscribe('disk:user', listener),
  onDebugMode: (listener: Listener<string>) => subscribe('disk:debug-mode', listener),
  onLastPush: (listener: Listener<string>) => subscribe('push:last', listener),
  onCommandOutput: (listener: Listener<unknown>) => subscribe('command:output', listener),
  onCommandState: (listener: Listener<unknown>) => subscribe('command:state', listener),
})
