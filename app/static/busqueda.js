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

  var ETIQUETAS_POR_IDIOMA = {
    es: { nota: "Notas", tarea: "Tareas", mensaje: "Correo", vencimiento_fiscal: "Fiscal", cliente_fiscal: "Clientes", preguntar: "Preguntar al asistente" },
    ca: { nota: "Notes", tarea: "Tasques", mensaje: "Correu", vencimiento_fiscal: "Fiscal", cliente_fiscal: "Clients", preguntar: "Pregunta a l'assistent" },
    en: { nota: "Notes", tarea: "Tasks", mensaje: "Email", vencimiento_fiscal: "Tax", cliente_fiscal: "Clients", preguntar: "Ask the assistant" },
    fr: { nota: "Notes", tarea: "Tâches", mensaje: "E-mail", vencimiento_fiscal: "Fiscal", cliente_fiscal: "Clients", preguntar: "Demander à l'assistant" },
  };
  var ETIQUETAS_TIPO = ETIQUETAS_POR_IDIOMA[document.documentElement.lang] || ETIQUETAS_POR_IDIOMA.es;
  // Comandos de la paleta: «Ir a…» sale del propio menú lateral (así respeta idioma, permisos y módulos activos); las acciones son fijas.
  var TXT_COMANDOS = {
    es: { ir: "Ir a", acciones: "Acciones", nueva_tarea: "Nueva tarea", nueva_nota: "Nueva nota", redactar: "Redactar correo", nuevo_cliente: "Nuevo cliente", tema: "Cambiar tema (sistema · claro · oscuro)", atajos: "Ver atajos de teclado", plegar: "Plegar o desplegar el menú lateral", tema_ahora: "Tema" },
    ca: { ir: "Anar a", acciones: "Accions", nueva_tarea: "Nova tasca", nueva_nota: "Nova nota", redactar: "Redactar correu", nuevo_cliente: "Nou client", tema: "Canviar tema (sistema · clar · fosc)", atajos: "Veure dreceres de teclat", plegar: "Plegar o desplegar el menú lateral", tema_ahora: "Tema" },
    en: { ir: "Go to", acciones: "Actions", nueva_tarea: "New task", nueva_nota: "New note", redactar: "Write email", nuevo_cliente: "New client", tema: "Change theme (system · light · dark)", atajos: "Show keyboard shortcuts", plegar: "Collapse or expand the side menu", tema_ahora: "Theme" },
    fr: { ir: "Aller à", acciones: "Actions", nueva_tarea: "Nouvelle tâche", nueva_nota: "Nouvelle note", redactar: "Écrire un e-mail", nuevo_cliente: "Nouveau client", tema: "Changer de thème (système · clair · sombre)", atajos: "Voir les raccourcis clavier", plegar: "Replier ou déplier le menu latéral", tema_ahora: "Thème" },
  };
  var TC = TXT_COMANDOS[document.documentElement.lang] || TXT_COMANDOS.es;

  function normalizar(t) { return String(t || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").trim(); }

  function comandosDeNavegacion() {
    var vistos = {}, res = [];
    document.querySelectorAll("#rail-principal a[href], .icon-rail a[href]").forEach(function (a) {
      var href = a.getAttribute("href");
      if (!href || a.classList.contains("icon-rail-brand") || href.charAt(0) !== "/" || /logout|salir|apagar|ver-como|#/.test(href) || vistos[href]) return;
      var et = a.querySelector(".icon-rail-etiqueta");
      var texto = ((et ? et.textContent : a.textContent) || "").replace(/\s+/g, " ").trim();
      if (!texto || texto.length > 48) return;
      var uso = a.querySelector("svg use"); var icono = uso ? (uso.getAttribute("href") || "").split("#icono-")[1] : "";
      vistos[href] = true;
      res.push({ grupo: "ir", etiqueta: TC.ir + " " + texto, buscar: normalizar(texto + " " + TC.ir), href: href, icono: icono || "arrow-right" });
    });
    return res;
  }

  function comandosDeAccion() {
    var tieneClientes = !!document.querySelector('.icon-rail a[href^="/clientes"]');
    var c = [
      { grupo: "acciones", etiqueta: TC.nueva_tarea, buscar: normalizar(TC.nueva_tarea + " crear tarea add task"), href: "/tareas/?nueva=1", icono: "plus" },
      { grupo: "acciones", etiqueta: TC.nueva_nota, buscar: normalizar(TC.nueva_nota + " crear nota add note"), href: "/notas?nueva=1", icono: "notebook-pen" },
      { grupo: "acciones", etiqueta: TC.redactar, buscar: normalizar(TC.redactar + " nuevo correo email mail compose"), href: "/correo/redactar", icono: "mail" },
    ];
    if (tieneClientes) c.push({ grupo: "acciones", etiqueta: TC.nuevo_cliente, buscar: normalizar(TC.nuevo_cliente + " crear cliente add client"), href: "/clientes/nuevo", icono: "users" });
    c.push({ grupo: "acciones", etiqueta: TC.tema, buscar: normalizar(TC.tema + " theme oscuro claro dark light"), accion: "tema", icono: "moon" });
    c.push({ grupo: "acciones", etiqueta: TC.atajos, buscar: normalizar(TC.atajos + " ayuda help shortcuts"), accion: "atajos", icono: "zap" });
    c.push({ grupo: "acciones", etiqueta: TC.plegar, buscar: normalizar(TC.plegar + " sidebar menu"), accion: "plegar", icono: "panel-left" });
    return c;
  }

  var COMANDOS = null;
  function comandos() { return COMANDOS || (COMANDOS = comandosDeAccion().concat(comandosDeNavegacion())); }

  function comandosParaTexto(texto) {
    var todos = comandos();
    var q = normalizar(texto);
    if (!q) return todos.filter(function (c) { return c.grupo === "acciones"; }).slice(0, 5).concat(todos.filter(function (c) { return c.grupo === "ir"; }).slice(0, 8));
    var palabras = q.split(/\s+/);
    return todos.filter(function (c) { return palabras.every(function (p) { return c.buscar.indexOf(p) !== -1; }); }).slice(0, 7);
  }

  function ejecutarAccion(nombre) {
    cerrar();
    if (nombre === "atajos") { var b = document.getElementById("atajos-ayuda-abrir"); if (b) b.click(); }
    else if (nombre === "plegar") { var t = document.querySelector(".icon-rail-toggle"); if (t) t.click(); }
    else if (nombre === "tema") {
      var orden = ["system", "light", "dark"], actual = "system";
      try { actual = localStorage.getItem("guilda-work-tema") || "system"; } catch (e) { /* sin almacenamiento */ }
      var sig = orden[(orden.indexOf(actual) + 1) % 3];
      try { localStorage.setItem("guilda-work-tema", sig); } catch (e) { /* sin almacenamiento */ }
      if (sig === "system") document.documentElement.removeAttribute("data-theme"); else document.documentElement.dataset.theme = sig;
    }
  }

  function pintarComandos(texto) {
    var cmds = comandosParaTexto(texto), grupo = null;
    cmds.forEach(function (c) {
      if (c.grupo !== grupo) {
        grupo = c.grupo;
        var cab = document.createElement("li"); cab.className = "busqueda-grupo"; cab.setAttribute("role", "presentation");
        cab.textContent = grupo === "ir" ? TC.ir : TC.acciones; lista.appendChild(cab);
      }
      var li = document.createElement("li"), a = document.createElement("a");
      a.href = c.href || "#"; a.className = "busqueda-comando";
      if (c.accion) a.dataset.accion = c.accion;
      a.innerHTML = '<span class="busqueda-icono-tipo"><svg aria-hidden="true"><use href="' + URL_ICONOS + '#icono-' + escapeHtml(c.icono) + '"></use></svg></span><span class="busqueda-resultado-texto">' + escapeHtml(c.etiqueta) + "</span>";
      li.appendChild(a); lista.appendChild(li);
    });
  }

  function pintarSoloComandos() {
    lista.innerHTML = "";
    pintarComandos("");
    resultadosActuales = Array.prototype.slice.call(lista.querySelectorAll("a"));
    activo = resultadosActuales.length ? 0 : -1;
    marcarActivo();
  }
  var ICONO_TIPO = { nota: "notebook-pen", tarea: "list-checks", mensaje: "mail", vencimiento_fiscal: "calendar-days", cliente_fiscal: "briefcase" };
  var filtroTipo = "";                 // "" = todo
  var hitsCrudos = [];
  var URL_HISTORIAL = boton.dataset.urlHistorial;
  var URL_CORREO = boton.dataset.urlCorreo;
  var URL_FISCAL_VENCIMIENTO = boton.dataset.urlFiscalVencimiento;
  var URL_FISCAL_CLIENTE = boton.dataset.urlFiscalCliente;

  // vencimiento_fiscal/cliente_fiscal enlazan directo a su ficha (el id
  // real va tras el último guion del id del documento, ej.
  // "vencimiento_fiscal-42" -> 42) -- a diferencia de nota/tarea/mensaje,
  // que no tienen una página propia y por eso enlazan a una búsqueda de
  // texto en historial/correo.
  // Sustituye el segmento "0" (id de relleno usado al generar la URL
  // base con url_for, ver base.html) por el id real del resultado.
  function sustituirIdEnRuta(urlBase, idReal) {
    return urlBase.split("/").map(function (seg) {
      return seg === "0" ? String(idReal) : seg;
    }).join("/");
  }

  function urlDestino(hit) {
    var idReal = hit.id.split("-").pop();
    if (hit.tipo === "vencimiento_fiscal") return sustituirIdEnRuta(URL_FISCAL_VENCIMIENTO, idReal);
    if (hit.tipo === "cliente_fiscal") return sustituirIdEnRuta(URL_FISCAL_CLIENTE, idReal);
    var base = hit.tipo === "mensaje" ? URL_CORREO : URL_HISTORIAL;
    return base + "?q=" + encodeURIComponent(hit.texto.slice(0, 60));
  }

  var URL_ICONOS = document.body.dataset.urlIconos;

  function actualizarIcono() {
    var hayTexto = input.value.trim().length > 0;
    var use = iconoBoton.querySelector("use");
    if (use) use.setAttribute("href", URL_ICONOS + (hayTexto ? "#icono-x" : "#icono-search"));
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

  function resaltar(formateado) { return resaltarSeguro(formateado); }

  function pintar(hits, meta) {
    hitsCrudos = hits;
    var visibles = filtroTipo ? hits.filter(function (h) { return h.tipo === filtroTipo; }) : hits;
    resultadosActuales = visibles;
    lista.innerHTML = "";
    var texto = input.value.trim();
    vacio.hidden = visibles.length !== 0 || !texto;
    // «Preguntar al asistente» es siempre la primera acción cuando hay texto.
    if (texto) {
      var li0 = document.createElement("li");
      var ia = document.createElement("a");
      ia.href = "/ia/?q=" + encodeURIComponent(texto);
      ia.className = "busqueda-fila-ia is-activo";
      ia.innerHTML = '<span class="busqueda-icono-tipo busqueda-icono-ia"><svg aria-hidden="true"><use href="' + URL_ICONOS + '#icono-sparkles"></use></svg></span>' +
        '<span class="busqueda-resultado-texto">' + escapeHtml(ETIQUETAS_TIPO.preguntar) + ': «' + escapeHtml(texto) + '»</span><kbd>Intro</kbd>';
      li0.appendChild(ia);
      lista.appendChild(li0);
    }
    activo = texto ? 0 : (visibles.length ? 0 : -1);
    if (texto) pintarComandos(texto);
    var grupoActual = null;
    visibles.forEach(function (hit, i) {
      if (hit.tipo !== grupoActual) {
        grupoActual = hit.tipo;
        var cab = document.createElement("li");
        cab.className = "busqueda-grupo";
        cab.setAttribute("role", "presentation");
        cab.textContent = ETIQUETAS_TIPO[hit.tipo] || hit.tipo;
        lista.appendChild(cab);
      }
      var li = document.createElement("li");
      var a = document.createElement("a");
      a.href = urlDestino(hit);
      var formateado = (hit._formatted && hit._formatted.texto) || hit.texto || "";
      a.innerHTML =
        '<span class="busqueda-icono-tipo"><svg aria-hidden="true"><use href="' + URL_ICONOS + '#icono-' + (ICONO_TIPO[hit.tipo] || "search") + '"></use></svg></span>' +
        '<span class="busqueda-resultado-texto">' + resaltar(formateado) + "</span>";
      li.appendChild(a);
      lista.appendChild(li);
    });
    // la lista de enlaces incluye ahora la fila de la IA: se navega sobre todos
    resultadosActuales = Array.prototype.slice.call(lista.querySelectorAll("a"));
    if (meta && visibles.length) {
      var total = meta.estimatedTotalHits;
      var txt = total > visibles.length
        ? (total + " resultados (mostrando " + visibles.length + ") · " + meta.processingTimeMs + " ms")
        : (visibles.length + (visibles.length === 1 ? " resultado · " : " resultados · ") + meta.processingTimeMs + " ms");
      pie.textContent = txt;
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
    pintar([], null);                      // sin buscador, «Preguntar al asistente» sigue ahí
    vacio.hidden = true;
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
    if (!texto.trim()) { limpiar(); pintarSoloComandos(); return; }
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
    pintarSoloComandos();
    setTimeout(function () { input.focus(); }, 0);
  }

  function cerrar() {
    overlay.hidden = true;
  }

  boton.addEventListener("click", abrir);

  // Chips de tipo (Todo, Tareas, Notas…): filtran lo ya buscado.
  overlay.querySelectorAll(".busqueda-filtro").forEach(function (chip) {
    chip.addEventListener("click", function () {
      filtroTipo = chip.dataset.tipo || "";
      overlay.querySelectorAll(".busqueda-filtro").forEach(function (c) { c.classList.toggle("on", c === chip); c.setAttribute("aria-pressed", c === chip ? "true" : "false"); });
      if (input.value.trim()) pintar(hitsCrudos, null);
      input.focus();
    });
  });

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
  lista.addEventListener("click", function (e) {
    var a = e.target.closest("a[data-accion]");
    if (a) { e.preventDefault(); ejecutarAccion(a.dataset.accion); }
  });

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
      pintarSoloComandos();
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
      if (enlaces[activo]) {
        if (enlaces[activo].dataset.accion) { e.preventDefault(); ejecutarAccion(enlaces[activo].dataset.accion); }
        else window.location.href = enlaces[activo].getAttribute("href");
      }
    }
  });
})();
