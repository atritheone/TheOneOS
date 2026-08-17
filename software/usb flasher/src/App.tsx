import { useEffect, useMemo, useState } from 'react'
import logo from './assets/t1os-logo-white-transparent.png'

interface LogEntry extends FlashLog {
  id: number
}

const initialProgress: FlashProgress = {
  stage: 'idle',
  percent: 0,
  message: 'select a The One OS installer and a USB drive.',
}

const bridge = window.t1osFlasher ?? {
  detectImage: async () => null,
  chooseImage: async () => null,
  listUsbTargets: async () => [],
  startFlash: async () => ({ accepted: false, message: 'the desktop bridge is unavailable.' }),
  onProgress: () => () => undefined,
  onState: () => () => undefined,
  onLog: () => () => undefined,
}

export default function App() {
  const [image, setImage] = useState<ImageInfo | null>(null)
  const [targets, setTargets] = useState<UsbTarget[]>([])
  const [selectedDisk, setSelectedDisk] = useState('')
  const [acknowledged, setAcknowledged] = useState(false)
  const [loadingTargets, setLoadingTargets] = useState(true)
  const [running, setRunning] = useState(false)
  const [progress, setProgress] = useState<FlashProgress>(initialProgress)
  const [error, setError] = useState('')
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [detailsOpen, setDetailsOpen] = useState(false)

  const selectedTarget = useMemo(
    () => targets.find((target) => String(target.diskNumber) === selectedDisk) ?? null,
    [selectedDisk, targets],
  )

  const refreshTargets = async () => {
    setLoadingTargets(true)
    setError('')
    try {
      const nextTargets = await bridge.listUsbTargets()
      setTargets(nextTargets)
      setSelectedDisk((current) => (
        nextTargets.some((target) => String(target.diskNumber) === current) ? current : ''
      ))
    } catch (loadError) {
      setTargets([])
      setSelectedDisk('')
      setError(loadError instanceof Error ? loadError.message : String(loadError))
    } finally {
      setLoadingTargets(false)
    }
  }

  useEffect(() => {
    const removeProgress = bridge.onProgress((nextProgress) => {
      setProgress(nextProgress)
      if (nextProgress.stage === 'error') setDetailsOpen(true)
    })
    const removeState = bridge.onState((state) => {
      setRunning(state.running)
      if (!state.running && state.succeeded) {
        setAcknowledged(false)
        setSelectedDisk('')
      }
    })
    let nextLogId = 1
    const removeLog = bridge.onLog((entry) => {
      setLogs((current) => [...current.slice(-99), { ...entry, id: nextLogId++ }])
    })

    void bridge.detectImage()
      .then((detected) => {
        if (detected) setImage(detected)
      })
      .catch((detectError: Error) => setError(detectError.message))
    void refreshTargets()

    return () => {
      removeProgress()
      removeState()
      removeLog()
    }
  }, [])

  const chooseImage = async () => {
    setError('')
    try {
      const selected = await bridge.chooseImage()
      if (selected) {
        setImage(selected)
        setAcknowledged(false)
        setProgress(initialProgress)
        setLogs([])
      }
    } catch (selectionError) {
      setError(selectionError instanceof Error ? selectionError.message : String(selectionError))
    }
  }

  const flash = async () => {
    if (!image || !selectedTarget || !acknowledged || running) return
    setError('')
    setLogs([])
    setDetailsOpen(false)
    try {
      const result = await bridge.startFlash({
        imagePath: image.path,
        diskNumber: selectedTarget.diskNumber,
      })
      if (!result.accepted && !result.canceled) {
        setError(result.message ?? 'the flash could not be started.')
      }
    } catch (flashError) {
      setError(flashError instanceof Error ? flashError.message : String(flashError))
    }
  }

  const ready = Boolean(image && selectedTarget && acknowledged && !running)
  const statusClass = progress.stage === 'complete'
    ? 'status status--complete'
    : progress.stage === 'error' || error
      ? 'status status--error'
      : 'status'

  return (
    <main className="app-shell">
      <header className="brand">
        <img src={logo} alt="The One OS logo" />
        <div>
          <p>USB installer</p>
          <h1>The One OS</h1>
        </div>
      </header>

      <section className="selection" aria-label="flash settings">
        <div className="field">
          <div className="field-heading">
            <label>The One OS installer</label>
            <button className="quiet-button" disabled={running} onClick={() => void chooseImage()} type="button">
              browse
            </button>
          </div>
          {image ? (
            <div className="selected-item">
              <div className="selected-copy">
                <strong>{image.name}</strong>
                <span>{image.sizeGiB} GiB · installer with recovery · {image.volumeLabel}</span>
              </div>
            </div>
          ) : (
            <button className="empty-selection" disabled={running} onClick={() => void chooseImage()} type="button">
              choose a .t1os file
            </button>
          )}
        </div>

        <div className="field">
          <div className="field-heading">
            <label htmlFor="usb-target">USB drive</label>
            <button className="quiet-button" disabled={running || loadingTargets} onClick={() => void refreshTargets()} type="button">
              {loadingTargets ? 'checking…' : 'refresh'}
            </button>
          </div>
          <select
            id="usb-target"
            disabled={running || loadingTargets || targets.length === 0}
            onChange={(event) => {
              setSelectedDisk(event.target.value)
              setAcknowledged(false)
            }}
            value={selectedDisk}
          >
            <option value="">{targets.length ? 'select a USB drive' : 'no eligible USB drives found'}</option>
            {targets.map((target) => (
              <option key={target.diskNumber} value={target.diskNumber}>
                disk {target.diskNumber} · {target.friendlyName} · {target.sizeGiB} GiB
              </option>
            ))}
          </select>
          {selectedTarget && (
            <p className="target-detail">
              {selectedTarget.serialNumber ? `serial ${selectedTarget.serialNumber}` : 'serial unavailable'}
            </p>
          )}
        </div>

        <label className={`erase-warning${selectedTarget ? ' erase-warning--active' : ''}`}>
          <input
            checked={acknowledged}
            disabled={!selectedTarget || running}
            onChange={(event) => setAcknowledged(event.target.checked)}
            type="checkbox"
          />
          <span>I understand every file on the selected USB drive will be permanently erased.</span>
        </label>
      </section>

      <section className="flash-area" aria-live="polite">
        <div className="progress-track" aria-label="flash progress" aria-valuemax={100} aria-valuemin={0} aria-valuenow={progress.percent} role="progressbar">
          <span style={{ width: `${Math.max(0, Math.min(100, progress.percent))}%` }} />
        </div>
        <p className={statusClass}>{error || progress.message}</p>
        <button className="flash-button" disabled={!ready} onClick={() => void flash()} type="button">
          {running ? 'flashing…' : 'flash The One OS'}
        </button>
      </section>

      {logs.length > 0 && (
        <details className="details" onToggle={(event) => setDetailsOpen(event.currentTarget.open)} open={detailsOpen}>
          <summary>details</summary>
          <div className="log" role="log">
            {logs.map((entry) => (
              <p className={entry.error ? 'log-error' : undefined} key={entry.id}>{entry.line}</p>
            ))}
          </div>
        </details>
      )}

      <footer>Windows · administrator access required</footer>
    </main>
  )
}
