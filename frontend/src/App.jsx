import { useState, useEffect, useRef } from 'react'
import { useVoice } from './hooks/useVoice'

// ── Design tokens ────────────────────────────────────────────────────────────

const COLORS = {
    bgTop:     '#0b0b14',
    bgBottom:  '#05050a',
    glass:     'rgba(255,255,255,0.06)',
    glassBorder: 'rgba(255,255,255,0.12)',
    text:      '#f2f2f7',
    textDim:   'rgba(242,242,247,0.55)',
    accentA:   '#6366f1',   // indigo — assistant speaking
    accentB:   '#22c55e',   // green — user speaking
    accentC:   '#f59e0b',   // amber — processing
    accentIdle:'#3b82f6',   // blue — idle glow
    danger:    '#ef4444',
}

// ── Keyframes injected once ──────────────────────────────────────────────────

const KEYFRAMES = `
@keyframes orbSpin {
    0%   { transform: rotate(0deg) scale(1); }
    100% { transform: rotate(360deg) scale(1); }
}
@keyframes orbPulse {
    0%, 100% { transform: scale(1); }
    50%      { transform: scale(1.06); }
}
@keyframes orbGlowPulse {
    0%, 100% { opacity: 0.55; transform: scale(1); }
    50%      { opacity: 0.9;  transform: scale(1.12); }
}
@keyframes fadeUp {
    from { opacity: 0; transform: translateY(8px); }
    to   { opacity: 1; transform: translateY(0); }
}
@keyframes dotBounce {
    0%, 80%, 100% { transform: translateY(0); opacity: 0.4; }
    40%           { transform: translateY(-4px); opacity: 1; }
}
@keyframes ringExpand {
    0%   { transform: scale(0.9); opacity: 0.35; }
    100% { transform: scale(1.7); opacity: 0; }
}
`

// ── Inline styles ────────────────────────────────────────────────────────────

const css = {
    root: {
        position: 'relative',
        display: 'flex',
        flexDirection: 'column',
        height: '100dvh',
        maxWidth: '720px',
        margin: '0 auto',
        fontFamily: "'Inter', system-ui, -apple-system, sans-serif",
        color: COLORS.text,
        overflow: 'hidden',
        background: `radial-gradient(circle at 50% -10%, #1c1c30 0%, ${COLORS.bgTop} 45%, ${COLORS.bgBottom} 100%)`,
    },
    ambientGlow: (color) => ({
        position: 'absolute',
        top: '-20%',
        left: '50%',
        width: '480px',
        height: '480px',
        marginLeft: '-240px',
        background: `radial-gradient(circle, ${color}33 0%, transparent 70%)`,
        filter: 'blur(40px)',
        pointerEvents: 'none',
        transition: 'background 0.6s ease',
        zIndex: 0,
    }),
    header: {
        position: 'relative',
        zIndex: 1,
        padding: '20px 24px 12px',
        display: 'flex',
        alignItems: 'center',
        gap: '10px',
    },
    dot: (color) => ({
        width: 8,
        height: 8,
        borderRadius: '50%',
        background: color,
        flexShrink: 0,
        boxShadow: `0 0 8px ${color}`,
        transition: 'background 0.3s ease, box-shadow 0.3s ease',
    }),
    headerTitle: {
        fontSize: 15,
        fontWeight: 600,
        color: COLORS.text,
        margin: 0,
        letterSpacing: '-0.01em',
    },
    headerStatus: {
        fontSize: 12,
        color: COLORS.textDim,
        marginLeft: 'auto',
        fontWeight: 500,
    },

    // ── Orb stage (shown when conversation is empty / as a persistent hero) ──
    stage: {
        position: 'relative',
        zIndex: 1,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 18,
        padding: '18px 24px',
        flexShrink: 0,
    },
    orbWrap: {
        position: 'relative',
        width: 120,
        height: 120,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
    },
    orbRing: (color, delay) => ({
        position: 'absolute',
        inset: 0,
        borderRadius: '50%',
        border: `1.5px solid ${color}`,
        animation: `ringExpand 2.2s ${delay}s ease-out infinite`,
    }),
    orbGlow: (color) => ({
        position: 'absolute',
        inset: -14,
        borderRadius: '50%',
        background: `radial-gradient(circle, ${color}66 0%, transparent 72%)`,
        filter: 'blur(6px)',
        animation: 'orbGlowPulse 2.6s ease-in-out infinite',
        transition: 'background 0.4s ease',
    }),
    orbCore: (spinning, pulsing) => ({
        position: 'relative',
        width: 92,
        height: 92,
        borderRadius: '50%',
        background: 'conic-gradient(from 0deg, #6366f1, #22d3ee, #a855f7, #f59e0b, #6366f1)',
        boxShadow: 'inset 0 0 24px rgba(255,255,255,0.25), 0 8px 30px rgba(0,0,0,0.45)',
        animation: [
            spinning ? 'orbSpin 6s linear infinite' : null,
            pulsing  ? 'orbPulse 1.6s ease-in-out infinite' : null,
        ].filter(Boolean).join(', ') || 'none',
    }),
    orbSheen: {
        position: 'absolute',
        inset: 6,
        borderRadius: '50%',
        background: 'radial-gradient(circle at 35% 30%, rgba(255,255,255,0.55), rgba(255,255,255,0) 55%)',
        pointerEvents: 'none',
    },
    statusLabel: {
        fontSize: 14,
        fontWeight: 500,
        color: COLORS.textDim,
        letterSpacing: '0.01em',
        transition: 'color 0.3s ease',
    },

    // ── Message list ──────────────────────────────────────────────────────────
    messages: {
        position: 'relative',
        zIndex: 1,
        flex: 1,
        minHeight: 0,
        overflowY: 'auto',
        padding: '4px 20px 16px',
        display: 'flex',
        flexDirection: 'column',
        gap: '14px',
    },
    empty: {
        flex: 1,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: COLORS.textDim,
        fontSize: 14,
        userSelect: 'none',
        textAlign: 'center',
        padding: '0 40px',
    },
    row: (role) => ({
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
        alignItems: role === 'user' ? 'flex-end' : 'flex-start',
        animation: 'fadeUp 0.35s ease both',
    }),
    bubble: (role) => ({
        maxWidth: '78%',
        padding: '11px 15px',
        borderRadius: role === 'user' ? '16px 16px 4px 16px' : '16px 16px 16px 4px',
        background: role === 'user'
            ? 'linear-gradient(135deg, #6366f1, #4f46e5)'
            : COLORS.glass,
        border: role === 'user' ? 'none' : `1px solid ${COLORS.glassBorder}`,
        backdropFilter: role === 'user' ? 'none' : 'blur(12px)',
        color: role === 'user' ? '#fff' : COLORS.text,
        fontSize: 14.5,
        lineHeight: 1.5,
        wordBreak: 'break-word',
        boxShadow: role === 'user'
            ? '0 4px 16px rgba(99,102,241,0.35)'
            : '0 2px 12px rgba(0,0,0,0.25)',
    }),
    roleLabel: {
        fontSize: 11,
        color: COLORS.textDim,
        padding: '0 4px',
    },
    typingBubble: {
        display: 'flex',
        gap: 4,
        padding: '13px 16px',
        borderRadius: '16px 16px 16px 4px',
        background: COLORS.glass,
        border: `1px solid ${COLORS.glassBorder}`,
        backdropFilter: 'blur(12px)',
        width: 'fit-content',
    },
    typingDot: (delay) => ({
        width: 6,
        height: 6,
        borderRadius: '50%',
        background: COLORS.textDim,
        animation: `dotBounce 1.2s ${delay}s ease-in-out infinite`,
    }),

    // ── Footer ────────────────────────────────────────────────────────────────
    footer: {
        position: 'relative',
        zIndex: 1,
        padding: '14px 24px 26px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
    },
    controls: {
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 10,
    },
    micBtn: (active, disabled) => ({
        width: 64,
        height: 64,
        borderRadius: '50%',
        border: `1px solid ${active ? 'rgba(239,68,68,0.5)' : COLORS.glassBorder}`,
        cursor: disabled ? 'not-allowed' : 'pointer',
        background: active
            ? 'linear-gradient(135deg, #ef4444, #dc2626)'
            : 'linear-gradient(135deg, rgba(255,255,255,0.12), rgba(255,255,255,0.04))',
        backdropFilter: 'blur(10px)',
        color: '#fff',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize: 24,
        boxShadow: active
            ? '0 0 0 8px rgba(239,68,68,0.15), 0 4px 20px rgba(239,68,68,0.4)'
            : '0 4px 20px rgba(0,0,0,0.4)',
        transition: 'background 0.25s ease, box-shadow 0.25s ease, transform 0.15s ease',
        outline: 'none',
        opacity: disabled ? 0.4 : 1,
    }),
    hint: {
        fontSize: 12,
        color: COLORS.textDim,
        textAlign: 'center',
    },
    errorToast: {
        position: 'absolute',
        top: 64,
        left: '50%',
        transform: 'translateX(-50%)',
        zIndex: 5,
        background: 'rgba(239,68,68,0.15)',
        border: '1px solid rgba(239,68,68,0.4)',
        backdropFilter: 'blur(12px)',
        color: '#fecaca',
        fontSize: 13,
        padding: '10px 16px',
        borderRadius: 12,
        maxWidth: '85%',
        textAlign: 'center',
        animation: 'fadeUp 0.3s ease both',
    },
}

// ── Status helpers ────────────────────────────────────────────────────────────

function statusColor(state) {
    if (!state.isStarted)          return 'rgba(255,255,255,0.25)'
    if (state.isAssistantSpeaking) return COLORS.accentA
    if (state.isUserSpeaking)      return COLORS.accentB
    if (state.isProcessing)        return COLORS.accentC
    return COLORS.accentB
}

function statusLabel(state) {
    if (!state.isStarted)          return 'Not connected'
    if (state.isAssistantSpeaking) return 'Flash is speaking…'
    if (state.isUserSpeaking)      return 'Listening…'
    if (state.isProcessing)        return 'Thinking…'
    return 'Ready — say something'
}

// ── Icons ─────────────────────────────────────────────────────────────────────

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

// ── Orb ────────────────────────────────────────────────────────────────────────

function Orb({ state }) {
    const glowColor = statusColor(state)
    const spinning = state.isAssistantSpeaking || state.isProcessing
    const pulsing  = state.isUserSpeaking
    const showRings = state.isUserSpeaking || state.isAssistantSpeaking

    return (
        <div style={css.orbWrap}>
            {showRings && (
                <>
                    <div style={css.orbRing(glowColor, 0)} />
                    <div style={css.orbRing(glowColor, 0.7)} />
                </>
            )}
            <div style={css.orbGlow(glowColor)} />
            <div style={css.orbCore(spinning, pulsing)}>
                <div style={css.orbSheen} />
            </div>
        </div>
    )
}

// ── App ────────────────────────────────────────────────────────────────────────

export default function App() {
    const { state, error, handlers } = useVoice()
    const { handleStartMic, handleStart, handleStop } = handlers
    const messagesEndRef = useRef(null)

    const [micReady, setMicReady] = useState(false)

    useEffect(() => {
        handleStartMic().then(() => setMicReady(true))
    }, [])

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }, [state.conversation])

    const isActive = state.isStarted
    const glowColor = statusColor(state)
    const messages = state.conversation || []

    async function toggleCall() {
        if (isActive) {
            await handleStop()
        } else {
            await handleStart()
        }
    }

    return (
        <div style={css.root}>
            <style>{KEYFRAMES}</style>

            <div style={css.ambientGlow(glowColor)} />

            {error && <div style={css.errorToast}>{error}</div>}

            {/* Header */}
            <header style={css.header}>
                <div style={css.dot(glowColor)} />
                <h1 style={css.headerTitle}>Flash · Order Support</h1>
                <span style={css.headerStatus}>{statusLabel(state)}</span>
            </header>

            {/* Orb stage */}
            <div style={css.stage}>
                <Orb state={state} />
            </div>

            {/* Message list */}
            <div style={css.messages}>
                {messages.length === 0 ? (
                    <div style={css.empty}>
                        Press the mic to start — ask about an order,<br />
                        a delivery estimate, or a cancellation.
                    </div>
                ) : (
                    messages.map((msg, i) => (
                        <div key={i} style={css.row(msg.role)}>
                            <span style={css.roleLabel}>
                                {msg.role === 'user' ? 'You' : 'Flash'}
                            </span>
                            <div style={css.bubble(msg.role)}>
                                {msg.content}
                            </div>
                        </div>
                    ))
                )}
                {state.isProcessing && (
                    <div style={css.row('assistant')}>
                        <span style={css.roleLabel}>Flash</span>
                        <div style={css.typingBubble}>
                            <span style={css.typingDot(0)} />
                            <span style={css.typingDot(0.15)} />
                            <span style={css.typingDot(0.3)} />
                        </div>
                    </div>
                )}
                <div ref={messagesEndRef} />
            </div>

            {/* Footer — mic button */}
            <footer style={css.footer}>
                <div style={css.controls}>
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
