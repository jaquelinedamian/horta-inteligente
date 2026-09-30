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
