const toggleBtn = document.getElementById("toggleBtn");
const statusEl = document.getElementById("status");
const outputEl = document.getElementById("output");
const partialEl = document.getElementById("partial");

let ws = null;
let audioCtx = null;
let mediaStream = null;
let scriptProcessor = null;
let isRecording = false;
let totalBytes = 0;
let callbackCount = 0;
let modelReady = false;
let pingInterval = null;

const WS_URL = `ws://${location.host}/ws`;
const HEALTH_URL = `/health`;

function setStatus(text, listening = false) {
    statusEl.textContent = text;
    statusEl.className = "status" + (listening ? " listening" : "");
}

function appendText(text) {
    if (outputEl.value.length > 0) {
        outputEl.value += "\n";
    }
    outputEl.value += text;
    outputEl.scrollTop = outputEl.scrollHeight;
}

// Poll /health until model is loaded
async function waitForModel() {
    toggleBtn.disabled = true;
    toggleBtn.textContent = "Chargement…";
    setStatus("Chargement du modèle vocal…");

    while (!modelReady) {
        try {
            const res = await fetch(HEALTH_URL);
            const data = await res.json();
            if (data.status === "ready") {
                modelReady = true;
                toggleBtn.disabled = false;
                toggleBtn.textContent = "Démarrer";
                setStatus("Prêt — cliquez pour démarrer");
                console.log("[app] Model loaded");
                return;
            }
        } catch {
            // ignore transient errors
        }
        await new Promise((r) => setTimeout(r, 500));
    }
}

async function startRecording() {
    if (!modelReady) {
        setStatus("Modèle en cours de chargement…");
        return;
    }

    try {
        ws = new WebSocket(WS_URL);

        ws.onopen = () => {
            console.log("[app] WebSocket connected");
            isRecording = true;
            toggleBtn.textContent = "Arrêter";
            toggleBtn.className = "btn btn-stop";
            setStatus("Écoute en cours…", true);
            initAudio();
            // Send ping every 10 seconds so server knows we're alive
            pingInterval = setInterval(() => {
                if (ws.readyState === WebSocket.OPEN) {
                    ws.send("ping");
                }
            }, 10000);
        };

        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.type === "ready") {
                console.log("[app] Server ready, starting audio");
                return;
            }
            if (data.type === "final") {
                appendText(data.text);
                partialEl.textContent = "";
            }
            if (data.type === "partial") {
                partialEl.textContent = data.text;
            }
            if (data.type === "pong") {
                // Server acknowledged our ping
            }
        };

        ws.onerror = (err) => {
            console.error("[app] WebSocket error:", err);
            stopRecording();
            setStatus("Erreur de connexion");
        };

        ws.onclose = (e) => {
            console.log("[app] WebSocket closed:", e.code, e.reason);
            stopRecording();
            setStatus("Connecteur fermé");
        };
    } catch (err) {
        console.error("[app] Start error:", err);
        setStatus("Erreur: " + err.message);
    }
}

function stopRecording() {
    isRecording = false;

    if (scriptProcessor) {
        scriptProcessor.disconnect();
        scriptProcessor = null;
    }
    if (mediaStream) {
        mediaStream.getTracks().forEach((t) => t.stop());
        mediaStream = null;
    }
    if (audioCtx) {
        audioCtx.close();
        audioCtx = null;
    }
    if (ws) {
        if (pingInterval) {
            clearInterval(pingInterval);
            pingInterval = null;
        }
        ws.close();
        ws = null;
    }

    toggleBtn.textContent = "Démarrer";
    toggleBtn.className = "btn btn-start";
    setStatus("En attente...");
    outputEl.value = "";
    partialEl.textContent = "";
    console.log("[app] Stopped. Callbacks:", callbackCount, "Total bytes:", totalBytes);
}

async function initAudio() {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    console.log("[app] AudioContext created, sampleRate:", audioCtx.sampleRate, "state:", audioCtx.state);

    if (audioCtx.state === "suspended") {
        await audioCtx.resume();
        console.log("[app] AudioContext resumed");
    }

    mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
            channelCount: 1,
            echoCancellation: true,
            noiseSuppression: true,
        },
    });
    console.log("[app] MediaStream ready");

    const source = audioCtx.createMediaStreamSource(mediaStream);

    scriptProcessor = audioCtx.createScriptProcessor(4096, 1, 1);

    scriptProcessor.onaudioprocess = (event) => {
        callbackCount++;
        if (callbackCount % 100 === 1) {
            console.log("[app] Callback #", callbackCount, "ws.readyState:", ws ? ws.readyState : "null");
        }

        if (!ws || ws.readyState !== WebSocket.OPEN) return;

        try {
            const input = event.inputBuffer.getChannelData(0);
            const inputRate = audioCtx.sampleRate;
            const targetRate = 16000;
            const ratio = inputRate / targetRate;
            const outLen = Math.floor(input.length / ratio);
            const pcm = new Int16Array(outLen);

            for (let i = 0; i < outLen; i++) {
                const srcIdx = i * ratio;
                const idx = Math.floor(srcIdx);
                const frac = srcIdx - idx;
                const a = idx < input.length ? input[idx] : 0;
                const b = (idx + 1) < input.length ? input[idx + 1] : 0;
                const s = a + frac * (b - a);
                pcm[i] = s < 0 ? Math.max(-1, s) * 0x8000 : Math.min(1, s) * 0x7fff;
            }

            totalBytes += pcm.byteLength;
            ws.send(pcm.buffer);
        } catch (err) {
            console.error("[app] Callback error:", err);
        }
    };

    source.connect(scriptProcessor);
    scriptProcessor.connect(audioCtx.destination);
    console.log("[app] Audio graph connected");
}

toggleBtn.addEventListener("click", () => {
    if (isRecording) {
        stopRecording();
    } else {
        startRecording();
    }
});

// Start polling on page load
waitForModel();
