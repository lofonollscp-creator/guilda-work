// Asistente IA: gobierna cualquier .ia-chat presente en la página (el chat
// de página completa en /ia, y/o el panel flotante de base.html). Sin SPA:
// fetch a /ia/mensaje y /ia/confirmar, actualiza el DOM con lo que devuelven.
(function () {
  // El modelo devuelve markdown básico (negrita, listas, enlaces...) pero
  // los mensajes se pintaban con textContent -- se veía "**MANGER**"
  // literal en vez de negrita (encontrado en producción). Sin ninguna
  // librería externa, a propósito (mismo criterio que el resto del
  // proyecto): escapa TODO primero (nunca confiar en el HTML del
  // modelo) y solo entonces reintroduce las etiquetas de un subconjunto
  // de markdown -- el orden importa, código en línea va primero para
  // que su contenido no se interprete como más markdown.
  function escaparHtml(texto) {
    var d = document.createElement("div");
    d.textContent = texto;
    // El truco textContent->innerHTML escapa &, < y > pero NO las comillas
    // (no son especiales dentro de un nodo de texto) -- el resultado se
    // usa luego también dentro de atributos (href="...", title="...",
    // alt="..."), así que hay que escaparlas aparte para que el modelo no
    // pueda cerrar el atributo e inyectar otro (bug real encontrado en la
    // auditoría de 2026-09-30: un enlace markdown con una comilla en la
    // URL rompía el href e inyectaba HTML).
    return d.innerHTML.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  // Detecta bloques de tabla markdown ("| a | b |" + fila separadora
  // "|---|---|") y los convierte a <table> de verdad -- si no, se veían
  // los pipes y guiones tal cual (encontrado en producción, ver captura
  // del chat con una lista de correos en formato tabla).
  function esFilaTabla(linea) {
    return /^\s*\|.*\|\s*$/.test(linea);
  }
  function esSeparadorTabla(linea) {
    return /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(linea);
  }
  function celdasDeFila(linea) {
    var recortada = linea.trim().replace(/^\|/, "").replace(/\|$/, "");
    return recortada.split("|").map(function (c) { return c.trim(); });
  }
  function convertirTablas(html) {
    var lineas = html.split("\n");
    var salida = [];
    var i = 0;
    while (i < lineas.length) {
      if (esFilaTabla(lineas[i]) && lineas[i + 1] !== undefined && esSeparadorTabla(lineas[i + 1])) {
        var cabecera = celdasDeFila(lineas[i]);
        var filas = [];
        var j = i + 2;
        while (j < lineas.length && esFilaTabla(lineas[j])) {
          filas.push(celdasDeFila(lineas[j]));
          j++;
        }
        var tabla = '<div class="ia-tabla-wrap"><table class="ia-tabla"><thead><tr>';
        cabecera.forEach(function (c) { tabla += "<th>" + c + "</th>"; });
        tabla += "</tr></thead><tbody>";
        filas.forEach(function (fila) {
          tabla += "<tr>";
          fila.forEach(function (c) { tabla += "<td>" + c + "</td>"; });
          tabla += "</tr>";
        });
        tabla += "</tbody></table></div>";
        salida.push(tabla);
        i = j;
      } else {
        salida.push(lineas[i]);
        i++;
      }
    }
    return salida.join("\n");
  }

  function renderizarMarkdown(texto) {
    var html = escaparHtml(texto);
    html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");
    html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    html = convertirTablas(html);
    // Sin convertir "\n" a <br>: .ia-msg ya usa white-space: pre-wrap,
    // que respeta los saltos de línea tal cual -- añadir <br> aquí
    // los duplicaría. Las tablas ya son bloques propios, no les afecta.
    return html;
  }

  function iconoSvg(nombre) {
    return '<svg class="icono-inline" aria-hidden="true"><use href="/static/iconos.svg#icono-' + nombre + '"></use></svg>';
  }

  // Devuelve HTML (no texto plano) -- el llamador debe pintarlo con
  // innerHTML, nunca textContent. herramienta/datos.error se escapan
  // igual que el resto del contenido del modelo (ver escaparHtml arriba):
  // nunca confiar en texto que puede venir influido por el propio LLM.
  // Adjuntos que una tool le manda al usuario por el chat (Drive, documento
  // firmado...) -- ver mcp_tools.py:_guardar_adjunto_para_chat, siempre
  // devuelve {adjunto_id, nombre_archivo, tipo_mime}. En vez del texto
  // genérico "usó X", se pinta un chip descargable + vista previa inline
  // para imagen/PDF, mismo lenguaje visual que los adjuntos de Correo
  // (.correo-adjunto-*, ver app/templates/correo_bandeja.html) con sus
  // propias clases .ia-adjunto-* para no acoplar los dos módulos.
  function chipAdjuntoTool(datos) {
    var url = "/ia/adjuntos/" + encodeURIComponent(datos.adjunto_id);
    var nombre = escaparHtml(datos.nombre_archivo || ("adjunto-" + datos.adjunto_id));
    var tipoMime = datos.tipo_mime || "";
    var html =
      '<div class="ia-adjunto">' +
      '<a class="ia-adjunto-chip" href="' + url + '" target="_blank" title="' + nombre + '">' +
      iconoSvg("paperclip") + " " + nombre + "</a>";
    if (tipoMime.indexOf("image/") === 0) {
      html += '<a href="' + url + '" target="_blank" title="Ver a tamaño completo">' +
        '<img class="ia-adjunto-preview-imagen" src="' + url + '" alt="' + nombre + '" loading="lazy"></a>';
    } else if (tipoMime === "application/pdf") {
      html += '<embed class="ia-adjunto-preview-pdf" src="' + url + '" type="application/pdf">';
    }
    html += "</div>";
    return html;
  }

  // «listar_clientes_fiscales» -> «listar clientes fiscales»
  function nombreLegible(herramienta) {
    return String(herramienta || "").replace(/_/g, " ");
  }

  // Valor de un argumento para mostrarlo a una persona (no JSON): listas con comas, objetos con sus valores, sí/no.
  function valorLegible(v) {
    if (v === null || v === undefined || v === "") return "—";
    if (typeof v === "boolean") return v ? "sí" : "no";
    if (Array.isArray(v)) return v.map(valorLegible).join(", ");
    if (typeof v === "object") return Object.keys(v).map(function (k) { return nombreLegible(k) + ": " + valorLegible(v[k]); }).join("; ");
    var t = String(v);
    return t.length > 300 ? t.slice(0, 300) + "…" : t;
  }

  // Sustituye el JSON en bruto de «¿Ejecuto…?» por una lista de «campo: valor». Nunca innerHTML con datos del modelo: solo textContent.
  function pintarArgumentos(pendienteEl, argumentos) {
    var antiguo = pendienteEl.querySelector(".ia-chat-pendiente-args");
    if (!antiguo) return;
    if (typeof argumentos === "string") {
      try { argumentos = JSON.parse(argumentos.replace(/'/g, '"').replace(/\bNone\b/g, "null").replace(/\bTrue\b/g, "true").replace(/\bFalse\b/g, "false")); } catch (e) { /* se deja como texto */ }
    }
    var lista = document.createElement("dl");
    lista.className = "ia-chat-pendiente-args";
    if (argumentos && typeof argumentos === "object" && !Array.isArray(argumentos) && Object.keys(argumentos).length) {
      Object.keys(argumentos).forEach(function (k) {
        var dt = document.createElement("dt"); dt.textContent = nombreLegible(k);
        var dd = document.createElement("dd"); dd.textContent = valorLegible(argumentos[k]);
        lista.appendChild(dt); lista.appendChild(dd);
      });
    } else if (typeof argumentos === "string" && argumentos.trim() && argumentos.trim() !== "{}") {
      var dd0 = document.createElement("dd"); dd0.textContent = argumentos; lista.appendChild(dd0);
    } else {                                              // sin parámetros: no hay nada que enseñar
      antiguo.remove();
      return;
    }
    antiguo.replaceWith(lista);
  }

  // Varias llamadas seguidas a la misma herramienta se muestran como una sola línea con «×N».
  function agruparHerramientas(contenedor) {
    var previo = null, n = 0;
    contenedor.querySelectorAll(".ia-msg-tool").forEach(function (el) {
      var misma = previo && !el.querySelector(".ia-adjunto") && el.dataset.herramienta && previo.dataset.herramienta === el.dataset.herramienta && el.dataset.agrupado !== "1";
      if (misma) {
        n += 1;
        el.hidden = true; el.dataset.agrupado = "1";
        var marca = previo.querySelector(".ia-tool-n");
        if (!marca) { marca = document.createElement("span"); marca.className = "ia-tool-n"; previo.appendChild(marca); }
        marca.textContent = " ×" + (n + 1);
      } else if (el.dataset.agrupado !== "1") { previo = el; n = 0; }
    });
  }

  function textoMensajeTool(herramienta, contenidoJson) {
    var icono = iconoSvg("wrench");
    var texto = escaparHtml(nombreLegible(herramienta));
    try {
      var datos = JSON.parse(contenidoJson || "{}");
      if (datos && datos.error) {
        icono = iconoSvg("triangle-alert");
        texto = escaparHtml(nombreLegible(herramienta)) + ": " + escaparHtml(datos.error);
      } else if (datos && datos.rechazado) {
        icono = iconoSvg("x");
        texto = escaparHtml(nombreLegible(herramienta)) + " (rechazada)";
      } else if (datos && datos.adjunto_id) {
        return chipAdjuntoTool(datos);
      }
    } catch (e) {
      // contenido no era JSON válido: se deja el texto por defecto
    }
    return icono + " usó " + texto;
  }

  // Idioma de interfaz -> BCP-47 completo, para que STT/TTS elijan una voz
  // razonable (el atributo lang="es"/"ca"/"en"/"fr" del <html>, ver
  // base.html, funciona pero un código completo da mejores resultados en
  // más navegadores).
  var LOCALE_VOZ = { es: "es-ES", ca: "ca-ES", en: "en-US", fr: "fr-FR" };

  // Fuentes citadas bajo la burbuja del asistente: enlaces internos (solo
  // rutas que empiezan por "/"), creados con textContent/href, nunca con innerHTML.
  function pintarFuentes(burbuja, fuentes) {
    if (!burbuja || !fuentes || !fuentes.length) return;
    var validas = fuentes.filter(function (f) { return f && typeof f.url === "string" && f.url.charAt(0) === "/" && f.url.charAt(1) !== "/"; });
    if (!validas.length) return;
    var caja = document.createElement("details");
    caja.className = "ia-fuentes";
    var resumen = document.createElement("summary");
    resumen.className = "ia-fuentes-etiqueta";
    resumen.textContent = (TXT[document.documentElement.lang] || TXT.es).fuentes(validas.length);
    caja.appendChild(resumen);
    validas.forEach(function (f) {
      var a = document.createElement("a");
      a.className = "ia-fuente ia-fuente-" + String(f.tipo || "").replace(/[^a-z]/g, "");
      a.href = f.url;
      a.textContent = String(f.titulo || f.url);
      caja.appendChild(a);
    });
    pieDe(burbuja).appendChild(caja);
  }

  // Textos de lo nuevo (el resto de la interfaz va en el HTML; esto se pinta desde JavaScript).
  var TXT = {
    es: { fuentes: function (n) { return n === 1 ? "1 fuente" : n + " fuentes"; }, cautela: "Cifra estimada: compruébala antes de presentar", copiar: "Copiar", copiado: "Copiado", leer: "Leer en voz alta",
          ejecuto: "Voy a hacer esto. ¿Lo confirmo?", si: "Sí, hazlo", no: "No", pasos: "Consultando…",
          acciones: { crear_tarea: "Nueva tarea", crear_nota: "Nueva nota", editar_tarea: "Cambiar una tarea", editar_nota: "Cambiar una nota", completar_tarea: "Completar una tarea", enviar_correo: "Enviar un correo" } },
    ca: { fuentes: function (n) { return n === 1 ? "1 font" : n + " fonts"; }, cautela: "Xifra estimada: comprova-la abans de presentar", copiar: "Copia", copiado: "Copiat", leer: "Llegeix en veu alta",
          ejecuto: "Faré això. Ho confirmo?", si: "Sí, fes-ho", no: "No", pasos: "Consultant…",
          acciones: { crear_tarea: "Nova tasca", crear_nota: "Nova nota", editar_tarea: "Canviar una tasca", editar_nota: "Canviar una nota", completar_tarea: "Completar una tasca", enviar_correo: "Enviar un correu" } },
    en: { fuentes: function (n) { return n === 1 ? "1 source" : n + " sources"; }, cautela: "Estimated figure: check it before filing", copiar: "Copy", copiado: "Copied", leer: "Read aloud",
          ejecuto: "I'm about to do this. Shall I go ahead?", si: "Yes, do it", no: "No", pasos: "Looking it up…",
          acciones: { crear_tarea: "New task", crear_nota: "New note", editar_tarea: "Change a task", editar_nota: "Change a note", completar_tarea: "Complete a task", enviar_correo: "Send an email" } },
    fr: { fuentes: function (n) { return n === 1 ? "1 source" : n + " sources"; }, cautela: "Chiffre estimé : vérifiez-le avant de déclarer", copiar: "Copier", copiado: "Copié", leer: "Lire à voix haute",
          ejecuto: "Je vais faire ceci. Je confirme ?", si: "Oui, fais-le", no: "Non", pasos: "Consultation…",
          acciones: { crear_tarea: "Nouvelle tâche", crear_nota: "Nouvelle note", editar_tarea: "Modifier une tâche", editar_nota: "Modifier une note", completar_tarea: "Terminer une tâche", enviar_correo: "Envoyer un e-mail" } },
  };
  function t() { return TXT[document.documentElement.lang] || TXT.es; }
  function nombreAccion(herramienta) { var a = t().acciones[herramienta]; return a || nombreLegible(herramienta); }

  // La etiqueta de cautela solo acompaña a respuestas con importes o plazos fiscales, y se puede silenciar (localStorage).
  var CLAVE_CAUTELA = "guilda-ia-recordar-cifras";
  function cautelaActiva() { try { return localStorage.getItem(CLAVE_CAUTELA) !== "0"; } catch (e) { return true; } }
  function hablaDeCifras(texto) { return /\d[\d.,]*\s?€|€\s?\d|\b(modelo|IVA|IRPF|303|130|111|115|390|200)\b/i.test(texto || ""); }

  // El pie de una respuesta (cautela, fuentes plegadas, acciones) vive en un contenedor justo debajo de su burbuja.
  function pieDe(burbuja) {
    var p = burbuja.nextElementSibling;
    if (!p || !p.classList.contains("ia-msg-pie")) {
      p = document.createElement("div");
      p.className = "ia-msg-pie";
      burbuja.insertAdjacentElement("afterend", p);
    }
    return p;
  }
  function pintarCautela(burbuja, texto) {
    if (!cautelaActiva() || !hablaDeCifras(texto)) return;
    var pie = pieDe(burbuja);
    if (pie.querySelector(".ia-cautela")) return;
    var c = document.createElement("p");
    c.className = "ia-cautela";
    c.innerHTML = iconoSvg("info");
    c.appendChild(document.createTextNode(" " + t().cautela));
    pie.insertBefore(c, pie.firstChild);
  }
  // Copiar y leer en voz alta, solo bajo la última respuesta.
  function pintarAcciones(mensajesEl) {
    mensajesEl.querySelectorAll(".ia-msg-acciones").forEach(function (a) { a.remove(); });
    var respuestas = mensajesEl.querySelectorAll(".ia-msg-assistant:not(.chat-pensando)");
    var ultima = respuestas[respuestas.length - 1];
    if (!ultima || !ultima.textContent.trim()) return;
    var caja = document.createElement("div");
    caja.className = "ia-msg-acciones";
    var copiar = document.createElement("button");
    copiar.type = "button"; copiar.className = "ia-msg-accion"; copiar.title = t().copiar; copiar.setAttribute("aria-label", t().copiar);
    copiar.innerHTML = iconoSvg("copy");
    copiar.addEventListener("click", function () {
      if (navigator.clipboard) navigator.clipboard.writeText(ultima.textContent.trim());
      copiar.title = t().copiado; copiar.setAttribute("aria-label", t().copiado);
      setTimeout(function () { copiar.title = t().copiar; copiar.setAttribute("aria-label", t().copiar); }, 1500);
    });
    caja.appendChild(copiar);
    if ("speechSynthesis" in window) {
      var leer = document.createElement("button");
      leer.type = "button"; leer.className = "ia-msg-accion"; leer.title = t().leer; leer.setAttribute("aria-label", t().leer);
      leer.innerHTML = iconoSvg("volume-2");
      leer.addEventListener("click", function () {
        window.speechSynthesis.cancel();
        var u = new SpeechSynthesisUtterance(ultima.textContent.trim());
        u.lang = LOCALE_VOZ[document.documentElement.lang] || "es-ES";
        window.speechSynthesis.speak(u);
      });
      caja.appendChild(leer);
    }
    pieDe(ultima).appendChild(caja);
  }
  // El panel de la derecha enseña las fuentes de la última respuesta.
  function actualizarPanelFuentes(mensajesEl) {
    var lado = document.getElementById("ia-lado-fuentes");
    if (!lado) return;
    var cajas = mensajesEl.querySelectorAll(".ia-fuentes");
    var ultima = cajas[cajas.length - 1];
    var lista = lado.querySelector(".ia-lado-fuentes-lista");
    lista.innerHTML = "";
    var enlaces = ultima ? ultima.querySelectorAll("a.ia-fuente") : [];
    enlaces.forEach(function (a) {
      var li = document.createElement("li");
      var copia = document.createElement("a");
      copia.href = a.getAttribute("href");
      copia.textContent = a.textContent;
      li.appendChild(copia);
      lista.appendChild(li);
    });
    lado.hidden = enlaces.length === 0;
  }

  function iniciarChat(contenedor) {
    var id = contenedor.id;
    var mensajesEl = document.getElementById(id + "-mensajes");
    var pendienteEl = document.getElementById(id + "-pendiente");
    var formEl = document.getElementById(id + "-form");
    var vaciarEl = document.getElementById(id + "-vaciar");
    var micEl = document.getElementById(id + "-mic");
    var liveEl = document.getElementById(id + "-live");
    var textareaEl = formEl.querySelector("textarea");
    if (!mensajesEl || !pendienteEl || !formEl) return;

    var idioma = LOCALE_VOZ[document.documentElement.lang] || "es-ES";
    var enviando = false;

    // Pinta el texto real de los mensajes "tool" ya renderizados por Jinja
    // (llevan el JSON crudo en data-contenido, ver _ia_chat_macro.html).
    mensajesEl.querySelectorAll(".ia-msg-tool").forEach(function (el) {
      el.innerHTML = textoMensajeTool(el.dataset.herramienta, el.dataset.contenido);
    });
    agruparHerramientas(mensajesEl);
    if (!pendienteEl.hidden) {
      var argsServidor = pendienteEl.querySelector(".ia-chat-pendiente-args");
      var nombreServidor = pendienteEl.querySelector("strong");
      if (nombreServidor) nombreServidor.textContent = nombreAccion(nombreServidor.dataset.herramienta || nombreServidor.textContent);
      if (argsServidor) pintarArgumentos(pendienteEl, argsServidor.textContent);
    }
    mensajesEl.querySelectorAll(".ia-msg-assistant").forEach(function (el) {
      var textoPlano = el.textContent;
      el.innerHTML = renderizarMarkdown(textoPlano);
      pintarCautela(el, textoPlano);
    });
    // Fuentes de los mensajes ya guardados (las pinta Jinja como contenedores vacíos).
    mensajesEl.querySelectorAll(".ia-fuentes[data-fuentes]").forEach(function (caja) {
      var previo = caja.previousElementSibling;
      var datos = [];
      try { datos = JSON.parse(caja.dataset.fuentes); } catch (e) { datos = []; }
      caja.remove();
      pintarFuentes(previo, datos);
    });
    pintarAcciones(mensajesEl);
    actualizarPanelFuentes(mensajesEl);
    // Atajos: un clic envía el texto del atajo.
    var atajosEl = document.getElementById(id + "-atajos");
    if (atajosEl) {
      atajosEl.querySelectorAll(".ia-atajo").forEach(function (b) {
        b.addEventListener("click", function () { enviarMensaje(b.dataset.prompt || ""); });
      });
    }

    function adjuntarBotonesPendiente() {
      pendienteEl.querySelectorAll(".ia-chat-confirmar").forEach(function (btn) {
        btn.onclick = function () { confirmar(btn.dataset.aceptar === "true"); };
      });
    }
    adjuntarBotonesPendiente();

    function pintarPendiente(pendiente) {
      if (!pendiente) {
        pendienteEl.hidden = true;
        pendienteEl.innerHTML = "";
        return;
      }
      pendienteEl.innerHTML =
        '<p class="ia-chat-pendiente-titulo"><strong></strong></p>' +
        '<pre class="ia-chat-pendiente-args"></pre>' +
        '<p class="ia-chat-pendiente-pregunta"></p>' +
        '<div class="ia-chat-pendiente-botones">' +
        '<button type="button" class="ia-chat-confirmar" data-aceptar="true"></button>' +
        '<button type="button" class="ia-chat-confirmar" data-aceptar="false"></button>' +
        "</div>";
      pendienteEl.querySelector("strong").textContent = nombreAccion(pendiente.herramienta);
      pendienteEl.querySelector(".ia-chat-pendiente-pregunta").textContent = t().ejecuto;
      pendienteEl.querySelector('[data-aceptar="true"]').textContent = t().si;
      pendienteEl.querySelector('[data-aceptar="false"]').textContent = t().no;
      pintarArgumentos(pendienteEl, pendiente.argumentos);
      pendienteEl.hidden = false;
      adjuntarBotonesPendiente();
    }

    // ---------------------------------------------------------------------
    // Voz: lectura en voz alta (TTS) de la respuesta según va llegando en
    // streaming, y dictado (STT) para no tener que escribir. Ninguna de las
    // dos usa librerías externas -- SpeechSynthesis/SpeechRecognition son
    // nativas del navegador (Chrome/Edge/Safari; Firefox no implementa
    // SpeechRecognition todavía, ver caniuse -- por eso todo esto se oculta
    // solo si no está disponible, sin romper el chat normal).
    var vozDisponible = "speechSynthesis" in window;
    var colaTts = [];
    var hablando = false;
    var ttsBuffer = "";

    function hablar(texto) {
      texto = texto.trim();
      if (!vozDisponible || !texto) return;
      var utterance = new SpeechSynthesisUtterance(texto);
      utterance.lang = idioma;
      colaTts.push(utterance);
      procesarColaTts();
    }
    function procesarColaTts() {
      if (hablando || colaTts.length === 0) return;
      hablando = true;
      var utterance = colaTts.shift();
      utterance.onend = utterance.onerror = function () {
        hablando = false;
        if (colaTts.length > 0) procesarColaTts();
        else if (liveActivo) empezarEscucha();
      };
      speechSynthesis.speak(utterance);
    }
    // Trocea el texto que va llegando por frases completas (acaban en
    // ./!/?/salto de línea) para poder empezar a leer antes de que termine
    // todo el turno -- el trozo final, incompleto, se queda en ttsBuffer
    // hasta la siguiente llamada o hasta flushTts().
    function trocearParaTts(fragmento) {
      ttsBuffer += fragmento;
      var partes = ttsBuffer.split(/([.!?\n]+\s*)/);
      var listo = "";
      var i;
      for (i = 0; i + 1 < partes.length; i += 2) {
        listo += partes[i] + partes[i + 1];
      }
      if (listo) hablar(listo);
      ttsBuffer = partes[partes.length - 1] || "";
    }
    function flushTts() {
      if (ttsBuffer.trim()) hablar(ttsBuffer);
      ttsBuffer = "";
    }
    function cancelarVoz() {
      colaTts = [];
      hablando = false;
      ttsBuffer = "";
      if (vozDisponible) speechSynthesis.cancel();
    }

    var ReconocedorVoz = window.SpeechRecognition || window.webkitSpeechRecognition;
    var recognition = null;
    var escuchando = false;
    var liveActivo = false;

    function actualizarBotonMic() {
      if (micEl) micEl.classList.toggle("escuchando", escuchando);
    }
    function empezarEscucha() {
      if (!recognition || escuchando || enviando || hablando || !pendienteEl.hidden) return;
      try {
        recognition.start();
      } catch (e) {
        // Ya estaba escuchando (algunos navegadores lanzan si se llama a
        // start() dos veces seguidas) -- no pasa nada, se ignora.
      }
    }
    function pararEscucha() {
      if (recognition && escuchando) recognition.stop();
    }

    if (ReconocedorVoz) {
      recognition = new ReconocedorVoz();
      recognition.lang = idioma;
      recognition.continuous = false;
      recognition.interimResults = false;
      recognition.maxAlternatives = 1;
      recognition.onstart = function () {
        escuchando = true;
        actualizarBotonMic();
      };
      recognition.onresult = function (e) {
        var transcripcion = e.results[0][0].transcript;
        textareaEl.value = transcripcion;
        if (liveActivo && transcripcion.trim()) {
          formEl.requestSubmit ? formEl.requestSubmit() : enviarMensaje(transcripcion);
        }
      };
      recognition.onend = function () {
        escuchando = false;
        actualizarBotonMic();
      };
      recognition.onerror = function () {
        escuchando = false;
        actualizarBotonMic();
      };
    }
    // Sin soporte de voz en este navegador: se ocultan los controles, el
    // chat de siempre (escribir + enviar) sigue funcionando igual.
    if (!recognition || !vozDisponible) {
      if (micEl) micEl.hidden = true;
      if (liveEl) liveEl.hidden = true;
    }

    if (micEl) {
      micEl.addEventListener("click", function () {
        if (escuchando) pararEscucha(); else empezarEscucha();
      });
    }
    if (liveEl) {
      liveEl.addEventListener("click", function () {
        liveActivo = !liveActivo;
        liveEl.classList.toggle("activo", liveActivo);
        liveEl.innerHTML = (liveActivo ? '<span class="ia-live-punto" aria-hidden="true"></span>' : iconoSvg("headphones")) + " Live";
        if (liveActivo) {
          empezarEscucha();
        } else {
          pararEscucha();
          cancelarVoz();
        }
      });
    }

    // ---------------------------------------------------------------------
    // Streaming: lee la respuesta de /ia/mensaje(/stream) y /ia/confirmar
    // (/stream) trozo a trozo (Server-Sent Events, ver
    // ia_asistente.procesar_turno_stream en el backend) en vez de esperar
    // el JSON completo -- necesario para poder leer en voz alta según va
    // llegando el texto, y de paso también hace que el chat escrito de
    // siempre se pinte progresivamente en vez de todo de golpe al final.
    function leerStream(url, cuerpo, manejadores) {
      return fetch(url, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo),
      }).then(function (resp) {
        var reader = resp.body.getReader();
        var decoder = new TextDecoder();
        var buffer = "";
        function leer() {
          return reader.read().then(function (r) {
            if (r.done) return;
            buffer += decoder.decode(r.value, { stream: true });
            var trozos = buffer.split("\n\n");
            buffer = trozos.pop();
            trozos.forEach(function (trozo) {
              var linea = trozo.trim();
              if (linea.indexOf("data:") !== 0) return;
              var crudo = linea.slice(5).trim();
              var evento;
              try { evento = JSON.parse(crudo); } catch (err) { return; }
              if (evento.tipo === "delta" && manejadores.onDelta) manejadores.onDelta(evento.texto);
              else if (evento.tipo === "mensaje" && manejadores.onMensaje) manejadores.onMensaje(evento.mensaje);
              else if (evento.tipo === "pendiente" && manejadores.onPendiente) manejadores.onPendiente(evento.pendiente);
              else if (evento.tipo === "error" && manejadores.onError) manejadores.onError(evento.mensaje);
              else if (evento.tipo === "fin" && manejadores.onFin) manejadores.onFin();
            });
            return leer();
          });
        }
        return leer();
      });
    }

    function manejarTurno(url, cuerpo) {
      enviando = true;
      textareaEl.disabled = true;
      var pensandoEl = document.createElement("div");
      pensandoEl.className = "ia-msg ia-msg-assistant chat-pensando";
      pensandoEl.innerHTML = '<span class="ia-puntos" aria-hidden="true"><i></i><i></i><i></i></span>';
      pensandoEl.appendChild(document.createTextNode(" " + t().pasos));
      mensajesEl.appendChild(pensandoEl);
      mensajesEl.scrollTop = mensajesEl.scrollHeight;

      var bubbujaViva = null;
      var textoVivo = "";
      function quitarPensando() {
        if (pensandoEl.parentNode) pensandoEl.remove();
      }
      function iniciarBurbujaViva() {
        if (bubbujaViva) return;
        quitarPensando();
        bubbujaViva = document.createElement("div");
        bubbujaViva.className = "ia-msg ia-msg-assistant";
        mensajesEl.appendChild(bubbujaViva);
        textoVivo = "";
      }

      leerStream(url, cuerpo, {
        onDelta: function (texto) {
          iniciarBurbujaViva();
          textoVivo += texto;
          bubbujaViva.textContent = textoVivo;
          mensajesEl.scrollTop = mensajesEl.scrollHeight;
          if (liveActivo) trocearParaTts(texto);
        },
        onMensaje: function (mensaje) {
          quitarPensando();
          if (mensaje.rol === "assistant" && mensaje.contenido) {
            if (!bubbujaViva) iniciarBurbujaViva();
            bubbujaViva.innerHTML = renderizarMarkdown(mensaje.contenido);
            pintarCautela(bubbujaViva, mensaje.contenido);
            if (mensaje.fuentes_json) {
              var fuentesVivas = [];
              try { fuentesVivas = JSON.parse(mensaje.fuentes_json); } catch (e) { fuentesVivas = []; }
              pintarFuentes(bubbujaViva, fuentesVivas);
            }
            bubbujaViva = null;
            pintarAcciones(mensajesEl);
            actualizarPanelFuentes(mensajesEl);
          } else if (mensaje.rol === "tool") {
            var div = document.createElement("div");
            div.className = "ia-msg ia-msg-tool";
            div.dataset.herramienta = mensaje.nombre_herramienta || "";
            div.innerHTML = textoMensajeTool(mensaje.nombre_herramienta, mensaje.contenido);
            mensajesEl.appendChild(div);
            agruparHerramientas(mensajesEl);
          }
          mensajesEl.scrollTop = mensajesEl.scrollHeight;
        },
        onPendiente: function (pendiente) {
          quitarPensando();
          pintarPendiente(pendiente);
          if (liveActivo) {
            flushTts();
            hablar("¿Ejecuto " + nombreLegible(pendiente.herramienta) + "?");
          }
        },
        onError: function (mensaje) {
          quitarPensando();
          var div = document.createElement("div");
          div.className = "ia-msg ia-msg-error";
          div.innerHTML = iconoSvg("triangle-alert") + " " + escaparHtml(mensaje || "Ha ocurrido un error.");
          mensajesEl.appendChild(div);
          mensajesEl.scrollTop = mensajesEl.scrollHeight;
        },
        onFin: function () {
          quitarPensando();
          bubbujaViva = null;
          if (liveActivo) {
            flushTts();
            if (colaTts.length === 0 && !hablando) empezarEscucha();
          }
        },
      }).catch(function () {
        quitarPensando();
        var errorDiv = document.createElement("div");
        errorDiv.className = "ia-msg ia-msg-error";
        errorDiv.innerHTML = iconoSvg("triangle-alert") + " No se pudo contactar con el servidor.";
        mensajesEl.appendChild(errorDiv);
        mensajesEl.scrollTop = mensajesEl.scrollHeight;
      }).finally(function () {
        enviando = false;
        textareaEl.disabled = false;
        if (!liveActivo) textareaEl.focus();
      });
    }

    function confirmar(aceptar) {
      manejarTurno("/ia/confirmar/stream", { aceptar: aceptar });
    }

    function enviarMensaje(texto) {
      texto = texto.trim();
      if (!texto || enviando) return;
      // El adjunto pendiente (si hay uno subido y sin usar) se antepone al
      // texto para que el modelo sepa que existe y con qué id llamar a la
      // tool leer_adjunto_chat -- no se sube el contenido entero al mensaje,
      // solo la referencia (evita gastar contexto con algo que puede que el
      // modelo ni necesite leer).
      if (adjuntoPendiente) {
        texto = "[Adjunto #" + adjuntoPendiente.id + ": " + adjuntoPendiente.nombre_archivo + "]\n" + texto;
        limpiarAdjuntoPendiente();
      }
      var div = document.createElement("div");
      div.className = "ia-msg ia-msg-user";
      div.textContent = texto;
      mensajesEl.appendChild(div);
      mensajesEl.scrollTop = mensajesEl.scrollHeight;
      textareaEl.value = "";
      manejarTurno("/ia/mensaje/stream", { texto: texto });
    }

    formEl.addEventListener("submit", function (e) {
      e.preventDefault();
      enviarMensaje(textareaEl.value);
    });

    // ---------------------------------------------------------------------
    // Adjuntos (Fase G2): sube el archivo en cuanto se elige (no espera al
    // envío del mensaje) para poder avisar de un error de formato/tamaño
    // antes de que el usuario termine de escribir su pregunta sobre él.
    var adjuntoInputEl = document.getElementById(id + "-adjunto");
    var adjuntoPendienteEl = document.getElementById(id + "-adjunto-pendiente");
    var adjuntoPendiente = null;

    function limpiarAdjuntoPendiente() {
      adjuntoPendiente = null;
      adjuntoPendienteEl.hidden = true;
      adjuntoPendienteEl.innerHTML = "";
      if (adjuntoInputEl) adjuntoInputEl.value = "";
    }

    if (adjuntoInputEl) {
      adjuntoInputEl.addEventListener("change", function () {
        var archivo = adjuntoInputEl.files[0];
        if (!archivo) return;
        var formData = new FormData();
        formData.append("adjunto", archivo);
        adjuntoPendienteEl.hidden = false;
        adjuntoPendienteEl.textContent = "Subiendo " + archivo.name + "…";
        fetch("/ia/adjuntos", { method: "POST", body: formData })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (!data.ok) {
              adjuntoPendienteEl.innerHTML = iconoSvg("triangle-alert") + " " + escaparHtml(data.error);
              adjuntoInputEl.value = "";
              return;
            }
            adjuntoPendiente = data;
            adjuntoPendienteEl.innerHTML = "";
            var span = document.createElement("span");
            span.innerHTML = iconoSvg("paperclip") + " " + escaparHtml(data.nombre_archivo);
            var quitar = document.createElement("button");
            quitar.type = "button";
            quitar.className = "ia-chat-adjunto-quitar";
            quitar.innerHTML = iconoSvg("x");
            quitar.onclick = limpiarAdjuntoPendiente;
            adjuntoPendienteEl.appendChild(span);
            adjuntoPendienteEl.appendChild(quitar);
          })
          .catch(function () {
            adjuntoPendienteEl.innerHTML = iconoSvg("triangle-alert") + " No se ha podido subir el archivo.";
            adjuntoInputEl.value = "";
          });
      });
    }

    if (vaciarEl) {
      // "Nueva conversación": no borra nada (la anterior queda en la lista de
      // conversaciones), así que no pide confirmación.
      vaciarEl.addEventListener("click", function () {
        if (liveActivo) liveEl.click(); // apaga Live también, no se queda escuchando sobre un chat vacío
        fetch("/ia/vaciar", { method: "POST" }).then(function () {
          // En la página del asistente se recarga para actualizar el selector
          // de conversaciones; en el panel flotante basta con vaciar el chat.
          if (document.getElementById("ia-conv-select")) { location.reload(); return; }
          mensajesEl.innerHTML = "";
          pintarPendiente(null);
        });
      });
    }
  }

  document.querySelectorAll(".ia-chat").forEach(iniciarChat);

  // Lista de conversaciones (solo en la página del asistente).
  var convCaja = document.querySelector(".ia-conversaciones");
  if (convCaja) {
    var accionConversacion = function (url, cuerpo) {
      var opciones = { method: "POST" };
      if (cuerpo) { opciones.headers = { "Content-Type": "application/json" }; opciones.body = JSON.stringify(cuerpo); }
      return fetch(url, opciones).then(function () { location.reload(); });
    };
    var activa = function () { return convCaja.querySelector(".ia-conv-item.on"); };
    convCaja.querySelectorAll(".ia-conv-item").forEach(function (b) {
      b.addEventListener("click", function () {
        if (b.classList.contains("on")) return;
        accionConversacion("/ia/conversaciones/" + b.dataset.convId + "/activar");
      });
    });
    var renombrar = document.getElementById("ia-conv-renombrar");
    if (renombrar) renombrar.addEventListener("click", function () {
      var actual = activa();
      if (!actual) return;
      var preguntarTitulo = window.GuildaDS ? window.GuildaDS.pedirTexto(convCaja.dataset.promptRenombrar, actual.dataset.titulo || "") : Promise.resolve(prompt(convCaja.dataset.promptRenombrar, actual.dataset.titulo || ""));
      preguntarTitulo.then(function (titulo) {
        if (titulo === null || !titulo.trim()) return;
        accionConversacion("/ia/conversaciones/" + actual.dataset.convId + "/renombrar", { titulo: titulo });
      });
    });
    var eliminar = document.getElementById("ia-conv-eliminar");
    if (eliminar) eliminar.addEventListener("click", function () {
      var actual = activa();
      if (!actual) return;
      var preguntarBorrar = window.GuildaDS ? window.GuildaDS.confirmar(convCaja.dataset.confirmarEliminar, { peligro: true }) : Promise.resolve(confirm(convCaja.dataset.confirmarEliminar));
      preguntarBorrar.then(function (si) {
        if (si) accionConversacion("/ia/conversaciones/" + actual.dataset.convId + "/eliminar");
      });
    });
  }

  var nuevaConv = document.getElementById("ia-nueva-conversacion");
  var vaciarPagina = document.getElementById("ia-chat-pagina-vaciar");
  if (nuevaConv && vaciarPagina) nuevaConv.addEventListener("click", function () { vaciarPagina.click(); });

  // «Cómo funciona»: el aviso de que la IA puede equivocarse, a un clic desde la cabecera, con el interruptor de la etiqueta de cautela.
  var infoDialogo = document.getElementById("ia-info");
  if (infoDialogo) {
    var cautelaCasilla = document.getElementById("ia-info-cautela");
    if (cautelaCasilla) {
      cautelaCasilla.checked = cautelaActiva();
      cautelaCasilla.addEventListener("change", function () { try { localStorage.setItem(CLAVE_CAUTELA, cautelaCasilla.checked ? "1" : "0"); } catch (e) { /* sin almacenamiento */ } });
    }
    document.querySelectorAll(".js-ia-info").forEach(function (b) {
      b.addEventListener("click", function () { if (infoDialogo.showModal) infoDialogo.showModal(); else infoDialogo.setAttribute("open", ""); });
    });
    infoDialogo.querySelectorAll(".js-ia-info-cerrar").forEach(function (b) { b.addEventListener("click", function () { infoDialogo.close ? infoDialogo.close() : infoDialogo.removeAttribute("open"); }); });
  }

  // `?q=` en la dirección (las sugerencias de Hoy y de las fichas): se escribe la pregunta y se envía una sola vez.
  var consulta = new URLSearchParams(location.search).get("q");
  if (consulta) {
    history.replaceState(null, "", location.pathname);
    var cajaTexto = document.querySelector(".ia-chat-form textarea");
    var formChat = document.querySelector(".ia-chat-form");
    if (cajaTexto && formChat) { cajaTexto.value = consulta; formChat.requestSubmit ? formChat.requestSubmit() : formChat.dispatchEvent(new Event("submit", { cancelable: true })); }
  }

  var togglePanel = document.getElementById("ia-panel-toggle");
  var panel = document.getElementById("ia-panel-flotante");
  var cerrarPanel = document.getElementById("ia-panel-cerrar");
  // El contenido del panel flotante se pide la primera vez que se abre (no viaja en cada
  // página: el historial del chat puede ser largo) y se inicializa igual que el resto.
  var panelCargado = false;
  function cargarPanel() {
    var cont = document.getElementById("ia-panel-contenido");
    if (panelCargado || !cont) return;
    panelCargado = true;
    cont.textContent = panel.dataset.cargando || "…";
    fetch(panel.dataset.url, { credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(function (html) {
        cont.innerHTML = html;
        var chat = cont.querySelector(".ia-chat");
        if (chat) iniciarChat(chat);
      })
      .catch(function () {
        panelCargado = false;
        cont.textContent = panel.dataset.error || "";
      });
  }
  if (togglePanel && panel) {
    togglePanel.addEventListener("click", function () {
      panel.hidden = !panel.hidden;
      var ajustes = document.getElementById("perfil-panel");     // el panel de ajustes desde el que se abrió se cierra
      if (ajustes) ajustes.hidden = true;
      if (!panel.hidden) {
        cargarPanel();
        var campo = panel.querySelector("textarea");
        if (campo) campo.focus();
      }
    });
    document.addEventListener("keydown", function (e) {            // Esc cierra el asistente
      if (e.key === "Escape" && !panel.hidden && !document.querySelector(".selbus-panel")) panel.hidden = true;
    });
  }
  if (cerrarPanel && panel) {
    cerrarPanel.addEventListener("click", function () { panel.hidden = true; });
  }
})();
