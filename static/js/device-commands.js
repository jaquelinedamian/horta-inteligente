(() => {
  const POLL_INTERVAL_MS = 500;
  const POLL_DEADLINE_MS = 30000;
  const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

  async function pollCommand(statusUrl, startedAt, message) {
    while (Date.now() - startedAt < POLL_DEADLINE_MS) {
      const response = await fetch(statusUrl, {
        headers: { Accept: 'application/json' }, credentials: 'same-origin', cache: 'no-store',
      });
      if (!response.ok) throw new Error('Não foi possível consultar a confirmação do controlador.');
      const command = await response.json();
      if (command.status === 'succeeded') {
        message.textContent = 'Comando confirmado. Atualizando estado…';
        window.location.reload();
        return;
      }
      if (['failed', 'expired', 'canceled'].includes(command.status)) {
        throw new Error('O controlador não conseguiu executar o comando.');
      }
      await wait(POLL_INTERVAL_MS);
    }
    throw new Error('O comando continua pendente. Verifique a conexão do controlador.');
  }

  [...document.querySelectorAll('form[method="post"]')].filter((form) => {
    try { return new URL(form.action, window.location.href).pathname.endsWith('/app/dispositivo/acao/'); }
    catch (_) { return false; }
  }).forEach((form) => form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (form.dataset.commandPending === 'true') return;
    form.dataset.commandPending = 'true';
    const data = new FormData(form);
    data.set('client_clicked_at', new Date().toISOString());
    if (event.submitter?.name) data.set(event.submitter.name, event.submitter.value);
    const buttons = [...form.querySelectorAll('button, input[type="submit"]')];
    buttons.forEach((button) => { button.disabled = true; });
    let message = form.querySelector('[data-command-status]');
    if (!message) {
      message = document.createElement('small');
      message.dataset.commandStatus = 'true';
      message.className = 'd-block text-muted mt-2';
      message.setAttribute('role', 'status');
      message.setAttribute('aria-live', 'polite');
      form.appendChild(message);
    }
    message.textContent = 'Enviando comando… Aguardando confirmação do controlador.';
    try {
      const response = await fetch(form.action, {
        method: 'POST', body: data, credentials: 'same-origin',
        headers: { Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'Não foi possível enviar o comando.');
      await pollCommand(payload.status_url, Date.now(), message);
    } catch (error) {
      message.textContent = error.message;
      message.classList.remove('text-muted');
      message.classList.add('text-danger');
      buttons.forEach((button) => { button.disabled = false; });
      form.dataset.commandPending = 'false';
    }
  }));
})();
