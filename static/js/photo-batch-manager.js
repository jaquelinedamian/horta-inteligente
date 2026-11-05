(() => {
  const form = document.querySelector('[data-photo-batch-form]');
  if (!form) return;
  const checkboxes = [...form.querySelectorAll('[data-photo-checkbox]')];
  const count = form.querySelector('[data-selected-count]');
  const confirmCount = form.querySelector('[data-confirm-count]');
  const deleteButton = form.querySelector('[data-open-delete]');
  const scope = form.querySelector('[data-selection-scope]');
  const inputContainer = form.querySelector('[data-selected-inputs]');
  const storageKey = form.dataset.selectionKey;
  let stored = [];
  try { stored = JSON.parse(sessionStorage.getItem(storageKey) || '[]'); } catch (_) { sessionStorage.removeItem(storageKey); }
  let selected = new Set(Array.isArray(stored) ? stored : []);
  let allFiltered = false;

  const render = () => {
    checkboxes.forEach((checkbox) => { checkbox.checked = selected.has(checkbox.value); });
    inputContainer.replaceChildren(...[...selected].map((id) => {
      const input = document.createElement('input'); input.type = 'hidden'; input.name = 'photo_ids'; input.value = id; return input;
    }));
    const selectedCount = allFiltered ? Number(form.dataset.filteredCount) : selected.size;
    count.textContent = selectedCount; confirmCount.textContent = selectedCount;
    deleteButton.disabled = selectedCount === 0;
    scope.value = allFiltered ? 'filtered' : 'selected';
    sessionStorage.setItem(storageKey, JSON.stringify([...selected]));
  };

  checkboxes.forEach((checkbox) => checkbox.addEventListener('change', () => {
    allFiltered = false;
    if (checkbox.checked) selected.add(checkbox.value); else selected.delete(checkbox.value);
    render();
  }));
  form.querySelector('[data-select-page]').addEventListener('click', () => { allFiltered = false; checkboxes.forEach((item) => selected.add(item.value)); render(); });
  form.querySelector('[data-select-filtered]').addEventListener('click', () => { allFiltered = true; render(); });
  form.querySelector('[data-clear-selection]').addEventListener('click', () => { allFiltered = false; selected.clear(); sessionStorage.removeItem(storageKey); render(); });
  deleteButton.addEventListener('click', () => bootstrap.Modal.getOrCreateInstance(document.getElementById('photoBatchDeleteModal')).show());
  form.addEventListener('submit', () => sessionStorage.removeItem(storageKey));
  render();
})();
