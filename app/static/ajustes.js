// Ajustes: filtro de la lista y controles de apariencia (tema y densidad, que viven en el navegador con las mismas claves que el panel de
// la barra superior, static/sidebar.js; el idioma es un formulario normal).
(function () {
  "use strict";
  const CLAVE_TEMA = "guilda-work-tema", CLAVE_DENSIDAD = "guilda-work-densidad";
  const guardar = (clave, valor) => { try { localStorage.setItem(clave, valor); } catch (e) { /* navegación privada */ } };
  const leer = (clave, defecto) => { try { return localStorage.getItem(clave) || defecto; } catch (e) { return defecto; } };

  function segmentado(grupo, actual, alElegir) {
    const botones = [...grupo.querySelectorAll("button[data-valor]")];
    const pintar = (valor) => botones.forEach((b) => { const on = b.dataset.valor === valor; b.setAttribute("aria-checked", on ? "true" : "false"); b.classList.toggle("is-activo", on); b.tabIndex = on ? 0 : -1; });
    pintar(actual);
    botones.forEach((b, i) => {
      b.addEventListener("click", () => { pintar(b.dataset.valor); alElegir(b.dataset.valor); });
      b.addEventListener("keydown", (e) => {   // flechas dentro del grupo, como un radiogroup
        const paso = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
        if (!paso) return;
        e.preventDefault();
        const siguiente = botones[(i + paso + botones.length) % botones.length];
        siguiente.focus(); siguiente.click();
      });
    });
  }

  document.querySelectorAll("[data-ajuste-tema]").forEach((g) => segmentado(g, leer(CLAVE_TEMA, "system"), (v) => {
    guardar(CLAVE_TEMA, v);
    if (v === "system") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = v;
  }));
  document.querySelectorAll("[data-ajuste-densidad]").forEach((g) => segmentado(g, leer(CLAVE_DENSIDAD, "normal"), (v) => {
    guardar(CLAVE_DENSIDAD, v);
    if (v === "normal") delete document.documentElement.dataset.densidad; else document.documentElement.dataset.densidad = v;
  }));

  // Filtro de la lista de ajustes (sin distinguir mayúsculas ni acentos)
  const filtro = document.getElementById("ajustes-filtro");
  if (!filtro) return;
  const norm = (t) => (t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const tarjetas = [...document.querySelectorAll("[data-ajuste]")];
  const vacio = document.getElementById("ajustes-vacio");
  filtro.addEventListener("input", () => {
    const palabras = norm(filtro.value).split(/\s+/).filter(Boolean);
    let visibles = 0;
    tarjetas.forEach((t) => { const ok = palabras.every((p) => norm(t.dataset.texto).includes(p)); t.hidden = !ok; if (ok) visibles++; });
    document.querySelectorAll(".ajustes-grupo").forEach((s) => { s.hidden = !s.querySelector("[data-ajuste]:not([hidden])"); });
    document.querySelectorAll(".ajustes-rapidos").forEach((s) => { s.hidden = palabras.length > 0 && !norm("apariencia tema densidad idioma oscuro claro compacta").includes(palabras[0]); });
    if (vacio) vacio.hidden = visibles > 0 || document.querySelector(".ajustes-rapidos:not([hidden])") !== null;
  });
})();
