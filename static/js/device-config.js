// Enderecos dos dispositivos acessiveis pela rede local do navegador.
// Ajuste somente este arquivo quando o roteador atribuir novos IPs.
window.HORTA_DEVICE_CONFIG = Object.freeze({
  ESP8266_BASE_URL: "",
  ESP32_CAM_BASE_URL: "",

  // Zero desativa a atualizacao automatica da camera. Use um intervalo
  // moderado (por exemplo, 30000) se quiser habilita-la no futuro.
  CAMERA_AUTO_REFRESH_MS: 0,
});
