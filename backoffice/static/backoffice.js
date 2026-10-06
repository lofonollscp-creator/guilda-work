// Interacciones del backoffice (sin JS en línea: la CSP solo permite scripts propios).
(function () {
  "use strict";
  var raiz = document.documentElement;

  function guardar(clave, valor) { try { localStorage.setItem(clave, valor); } catch (e) { /* sin almacenamiento */ } }

  document.addEventListener("click", function (e) {
    var el = e.target.closest("[data-accion], [data-abrir], [data-cerrar], [data-copiar], [data-confirmar]");
    if (!el) return;

    if (el.dataset.confirmar && !window.confirm(el.dataset.confirmar)) { e.preventDefault(); return; }

    if (el.dataset.accion === "tema") {
      var nuevo = raiz.dataset.tema === "claro" ? "oscuro" : "claro";
      raiz.dataset.tema = nuevo;
      guardar("bo-tema", nuevo);
    } else if (el.dataset.accion === "lateral") {
      var cerrado = raiz.dataset.lateral === "cerrado";
      if (cerrado) { delete raiz.dataset.lateral; } else { raiz.dataset.lateral = "cerrado"; }
      guardar("bo-lateral", cerrado ? "abierto" : "cerrado");
    } else if (el.dataset.abrir) {
      var dialogo = document.getElementById(el.dataset.abrir);
      if (dialogo && dialogo.showModal) { dialogo.showModal(); var campo = dialogo.querySelector("input:not([type=hidden]), select"); if (campo) campo.focus(); }
    } else if (el.hasAttribute("data-cerrar")) {
      var padre = el.closest("dialog");
      if (padre) padre.close();
    } else if (el.dataset.copiar) {
      var origen = document.getElementById(el.dataset.copiar);
      if (origen && navigator.clipboard) {
        navigator.clipboard.writeText(origen.textContent.trim()).then(function () {
          var texto = el.textContent; el.textContent = "¡Copiado!";
          setTimeout(function () { el.textContent = texto; }, 1500);
        });
      }
    }
  });

  // Selectores que reenvían el formulario al cambiar (resultados por página…).
  document.querySelectorAll("[data-autoenviar]").forEach(function (sel) {
    sel.addEventListener("change", function () { if (sel.form) sel.form.submit(); });
  });

  // Cierra los desplegables de filtros al pulsar fuera de ellos.
  document.addEventListener("click", function (e) {
    document.querySelectorAll("details.desplegable[open]").forEach(function (d) { if (!d.contains(e.target)) d.removeAttribute("open"); });
  });

  // Los diálogos se cierran al pulsar sobre el fondo.
  document.querySelectorAll("dialog.dialogo").forEach(function (d) {
    d.addEventListener("click", function (e) { if (e.target === d) d.close(); });
  });

  // Los avisos desaparecen solos.
  document.querySelectorAll(".aviso-ok").forEach(function (a) { setTimeout(function () { a.classList.add("oculto"); }, 5000); });
})();
