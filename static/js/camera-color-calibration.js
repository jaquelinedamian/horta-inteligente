(() => {
  const form = document.querySelector('[data-camera-calibration]');
  if (!form) return;

  const automatic = {
    temperature: -10, hue: -6, saturation: 92, contrast: 102,
    brightness: 100, green_intensity: 100, magenta_compensation: 28,
    white_balance: true,
  };
  const neutral = {
    temperature: 0, hue: 0, saturation: 100, contrast: 100,
    brightness: 100, green_intensity: 100, magenta_compensation: 0,
    white_balance: false,
  };

  const numberValue = (name) => Number(form.elements[name]?.value || 0);
  const manualValues = () => ({
    temperature: numberValue('temperature'), hue: numberValue('hue'),
    saturation: numberValue('saturation'), contrast: numberValue('contrast'),
    brightness: numberValue('brightness'), green_intensity: numberValue('green_intensity'),
    magenta_compensation: numberValue('magenta_compensation'),
    white_balance: Boolean(form.elements.white_balance?.checked),
  });

  const updatePreview = () => {
    const mode = form.elements.mode.value;
    const values = mode === 'original' ? neutral : (mode === 'automatic' ? automatic : manualValues());
    const temperature = values.temperature / 100 * 0.12;
    const magenta = values.magenta_compensation / 100 * 0.18;
    let red = 1 + temperature - magenta;
    let green = values.green_intensity / 100 + magenta;
    let blue = 1 - temperature - magenta;
    if (values.white_balance) {
      const average = (red + green + blue) / 3;
      red /= average; green /= average; blue /= average;
    }
    const matrix = document.querySelector('[data-calibration-matrix]');
    matrix?.setAttribute('values', `${red} 0 0 0 0  0 ${green} 0 0 0  0 0 ${blue} 0 0  0 0 0 1 0`);
    const filter = `url(#cameraColorMatrix) hue-rotate(${values.hue}deg) saturate(${values.saturation}%) contrast(${values.contrast}%) brightness(${values.brightness}%)`;
    document.querySelectorAll('[data-calibration-image]').forEach((image) => { image.style.filter = filter; });
    form.dataset.activeMode = mode;
  };

  form.querySelectorAll('[data-calibration-control]').forEach((control) => {
    const range = control.querySelector('[data-calibration-range]');
    const number = control.querySelector('[data-calibration-number]');
    const sync = (source, target) => {
      const minimum = Number(target.min); const maximum = Number(target.max);
      const value = Math.min(maximum, Math.max(minimum, Number(source.value)));
      source.value = value; target.value = value; updatePreview();
    };
    range.addEventListener('input', () => sync(range, number));
    number.addEventListener('input', () => sync(number, range));
  });
  form.querySelectorAll('input[name="mode"], #id_white_balance').forEach((input) => input.addEventListener('change', updatePreview));

  const comparison = document.querySelector('[data-comparison-position]');
  const corrected = document.querySelector('[data-calibration-corrected]');
  const divider = document.querySelector('[data-calibration-divider]');
  comparison?.addEventListener('input', () => {
    corrected.style.clipPath = `inset(0 ${100 - comparison.value}% 0 0)`;
    divider.style.left = `${comparison.value}%`;
  });

  const referenceInput = form.querySelector('[data-neutral-reference]');
  const referenceStatus = form.querySelector('[data-neutral-reference-status]');
  referenceInput?.addEventListener('change', () => {
    const file = referenceInput.files?.[0];
    if (!file) return;
    const image = new Image();
    const objectUrl = URL.createObjectURL(file);
    image.onload = () => {
      const canvas = document.createElement('canvas');
      const size = 80; canvas.width = size; canvas.height = size;
      const context = canvas.getContext('2d', { willReadFrequently: true });
      context.drawImage(image, image.width * .35, image.height * .35, image.width * .3, image.height * .3, 0, 0, size, size);
      const pixels = context.getImageData(0, 0, size, size).data;
      let red = 0, green = 0, blue = 0;
      for (let index = 0; index < pixels.length; index += 4) { red += pixels[index]; green += pixels[index + 1]; blue += pixels[index + 2]; }
      const count = pixels.length / 4; red /= count; green /= count; blue /= count;
      const average = Math.max(1, (red + green + blue) / 3);
      const setValue = (name, value) => {
        const range = form.elements[name]; const number = range.closest('[data-calibration-control]').querySelector('[data-calibration-number]');
        const safe = Math.round(Math.min(Number(range.max), Math.max(Number(range.min), value)));
        range.value = safe; number.value = safe;
      };
      setValue('temperature', (blue - red) / average * 100);
      setValue('magenta_compensation', (((red + blue) / 2) - green) / average * 160);
      setValue('green_intensity', average / Math.max(1, green) * 100);
      form.querySelector('input[name="mode"][value="manual"]').checked = true;
      form.elements.white_balance.checked = true;
      referenceStatus.textContent = 'Referência analisada. Revise a prévia e salve para aplicar este perfil.';
      URL.revokeObjectURL(objectUrl); updatePreview();
    };
    image.onerror = () => { referenceStatus.textContent = 'Não foi possível analisar esta imagem.'; URL.revokeObjectURL(objectUrl); };
    image.src = objectUrl;
  });
  updatePreview();
})();
