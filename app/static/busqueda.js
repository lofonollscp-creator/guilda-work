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
  var cargando = document.getElementById("busqueda-cargando");
  var pie = document.getElementById("busqueda-pie");
  var iconoBoton = document.getElementById("busqueda-icono");
  var cerrarBoton = document.getElementById("busqueda-cerrar");
  if (!boton || !overlay) return;

  var sesion = null; // { token, url, indice }
  var activo = -1;
  var resultadosActuales = [];
  var temporizadorBusqueda = null;
  var temporizadorCarga = null;
  var peticionEnCurso = 0; // contador para descartar respuestas fuera de orden

  function escapeHtml(s) {
    var div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }

  // Convierte el texto _formatted que devuelve Meilisearch (con
  // <mark>...</mark> alrededor de cada coincidencia) en HTML seguro:
  // el contenido del usuario (nota/tarea/correo) puede llevar sus
  // propios símbolos < > y hay que escaparlos igual que en cualquier
  // otro sitio, sin perder las marcas de resaltado que sí son nuestras.
  function resaltarSeguro(formateado) {
    var partes = String(formateado).split(/(<mark>|<\/mark>)/);
    var html = "";
    partes.forEach(function (p) {
      if (p === "<mark>" || p === "</mark>") html += p;
      else html += escapeHtml(p);
    });
    return html;
  }

  var ETIQUETAS_TIPO = { nota: "Nota", tarea: "Tarea", mensaje: "Correo" };
  var URL_HISTORIAL = boton.dataset.urlHistorial;
  var URL_CORREO = boton.dataset.urlCorreo;

  function urlDestino(hit) {
    var base = hit.tipo === "mensaje" ? URL_CORREO : URL_HISTORIAL;
    return base + "?q=" + encodeURIComponent(hit.texto.slice(0, 60));
  }

  function actualizarIcono() {
    var hayTexto = input.value.trim().length > 0;
    iconoBoton.textContent = hayTexto ? "✕" : "🔍";
    iconoBoton.title = hayTexto ? iconoBoton.dataset.tituloLimpiar : iconoBoton.dataset.tituloBuscar;
    iconoBoton.setAttribute("aria-label", iconoBoton.title);
  }

  function limpiar() {
    lista.innerHTML = "";
    vacio.hidden = true;
    error.hidden = true;
    cargando.hidden = true;
    pie.hidden = true;
    resultadosActuales = [];
    activo = -1;
  }

  function pintar(hits, meta) {
    resultadosActuales = hits;
    activo = hits.length ? 0 : -1;
    lista.innerHTML = "";
    vacio.hidden = hits.length !== 0 || !input.value.trim();
    hits.forEach(function (hit, i) {
      var li = document.createElement("li");
      var a = document.createElement("a");
      a.href = urlDestino(hit);
      a.className = i === 0 ? "is-activo" : "";
      var formateado = (hit._formatted && hit._formatted.texto) || hit.texto || "";
      a.innerHTML =
        '<span class="busqueda-resultado-tipo">' + escapeHtml(ETIQUETAS_TIPO[hit.tipo] || hit.tipo) + "</span>" +
        '<span class="busqueda-resultado-texto">' + resaltarSeguro(formateado) + "</span>";
      li.appendChild(a);
      lista.appendChild(li);
    });
    if (meta && hits.length) {
      var total = meta.estimatedTotalHits;
      var texto = total > hits.length
        ? (total + " resultados (mostrando " + hits.length + ") · " + meta.processingTimeMs + " ms")
        : (hits.length + (hits.length === 1 ? " resultado · " : " resultados · ") + meta.processingTimeMs + " ms");
      pie.textContent = texto;
      pie.hidden = false;
    } else {
      pie.hidden = true;
    }
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
    clearTimeout(temporizadorCarga);
    if (!texto.trim()) { limpiar(); return; }
    var miPeticion = ++peticionEnCurso;
    // Meilisearch local suele responder en pocos ms -- el indicador de
    // carga solo se enseña si de verdad tarda, para no parpadear en
    // cada tecla pulsada.
    temporizadorCarga = setTimeout(function () {
      if (miPeticion === peticionEnCurso) {
        cargando.hidden = false;
        vacio.hidden = true;
        error.hidden = true;
        pie.hidden = true;
      }
    }, 250);
    var inicio = performance.now();
    conseguirSesion()
      .then(function (s) {
        return fetch(s.url + "/indexes/" + s.indice + "/search", {
          method: "POST",
          headers: { Authorization: "Bearer " + s.token, "Content-Type": "application/json" },
          body: JSON.stringify({
            q: texto,
            limit: 15,
            attributesToHighlight: ["texto"],
            highlightPreTag: "<mark>",
            highlightPostTag: "</mark>",
            attributesToCrop: ["texto"],
            cropLength: 20,
            cropMarker: "…",
          }),
        });
      })
      .then(function (r) { return r.json(); })
      .then(function (datos) {
        if (miPeticion !== peticionEnCurso) return; // llegó tarde, ya no aplica
        clearTimeout(temporizadorCarga);
        cargando.hidden = true;
        var procesamiento = typeof datos.processingTimeMs === "number" ? datos.processingTimeMs : Math.round(performance.now() - inicio);
        pintar(datos.hits || [], { estimatedTotalHits: datos.estimatedTotalHits || (datos.hits || []).length, processingTimeMs: procesamiento });
      })
      .catch(function (e) {
        if (miPeticion !== peticionEnCurso) return;
        clearTimeout(temporizadorCarga);
        mostrarError(e.message || "No se ha podido buscar ahora mismo.");
      });
  }

  function abrir() {
    overlay.hidden = false;
    input.value = "";
    actualizarIcono();
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

  cerrarBoton.addEventListener("click", cerrar);

  // Icono dinámico: lupa decorativa mientras el campo está vacío
  // (enfoca el input al pulsarlo), botón de limpiar en cuanto hay
  // texto escrito -- mismo elemento, dos funciones reales según el
  // estado, en vez de una lupa puramente decorativa sin ningún
  // comportamiento.
  iconoBoton.dataset.tituloBuscar = iconoBoton.title;
  iconoBoton.dataset.tituloLimpiar = "Limpiar búsqueda";
  iconoBoton.addEventListener("click", function () {
    if (input.value) {
      input.value = "";
      limpiar();
      actualizarIcono();
    }
    input.focus();
  });

  input.addEventListener("input", function () {
    actualizarIcono();
    clearTimeout(temporizadorBusqueda);
    var texto = input.value;
    temporizadorBusqueda = setTimeout(function () { buscar(texto); }, 200);
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
