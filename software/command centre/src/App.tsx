import { type FormEvent, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import {
  commandCatalogue,
  commandGroups,
  type CommandId,
  type CommandSpec,
} from '../electron/commands'
import commandCentreLogo from './assets/t1oscommandcentrelogo.png'

type Action = CommandSpec & { id: CommandId }

interface ConsoleLine extends CommandOutput {
  id: number
  time: string
}

const actions = (Object.entries(commandCatalogue) as Array<[CommandId, CommandSpec]>)
  .map(([id, definition]) => ({ id, ...definition }))

function timestamp() {
  return new Date().toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export default function App() {
  const [diskStatus, setDiskStatus] = useState<DiskStatus | 'checking'>('checking')
  const [diskHealth, setDiskHealth] = useState<DiskHealth>('unavailable')
  const [diskUser, setDiskUser] = useState<DiskUser>({ state: 'unavailable' })
  const [debugMode, setDebugMode] = useState<DebugMode>('unavailable')
  const [running, setRunning] = useState<CommandState | null>(null)
  const [search, setSearch] = useState('')
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [currentVersion, setCurrentVersion] = useState('')
  const [savedVersion, setSavedVersion] = useState('')
  const [lastPush, setLastPush] = useState<string | null>(null)
  const [createUserOpen, setCreateUserOpen] = useState(false)
  const [newUsername, setNewUsername] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [createUserError, setCreateUserError] = useState('')
  const [accountTarget, setAccountTarget] = useState<'disk' | 'usb'>('disk')
  const [changeUserOpen, setChangeUserOpen] = useState(false)
  const [changedUsername, setChangedUsername] = useState('')
  const [currentPassword, setCurrentPassword] = useState('')
  const [changedPassword, setChangedPassword] = useState('')
  const [confirmChangedPassword, setConfirmChangedPassword] = useState('')
  const [changeUserError, setChangeUserError] = useState('')
  const [removeUserOpen, setRemoveUserOpen] = useState(false)
  const [removeUsername, setRemoveUsername] = useState('')
  const [removePassword, setRemovePassword] = useState('')
  const [removeUserError, setRemoveUserError] = useState('')
  const [flashOpen, setFlashOpen] = useState(false)
  const [flashDiskNumber, setFlashDiskNumber] = useState('')
  const [flashConfirmation, setFlashConfirmation] = useState('')
  const [flashError, setFlashError] = useState('')
  const [flashTargets, setFlashTargets] = useState<UsbTarget[]>([])
  const [protectedFlashTargets, setProtectedFlashTargets] = useState<UsbTargetList['protectedTargets']>([])
  const [flashTargetsLoading, setFlashTargetsLoading] = useState(false)
  const [wirelessOpen, setWirelessOpen] = useState(false)
  const [wirelessSsid, setWirelessSsid] = useState('')
  const [wirelessSecurity, setWirelessSecurity] = useState<'open' | 'wpa2' | 'wpa3'>('open')
  const [wirelessPassphrase, setWirelessPassphrase] = useState('')
  const [wirelessError, setWirelessError] = useState('')
  const [lines, setLines] = useState<ConsoleLine[]>([
    { id: 0, time: timestamp(), line: 'the one os command centre is ready.', stream: 'system' },
  ])
  const nextLineId = useRef(1)
  const consoleOutputRef = useRef<HTMLDivElement>(null)
  const previousDiskStatus = useRef<string>('checking')
  const previousDiskHealth = useRef<DiskHealth>('unavailable')
  const visibleActions = useMemo(() => {
    const query = search.trim().toLowerCase()
    return actions.filter((action) => {
      if (action.advanced && !showAdvanced) return false
      if (!query) return true
      return `${action.label} ${action.detail} ${action.group}`.toLowerCase().includes(query)
    })
  }, [search, showAdvanced])

  const addLine = (output: CommandOutput) => {
    setLines((current) => [
      ...current.slice(-499),
      { ...output, id: nextLineId.current++, time: timestamp() },
    ])
  }

  useLayoutEffect(() => {
    const output = consoleOutputRef.current
    if (output) output.scrollTop = output.scrollHeight
  }, [lines])

  useEffect(() => {
    const removeDiskListener = window.t1os.onDiskStatus((status) => {
      setDiskStatus(status)
      if (status !== previousDiskStatus.current) {
        const message = status === 'error' ? 'could not read the wsl disk status.' : `disk is ${status}.`
        addLine({ line: message, stream: status === 'error' ? 'stderr' : 'system' })
        previousDiskStatus.current = status
      }
    })
    const removeHealthListener = window.t1os.onDiskHealth((health) => {
      setDiskHealth(health)
      if (health !== previousDiskHealth.current) {
        const message = health === 'checking'
          ? 'checking disk health...'
          : health === 'ok'
            ? 'disk health is ok.'
            : health === 'corrupted'
              ? 'disk health check found corruption.'
              : 'disk health is unavailable.'
        addLine({ line: message, stream: health === 'corrupted' ? 'stderr' : 'system' })
        previousDiskHealth.current = health
      }
    })
    const removeUserListener = window.t1os.onDiskUser(setDiskUser)
    const removeDebugModeListener = window.t1os.onDebugMode(setDebugMode)
    const removeLastPushListener = window.t1os.onLastPush(setLastPush)
    const removeOutputListener = window.t1os.onCommandOutput(addLine)
    const removeStateListener = window.t1os.onCommandState((state) => setRunning(state.running ? state : null))
    void window.t1os.getDiskStatus()
    void window.t1os.getDiskHealth().then(setDiskHealth)
    void window.t1os.getDiskUser().then(setDiskUser)
    void window.t1os.getDebugMode().then(setDebugMode)
    void window.t1os.getLastPush()
      .then(setLastPush)
      .catch((error: Error) => addLine({ line: `could not load the last push timestamp: ${error.message}`, stream: 'stderr' }))
    void window.t1os.getCurrentVersion()
      .then((version) => {
        setCurrentVersion(version)
        setSavedVersion(version)
      })
      .catch((error: Error) => addLine({ line: `could not load the current version: ${error.message}`, stream: 'stderr' }))

    return () => {
      removeDiskListener()
      removeHealthListener()
      removeUserListener()
      removeDebugModeListener()
      removeLastPushListener()
      removeOutputListener()
      removeStateListener()
    }
  }, [])

  const saveCurrentVersion = async () => {
    const candidate = currentVersion.trim()
    if (candidate === savedVersion) return

    try {
      const version = await window.t1os.setCurrentVersion(candidate)
      setCurrentVersion(version)
      setSavedVersion(version)
      addLine({ line: `current version set to ${version}.`, stream: 'system' })
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      addLine({ line: `could not save the current version: ${message}`, stream: 'stderr' })
      setCurrentVersion(savedVersion)
    }
  }

  const run = async (id: CommandId) => {
    try {
      const response = await window.t1os.runCommand(id)
      if (!response.accepted) {
        addLine({ line: response.message ?? 'the command could not be started.', stream: 'stderr' })
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      addLine({ line: `the command could not be started: ${message}`, stream: 'stderr' })
    }
  }

  const cancelRunningCommand = async () => {
    if (!running || !window.confirm(`stop ${running.label} and all of its child processes?`)) return
    try {
      const response = await window.t1os.cancelCommand()
      if (!response.cancelled) {
        addLine({ line: response.message ?? 'the command could not be stopped.', stream: 'stderr' })
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      addLine({ line: `the command could not be stopped: ${message}`, stream: 'stderr' })
    }
  }

  const closeFlash = () => {
    setFlashOpen(false)
    setFlashDiskNumber('')
    setFlashConfirmation('')
    setFlashError('')
  }

  const refreshFlashTargets = async () => {
    setFlashTargetsLoading(true)
    setFlashError('')
    try {
      const result = await window.t1os.getUsbTargets()
      setFlashTargets(result.targets)
      setProtectedFlashTargets(result.protectedTargets)
      if (!result.targets.some((target) => String(target.diskNumber) === flashDiskNumber)) {
        setFlashDiskNumber('')
        setFlashConfirmation('')
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      setFlashTargets([])
      setProtectedFlashTargets([])
      setFlashError(`USB targets could not be loaded: ${message}`)
    } finally {
      setFlashTargetsLoading(false)
    }
  }

  const openFlash = () => {
    setFlashOpen(true)
    setFlashDiskNumber('')
    setFlashConfirmation('')
    setFlashError('')
    void refreshFlashTargets()
  }

  const closeWireless = () => {
    setWirelessOpen(false)
    setWirelessSsid('')
    setWirelessSecurity('open')
    setWirelessPassphrase('')
    setWirelessError('')
  }

  const submitWireless = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setWirelessError('')
    try {
      const response = await window.t1os.runCommand('configure-hardware-wireless', {
        ssid: wirelessSsid,
        security: wirelessSecurity,
        passphrase: wirelessPassphrase,
      })
      if (!response.accepted) {
        const message = response.message ?? 'the Wi-Fi settings could not be saved.'
        setWirelessError(message)
        addLine({ line: message, stream: 'stderr' })
        return
      }
      closeWireless()
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      setWirelessError(message)
      addLine({ line: `the Wi-Fi settings could not be saved: ${message}`, stream: 'stderr' })
    }
  }

  const submitFlash = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setFlashError('')
    const diskNumber = Number(flashDiskNumber)
    const selectedTarget = flashTargets.find((target) => target.diskNumber === diskNumber)
    if (!selectedTarget) {
      setFlashError('select an eligible USB target.')
      return
    }
    if (flashConfirmation !== selectedTarget.confirmation) {
      setFlashError(`paste the complete confirmation for disk ${diskNumber}.`)
      return
    }

    try {
      const response = await window.t1os.runCommand('flash-hardware-usb', {
        diskNumber,
        confirmation: flashConfirmation,
      })
      if (!response.accepted) {
        const message = response.message ?? 'the USB flash could not be started.'
        setFlashError(message)
        addLine({ line: message, stream: 'stderr' })
        return
      }
      closeFlash()
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      setFlashError(message)
      addLine({ line: `the USB flash could not be started: ${message}`, stream: 'stderr' })
    }
  }

  const openDisk = async () => {
    const response = await window.t1os.openDisk()
    if (!response.opened) {
      addLine({ line: response.message ?? 'the disk could not be opened.', stream: 'stderr' })
    }
  }

  const closeCreateUser = () => {
    setCreateUserOpen(false)
    setNewUsername('')
    setNewPassword('')
    setConfirmPassword('')
    setCreateUserError('')
  }

  const submitCreateUser = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setCreateUserError('')

    if (!newUsername.trim()) {
      setCreateUserError('enter a username.')
      return
    }
    if (!newPassword) {
      setCreateUserError('enter a password.')
      return
    }
    if (newPassword !== confirmPassword) {
      setCreateUserError('passwords do not match.')
      return
    }

    try {
      const response = await window.t1os.runCommand(accountTarget === 'usb' ? 'create-usb-user' : 'create-user', {
        username: newUsername,
        password: newPassword,
      })
      if (!response.accepted) {
        const message = response.message ?? 'the disk user could not be created.'
        setCreateUserError(message)
        addLine({ line: message, stream: 'stderr' })
        return
      }
      closeCreateUser()
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      setCreateUserError(message)
      addLine({ line: `the disk user could not be created: ${message}`, stream: 'stderr' })
    }
  }

  const openChangeUser = (target: 'disk' | 'usb') => {
    setAccountTarget(target)
    setChangedUsername(target === 'disk' && diskUser.state === 'user' ? diskUser.username : '')
    setCurrentPassword('')
    setChangedPassword('')
    setConfirmChangedPassword('')
    setChangeUserError('')
    setChangeUserOpen(true)
  }

  const closeChangeUser = () => {
    setChangeUserOpen(false)
    setChangedUsername('')
    setCurrentPassword('')
    setChangedPassword('')
    setConfirmChangedPassword('')
    setChangeUserError('')
  }

  const submitChangeUser = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setChangeUserError('')
    const username = changedUsername.trim()
    const changePassword = changedPassword.length > 0
    if (!username) {
      setChangeUserError('enter the new username.')
      return
    }
    if (!currentPassword) {
      setChangeUserError('enter the current password.')
      return
    }
    if (changePassword && changedPassword !== confirmChangedPassword) {
      setChangeUserError('new passwords do not match.')
      return
    }
    if (accountTarget === 'disk' && diskUser.state === 'user' && username === diskUser.username && !changePassword) {
      setChangeUserError('change the username, enter a new password, or both.')
      return
    }

    try {
      const response = await window.t1os.runCommand(accountTarget === 'usb' ? 'change-usb-user' : 'change-user', {
        username,
        currentPassword,
        newPassword: changedPassword,
        changePassword,
      })
      if (!response.accepted) {
        const message = response.message ?? 'the disk user could not be changed.'
        setChangeUserError(message)
        addLine({ line: message, stream: 'stderr' })
        return
      }
      closeChangeUser()
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      setChangeUserError(message)
      addLine({ line: `the disk user could not be changed: ${message}`, stream: 'stderr' })
    }
  }

  const openRemoveUser = (target: 'disk' | 'usb') => {
    setAccountTarget(target)
    setRemoveUsername('')
    setRemovePassword('')
    setRemoveUserError('')
    setRemoveUserOpen(true)
  }

  const closeRemoveUser = () => {
    setRemoveUserOpen(false)
    setRemoveUsername('')
    setRemovePassword('')
    setRemoveUserError('')
  }

  const submitRemoveUser = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setRemoveUserError('')
    if (accountTarget === 'disk' && diskUser.state !== 'user') {
      setRemoveUserError('the active disk user could not be read.')
      return
    }
    if (accountTarget === 'disk' && diskUser.state === 'user' && removeUsername.trim() !== diskUser.username) {
      setRemoveUserError(`type ${diskUser.username} exactly to confirm removal.`)
      return
    }
    if (!removePassword) {
      setRemoveUserError('enter the current password.')
      return
    }

    try {
      const response = await window.t1os.runCommand(accountTarget === 'usb' ? 'remove-usb-user' : 'remove-user', {
        username: removeUsername.trim(),
        password: removePassword,
      })
      if (!response.accepted) {
        const message = response.message ?? 'the disk user could not be removed.'
        setRemoveUserError(message)
        addLine({ line: message, stream: 'stderr' })
        return
      }
      closeRemoveUser()
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      setRemoveUserError(message)
      addLine({ line: `the disk user could not be removed: ${message}`, stream: 'stderr' })
    }
  }

  const mounted = diskStatus === 'mounted'
  const selectedFlashTarget = flashTargets.find((target) => String(target.diskNumber) === flashDiskNumber)
  const statusLabel = diskStatus === 'checking' ? 'checking' : diskStatus === 'error' ? 'unavailable' : mounted ? 'mounted' : 'unmounted'
  const healthLabel = diskHealth === 'ok' ? 'ok' : diskHealth
  const diskUserLabel = diskUser.state === 'user'
    ? diskUser.username
    : diskUser.state === 'none'
      ? 'no user'
      : 'unavailable'
  const debugModeLabel = debugMode === 'checking' ? 'checking' : debugMode

  const disabledReason = (action: Action) => {
    if (running) return true
    if (diskHealth === 'checking') return true
    const requirement = action.disk ?? 'none'
    if (requirement !== 'none' && (diskStatus === 'checking' || diskStatus === 'error')) return true
    if (requirement === 'mounted') return !mounted
    if (requirement === 'unmounted') return mounted
    return false
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <img className="brand-logo" src={commandCentreLogo} alt="T1OS Command Centre logo" />
          <div>
            <p className="overline">Development command centre</p>
            <h1>The One OS</h1>
          </div>
        </div>
        <div className="topbar-controls">
          <div className="version-stack">
            <label className="version-control">
              <span>current version</span>
              <input
                aria-label="current version"
                disabled={!savedVersion}
                maxLength={64}
                onBlur={() => void saveCurrentVersion()}
                onChange={(event) => setCurrentVersion(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') event.currentTarget.blur()
                  if (event.key === 'Escape') {
                    setCurrentVersion(savedVersion)
                    event.currentTarget.blur()
                  }
                }}
                spellCheck={false}
                value={currentVersion}
              />
            </label>
            <button
              className="disk-open"
              disabled={!mounted || Boolean(running)}
              onClick={() => void openDisk()}
              type="button"
            >
              open disk
            </button>
          </div>
          <div className="disk-indicators">
            <div className={`disk-status disk-status-primary disk-status--${diskStatus}`} aria-live="polite">
              <span className="disk-label">disk status</span>
              <span className="disk-value">{statusLabel}</span>
              <span className="status-dot" aria-hidden="true" />
            </div>
            <div className={`disk-status disk-health--${diskHealth}`} aria-live="polite">
              <span className="disk-label">disk health</span>
              <span className="disk-value">{healthLabel}</span>
              <span className="status-dot" aria-hidden="true" />
            </div>
            <div className={`disk-user disk-user--${diskUser.state}`} aria-live="polite">
              <span className="disk-user-label">disk user</span>
              <span className="disk-user-value">{diskUserLabel}</span>
            </div>
            <div className={`disk-status debug-mode--${debugMode}`} aria-live="polite">
              <span className="disk-label">debug mode</span>
              <span className="disk-value">{debugModeLabel}</span>
              <span className="status-dot" aria-hidden="true" />
            </div>
          </div>
        </div>
      </header>

      <section className="command-toolbar" aria-label="command filters">
        <label className="command-search">
          <span>find a workflow</span>
          <input
            onChange={(event) => setSearch(event.target.value)}
            placeholder="search builds, tests, USB, Python…"
            spellCheck={false}
            type="search"
            value={search}
          />
        </label>
        <label className="advanced-toggle">
          <input
            checked={showAdvanced}
            onChange={(event) => setShowAdvanced(event.target.checked)}
            type="checkbox"
          />
          <span>advanced workflows</span>
        </label>
        <span className="command-count">{visibleActions.length} of {actions.length} workflows</span>
      </section>

      <section className="workspace" aria-label="development commands">
        {commandGroups.filter((group) => visibleActions.some((action) => action.group === group)).map((group) => (
          <div className={`command-group command-group--${group.toLowerCase().replace(' ', '-')}`} key={group}>
            <div className="group-heading">
              <h2>{group}</h2>
              <span>{visibleActions.filter((action) => action.group === group).length}</span>
            </div>
            <div className="action-grid">
              {visibleActions.filter((action) => action.group === group).map((action) => (
                <div className="command-item" key={action.id}>
                  <button
                    className="command-button"
                    disabled={disabledReason(action)}
                    onClick={() => {
                      if (action.input === 'create-user') {
                        setAccountTarget(action.id === 'create-usb-user' ? 'usb' : 'disk')
                        setCreateUserOpen(true)
                        setCreateUserError('')
                      } else if (action.input === 'change-user') {
                        openChangeUser(action.id === 'change-usb-user' ? 'usb' : 'disk')
                      } else if (action.input === 'remove-user') {
                        openRemoveUser(action.id === 'remove-usb-user' ? 'usb' : 'disk')
                      } else if (action.input === 'flash-usb') {
                        openFlash()
                      } else if (action.input === 'wireless') {
                        setWirelessOpen(true)
                        setWirelessError('')
                      } else if (action.confirm) {
                        if (window.confirm(action.confirm)) {
                          void run(action.id)
                        }
                      } else {
                        void run(action.id)
                      }
                    }}
                  >
                    <span className="command-label">{action.label}</span>
                    <span className="command-detail">{action.detail}</span>
                  </button>
                  {action.recordsPush && (
                    <div className="push-timestamp" aria-live="polite">
                      <span>last push</span>
                      <span>{lastPush ?? 'never'}</span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </section>

      <section className="console-panel" aria-label="command output">
        <div className="console-header">
          <div className="console-title">
            <span className={`activity-light ${running ? 'activity-light--running' : ''}`} />
            <span>output</span>
            <span className="activity-label">{running ? running.label : 'idle'}</span>
          </div>
          <div className="console-actions">
            {running && <button className="stop-button" onClick={() => void cancelRunningCommand()}>stop</button>}
            <button className="clear-button" onClick={() => setLines([])}>clear</button>
          </div>
        </div>
        <div className="console-output" ref={consoleOutputRef} role="log" aria-live="polite">
          {lines.length === 0 && <div className="console-empty">no output.</div>}
          {lines.map((entry) => (
            <div className={`console-line console-line--${entry.stream}`} key={entry.id}>
              <span className="console-time">{entry.time}</span>
              <span>{entry.line}</span>
            </div>
          ))}
        </div>
      </section>

      {createUserOpen && (
        <div className="dialog-backdrop" role="presentation">
          <form
            aria-describedby="create-user-note"
            aria-labelledby="create-user-title"
            aria-modal="true"
            className="user-dialog"
            onSubmit={(event) => void submitCreateUser(event)}
            role="dialog"
          >
            <div className="user-dialog-heading">
              <h2 id="create-user-title">create {accountTarget} user</h2>
              <button aria-label="close create user dialog" className="dialog-close" onClick={closeCreateUser} type="button">×</button>
            </div>
            <p id="create-user-note">
              this replaces the active master credentials on the {accountTarget === 'usb' ? 'validated t1os usb' : 'storage image'}. existing home files are kept.
            </p>
            <label>
              <span>username</span>
              <input
                autoFocus
                maxLength={32}
                onChange={(event) => setNewUsername(event.target.value)}
                spellCheck={false}
                value={newUsername}
              />
            </label>
            <label>
              <span>password</span>
              <input
                autoComplete="new-password"
                maxLength={32}
                onChange={(event) => setNewPassword(event.target.value)}
                type="password"
                value={newPassword}
              />
            </label>
            <label>
              <span>confirm password</span>
              <input
                autoComplete="new-password"
                maxLength={32}
                onChange={(event) => setConfirmPassword(event.target.value)}
                type="password"
                value={confirmPassword}
              />
            </label>
            {createUserError && <p className="dialog-error" role="alert">{createUserError}</p>}
            <div className="dialog-actions">
              <button className="dialog-button dialog-button--secondary" onClick={closeCreateUser} type="button">cancel</button>
              <button className="dialog-button dialog-button--primary" type="submit">create user</button>
            </div>
          </form>
        </div>
      )}

      {changeUserOpen && (
        <div className="dialog-backdrop" role="presentation">
          <form
            aria-describedby="change-user-note"
            aria-labelledby="change-user-title"
            aria-modal="true"
            className="user-dialog"
            onSubmit={(event) => void submitChangeUser(event)}
            role="dialog"
          >
            <div className="user-dialog-heading">
              <h2 id="change-user-title">change {accountTarget} user</h2>
              <button aria-label="close change user dialog" className="dialog-close" onClick={closeChangeUser} type="button">×</button>
            </div>
            <p id="change-user-note">
              enter the current password, then change the username, password, or both. leave the new password blank to keep it.
            </p>
            <label>
              <span>username</span>
              <input
                autoFocus
                maxLength={32}
                onChange={(event) => setChangedUsername(event.target.value)}
                spellCheck={false}
                value={changedUsername}
              />
            </label>
            <label>
              <span>current password</span>
              <input
                autoComplete="current-password"
                maxLength={32}
                onChange={(event) => setCurrentPassword(event.target.value)}
                type="password"
                value={currentPassword}
              />
            </label>
            <label>
              <span>new password (optional)</span>
              <input
                autoComplete="new-password"
                maxLength={32}
                onChange={(event) => setChangedPassword(event.target.value)}
                type="password"
                value={changedPassword}
              />
            </label>
            <label>
              <span>confirm new password</span>
              <input
                autoComplete="new-password"
                disabled={!changedPassword}
                maxLength={32}
                onChange={(event) => setConfirmChangedPassword(event.target.value)}
                type="password"
                value={confirmChangedPassword}
              />
            </label>
            {changeUserError && <p className="dialog-error" role="alert">{changeUserError}</p>}
            <div className="dialog-actions">
              <button className="dialog-button dialog-button--secondary" onClick={closeChangeUser} type="button">cancel</button>
              <button className="dialog-button dialog-button--primary" type="submit">change user</button>
            </div>
          </form>
        </div>
      )}

      {removeUserOpen && (
        <div className="dialog-backdrop" role="presentation">
          <form
            aria-describedby="remove-user-note"
            aria-labelledby="remove-user-title"
            aria-modal="true"
            className="user-dialog"
            onSubmit={(event) => void submitRemoveUser(event)}
            role="dialog"
          >
            <div className="user-dialog-heading">
              <h2 id="remove-user-title">remove {accountTarget} user</h2>
              <button aria-label="close remove user dialog" className="dialog-close" onClick={closeRemoveUser} type="button">×</button>
            </div>
            <p id="remove-user-note">
              this permanently removes the active credentials and private home. type the active username and current password to confirm.
            </p>
            <label>
              <span>active username ({accountTarget === 'usb' ? 'type exactly' : diskUser.state === 'user' ? diskUser.username : 'unavailable'})</span>
              <input
                autoFocus
                autoComplete="off"
                maxLength={32}
                onChange={(event) => setRemoveUsername(event.target.value)}
                spellCheck={false}
                value={removeUsername}
              />
            </label>
            <label>
              <span>current password</span>
              <input
                autoComplete="current-password"
                maxLength={32}
                onChange={(event) => setRemovePassword(event.target.value)}
                type="password"
                value={removePassword}
              />
            </label>
            {removeUserError && <p className="dialog-error" role="alert">{removeUserError}</p>}
            <div className="dialog-actions">
              <button className="dialog-button dialog-button--secondary" onClick={closeRemoveUser} type="button">cancel</button>
              <button className="dialog-button dialog-button--danger" type="submit">remove user and home</button>
            </div>
          </form>
        </div>
      )}

      {flashOpen && (
        <div className="dialog-backdrop" role="presentation">
          <form
            aria-describedby="flash-usb-note"
            aria-labelledby="flash-usb-title"
            aria-modal="true"
            className="user-dialog user-dialog--usb"
            onSubmit={(event) => void submitFlash(event)}
            role="dialog"
          >
            <div className="user-dialog-heading">
              <h2 id="flash-usb-title">flash hardware usb</h2>
              <button aria-label="close flash usb dialog" className="dialog-close" onClick={closeFlash} type="button">×</button>
            </div>
            <p id="flash-usb-note">
              select an eligible target, then paste its exact confirmation. this permanently erases the selected disk and requires command centre to be running as administrator.
            </p>
            <div className="usb-targets">
              <div className="usb-targets-heading">
                <span>eligible usb targets</span>
                <button disabled={flashTargetsLoading} onClick={() => void refreshFlashTargets()} type="button">
                  {flashTargetsLoading ? 'refreshing…' : 'refresh'}
                </button>
              </div>
              {flashTargetsLoading && <p className="usb-target-message">checking attached usb disks…</p>}
              {!flashTargetsLoading && flashTargets.length === 0 && !flashError && (
                <p className="usb-target-message">no eligible non-system usb disks are attached.</p>
              )}
              {!flashTargetsLoading && flashTargets.map((target) => (
                <button
                  className={`usb-target ${target.diskNumber === selectedFlashTarget?.diskNumber ? 'usb-target--selected' : ''}`}
                  key={target.diskNumber}
                  onClick={() => {
                    setFlashDiskNumber(String(target.diskNumber))
                    setFlashConfirmation('')
                    setFlashError('')
                  }}
                  type="button"
                >
                  <span>disk {target.diskNumber} · {target.friendlyName} · {target.sizeGiB} gib</span>
                  <span>serial {target.serialNumber || 'unavailable'}</span>
                </button>
              ))}
              {!flashTargetsLoading && protectedFlashTargets.length > 0 && (
                <p className="usb-protected-targets">
                  protected and excluded: {protectedFlashTargets.map((target) => `disk ${target.diskNumber} ${target.friendlyName}`).join(', ')}
                </p>
              )}
            </div>
            {selectedFlashTarget && (
              <div className="usb-confirmation-guide">
                <span>exact confirmation</span>
                <code>{selectedFlashTarget.confirmation}</code>
              </div>
            )}
            <label>
              <span>exact erase confirmation</span>
              <input
                autoFocus={Boolean(selectedFlashTarget)}
                autoComplete="off"
                disabled={!selectedFlashTarget}
                maxLength={512}
                onChange={(event) => setFlashConfirmation(event.target.value)}
                placeholder="ERASE DISK …"
                spellCheck={false}
                value={flashConfirmation}
              />
            </label>
            {flashError && <p className="dialog-error" role="alert">{flashError}</p>}
            <div className="dialog-actions">
              <button className="dialog-button dialog-button--secondary" onClick={closeFlash} type="button">cancel</button>
              <button className="dialog-button dialog-button--danger" disabled={!selectedFlashTarget || flashTargetsLoading} type="submit">erase and flash</button>
            </div>
          </form>
        </div>
      )}

      {wirelessOpen && (
        <div className="dialog-backdrop" role="presentation">
          <form
            aria-describedby="wireless-note"
            aria-labelledby="wireless-title"
            aria-modal="true"
            className="user-dialog"
            onSubmit={(event) => void submitWireless(event)}
            role="dialog"
          >
            <div className="user-dialog-heading">
              <h2 id="wireless-title">configure hardware Wi-Fi</h2>
              <button aria-label="close Wi-Fi dialog" className="dialog-close" onClick={closeWireless} type="button">×</button>
            </div>
            <p id="wireless-note">
              only a non-secret open-network name may be placed in a distributable image. configure protected Wi-Fi in T1OS Settings on the target device.
            </p>
            <label>
              <span>network name (SSID)</span>
              <input
                autoFocus
                autoComplete="off"
                maxLength={32}
                onChange={(event) => setWirelessSsid(event.target.value)}
                spellCheck={false}
                value={wirelessSsid}
              />
            </label>
            <label>
              <span>security</span>
              <select
                onChange={(event) => setWirelessSecurity(event.target.value as 'open' | 'wpa2' | 'wpa3')}
                value={wirelessSecurity}
              >
                <option value="open">Open network</option>
              </select>
            </label>
            {wirelessSecurity !== 'open' && (
              <label>
                <span>passphrase</span>
                <input
                  autoComplete="new-password"
                  maxLength={63}
                  onChange={(event) => setWirelessPassphrase(event.target.value)}
                  type="password"
                  value={wirelessPassphrase}
                />
              </label>
            )}
            {wirelessError && <p className="dialog-error" role="alert">{wirelessError}</p>}
            <div className="dialog-actions">
              <button className="dialog-button dialog-button--secondary" onClick={closeWireless} type="button">cancel</button>
              <button className="dialog-button dialog-button--primary" type="submit">save Wi-Fi</button>
            </div>
          </form>
        </div>
      )}
    </main>
  )
}
