import { contextBridge, ipcRenderer } from 'electron'

type Listener<T> = (payload: T) => void

function subscribe<T>(channel: string, listener: Listener<T>) {
  const wrapped = (_event: Electron.IpcRendererEvent, payload: T) => listener(payload)
  ipcRenderer.on(channel, wrapped)
  return () => ipcRenderer.removeListener(channel, wrapped)
}

contextBridge.exposeInMainWorld('t1osFlasher', {
  detectImage: () => ipcRenderer.invoke('image:detect'),
  chooseImage: () => ipcRenderer.invoke('image:choose'),
  listUsbTargets: () => ipcRenderer.invoke('usb:list'),
  startFlash: (request: unknown) => ipcRenderer.invoke('flash:start', request),
  onProgress: (listener: Listener<unknown>) => subscribe('flash:progress', listener),
  onState: (listener: Listener<unknown>) => subscribe('flash:state', listener),
  onLog: (listener: Listener<unknown>) => subscribe('flash:log', listener),
})
