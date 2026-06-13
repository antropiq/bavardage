const OutputHandler = (() => {
    const outputEl = document.getElementById("output");

    let cursorPos = 0;
    let _pendingStack = [];
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
            _pendingStack.push({ text: data.text, cursorPos: startCursor });
            if (_finalTimeout) {
                clearTimeout(_finalTimeout);
            }
            _finalTimeout = setTimeout(() => {
                if (_pendingStack.length > 0) {
                    const pending = _pendingStack[0];
                    outputEl.textContent = outputEl.textContent.slice(0, pending.cursorPos);
                    cursorPos = pending.cursorPos;
                    _pendingStack = [];
                }
            }, 2000);
        }
    }

    function handleFinalLlm(data) {
        if (_pendingStack.length > 0) {
            clearTimeout(_finalTimeout);
            _finalTimeout = null;
            const pending = _pendingStack.shift();
            const rawLen = pending.text.replace(/\r?\n/g, " ").trim().length;
            const llmText = data.text.replace(/\r?\n/g, " ").trim();
            const llmLen = llmText.length;
            const delta = llmLen - rawLen;

            // Update cursor positions for all remaining pending entries
            for (const entry of _pendingStack) {
                entry.cursorPos += delta;
            }

            // Find the end of this fragment (start of next or end of DOM)
            const nextCursor = _pendingStack.length > 0
                ? _pendingStack[0].cursorPos
                : outputEl.textContent.length;

            // Replace only this fragment's portion while preserving subsequent fragments
            const before = outputEl.textContent.slice(0, pending.cursorPos);
            const after = outputEl.textContent.slice(nextCursor);
            outputEl.textContent = before + llmText + " " + after;

            cursorPos = pending.cursorPos + llmLen + 1 + after.length;
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
        if (_pendingStack.length > 0) {
            _pendingStack = [];
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
        _pendingStack = [];
        cursorPos = 0;
        if (_finalTimeout) {
            clearTimeout(_finalTimeout);
            _finalTimeout = null;
        }
    }

    function reset() {
        _pendingStack = [];
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
