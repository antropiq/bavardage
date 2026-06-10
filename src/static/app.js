const toggleBtn = document.getElementById("toggleBtn");
const statusEl = document.getElementById("status");
const outputEl = document.getElementById("output");
const partialEl = document.getElementById("partial");
const modeIndicator = document.getElementById("modeIndicator");

let ws = null;
let audioCtx = null;
let mediaStream = null;
let audioWorkletNode = null;
let isRecording = false;
let totalBytes = 0;
let callbackCount = 0;
let modelReady = false;
let pingInterval = null;
let lastPartialText = "";
let commandMode = false;

const WS_URL = `ws://${location.host}/ws`;
const HEALTH_URL = `/health`;

function setStatus(text, listening = false) {
    statusEl.textContent = text;
    statusEl.className = "status" + (listening ? " listening" : "");
}

function setCommandMode(mode) {
    commandMode = mode;
    if (mode) {
        statusEl.className = "status command-mode listening";
        setStatus("Mode commande — dites \"bavardage\" pour revenir");
        modeIndicator.style.display = "inline-block";
    } else {
        setStatus("Écoute en cours…", true);
        modeIndicator.style.display = "none";
    }
}

function appendText(text) {
    if (outputEl.value.length > 0) {
        outputEl.value += "\n";
    }
    outputEl.value += text;
    outputEl.scrollTop = outputEl.scrollHeight;
}

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
            if (data.type === "mode_change") {
                console.log("[app] Mode changed to:", data.mode);
                setCommandMode(data.mode === "command");
                return;
            }
            if (data.type === "command") {
                if (data.action === "clear") {
                    console.log("[app] Clear command received");
                    outputEl.value = "";
                    return;
                }
                if (data.action === "clear_last_line") {
                    console.log("[app] Clear last line command received");
                    const lines = outputEl.value.split("\n");
                    if (lines.length > 0) {
                        lines.pop();
                        outputEl.value = lines.join("\n");
                    }
                    return;
                }
            }
            if (data.type === "final") {
                appendText(data.text);
                partialEl.textContent = "";
                lastPartialText = "";
            }
            if (data.type === "partial") {
                if (data.text !== lastPartialText) {
                    lastPartialText = data.text;
                    partialEl.textContent = data.text;
                }
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

    if (audioWorkletNode) {
        try { audioWorkletNode.disconnect(); } catch(e) {}
        audioWorkletNode.port.onmessage = null;
        audioWorkletNode = null;
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
    lastPartialText = "";
    commandMode = false;
    console.log("[app] Stopped. Callbacks:", callbackCount, "Total bytes:", totalBytes);
}

async function initAudio() {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    console.log("[app] AudioContext created, sampleRate:", audioCtx.sampleRate, "state:", audioCtx.state);

    // Listen for state changes (could indicate a problem)
    audioCtx.addEventListener('statechange', () => {
        const ctx = audioCtx;
        if (!ctx) return;
        console.log("[app] AudioContext state changed to:", ctx.state);
        if (ctx.state === 'suspended') {
            console.warn("[app] AudioContext suspended — check for errors");
        }
        if (ctx.state === 'closed') {
            console.error("[app] AudioContext closed unexpectedly");
        }
    });

    // Catch errors from the worklet thread
    const originalConsoleError = console.error;
    console.error = function(...args) {
        originalConsoleError.apply(console, args);
        if (args[0] && typeof args[0] === 'string' && args[0].includes('[worklet]')) {
            originalConsoleError.apply(console, ['[app] WORKLET ERROR:', args[0].replace('[worklet] ', '')]);
        }
    };

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
    console.log("[app] MediaStreamSource created");

    // Load the AudioWorklet module
    const workletUrl = `/audio-processor.js?v=6`;
    try {
        await audioCtx.audioWorklet.addModule(workletUrl);
        console.log("[app] AudioWorklet module loaded");
    } catch (err) {
        console.error("[app] Failed to load AudioWorklet:", err);
        setStatus("Erreur: AudioWorklet non supporté");
        stopRecording();
        return;
    }

    // Create the AudioWorkletNode
    audioWorkletNode = new AudioWorkletNode(audioCtx, 'resample-processor', {
        numberOfInputs: 1,
        numberOfOutputs: 1,
        channelCount: 1,
    });
    console.log("[app] AudioWorkletNode created");

    // Handle audio data from the worklet
    audioWorkletNode.port.onmessage = (event) => {
        callbackCount++;
        if (callbackCount % 100 === 1) {
            console.log("[app] Worklet callback #", callbackCount, "ws.readyState:", ws ? ws.readyState : "null");
        }

        if (!ws || ws.readyState !== WebSocket.OPEN) return;

        const msg = event.data;
        if (msg.type === 'audio') {
            totalBytes += msg.data.byteLength;
            ws.send(msg.data);
        }
    };

    // Error handler on the worklet port
    audioWorkletNode.port.onerror = (err) => {
        console.error("[worklet] Port error:", err);
        console.error("[app] Worklet port error — stopping recording");
        setStatus("Erreur audio — vérifiez la console");
        stopRecording();
    };

    // Connect: source → worklet (no destination — use headphones if you need monitoring)
    source.connect(audioWorkletNode);

    console.log("[app] Audio graph connected (AudioWorklet)");
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
