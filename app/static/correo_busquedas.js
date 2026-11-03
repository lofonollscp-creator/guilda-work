/* Bandeja de correo: búsquedas guardadas. Guarda el texto de la caja de búsqueda (con sus operadores: de:ana asunto:factura adjunto:…) con un nombre y lo vuelve a lanzar con un clic.
   Se guardan en este navegador (localStorage), no en el servidor: son un atajo personal, no una vista compartida. Si el navegador no deja guardar, el resto de la búsqueda sigue funcionando. */
(function () {
  "use strict";
  var caja = document.querySelector(".correo-lista-toolbar input[name='q']");
  if (!caja) return;
  var CLAVE = "guilda.correo.busquedas";
  var d = caja.form.dataset;
  var textos = { correoBusquedasTitulo: d.tBusquedas, correoBusquedasGuardar: d.tGuardarBusqueda, correoBusquedasNombre: d.tNombreBusqueda, correoBusquedasVacio: d.tSinBusquedas, correoBusquedasQuitar: d.tQuitar };

  function leer() {
    try {
      var v = JSON.parse(localStorage.getItem(CLAVE) || "[]");
      return Array.isArray(v) ? v.filter(function (b) { return b && typeof b.nombre === "string" && typeof b.q === "string"; }) : [];
    } catch (e) { return []; }
  }
  function guardar(lista) {
    try { localStorage.setItem(CLAVE, JSON.stringify(lista.slice(0, 20))); return true; } catch (e) { return false; }
  }

  var boton = document.createElement("button");
  boton.type = "button";
  boton.className = "btn btn-ghost correo-busquedas-boton";
  boton.textContent = "★ " + (textos.correoBusquedasTitulo || "Búsquedas");
  boton.setAttribute("aria-expanded", "false");
  var panel = document.createElement("div");
  panel.className = "correo-busquedas-panel";
  panel.hidden = true;
  caja.insertAdjacentElement("afterend", boton);
  boton.insertAdjacentElement("afterend", panel);

  function pintar() {
    panel.textContent = "";
    var lista = leer();
    var guardarEsta = document.createElement("button");
    guardarEsta.type = "button";
    guardarEsta.className = "btn btn-primary correo-busquedas-guardar";
    guardarEsta.textContent = textos.correoBusquedasGuardar || "Guardar esta búsqueda";
    guardarEsta.disabled = !caja.value.trim();
    guardarEsta.addEventListener("click", function () {
      var q = caja.value.trim();
      if (!q) return;
      var pedir = window.GuildaDS ? window.GuildaDS.pedirTexto(textos.correoBusquedasNombre || "Nombre de la búsqueda", q.slice(0, 40)) : Promise.resolve(window.prompt(textos.correoBusquedasNombre || "Nombre de la búsqueda", q.slice(0, 40)));
      Promise.resolve(pedir).then(function (nombre) {
        nombre = (nombre || "").trim().slice(0, 60);
        if (!nombre) return;
        var otras = leer().filter(function (b) { return b.nombre !== nombre; });
        otras.unshift({ nombre: nombre, q: q });
        guardar(otras);
        pintar();
      });
    });
    panel.appendChild(guardarEsta);
    if (!lista.length) {
      var vacio = document.createElement("p");
      vacio.className = "muted";
      vacio.textContent = textos.correoBusquedasVacio || "Aún no has guardado ninguna búsqueda.";
      panel.appendChild(vacio);
      return;
    }
    var ul = document.createElement("ul");
    ul.className = "correo-busquedas-lista";
    lista.forEach(function (b) {
      var li = document.createElement("li");
      var ir = document.createElement("button");
      ir.type = "button";
      ir.className = "correo-busquedas-ir";
      ir.textContent = b.nombre;
      ir.title = b.q;
      ir.addEventListener("click", function () { caja.value = b.q; caja.form.requestSubmit(); });
      var quitar = document.createElement("button");
      quitar.type = "button";
      quitar.className = "correo-busquedas-quitar";
      quitar.textContent = "×";
      quitar.setAttribute("aria-label", (textos.correoBusquedasQuitar || "Quitar") + ": " + b.nombre);
      quitar.addEventListener("click", function () { guardar(leer().filter(function (x) { return x.nombre !== b.nombre; })); pintar(); });
      li.appendChild(ir); li.appendChild(quitar);
      ul.appendChild(li);
    });
    panel.appendChild(ul);
  }

  boton.addEventListener("click", function () {
    panel.hidden = !panel.hidden;
    boton.setAttribute("aria-expanded", panel.hidden ? "false" : "true");
    if (!panel.hidden) pintar();
  });
  caja.addEventListener("input", function () { var g = panel.querySelector(".correo-busquedas-guardar"); if (g) g.disabled = !caja.value.trim(); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !panel.hidden) { panel.hidden = true; boton.setAttribute("aria-expanded", "false"); } });
})();
