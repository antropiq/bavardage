const OutputHandler = (() => {
    const outputEl = document.getElementById("output");

    let cursorPos = 0;
    let _pendingFinal = null;
    let _pendingCursor = null;
    let _finalTimeout = null;
    let llmEnabled = false;

    function replaceFromCursor(text) {
        outputEl.textContent = outputEl.textContent.slice(0, cursorPos) + text;
        outputEl.scrollTop = outputEl.scrollHeight;
    }

    function finalizeRaw(text) {
        const startCursor = cursorPos;
        replaceFromCursor(text.replace(/\r?\n/g, " ").trim());
        outputEl.textContent += " ";
        cursorPos = outputEl.textContent.length;
        return startCursor;
    }

    function handleFinal(data) {
        const startCursor = finalizeRaw(data.text);
        if (llmEnabled) {
            _pendingFinal = data.text;
            _pendingCursor = startCursor;
            if (_finalTimeout) {
                clearTimeout(_finalTimeout);
            }
            _finalTimeout = setTimeout(() => {
                if (_pendingFinal !== null) {
                    outputEl.textContent = outputEl.textContent.slice(0, _pendingCursor);
                    cursorPos = _pendingCursor;
                    _pendingFinal = null;
                    _pendingCursor = null;
                }
            }, 3000);
        }
    }

    function handleFinalLlm(data) {
        if (_pendingCursor !== null) {
            clearTimeout(_finalTimeout);
            _finalTimeout = null;
            cursorPos = _pendingCursor;
            replaceFromCursor(data.text.replace(/\r?\n/g, " ").trim());
            outputEl.textContent += " ";
            cursorPos = outputEl.textContent.length;
            _pendingFinal = null;
            _pendingCursor = null;
        }
    }

    function handlePartial(data) {
        if (outputEl.textContent.length > 0 &&
            cursorPos >= outputEl.textContent.length &&
            outputEl.textContent.charAt(outputEl.textContent.length - 1) !== " ") {
            outputEl.textContent += " ";
            cursorPos = outputEl.textContent.length;
        }
        replaceFromCursor(data.text.replace(/\r?\n/g, " "));
    }

    function handleWsMessage(event) {
        if (event.data === "pong") {
            return;
        }
        const data = JSON.parse(event.data);
        if (data.type === "final") {
            handleFinal(data);
        } else if (data.type === "final_llm") {
            handleFinalLlm(data);
        } else if (data.type === "partial") {
            handlePartial(data);
        } else if (data.type === "pong") {
            // Server acknowledged our ping
        }
    }

    function clearLastLine() {
        if (_pendingCursor !== null) {
            _pendingFinal = null;
            _pendingCursor = null;
            if (_finalTimeout) {
                clearTimeout(_finalTimeout);
                _finalTimeout = null;
            }
            return;
        }
        const lines = outputEl.textContent.split("\n");
        if (lines.length > 0) {
            lines.pop();
            outputEl.textContent = lines.join("\n");
        }
    }

    function clearAll() {
        outputEl.textContent = "";
        _pendingFinal = null;
        _pendingCursor = null;
        cursorPos = 0;
        if (_finalTimeout) {
            clearTimeout(_finalTimeout);
            _finalTimeout = null;
        }
    }

    function reset() {
        _pendingFinal = null;
        _pendingCursor = null;
        cursorPos = 0;
        if (_finalTimeout) {
            clearTimeout(_finalTimeout);
            _finalTimeout = null;
        }
    }

    function setLlmEnabled(enabled) {
        llmEnabled = enabled;
    }

    return {
        handleWsMessage,
        handleFinal,
        handleFinalLlm,
        handlePartial,
        clearLastLine,
        clearAll,
        reset,
        setLlmEnabled,
    };
})();
