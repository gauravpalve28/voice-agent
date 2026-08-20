/**
 * StatusPanel component.
 *
 * Displays the current mic, call, and pipeline state indicators.
 *
 * @param {object} props
 * @param {boolean} props.isMicStarted
 * @param {boolean} props.isStarted
 * @param {string|null} props.callState
 */
export default function StatusPanel({ isMicStarted, isStarted, callState }) {
    return (
        <section className="status">
            <h2>Status</h2>
            <div className="status-items">
                <div className={`status-item ${isMicStarted ? 'active' : ''}`}>
                    <span>🎙️ Microphone:</span>
                    <span>{isMicStarted ? 'ON' : 'OFF'}</span>
                </div>
                <div className={`status-item ${isStarted ? 'active' : ''}`}>
                    <span>💬 Call:</span>
                    <span>{isStarted ? 'ACTIVE' : 'IDLE'}</span>
                </div>
                {callState && (
                    <div className="status-item">
                        <span>📊 State:</span>
                        <span>{callState}</span>
                    </div>
                )}
            </div>
        </section>
    )
}
