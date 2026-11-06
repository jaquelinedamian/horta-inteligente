document.addEventListener("DOMContentLoaded", () => {
  const input = document.querySelector("input[type=file][name=image]");
  const preview = document.getElementById("plan-image-preview");
  input?.addEventListener("change", () => {
    const file = input.files?.[0];
    if (!file) return;
    preview.src = URL.createObjectURL(file);
    preview.classList.remove("d-none");
    document.getElementById("plan-image-placeholder")?.classList.add("d-none");
  });
  document.getElementById("add-benefit")?.addEventListener("click", () => {
    const total = document.getElementById("id_benefits-TOTAL_FORMS");
    const template = document.getElementById("empty-benefit");
    const html = template.innerHTML.replaceAll("__prefix__", total.value);
    document.getElementById("benefit-list").insertAdjacentHTML("beforeend", html);
    total.value = Number(total.value) + 1;
  });
  const mirror = (source, target, fallback) => {
    const input = document.getElementById(source);
    const output = document.getElementById(target);
    const update = () => { if (output) output.textContent = input?.value || fallback; };
    input?.addEventListener("input", update); update();
  };
  mirror("id_name", "preview-name", "Nome do plano");
  mirror("id_commercial_title", "preview-title", "Título comercial");
  mirror("id_short_copy", "preview-copy", "A descrição curta aparecerá aqui.");
  const price = document.getElementById("id_monthly_price");
  const pricePreview = document.getElementById("preview-price");
  const updatePrice = () => {
    const value = Number(String(price?.value || "0").replace(",", "."));
    if (pricePreview) pricePreview.innerHTML = `${value.toLocaleString("pt-BR", {style: "currency", currency: "BRL"})}<small>/mês</small>`;
  };
  price?.addEventListener("input", updatePrice); updatePrice();
  const modelSelect = document.getElementById("id_garden_model");
  const modelSection = document.getElementById("model-technical-section");
  const modelGrid = document.getElementById("model-feature-grid");
  const modelEmpty = document.getElementById("model-empty");
  const modelLoading = document.getElementById("model-loading");
  const modelIncomplete = document.getElementById("model-incomplete");
  const modelEdit = document.getElementById("edit-garden-model");
  let modelRequest = 0;
  const updateModelPreview = async () => {
    const modelId = modelSelect?.value;
    const requestId = ++modelRequest;
    modelGrid.replaceChildren();
    modelIncomplete.classList.add("d-none");
    modelEdit.classList.add("d-none");
    if (!modelId) {
      modelEmpty.classList.remove("d-none");
      modelLoading.classList.add("d-none");
      return;
    }
    modelEmpty.classList.add("d-none");
    modelLoading.classList.remove("d-none");
    try {
      const url = modelSection.dataset.modelUrlBase.replace("00000000-0000-0000-0000-000000000000", modelId);
      const response = await fetch(url, {headers: {"Accept": "application/json"}});
      if (!response.ok) throw new Error("Características físicas não cadastradas. Você pode continuar editando e publicar este plano.");
      const model = await response.json();
      if (requestId !== modelRequest) return;
      model.features.forEach((feature) => {
        const item = document.createElement("div");
        item.className = "garden-feature-preview-item";
        const icon = document.createElement("i"); icon.className = `bi ${feature.icon || "bi-info-circle"}`;
        const value = document.createElement("strong"); value.textContent = `${feature.value}${feature.unit ? ` ${feature.unit}` : ""}`;
        const name = document.createElement("small"); name.textContent = feature.name;
        item.append(icon, value, name); modelGrid.append(item);
      });
      modelEdit.href = model.edit_url;
      modelEdit.textContent = "Editar modelo físico";
      modelEdit.classList.remove("d-none");
      if (!model.is_complete) {
        modelIncomplete.textContent = `Características opcionais não cadastradas: ${model.missing.join(", ")}. Você pode continuar editando e publicar este plano.`;
        modelIncomplete.classList.remove("d-none");
      }
      if (!model.features.length) {
        modelEmpty.textContent = "Nenhuma característica técnica foi cadastrada neste modelo.";
        modelEmpty.classList.remove("d-none");
      }
    } catch (error) {
      if (requestId === modelRequest) {
        modelEmpty.textContent = error.message;
        modelEmpty.classList.remove("d-none");
      }
    } finally {
      if (requestId === modelRequest) modelLoading.classList.add("d-none");
    }
  };
  modelSelect?.addEventListener("change", updateModelPreview);
  updateModelPreview();
});
