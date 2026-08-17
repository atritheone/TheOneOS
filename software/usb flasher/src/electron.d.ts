interface ImageInfo {
  path: string
  name: string
  sizeBytes: number
  sizeGiB: number
  payloadBytes: number
  payloadGiB: number
  minimumTargetBytes: number
  minimumTargetGiB: number
  espBytes: number
  recoveryBytes: number
  recoveryPartitionBytes: number
  rootBytes: number
  version: string
  driveVersion: string
  volumeLabel: string
  production: boolean
}

interface UsbTarget {
  diskNumber: number
  friendlyName: string
  serialNumber: string
  sizeBytes: number
  sizeGiB: number
  confirmation: string
}

type FlashStage = 'idle' | 'validating' | 'preparing' | 'writing' | 'verifying' | 'complete' | 'error'

interface FlashProgress {
  stage: FlashStage
  percent: number
  message: string
}

interface FlashState {
  running: boolean
  succeeded?: boolean
  exitCode?: number | null
}

interface FlashLog {
  line: string
  error: boolean
}

interface Window {
  t1osFlasher: {
    detectImage: () => Promise<ImageInfo | null>
    chooseImage: () => Promise<ImageInfo | null>
    listUsbTargets: () => Promise<UsbTarget[]>
    startFlash: (request: { imagePath: string; diskNumber: number }) => Promise<{
      accepted: boolean
      canceled?: boolean
      message?: string
    }>
    onProgress: (listener: (progress: FlashProgress) => void) => () => void
    onState: (listener: (state: FlashState) => void) => () => void
    onLog: (listener: (entry: FlashLog) => void) => () => void
  }
}
