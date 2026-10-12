// Selector de fecha del sistema de diseño. Sustituye al calendario nativo de <input type="date|datetime-local|time"> por un calendario propio,
// igual en todos los navegadores y en los dos temas.
//
// Mejora progresiva (mismo criterio que selector_buscable.js): el <input> sigue siendo el control real —formulario, `required`, `min`/`max`,
// `value`, eventos `input`/`change`, teclear la fecha por segmentos—. Solo se intercepta la APERTURA del selector nativo.
//
//   <input type="date">             calendario; elegir un día cierra y rellena
//   <input type="datetime-local">   calendario + hora; se confirma con «Aceptar»
//   <input type="time">             solo hora
//   <input type="date" data-nativo> nunca se mejora
//   name="desde" / name="hasta" en el mismo formulario: atajos de periodo («Este mes», «Este trimestre»…) que rellenan los dos a la vez
//
// Teclado: Alt+↓ o F4 abren; dentro, flechas mueven el día, Inicio/Fin la semana, AvPág/RePág el mes (con Mayús, el año), Intro elige, Esc cierra.
(function () {
  "use strict";

  const TIPOS = new Set(["date", "datetime-local", "time"]);
  const MOVIL = window.matchMedia ? window.matchMedia("(max-width: 640px)") : { matches: false };
  const T = () => window.GUILDA_I18N || {};
  const txt = (clave, defecto) => T()[clave] || defecto;
  const idioma = () => document.documentElement.lang || "es";

  const pad = (n) => String(n).padStart(2, "0");
  const iso = (d) => d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  const analizar = (s) => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s || ""); return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null; };
  const horaDe = (s) => { const m = /(\d{2}):(\d{2})/.exec(s || ""); return m ? { h: +m[1], m: +m[2] } : null; };
  const mismoDia = (a, b) => a && b && iso(a) === iso(b);
  const sumarDias = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
  const sumarMeses = (d, n) => {            // conserva el día si existe en el mes de destino; si no, el último
    const x = new Date(d.getFullYear(), d.getMonth() + n, 1);
    x.setDate(Math.min(d.getDate(), new Date(x.getFullYear(), x.getMonth() + 1, 0).getDate()));
    return x;
  };

  let abierto = null;     // { input, panel, fondo, vista, foco, elegido, hora, tipo }

  const mejorable = (el) => el && el.tagName === "INPUT" && TIPOS.has(el.type) && !el.disabled && !el.readOnly && !("nativo" in el.dataset);

  function nombresMes(d) { return new Intl.DateTimeFormat(idioma(), { month: "long", year: "numeric" }).format(d); }
  function nombresDia() {
    const f = new Intl.DateTimeFormat(idioma(), { weekday: "short" });
    return [...Array(7)].map((_, i) => f.format(new Date(2024, 0, 1 + i)));      // el 1/1/2024 fue lunes
  }
  function nombreLargo(d) { return new Intl.DateTimeFormat(idioma(), { weekday: "long", day: "numeric", month: "long", year: "numeric" }).format(d); }

  // ---- Atajos de periodo (solo cuando hay un par desde/hasta en el formulario) ------------------------------------------------------
  function parDesdeHasta(input) {
    if (!input.form || (input.name !== "desde" && input.name !== "hasta")) return null;
    const desde = input.form.elements.desde, hasta = input.form.elements.hasta;
    return desde && hasta && desde.type === "date" && hasta.type === "date" ? { desde, hasta } : null;
  }
  function periodos() {
    const hoy = new Date(), y = hoy.getFullYear(), m = hoy.getMonth();
    const lunes = sumarDias(hoy, -((hoy.getDay() + 6) % 7));
    const trimIni = Math.floor(m / 3) * 3;
    return [
      [txt("dsEstaSemana", "Esta semana"), lunes, sumarDias(lunes, 6)],
      [txt("dsEsteMes", "Este mes"), new Date(y, m, 1), new Date(y, m + 1, 0)],
      [txt("dsMesPasado", "Mes pasado"), new Date(y, m - 1, 1), new Date(y, m, 0)],
      [txt("dsEsteTrimestre", "Este trimestre"), new Date(y, trimIni, 1), new Date(y, trimIni + 3, 0)],
      [txt("dsEsteAnio", "Este año"), new Date(y, 0, 1), new Date(y, 11, 31)],
    ];
  }

  // ---- Escribir el valor -------------------------------------------------------------------------------------------------------------
  function poner(input, valor) {
    if (input.value === valor) return;
    input.value = valor;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function valorFinal(a) {
    if (a.tipo === "time") return pad(a.hora.h) + ":" + pad(a.hora.m);
    if (!a.elegido) return "";
    return a.tipo === "date" ? iso(a.elegido) : iso(a.elegido) + "T" + pad(a.hora.h) + ":" + pad(a.hora.m);
  }

  // ---- Panel -------------------------------------------------------------------------------------------------------------------------
  function abrir(input) {
    if (abierto) cerrar(false);
    const tipo = input.type;
    const actual = tipo === "time" ? null : analizar(input.value);
    const hoy = new Date();
    const hora = horaDe(input.value) || (tipo === "datetime-local" ? { h: 9, m: 0 } : { h: 9, m: 0 });
    const panel = document.createElement("div");
    panel.className = "ds-cal";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", (input.labels && input.labels[0] ? input.labels[0].textContent.trim() : input.title || input.name || "") || txt("dsFecha", "Fecha"));
    let fondo = null;
    if (MOVIL.matches) {
      fondo = document.createElement("div");
      fondo.className = "ds-cal-fondo";
      fondo.addEventListener("click", () => cerrar(true));
      document.body.append(fondo);
      panel.classList.add("ds-cal-hoja");
    }
    document.body.append(panel);
    const base = actual || hoy;
    abierto = { input, panel, fondo, tipo, vista: new Date(base.getFullYear(), base.getMonth(), 1), foco: actual || hoy, elegido: actual, hora };
    pintar();
    posicionar();
    enfocar();
  }

  function limites(input) {
    return { min: analizar(input.min), max: analizar(input.max) };
  }
  function permitido(d, lim) { return !((lim.min && d < lim.min) || (lim.max && d > lim.max)); }

  function boton(clase, texto, etiqueta, alClic) {
    const b = document.createElement("button");
    b.type = "button"; b.className = clase; b.textContent = texto;
    if (etiqueta) b.setAttribute("aria-label", etiqueta);
    b.addEventListener("click", alClic);
    return b;
  }

  function pintar() {
    const a = abierto;
    const p = a.panel;
    p.textContent = "";
    const lim = limites(a.input);

    if (a.tipo !== "time") {
      const cab = document.createElement("div");
      cab.className = "ds-cal-cabecera";
      const titulo = document.createElement("div");
      titulo.className = "ds-cal-titulo"; titulo.setAttribute("aria-live", "polite"); titulo.textContent = nombresMes(a.vista);
      cab.append(
        boton("ds-cal-nav", "‹", txt("dsMesAnterior", "Mes anterior"), () => { a.vista = sumarMeses(a.vista, -1); a.foco = sumarMeses(a.foco, -1); pintar(); enfocar(); }),
        titulo,
        boton("ds-cal-nav", "›", txt("dsMesSiguiente", "Mes siguiente"), () => { a.vista = sumarMeses(a.vista, 1); a.foco = sumarMeses(a.foco, 1); pintar(); enfocar(); }),
      );
      p.append(cab);

      const rejilla = document.createElement("div");
      rejilla.className = "ds-cal-rejilla"; rejilla.setAttribute("role", "grid"); rejilla.setAttribute("aria-label", nombresMes(a.vista));
      nombresDia().forEach((n) => { const s = document.createElement("span"); s.className = "ds-cal-sem"; s.setAttribute("role", "columnheader"); s.textContent = n; rejilla.append(s); });
      const primero = new Date(a.vista.getFullYear(), a.vista.getMonth(), 1);
      const inicio = sumarDias(primero, -((primero.getDay() + 6) % 7));
      const hoy = new Date();
      for (let i = 0; i < 42; i++) {
        const d = sumarDias(inicio, i);
        const b = document.createElement("button");
        b.type = "button"; b.className = "ds-cal-dia"; b.textContent = String(d.getDate()); b.dataset.fecha = iso(d);
        b.setAttribute("role", "gridcell"); b.setAttribute("aria-label", nombreLargo(d));
        if (d.getMonth() !== a.vista.getMonth()) b.classList.add("fuera");
        if (mismoDia(d, hoy)) { b.classList.add("hoy"); b.setAttribute("aria-current", "date"); }
        if (mismoDia(d, a.elegido)) { b.classList.add("elegido"); b.setAttribute("aria-selected", "true"); }
        if (!permitido(d, lim)) { b.disabled = true; }
        b.tabIndex = mismoDia(d, a.foco) ? 0 : -1;
        b.addEventListener("click", () => elegirDia(d));
        rejilla.append(b);
      }
      p.append(rejilla);
    }

    if (a.tipo !== "date") {
      const fila = document.createElement("div");
      fila.className = "ds-cal-hora";
      const h = numero(txt("dsHora", "Hora"), 23, a.hora.h, (v) => { a.hora.h = v; });
      const m = numero(txt("dsMinutos", "Minutos"), 59, a.hora.m, (v) => { a.hora.m = v; });
      const dos = document.createElement("span"); dos.textContent = ":"; dos.setAttribute("aria-hidden", "true");
      fila.append(h, dos, m);
      p.append(fila);
    }

    const pie = document.createElement("div");
    pie.className = "ds-cal-pie";
    if (a.tipo === "date") {
      pie.append(boton("btn btn-ghost btn-sm", txt("dsHoy", "Hoy"), null, () => elegirDia(new Date())));
    } else if (a.tipo === "datetime-local") {
      pie.append(boton("btn btn-ghost btn-sm", txt("dsHoy", "Hoy"), null, () => { a.elegido = new Date(); a.vista = new Date(a.elegido.getFullYear(), a.elegido.getMonth(), 1); a.foco = a.elegido; pintar(); enfocar(); }));
    }
    if (!a.input.required && a.input.value) pie.append(boton("btn btn-ghost btn-sm", txt("dsBorrar", "Borrar"), null, () => { poner(a.input, ""); cerrar(true); }));
    if (a.tipo !== "date") pie.append(boton("btn btn-primary btn-sm", txt("dsAceptar", "Aceptar"), null, () => { poner(a.input, valorFinal(a)); cerrar(true); }));
    if (pie.children.length) p.append(pie);

    const par = parDesdeHasta(a.input);
    if (par) {
      const per = document.createElement("div");
      per.className = "ds-cal-periodos"; per.setAttribute("role", "group"); per.setAttribute("aria-label", txt("dsPeriodo", "Periodo"));
      periodos().forEach(([nombre, d1, d2]) => per.append(boton("ds-chip ds-cal-periodo", nombre, null, () => {
        poner(par.desde, iso(d1)); poner(par.hasta, iso(d2)); cerrar(true);
      })));
      p.append(per);
    }
  }

  function numero(etiqueta, max, valor, alCambiar) {
    const i = document.createElement("input");
    i.type = "number"; i.min = "0"; i.max = String(max); i.value = pad(valor); i.inputMode = "numeric";
    i.setAttribute("aria-label", etiqueta); i.className = "ds-cal-num";
    i.addEventListener("input", () => { const v = Math.min(max, Math.max(0, parseInt(i.value, 10) || 0)); alCambiar(v); });
    i.addEventListener("blur", () => { i.value = pad(Math.min(max, Math.max(0, parseInt(i.value, 10) || 0))); });
    return i;
  }

  function enfocar() {
    const a = abierto;
    if (!a) return;
    const b = a.panel.querySelector(".ds-cal-dia[tabindex='0']") || a.panel.querySelector(".ds-cal-num") || a.panel.querySelector("button");
    if (b) b.focus({ preventScroll: true });
  }

  function elegirDia(d) {
    const a = abierto;
    if (!a || !permitido(d, limites(a.input))) return;
    a.elegido = d; a.foco = d;
    if (a.tipo === "date") { poner(a.input, iso(d)); cerrar(true); return; }
    a.vista = new Date(d.getFullYear(), d.getMonth(), 1);
    pintar(); enfocar();
  }

  function cerrar(devolverFoco) {
    if (!abierto) return;
    const { input, panel, fondo } = abierto;
    abierto = null;
    panel.remove();
    if (fondo) fondo.remove();
    if (devolverFoco) input.focus({ preventScroll: true });
  }

  function posicionar() {
    const a = abierto;
    if (!a || a.panel.classList.contains("ds-cal-hoja")) return;
    const r = a.input.getBoundingClientRect();
    const ancho = a.panel.offsetWidth || 296;
    a.panel.style.left = Math.min(Math.max(8, r.left), window.innerWidth - ancho - 8) + "px";
    const alto = a.panel.offsetHeight || 340;
    const cabeAbajo = window.innerHeight - r.bottom - 12 >= alto;
    const cabeArriba = r.top - 12 >= alto;
    if (!cabeAbajo && cabeArriba) { a.panel.style.top = "auto"; a.panel.style.bottom = window.innerHeight - r.top + 6 + "px"; }
    else { a.panel.style.bottom = "auto"; a.panel.style.top = Math.max(8, r.bottom + 6) + "px"; }
  }

  // ---- Teclado dentro del calendario -------------------------------------------------------------------------------------------------
  function teclasPanel(e) {
    const a = abierto;
    if (!a) return;
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); cerrar(true); return; }
    if (!e.target.classList || !e.target.classList.contains("ds-cal-dia")) return;
    const mov = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[e.key];
    let destino = null;
    if (mov) destino = sumarDias(a.foco, mov);
    else if (e.key === "Home") destino = sumarDias(a.foco, -((a.foco.getDay() + 6) % 7));
    else if (e.key === "End") destino = sumarDias(a.foco, 6 - ((a.foco.getDay() + 6) % 7));
    else if (e.key === "PageUp") destino = e.shiftKey ? sumarMeses(a.foco, -12) : sumarMeses(a.foco, -1);
    else if (e.key === "PageDown") destino = e.shiftKey ? sumarMeses(a.foco, 12) : sumarMeses(a.foco, 1);
    if (destino) {
      e.preventDefault();
      a.foco = destino;
      if (destino.getMonth() !== a.vista.getMonth() || destino.getFullYear() !== a.vista.getFullYear()) a.vista = new Date(destino.getFullYear(), destino.getMonth(), 1);
      pintar(); enfocar();
    }
  }

  // ---- Enganche global (delegado: vale también para campos que aparecen después) ------------------------------------------------------
  document.addEventListener("mousedown", (e) => {
    if (abierto && !abierto.panel.contains(e.target) && e.target !== abierto.input) cerrar(false);
    const el = e.target;
    if (!mejorable(el) || e.button !== 0) return;
    e.preventDefault();                       // evita el calendario nativo
    el.focus({ preventScroll: true });
    abierto && abierto.input === el ? cerrar(true) : abrir(el);
  }, true);
  document.addEventListener("click", (e) => { if (mejorable(e.target)) e.preventDefault(); }, true);   // el icono del calendario nativo abre al hacer clic
  document.addEventListener("keydown", (e) => {
    if (abierto && abierto.panel.contains(e.target)) { teclasPanel(e); return; }
    if (mejorable(e.target) && ((e.key === "ArrowDown" && e.altKey) || e.key === "F4")) { e.preventDefault(); abrir(e.target); }
  }, true);
  document.addEventListener("touchend", (e) => {
    const el = e.target;
    if (mejorable(el) && e.cancelable) { e.preventDefault(); el.focus({ preventScroll: true }); abrir(el); }
  }, { capture: true, passive: false });
  window.addEventListener("resize", () => { if (abierto) { if (MOVIL.matches !== abierto.panel.classList.contains("ds-cal-hoja")) cerrar(false); else posicionar(); } });
  window.addEventListener("scroll", (e) => { if (abierto && !abierto.panel.contains(e.target)) posicionar(); }, true);

  window.GuildaFecha = { abrir, cerrar: () => cerrar(false), _iso: iso, _analizar: analizar };
})();
