/**
 * Controls component.
 *
 * Renders the mic and call action buttons.
 *
 * @param {object} props
 * @param {boolean} props.isMicStarted
 * @param {boolean} props.isStarted
 * @param {Function} props.onStartMic
 * @param {Function} props.onStart
 * @param {Function} props.onStop
 * @param {Function} props.onMute
 */
export default function Controls({
    isMicStarted,
    isStarted,
    onStartMic,
    onStart,
    onStop,
    onMute,
}) {
    return (
        <section className="controls">
            <h2>Controls</h2>
            <div className="button-group">
                <button
                    id="btn-start-mic"
                    onClick={onStartMic}
                    disabled={isMicStarted}
                    className="btn btn-primary"
                >
                    🎤 Start Mic
                </button>
                <button
                    id="btn-start-call"
                    onClick={onStart}
                    disabled={!isMicStarted || isStarted}
                    className="btn btn-success"
                >
                    ▶️ Start Call
                </button>
                <button
                    id="btn-stop-call"
                    onClick={onStop}
                    disabled={!isStarted}
                    className="btn btn-danger"
                >
                    ⏹️ Stop Call
                </button>
                <button
                    id="btn-mute-mic"
                    onClick={onMute}
                    disabled={!isMicStarted}
                    className="btn btn-secondary"
                >
                    🔇 Mute Mic
                </button>
            </div>
        </section>
    )
}
