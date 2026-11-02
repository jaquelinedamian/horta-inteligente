const ESP32_CAM_BASE_URL = window.HORTA_DEVICE_CONFIG?.ESP32_CAM_BASE_URL;
const CAMERA_AUTO_REFRESH_MS =
  Number(window.HORTA_DEVICE_CONFIG?.CAMERA_AUTO_REFRESH_MS) || 0;

const painelCamera = document.querySelector("[data-horta-camera-painel]");

if (painelCamera) {
  const imagem = painelCamera.querySelector("[data-horta-camera-imagem]");
  const estado = painelCamera.querySelector("[data-horta-camera-status]");
  const ultimaCaptura = painelCamera.querySelector("[data-horta-camera-horario]");
  const aviso = painelCamera.querySelector("[data-horta-camera-aviso]");
  const botao = painelCamera.querySelector("[data-horta-camera-atualizar]");

  function definirEstado(texto, classe) {
    estado.textContent = texto;
    estado.classList.remove("text-success", "text-danger", "text-warning");
    estado.classList.add(classe);
  }

  function atualizarImagem() {
    if (!ESP32_CAM_BASE_URL) {
      definirEstado("Offline", "text-danger");
      aviso.textContent = "ESP32_CAM_BASE_URL nao foi configurada.";
      aviso.classList.remove("d-none");
      return;
    }

    definirEstado("Conectando", "text-warning");
    botao.disabled = true;
    imagem.src = `${ESP32_CAM_BASE_URL}/capture?t=${Date.now()}`;
  }

  imagem.addEventListener("load", () => {
    definirEstado("Online", "text-success");
    ultimaCaptura.textContent = new Date().toLocaleTimeString("pt-BR");
    aviso.classList.add("d-none");
    botao.disabled = false;
  });

  imagem.addEventListener("error", () => {
    definirEstado("Offline", "text-danger");
    aviso.textContent = "Camera offline. Verifique a alimentacao, o IP e a rede local.";
    aviso.classList.remove("d-none");
    botao.disabled = false;
  });

  botao.addEventListener("click", atualizarImagem);
  window.atualizarCameraHorta = atualizarImagem;
  atualizarImagem();

  if (CAMERA_AUTO_REFRESH_MS >= 10000) {
    setInterval(atualizarImagem, CAMERA_AUTO_REFRESH_MS);
  }
}

(() => {
  const modalElement = document.getElementById("liveCameraModal");
  if (!modalElement) return;

  const stream = modalElement.querySelector("[data-live-camera-stream]");
  const loading = modalElement.querySelector("[data-live-camera-loading]");
  const error = modalElement.querySelector("[data-live-camera-error]");
  const errorMessage = modalElement.querySelector("[data-live-camera-error-message]");
  const cameraName = modalElement.querySelector("[data-live-camera-name]");
  const retry = modalElement.querySelector("[data-live-camera-retry]");
  const networkMessage = modalElement.dataset.cameraNetworkMessage;
  let infoUrl = "";
  let timeoutId = null;
  let requestController = null;
  let connectionId = 0;

  function stopStream() {
    connectionId += 1;
    clearTimeout(timeoutId);
    timeoutId = null;
    requestController?.abort();
    requestController = null;
    stream.onload = null;
    stream.onerror = null;
    stream.removeAttribute("src");
    stream.classList.add("d-none");
  }

  function showLoading() {
    loading.classList.remove("d-none");
    error.classList.add("d-none");
    stream.classList.add("d-none");
  }

  function showError(message = networkMessage) {
    clearTimeout(timeoutId);
    loading.classList.add("d-none");
    stream.classList.add("d-none");
    errorMessage.textContent = message;
    error.classList.remove("d-none");
  }

  async function startStream() {
    stopStream();
    showLoading();
    const currentConnection = connectionId;
    requestController = new AbortController();

    try {
      const response = await fetch(infoUrl, {
        headers: { Accept: "application/json" },
        cache: "no-store",
        signal: requestController.signal,
      });
      const data = await response.json();
      if (currentConnection !== connectionId) return;
      if (!response.ok || !data.available || !data.stream_url) {
        showError(data.message || networkMessage);
        return;
      }

      cameraName.textContent = data.garden_name;
      stream.onload = () => {
        if (currentConnection !== connectionId) return;
        clearTimeout(timeoutId);
        loading.classList.add("d-none");
        stream.classList.remove("d-none");
      };
      stream.onerror = () => {
        if (currentConnection === connectionId) showError();
      };
      timeoutId = window.setTimeout(() => {
        if (currentConnection === connectionId) {
          stream.removeAttribute("src");
          showError();
        }
      }, 12000);
      stream.src = data.stream_url;
    } catch (fetchError) {
      if (fetchError.name !== "AbortError" && currentConnection === connectionId) {
        showError();
      }
    }
  }

  modalElement.addEventListener("show.bs.modal", (event) => {
    infoUrl = event.relatedTarget?.dataset.cameraInfoUrl || infoUrl;
    if (infoUrl) startStream();
  });
  modalElement.addEventListener("hidden.bs.modal", stopStream);
  retry.addEventListener("click", startStream);
})();
