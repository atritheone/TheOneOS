import type { CommandId } from '../electron/commands'

declare global {
type DiskStatus = 'mounted' | 'unmounted' | 'error'
type DiskHealth = 'ok' | 'corrupted' | 'checking' | 'unavailable'
type DebugMode = 'on' | 'off' | 'checking' | 'unavailable'
type DiskUser =
  | { state: 'user'; username: string }
  | { state: 'none' | 'unavailable' }

interface CommandOutput {
  line: string
  stream: 'stdout' | 'stderr' | 'system' | 'diagnostic'
}

interface CommandState {
  running: boolean
  id: CommandId
  label: string
  succeeded?: boolean
  cancelled?: boolean
  exitCode?: number | null
}

interface CreateUserRequest {
  username: string
  password: string
}

interface ChangeUserRequest {
  username: string
  currentPassword: string
  newPassword: string
  changePassword: boolean
}

interface RemoveUserRequest {
  username: string
  password: string
}

interface FlashUsbRequest {
  diskNumber: number
  confirmation: string
}

interface WirelessRequest {
  ssid: string
  security: 'open' | 'wpa2' | 'wpa3'
  passphrase: string
}

interface UsbTarget {
  diskNumber: number
  friendlyName: string
  serialNumber: string
  sizeGiB: number
  confirmation: string
}

interface UsbTargetList {
  targets: UsbTarget[]
  protectedTargets: Array<Omit<UsbTarget, 'confirmation'>>
}

  interface Window {
    t1os: {
    runCommand: (
      id: CommandId,
      input?: CreateUserRequest | ChangeUserRequest | RemoveUserRequest | FlashUsbRequest | WirelessRequest,
    ) => Promise<{ accepted: boolean; message?: string }>
    cancelCommand: () => Promise<{ cancelled: boolean; message?: string }>
    getDiskStatus: () => Promise<DiskStatus>
    getDiskHealth: () => Promise<DiskHealth>
    getDiskUser: () => Promise<DiskUser>
    getDebugMode: () => Promise<DebugMode>
    openDisk: () => Promise<{ opened: boolean; message?: string }>
    getUsbTargets: () => Promise<UsbTargetList>
    getLastPush: () => Promise<string | null>
    getCurrentVersion: () => Promise<string>
    setCurrentVersion: (version: string) => Promise<string>
    onDiskStatus: (listener: (status: DiskStatus) => void) => () => void
    onDiskHealth: (listener: (health: DiskHealth) => void) => () => void
    onDiskUser: (listener: (user: DiskUser) => void) => () => void
    onDebugMode: (listener: (mode: DebugMode) => void) => () => void
    onLastPush: (listener: (timestamp: string) => void) => () => void
    onCommandOutput: (listener: (output: CommandOutput) => void) => () => void
    onCommandState: (listener: (state: CommandState) => void) => () => void
    }
  }
}

export {}
