// Buscador global (Ctrl/Cmd+K) sobre notas/tareas/correo — llama a
// Meilisearch DIRECTAMENTE con un tenant token (nunca pasa por Flask
// más que para pedir el token en sí, ver /api/v1/busqueda/token), mismo
// patrón estándar de tenant tokens que ya usa la documentación para
// desarrolladores (app/static/docs.js), pero aquí contra datos reales
// del usuario en vez de contenido estático.

(function () {
  var boton = document.getElementById("busqueda-abrir");
  var overlay = document.getElementById("busqueda-overlay");
  var input = document.getElementById("busqueda-input");
  var lista = document.getElementById("busqueda-resultados");
  var vacio = document.getElementById("busqueda-vacio");
  var error = document.getElementById("busqueda-error");
  if (!boton || !overlay) return;

  var sesion = null; // { token, url, indice }
  var activo = -1;
  var resultadosActuales = [];
  var temporizador = null;

  var ETIQUETAS_TIPO = { nota: "Nota", tarea: "Tarea", mensaje: "Correo" };
  var URL_HISTORIAL = boton.dataset.urlHistorial;
  var URL_CORREO = boton.dataset.urlCorreo;

  function urlDestino(hit) {
    var base = hit.tipo === "mensaje" ? URL_CORREO : URL_HISTORIAL;
    return base + "?q=" + encodeURIComponent(hit.texto.slice(0, 60));
  }

  function limpiar() {
    lista.innerHTML = "";
    vacio.hidden = true;
    error.hidden = true;
    resultadosActuales = [];
    activo = -1;
  }

  function pintar(hits) {
    resultadosActuales = hits;
    activo = hits.length ? 0 : -1;
    lista.innerHTML = "";
    vacio.hidden = hits.length !== 0 || !input.value.trim();
    hits.forEach(function (hit, i) {
      var li = document.createElement("li");
      var a = document.createElement("a");
      a.href = urlDestino(hit);
      a.className = i === 0 ? "is-activo" : "";
      var texto = hit.texto || "";
      a.innerHTML =
        '<span class="busqueda-resultado-tipo">' + (ETIQUETAS_TIPO[hit.tipo] || hit.tipo) + "</span>" +
        '<span class="busqueda-resultado-texto">' + texto.slice(0, 140) + "</span>";
      li.appendChild(a);
      lista.appendChild(li);
    });
  }

  function marcarActivo() {
    var enlaces = lista.querySelectorAll("a");
    enlaces.forEach(function (a, i) { a.classList.toggle("is-activo", i === activo); });
    if (enlaces[activo]) enlaces[activo].scrollIntoView({ block: "nearest" });
  }

  function mostrarError(mensaje) {
    limpiar();
    error.hidden = false;
    error.textContent = mensaje;
  }

  function conseguirSesion() {
    if (sesion) return Promise.resolve(sesion);
    return fetch("/busqueda/token", { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (datos) {
        if (!datos.ok) throw new Error(datos.error || "Buscador no disponible.");
        sesion = { token: datos.token, url: datos.url, indice: datos.indice };
        return sesion;
      });
  }

  function buscar(texto) {
    if (!texto.trim()) { limpiar(); return; }
    conseguirSesion()
      .then(function (s) {
        return fetch(s.url + "/indexes/" + s.indice + "/search", {
          method: "POST",
          headers: { Authorization: "Bearer " + s.token, "Content-Type": "application/json" },
          body: JSON.stringify({ q: texto, limit: 15 }),
        });
      })
      .then(function (r) { return r.json(); })
      .then(function (datos) { pintar(datos.hits || []); })
      .catch(function (e) { mostrarError(e.message || "No se ha podido buscar ahora mismo."); });
  }

  function abrir() {
    overlay.hidden = false;
    input.value = "";
    limpiar();
    setTimeout(function () { input.focus(); }, 0);
  }

  function cerrar() {
    overlay.hidden = true;
  }

  boton.addEventListener("click", abrir);

  document.addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      overlay.hidden ? abrir() : cerrar();
    }
  });

  overlay.addEventListener("click", function (e) {
    if (e.target === overlay) cerrar();
  });

  input.addEventListener("input", function () {
    clearTimeout(temporizador);
    var texto = input.value;
    temporizador = setTimeout(function () { buscar(texto); }, 200);
  });

  input.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      cerrar();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      if (resultadosActuales.length) { activo = (activo + 1) % resultadosActuales.length; marcarActivo(); }
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (resultadosActuales.length) { activo = (activo - 1 + resultadosActuales.length) % resultadosActuales.length; marcarActivo(); }
    } else if (e.key === "Enter") {
      var enlaces = lista.querySelectorAll("a");
      if (enlaces[activo]) window.location.href = enlaces[activo].getAttribute("href");
    }
  });
})();
