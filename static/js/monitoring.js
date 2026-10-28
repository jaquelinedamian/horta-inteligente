(() => {
  const ns = 'http://www.w3.org/2000/svg';
  const draw = (root, sensor, type = 'line', events = []) => {
    const points = sensor?.points || [];
    root.replaceChildren();
    if (!points.length) {
      const empty = document.createElement('div'); empty.className = 'monitor-empty';
      empty.innerHTML = '<strong>Sem dados no período</strong><small>Altere o período ou aguarde novas leituras do sensor.</small>';
      root.append(empty); return;
    }
    const width = 900, height = 260, pad = 36;
    const values = points.map(item => Number(item.value));
    let min = Math.min(...values), max = Math.max(...values); if (min === max) { min -= 1; max += 1; }
    const x = index => pad + index * (width - pad * 2) / Math.max(1, points.length - 1);
    const y = value => height - pad - (value - min) * (height - pad * 2) / (max - min);
    const svg = document.createElementNS(ns, 'svg'); svg.setAttribute('viewBox', `0 0 ${width} ${height}`); svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', `Histórico de ${sensor.label}`);
    [0, .5, 1].forEach(step => { const line = document.createElementNS(ns, 'line'); const py = pad + step * (height - pad * 2); line.setAttribute('x1', pad); line.setAttribute('x2', width - pad); line.setAttribute('y1', py); line.setAttribute('y2', py); line.setAttribute('class', 'chart-grid'); svg.append(line); });
    if (type === 'bar') {
      const barWidth = Math.max(3, (width - pad * 2) / points.length * .65);
      points.forEach((point, index) => { const rect = document.createElementNS(ns, 'rect'); rect.setAttribute('x', x(index) - barWidth / 2); rect.setAttribute('y', y(point.value)); rect.setAttribute('width', barWidth); rect.setAttribute('height', height - pad - y(point.value)); rect.setAttribute('class', 'chart-bar'); svg.append(rect); });
    } else {
      const coords = points.map((point, index) => `${x(index)},${y(point.value)}`).join(' ');
      if (type === 'area') { const area = document.createElementNS(ns, 'polygon'); area.setAttribute('points', `${pad},${height-pad} ${coords} ${width-pad},${height-pad}`); area.setAttribute('class', 'chart-area'); svg.append(area); }
      const line = document.createElementNS(ns, 'polyline'); line.setAttribute('points', coords); line.setAttribute('class', 'chart-line'); svg.append(line);
    }
    const firstAt = new Date(points[0].at).getTime(), lastAt = new Date(points.at(-1).at).getTime();
    if (lastAt > firstAt) events.forEach(event => {
      const at = new Date(event.at).getTime(); if (at < firstAt || at > lastAt) return;
      const marker = document.createElementNS(ns, 'line'); const px = pad + (at - firstAt) * (width - pad * 2) / (lastAt - firstAt);
      marker.setAttribute('x1', px); marker.setAttribute('x2', px); marker.setAttribute('y1', pad); marker.setAttribute('y2', height-pad); marker.setAttribute('class', `chart-event chart-event-${event.metric}`);
      const title = document.createElementNS(ns, 'title'); title.textContent = `${event.metric === 'pump_state' ? 'Irrigação' : 'Iluminação'} ${event.on ? 'ligada' : 'desligada'} · ${new Date(event.at).toLocaleString('pt-BR')}`; marker.append(title); svg.append(marker);
    });
    const first = document.createElementNS(ns, 'text'); first.textContent = new Date(points[0].at).toLocaleString('pt-BR', {day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit'}); first.setAttribute('x', pad); first.setAttribute('y', height - 8); first.setAttribute('class', 'chart-label'); svg.append(first);
    const last = document.createElementNS(ns, 'text'); last.textContent = new Date(points.at(-1).at).toLocaleString('pt-BR', {day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit'}); last.setAttribute('x', width-pad); last.setAttribute('y', height - 8); last.setAttribute('text-anchor', 'end'); last.setAttribute('class', 'chart-label'); svg.append(last);
    root.append(svg);
  };
  document.querySelectorAll('[data-monitoring]').forEach(async panel => {
    const chart = panel.querySelector('[data-chart]'); const summary = panel.querySelector('[data-chart-summary]');
    try {
      const response = await fetch(panel.dataset.api, {headers:{Accept:'application/json'}}); if (!response.ok) throw new Error();
      const data = await response.json(); let selected = panel.querySelector('[data-sensor].active')?.dataset.sensor || 'air_temperature';
      const render = () => { const sensor = data.sensors[selected]; draw(chart, sensor, panel.querySelector('[data-chart-type].active')?.dataset.chartType || 'line', data.events); if (summary) summary.textContent = sensor.average == null ? 'Sem leituras no período' : `Mín. ${sensor.minimum.toFixed(1)} · Média ${sensor.average.toFixed(1)} · Máx. ${sensor.maximum.toFixed(1)} ${sensor.unit}`; };
      panel.querySelectorAll('[data-sensor]').forEach(button => button.addEventListener('click', () => { panel.querySelectorAll('[data-sensor]').forEach(item => item.classList.remove('active')); button.classList.add('active'); selected = button.dataset.sensor; render(); }));
      panel.querySelectorAll('[data-chart-type]').forEach(button => button.addEventListener('click', () => { panel.querySelectorAll('[data-chart-type]').forEach(item => item.classList.remove('active')); button.classList.add('active'); render(); }));
      render();
    } catch (error) { chart.innerHTML = '<div class="monitor-empty"><strong>Não foi possível carregar o histórico</strong><small>Tente novamente em alguns instantes.</small></div>'; if (summary) summary.textContent = 'Falha ao carregar'; }
  });
})();
