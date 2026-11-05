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
  const modelDataNode = document.getElementById("garden-model-data");
  const models = modelDataNode ? JSON.parse(modelDataNode.textContent) : [];
  const setText = (selector, value) => { const node = document.querySelector(selector); if (node) node.textContent = value; };
  const updateModelPreview = () => {
    const model = models.find((item) => String(item.id) === modelSelect?.value);
    setText("[data-model-capacity]", `${model?.capacity ?? "—"} mudas`);
    setText("[data-model-reservoir]", `${model?.reservoir_liters ?? "—"} L`);
    setText("[data-model-height]", `${model?.height_cm ?? "—"} cm`);
    setText("[data-model-modules]", `${model?.module_count ?? "—"} módulos`);
  };
  modelSelect?.addEventListener("change", updateModelPreview);
  updateModelPreview();
});
