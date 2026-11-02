(() => {
  const intervalMs = 5000;
  document.querySelectorAll('[data-wifi-setup]').forEach((panel) => {
    let polling = null;
    const wizard = panel.querySelector('[data-wifi-wizard]');
    const poll = async () => {
      try {
        const response = await fetch(panel.dataset.statusUrl, {headers: {Accept: 'application/json'}, cache: 'no-store'});
        if (!response.ok) return;
        const status = await response.json();
        ['controller', 'camera'].forEach((kind) => {
          const item = status[kind];
          if (!item) return;
          const card = panel.querySelector(`[data-device-id="${item.id}"]`);
          if (!card) return;
          card.querySelector('[data-wifi-online]').textContent = item.online ? 'Online' : 'Aguardando conexão…';
          card.querySelector('[data-wifi-ssid]').textContent = item.ssid || 'Não informado';
          card.querySelector('[data-wifi-ip]').textContent = item.local_ip || 'Não informado';
        });
        if ([status.controller, status.camera].filter(Boolean).every((item) => item.online)) {
          wizard.querySelector('[data-wizard-status]').textContent = 'Controlador e câmera conectados.';
          clearInterval(polling);
        }
      } catch (_) { /* O navegador pode estar temporariamente no AP local e sem internet. */ }
    };
    panel.querySelectorAll('[data-wifi-configure]').forEach((form) => form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const feedback = form.querySelector('[data-wifi-feedback]');
      feedback.textContent = `Preparando ${form.dataset.deviceLabel}…`;
      wizard.hidden = false;
      wizard.querySelector('[data-setup-ap-name]').textContent = form.dataset.setupAp;
      try {
        const response = await fetch(form.action, {method: 'POST', body: new FormData(form), headers: {Accept: 'application/json'}});
        if (!response.ok) throw new Error('Não foi possível iniciar a configuração.');
        feedback.textContent = `Conecte-se a ${form.dataset.setupAp} e escolha a nova rede 2,4 GHz.`;
        if (!polling) polling = setInterval(poll, intervalMs);
      } catch (error) { feedback.textContent = error.message; }
    }));
  });
})();
