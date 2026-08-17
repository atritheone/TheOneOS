import {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  nativeImage,
  powerSaveBlocker,
} from 'electron'
import { execFile, spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { existsSync, readdirSync, statSync } from 'node:fs'
import path from 'node:path'

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

interface FlashRequest {
  imagePath: string
  diskNumber: number
}

type FlashStage = 'idle' | 'validating' | 'preparing' | 'writing' | 'verifying' | 'complete' | 'error'

let mainWindow: BrowserWindow | null = null
let activeProcess: ChildProcessWithoutNullStreams | null = null
let powerSaveBlockerId: number | null = null

const productName = 'The One OS USB Flasher'
const logoPath = app.isPackaged
  ? path.join(process.resourcesPath, 't1os-logo-white-transparent.png')
  : path.resolve(__dirname, '..', 'src', 'assets', 't1os-logo-white-transparent.png')
const flashScriptPath = app.isPackaged
  ? path.join(process.resourcesPath, 'scripts', 'flash production usb.ps1')
  : path.resolve(__dirname, '..', '..', 'scripts', 'flash hardware usb.ps1')

const appIcon = nativeImage.createFromPath(logoPath)
if (appIcon.isEmpty()) throw new Error(`The One OS logo could not be loaded: ${logoPath}`)

app.setName(productName)
app.setAppUserModelId('t1os.usb-flasher')

function send(channel: string, payload: unknown) {
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send(channel, payload)
}

function stripAnsi(value: string) {
  return value.replace(/[\u001B\u009B][[\]()#;?]*(?:(?:(?:[a-zA-Z\d]*(?:;[-a-zA-Z\d/#&.:=?%@~_]+)*)?\u0007)|(?:(?:\d{1,4}(?:[;:]\d{0,4})*)?[\dA-PR-TZcf-nq-uy=><~]))/g, '')
}

function pipeLines(
  child: ChildProcessWithoutNullStreams,
  stream: 'stdout' | 'stderr',
  onLine: (line: string) => void,
) {
  let remainder = ''
  child[stream].setEncoding('utf8')
  child[stream].on('data', (chunk: string) => {
    const lines = (remainder + stripAnsi(chunk)).split(/\r?\n/)
    remainder = lines.pop() ?? ''
    for (const line of lines) if (line.trim()) onLine(line.trim())
  })
  child[stream].on('end', () => {
    if (remainder.trim()) onLine(remainder.trim())
  })
}

function roundGiB(bytes: number) {
  return Math.round((bytes / (1024 ** 3)) * 100) / 100
}

function inspectImageFile(imagePath: string) {
  const resolvedPath = path.resolve(imagePath)
  if (path.extname(resolvedPath).toLowerCase() !== '.t1os') {
    throw new Error('select a The One OS installer ending in .t1os.')
  }
  if (!existsSync(resolvedPath) || !statSync(resolvedPath).isFile()) {
    throw new Error('the selected installer does not exist.')
  }

  const image = statSync(resolvedPath)
  if (image.size <= 0) throw new Error('the selected installer is empty.')

  return {
    path: resolvedPath,
    name: path.basename(resolvedPath),
    sizeBytes: image.size,
    sizeGiB: roundGiB(image.size),
  }
}

function validateImageLayout(imagePath: string): Promise<ImageInfo> {
  const image = inspectImageFile(imagePath)
  if (!existsSync(flashScriptPath)) return Promise.reject(new Error('the bundled USB installer validator is missing.'))

  return new Promise((resolve, reject) => {
    execFile(
      'pwsh.exe',
      [
        '-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
        '-File', flashScriptPath, '-InspectImage', '-ImagePath', image.path,
      ],
      { windowsHide: true, timeout: 30000, encoding: 'utf8', maxBuffer: 2 * 1024 * 1024 },
      (error, stdout, stderr) => {
        if (error) {
          reject(new Error(stripAnsi(stderr || stdout || error.message).trim()))
          return
        }
        try {
          const jsonLine = stdout.split(/\r?\n/).map((line) => line.trim()).reverse()
            .find((line) => line.startsWith('{'))
          if (!jsonLine) throw new Error('PowerShell did not return installer validation data.')
          const layout = JSON.parse(jsonLine) as Record<string, unknown>
          if (
            layout.valid !== true || layout.bundle !== true ||
            layout.partitionTable !== 'gpt' || layout.rootFilesystem !== 'ntfs'
          ) {
            throw new Error('the selected file is not a valid The One OS USB installer.')
          }
          if (Number(layout.bytes) !== image.sizeBytes) {
            throw new Error('the installer changed while it was being validated.')
          }
          const version = typeof layout.version === 'string' ? layout.version : ''
          const driveVersion = typeof layout.driveVersion === 'string' ? layout.driveVersion : ''
          const volumeLabel = typeof layout.volumeLabel === 'string' ? layout.volumeLabel : ''
          const payloadBytes = Number(layout.payloadBytes)
          const minimumTargetBytes = Number(layout.minimumTargetBytes)
          const espBytes = Number(layout.espBytes)
          const recoveryBytes = Number(layout.recoveryBytes)
          const recoveryPartitionBytes = Number(layout.recoveryPartitionBytes)
          const rootBytes = Number(layout.rootBytes)
          const production = layout.production === true
          if (
            !/^\d+\.\d+$/.test(version) || driveVersion !== version ||
            volumeLabel !== `T1OS ${version}` ||
            !Number.isSafeInteger(payloadBytes) || payloadBytes <= 0 ||
            !Number.isSafeInteger(minimumTargetBytes) || minimumTargetBytes < payloadBytes ||
            !Number.isSafeInteger(espBytes) || espBytes <= 0 ||
            !Number.isSafeInteger(recoveryBytes) || recoveryBytes <= 0 ||
            !Number.isSafeInteger(recoveryPartitionBytes) || recoveryPartitionBytes < recoveryBytes ||
            !Number.isSafeInteger(rootBytes) || rootBytes <= 0 ||
            payloadBytes !== espBytes + recoveryBytes + rootBytes ||
            minimumTargetBytes !== 2 * 1024 * 1024 + espBytes + recoveryPartitionBytes + rootBytes
          ) {
            throw new Error('the installer filename, recovery payload, or capacity data is invalid.')
          }
          resolve({
            ...image,
            payloadBytes,
            payloadGiB: roundGiB(payloadBytes),
            minimumTargetBytes,
            minimumTargetGiB: roundGiB(minimumTargetBytes),
            espBytes,
            recoveryBytes,
            recoveryPartitionBytes,
            rootBytes,
            version,
            driveVersion,
            volumeLabel,
            production,
          })
        } catch (parseError) {
          const message = parseError instanceof Error ? parseError.message : String(parseError)
          reject(new Error(`the installer could not be validated: ${message}`))
        }
      },
    )
  })
}

function portableDirectory() {
  const portableDir = process.env.PORTABLE_EXECUTABLE_DIR
  return portableDir ? path.resolve(portableDir) : path.dirname(process.execPath)
}

async function detectImage(): Promise<ImageInfo | null> {
  const directories = app.isPackaged
    ? [portableDirectory()]
    : [path.resolve(__dirname, '..', '..', 'environment', 'hardware')]

  const images: ImageInfo[] = []
  for (const directory of directories) {
    if (!existsSync(directory)) continue
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      if (!entry.isFile() || path.extname(entry.name).toLowerCase() !== '.t1os') continue
      try {
        images.push(await validateImageLayout(path.join(directory, entry.name)))
      } catch {
        // Empty, inaccessible, or invalid bundles are ignored during automatic detection.
      }
    }
  }
  return images.length === 1 ? images[0] : null
}

async function chooseImage() {
  if (activeProcess) throw new Error('wait for the current flash to finish.')
  const result = await dialog.showOpenDialog(mainWindow!, {
    title: 'Select The One OS USB installer',
    properties: ['openFile'],
    filters: [{ name: 'The One OS USB installer', extensions: ['t1os'] }],
  })
  if (result.canceled || result.filePaths.length !== 1) return null
  return validateImageLayout(result.filePaths[0])
}

function validateTarget(value: unknown): UsbTarget {
  if (!value || typeof value !== 'object') throw new Error('USB target data was invalid.')
  const target = value as Record<string, unknown>
  const result: UsbTarget = {
    diskNumber: Number(target.diskNumber),
    friendlyName: String(target.friendlyName ?? '').trim(),
    serialNumber: String(target.serialNumber ?? '').trim(),
    sizeBytes: Number(target.sizeBytes),
    sizeGiB: Number(target.sizeGiB),
    confirmation: String(target.confirmation ?? ''),
  }
  if (
    !Number.isInteger(result.diskNumber) || result.diskNumber < 1 ||
    !Number.isSafeInteger(result.sizeBytes) || result.sizeBytes <= 0 ||
    !result.friendlyName || !Number.isFinite(result.sizeGiB) || result.sizeGiB <= 0 ||
    !result.confirmation.startsWith(`ERASE DISK ${result.diskNumber} `)
  ) {
    throw new Error('USB target data was invalid.')
  }
  return result
}

function getUsbTargets(): Promise<UsbTarget[]> {
  if (activeProcess) return Promise.reject(new Error('wait for the current flash to finish.'))
  if (!existsSync(flashScriptPath)) return Promise.reject(new Error('the bundled USB writer is missing.'))

  return new Promise((resolve, reject) => {
    execFile(
      'pwsh.exe',
      [
        '-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
        '-File', flashScriptPath, '-ListTargets', '-Json',
      ],
      { windowsHide: true, timeout: 30000, encoding: 'utf8', maxBuffer: 2 * 1024 * 1024 },
      (error, stdout, stderr) => {
        if (error) {
          reject(new Error(stripAnsi(stderr || stdout || error.message).trim()))
          return
        }
        try {
          const jsonLine = stdout.split(/\r?\n/).map((line) => line.trim()).reverse()
            .find((line) => line.startsWith('{'))
          if (!jsonLine) throw new Error('PowerShell did not return USB target data.')
          const parsed = JSON.parse(jsonLine) as { targets?: unknown[] }
          const targets = Array.isArray(parsed.targets) ? parsed.targets.map(validateTarget) : []
          resolve(targets.filter((target) => target.sizeGiB <= 256))
        } catch (parseError) {
          const message = parseError instanceof Error ? parseError.message : String(parseError)
          reject(new Error(`USB targets could not be read: ${message}`))
        }
      },
    )
  })
}

function validateFlashRequest(value: unknown): FlashRequest {
  if (!value || typeof value !== 'object') throw new Error('flash details were not supplied.')
  const request = value as Record<string, unknown>
  const imagePath = typeof request.imagePath === 'string' ? request.imagePath : ''
  const diskNumber = Number(request.diskNumber)
  if (!imagePath || !Number.isInteger(diskNumber) || diskNumber < 1) {
    throw new Error('select a The One OS installer and an eligible USB drive.')
  }
  return { imagePath, diskNumber }
}

function emitProgress(stage: FlashStage, percent: number, message: string) {
  send('flash:progress', { stage, percent, message })
}

function processFlashLine(line: string, error = false) {
  send('flash:log', { line, error })
  const writing = line.match(/^Writing T1OS USB(?: image)?:\s*(\d+)%$/i)
  if (writing) {
    const percent = Math.min(100, Number(writing[1]))
    emitProgress('writing', percent * 0.7, `writing The One OS… ${percent}%`)
    return
  }
  const verifying = line.match(/^Verifying T1OS USB(?: image)?:\s*(\d+)%$/i)
  if (verifying) {
    const percent = Math.min(100, Number(verifying[1]))
    emitProgress('verifying', 70 + percent * 0.3, `validating USB… ${percent}%`)
    return
  }
  if (/expanding the T1OS root|revalidating.*root|roothealth/i.test(line)) {
    emitProgress('verifying', 100, 'finalising the USB drive…')
    return
  }
  if (/locking|dismounting|offline|preparing capacity-independent/i.test(line)) {
    emitProgress('preparing', 0, 'preparing the USB drive…')
  }
}

async function startFlash(value: unknown) {
  if (activeProcess) return { accepted: false, message: 'a flash is already running.' }

  let request: FlashRequest
  let image: ImageInfo
  try {
    request = validateFlashRequest(value)
    image = await validateImageLayout(request.imagePath)
  } catch (error) {
    return { accepted: false, message: error instanceof Error ? error.message : String(error) }
  }

  let target: UsbTarget | undefined
  try {
    target = (await getUsbTargets()).find((candidate) => candidate.diskNumber === request.diskNumber)
  } catch (error) {
    return { accepted: false, message: error instanceof Error ? error.message : String(error) }
  }
  if (!target) return { accepted: false, message: 'the selected USB drive is no longer eligible or connected.' }
  if (target.sizeBytes < image.minimumTargetBytes) {
    return {
      accepted: false,
      message: `the selected USB drive is smaller than the required ${image.minimumTargetGiB} GiB.`,
    }
  }

  if (activeProcess) return { accepted: false, message: 'a flash is already running.' }

  emitProgress('validating', 0, 'validating The One OS installer…')
  send('flash:state', { running: true })

  const child = spawn(
    'pwsh.exe',
    [
      '-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
      '-File', flashScriptPath,
      '-DiskNumber', String(target.diskNumber),
      '-ImagePath', image.path,
      '-Confirmation', target.confirmation,
      '-EndUserImage',
      '-Confirm:$false',
    ],
    {
      windowsHide: true,
      cwd: path.dirname(flashScriptPath),
      env: { ...process.env, NO_COLOR: '1', TERM: 'dumb' },
    },
  )
  activeProcess = child
  powerSaveBlockerId = powerSaveBlocker.start('prevent-app-suspension')

  pipeLines(child, 'stdout', (line) => processFlashLine(line))
  pipeLines(child, 'stderr', (line) => processFlashLine(line, true))

  let completed = false
  const finish = (exitCode: number | null) => {
    if (completed) return
    completed = true
    const succeeded = exitCode === 0
    activeProcess = null
    if (powerSaveBlockerId !== null && powerSaveBlocker.isStarted(powerSaveBlockerId)) {
      powerSaveBlocker.stop(powerSaveBlockerId)
    }
    powerSaveBlockerId = null
    if (succeeded) {
      emitProgress(
        'complete',
        100,
        'The One OS is ready. Keep the USB connected, restart the computer, and select it from the one-time boot menu.',
      )
    } else {
      emitProgress('error', 0, 'the USB could not be flashed. Open details for the error.')
    }
    send('flash:state', { running: false, succeeded, exitCode })
  }

  child.once('error', (error) => {
    processFlashLine(`could not start the USB writer: ${error.message}`, true)
    finish(null)
  })
  child.once('close', finish)
  return { accepted: true }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 500,
    height: 670,
    minWidth: 500,
    minHeight: 670,
    backgroundColor: '#090b0e',
    title: productName,
    icon: appIcon,
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })

  mainWindow.once('ready-to-show', () => mainWindow?.show())
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  mainWindow.webContents.on('will-navigate', (event) => event.preventDefault())
  mainWindow.on('close', (event) => {
    if (!activeProcess) return
    event.preventDefault()
    void dialog.showMessageBox(mainWindow!, {
      type: 'warning',
      title: 'Flash in progress',
      message: 'Keep the flasher open until writing and verification have finished.',
      buttons: ['ok'],
    })
  })

  const devServerUrl = process.env.VITE_DEV_SERVER_URL
  if (devServerUrl) void mainWindow.loadURL(devServerUrl)
  else void mainWindow.loadFile(path.join(__dirname, '..', 'dist', 'index.html'))

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

app.whenReady().then(() => {
  app.setAboutPanelOptions({
    applicationName: productName,
    applicationVersion: app.getVersion(),
    iconPath: logoPath,
  })
  ipcMain.handle('image:detect', () => detectImage())
  ipcMain.handle('image:choose', () => chooseImage())
  ipcMain.handle('usb:list', () => getUsbTargets())
  ipcMain.handle('flash:start', (_event, value: unknown) => startFlash(value))
  createWindow()
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
