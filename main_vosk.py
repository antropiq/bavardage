from vosk import Model, KaldiRecognizer
import pyaudio
import json
import sys

def main():
    # Path to your French model folder
    model_path = "vosk-model-fr-0.22"  # Update this to your extracted model folder

    try:
        model = Model(model_path)
    except Exception as e:
        print(f"Error loading model: {e}", file=sys.stderr)
        sys.exit(1)

    recognizer = KaldiRecognizer(model, 16000)

    p = pyaudio.PyAudio()
    stream = p.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=16000,
        input=True,
        frames_per_buffer=4000
    )
    stream.start_stream()

    print("Listening (French)... Press Ctrl+C to stop.", file=sys.stderr)

    try:
        while True:
            data = stream.read(4000, exception_on_overflow=False)
            if len(data) == 0:
                break

            if recognizer.AcceptWaveform(data):
                result = json.loads(recognizer.FinalResult())
                text = result.get("text", "").strip()
                if text:
                    # Clear any leftover partial text, then print final result
                    print(f"\r{' ' * 80}\r\x1b[1m\x1b[93m{text}\x1b[0m")
                    sys.stdout.flush()

            else:
                partial = recognizer.PartialResult()
                if partial and 'partial' in partial:
                    partial_text = json.loads(partial).get("partial", "").strip()
                    if partial_text:
                        print(f"\r{partial_text} ", end='', flush=True)

    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()

if __name__ == "__main__":
    main()
