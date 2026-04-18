(() => {
  const state = {
    context: null,
    sessionId: null,
    socket: null,
    latestLatency: {
      transcription: null,
      llm: null,
      execution: null,
      tts: null,
      endToEnd: null,
    },
    timelineCount: 0,
    micCapture: null,
    micActive: false,
    queueDepth: 0,
    autoplayAudio: true,
  };

  const el = (id) => document.getElementById(id);

  const buttons = {
    create: el("btn-create-session"),
    connect: el("btn-connect-ws"),
    disconnect: el("btn-disconnect-ws"),
    upload: el("btn-upload"),
    uploadSample: el("btn-upload-sample"),
    clearTimeline: el("btn-clear-timeline"),
    micStart: el("btn-mic-start"),
    micStop: el("btn-mic-stop"),
  };

  const labels = {
    serviceInfo: el("service-info"),
    sessionId: el("session-id"),
    sessionStatus: el("session-status"),
    wsStatus: el("ws-status"),
    transcript: el("transcript-text"),
    assistantText: el("assistant-text"),
    assistantAudio: el("assistant-audio"),
    assistantAudioLink: el("assistant-audio-link"),
    providers: el("provider-chips"),
    uploadStatus: el("upload-status"),
    sampleSelect: el("sample-select"),
    simHeading: el("sim-heading"),
    simVelocity: el("sim-velocity"),
    simIsMoving: el("sim-is-moving"),
    simLastAction: el("sim-last-action"),
    simUpdatedAt: el("sim-updated-at"),
    latTranscription: el("lat-transcription"),
    latLlm: el("lat-llm"),
    latExecution: el("lat-execution"),
    latTts: el("lat-tts"),
    latEndToEnd: el("lat-end-to-end"),
    timeline: el("timeline"),
    timelineCount: el("timeline-count"),
    audioFile: el("audio-file"),
    micState: el("mic-state"),
    micProcessing: el("mic-processing"),
    micVoice: el("mic-voice"),
    micQueue: el("mic-queue"),
    micStatus: el("mic-status"),
    autoplayCheckbox: el("chk-autoplay"),
  };

  const setUploadStatus = (text, level = "") => {
    labels.uploadStatus.textContent = text;
    labels.uploadStatus.className = level;
  };

  const setMicStatus = (text, level = "") => {
    labels.micStatus.textContent = text;
    labels.micStatus.className = level;
  };

  const setMicState = (value) => {
    labels.micState.textContent = value;
  };

  const setMicProcessing = (value) => {
    labels.micProcessing.textContent = value;
  };

  const setMicVoice = (speaking) => {
    labels.micVoice.textContent = speaking ? "speaking" : "silent";
  };

  const setMicQueue = (depth) => {
    state.queueDepth = depth;
    labels.micQueue.textContent = String(depth);
  };

  const updateMicButtons = () => {
    const ready = Boolean(state.sessionId) && state.context?.live_audio?.enabled;
    buttons.micStart.disabled = !ready || state.micActive;
    buttons.micStop.disabled = !state.micActive;
  };

  const formatMs = (value) => (value == null ? "-" : `${value} ms`);

  const setSimulatorState = (simulator) => {
    if (!simulator) {
      labels.simHeading.textContent = "-";
      labels.simVelocity.textContent = "-";
      labels.simIsMoving.textContent = "-";
      labels.simLastAction.textContent = "-";
      labels.simUpdatedAt.textContent = "-";
      return;
    }
    labels.simHeading.textContent = Number(simulator.heading_deg).toFixed(1);
    labels.simVelocity.textContent = Number(simulator.velocity).toFixed(2);
    labels.simIsMoving.textContent = simulator.is_moving ? "true" : "false";
    labels.simLastAction.textContent = simulator.last_action || "-";
    labels.simUpdatedAt.textContent = simulator.updated_at || "-";
  };

  const renderLatency = () => {
    labels.latTranscription.textContent = formatMs(state.latestLatency.transcription);
    labels.latLlm.textContent = formatMs(state.latestLatency.llm);
    labels.latExecution.textContent = formatMs(state.latestLatency.execution);
    labels.latTts.textContent = formatMs(state.latestLatency.tts);
    labels.latEndToEnd.textContent = formatMs(state.latestLatency.endToEnd);
  };

  const resetLatency = () => {
    state.latestLatency = {
      transcription: null,
      llm: null,
      execution: null,
      tts: null,
      endToEnd: null,
    };
    renderLatency();
  };

  const appendTimeline = (event) => {
    state.timelineCount += 1;
    const item = document.createElement("li");
    const time = document.createElement("span");
    time.className = "evt-time";
    time.textContent = event.timestamp || new Date().toISOString();
    const type = document.createElement("span");
    type.className = event.type === "error" ? "evt-error" : "evt-type";
    type.textContent = event.type;
    const payload = document.createElement("span");
    payload.className = "evt-payload";
    payload.textContent = event.payload ? JSON.stringify(event.payload) : "";
    item.appendChild(time);
    item.appendChild(type);
    item.appendChild(payload);
    labels.timeline.appendChild(item);
    labels.timeline.scrollTop = labels.timeline.scrollHeight;
    labels.timelineCount.textContent = `${state.timelineCount} events`;
  };

  const clearTimeline = () => {
    labels.timeline.innerHTML = "";
    state.timelineCount = 0;
    labels.timelineCount.textContent = "0 events";
  };

  const updateProviderChips = () => {
    if (!state.context) return;
    labels.providers.innerHTML = "";
    const entries = [state.context.providers.stt, state.context.providers.llm, state.context.providers.tts];
    for (const entry of entries) {
      const chip = document.createElement("span");
      chip.className = `chip ${entry.configured ? "ok" : "warn"}`;
      chip.textContent = `${entry.name}: ${entry.provider}`;
      chip.title = entry.detail || "";
      labels.providers.appendChild(chip);
    }
  };

  const setWsStatus = (value) => {
    labels.wsStatus.textContent = value;
  };

  const loadContext = async () => {
    const response = await fetch("/api/v1/demo/context");
    if (!response.ok) {
      throw new Error(`context request failed: ${response.status}`);
    }
    state.context = await response.json();
    labels.serviceInfo.textContent = `${state.context.service} / ${state.context.environment} / demo_mode=${state.context.demo_mode}`;
    updateProviderChips();
  };

  const loadSamples = async () => {
    if (!state.context) return;
    try {
      const response = await fetch(state.context.demo_samples_path);
      if (!response.ok) return;
      const payload = await response.json();
      labels.sampleSelect.innerHTML = "";
      if (!payload.assets.length) {
        const option = document.createElement("option");
        option.value = "";
        option.textContent = "no bundled samples";
        labels.sampleSelect.appendChild(option);
        buttons.uploadSample.disabled = true;
        return;
      }
      for (const asset of payload.assets) {
        const option = document.createElement("option");
        option.value = asset.name;
        option.textContent = `${asset.name} (${asset.size_bytes} bytes)`;
        labels.sampleSelect.appendChild(option);
      }
      buttons.uploadSample.disabled = !state.sessionId;
    } catch (err) {
      console.error(err);
    }
  };

  const createSession = async () => {
    buttons.create.disabled = true;
    try {
      const response = await fetch(`${state.context.sessions_path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      if (!response.ok) {
        throw new Error(`session create failed: ${response.status}`);
      }
      const session = await response.json();
      state.sessionId = session.session_id;
      labels.sessionId.textContent = session.session_id;
      labels.sessionStatus.textContent = session.status;
      buttons.connect.disabled = false;
      buttons.uploadSample.disabled = !labels.sampleSelect.value;
      setUploadStatus("session created", "ok");
      updateMicButtons();
    } catch (err) {
      setUploadStatus(err.message, "error");
    } finally {
      buttons.create.disabled = false;
    }
  };

  const computeWsUrl = () => {
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    return `${scheme}://${window.location.host}${state.context.websocket_base_path}/${state.sessionId}`;
  };

  const handleEvent = (event) => {
    appendTimeline(event);
    const payload = event.payload || {};
    if (event.type === "session.connected") {
      labels.sessionStatus.textContent = payload.session_status || "active";
    }
    if (event.type === "transcription.completed") {
      labels.transcript.textContent = payload.text || "-";
      state.latestLatency.transcription = payload.duration_ms ?? null;
      renderLatency();
    }
    if (event.type === "llm.completed") {
      state.latestLatency.llm = payload.duration_ms ?? null;
      renderLatency();
    }
    if (event.type === "assistant.response") {
      labels.assistantText.textContent = payload.text || "-";
    }
    if (event.type === "assistant.audio_ready") {
      const url = payload.url;
      if (url) {
        labels.assistantAudio.src = url;
        labels.assistantAudioLink.href = url;
        labels.assistantAudioLink.textContent = url;
      }
    }
    if (event.type === "tts.completed") {
      state.latestLatency.tts = payload.duration_ms ?? null;
      renderLatency();
    }
    if (event.type === "action.execution_completed") {
      state.latestLatency.execution = payload.duration_ms ?? null;
      renderLatency();
    }
    if (event.type === "simulator.state_updated") {
      setSimulatorState(payload.state);
    }
    if (event.type === "session.state" && payload.simulator_state) {
      setSimulatorState(payload.simulator_state);
    }
    if (event.type === "live_audio.started") {
      setMicProcessing("idle");
    }
    if (event.type === "live_audio.utterance_captured") {
      setMicProcessing("queued");
    }
    if (event.type === "live_audio.processing_started") {
      setMicProcessing("processing");
      resetLatency();
    }
    if (event.type === "live_audio.processing_completed") {
      setMicProcessing(payload.status === "failed" ? "failed" : "completed");
    }
    if (event.type === "live_audio.idle") {
      setMicProcessing("idle");
      setMicQueue(0);
    }
    if (event.type === "assistant.audio_ready" && state.autoplayAudio && state.micActive) {
      const audioElement = labels.assistantAudio;
      if (audioElement) {
        audioElement.muted = false;
        audioElement.play().catch(() => {});
      }
    }
  };

  const connectWebsocket = () => {
    if (!state.sessionId) return;
    const socket = new WebSocket(computeWsUrl());
    state.socket = socket;
    setWsStatus("connecting");
    buttons.connect.disabled = true;
    buttons.disconnect.disabled = false;
    buttons.upload.disabled = false;
    socket.addEventListener("open", () => {
      setWsStatus("open");
    });
    socket.addEventListener("message", (evt) => {
      try {
        const parsed = JSON.parse(evt.data);
        handleEvent(parsed);
      } catch (err) {
        console.error(err);
      }
    });
    socket.addEventListener("close", () => {
      setWsStatus("closed");
      state.socket = null;
      buttons.connect.disabled = false;
      buttons.disconnect.disabled = true;
      buttons.upload.disabled = true;
    });
    socket.addEventListener("error", () => {
      setWsStatus("error");
    });
  };

  const disconnectWebsocket = () => {
    if (state.socket) {
      state.socket.close();
    }
  };

  const uploadFile = async (fileOrBlob, filename) => {
    if (!state.sessionId) {
      setUploadStatus("create a session first", "error");
      return;
    }
    setUploadStatus(`uploading ${filename}...`);
    resetLatency();
    const formData = new FormData();
    formData.append("file", fileOrBlob, filename);
    try {
      const response = await fetch(
        `${state.context.sessions_path}/${state.sessionId}/transcriptions`,
        { method: "POST", body: formData }
      );
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(`upload failed: ${response.status} ${detail}`);
      }
      const result = await response.json();
      setUploadStatus(`uploaded ${filename} (request_id=${result.request_id})`, "ok");
      const start = Date.now();
      const waitAndEstimate = () => {
        const elapsed = Date.now() - start;
        if (state.latestLatency.endToEnd == null) {
          state.latestLatency.endToEnd = elapsed;
          renderLatency();
        }
      };
      setTimeout(waitAndEstimate, 250);
    } catch (err) {
      setUploadStatus(err.message, "error");
    }
  };

  const handleLocalUpload = async () => {
    const file = labels.audioFile.files[0];
    if (!file) {
      setUploadStatus("choose an audio file first", "error");
      return;
    }
    await uploadFile(file, file.name);
  };

  const submitLiveUtterance = async ({ blob, durationMs, filename, mimeType }) => {
    if (!state.sessionId) return;
    setMicQueue(state.queueDepth + 1);
    const formData = new FormData();
    formData.append("file", new Blob([blob], { type: mimeType }), filename);
    formData.append("duration_ms", String(Math.round(durationMs)));
    try {
      const response = await fetch(
        `${state.context.api_prefix}/sessions/${state.sessionId}/live-audio`,
        { method: "POST", body: formData }
      );
      if (!response.ok) {
        const detail = await response.text();
        setMicStatus(`utterance rejected: ${response.status} ${detail}`, "error");
        setMicQueue(Math.max(state.queueDepth - 1, 0));
        return;
      }
      const payload = await response.json();
      setMicQueue(payload.queued_position);
      setMicStatus(`utterance queued (${durationMs} ms)`, "ok");
    } catch (err) {
      setMicStatus(err.message, "error");
      setMicQueue(Math.max(state.queueDepth - 1, 0));
    }
  };

  const startMicrophone = async () => {
    if (!state.sessionId || !state.context?.live_audio?.enabled) {
      setMicStatus("live audio not available", "error");
      return;
    }
    if (typeof window.LiveAudioCapture === "undefined") {
      setMicStatus("live audio capture not loaded", "error");
      return;
    }
    try {
      await fetch(
        `${state.context.api_prefix}/sessions/${state.sessionId}/live-audio/start`,
        { method: "POST" }
      );
      const config = state.context.live_audio;
      const capture = new window.LiveAudioCapture({
        silenceWindowMs: config.silence_window_ms,
        minMs: Math.max(Math.round(config.min_seconds_per_utterance * 1000), 0),
        maxMs: Math.round(config.max_seconds_per_utterance * 1000),
        onUtterance: submitLiveUtterance,
        onVoiceState: setMicVoice,
        onError: (err) => setMicStatus(err.message || String(err), "error"),
      });
      await capture.start();
      state.micCapture = capture;
      state.micActive = true;
      setMicState("listening");
      setMicStatus("microphone active", "ok");
      updateMicButtons();
    } catch (err) {
      setMicStatus(err.message || String(err), "error");
    }
  };

  const stopMicrophone = async () => {
    const capture = state.micCapture;
    state.micCapture = null;
    state.micActive = false;
    if (capture) {
      capture.stop();
    }
    setMicState("idle");
    setMicVoice(false);
    updateMicButtons();
    if (state.sessionId) {
      try {
        await fetch(
          `${state.context.api_prefix}/sessions/${state.sessionId}/live-audio/stop`,
          { method: "POST" }
        );
      } catch (err) {
        console.error(err);
      }
    }
    setMicStatus("microphone stopped");
  };

  const handleSampleUpload = async () => {
    const name = labels.sampleSelect.value;
    if (!name) {
      setUploadStatus("select a sample first", "error");
      return;
    }
    const response = await fetch(`${state.context.demo_samples_path}/${name}`);
    if (!response.ok) {
      setUploadStatus(`failed to fetch sample ${name}`, "error");
      return;
    }
    const blob = await response.blob();
    await uploadFile(blob, name);
  };

  const refreshOverview = async () => {
    if (!state.sessionId || !state.context) return;
    try {
      const response = await fetch(
        `${state.context.api_prefix}/demo/sessions/${state.sessionId}/overview`
      );
      if (!response.ok) return;
      const overview = await response.json();
      if (overview.latest_latency) {
        const latency = overview.latest_latency;
        state.latestLatency.transcription = latency.transcription_duration_ms ?? state.latestLatency.transcription;
        state.latestLatency.llm = latency.llm_duration_ms ?? state.latestLatency.llm;
        state.latestLatency.execution = latency.execution_duration_ms ?? state.latestLatency.execution;
        state.latestLatency.tts = latency.tts_duration_ms ?? state.latestLatency.tts;
        if (latency.end_to_end_duration_ms != null) {
          state.latestLatency.endToEnd = latency.end_to_end_duration_ms;
        }
        renderLatency();
      }
      if (overview.simulator_state) {
        setSimulatorState(overview.simulator_state);
      }
    } catch (err) {
      console.error(err);
    }
  };

  buttons.create.addEventListener("click", createSession);
  buttons.connect.addEventListener("click", connectWebsocket);
  buttons.disconnect.addEventListener("click", disconnectWebsocket);
  buttons.upload.addEventListener("click", handleLocalUpload);
  buttons.uploadSample.addEventListener("click", handleSampleUpload);
  buttons.clearTimeline.addEventListener("click", clearTimeline);
  buttons.micStart.addEventListener("click", startMicrophone);
  buttons.micStop.addEventListener("click", stopMicrophone);
  labels.autoplayCheckbox.addEventListener("change", (evt) => {
    state.autoplayAudio = evt.target.checked;
  });

  setInterval(refreshOverview, 4000);

  (async () => {
    try {
      await loadContext();
      await loadSamples();
      if (state.context?.live_audio) {
        state.autoplayAudio = Boolean(state.context.live_audio.autoplay_default);
        labels.autoplayCheckbox.checked = state.autoplayAudio;
      }
      updateMicButtons();
      setMicQueue(0);
    } catch (err) {
      labels.serviceInfo.textContent = `failed to load context: ${err.message}`;
    }
  })();
})();
