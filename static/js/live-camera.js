document.querySelectorAll("[data-live-camera-modal]").forEach((modal) => {
  const image = modal.querySelector("[data-live-camera-image]");
  const loading = modal.querySelector("[data-live-camera-loading]");
  const error = modal.querySelector("[data-live-camera-error]");
  const retry = modal.querySelector("[data-live-camera-retry]");
  const status = modal.querySelector("[data-live-camera-status]");
  const streamUrl = modal.dataset.streamUrl;

  function disconnect() {
    image.removeAttribute("src");
    image.classList.add("d-none");
  }

  function showError() {
    disconnect();
    loading.classList.add("d-none");
    error.classList.remove("d-none");
    status.innerHTML = '<i class="bi bi-wifi-off"></i> Offline';
    status.classList.remove("is-online");
    status.classList.add("is-offline");
  }

  function connect() {
    disconnect();
    error.classList.add("d-none");
    loading.classList.remove("d-none");
    status.innerHTML = '<i class="bi bi-broadcast"></i> Conectando';
    status.classList.remove("is-offline");
    status.classList.add("is-online");
    if (!streamUrl) {
      showError();
      return;
    }
    image.src = streamUrl;
  }

  image.addEventListener("load", () => {
    loading.classList.add("d-none");
    error.classList.add("d-none");
    image.classList.remove("d-none");
    status.innerHTML = '<i class="bi bi-broadcast"></i> Ao vivo';
  });
  image.addEventListener("error", showError);
  retry.addEventListener("click", connect);
  modal.addEventListener("show.bs.modal", connect);
  modal.addEventListener("hidden.bs.modal", () => {
    disconnect();
    loading.classList.remove("d-none");
    error.classList.add("d-none");
  });
});
