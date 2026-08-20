/**
 * useVoice.js — Ultra-low-latency voice hook for Nue Voice Bot.
 *
 * Uses @micdrop/client for:
 *   - Microphone access (getUserMedia with browser-native audio constraints)
 *   - Silero VAD (neural voice activity detection — primary gate)
 *   - Volume-based VAD (amplitude gate — secondary noise guard)
 *   - Built-in noise cancellation
 *
 * VAD design philosophy:
 *   The goal is to fire StopSpeaking as fast as possible after the user
 *   actually stops speaking, without false positives from:
 *     - Background noise (fans, HVAC, keyboard, traffic)
 *     - Breathing sounds
 *     - Brief natural pauses within a sentence
 *
 *   The two-layer VAD approach solves this:
 *   1. Volume gate (amplitude < threshold) → Silero won't even receive the frame.
 *   2. Silero VAD (neural, 16ms frame) → confirms it's real speech vs. residual noise.
 *
 * Latency budget:
 *   VAD silence: 700ms → backend safety net: 1200ms → total overhead: 700ms
 *   (Previously 2000ms VAD → saved ~1.3s per turn)
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import { CALL_WS_URL } from '../services/api'

// ── Default state shape ───────────────────────────────────────────────────────
const DEFAULT_STATE = {
    isStarted:           false,
    isMicStarted:        false,
    isUserSpeaking:      false,
    isProcessing:        false,
    isAssistantSpeaking: false,
    callState:           null,
    conversation:        [],
}

// ── Browser DevTools console styling ─────────────────────────────────────────
const S = {
    mic:     'color:#22c55e;font-weight:bold;font-size:12px;',
    voice:   'color:#16a34a;font-weight:bold;font-size:12px;',
    noise:   'color:#94a3b8;font-size:11px;',
    user:    'color:#22c55e;font-weight:bold;font-size:13px;',
    neura:   'color:#818cf8;font-weight:bold;font-size:13px;',
    llm:     'color:#8b5cf6;font-size:12px;',
    tts:     'color:#06b6d4;font-size:12px;',
    audio:   'color:#f59e0b;font-size:12px;',
    latency: 'color:#f97316;font-weight:bold;font-size:12px;',
    error:   'color:#ef4444;font-weight:bold;font-size:12px;',
    divider: 'color:#64748b;font-size:11px;',
    intr:    'color:#f43f5e;font-weight:bold;font-size:12px;',
}

// ── Latency tracker ───────────────────────────────────────────────────────────
let _speechEndTime  = null   // timestamp when StopSpeaking fired
let _firstAudioTime = null   // timestamp when first AI audio chunk arrived

/**
 * Structured pipeline logger — fires on every Micdrop state change.
 * Throttled to avoid spamming the console during high-frequency transitions.
 */
function logPipeline(newState, prevState, prevConvLen) {
    const p = prevState || {}

    // ── New conversation messages ─────────────────────────────────────────────
    if (newState.conversation.length > prevConvLen) {
        const newItems = newState.conversation.slice(prevConvLen)
        newItems.forEach(item => {
            if (item.role === 'user') {
                console.log(`%c👤 [USER] "${item.content}"`, S.user)
            } else if (item.role === 'assistant') {
                console.log(`%c🤖 [NEURA] "${item.content}"`, S.neura)
            }
        })
    }

    // ── State transition logs ─────────────────────────────────────────────────
    if (!p.isUserSpeaking && newState.isUserSpeaking) {
        _speechEndTime  = null
        _firstAudioTime = null
        console.log('%c[MIC ACTIVE]   User started speaking', S.mic)
    } else if (p.isUserSpeaking && !newState.isUserSpeaking) {
        _speechEndTime = performance.now()
        console.log('%c[MIC ACTIVE]   User stopped — sending audio to STT', S.mic)
    }

    if (!p.isProcessing && newState.isProcessing) {
        console.log('%c[LLM START]   STT→LLM→TTS pipeline activated', S.llm)
    } else if (p.isProcessing && !newState.isProcessing) {
        console.log('%c[LLM TOKEN STREAM]   Response generation complete', S.llm)
    }

    if (!p.isAssistantSpeaking && newState.isAssistantSpeaking) {
        _firstAudioTime = performance.now()
        const ttt = _speechEndTime ? (_firstAudioTime - _speechEndTime).toFixed(0) : '?'
        console.log(`%c[AUDIO STREAMING]   Neura speaking — PCM stream active`, S.tts)
        console.log(`%c[LATENCY]   StopSpeaking → First Audio: ${ttt}ms`, S.latency)
    } else if (p.isAssistantSpeaking && !newState.isAssistantSpeaking) {
        console.log('%c[AUDIO STREAMING]   Neura finished speaking', S.tts)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// useVoice hook
// ─────────────────────────────────────────────────────────────────────────────

export function useVoice() {
    const [micdropState, setMicdropState] = useState(DEFAULT_STATE)
    const [error,        setError]        = useState(null)

    const micdropRef   = useRef(null)
    const handlerRef   = useRef(null)
    const prevConvLen  = useRef(0)
    const micListeners = useRef({})
    const errorTimer   = useRef(null)

    // ── Cleanup on unmount ────────────────────────────────────────────────────
    useEffect(() => {
        return () => {
            if (errorTimer.current) clearTimeout(errorTimer.current)
            const md = micdropRef.current?.Micdrop
            if (!md) return
            if (handlerRef.current) md.off('StateChange', handlerRef.current)
            const { onSpeechStart, onSpeechEnd, onError } = micListeners.current
            if (onSpeechStart) md.off('speechStart', onSpeechStart)
            if (onSpeechEnd)   md.off('speechEnd',   onSpeechEnd)
            if (onError)       md.off('error',        onError)
        }
    }, [])

    // ── Error display (auto-dismiss after 6s) ─────────────────────────────────
    const showError = useCallback((msg) => {
        console.error(`%c[ERROR]  ${msg}`, S.error)
        setError(msg)
        if (errorTimer.current) clearTimeout(errorTimer.current)
        errorTimer.current = setTimeout(() => setError(null), 6000)
    }, [])

    const clearError = useCallback(() => {
        setError(null)
        if (errorTimer.current) clearTimeout(errorTimer.current)
    }, [])

    // ── Lazy Micdrop initialisation ───────────────────────────────────────────
    const ensureMicdrop = async () => {
        if (micdropRef.current) return micdropRef.current

        const { Micdrop } = await import('@micdrop/client')
        micdropRef.current = { Micdrop }
        setMicdropState(s => ({ ...DEFAULT_STATE, ...Micdrop.state }))

        const handler = (newState, prevState) => {
            logPipeline(newState, prevState, prevConvLen.current)
            prevConvLen.current = newState.conversation?.length ?? 0
            setMicdropState(newState)
        }
        handlerRef.current = handler
        Micdrop.on('StateChange', handler)

        return micdropRef.current
    }

    /**
     * handleStartMic — Initialise microphone with ultra-optimised VAD settings.
     *
     * VAD parameter tuning:
     *
     * sileroVadThreshold (0.45):
     *   Probability threshold to OPEN the speech gate.
     *   Lower → catches quieter voices / accented speech.
     *   0.5 missed soft-spoken users. 0.45 is the sweet spot.
     *
     * sileroVadNegThreshold (0.30):
     *   Probability to CLOSE (hysteresis). Must be < open threshold.
     *   Lower → faster gate closure after speech ends.
     *
     * sileroVadMinSpeechDuration (150ms):
     *   Minimum voice burst to count as speech.
     *   150ms catches single syllables: "yes", "no", "ok", "stop".
     *
     * sileroVadMinSilenceDuration (700ms):
     *   Silence required before StopSpeaking fires.
     *   700ms = natural inter-sentence pause without cutting mid-thought.
     *   (Down from 2000ms → saves ~1.3s per turn.)
     *
     * volumeThreshold (7):
     *   RMS amplitude gate. Frames below this level are NOT sent to Silero.
     *   Blocks: HVAC fan hum, keyboard clicks, mouse noise, ambient chatter.
     *   7 is empirically tuned for typical office/home noise floors.
     *   (Higher = stricter noise gate. 4 was too permissive.)
     *
     * volumeMinDuration (100ms):
     *   Minimum continuous volume above threshold to activate Silero.
     *   Prevents single-frame spikes (mouse click) from opening the gate.
     *
     * volumeSilenceDuration (700ms):
     *   Matches Silero's silence window for consistency.
     */
    const handleStartMic = async () => {
        try {
            clearError()
            const { Micdrop } = await ensureMicdrop()

            if (!Micdrop) {
                throw new Error('Micdrop failed to initialise')
            }

            console.log('%c[MIC ACTIVE]   Initialising microphone with advanced VAD…', S.mic)

            await Micdrop.startMic({
                vad: ['silero', 'volume'],
                vadOptions: {
                    // ── Silero neural VAD (primary gate) ─────────────────────────
                    sileroVadThreshold:          0.45,   // open gate (sensitive to quiet speech)
                    sileroVadNegThreshold:        0.30,   // close gate (fast hysteresis)
                    sileroVadMinSpeechDuration:   150,    // minimum valid speech burst (ms)
                    sileroVadMinSilenceDuration:  700,    // silence before StopSpeaking (ms)

                    // ── Volume amplitude gate (noise pre-filter) ──────────────────
                    volumeThreshold:              7,      // blocks HVAC, fan, keyboard noise
                    volumeMinDuration:            100,    // blocks single-click spikes (ms)
                    volumeSilenceDuration:        700,    // matches Silero window (ms)
                },
                noiseCancellation: true,
            })

            console.log('%c[NOISE FILTERED]   Silero VAD + volume gate active', S.noise)
            console.log('%c[NOISE FILTERED]   Browser echo cancellation + noise suppression active', S.noise)

            // ── Register VAD event listeners (once only) ──────────────────────
            if (!micListeners.current.onSpeechStart) {
                const onSpeechStart = () => {
                    console.log('%c[VOICE DETECTED]   Speech onset detected by VAD', S.voice)
                }
                const onSpeechEnd = () => {
                    console.log('%c[VOICE DETECTED]   Speech offset — queuing STT request', S.voice)
                }
                const onError = (err) => {
                    const msg = err?.message || String(err)
                    console.error(`%c[ERROR]  VAD error: ${msg}`, S.error)
                    showError(`Microphone error: ${msg}`)
                }
                micListeners.current = { onSpeechStart, onSpeechEnd, onError }
                Micdrop.on('speechStart', onSpeechStart)
                Micdrop.on('speechEnd',   onSpeechEnd)
                Micdrop.on('error',       onError)
            }

            console.log('%c[MIC ACTIVE]   Microphone ready — press Start Call to begin', S.mic)

        } catch (err) {
            showError(`Microphone error: ${err.message}`)
            console.error('Mic init error:', err)
        }
    }

    /**
     * handleStart — Connect to the backend WebSocket and start the call.
     *
     * Micdrop will:
     *  1. Open WebSocket to CALL_WS_URL
     *  2. Start streaming PCM audio chunks when VAD detects speech
     *  3. Send "StartSpeaking" / "StopSpeaking" text signals
     *  4. Receive and play PCM audio bytes from the backend
     */
    const handleStart = async () => {
        try {
            clearError()
            prevConvLen.current = 0
            _speechEndTime      = null
            _firstAudioTime     = null

            const { Micdrop } = await ensureMicdrop()
            console.log(`%c${'─'.repeat(60)}`, S.divider)
            console.log(`%c📞 [WS CONNECTED]  Connecting to ${CALL_WS_URL}`, S.divider)
            console.log(`%c${'─'.repeat(60)}`, S.divider)

            await Micdrop.start({
                url:      CALL_WS_URL,
                debugLog: false,     // disable micdrop internal debug (we have our own)
            })
        } catch (err) {
            showError(`Connection error: ${err.message}`)
            console.error('Call start error:', err)
        }
    }

    /** handleStop — End the call and reset all state. */
    const handleStop = async () => {
        try {
            clearError()
            if (!micdropRef.current) return
            await micdropRef.current.Micdrop.stop()
            console.log(`%c📴 [WS CONNECTED]  Call ended`, S.divider)
            console.log(`%c${'─'.repeat(60)}`, S.divider)
        } catch (err) {
            showError(`Stop error: ${err.message}`)
            console.error('Call stop error:', err)
        }
    }

    /** handleMute — Mute microphone without ending the call. */
    const handleMute = () => {
        try {
            clearError()
            if (!micdropRef.current) return
            micdropRef.current.Micdrop.mute()
            console.log('%c[MIC ACTIVE]   Microphone muted', S.mic)
        } catch (err) {
            showError(`Mute error: ${err.message}`)
        }
    }

    return {
        state:    micdropState,
        error,
        handlers: {
            handleStartMic,
            handleStart,
            handleStop,
            handleMute,
        },
    }
}
