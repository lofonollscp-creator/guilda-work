/* Web v2 · flujos de interfaz comunes a toda la plataforma.
   1) Marca <html class="js"> (para ocultar controles que solo hacen falta sin JavaScript).
   2) Evita envíos dobles: al enviar un formulario, el botón se bloquea y muestra «cargando» (se libera al volver con «atrás» o a los 20 s).
   3) Avisa antes de salir de un formulario largo con cambios sin guardar.
   4) El botón «Más» de la barra inferior (móvil) abre el menú lateral.
   5) Enlaza las etiquetas sueltas con su campo. */
(function () {
  "use strict";
  document.documentElement.classList.add("js");

  var NO_BLOQUEAR = /descargar|export|pdf|csv|json|\.ics|fichero|imprimir|logout|salir/i;
  var cambiosSinGuardar = false;

  function liberar(boton) {
    boton.classList.remove("is-enviando");
    boton.removeAttribute("aria-busy");
    boton.disabled = false;
  }

  document.addEventListener("submit", function (e) {
    var f = e.target;
    if (!(f instanceof HTMLFormElement) || e.defaultPrevented) return;
    cambiosSinGuardar = false;
    if ((f.getAttribute("method") || "").toLowerCase() !== "post" || f.target === "_blank" || f.hasAttribute("data-no-bloquear") || NO_BLOQUEAR.test(f.action || "")) return;
    var boton = e.submitter && e.submitter.tagName === "BUTTON" ? e.submitter : f.querySelector('button[type="submit"], button:not([type])');
    if (!boton || boton.disabled) return;
    // Se bloquea en el siguiente ciclo: así el botón sigue aportando su name/value al envío.
    setTimeout(function () {
      if (e.defaultPrevented) return;      // otro manejador lo ha cancelado (confirmación rechazada) o lo envía por fetch
      boton.classList.add("is-enviando");
      boton.setAttribute("aria-busy", "true");
      boton.disabled = true;
      setTimeout(function () { liberar(boton); }, 20000);
    }, 0);
  }, true);

  window.addEventListener("pageshow", function (ev) {
    if (!ev.persisted) return;
    document.querySelectorAll("button.is-enviando").forEach(liberar);
  });

  // Formularios largos de edición: aviso al salir con cambios.
  document.querySelectorAll("form.edit-form, form.notas-form").forEach(function (f) {
    if ((f.getAttribute("method") || "").toLowerCase() !== "post") return;
    f.addEventListener("input", function () { cambiosSinGuardar = true; });
  });
  window.addEventListener("beforeunload", function (e) {
    if (!cambiosSinGuardar) return;
    e.preventDefault();
    e.returnValue = "";
  });

  var mas = document.getElementById("barra-inferior-mas");
  var abrir = document.getElementById("menu-movil-abrir");
  if (mas && abrir) mas.addEventListener("click", function () { abrir.click(); });

  /* ---- Escritorio: atajos de una tecla y navegación por listas -------------------------------------------------------------- */
  function escribiendo(e) {
    var el = e.target; if (!el) return false;
    return /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable;
  }
  var DESTINOS = { h: "/hoy/", t: "/tareas/", n: "/notas", c: "/correo/", f: "/fichaje/", i: "/ia/", l: "/clientes/" };
  var esperandoG = false, temporizadorG = null;
  var enCorreo = /^\/correo\//.test(location.pathname);
  var indice = -1;

  function filas() {
    return Array.prototype.slice.call(document.querySelectorAll(".tarea-fila, .cliente-fila, .nota-item, .fiscal-fila.vencimiento-fiscal-item")).filter(function (f) { return f.offsetParent !== null; });
  }
  function enfocar(i) {
    var lista = filas(); if (!lista.length) return;
    indice = Math.max(0, Math.min(lista.length - 1, i));
    lista.forEach(function (f) { f.classList.remove("fila-foco"); });
    var f = lista[indice]; f.classList.add("fila-foco"); f.scrollIntoView({ block: "nearest" });
    var enlace = f.querySelector("a[data-ficha]");
    if (enlace && window.matchMedia("(min-width: 1400px)").matches) enlace.click();   // actualiza la ficha lateral de Tareas
  }

  document.addEventListener("keydown", function (e) {
    if (e.ctrlKey || e.altKey || e.metaKey || escribiendo(e) || e.defaultPrevented) return;
    if (document.querySelector(".busqueda-overlay:not([hidden]), dialog[open]")) return;
    var k = e.key;
    if (esperandoG) {
      esperandoG = false; clearTimeout(temporizadorG);
      var d = DESTINOS[k.toLowerCase()];
      if (d) { e.preventDefault(); location.href = d; }
      return;
    }
    if (k === "g" && !enCorreo) { esperandoG = true; temporizadorG = setTimeout(function () { esperandoG = false; }, 1200); return; }
    if (k === "/") { var b = document.getElementById("rail-buscar"); if (b) { e.preventDefault(); b.click(); } return; }
    if (k === "[") { var t = document.querySelector(".icon-rail-toggle"); if (t) { e.preventDefault(); t.click(); } return; }
    if (enCorreo) return;                                   // Correo tiene sus propios atajos (j, k, u, e, #)
    if (k === "n") { e.preventDefault(); location.href = "/tareas/?nueva=1"; return; }
    if (k === "c") { e.preventDefault(); location.href = "/correo/redactar"; return; }
    if (k === "j" || k === "ArrowDown") { if (filas().length) { e.preventDefault(); enfocar(indice + 1); } return; }
    if (k === "k" || k === "ArrowUp") { if (filas().length) { e.preventDefault(); enfocar(indice <= 0 ? 0 : indice - 1); } return; }
    var actual = indice >= 0 ? filas()[indice] : null;
    if (!actual) return;
    if (k === "Enter") { var a = actual.querySelector("a.cliente-fila-enlace, a.tarea-fila-titulo, a[href]"); if (a) { e.preventDefault(); a.click(); } return; }
    if (k === "x") { var ch = actual.querySelector(".tarea-check:not(:disabled)"); if (ch) { e.preventDefault(); ch.click(); } }
  });

  /* 5) Enlaza cada <label> suelto con el campo que tiene justo al lado (sin `for` ni anidado): pulsar la etiqueta enfoca el campo y el lector de pantalla lo anuncia. */
  var seq = 0;
  function enlazarEtiquetas() {
    document.querySelectorAll("label:not([for])").forEach(function (l) {
      if (l.querySelector("input, select, textarea")) return;
      var c = l.nextElementSibling;
      if (!c || !/^(INPUT|SELECT|TEXTAREA)$/.test(c.tagName) || c.type === "hidden" || c.type === "checkbox" || c.type === "radio") return;
      if (!c.id) c.id = "campo-auto-" + (++seq);
      if (!document.querySelector('label[for="' + c.id + '"]')) l.setAttribute("for", c.id);
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", enlazarEtiquetas); else enlazarEtiquetas();
})();
