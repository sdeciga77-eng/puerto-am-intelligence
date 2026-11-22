/* Puerto A&M — panel privado: autenticación, dashboard y agente financiero. */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const PALETTE = ["#c6a66a", "#2c7da0", "#0f9d76", "#6c7fd8", "#c9744f", "#3f9c8f", "#b08bc4", "#d4a373"];
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const moneyFmt = new Intl.NumberFormat("es-MX", { style: "currency", currency: "MXN", minimumFractionDigits: 0, maximumFractionDigits: 0 });
  const moneyFullFmt = new Intl.NumberFormat("es-MX", { style: "currency", currency: "MXN", minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const intFmt = new Intl.NumberFormat("es-MX", { maximumFractionDigits: 0 });

  const money = (v) => moneyFmt.format(Number(v || 0));
  const moneyFull = (v) => moneyFullFmt.format(Number(v || 0));
  const num = (v) => intFmt.format(Number(v || 0));
  const pct = (v) => `${Number(v || 0).toLocaleString("es-MX", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;

  let csrfToken = "";
  let username = "";
  let toastTimer = null;
  const state = { data: null, rows: [], page: 1, pageSize: 15, sort: { key: "fecha", dir: -1 }, search: "", charts: {}, initialized: false };

  function escapeHtml(value) {
    return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
  }
  function toast(message, isError) {
    const el = $("adminToast");
    if (!el) return;
    el.textContent = message;
    el.className = "toast show" + (isError ? " error" : "");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (el.className = "toast"), 3800);
  }
  async function getJson(path) {
    const response = await fetch(path, { cache: "no-store" });
    if (response.status === 401) { location.href = "/admin/login"; throw new Error("Sesión expirada"); }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `Error ${response.status}`);
    return data;
  }
  async function postJson(path, body) {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
      body: JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));
    if (response.status === 401) { location.href = "/admin/login"; throw new Error("Sesión expirada"); }
    if (!response.ok) throw new Error(data.detail || `Error ${response.status}`);
    return data;
  }

  /* ================= LOGIN ================= */
  function setupLogin() {
    $("loginYear").textContent = new Date().getFullYear();
    $("loginForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      const error = $("loginError");
      error.textContent = "";
      const button = $("loginSubmit");
      button.disabled = true;
      button.textContent = "Verificando…";
      try {
        const response = await fetch("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username: $("loginUser").value.trim(), password: $("loginPass").value }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || "No se pudo iniciar sesión");
        location.href = "/admin/dashboard";
      } catch (err) {
        error.textContent = err.message || "Credenciales inválidas";
      } finally {
        button.disabled = false;
        button.innerHTML = 'Entrar al panel <span class="arrow">→</span>';
      }
    });
  }

  /* ================= DASHBOARD ================= */
  function queryString(extra) {
    const params = new URLSearchParams();
    const desde = $("fechaDesde").value, hasta = $("fechaHasta").value;
    const producto = $("productoFilter").value, categoria = $("categoriaFilter").value;
    if (desde) params.set("fecha_desde", desde);
    if (hasta) params.set("fecha_hasta", hasta);
    if (producto) params.set("producto", producto);
    if (categoria) params.set("categoria", categoria);
    Object.entries(extra || {}).forEach(([key, value]) => params.set(key, value));
    params.set("_", Date.now().toString());
    return params.toString();
  }
  function animateValue(el, target, formatter) {
    if (!el) return;
    if (reduceMotion || !Number.isFinite(target)) { el.textContent = formatter(target); return; }
    const start = performance.now();
    const step = (now) => {
      const p = Math.min((now - start) / 620, 1);
      el.textContent = formatter(target * (1 - Math.pow(1 - p, 3)));
      if (p < 1) requestAnimationFrame(step); else el.textContent = formatter(target);
    };
    requestAnimationFrame(step);
  }
  function setChip(id, text, className) {
    const el = $(id);
    if (!el) return;
    el.textContent = text;
    el.className = "chip" + (className ? " " + className : "");
  }

  function syncControls(filtros) {
    if (state.initialized) return;
    $("fechaDesde").value = filtros.fechaDesde;
    $("fechaHasta").value = filtros.fechaHasta;
    filtros.opciones.productos.forEach((name) => {
      const option = document.createElement("option"); option.value = name; option.textContent = name;
      $("productoFilter").appendChild(option);
    });
    filtros.opciones.categorias.forEach((name) => {
      const option = document.createElement("option"); option.value = name; option.textContent = name;
      $("categoriaFilter").appendChild(option);
    });
    ["fechaDesde", "fechaHasta"].forEach((id) => {
      $(id).min = filtros.opciones.fechaMin; $(id).max = filtros.opciones.fechaMax;
    });
    state.initialized = true;
  }

  function renderKpis(kpis, meta) {
    animateValue($("kpiVentas"), kpis.ventasTotales, money);
    animateValue($("kpiPedidos"), kpis.pedidos, num);
    animateValue($("kpiTicket"), kpis.ticketPromedio, money);
    animateValue($("kpiUnidades"), kpis.unidadesVendidas, num);
    animateValue($("kpiCostos"), kpis.costos, money);
    animateValue($("kpiUtilidad"), kpis.utilidadBruta, money);
    animateValue($("kpiMargen"), kpis.margenBruto, pct);
    const growth = kpis.crecimientoMensual;
    if (growth === null || growth === undefined) {
      $("kpiCrecimiento").textContent = "—";
      setChip("chipCrecimiento", "Sin mes previo");
    } else {
      $("kpiCrecimiento").textContent = `${growth >= 0 ? "+" : ""}${pct(growth)}`;
      setChip("chipCrecimiento", growth >= 0 ? "▲ positivo" : "▼ negativo", growth >= 0 ? "pos" : "neg");
    }
    $("growthLabel").textContent = kpis.crecimientoEtiqueta || "Último mes";
    setChip("chipVentas", `${num(kpis.registros)} líneas`);
    setChip("chipPedidos", `${pct(kpis.pedidos / meta.registrosTotales * 100)} del total`);
    setChip("chipTicket", money(kpis.ticketPromedio));
    setChip("chipUnidades", `${num(kpis.unidadesVendidas)} uds`);
    setChip("chipCostos", `${pct(kpis.ventasTotales ? kpis.costos / kpis.ventasTotales * 100 : 0)} de ventas`);
    setChip("chipUtilidad", `${pct(kpis.ventasTotales ? kpis.utilidadBruta / kpis.ventasTotales * 100 : 0)} margen`, kpis.utilidadBruta >= 0 ? "pos" : "neg");
    setChip("chipMargen", kpis.margenBruto >= 30 ? "saludable" : "en revisión", kpis.margenBruto >= 30 ? "pos" : "gold");
    const top = kpis.productoMasVendido;
    $("topProductName").textContent = top ? top.producto : "Sin datos";
    $("topProductDetail").textContent = top ? `${money(top.ingreso)} en ingresos` : "Ajusta los filtros";
    $("topProductUnits").textContent = top ? `${num(top.unidades)} uds.` : "—";
    const goal = kpis.cumplimientoMetas;
    $("goalCompliance").textContent = goal === null ? "—" : pct(goal);
    $("goalProgress").style.width = `${Math.max(0, Math.min(goal || 0, 100))}%`;
    $("goalDetail").textContent = goal === null ? "Sin metas en el rango" : (goal >= 100 ? "Meta superada" : "Meta en curso");
    if ($("aiContext")) {
      $("aiContext").textContent = `Contexto verificado · ${meta.archivo} · ventas ${money(kpis.ventasTotales)} · costo ${money(kpis.costos)} · margen ${pct(kpis.margenBruto)}`;
      $("aiStatus").textContent = "Motor local · datos reales";
    }
  }

  function renderMeta(meta) {
    const fecha = new Date(meta.ultimaModificacion.replace(" ", "T"));
    const formatted = fecha.toLocaleString("es-MX", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
    $("lastUpdate").textContent = `Excel: ${formatted}`;
    $("excelStatus").textContent = "Excel conectado";
    $("excelFileName").textContent = meta.archivo;
    $("filterCount").textContent = `${num(meta.registrosTotales)} registros · ${num(meta.catalogoProductos)} productos`;
    $("sourceDescription").textContent =
      `El panel consulta ${meta.archivo} (${meta.fuente}). Última modificación: ${formatted}. ` +
      `${num(meta.registrosTotales)} líneas de venta, ${num(meta.catalogoProductos)} productos. ` +
      (meta.registrosInvalidos ? `${num(meta.registrosInvalidos)} registros omitidos por datos incompletos.` : "Todos los registros son válidos.") +
      " " + meta.disclaimer;
    $("footerDisclaimer").textContent = meta.disclaimer;
  }

  function renderGoals(detail) {
    $("goalsBody").innerHTML = detail.length ? detail.map((g) => {
      const low = g.cumplimiento < 100;
      return `<tr><td><strong>${escapeHtml(g.etiqueta)}</strong></td><td class="num">${moneyFull(g.metaVentas)}</td><td class="num">${moneyFull(g.resultadoVentas)}</td><td class="num"><span class="compliance${low ? " low" : ""}"><i></i>${pct(g.cumplimiento)}</span></td><td class="num">${num(g.metaPedidos)} / ${num(g.resultadoPedidos)}</td><td class="num">${money(g.metaUtilidad)} / ${money(g.resultadoUtilidad)}</td></tr>`;
    }).join("") : '<tr class="empty-row"><td colspan="6">Sin metas para el rango seleccionado.</td></tr>';
  }

  function renderTable() {
    let rows = [...state.rows];
    const search = state.search.trim().toLowerCase();
    if (search) rows = rows.filter((r) => [r.fecha, r.pedido, r.producto, r.categoria, r.canal, r.pago].some((v) => String(v).toLowerCase().includes(search)));
    const { key, dir } = state.sort;
    rows.sort((a, b) => typeof a[key] === "number" ? (a[key] - b[key]) * dir : String(a[key]).localeCompare(String(b[key]), "es") * dir);
    const total = rows.length;
    const pages = Math.max(1, Math.ceil(total / state.pageSize));
    state.page = Math.min(Math.max(1, state.page), pages);
    const start = (state.page - 1) * state.pageSize;
    const pageRows = rows.slice(start, start + state.pageSize);
    $("salesBody").innerHTML = pageRows.length ? pageRows.map((row) => `<tr>
      <td>${escapeHtml(row.fecha)}</td><td class="order-cell">${escapeHtml(row.pedido)}</td>
      <td class="product-cell">${escapeHtml(row.producto)}</td><td>${escapeHtml(row.categoria)}</td>
      <td class="num">${num(row.cantidad)}</td><td class="num">${moneyFull(row.precio)}</td>
      <td class="num">${moneyFull(row.ingreso)}</td><td class="num ${row.utilidad >= 0 ? "profit-pos" : "profit-neg"}">${moneyFull(row.utilidad)}</td>
    </tr>`).join("") : '<tr class="empty-row"><td colspan="8">Sin ventas para los filtros seleccionados.</td></tr>';
    $("pageInfo").textContent = total ? `Mostrando ${num(start + 1)}–${num(Math.min(start + state.pageSize, total))} de ${num(total)}` : "0 registros";
    $("prevPage").disabled = state.page === 1;
    $("nextPage").disabled = state.page === pages;
  }

  function chartOptions() {
    return {
      responsive: true, maintainAspectRatio: false,
      animation: reduceMotion ? false : { duration: 650 },
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { boxWidth: 9, boxHeight: 9, padding: 14, font: { size: 9 } } },
        tooltip: { backgroundColor: "#071c31", padding: 10, cornerRadius: 7, titleFont: { size: 10 }, bodyFont: { size: 10 } },
      },
      scales: {
        x: { grid: { display: false }, ticks: { font: { size: 9 } } },
        y: { beginAtZero: true, grid: { color: "#edf1f4" }, ticks: { font: { size: 9 }, callback: (v) => money(v) } },
      },
    };
  }
  function renderCharts(charts) {
    if (typeof Chart === "undefined") { toast("No se pudo cargar Chart.js", true); return; }
    Object.values(state.charts).forEach((chart) => chart && chart.destroy());
    state.charts = {};
    Chart.defaults.font.family = '"Manrope", "Segoe UI", sans-serif';
    Chart.defaults.color = "#6b7a88";
    const moneyLabel = (ctx) => ` ${ctx.dataset.label}: ${moneyFull(ctx.parsed.y)}`;

    const evo = chartOptions(); evo.plugins.tooltip.callbacks = { label: moneyLabel };
    state.charts.evolucion = new Chart($("chartEvolucion"), { type: "line", data: { labels: charts.evolucion.labels, datasets: [
      { label: "Ingresos", data: charts.evolucion.ingresos, borderColor: "#c6a66a", backgroundColor: "rgba(198,166,106,.12)", fill: true, tension: .35, borderWidth: 2.5, pointRadius: 3 },
      { label: "Utilidad", data: charts.evolucion.utilidades, borderColor: "#0f9d76", backgroundColor: "rgba(15,157,118,.08)", fill: true, tension: .35, borderWidth: 2.5, pointRadius: 3 },
    ] }, options: evo });

    const compare = chartOptions(); compare.plugins.tooltip.callbacks = { label: moneyLabel };
    state.charts.ingresosCostos = new Chart($("chartIngresosCostos"), { type: "bar", data: { labels: charts.ingresosCostos.labels, datasets: [
      { label: "Ingresos", data: charts.ingresosCostos.ingresos, backgroundColor: "#12446e", borderRadius: 6, maxBarThickness: 44 },
      { label: "Costos", data: charts.ingresosCostos.costos, backgroundColor: "#c6a66a", borderRadius: 6, maxBarThickness: 44 },
    ] }, options: compare });

    const cat = chartOptions(); delete cat.scales; cat.cutout = "68%";
    cat.plugins.legend.position = window.innerWidth > 620 ? "right" : "bottom";
    cat.plugins.tooltip.callbacks = { label: (ctx) => ` ${ctx.label}: ${moneyFull(ctx.parsed)} (${pct(charts.categorias.porcentajes[ctx.dataIndex])})` };
    state.charts.categorias = new Chart($("chartCategorias"), { type: "doughnut", data: { labels: charts.categorias.labels, datasets: [{ data: charts.categorias.ingresos, backgroundColor: PALETTE, borderWidth: 2, borderColor: "#fff", hoverOffset: 7 }] }, options: cat });

    const prod = chartOptions(); prod.indexAxis = "y"; prod.plugins.legend.display = false;
    prod.plugins.tooltip.callbacks = { label: (ctx) => ` ${moneyFull(ctx.parsed.x)} · ${num(charts.productos.unidades[ctx.dataIndex])} uds.` };
    state.charts.productos = new Chart($("chartProductos"), { type: "bar", data: { labels: charts.productos.labels, datasets: [{ label: "Ingresos", data: charts.productos.ingresos, backgroundColor: PALETTE, borderRadius: 5, maxBarThickness: 19 }] }, options: prod });

    const goals = chartOptions();
    goals.plugins.tooltip.callbacks = { label: (ctx) => ctx.dataset.label.includes("Cumplimiento") ? ` Cumplimiento: ${pct(ctx.parsed.y)}` : ` ${ctx.dataset.label}: ${moneyFull(ctx.parsed.y)}` };
    goals.scales.y1 = { position: "right", beginAtZero: true, suggestedMax: 130, grid: { drawOnChartArea: false }, ticks: { callback: (v) => `${v}%`, font: { size: 9 } } };
    state.charts.metas = new Chart($("chartMetas"), { type: "bar", data: { labels: charts.metas.labels, datasets: [
      { type: "bar", label: "Meta", data: charts.metas.metas, backgroundColor: "#d7dfe6", borderRadius: 6, maxBarThickness: 56, order: 2 },
      { type: "bar", label: "Resultado", data: charts.metas.resultados, backgroundColor: "#12446e", borderRadius: 6, maxBarThickness: 56, order: 1 },
      { type: "line", label: "Cumplimiento", data: charts.metas.cumplimiento, yAxisID: "y1", borderColor: "#c6a66a", backgroundColor: "#c6a66a", borderWidth: 2.5, tension: .3, pointRadius: 4, order: 0 },
    ] }, options: goals });
  }

  async function loadData(showToast) {
    const btn = $("refreshBtn");
    btn.classList.add("loading"); btn.disabled = true;
    try {
      const data = await getJson(`/api/admin/dashboard?${queryString()}`);
      state.data = data; state.rows = data.tabla.filas; state.page = 1;
      syncControls(data.filtros); renderMeta(data.meta); renderKpis(data.kpis, data.meta);
      renderGoals(data.metasDetalle); renderCharts(data.graficos); renderTable();
      if (showToast) toast("Datos actualizados desde el archivo Excel");
    } catch (error) { toast(`No se pudo leer la fuente: ${error.message}`, true); }
    finally { btn.classList.remove("loading"); btn.disabled = false; }
  }

  async function loadAlerts() {
    try {
      const data = await getJson("/api/admin/anomalias");
      $("alertsList").innerHTML = data.alertas.length ? data.alertas.slice(0, 6).map((a) =>
        `<article class="alert-card ${escapeHtml(a.severidad)}"><strong>${escapeHtml(a.titulo)}</strong><p>${escapeHtml(a.detalle)}</p></article>`
      ).join("") : '<article class="alert-card"><strong>Sin anomalías detectadas</strong><p>No se detectaron desviaciones con las reglas actuales sobre la fuente conectada.</p></article>';
    } catch (_error) { $("alertsList").innerHTML = '<p class="loading-line">No se pudieron calcular las alertas.</p>'; }
  }

  async function loadIntegrations() {
    try {
      const data = await getJson("/api/admin/integrations");
      const entries = Object.entries(data);
      const connected = entries.filter(([, v]) => v.estado === "conectado").length;
      const badge = $("integrationCount");
      badge.textContent = `${connected}/${entries.length} canales configurados`;
      badge.classList.toggle("pending", connected < entries.length);
      $("integrationsList").innerHTML = entries.map(([key, item]) =>
        `<div class="integration-item ${item.estado === "conectado" ? "ok" : ""}"><span class="int-dot"></span><div><strong>${escapeHtml(item.nombre)}</strong><small>${escapeHtml(item.detalle)}</small></div><span class="int-estado">${item.estado === "conectado" ? "Conectado" : "Pendiente"}</span></div>`
      ).join("") + `<div class="actions-row">
        <span>Automatizaciones:</span>
        <button data-action="generate_report">Generar reporte</button>
        <button data-action="email_report">Enviar por Gmail</button>
        <button data-action="drive_backup">Guardar en Drive</button>
      </div>`;
      $("integrationsList").querySelectorAll("[data-action]").forEach((button) => {
        button.addEventListener("click", () => runAction(button.dataset.action));
      });
    } catch (_error) { $("integrationsList").innerHTML = '<p class="loading-line">No se pudo consultar el estado.</p>'; }
  }

  async function runAction(action) {
    if (!window.confirm("¿Solicitar esta automatización al workflow de n8n?")) return;
    try {
      const result = await postJson("/api/admin/actions", { action, confirm: true, payload: { source: "dashboard" } });
      toast(result.message || result.estado, result.estado === "error");
    } catch (error) { toast(error.message, true); }
  }

  async function exportReport(format) {
    try {
      const response = await fetch(`/api/admin/exportar?${queryString({ formato: format })}`, { cache: "no-store" });
      if (response.status === 401) { location.href = "/admin/login"; return; }
      if (!response.ok) throw new Error(`Error ${response.status}`);
      const blob = await response.blob();
      const disposition = response.headers.get("Content-Disposition") || "";
      const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i);
      const filename = encoded ? decodeURIComponent(encoded[1]) : `PuertoAM_Reporte.${format}`;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a"); anchor.href = url; anchor.download = filename;
      document.body.appendChild(anchor); anchor.click(); anchor.remove(); URL.revokeObjectURL(url);
      toast(`Reporte ${format.toUpperCase()} generado`);
    } catch (error) { toast(`No se pudo exportar: ${error.message}`, true); }
  }

  /* ================= AGENTE IA ================= */
  const aiSuggestions = ["¿Cómo van las ventas?", "¿Cuánto gastamos este mes?", "¿Qué facturas faltan?", "¿Hay anomalías?", "¿Cómo va el margen?"];
  let aiBusy = false;
  function renderAiSuggestions(items) {
    const box = $("aiSuggestions"); box.replaceChildren();
    (items || aiSuggestions).forEach((text) => {
      const button = document.createElement("button"); button.type = "button"; button.textContent = text;
      button.addEventListener("click", () => askAgent(text)); box.appendChild(button);
    });
  }
  function addAiMessage(text, kind, meta) {
    const node = document.createElement("div"); node.className = "ai-msg " + kind;
    const body = document.createElement("span"); body.textContent = text; node.appendChild(body);
    if (meta) {
      const foot = document.createElement("span"); foot.className = "ai-meta";
      foot.textContent = meta; node.appendChild(foot);
    }
    $("aiMessages").appendChild(node);
    $("aiMessages").scrollTop = $("aiMessages").scrollHeight;
    return node;
  }
  function openAi() {
    $("aiPanel").classList.add("open"); $("aiPanel").setAttribute("aria-hidden", "false");
    $("aiOverlay").classList.add("show"); $("aiOverlay").setAttribute("aria-hidden", "false");
    setTimeout(() => $("aiInput").focus(), 200);
  }
  function closeAi() {
    $("aiPanel").classList.remove("open"); $("aiPanel").setAttribute("aria-hidden", "true");
    $("aiOverlay").classList.remove("show"); $("aiOverlay").setAttribute("aria-hidden", "true");
  }
  async function askAgent(question) {
    const text = String(question || "").trim();
    if (!text || aiBusy) return;
    aiBusy = true;
    addAiMessage(text, "user");
    $("aiInput").value = "";
    $("aiStatus").textContent = "Analizando la fuente…";
    const typing = document.createElement("div"); typing.className = "ai-msg typing";
    typing.innerHTML = "<i></i><i></i><i></i>";
    $("aiMessages").appendChild(typing);
    $("aiMessages").scrollTop = $("aiMessages").scrollHeight;
    try {
      const result = await postJson("/api/admin/agent", { message: text });
      typing.remove();
      const facts = result.verifiedFacts || {};
      const parts = [
        `Periodo: ${result.periodo || facts.periodo || "—"}`,
        `Fuente: ${facts.fuente || "Excel"}`,
        result.mode === "n8n"
          ? "Respuesta: agente n8n · cifras verificadas adjuntas"
          : result.mode === "openrouter"
            ? "Respuesta: IA con cifras verificadas del Excel"
            : "Respuesta: motor local · cifras calculadas del Excel",
        result.sources && result.sources[result.sources.length - 1],
      ];
      if (result.notice) parts.unshift(result.notice);
      addAiMessage(result.answer || "Sin respuesta", "bot", parts.join(" · "));
      $("aiContext").textContent = `Contexto verificado · ${facts.periodo || "—"} · ventas ${money(facts.ventas)} · costo ${money(facts.costos)} · margen ${pct(facts.margenBruto)}`;
      renderAiSuggestions(result.followUps);
      $("aiStatus").textContent =
        result.mode === "n8n"
          ? "Agente n8n conectado"
          : result.mode === "openrouter"
            ? "IA activa · cifras verificadas"
            : "Motor local · datos reales";
    } catch (error) {
      typing.remove();
      addAiMessage(`No se pudo completar la consulta: ${error.message}`, "bot");
      $("aiStatus").textContent = "Sin conexión";
    } finally { aiBusy = false; }
  }

  function setupDashboardEvents() {
    $("refreshBtn").addEventListener("click", () => loadData(true));
    $("applyFilters").addEventListener("click", () => loadData(true));
    $("clearFilters").addEventListener("click", () => {
      $("fechaDesde").value = state.data?.filtros.opciones.fechaMin || "";
      $("fechaHasta").value = state.data?.filtros.opciones.fechaMax || "";
      $("productoFilter").value = ""; $("categoriaFilter").value = "";
      state.search = ""; $("searchInput").value = ""; loadData(true);
    });
    $("searchInput").addEventListener("input", (event) => { state.search = event.target.value; state.page = 1; renderTable(); });
    $("pageSize").addEventListener("change", (event) => { state.pageSize = Number(event.target.value); state.page = 1; renderTable(); });
    $("prevPage").addEventListener("click", () => { state.page -= 1; renderTable(); });
    $("nextPage").addEventListener("click", () => { state.page += 1; renderTable(); });
    document.querySelectorAll("thead th[data-sort]").forEach((th) => {
      th.addEventListener("click", () => {
        const key = th.dataset.sort;
        state.sort = { key, dir: state.sort.key === key ? -state.sort.dir : -1 };
        state.page = 1; renderTable();
      });
    });
    document.querySelectorAll(".export-btn").forEach((button) => button.addEventListener("click", () => exportReport(button.dataset.format)));

    const sidebar = $("adminSidebar"), overlay = $("adminOverlay");
    const closeSidebar = () => { sidebar.classList.remove("open"); overlay.classList.remove("show"); };
    $("menuBtn").addEventListener("click", () => { sidebar.classList.add("open"); overlay.classList.add("show"); });
    overlay.addEventListener("click", closeSidebar);
    document.querySelectorAll(".nav-link").forEach((link) => link.addEventListener("click", () => {
      document.querySelectorAll(".nav-link").forEach((item) => item.classList.remove("active"));
      link.classList.add("active"); closeSidebar();
    }));

    $("logoutBtn").addEventListener("click", async () => {
      try { await postJson("/api/auth/logout", {}); } catch (_error) { /* la sesión ya expiró */ }
      location.href = "/admin/login";
    });

    $("aiOpen").addEventListener("click", openAi);
    $("aiClose").addEventListener("click", closeAi);
    $("aiOverlay").addEventListener("click", closeAi);
    $("aiForm").addEventListener("submit", (event) => { event.preventDefault(); askAgent($("aiInput").value); });
    document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeAi(); });
    renderAiSuggestions();
  }

  async function setupDashboard() {
    $("adminYear").textContent = new Date().getFullYear();
    try {
      const me = await getJson("/api/auth/me");
      csrfToken = me.csrfToken; username = me.username;
      $("userName").textContent = username;
      $("userInitial").textContent = (username || "A").charAt(0).toUpperCase();
    } catch (_error) { return; }
    setupDashboardEvents();
    await loadData(false);
    loadAlerts();
    loadIntegrations();
  }

  document.addEventListener("DOMContentLoaded", () => {
    if ($("loginForm")) setupLogin();
    else if ($("refreshBtn")) setupDashboard();
  });
})();
