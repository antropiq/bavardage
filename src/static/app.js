const toggleBtn = document.getElementById("toggleBtn");
const outputEl = document.getElementById("output");
const partialEl = document.getElementById("partial");
const conversationEl = document.getElementById("conversation");
const askQuestionBtn = document.getElementById("askQuestionBtn");

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
let llmEnabled = false;

const WS_URL = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`;
const HEALTH_URL = `/health`;

function appendText(text) {
    if (outputEl.textContent.length > 0) {
        outputEl.textContent += "\n";
    }
    outputEl.textContent += text;
    outputEl.scrollTop = outputEl.scrollHeight;
}

async function waitForModel() {
    toggleBtn.disabled = true;
    toggleBtn.textContent = "Chargement…";

    while (!modelReady) {
        try {
            const res = await fetch(HEALTH_URL);
            const data = await res.json();
            console.log("[app] Health check:", data);
            if (data.status === "ready") {
                modelReady = true;
                toggleBtn.disabled = false;
                toggleBtn.textContent = "Démarrer";
                console.log("[app] Model loaded");

                // Check LLM availability
                llmEnabled = data.llm_enabled || false;
                askQuestionBtn.disabled = !llmEnabled;
                if (llmEnabled) {
                    console.log("[app] LLM post-processing enabled");
                }
                return;
            }
        } catch (err) {
            console.warn("[app] Health check failed:", err.message);
        }
        await new Promise((r) => setTimeout(r, 500));
    }
}

async function startRecording() {
    try {
        ws = new WebSocket(WS_URL);

        ws.onopen = () => {
            console.log("[app] WebSocket connected");
            isRecording = true;
            toggleBtn.textContent = "Arrêter";
            toggleBtn.className = "btn btn-stop";
            initAudio();
            pingInterval = setInterval(() => {
                if (ws.readyState === WebSocket.OPEN) {
                    ws.send("ping");
                }
            }, 10000);
        };

        ws.onmessage = (event) => {
            if (event.data === "pong") {
                return;
            }
            const data = JSON.parse(event.data);
            if (data.type === "ready") {
                console.log("[app] Server ready, starting audio");
                return;
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
        };

        ws.onclose = (e) => {
            console.log("[app] WebSocket closed:", e.code, e.reason);
            stopRecording();
        };
    } catch (err) {
        console.error("[app] Start error:", err);
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
    outputEl.value = "";
    partialEl.textContent = "";
    lastPartialText = "";
    console.log("[app] Stopped. Callbacks:", callbackCount, "Total bytes:", totalBytes);
}

function clearLastLine() {
    const lines = outputEl.textContent.split("\n");
    if (lines.length > 0) {
        lines.pop();
        outputEl.textContent = lines.join("\n");
    }
}

function clearAll() {
    outputEl.textContent = "";
}

function appendConversationEntry(question, answer) {
    conversationEl.innerHTML = "";

    const questionDiv = document.createElement("div");
    questionDiv.className = "conversation-question";
    questionDiv.textContent = question;

    const answerDiv = document.createElement("div");
    answerDiv.className = "conversation-answer";
    answerDiv.textContent = answer;

    conversationEl.appendChild(questionDiv);
    conversationEl.appendChild(answerDiv);
}

function appendConversationLoading(question) {
    const questionDiv = document.createElement("div");
    questionDiv.className = "conversation-question";
    questionDiv.textContent = question;

    const loadingDiv = document.createElement("div");
    loadingDiv.className = "conversation-loading";
    loadingDiv.textContent = "Recherche en cours";

    conversationEl.innerHTML = "";
    conversationEl.appendChild(questionDiv);
    conversationEl.appendChild(loadingDiv);
    return loadingDiv;
}

async function askQuestion() {
    const text = outputEl.textContent.trim();
    if (!text) {
        console.warn("[app] No text to ask about");
        return;
    }
    if (!llmEnabled) {
        console.warn("[app] LLM not enabled");
        return;
    }

    askQuestionBtn.disabled = true;
    const loadingEl = appendConversationLoading(text);
    console.log("[app] Sending to LLM:", text.substring(0, 200));

    try {
        const res = await fetch("/api/llm-chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text }),
        });
        console.log("[app] LLM response status:", res.status);

        const data = await res.json();

        if (!res.ok || data.error) {
            console.error("[app] LLM chat error:", data.error);
            appendConversationLoading(text + "\n[Erreur: " + data.error + "]");
            return;
        }

        appendConversationEntry(text, data.answer);
    } catch (err) {
        console.error("[app] LLM chat request failed:", err);
    } finally {
        askQuestionBtn.disabled = !llmEnabled;
    }
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
    const workletUrl = `/static/audio-processor.js?v=7`;
    try {
        await audioCtx.audioWorklet.addModule(workletUrl);
        console.log("[app] AudioWorklet module loaded");
    } catch (err) {
        console.error("[app] Failed to load AudioWorklet:", err);
        console.error("[app] AudioWorklet non supporté");
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

document.getElementById("clearLastLineBtn").addEventListener("click", clearLastLine);
document.getElementById("clearAllBtn").addEventListener("click", clearAll);
askQuestionBtn.addEventListener("click", askQuestion);

// Start polling on page load
waitForModel();
