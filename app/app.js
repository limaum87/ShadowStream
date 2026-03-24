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
  newName: document.querySelector("#new-station-name"),
  newUrl: document.querySelector("#new-station-url"),
  addStation: document.querySelector("#add-station"),
};

init().catch((error) => {
  console.error(error);
  setMessage("Nao foi possivel inicializar o controle remoto.");
  setStatus("Erro");
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
  elements.addStation.addEventListener("click", async () => {
    const name = elements.newName.value.trim();
    const url = elements.newUrl.value.trim();
    if (!name || !url) {
      setMessage("Preencha o nome e a URL da estacao.");
      return;
    }
    try {
      await postJson("/api/stations", { name, url });
      elements.newName.value = "";
      elements.newUrl.value = "";
      await loadStations();
      setMessage(`Estacao "${name}" adicionada.`);
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
    setMessage("Selecione uma estacao e envie para o Raspberry.");
    setStatus("Pronto");
  } else {
    setMessage("Nenhuma estacao configurada.");
    setStatus("Vazio");
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

    const removeBtn = document.createElement("span");
    removeBtn.className = "station-remove";
    removeBtn.textContent = "X";
    removeBtn.title = "Remover estacao";
    removeBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      try {
        await postJson("/api/stations/delete", { url: station.url });
        await loadStations();
        setMessage(`Estacao "${station.name}" removida.`);
      } catch (error) {
        showError(error);
      }
    });

    button.append(name, url, removeBtn);
    button.addEventListener("click", () => {
      state.selectedStation = station;
      syncStationButtons();
      setMessage(`${station.name} selecionada. Clique em Tocar para iniciar no Raspberry.`);
      setStatus("Pronto");
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
    elements.currentStation.textContent = "Nenhuma estacao selecionada";
  }

  if (payload.error) {
    setMessage(`Erro no player: ${payload.error}`);
    setStatus("Erro");
    return;
  }

  if (payload.playing) {
    setMessage(`Tocando ${payload.current_station?.name ?? "stream"} na saida do Raspberry.`);
    setStatus("Tocando");
  } else if (payload.current_station) {
    setMessage(`${payload.current_station.name} carregada no Raspberry, pausada.`);
    setStatus("Pausado");
  } else {
    setMessage("Nenhuma reproducao ativa no Raspberry.");
    setStatus("Parado");
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
    throw new Error(payload.error || `Requisicao falhou com status ${response.status}`);
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
  setMessage(error.message || "Comando falhou.");
  setStatus("Erro");
}

function setMessage(message) {
  elements.message.textContent = message;
}

function setStatus(status) {
  elements.statusPill.textContent = status;
}
