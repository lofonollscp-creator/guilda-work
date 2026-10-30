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
      var actual = raiz.dataset.preferencia || "sistema";                      // sistema → claro → oscuro → sistema
      var nuevo = actual === "sistema" ? "claro" : (actual === "claro" ? "oscuro" : "sistema");
      raiz.dataset.preferencia = nuevo;
      if (nuevo === "sistema") { delete raiz.dataset.tema; } else { raiz.dataset.tema = nuevo; }
      guardar("bo-tema", nuevo);
      el.title = "Tema: " + nuevo + " (clic para cambiar)";
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

  // Paleta de búsqueda global (Ctrl+K / "/" fuera de un campo): páginas, tenants y usuarios.
  var paleta = document.getElementById("paleta");
  if (paleta) {
    var campo = document.getElementById("paleta-q"), lista = document.getElementById("paleta-lista");
    var items = [], activo = 0, temporizador = null, ultima = 0;

    function pintar() {
      lista.textContent = "";
      items.forEach(function (it, i) {
        var li = document.createElement("li");
        li.setAttribute("role", "option");
        li.className = i === activo ? "activa" : "";
        var tipo = document.createElement("span"); tipo.className = "paleta-tipo"; tipo.textContent = it.tipo;
        var titulo = document.createElement("strong"); titulo.textContent = it.titulo;
        li.appendChild(tipo); li.appendChild(titulo);
        if (it.detalle) { var d = document.createElement("span"); d.className = "muted"; d.textContent = it.detalle; li.appendChild(d); }
        li.addEventListener("mousedown", function (e) { e.preventDefault(); window.location.href = it.url; });
        lista.appendChild(li);
      });
      if (!items.length) { var vacio = document.createElement("li"); vacio.className = "muted"; vacio.textContent = "Sin resultados"; lista.appendChild(vacio); }
    }
    function buscar() {
      var q = campo.value, marca = ++ultima;
      fetch(paleta.dataset.url + "?q=" + encodeURIComponent(q), { credentials: "same-origin", headers: { Accept: "application/json" } })
        .then(function (r) { return r.ok ? r.json() : { resultados: [] }; })
        .then(function (r) { if (marca !== ultima) return; items = r.resultados || []; activo = 0; pintar(); })
        .catch(function () { /* sin red: se deja la lista como estaba */ });
    }
    function abrirPaleta() { if (!paleta.open) paleta.showModal(); campo.value = ""; buscar(); campo.focus(); }

    campo.addEventListener("input", function () { clearTimeout(temporizador); temporizador = setTimeout(buscar, 150); });
    campo.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown") { e.preventDefault(); activo = Math.min(activo + 1, items.length - 1); pintar(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); activo = Math.max(activo - 1, 0); pintar(); }
      else if (e.key === "Enter" && items[activo]) { e.preventDefault(); window.location.href = items[activo].url; }
    });
    document.addEventListener("keydown", function (e) {
      var escribiendo = /^(INPUT|TEXTAREA|SELECT)$/.test((e.target.tagName || "")) || e.target.isContentEditable;
      if ((e.key === "k" || e.key === "K") && (e.ctrlKey || e.metaKey)) { e.preventDefault(); abrirPaleta(); }
      else if (e.key === "/" && !escribiendo && !e.ctrlKey && !e.metaKey) { e.preventDefault(); abrirPaleta(); }
    });
    document.addEventListener("click", function (e) { if (e.target.closest('[data-accion="paleta"]')) abrirPaleta(); });
  }
})();
