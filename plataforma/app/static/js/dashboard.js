/* ==========================================================================
   Dashboard de resultados.
   El navegador NO calcula nada: pide agregados ya decididos por el servidor
   (incluida la regla de confidencialidad) y los dibuja. Si la API responde
   `allowed: false`, se muestra el motivo y no hay dato que ocultar.
   ========================================================================== */
(function () {
  "use strict";

  // Paleta de datos independiente de la marca: el rojo corporativo no debe
  // leerse como "resultado malo".
  const C = {
    alto: "#1f5f8b", medio: "#4d97b8", neutro: "#b9c2cc",
    bajo: "#e0925f", critico: "#c25a3f",
    fav: "#1f5f8b", neu: "#b9c2cc", unf: "#c25a3f",
    grid: "#e4e6eb", ink: "#4a5160",
  };

  const base = document.body.dataset.base;          // /api/v1/o/<slug>
  const campaignId = document.body.dataset.campaign;
  const charts = [];

  function bandColor(score) {
    if (score === null || score === undefined) return C.neutro;
    if (score >= 75) return C.alto;
    if (score >= 60) return C.medio;
    if (score >= 45) return C.bajo;
    return C.critico;
  }

  function fmt(v, d) {
    if (v === null || v === undefined) return "—";
    return Number(v).toFixed(d === undefined ? 1 : d).replace(".", ",");
  }

  function mount(id) {
    const el = document.getElementById(id);
    if (!el) return null;
    const chart = echarts.init(el, null, { renderer: "svg" });
    charts.push(chart);
    return chart;
  }

  window.addEventListener("resize", () => charts.forEach((c) => c.resize()));

  function currentFilters() {
    const params = new URLSearchParams();
    document.querySelectorAll("[data-filter]").forEach((el) => {
      if (el.value) params.set(el.dataset.filter, el.value);
    });
    return params;
  }

  function blocked(message) {
    document.getElementById("resultados").innerHTML =
      '<div class="note warn"><strong>Segmento no disponible.</strong> ' + message + "</div>";
  }

  async function load() {
    const params = currentFilters();
    const url = `${base}/results/${campaignId}?${params.toString()}`;
    const res = await fetch(url, { headers: { Accept: "application/json" } });
    const data = await res.json();
    if (!data.allowed) {
      blocked(data.message || "No se puede mostrar este segmento.");
      return;
    }
    document.getElementById("resultados").style.display = "";
    render(data);
    const active = params.toString();
    document.getElementById("filtro-activo").textContent =
      active ? `Filtros aplicados: ${decodeURIComponent(active.replace(/&/g, " · "))}` :
               "Sin filtros: toda la organización.";
  }

  function render(data) {
    document.getElementById("kpi-participacion").textContent = fmt(data.participation.rate) + "%";
    document.getElementById("kpi-participacion-hint").textContent =
      `${data.participation.submitted} de ${data.participation.invited} invitaciones`;
    document.getElementById("kpi-general").textContent = fmt(data.general_score);
    document.getElementById("kpi-general").className = "value";
    document.getElementById("kpi-general").style.color = bandColor(data.general_score);
    document.getElementById("kpi-n").textContent = data.n_responses;
    document.getElementById("kpi-umbral").textContent = data.threshold;

    renderDimensions(data.dimensions);
    renderDistribution(data.dimensions);
    renderOutcomes(data.outcomes);
    renderIndices(data.indices);
    renderDrivers(data.drivers || []);
    renderMatrix(data.priority_matrix);
    renderTable(data.dimensions.concat(data.outcomes));
    renderBenchmark(data);
  }

  function renderDimensions(dims) {
    const chart = mount("chart-dimensiones");
    if (!chart) return;
    const sorted = dims.slice().filter((d) => d.score !== null).sort((a, b) => a.score - b.score);
    chart.setOption({
      grid: { left: 190, right: 40, top: 10, bottom: 28 },
      xAxis: { max: 100, splitLine: { lineStyle: { color: C.grid } }, axisLabel: { color: C.ink } },
      yAxis: {
        type: "category", data: sorted.map((d) => d.name),
        axisLabel: { color: C.ink, width: 175, overflow: "truncate" },
        axisLine: { show: false }, axisTick: { show: false },
      },
      tooltip: {
        trigger: "axis", axisPointer: { type: "shadow" },
        formatter: (p) => {
          const d = sorted[p[0].dataIndex];
          return `<strong>${d.name}</strong><br>Puntaje: ${fmt(d.score)}<br>` +
            `Favorable: ${fmt(d.favorable_pct)}%<br>n = ${d.n}` +
            (d.ci95 ? `<br>IC 95 %: ${fmt(d.ci95[0])} – ${fmt(d.ci95[1])}` : "");
        },
      },
      series: [{
        type: "bar", barMaxWidth: 18,
        data: sorted.map((d) => ({ value: d.score, itemStyle: { color: bandColor(d.score) } })),
        label: { show: true, position: "right", formatter: (p) => fmt(p.value), color: C.ink },
      }],
    });
  }

  function renderDistribution(dims) {
    const chart = mount("chart-distribucion");
    if (!chart) return;
    const d = dims.filter((x) => x.score !== null);
    chart.setOption({
      grid: { left: 190, right: 30, top: 30, bottom: 20 },
      legend: { data: ["Favorable", "Neutral", "Desfavorable"], top: 0, textStyle: { color: C.ink } },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: (v) => fmt(v) + "%" },
      xAxis: { max: 100, axisLabel: { formatter: "{value}%", color: C.ink }, splitLine: { lineStyle: { color: C.grid } } },
      yAxis: { type: "category", data: d.map((x) => x.name), axisLabel: { color: C.ink, width: 175, overflow: "truncate" } },
      series: [
        { name: "Favorable", type: "bar", stack: "t", itemStyle: { color: C.fav }, data: d.map((x) => x.favorable_pct) },
        { name: "Neutral", type: "bar", stack: "t", itemStyle: { color: C.neu }, data: d.map((x) => x.neutral_pct) },
        { name: "Desfavorable", type: "bar", stack: "t", itemStyle: { color: C.unf }, data: d.map((x) => x.unfavorable_pct) },
      ],
    });
  }

  function renderOutcomes(outcomes) {
    const box = document.getElementById("outcomes");
    if (!box) return;
    box.innerHTML = outcomes.map((o) => `
      <div class="kpi">
        <div class="label">${o.name}</div>
        <div class="value" style="color:${bandColor(o.score)}">${fmt(o.score)}</div>
        <div class="hint">${fmt(o.favorable_pct)}% favorable · n = ${o.n}</div>
      </div>`).join("");
  }

  function renderIndices(indices) {
    const box = document.getElementById("indices");
    if (!box) return;
    if (!indices.length) { box.innerHTML = '<p class="small muted">Sin índices calculables.</p>'; return; }
    box.innerHTML = indices.map((i) => `
      <div class="kpi">
        <div class="label">${i.name}</div>
        <div class="value" style="color:${bandColor(i.score)}">${fmt(i.score)}</div>
        <div class="hint">${i.n_dimensions} dimensiones · agrupación por validar</div>
      </div>`).join("");
  }

  function renderDrivers(drivers) {
    const box = document.getElementById("drivers-warnings");
    const chart = mount("chart-impulsores");
    if (!drivers.length) {
      if (box) box.innerHTML = '<p class="small muted">No hay variables de resultado suficientes para estimar impulsores.</p>';
      return;
    }
    const selector = document.getElementById("driver-outcome");
    if (selector && !selector.dataset.ready) {
      selector.innerHTML = drivers.map((d, i) => `<option value="${i}">${d.outcome_name}</option>`).join("");
      selector.dataset.ready = "1";
      selector.addEventListener("change", () => paint(drivers[selector.value]));
    }
    paint(drivers[selector ? selector.value : 0]);

    function paint(dr) {
      if (!dr || !chart) return;
      const items = dr.drivers.slice(0, 12).reverse();
      chart.setOption({
        grid: { left: 190, right: 50, top: 10, bottom: 28 },
        xAxis: { splitLine: { lineStyle: { color: C.grid } }, axisLabel: { color: C.ink } },
        yAxis: { type: "category", data: items.map((d) => d.name), axisLabel: { color: C.ink, width: 175, overflow: "truncate" } },
        tooltip: {
          trigger: "axis", axisPointer: { type: "shadow" },
          formatter: (p) => {
            const d = items[p[0].dataIndex];
            return `<strong>${d.name}</strong><br>Coeficiente estandarizado: ${fmt(d.beta, 3)}` +
              `<br>Correlación: ${fmt(d.r, 3)}<br>VIF: ${fmt(d.vif, 2)}<br><em>${d.strength}</em>`;
          },
        },
        series: [{
          type: "bar", barMaxWidth: 16,
          data: items.map((d) => ({
            value: d.beta !== null ? d.beta : d.r,
            itemStyle: { color: (d.beta || d.r || 0) >= 0 ? C.medio : C.bajo },
          })),
          label: { show: true, position: "right", formatter: (p) => fmt(p.value, 2), color: C.ink },
        }],
      });
      if (box) {
        const w = (dr.warnings || []).map((x) => `<div class="note warn small">${x}</div>`).join("");
        box.innerHTML = `<p class="small">Modelo sobre ${dr.n} casos completos · R² = ${fmt(dr.r2, 3)}
          (ajustado ${fmt(dr.adj_r2, 3)})</p>${w}
          <div class="note small">${dr.disclaimer}</div>`;
      }
    }
  }

  function renderMatrix(matrix) {
    const chart = mount("chart-matriz");
    if (!chart || !matrix) return;
    const pts = matrix.points.filter((p) => p.association !== null);
    chart.setOption({
      grid: { left: 60, right: 30, top: 20, bottom: 50 },
      xAxis: { name: "Nivel actual (0-100)", nameLocation: "middle", nameGap: 30, min: 0, max: 100,
               splitLine: { lineStyle: { color: C.grid } } },
      yAxis: { name: "Asociación con el resultado", nameLocation: "middle", nameGap: 40,
               splitLine: { lineStyle: { color: C.grid } } },
      tooltip: {
        formatter: (p) => `<strong>${p.data.name}</strong><br>Puntaje: ${fmt(p.data.value[0])}` +
          `<br>Asociación: ${fmt(p.data.value[1], 3)}<br>${p.data.quadrant.replace(/_/g, " ")}`,
      },
      series: [{
        type: "scatter", symbolSize: 16,
        data: pts.map((p) => ({
          name: p.name, quadrant: p.quadrant, value: [p.score, p.association],
          itemStyle: { color: p.quadrant === "prioridad_critica" ? C.critico :
                              p.quadrant === "fortaleza_estrategica" ? C.alto : C.neutro },
        })),
        label: { show: true, position: "top", formatter: (p) => p.data.name, fontSize: 10, color: C.ink },
        markLine: {
          silent: true, symbol: "none", lineStyle: { color: C.grid, type: "dashed" },
          data: [{ xAxis: matrix.pivot_x }, { yAxis: matrix.pivot_y }],
        },
      }],
    });
    const note = document.getElementById("matriz-nota");
    if (note) note.textContent = matrix.note;
  }

  function renderTable(rows) {
    const body = document.getElementById("tabla-dimensiones");
    if (!body) return;
    body.innerHTML = rows.map((d) => `
      <tr>
        <td>${d.name}${d.is_outcome ? ' <span class="badge info">resultado</span>' : ""}</td>
        <td class="num" style="color:${bandColor(d.score)};font-weight:700">${fmt(d.score)}</td>
        <td class="num">${fmt(d.favorable_pct)}%</td>
        <td class="num">${fmt(d.neutral_pct)}%</td>
        <td class="num">${fmt(d.unfavorable_pct)}%</td>
        <td class="num">${d.n}</td>
        <td class="num">${d.ci95 ? fmt(d.ci95[0]) + " – " + fmt(d.ci95[1]) : "—"}</td>
        <td class="num">${fmt(d.sd)}</td>
        <td class="num">${d.polarization !== null && d.polarization !== undefined ? fmt(d.polarization, 2) : "—"}</td>
        <td class="num">${d.delta !== undefined && d.delta !== null ? (d.delta > 0 ? "+" : "") + fmt(d.delta) : "—"}</td>
        <td class="num">${d.benchmark !== undefined && d.benchmark !== null ? fmt(d.benchmark) : "—"}</td>
      </tr>`).join("");
  }

  function renderBenchmark(data) {
    const box = document.getElementById("benchmark-fuente");
    if (!box) return;
    const b = data.benchmark_source;
    box.innerHTML = b
      ? `<p class="small"><strong>${b.name}</strong> · ${b.n_organizations} organizaciones ·
         ${b.n_responses} respuestas.<br><span class="muted">${b.limitations || ""}</span></p>`
      : '<p class="small muted">No hay benchmark comparable para esta versión del instrumento.</p>';
  }

  document.querySelectorAll("[data-filter]").forEach((el) => el.addEventListener("change", load));
  const reset = document.getElementById("limpiar-filtros");
  if (reset) reset.addEventListener("click", () => {
    document.querySelectorAll("[data-filter]").forEach((el) => { el.value = ""; });
    load();
  });

  if (campaignId) load();
})();
