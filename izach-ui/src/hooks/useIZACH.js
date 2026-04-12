import { useState, useEffect, useRef, useCallback } from 'react'

const BASE  = 'http://localhost:5050'
const WA    = 'http://localhost:3000'
const MMA   = 'http://localhost:6060'

async function safeFetch(url, opts = {}, ms = 4000) {
  const ctrl  = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), ms)
  try {
    return await fetch(url, { ...opts, signal: ctrl.signal })
  } finally {
    clearTimeout(timer)
  }
}

function nowStr() {
  return new Date().toLocaleTimeString('en-IN', {
    hour: '2-digit', minute: '2-digit', hour12: false,
  })
}

export function useIZACH() {
  const [messages, setMessages] = useState([
    { id: 1, sender: 'iZACH', text: 'Neural interface online. All systems nominal.', ts: nowStr(), type: 'system' },
  ])
  const [inputText, setInputText]   = useState('')
  const [isLoading, setIsLoading]   = useState(false)
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [micActive, setMicActive]   = useState(true)
  const [liveText, setLiveText]     = useState('')

  // statuses
  const [backendStatus, setBackendStatus] = useState('unknown')
  const [waStatus, setWaStatus]           = useState('offline')
  const [mmaStatus, setMmaStatus]         = useState('offline')

  // system stats
  const [cpuUsage, setCpuUsage]   = useState(0)
  const [ramUsage, setRamUsage]   = useState(0)
  const [procCpu,  setProcCpu]    = useState(0)
  const [procMem,  setProcMem]    = useState(0)

  // spotify
  const [spotifyTrack, setSpotifyTrack] = useState({
    playing: false, title: '—', artist: '—', device: '—',
    albumArt: '', progress: 0, duration: 0, volume: 0,
  })

  // settings & memory (for Settings page)
  const [memoryEntries, setMemoryEntries] = useState([])
  const [settings,      setSettings]      = useState({})

  const [notifications, setNotifications] = useState([])
  const chatBottomRef = useRef(null)
  const liveTimer     = useRef(null)
  const wsRef         = useRef(null)

  // ── WebSocket — voice chat + live text from Python backend ─
  useEffect(() => {
    function connect() {
      const ws = new WebSocket('ws://localhost:5051')
      wsRef.current = ws

      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data)
          if (data.type === 'chat') {
            setMessages(prev => [
              ...prev,
              { id: Date.now() + Math.random(), sender: data.sender, text: data.text, ts: data.ts || nowStr(), type: 'normal' },
            ])
          } else if (data.type === 'live_text') {
            setLiveText(data.text || '')
            if (data.text) setIsSpeaking(true)
            else setIsSpeaking(false)
          }
        } catch {}
      }

      ws.onclose = () => {
        setTimeout(connect, 3000)
      }
    }
    connect()
    return () => { wsRef.current?.close() }
  }, [])

  // ── auto-scroll ───────────────────────────────────────────
  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // ── add message ───────────────────────────────────────────
  const addMessage = useCallback((sender, text, type = 'normal') => {
    setMessages(prev => [
      ...prev,
      { id: Date.now() + Math.random(), sender, text, ts: nowStr(), type },
    ])
  }, [])

  // ── poll backend health ───────────────────────────────────
  // FIX: UI showed late because Electron waited for all polls to resolve
  // before rendering. Now each poll is independent and non-blocking.
  useEffect(() => {
    let mounted = true

    async function pollAll() {
      // iZACH
      try {
        const r = await safeFetch(`${BASE}/health`, {}, 3000)
        if (mounted) setBackendStatus(r.ok ? 'online' : 'offline')
      } catch { if (mounted) setBackendStatus('offline') }

      // WhatsApp
      try {
        const r = await safeFetch(`${WA}/health`, {}, 2500)
        if (r.ok) {
          const d = await r.json().catch(() => ({}))
          if (mounted) setWaStatus(d.status === 'connected' ? 'online' : 'offline')
        } else {
          if (mounted) setWaStatus('offline')
        }
      } catch { if (mounted) setWaStatus('offline') }

      // MMA — FIX: was using wrong endpoint format
      // MMA health returns { "status": "online" } — check that specifically
      try {
        const r = await safeFetch(`${MMA}/health`, {}, 2500)
        if (r.ok) {
          const d = await r.json().catch(() => ({}))
          if (mounted) setMmaStatus(d.status === 'online' ? 'online' : 'offline')
        } else {
          if (mounted) setMmaStatus('offline')
        }
      } catch { if (mounted) setMmaStatus('offline') }
    }

    pollAll()
    const t = setInterval(pollAll, 15000)
    return () => { mounted = false; clearInterval(t) }
  }, [])

  // ── poll system stats ─────────────────────────────────────
  // FIX: was using interval=None which returns 0 on first call.
  // Backend now uses interval=0.1. Poll every 4s.
  useEffect(() => {
    let mounted = true

    async function pollStats() {
      try {
        const r = await safeFetch(`${BASE}/status`, {}, 4000)
        if (!r.ok) return
        const d = await r.json()
        if (!mounted || !d.ok) return
        setCpuUsage(d.cpu    ?? 0)
        setRamUsage(d.ram    ?? 0)
        setProcCpu(d.proc_cpu ?? 0)
        setProcMem(d.proc_mem ?? 0)
      } catch {
        // Backend offline — show last known values, don't freeze
      }
    }

    // First call after 1s (give backend time to finish booting)
    const first = setTimeout(pollStats, 1000)
    const t = setInterval(pollStats, 4000)
    return () => { mounted = false; clearTimeout(first); clearInterval(t) }
  }, [])

  // ── poll Spotify ──────────────────────────────────────────
  useEffect(() => {
    let mounted = true

    async function pollSpotify() {
      try {
        const r = await safeFetch(`${BASE}/spotify`, {}, 4000)
        if (!r.ok) return
        const d = await r.json()
        if (!mounted || !d.ok) return
        setSpotifyTrack({
          playing:  d.playing,
          title:    d.title   || '—',
          artist:   d.artist  || '—',
          device:   d.device  || '—',
          albumArt: d.album_art || '',
          progress: d.progress  || 0,
          duration: d.duration  || 0,
          volume:   d.volume    || 0,
          shuffle:  d.shuffle   || false,
          repeat:   d.repeat    || 'off',
        })
      } catch { /* spotify unavailable */ }
    }

    const t = setInterval(pollSpotify, 5000)
    pollSpotify()
    return () => { mounted = false; clearInterval(t) }
  }, [])

  // ── load memory & settings (for Settings page) ───────────
  const loadMemory = useCallback(async () => {
    try {
      const r = await safeFetch(`${BASE}/memory`, {}, 4000)
      const d = await r.json()
      if (d.ok) setMemoryEntries(d.data || [])
    } catch {}
  }, [])

  const loadSettings = useCallback(async () => {
    try {
      const r = await safeFetch(`${BASE}/settings`, {}, 4000)
      const d = await r.json()
      if (d.ok) setSettings(d.settings || {})
    } catch {}
  }, [])

  useEffect(() => {
    loadMemory()
    loadSettings()
  }, [loadMemory, loadSettings])

  const addMemoryEntry = useCallback(async (key, value) => {
    try {
      await safeFetch(`${BASE}/memory`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key, value }),
      }, 5000)
      loadMemory()
    } catch {}
  }, [loadMemory])

  const deleteMemoryEntry = useCallback(async (key) => {
    try {
      await safeFetch(`${BASE}/memory/${encodeURIComponent(key)}`, { method: 'DELETE' }, 5000)
      loadMemory()
    } catch {}
  }, [loadMemory])

  const saveSettings = useCallback(async (newSettings) => {
    try {
      await safeFetch(`${BASE}/settings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newSettings),
      }, 5000)
      loadSettings()
    } catch {}
  }, [loadSettings])

  // ── live word-by-word text ────────────────────────────────
  function startLiveTyping(text) {
    if (!text) return
    const words = text.split(' ')
    let i = 0
    setLiveText('')
    clearInterval(liveTimer.current)
    liveTimer.current = setInterval(() => {
      i++
      setLiveText(words.slice(0, i).join(' '))
      if (i >= words.length) clearInterval(liveTimer.current)
    }, 75)
  }

  function clearLiveText() {
    clearInterval(liveTimer.current)
    setLiveText('')
  }

  useEffect(() => () => clearInterval(liveTimer.current), [])

  // ── SEND ──────────────────────────────────────────────────
  const send = useCallback(async (text) => {
    const trimmed = text.trim()
    if (!trimmed || isLoading) return

    addMessage('YOU', trimmed)
    setInputText('')
    setIsLoading(true)

    const thinkingId = Date.now()
    setMessages(prev => [
      ...prev,
      { id: thinkingId, sender: 'iZACH', text: '...', ts: nowStr(), type: 'thinking' },
    ])

    try {
      const res = await safeFetch(
        `${BASE}/command`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({ text: trimmed, source: 'react_ui' }),
        },
        20000
      )

      setMessages(prev => prev.filter(m => m.id !== thinkingId))

      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        addMessage('iZACH', err.error || `Backend returned ${res.status}`, 'error')
        return
      }

      const data = await res.json()

      if (data.ok && data.response) {
        setIsSpeaking(true)
        startLiveTyping(data.response)
        addMessage('iZACH', data.response)
        setTimeout(() => {
          clearLiveText()
          setIsSpeaking(false)
        }, data.response.split(' ').length * 80 + 600)
      } else if (data.error) {
        addMessage('iZACH', data.error, 'error')
      } else {
        addMessage('iZACH', 'Command processed.', 'system')
      }
    } catch (err) {
      setMessages(prev => prev.filter(m => m.id !== thinkingId))
      if (err.name === 'AbortError') {
        addMessage('iZACH', 'Request timed out.', 'error')
      } else {
        addMessage('iZACH',
          backendStatus === 'offline'
            ? 'Backend offline — run python main.py'
            : `Connection error: ${err.message}`,
          'error'
        )
      }
    } finally {
      setIsLoading(false)
    }
  }, [isLoading, addMessage, backendStatus])

  // ── Stop speech ───────────────────────────────────────────
  const stopSpeech = useCallback(async () => {
    clearLiveText()
    setIsSpeaking(false)
    try {
      await safeFetch(`${BASE}/stop`, { method: 'POST' }, 3000)
    } catch {}
  }, [])

  const toggleMic = useCallback(() => setMicActive(v => !v), [])

  return {
    messages, addMessage,
    inputText, setInputText,
    isLoading, isSpeaking, liveText,
    micActive, toggleMic,
    backendStatus, waStatus, mmaStatus,
    cpuUsage, ramUsage, procCpu, procMem,
    spotifyTrack,
    memoryEntries, settings,
    addMemoryEntry, deleteMemoryEntry, saveSettings, loadMemory,
    notifications,
    chatBottomRef,
    send, stopSpeech,
  }
}