const state = {
  stations: [],
  selectedStation: null,
  remote: {
    current_station: null,
    playing: false,
    volume: 80,
    error: null,
  },
};

const elements = {
  currentStation: document.querySelector("#current-station"),
  message: document.querySelector("#message"),
  stationList: document.querySelector("#station-list"),
  statusPill: document.querySelector("#status-pill"),
  volume: document.querySelector("#volume"),
  playSelected: document.querySelector("#play-selected"),
  pause: document.querySelector("#pause"),
  resume: document.querySelector("#resume"),
  stop: document.querySelector("#stop"),
};

init().catch((error) => {
  console.error(error);
  setMessage("Could not initialize the remote control.");
  setStatus("Error");
});

async function init() {
  bindEvents();
  await loadStations();
  await refreshStatus();
  window.setInterval(async () => {
    try {
      await refreshStatus();
    } catch (error) {
      showError(error);
    }
  }, 5000);
}

function bindEvents() {
  elements.playSelected.addEventListener("click", async () => {
    try {
      await playSelectedStation();
    } catch (error) {
      showError(error);
    }
  });
  elements.pause.addEventListener("click", async () => {
    try {
      await postJson("/api/pause");
    } catch (error) {
      showError(error);
    }
  });
  elements.resume.addEventListener("click", async () => {
    try {
      await postJson("/api/resume");
    } catch (error) {
      showError(error);
    }
  });
  elements.stop.addEventListener("click", async () => {
    try {
      await postJson("/api/stop");
    } catch (error) {
      showError(error);
    }
  });
  elements.volume.addEventListener("change", async (event) => {
    try {
      await postJson("/api/volume", { volume: Number(event.target.value) });
    } catch (error) {
      showError(error);
    }
  });
}

async function loadStations() {
  const response = await fetch("/api/stations");
  const payload = await response.json();
  state.stations = payload.stations ?? [];
  state.selectedStation = state.stations[0] ?? null;
  renderStations();
  if (state.selectedStation) {
    setMessage("Select a station and send playback to the Raspberry.");
    setStatus("Ready");
  } else {
    setMessage("No stations configured.");
    setStatus("Empty");
  }
}

function renderStations() {
  elements.stationList.innerHTML = "";
  for (const station of state.stations) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "station-button";
    button.dataset.url = station.url;

    const name = document.createElement("span");
    name.className = "station-name";
    name.textContent = station.name;

    const url = document.createElement("span");
    url.className = "station-url";
    url.textContent = station.url;

    button.append(name, url);
    button.addEventListener("click", () => {
      state.selectedStation = station;
      syncStationButtons();
      setMessage(`${station.name} selected. Click Play Selected to start on the Raspberry.`);
      setStatus("Ready");
    });
    elements.stationList.appendChild(button);
  }
  syncStationButtons();
}

async function playSelectedStation() {
  if (!state.selectedStation) {
    return;
  }
  await postJson("/api/play", { url: state.selectedStation.url });
}

async function refreshStatus() {
  const response = await fetch("/api/status");
  const payload = await response.json();
  applyRemoteState(payload);
}

function applyRemoteState(payload) {
  state.remote = payload;
  elements.volume.value = String(payload.volume ?? 80);

  if (payload.current_station) {
    elements.currentStation.textContent = payload.current_station.name;
  } else {
    elements.currentStation.textContent = "No station selected";
  }

  if (payload.error) {
    setMessage(`Player error: ${payload.error}`);
    setStatus("Error");
    return;
  }

  if (payload.playing) {
    setMessage(`Playing ${payload.current_station?.name ?? "stream"} on the Raspberry output.`);
    setStatus("Playing");
  } else if (payload.current_station) {
    setMessage(`${payload.current_station.name} loaded on the Raspberry and currently paused.`);
    setStatus("Paused");
  } else {
    setMessage("No active playback on the Raspberry.");
    setStatus("Idle");
  }
}

async function postJson(url, body = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `Request failed with status ${response.status}`);
  }
  applyRemoteState(payload);
}

function syncStationButtons() {
  for (const button of elements.stationList.querySelectorAll(".station-button")) {
    button.classList.toggle("active", button.dataset.url === state.selectedStation?.url);
  }
}

function showError(error) {
  console.error(error);
  setMessage(error.message || "Command failed.");
  setStatus("Error");
}

function setMessage(message) {
  elements.message.textContent = message;
}

function setStatus(status) {
  elements.statusPill.textContent = status;
}
