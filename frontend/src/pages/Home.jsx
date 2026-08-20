import { useEffect, useRef } from 'react';
import ConversationPanel from '../components/ConversationPanel';
import { useVoice } from '../hooks/useVoice';
import { useTheme } from '../utils/theme';

import orbImage from '../assets/orb.png';
import videoSrc from '../assets/voice.mp4';
import logo from '../assets/neutrinoaistudiologo.png';
import logoWhite from '../assets/Neutrino AI Studio Logo- White Logo 4.png';
import themeIcon from '../assets/black theme.png';

export default function Home() {
    const { state, error, handlers } = useVoice();
    const {
        isStarted,
        conversation,
        isUserSpeaking,
        isProcessing,
        isAssistantSpeaking,
    } = state;
    const { handleStartMic, handleStart, handleStop } = handlers;
    const { toggleTheme, theme } = useTheme();

    const orbVideoRef = useRef(null);

    /* ── Control orb video based on call active state ─────────── */
    useEffect(() => {
        const video = orbVideoRef.current;
        if (!video) return;

        if (isStarted) {
            video.currentTime = 0;
            video.play().catch(() => { });
        } else {
            video.pause();
            video.currentTime = 0;
        }
    }, [isStarted]);

    /* ── Derive CSS class and status text from pipeline state ─── */
    const getOrbStateClass = () => {
        if (!isStarted) return '';
        if (isAssistantSpeaking) return 'speaking';
        if (isProcessing)        return 'thinking';
        if (isUserSpeaking)      return 'listening';
        return 'idle';
    };

    const getStatusText = () => {
        if (!isStarted) return 'Click to Talk';
        if (isAssistantSpeaking) return 'Neura is speaking…';
        if (isProcessing)        return 'Thinking…';
        if (isUserSpeaking)      return 'Listening…';
        return 'Click to End Call';
    };

    const getStatusState = () => {
        if (!isStarted) return '';
        if (isAssistantSpeaking) return 'speaking';
        if (isProcessing)        return 'thinking';
        if (isUserSpeaking)      return 'listening';
        return '';
    };

    /* ── Handle orb / mic button click ───────────────────────── */
    const handleOrbClick = async () => {
        try {
            if (isStarted) {
                await handleStop();
            } else {
                await handleStartMic();
                await handleStart();
            }
        } catch (err) {
            console.error(err);
        }
    };

    return (
        <div className="neura-container">

            {/* HEADER */}
            <header className="neura-header">
                <div className="logo">
                    <img src={theme === 'dark' ? logoWhite : logo} alt="Neutrino AI" />
                </div>

                <button onClick={toggleTheme} className="theme-toggle">
                    <img src={themeIcon} alt="theme toggle" className={theme === 'dark' ? 'inverted' : ''} />
                </button>
            </header>

            {/* MAIN */}
            <div className="neura-main">

                {/* LEFT */}
                <div className="neura-left">

                    <h1>
                        Talk to <span className="gradient-text">Neura</span>
                    </h1>

                    {/* ORB */}
                    <div className="orb-container" onClick={handleOrbClick}>
                        <div className={`orb-wrapper ${isStarted ? 'active' : ''} ${getOrbStateClass()}`}>

                            <img
                                src={orbImage}
                                alt="orb"
                                className={`orb-media ${isStarted ? 'hidden' : ''}`}
                            />

                            <video
                                ref={orbVideoRef}
                                className={`orb-media ${isStarted ? 'visible' : ''}`}
                                src={videoSrc}
                                muted
                                loop
                                playsInline
                            />
                        </div>
                    </div>

                    {/* STATUS TEXT */}
                    <div className="mic-text-wrapper">
                        <p className={`mic-text ${getStatusState()}`}>
                            {getStatusText()}
                        </p>
                    </div>

                    {/* MIC BUTTON */}
                    <div className="mic-btn-container">
                        <button
                            className={`mic-btn ${isStarted ? 'active' : ''} ${getStatusState()}`}
                            onClick={handleOrbClick}
                            title={isStarted ? 'End Call' : 'Start Conversation'}
                        >
                            {isStarted ? (
                                /* End Call — mic with slash */
                                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                    <path d="M12 1a3 3 0 0 0-3 3v4.27l1.38 1.38A2.99 2.99 0 0 1 12 4a3 3 0 0 1 3 3v3h1.8a3 3 0 0 0 .2-1V7a3 3 0 0 0-3-3M3.41 2.86L2 4.27 7.73 10H7v1c0 2.21 1.79 4 4 4 .41 0 .81-.07 1.18-.19l2.43 2.43C13.8 17.75 12.93 18 12 18c-3.1 0-5.61-2.31-6-5.32H4.1c.42 3.86 3.7 6.87 7.7 7.27V23h2v-3.05c1.4-.14 2.69-.64 3.77-1.39l2.86 2.86 1.41-1.41L3.41 2.86zM15.41 12.33L17 13.92c.15-.6.22-1.25.22-1.92h-1.89c0 .11-.01.22-.05.33z" fill="currentColor" />
                                </svg>
                            ) : (
                                /* Start — classic mic */
                                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                    <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z" fill="currentColor" />
                                    <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z" fill="currentColor" />
                                    <path d="M8 22h8v1H8v-1z" fill="currentColor" />
                                </svg>
                            )}
                        </button>
                    </div>

                </div>

                {/* RIGHT PANEL */}
                <div className="neura-right">
                    <ConversationPanel conversation={conversation} />
                </div>

            </div>

            {/* ERROR */}
            {error && <div className="error">{error}</div>}
        </div>
    );
}
