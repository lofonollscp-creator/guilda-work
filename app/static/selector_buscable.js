// Selector con buscador: los desplegables (<select>) con muchas opciones —proyectos, clientes, personas…— se abren en un panel con un
// campo de búsqueda en vez de la lista nativa. Con 200 clientes, recorrer una lista a ojo es inviable; aquí se escribe «vid» y quedan
// los que contienen «vid» (sin distinguir mayúsculas ni acentos).
//
// Mejora progresiva: el <select> sigue siendo el control real (formulario, `required`, `name`, `value`, eventos `change`, atajos de
// teclado, lectores de pantalla). Solo se intercepta la APERTURA para mostrar nuestro panel; elegir una opción pone `select.value` y
// lanza `change`, así que todo lo que escuchaba ese evento (data-autoenviar, cargas perezosas…) sigue funcionando. Sin JavaScript, o con
// pocas opciones, se ve el desplegable de siempre.
//
//   <select>                       se mejora solo si tiene MIN_OPCIONES o más opciones
//   <select data-buscable>         se mejora siempre
//   <select data-sin-buscador>     nunca (también se saltan los `multiple` y los de `size` > 1)
(function () {
  "use strict";

  const MIN_OPCIONES = 6;       // por debajo (prioridad, estado…), la lista nativa es más cómoda
  const MAX_VISIBLES = 300;     // con miles de opciones no se pintan todas: se afina escribiendo
  const MOVIL = window.matchMedia("(max-width: 640px)");

  const textos = (() => {
    const d = document.documentElement.dataset;
    return {
      buscar: d.tBuscarEn || "Buscar…",
      vacio: d.tSinResultados || "Sin resultados",
      mostrando: d.tMostrando || "Mostrando %s de %s: sigue escribiendo para afinar",
    };
  })();

  const normalizar = (t) => (t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

  let abierto = null;           // { select, panel, entrada, lista, fondo, activo, items }
  let contador = 0;

  const esMejorable = (sel) => {
    if (!(sel instanceof HTMLSelectElement) || sel.dataset.buscableListo) return false;
    if (sel.multiple || sel.size > 1 || "sinBuscador" in sel.dataset) return false;
    if (sel.closest("[data-sin-buscador]")) return false;
    return "buscable" in sel.dataset || sel.options.length >= MIN_OPCIONES;
  };

  // ---- Datos: opciones y grupos del <select> en una lista plana ------------------------------------------------------------------
  function leerOpciones(sel) {
    const items = [];
    const añadir = (op, grupo) => items.push({ op, valor: op.value, texto: op.textContent.trim(), clave: normalizar(op.textContent), deshabilitada: op.disabled, grupo });
    for (const hijo of sel.children) {
      if (hijo.tagName === "OPTGROUP") for (const op of hijo.children) añadir(op, hijo.label);
      else if (hijo.tagName === "OPTION") añadir(hijo, null);
    }
    return items;
  }

  // ---- Panel ---------------------------------------------------------------------------------------------------------------------
  function abrir(sel) {
    if (abierto) cerrar(false);
    if (sel.disabled) return;
    const id = "selector-buscable-" + ++contador;
    const panel = document.createElement("div");
    panel.className = "selbus-panel";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", etiquetaDe(sel));
    const entrada = document.createElement("input");
    entrada.type = "search"; entrada.className = "selbus-buscar"; entrada.autocomplete = "off"; entrada.spellcheck = false;
    entrada.placeholder = textos.buscar; entrada.setAttribute("role", "combobox");
    entrada.setAttribute("aria-expanded", "true"); entrada.setAttribute("aria-controls", id); entrada.setAttribute("aria-autocomplete", "list");
    entrada.setAttribute("aria-label", etiquetaDe(sel));
    const lista = document.createElement("ul");
    lista.id = id; lista.className = "selbus-lista"; lista.setAttribute("role", "listbox");
    const pie = document.createElement("div");
    pie.className = "selbus-pie"; pie.setAttribute("aria-live", "polite"); pie.hidden = true;
    panel.append(entrada, lista, pie);

    let fondo = null;
    if (MOVIL.matches) {
      fondo = document.createElement("div");
      fondo.className = "selbus-fondo";
      fondo.addEventListener("click", () => cerrar(true));
      document.body.append(fondo);
      panel.classList.add("selbus-hoja");
    }
    document.body.append(panel);

    abierto = { select: sel, panel, entrada, lista, pie, fondo, activo: -1, items: leerOpciones(sel), visibles: [] };
    sel.setAttribute("aria-expanded", "true");
    posicionar();
    filtrar("");
    entrada.addEventListener("input", () => filtrar(entrada.value));
    entrada.addEventListener("keydown", teclas);
    lista.addEventListener("mousedown", (e) => e.preventDefault());   // no robar el foco al campo
    lista.addEventListener("click", (e) => {
      const li = e.target.closest("li[data-i]");
      if (li) elegir(abierto.visibles[Number(li.dataset.i)]);
    });
    lista.addEventListener("mousemove", (e) => {
      const li = e.target.closest("li[data-i]");
      if (li && Number(li.dataset.i) !== abierto.activo) marcar(Number(li.dataset.i), false);
    });
    entrada.focus({ preventScroll: true });
  }

  function etiquetaDe(sel) {
    if (sel.getAttribute("aria-label")) return sel.getAttribute("aria-label");
    if (sel.labels && sel.labels[0]) return sel.labels[0].textContent.trim();
    return sel.title || sel.name || "";
  }

  function filtrar(consulta) {
    const a = abierto;
    const palabras = normalizar(consulta).split(/\s+/).filter(Boolean);
    const coincide = a.items.filter((it) => palabras.every((p) => it.clave.includes(p)));
    a.visibles = coincide.slice(0, MAX_VISIBLES);
    a.lista.textContent = "";
    let grupoActual = null;
    a.visibles.forEach((it, i) => {
      if (it.grupo && it.grupo !== grupoActual) {
        const cab = document.createElement("li");
        cab.className = "selbus-grupo"; cab.setAttribute("role", "presentation"); cab.textContent = it.grupo;
        a.lista.append(cab);
      }
      grupoActual = it.grupo;
      const li = document.createElement("li");
      li.id = a.lista.id + "-" + i; li.dataset.i = String(i);
      li.className = "selbus-opcion" + (it.op.selected ? " es-elegida" : "") + (it.deshabilitada ? " es-deshabilitada" : "");
      li.setAttribute("role", "option"); li.setAttribute("aria-selected", it.op.selected ? "true" : "false");
      if (it.deshabilitada) li.setAttribute("aria-disabled", "true");
      resaltar(li, it.texto, palabras);
      a.lista.append(li);
    });
    if (!a.visibles.length) {
      const vacio = document.createElement("li");
      vacio.className = "selbus-vacio"; vacio.setAttribute("role", "presentation"); vacio.textContent = textos.vacio;
      a.lista.append(vacio);
    }
    a.pie.hidden = coincide.length <= MAX_VISIBLES;
    a.pie.textContent = a.pie.hidden ? "" : textos.mostrando.replace("%s", String(MAX_VISIBLES)).replace("%s", String(coincide.length));
    // Activo: la opción elegida si se ve, y si no la primera habilitada
    let inicial = a.visibles.findIndex((it) => it.op.selected && !it.deshabilitada);
    if (palabras.length || inicial < 0) inicial = a.visibles.findIndex((it) => !it.deshabilitada);
    marcar(inicial, true);
  }

  // Resalta lo escrito (con nodos de texto: el texto de una opción nunca se interpreta como HTML)
  function resaltar(li, texto, palabras) {
    if (!palabras.length) { li.textContent = texto; return; }
    const normal = normalizar(texto);
    const rangos = [];
    for (const p of palabras) {
      const i = normal.indexOf(p);
      if (i >= 0) rangos.push([i, i + p.length]);
    }
    rangos.sort((x, y) => x[0] - y[0]);
    const unidos = [];
    for (const r of rangos) {
      const ultimo = unidos[unidos.length - 1];
      if (ultimo && r[0] <= ultimo[1]) ultimo[1] = Math.max(ultimo[1], r[1]); else unidos.push([...r]);
    }
    let pos = 0;
    for (const [d, h] of unidos) {
      if (d > pos) li.append(texto.slice(pos, d));
      const m = document.createElement("mark"); m.textContent = texto.slice(d, h); li.append(m);
      pos = h;
    }
    if (pos < texto.length) li.append(texto.slice(pos));
  }

  function marcar(i, desplazar) {
    const a = abierto;
    const previo = a.lista.querySelector(".es-activa");
    if (previo) previo.classList.remove("es-activa");
    a.activo = i;
    if (i < 0) { a.entrada.removeAttribute("aria-activedescendant"); return; }
    const li = a.lista.querySelector(`li[data-i="${i}"]`);
    if (!li) return;
    li.classList.add("es-activa");
    a.entrada.setAttribute("aria-activedescendant", li.id);
    if (desplazar) li.scrollIntoView({ block: "nearest" });
  }

  function mover(delta) {
    const a = abierto;
    if (!a.visibles.length) return;
    let i = a.activo;
    for (let n = 0; n < a.visibles.length; n++) {
      i = (i + delta + a.visibles.length) % a.visibles.length;
      if (!a.visibles[i].deshabilitada) break;
    }
    marcar(i, true);
  }

  function teclas(e) {
    if (e.key === "ArrowDown") { e.preventDefault(); mover(1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); mover(-1); }
    else if (e.key === "Home" && e.ctrlKey) { e.preventDefault(); marcar(abierto.visibles.findIndex((it) => !it.deshabilitada), true); }
    else if (e.key === "Enter") { e.preventDefault(); if (abierto.activo >= 0) elegir(abierto.visibles[abierto.activo]); }
    else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); cerrar(true); }
    else if (e.key === "Tab") cerrar(false);
  }

  function elegir(it) {
    if (!it || it.deshabilitada) return;
    const sel = abierto.select;
    const cambia = sel.value !== it.valor || !it.op.selected;
    cerrar(true);
    if (cambia) {
      sel.value = it.valor;
      sel.dispatchEvent(new Event("input", { bubbles: true }));
      sel.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }

  function cerrar(devolverFoco) {
    if (!abierto) return;
    const { select, panel, fondo } = abierto;
    abierto = null;
    panel.remove();
    if (fondo) fondo.remove();
    select.setAttribute("aria-expanded", "false");
    if (devolverFoco) select.focus({ preventScroll: true });
  }

  // Debajo del selector si cabe; si no, encima. En móvil es una hoja inferior (CSS) y no se posiciona.
  function posicionar() {
    const a = abierto;
    if (!a || a.panel.classList.contains("selbus-hoja")) return;
    const r = a.select.getBoundingClientRect();
    const ancho = Math.min(Math.max(r.width, 260), window.innerWidth - 16);
    const izquierda = Math.min(Math.max(8, r.left), window.innerWidth - ancho - 8);
    a.panel.style.width = ancho + "px";
    a.panel.style.left = izquierda + "px";
    const debajo = window.innerHeight - r.bottom - 12;
    const encima = r.top - 12;
    const hacerArriba = debajo < 220 && encima > debajo;
    const alto = Math.max(160, Math.min(380, hacerArriba ? encima : debajo));
    a.panel.style.maxHeight = alto + "px";
    if (hacerArriba) { a.panel.style.top = "auto"; a.panel.style.bottom = window.innerHeight - r.top + 6 + "px"; }
    else { a.panel.style.bottom = "auto"; a.panel.style.top = r.bottom + 6 + "px"; }
  }

  // ---- Enganche: se intercepta solo la apertura del <select> ----------------------------------------------------------------------
  function mejorar(sel) {
    if (!esMejorable(sel)) return;
    sel.dataset.buscableListo = "1";
    sel.classList.add("selbus-origen");
    sel.setAttribute("aria-haspopup", "listbox");
    sel.setAttribute("aria-expanded", "false");
    sel.addEventListener("mousedown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault();                 // evita la lista nativa
      abierto && abierto.select === sel ? cerrar(true) : abrir(sel);
    });
    sel.addEventListener("keydown", (e) => {
      if (e.altKey || e.ctrlKey || e.metaKey) return;
      if (e.key === " " || e.key === "Enter" || e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "F4") {
        if (e.key === "Enter" && !sel.form) return;
        e.preventDefault(); abrir(sel);
      } else if (e.key.length === 1) {    // escribir sobre el selector abre el panel con esa letra ya puesta
        e.preventDefault(); abrir(sel); abierto.entrada.value = e.key; filtrar(e.key);
      }
    });
    // Táctil: un toque abre nuestro panel (si no, iOS/Android muestran su selector nativo, sin búsqueda). Un arrastre no cuenta.
    let toque = null;
    sel.addEventListener("touchstart", (e) => { const t = e.touches[0]; toque = { x: t.clientX, y: t.clientY, t: Date.now() }; }, { passive: true });
    sel.addEventListener("touchend", (e) => {
      if (!toque) return;
      const t = e.changedTouches[0];
      const tap = Math.abs(t.clientX - toque.x) < 10 && Math.abs(t.clientY - toque.y) < 10 && Date.now() - toque.t < 600;
      toque = null;
      if (tap && e.cancelable) { e.preventDefault(); abrir(sel); }
    });
  }

  function barrer(raiz) {
    if (raiz.nodeType !== 1) return;
    if (raiz.tagName === "SELECT") mejorar(raiz);
    else raiz.querySelectorAll && raiz.querySelectorAll("select").forEach(mejorar);
  }

  document.addEventListener("mousedown", (e) => { if (abierto && !abierto.panel.contains(e.target) && e.target !== abierto.select) cerrar(false); }, true);
  window.addEventListener("resize", () => { if (abierto) { if (MOVIL.matches !== abierto.panel.classList.contains("selbus-hoja")) cerrar(false); else posicionar(); } });
  window.addEventListener("scroll", (e) => { if (abierto && !abierto.panel.contains(e.target)) posicionar(); }, true);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && abierto) { e.stopPropagation(); cerrar(true); } }, true);

  const arrancar = () => {
    document.querySelectorAll("select").forEach(mejorar);
    // Selects que aparecen después (modales, cargas perezosas) y selects a los que se añaden opciones tras cargar la página
    new MutationObserver((muts) => muts.forEach((m) => {
      m.addedNodes.forEach(barrer);
      const sel = m.target.nodeType === 1 && (m.target.tagName === "SELECT" ? m.target : m.target.closest && m.target.closest("select"));
      if (sel) mejorar(sel);
    })).observe(document.body, { childList: true, subtree: true });
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", arrancar); else arrancar();
  window.selectorBuscable = { mejorar, barrer };
})();
