import { app, BrowserWindow, ipcMain, nativeImage, shell } from 'electron'
import { execFile, spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { existsSync, readFileSync, renameSync, statSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { commandCatalogue, type CommandId, type CommandInput, type DiskRequirement } from './commands'

type DiskStatus = 'mounted' | 'unmounted' | 'error'
type DiskHealth = 'ok' | 'corrupted' | 'checking' | 'unavailable'
type DebugMode = 'on' | 'off' | 'checking' | 'unavailable'
type DiskUser =
  | { state: 'user'; username: string }
  | { state: 'none' | 'unavailable' }

interface CommandDefinition {
  label: string
  script: string
  arguments?: readonly string[]
  disk?: DiskRequirement
  input?: CommandInput
  recordsPush?: boolean
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
  protectedTargets: Omit<UsbTarget, 'confirmation'>[]
}

interface DiskHealthCheckResult {
  health: DiskHealth
  diagnostics: string[]
}

function isProjectRoot(candidate: string) {
  return ['scripts', 'environment', 'source'].every((name) =>
    existsSync(path.join(candidate, name)),
  )
}

function findProjectRoot(startPath: string | undefined) {
  if (!startPath) return null

  let candidate = path.resolve(startPath)
  while (true) {
    if (isProjectRoot(candidate)) return candidate
    const parent = path.dirname(candidate)
    if (parent === candidate) return null
    candidate = parent
  }
}

function resolveProjectRoot() {
  const configuredRoot = process.env.T1OS_PROJECT_ROOT
  if (configuredRoot) {
    const resolvedRoot = path.resolve(configuredRoot)
    if (!isProjectRoot(resolvedRoot)) {
      throw new Error(`T1OS_PROJECT_ROOT is not a t1os project directory: ${resolvedRoot}`)
    }
    return resolvedRoot
  }

  const candidates = [
    process.env.PORTABLE_EXECUTABLE_DIR,
    path.dirname(process.execPath),
    process.cwd(),
    path.resolve(__dirname, '..', '..'),
  ]

  for (const candidate of candidates) {
    const root = findProjectRoot(candidate)
    if (root) return root
  }

  throw new Error(
    'The t1os project directory could not be found. Keep the portable executable inside the t1os project tree or set T1OS_PROJECT_ROOT.',
  )
}

const projectRoot = resolveProjectRoot()
const scriptsRoot = path.join(projectRoot, 'scripts')
const diskImagePath = path.join(projectRoot, 'environment', 'storage.img')
const versionFile = path.join(projectRoot, 'current_version.txt')
const lastPushFile = path.join(projectRoot, 'last_push.txt')
const defaultVersion = '0.32'
const appIconPath = app.isPackaged
  ? path.join(process.resourcesPath, 't1oscommandcentrelogo.png')
  : path.join(projectRoot, 'software', 'command centre', 'src', 'assets', 't1oscommandcentrelogo.png')
const appIcon = nativeImage.createFromPath(appIconPath)

if (appIcon.isEmpty()) {
  throw new Error(`T1OS Command Centre logo could not be loaded: ${appIconPath}`)
}

app.setName('T1OS Command Centre')
app.setAppUserModelId('t1os.command-centre')

function migratePersistenceFile(legacyName: string, currentPath: string) {
  const legacyPath = path.join(projectRoot, legacyName)
  if (!existsSync(currentPath) && existsSync(legacyPath)) {
    renameSync(legacyPath, currentPath)
  }
}

migratePersistenceFile('current-version.txt', versionFile)
migratePersistenceFile('last-push.txt', lastPushFile)

const commands = Object.fromEntries(
  Object.entries(commandCatalogue).map(([id, definition]) => [
    id,
    { ...definition, script: path.join(scriptsRoot, definition.script) },
  ]),
) as unknown as Record<CommandId, CommandDefinition>

function isCommandId(value: unknown): value is CommandId {
  return typeof value === 'string' && Object.prototype.hasOwnProperty.call(commands, value)
}

let mainWindow: BrowserWindow | null = null
let activeProcess: ChildProcessWithoutNullStreams | null = null
let activeCommand: CommandId | null = null
let cancelRequestedFor: CommandId | null = null
let commandStarting = false
let currentDiskStatus: DiskStatus | null = null
let currentDiskHealth: DiskHealth = 'unavailable'
let currentDiskUser: DiskUser = { state: 'unavailable' }
let currentDebugMode: DebugMode = 'unavailable'
let cachedHealth: Exclude<DiskHealth, 'checking' | 'unavailable'> | null = null
let cachedHealthSignature: string | null = null
let healthCheckPromise: Promise<DiskHealth> | null = null
let diskUserPromise: Promise<DiskUser> | null = null
let debugModePromise: Promise<DebugMode> | null = null

function validateVersion(value: unknown) {
  if (typeof value !== 'string') throw new Error('current version must be text.')
  const version = value.trim()
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(version)) {
    throw new Error('use letters, numbers, dots, underscores, or hyphens for the current version.')
  }
  return version
}

function getCurrentVersion() {
  if (!existsSync(versionFile)) {
    writeFileSync(versionFile, `${defaultVersion}\n`, 'utf8')
    return defaultVersion
  }

  return validateVersion(readFileSync(versionFile, 'utf8'))
}

function setCurrentVersion(value: unknown) {
  const version = validateVersion(value)
  writeFileSync(versionFile, `${version}\n`, 'utf8')
  return version
}

function formatLastPush(date = new Date()) {
  const pad = (value: number) => value.toString().padStart(2, '0')
  const atreyanYear = date.getFullYear() - 2020
  return [
    pad(date.getHours()),
    pad(date.getMinutes()),
    pad(date.getDate()),
    pad(date.getMonth() + 1),
    `${atreyanYear}AE`,
  ].join(':')
}

function getLastPush() {
  if (!existsSync(lastPushFile)) return null
  const timestamp = readFileSync(lastPushFile, 'utf8').trim()
  return /^\d{2}:\d{2}:\d{2}:\d{2}:\d+AE$/.test(timestamp) ? timestamp : null
}

function recordLastPush() {
  const timestamp = formatLastPush()
  writeFileSync(lastPushFile, `${timestamp}\n`, 'utf8')
  return timestamp
}

function send(channel: string, payload: unknown) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(channel, payload)
  }
}

function stripAnsi(value: string) {
  return value.replace(/[\u001B\u009B][[\]()#;?]*(?:(?:(?:[a-zA-Z\d]*(?:;[-a-zA-Z\d/#&.:=?%@~_]+)*)?\u0007)|(?:(?:\d{1,4}(?:[;:]\d{0,4})*)?[\dA-PR-TZcf-nq-uy=><~]))/g, '')
}

function pipeLines(
  process: ChildProcessWithoutNullStreams,
  stream: 'stdout' | 'stderr',
  onLine: (line: string, stream: 'stdout' | 'stderr') => void,
) {
  let remainder = ''
  process[stream].setEncoding('utf8')
  process[stream].on('data', (chunk: string) => {
    const lines = (remainder + stripAnsi(chunk)).split(/\r?\n/)
    remainder = lines.pop() ?? ''
    for (const line of lines) {
      if (line.trim()) onLine(line, stream)
    }
  })
  process[stream].on('end', () => {
    if (remainder.trim()) onLine(remainder, stream)
  })
}

function setDiskHealth(health: DiskHealth) {
  currentDiskHealth = health
  send('disk:health', health)
  return health
}

function retainLastDiskHealth() {
  return setDiskHealth(cachedHealth ?? 'unavailable')
}

function setDiskUser(user: DiskUser) {
  currentDiskUser = user
  send('disk:user', user)
  return user
}

function refreshDiskUser(): Promise<DiskUser> {
  if (diskUserPromise) return diskUserPromise
  if (commandStarting || activeProcess || currentDiskStatus !== 'mounted') {
    return Promise.resolve(setDiskUser({ state: 'unavailable' }))
  }

  const readUserCommand = [
    'user_file="/mnt/t1fs/the one/master/master.txt"',
    'if [ ! -f "$user_file" ]; then exit 3; fi',
    'IFS= read -r first_line < "$user_file" || exit 4',
    'username=${first_line%%:*}',
    'if [ "$username" = "$first_line" ]; then exit 4; fi',
    'case "$username" in ""|*[!A-Za-z0-9._-]*) exit 4;; esac',
    'case "$username" in [A-Za-z0-9]*) :;; *) exit 4;; esac',
    'if [ "${#username}" -gt 32 ]; then exit 4; fi',
    'printf "%s\\n" "$username"',
  ].join('\n')

  diskUserPromise = new Promise<DiskUser>((resolve) => {
    execFile(
      'wsl.exe',
      ['-u', 'root', '--exec', 'nsenter', '-t', '1', '-m', '--', 'sh', '-c', readUserCommand],
      { windowsHide: true, timeout: 15000, encoding: 'utf8' },
      (error, stdout) => {
        if (commandStarting || activeProcess || currentDiskStatus !== 'mounted') {
          resolve(setDiskUser({ state: 'unavailable' }))
          return
        }

        if (error) {
          const exitCode = typeof error.code === 'number' ? error.code : null
          resolve(setDiskUser(exitCode === 3 ? { state: 'none' } : { state: 'unavailable' }))
          return
        }

        const username = stdout.split(/\r?\n/, 1)[0].trim()
        if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$/.test(username)) {
          resolve(setDiskUser({ state: 'unavailable' }))
          return
        }

        resolve(setDiskUser({ state: 'user', username }))
      },
    )
  }).finally(() => {
    diskUserPromise = null
  })

  return diskUserPromise
}

function setDebugMode(mode: DebugMode) {
  currentDebugMode = mode
  send('disk:debug-mode', mode)
  return mode
}

const readDebugModeCommand = [
  'set -eu',
  'mount_point=$1',
  'mountpoint -q "$mount_point"',
  'python3 - "$mount_point" <<\'PY\'',
  'import os',
  'import re',
  'import sys',
  '',
  'mount_point = sys.argv[1]',
  'roots = [',
  '    os.path.join(mount_point, "the one", "build"),',
  '    os.path.join(mount_point, "boot"),',
  '    os.path.join(mount_point, "software"),',
  ']',
  'pattern = re.compile(r"^[ \\t]*(?:DEBUG[A-Z0-9_]*|_DEBUG_[A-Z0-9_]*)[ \\t]*=[ \\t]*(True|False)[ \\t]*(?:#.*)?$", re.MULTILINE)',
  'found = False',
  'enabled = False',
  'for root in roots:',
  '    if not os.path.isdir(root):',
  '        continue',
  '    for directory, subdirectories, filenames in os.walk(root, followlinks=False):',
  '        subdirectories.sort()',
  '        for filename in sorted(filenames):',
  '            if not filename.endswith(".py"):',
  '                continue',
  '            path = os.path.join(directory, filename)',
  '            if os.path.islink(path):',
  '                continue',
  '            with open(path, "r", encoding="utf-8") as handle:',
  '                matches = pattern.findall(handle.read())',
  '            if matches:',
  '                found = True',
  '                enabled = enabled or "True" in matches',
  'print("on" if enabled else "off" if found else "unavailable")',
  'PY',
].join('\n')

function refreshDebugMode(): Promise<DebugMode> {
  if (debugModePromise) return debugModePromise
  if (currentDiskStatus !== 'mounted') {
    return Promise.resolve(setDebugMode('unavailable'))
  }
  if (commandStarting || activeProcess) return Promise.resolve(currentDebugMode)

  const previousMode = currentDebugMode === 'on' || currentDebugMode === 'off'
    ? currentDebugMode
    : 'unavailable'
  if (previousMode === 'unavailable') setDebugMode('checking')

  debugModePromise = new Promise<DebugMode>((resolve) => {
    execFile(
      'wsl.exe',
      [
        '-u', 'root', '--exec',
        'nsenter', '-t', '1', '-m', '--',
        'sh', '-c', readDebugModeCommand, 'sh', '/mnt/t1fs',
      ],
      { windowsHide: true, timeout: 15000, encoding: 'utf8' },
      (error, stdout) => {
        if (commandStarting || activeProcess) {
          resolve(setDebugMode(previousMode))
          return
        }
        if (error || currentDiskStatus !== 'mounted') {
          resolve(setDebugMode('unavailable'))
          return
        }

        const mode = stdout.trim()
        resolve(setDebugMode(mode === 'on' || mode === 'off' ? mode : 'unavailable'))
      },
    )
  }).finally(() => {
    debugModePromise = null
  })

  return debugModePromise
}

function getDiskImageSignature() {
  try {
    if (!existsSync(diskImagePath)) return null
    const stats = statSync(diskImagePath)
    return `${stats.size}:${stats.mtimeMs}`
  } catch {
    return null
  }
}

const readDiskStatusCommand = [
  'set -eu',
  'image_path=$1',
  'mount_point=$2',
  'if ! mountpoint -q "$mount_point"; then echo unmounted; exit 0; fi',
  'source_device=$(findmnt -rn -o SOURCE -T "$mount_point" | head -n 1)',
  'source_device=${source_device%%\\[*}',
  'case "$source_device" in /dev/loop*) ;; *) echo error; exit 0;; esac',
  'backing_file=$(losetup -n -O BACK-FILE "$source_device" 2>/dev/null | head -n 1)',
  '[ -n "$backing_file" ] || { echo error; exit 0; }',
  'if [ "$(readlink -f "$backing_file")" = "$(readlink -f "$image_path")" ]; then echo mounted; else echo error; fi',
].join('\n')

async function readDiskStatus(): Promise<DiskStatus> {
  try {
    const wslDiskImagePath = await getWslDiskImagePath()
    return await new Promise<DiskStatus>((resolve) => {
      execFile(
        'wsl.exe',
        [
          '-u', 'root', '--exec',
          'nsenter', '-t', '1', '-m', '--',
          'sh', '-c', readDiskStatusCommand, 'sh', wslDiskImagePath, '/mnt/t1fs',
        ],
        { windowsHide: true, timeout: 15000, encoding: 'utf8' },
        (error, stdout) => {
          if (error) {
            resolve('error')
            return
          }
          const state = stdout.trim()
          resolve(state === 'mounted' || state === 'unmounted' ? state : 'error')
        },
      )
    })
  } catch {
    return 'error'
  }
}

function getWslDiskImagePath(): Promise<string> {
  return new Promise((resolve, reject) => {
    execFile(
      'wsl.exe',
      ['--exec', 'wslpath', '-a', diskImagePath],
      { windowsHide: true, timeout: 15000, encoding: 'utf8' },
      (error, stdout) => {
        const translatedPath = stdout.trim()
        if (error || !translatedPath) {
          reject(error ?? new Error('WSL returned an empty disk image path.'))
          return
        }
        resolve(translatedPath)
      },
    )
  })
}

function getWindowsDiskMountPath(): Promise<string> {
  return new Promise((resolve, reject) => {
    execFile(
      'wsl.exe',
      ['--exec', 'wslpath', '-w', '/mnt/t1fs'],
      { windowsHide: true, timeout: 15000, encoding: 'utf8' },
      (error, stdout) => {
        const translatedPath = stdout.trim()
        if (error || !translatedPath) {
          reject(error ?? new Error('WSL returned an empty disk mount path.'))
          return
        }
        resolve(translatedPath)
      },
    )
  })
}

async function openDiskRoot() {
  if (commandStarting || activeProcess) {
    return { opened: false, message: 'wait for the current command to finish.' }
  }

  const status = await refreshDiskStatus()
  if (commandStarting || activeProcess) {
    return { opened: false, message: 'wait for the current command to finish.' }
  }
  if (status !== 'mounted') {
    return { opened: false, message: 'the disk must be mounted before it can be opened.' }
  }

  try {
    const windowsPath = await getWindowsDiskMountPath()
    const errorMessage = await shell.openPath(windowsPath)
    if (errorMessage) throw new Error(errorMessage)
    send('command:output', { stream: 'system', line: 'opened the disk root in windows explorer.' })
    return { opened: true }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    return { opened: false, message: `could not open the disk root: ${message}` }
  }
}

function runReadOnlyHealthCheck(wslDiskImagePath: string): Promise<DiskHealthCheckResult> {
  return new Promise((resolve) => {
    execFile(
      'wsl.exe',
      ['-u', 'root', '--exec', '/usr/sbin/e2fsck', '-f', '-n', wslDiskImagePath],
      { windowsHide: true, timeout: 5 * 60 * 1000, encoding: 'utf8', maxBuffer: 4 * 1024 * 1024 },
      (error, stdout, stderr) => {
        const diagnostics = stripAnsi(`${stdout}\n${stderr}`)
          .split(/\r?\n/)
          .map((line) => line.trimEnd())
          .filter((line) => line.trim())

        if (!error) {
          resolve({ health: 'ok', diagnostics: [] })
          return
        }

        const exitCode = typeof error.code === 'number' ? error.code : null
        resolve({
          health: exitCode === 4 ? 'corrupted' : 'unavailable',
          diagnostics,
        })
      },
    )
  })
}

function refreshDiskHealth(): Promise<DiskHealth> {
  if (healthCheckPromise) return healthCheckPromise
  if (commandStarting || activeProcess || currentDiskStatus !== 'unmounted') {
    return Promise.resolve(retainLastDiskHealth())
  }

  const signature = getDiskImageSignature()
  if (!signature) return Promise.resolve(retainLastDiskHealth())
  if (cachedHealth && cachedHealthSignature === signature) {
    return Promise.resolve(setDiskHealth(cachedHealth))
  }

  setDiskHealth('checking')
  healthCheckPromise = (async () => {
    try {
      const wslDiskImagePath = await getWslDiskImagePath()
      const checkResult = await runReadOnlyHealthCheck(wslDiskImagePath)
      const [statusAfterCheck, signatureAfterCheck] = await Promise.all([
        readDiskStatus(),
        Promise.resolve(getDiskImageSignature()),
      ])

      currentDiskStatus = statusAfterCheck
      send('disk:status', statusAfterCheck)
      if (statusAfterCheck !== 'unmounted' || signatureAfterCheck !== signature) {
        return retainLastDiskHealth()
      }

      if (checkResult.health !== 'ok') {
        for (const line of checkResult.diagnostics) {
          send('command:output', { line, stream: 'stderr' })
        }
      }

      if (checkResult.health === 'ok' || checkResult.health === 'corrupted') {
        cachedHealth = checkResult.health
        cachedHealthSignature = signature
        return setDiskHealth(checkResult.health)
      }
      return retainLastDiskHealth()
    } catch {
      return retainLastDiskHealth()
    } finally {
      healthCheckPromise = null
    }
  })()

  return healthCheckPromise
}

async function refreshDiskStatus(): Promise<DiskStatus> {
  const status = await readDiskStatus()
  currentDiskStatus = status
  send('disk:status', status)

  if (status === 'mounted') {
    cachedHealthSignature = null
    retainLastDiskHealth()
    if (commandStarting || activeProcess) setDiskUser({ state: 'unavailable' })
    else {
      void refreshDiskUser()
      void refreshDebugMode()
    }
  } else if (status === 'unmounted' && !commandStarting && !activeProcess) {
    setDiskUser({ state: 'unavailable' })
    setDebugMode('unavailable')
    void refreshDiskHealth()
  } else {
    retainLastDiskHealth()
    setDiskUser({ state: 'unavailable' })
    setDebugMode('unavailable')
  }

  return status
}

function finishCommand(id: CommandId, definition: CommandDefinition, exitCode: number | null) {
  const succeeded = exitCode === 0
  const cancelled = cancelRequestedFor === id
  if (succeeded && definition.recordsPush) {
    try {
      send('push:last', recordLastPush())
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      send('command:output', {
        stream: 'stderr',
        line: `could not save the last push timestamp: ${message}`,
      })
    }
  }
  send('command:output', {
    stream: cancelled ? 'system' : succeeded ? 'stdout' : 'stderr',
    line: cancelled
      ? `${definition.label} was stopped.`
      : succeeded
      ? `${definition.label} completed successfully.`
      : `${definition.label} failed with exit code ${exitCode ?? 'unknown'}.`,
  })
  activeProcess = null
  activeCommand = null
  cancelRequestedFor = null
  send('command:state', { running: false, id, label: definition.label, succeeded, cancelled, exitCode })
  void refreshDiskStatus()
}

async function cancelActiveCommand() {
  const child = activeProcess
  const id = activeCommand
  if (!child || !id) return { cancelled: false, message: 'no command is running.' }
  if (cancelRequestedFor) return { cancelled: false, message: 'the stop request is already in progress.' }

  cancelRequestedFor = id
  send('command:output', { stream: 'system', line: `stopping ${commands[id].label} and its child processes...` })

  try {
    if (process.platform === 'win32' && child.pid) {
      await new Promise<void>((resolve, reject) => {
        execFile(
          'taskkill.exe',
          ['/pid', String(child.pid), '/t', '/f'],
          { windowsHide: true, timeout: 15000, encoding: 'utf8' },
          (error) => error ? reject(error) : resolve(),
        )
      })
    } else {
      child.kill('SIGTERM')
    }
    return { cancelled: true }
  } catch (error) {
    if (activeProcess !== child) return { cancelled: true }
    cancelRequestedFor = null
    const message = error instanceof Error ? error.message : String(error)
    send('command:output', { stream: 'stderr', line: `could not stop the command: ${message}` })
    return { cancelled: false, message }
  }
}

function validateCreateUserRequest(value: unknown): CreateUserRequest {
  if (!value || typeof value !== 'object') throw new Error('user details were not supplied.')

  const candidate = value as Record<string, unknown>
  const username = typeof candidate.username === 'string' ? candidate.username.trim() : ''
  const password = typeof candidate.password === 'string' ? candidate.password : ''

  validateUsername(username)
  validateNewPassword(password)

  return { username, password }
}

function validateUsername(username: string) {
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$/.test(username)) {
    throw new Error('the username must contain 1–32 letters, numbers, dots, underscores, or hyphens and start with a letter or number.')
  }
}

function validateCurrentPassword(password: string) {
  if (!password || password.length > 32 || new TextEncoder().encode(password).length > 128 || /[\u0000\r\n]/.test(password)) {
    throw new Error('enter the current password (maximum 32 characters and 128 UTF-8 bytes).')
  }
}

function validateNewPassword(password: string) {
  if (password.length < 4 || password.length > 32 || new TextEncoder().encode(password).length > 128 || /[\u0000\r\n]/.test(password)) {
    throw new Error('the password must contain 4–32 characters, use at most 128 UTF-8 bytes, and contain no line breaks.')
  }
}

function validateChangeUserRequest(value: unknown): ChangeUserRequest {
  if (!value || typeof value !== 'object') throw new Error('user changes were not supplied.')
  const candidate = value as Record<string, unknown>
  const username = typeof candidate.username === 'string' ? candidate.username.trim() : ''
  const currentPassword = typeof candidate.currentPassword === 'string' ? candidate.currentPassword : ''
  const newPassword = typeof candidate.newPassword === 'string' ? candidate.newPassword : ''
  const changePassword = candidate.changePassword === true

  validateUsername(username)
  validateCurrentPassword(currentPassword)
  if (changePassword) validateNewPassword(newPassword)
  if (!changePassword && newPassword) throw new Error('a new password was supplied without requesting a password change.')
  return { username, currentPassword, newPassword, changePassword }
}

function validateRemoveUserRequest(value: unknown): RemoveUserRequest {
  if (!value || typeof value !== 'object') throw new Error('user removal details were not supplied.')
  const candidate = value as Record<string, unknown>
  const username = typeof candidate.username === 'string' ? candidate.username.trim() : ''
  const password = typeof candidate.password === 'string' ? candidate.password : ''
  validateUsername(username)
  validateCurrentPassword(password)
  return { username, password }
}

function validateFlashUsbRequest(value: unknown): FlashUsbRequest {
  if (!value || typeof value !== 'object') throw new Error('USB target details were not supplied.')

  const candidate = value as Record<string, unknown>
  const diskNumber = candidate.diskNumber
  const confirmation = typeof candidate.confirmation === 'string' ? candidate.confirmation.trim() : ''
  if (!Number.isInteger(diskNumber) || (diskNumber as number) < 1 || (diskNumber as number) > 1024) {
    throw new Error('the USB disk number must be an integer between 1 and 1024.')
  }
  if (!confirmation.startsWith(`ERASE DISK ${diskNumber} `) || confirmation.length > 512) {
    throw new Error(`type the complete confirmation beginning with ERASE DISK ${diskNumber}.`)
  }
  if (/[\u0000-\u001f\u007f]/.test(confirmation)) {
    throw new Error('the USB confirmation contains invalid control characters.')
  }

  return { diskNumber: diskNumber as number, confirmation }
}

function validateWirelessRequest(value: unknown): WirelessRequest {
  if (!value || typeof value !== 'object') throw new Error('Wi-Fi settings were not supplied.')

  const candidate = value as Record<string, unknown>
  const ssid = typeof candidate.ssid === 'string' ? candidate.ssid.trim() : ''
  const security = typeof candidate.security === 'string' ? candidate.security.toLowerCase() : ''
  const passphrase = typeof candidate.passphrase === 'string' ? candidate.passphrase : ''
  const bytes = new TextEncoder()
  if (!ssid || bytes.encode(ssid).length > 32 || /[\u0000\r\n=]/.test(ssid)) {
    throw new Error('the Wi-Fi name must contain 1–32 UTF-8 bytes and no control characters or equals sign.')
  }
  if (!['open', 'wpa2', 'wpa3'].includes(security)) {
    throw new Error('select open, WPA2, or WPA3 security.')
  }
  if (security !== 'open' && (bytes.encode(passphrase).length < 8 || bytes.encode(passphrase).length > 63)) {
    throw new Error('the Wi-Fi passphrase must contain 8–63 UTF-8 bytes.')
  }
  if (/[\u0000\r\n]/.test(passphrase)) {
    throw new Error('the Wi-Fi passphrase contains a control character.')
  }
  return { ssid, security: security as WirelessRequest['security'], passphrase }
}

function getUsbTargets(): Promise<UsbTargetList> {
  if (commandStarting || activeProcess) {
    return Promise.reject(new Error('wait for the current command to finish before refreshing USB targets.'))
  }

  const script = commands['list-usb-targets'].script
  return new Promise((resolve, reject) => {
    execFile(
      'pwsh.exe',
      ['-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', script, '-ListTargets', '-Json'],
      { cwd: path.dirname(script), windowsHide: true, timeout: 30000, encoding: 'utf8', maxBuffer: 1024 * 1024 },
      (error, stdout, stderr) => {
        if (error) {
          const detail = stripAnsi(stderr).trim()
          reject(new Error(detail || `USB targets could not be read (${error.message}).`))
          return
        }

        try {
          const parsed = JSON.parse(stdout.trim()) as Record<string, unknown>
          const readTarget = (value: unknown, includeConfirmation: boolean) => {
            if (!value || typeof value !== 'object') throw new Error('a USB target entry was invalid.')
            const item = value as Record<string, unknown>
            const target = {
              diskNumber: Number(item.diskNumber),
              friendlyName: String(item.friendlyName ?? ''),
              serialNumber: String(item.serialNumber ?? ''),
              sizeGiB: Number(item.sizeGiB),
            }
            if (!Number.isInteger(target.diskNumber) || target.diskNumber < 1 || !Number.isFinite(target.sizeGiB)) {
              throw new Error('a USB target identity was invalid.')
            }
            if (!includeConfirmation) return target
            const confirmation = String(item.confirmation ?? '')
            if (!confirmation.startsWith(`ERASE DISK ${target.diskNumber} `)) {
              throw new Error('a USB target confirmation was invalid.')
            }
            return { ...target, confirmation }
          }

          const targets = Array.isArray(parsed.targets)
            ? parsed.targets.map((target) => readTarget(target, true) as UsbTarget)
            : []
          const protectedTargets = Array.isArray(parsed.protectedTargets)
            ? parsed.protectedTargets.map((target) => readTarget(target, false))
            : []
          resolve({ targets, protectedTargets })
        } catch (parseError) {
          const message = parseError instanceof Error ? parseError.message : String(parseError)
          reject(new Error(`USB target data could not be read: ${message}`))
        }
      },
    )
  })
}

async function runCommand(candidateId: unknown, input?: unknown) {
  if (!isCommandId(candidateId)) return { accepted: false, message: 'unknown command.' }
  const id = candidateId
  const definition = commands[id]
  if (commandStarting || activeProcess) {
    const detail = activeCommand ? ` (${activeCommand})` : ''
    return { accepted: false, message: `another command is starting or already running${detail}.` }
  }
  if (healthCheckPromise) {
    return { accepted: false, message: 'wait for the disk health check to finish.' }
  }
  if (!existsSync(definition.script)) {
    return { accepted: false, message: `script not found: ${definition.script}` }
  }

  let commandInput: string | null = null
  const commandArguments = [...(definition.arguments ?? [])]
  if (definition.input === 'create-user') {
    try {
      commandInput = JSON.stringify(validateCreateUserRequest(input))
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      return { accepted: false, message }
    }
  }
  if (definition.input === 'change-user') {
    try {
      commandInput = JSON.stringify(validateChangeUserRequest(input))
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      return { accepted: false, message }
    }
  }
  if (definition.input === 'remove-user') {
    try {
      commandInput = JSON.stringify(validateRemoveUserRequest(input))
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      return { accepted: false, message }
    }
  }
  if (definition.input === 'wireless') {
    try {
      commandInput = JSON.stringify(validateWirelessRequest(input))
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      return { accepted: false, message }
    }
  }
  if (definition.input === 'flash-usb') {
    try {
      const request = validateFlashUsbRequest(input)
      commandArguments.push(
        '-DiskNumber', String(request.diskNumber),
        '-Confirmation', request.confirmation,
        '-Confirm:$false',
      )
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      return { accepted: false, message }
    }
  }

  commandStarting = true
  try {
    const diskRequirement = definition.disk ?? 'none'
    if (diskRequirement !== 'none') {
      const status = await readDiskStatus()
      currentDiskStatus = status
      send('disk:status', status)

      if (activeProcess) {
        return { accepted: false, message: `another command is already running (${activeCommand}).` }
      }
      if (status === 'error') {
        return { accepted: false, message: 'the disk mount state could not be verified.' }
      }
      if (diskRequirement === 'mounted' && status !== 'mounted') {
        return { accepted: false, message: 'the disk must be mounted for this command.' }
      }
      if (diskRequirement === 'unmounted' && status !== 'unmounted') {
        return { accepted: false, message: 'the disk must be unmounted for this command.' }
      }
    }

    send('command:output', { stream: 'system', line: `starting ${definition.label}...` })
    send('command:state', { running: true, id, label: definition.label })
    cachedHealthSignature = null
    retainLastDiskHealth()
    setDiskUser({ state: 'unavailable' })

    const child = spawn(
      'pwsh.exe',
      [
        '-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
        '-File', definition.script, ...commandArguments,
      ],
      {
        cwd: path.dirname(definition.script),
        windowsHide: true,
        env: { ...process.env, NO_COLOR: '1', TERM: 'dumb' },
      },
    )

    activeProcess = child
    activeCommand = id
    let finished = false
    const completeOnce = (exitCode: number | null) => {
      if (finished) return
      finished = true
      finishCommand(id, definition, exitCode)
    }

    pipeLines(child, 'stdout', (line, stream) => send('command:output', { line, stream }))
    pipeLines(child, 'stderr', (line) => send('command:output', { line, stream: 'diagnostic' }))
    child.once('error', (error) => {
      send('command:output', { stream: 'stderr', line: `could not start powershell: ${error.message}` })
      completeOnce(null)
    })
    child.once('close', completeOnce)

    if (commandInput !== null) {
      child.stdin.on('error', () => undefined)
      child.stdin.end(commandInput)
    }

    return { accepted: true }
  } finally {
    commandStarting = false
  }
}

function createWindow() {
  const uiScale = 0.4
  const windowScale = uiScale * 1.7
  const headless = process.env.T1OS_COMMAND_CENTRE_HEADLESS === '1'

  mainWindow = new BrowserWindow({
    width: 970,
    height: 1170,
    minWidth: Math.round(860 * windowScale),
    minHeight: Math.round(680 * windowScale),
    backgroundColor: '#0b0d10',
    title: 'T1OS Command Centre',
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

  mainWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  mainWindow.webContents.on('will-navigate', (event) => event.preventDefault())
  mainWindow.webContents.session.setPermissionRequestHandler((_webContents, _permission, callback) => callback(false))
  mainWindow.webContents.setZoomFactor(uiScale)
  mainWindow.once('ready-to-show', () => {
    if (!headless) mainWindow?.show()
  })

  const devServerUrl = process.env.VITE_DEV_SERVER_URL
  if (devServerUrl) {
    void mainWindow.loadURL(devServerUrl)
  } else {
    void mainWindow.loadFile(path.join(__dirname, '..', 'dist', 'index.html'))
  }

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

app.whenReady().then(() => {
  if (process.platform === 'darwin') app.dock?.setIcon(appIcon)
  app.setAboutPanelOptions({
    applicationName: 'T1OS Command Centre',
    applicationVersion: app.getVersion(),
    iconPath: appIconPath,
  })
  ipcMain.handle('command:run', (_event, id: unknown, input?: unknown) => runCommand(id, input))
  ipcMain.handle('command:cancel', () => cancelActiveCommand())
  ipcMain.handle('disk:get-status', () => refreshDiskStatus())
  ipcMain.handle('disk:get-health', () => refreshDiskHealth())
  ipcMain.handle('disk:get-user', () => refreshDiskUser())
  ipcMain.handle('disk:get-debug-mode', () => refreshDebugMode())
  ipcMain.handle('disk:open', () => openDiskRoot())
  ipcMain.handle('usb:get-targets', () => getUsbTargets())
  ipcMain.handle('push:get-last', () => getLastPush())
  ipcMain.handle('version:get', () => getCurrentVersion())
  ipcMain.handle('version:set', (_event, value: unknown) => setCurrentVersion(value))
  createWindow()
  void refreshDiskStatus()
  const statusTimer = setInterval(() => void refreshDiskStatus(), 3000)
  statusTimer.unref()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
