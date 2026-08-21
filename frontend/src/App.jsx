import { useState, useEffect, useRef } from 'react'
import { useVoice } from './hooks/useVoice'

// ── Inline styles (no external CSS dependency) ─────────────────────────────

const css = {
    root: {
        display: 'flex',
        flexDirection: 'column',
        height: '100dvh',
        maxWidth: '680px',
        margin: '0 auto',
        fontFamily: 'system-ui, -apple-system, sans-serif',
        background: '#fff',
    },
    header: {
        padding: '16px 20px',
        borderBottom: '1px solid #e5e5e5',
        display: 'flex',
        alignItems: 'center',
        gap: '10px',
    },
    dot: (color) => ({
        width: 10,
        height: 10,
        borderRadius: '50%',
        background: color,
        flexShrink: 0,
    }),
    headerTitle: {
        fontSize: 16,
        fontWeight: 600,
        color: '#111',
        margin: 0,
    },
    headerStatus: {
        fontSize: 12,
        color: '#888',
        marginLeft: 'auto',
    },
    messages: {
        flex: 1,
        overflowY: 'auto',
        padding: '20px',
        display: 'flex',
        flexDirection: 'column',
        gap: '12px',
    },
    empty: {
        flex: 1,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: '#bbb',
        fontSize: 14,
        userSelect: 'none',
    },
    bubble: (role) => ({
        maxWidth: '72%',
        padding: '10px 14px',
        borderRadius: role === 'user' ? '18px 18px 4px 18px' : '18px 18px 18px 4px',
        background: role === 'user' ? '#111' : '#f1f1f1',
        color: role === 'user' ? '#fff' : '#111',
        fontSize: 14,
        lineHeight: 1.5,
        alignSelf: role === 'user' ? 'flex-end' : 'flex-start',
        wordBreak: 'break-word',
    }),
    roleLabel: (role) => ({
        fontSize: 11,
        color: '#aaa',
        marginBottom: 3,
        alignSelf: role === 'user' ? 'flex-end' : 'flex-start',
    }),
    footer: {
        padding: '16px 20px',
        borderTop: '1px solid #e5e5e5',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: '16px',
    },
    micBtn: (active, disabled) => ({
        width: 64,
        height: 64,
        borderRadius: '50%',
        border: 'none',
        cursor: disabled ? 'not-allowed' : 'pointer',
        background: active ? '#ef4444' : '#111',
        color: '#fff',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize: 24,
        boxShadow: active ? '0 0 0 6px rgba(239,68,68,0.2)' : '0 2px 8px rgba(0,0,0,0.15)',
        transition: 'background 0.2s, box-shadow 0.2s',
        outline: 'none',
        opacity: disabled ? 0.5 : 1,
    }),
    hint: {
        fontSize: 12,
        color: '#aaa',
        textAlign: 'center',
        marginTop: 6,
    },
}

// ── Status helpers ─────────────────────────────────────────────────────────

function statusColor(state) {
    if (!state.isStarted)           return '#bbb'
    if (state.isAssistantSpeaking) return '#6366f1'
    if (state.isUserSpeaking)      return '#22c55e'
    if (state.isProcessing)        return '#f59e0b'
    return '#22c55e'
}

function statusLabel(state) {
    if (!state.isStarted)           return 'Not connected'
    if (state.isAssistantSpeaking) return 'Gaurav is speaking…'
    if (state.isUserSpeaking)      return 'Listening…'
    if (state.isProcessing)        return 'Processing…'
    return 'Ready'
}

// ── MicIcon SVG ────────────────────────────────────────────────────────────

function MicIcon() {
    return (
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" strokeWidth="2"
             strokeLinecap="round" strokeLinejoin="round">
            <rect x="9" y="2" width="6" height="11" rx="3" />
            <path d="M5 10a7 7 0 0 0 14 0" />
            <line x1="12" y1="19" x2="12" y2="22" />
            <line x1="8"  y1="22" x2="16" y2="22" />
        </svg>
    )
}

function StopIcon() {
    return (
        <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
            <rect x="4" y="4" width="16" height="16" rx="2" />
        </svg>
    )
}

// ── App ────────────────────────────────────────────────────────────────────

export default function App() {
    const { state, handlers } = useVoice()
    const { handleStartMic, handleStart, handleStop } = handlers
    const messagesEndRef = useRef(null)

    const [micReady, setMicReady] = useState(false)

    // Initialise mic once on mount
    useEffect(() => {
        handleStartMic().then(() => setMicReady(true))
    }, [])

    // Auto-scroll to latest message
    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }, [state.conversation])

    const isActive = state.isStarted
    const isBusy   = state.isAssistantSpeaking || state.isProcessing

    async function toggleCall() {
        if (isActive) {
            await handleStop()
        } else {
            await handleStart()
        }
    }

    const messages = state.conversation || []

    return (
        <div style={css.root}>

            {/* Header */}
            <header style={css.header}>
                <div style={css.dot(statusColor(state))} />
                <h1 style={css.headerTitle}>Gaurav</h1>
                <span style={css.headerStatus}>{statusLabel(state)}</span>
            </header>

            {/* Message list */}
            <div style={css.messages}>
                {messages.length === 0 ? (
                    <div style={css.empty}>
                        Press the mic button to start a conversation
                    </div>
                ) : (
                    messages.map((msg, i) => (
                        <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                            <span style={css.roleLabel(msg.role)}>
                                {msg.role === 'user' ? 'You' : 'Gaurav'}
                            </span>
                            <div style={css.bubble(msg.role)}>
                                {msg.content}
                            </div>
                        </div>
                    ))
                )}
                <div ref={messagesEndRef} />
            </div>

            {/* Footer — mic button only */}
            <footer style={css.footer}>
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
                    <button
                        id="mic-btn"
                        style={css.micBtn(isActive, !micReady)}
                        onClick={toggleCall}
                        disabled={!micReady}
                        title={isActive ? 'End call' : 'Start call'}
                    >
                        {isActive ? <StopIcon /> : <MicIcon />}
                    </button>
                    <span style={css.hint}>
                        {!micReady
                            ? 'Requesting microphone…'
                            : isActive
                                ? 'Tap to end call'
                                : 'Tap to start'}
                    </span>
                </div>
            </footer>

        </div>
    )
}
