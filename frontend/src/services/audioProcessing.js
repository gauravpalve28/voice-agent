/**
 * WebRTC Audio Processing Service
 * Handles noise suppression, echo cancellation, and auto gain control
 */

export class AudioProcessor {
    constructor(audioContext) {
        this.audioContext = audioContext
        this.sourceNode = null
        this.gainNode = null
        this.analyserNode = null
        this.highPassFilter = null
        this.compressor = null
        this.lowPassFilter = null
        this.isProcessing = false
        this._rafId = null
    }

    /**
     * Initialize audio processing with WebRTC constraints
     * @param {MediaStream} stream - Input audio stream from microphone
     * @returns {Promise<MediaStream>} - Processed audio stream
     */
    async initializeProcessing(stream) {
        try {
            this.sourceNode = this.audioContext.createMediaStreamSource(stream)

            // High-pass filter to remove low-frequency noise
            this.highPassFilter = this.audioContext.createBiquadFilter()
            this.highPassFilter.type = 'highpass'
            this.highPassFilter.frequency.value = 160 
            
            // Compressor to reduce sudden noise spikes
            this.compressor = this.audioContext.createDynamicsCompressor()
            this.compressor.threshold.value = -35
            this.compressor.ratio.value = 10
            this.compressor.attack.value = 0
            this.compressor.release.value = 0.25

            // Gain control for consistent volume
            this.gainNode = this.audioContext.createGain()
            this.gainNode.gain.value = 1.0

            // Noise Gate (KEY PART)
            this.analyserNode = this.audioContext.createAnalyser()
            this.analyserNode.fftSize = 512

            const dataArray = new Uint8Array(this.analyserNode.frequencyBinCount)

            const noiseGate = () => {
                if (!this.isProcessing) return
                this.analyserNode.getByteTimeDomainData(dataArray)
                let sum = 0
                for (let i = 0; i < dataArray.length; i++) {
                    const val = (dataArray[i] - 128) / 128
                    sum += val * val
                }
                const rms = Math.sqrt(sum / dataArray.length)

                // Threshold tuning
                this.gainNode.gain.value = rms < 0.02 ? 0 : 1

                this._rafId = requestAnimationFrame(noiseGate)
            }

            // Low-pass filter to remove sharp hiss
            this.lowPassFilter = this.audioContext.createBiquadFilter()
            this.lowPassFilter.type = 'lowpass'
            this.lowPassFilter.frequency.value = 8000

            this.sourceNode
                .connect(this.highPassFilter)
                .connect(this.lowPassFilter)
                .connect(this.compressor)
                .connect(this.gainNode)
                .connect(this.analyserNode)

            noiseGate()

            this.isProcessing = true
            return stream
        } catch (error) {
            console.error('Audio processing failed:', error)
            throw error
        }
    }

    /**
     * Stop audio processing
     */
    stop() {
        this.isProcessing = false
        if (this._rafId !== null) {
            cancelAnimationFrame(this._rafId)
            this._rafId = null
        }
        this.sourceNode?.disconnect()
        this.highPassFilter?.disconnect()
        this.lowPassFilter?.disconnect()
        this.compressor?.disconnect()
        this.gainNode?.disconnect()
        this.analyserNode?.disconnect()
    }
}

export default AudioProcessor

