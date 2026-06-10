/**
 * AudioWorklet Processor for real-time speech transcription.
 *
 * - Resample audio from AudioContext sample rate to 16 kHz
 * - Convert Float32 → Int16 PCM
 * - Emit fixed-size 1024-sample chunks via postMessage
 */
class ResampleProcessor extends AudioWorkletProcessor {
    static get parameterDescriptors() {
        return [];
    }

    constructor() {
        super();
        this.targetSampleRate = 16000;
        this.chunkSize = 1024;
        // Pointer into accumulated input buffer (samples already consumed)
        this.inputOffset = 0;
        // Buffer to hold input across process() calls
        this.inputBuffer = new Float32Array(0);
    }

    process(inputs, outputs) {
        const input = inputs[0];
        const output = outputs[0];

        // Copy input to output (pass-through for monitoring)
        if (input && input.length > 0 && output && output.length > 0) {
            const inChan = input[0];
            const outChan = output[0];
            const len = Math.min(inChan.length, outChan.length);
            for (let i = 0; i < len; i++) {
                outChan[i] = inChan[i];
            }
        }

        // No input — return true to keep processor alive
        if (!input || input.length === 0 || !input[0] || input[0].length === 0) {
            return true;
        }

        const inputChannel = input[0];
        const contextSampleRate = this.context ? this.context.sampleRate : 48000;
        const ratio = contextSampleRate / this.targetSampleRate;

        // Append new input to accumulated buffer
        const newBuffer = new Float32Array(this.inputBuffer.length + inputChannel.length);
        newBuffer.set(this.inputBuffer);
        newBuffer.set(inputChannel, this.inputBuffer.length);
        this.inputBuffer = newBuffer;

        // How many output samples can we produce from available input?
        const availableInput = this.inputBuffer.length - this.inputOffset;
        const outputSamples = Math.floor(availableInput / ratio);

        if (outputSamples <= 0) {
            return true;
        }

        // Resample into a temp buffer
        const resampled = new Float32Array(outputSamples);
        for (let i = 0; i < outputSamples; i++) {
            const srcIdx = this.inputOffset + i * ratio;
            const idx = Math.floor(srcIdx);
            const frac = srcIdx - idx;
            const a = idx < this.inputBuffer.length ? this.inputBuffer[idx] : 0;
            const b = (idx + 1) < this.inputBuffer.length ? this.inputBuffer[idx + 1] : 0;
            resampled[i] = a + frac * (b - a);
        }

        // Advance input offset
        this.inputOffset += outputSamples * ratio;

        // Convert to Int16 PCM
        const pcm = new Int16Array(resampled.length);
        for (let i = 0; i < resampled.length; i++) {
            const s = resampled[i] < 0 ? resampled[i] * 0x8000 : resampled[i] * 0x7fff;
            pcm[i] = s < -32768 ? -32768 : s > 32767 ? 32767 : s;
        }

        // Trim input buffer to remove consumed samples
        const remaining = this.inputBuffer.length - this.inputOffset;
        if (remaining > 0) {
            const trimmed = new Float32Array(remaining);
            trimmed.set(this.inputBuffer.subarray(this.inputOffset));
            this.inputBuffer = trimmed;
            this.inputOffset = 0;
        } else {
            this.inputBuffer = new Float32Array(0);
            this.inputOffset = 0;
        }

        // Send chunks to main thread
        for (let offset = 0; offset < pcm.length; offset += this.chunkSize) {
            const end = Math.min(offset + this.chunkSize, pcm.length);
            const chunk = pcm.subarray(offset, end);
            this.port.postMessage({
                type: 'audio',
                data: chunk.buffer,
            }, [chunk.buffer]);
        }

        return true;
    }
}

registerProcessor('resample-processor', ResampleProcessor);
