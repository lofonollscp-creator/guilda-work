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
    return d.innerHTML;
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

  function textoMensajeTool(herramienta, contenidoJson) {
    var texto = "🔧 usó " + herramienta;
    try {
      var datos = JSON.parse(contenidoJson || "{}");
      if (datos && datos.error) texto = "⚠️ " + herramienta + ": " + datos.error;
      else if (datos && datos.rechazado) texto = "❌ " + herramienta + " (rechazada)";
    } catch (e) {
      // contenido no era JSON válido: se deja el texto por defecto
    }
    return texto;
  }

  // Idioma de interfaz -> BCP-47 completo, para que STT/TTS elijan una voz
  // razonable (el atributo lang="es"/"ca"/"en"/"fr" del <html>, ver
  // base.html, funciona pero un código completo da mejores resultados en
  // más navegadores).
  var LOCALE_VOZ = { es: "es-ES", ca: "ca-ES", en: "en-US", fr: "fr-FR" };

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
      el.textContent = textoMensajeTool(el.dataset.herramienta, el.dataset.contenido);
    });
    mensajesEl.querySelectorAll(".ia-msg-assistant").forEach(function (el) {
      el.innerHTML = renderizarMarkdown(el.textContent);
    });

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
        '<p class="ia-chat-pendiente-titulo">¿Ejecuto <strong></strong>?</p>' +
        '<pre class="ia-chat-pendiente-args"></pre>' +
        '<div class="ia-chat-pendiente-botones">' +
        '<button type="button" class="ia-chat-confirmar" data-aceptar="true">Sí, hazlo</button>' +
        '<button type="button" class="ia-chat-confirmar" data-aceptar="false">No</button>' +
        "</div>";
      pendienteEl.querySelector("strong").textContent = pendiente.herramienta;
      pendienteEl.querySelector(".ia-chat-pendiente-args").textContent = JSON.stringify(pendiente.argumentos, null, 2);
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
        liveEl.textContent = liveActivo ? "🔴 Live" : "🎧 Live";
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
      pensandoEl.textContent = "Pensando...";
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
            bubbujaViva = null;
          } else if (mensaje.rol === "tool") {
            var div = document.createElement("div");
            div.className = "ia-msg ia-msg-tool";
            div.textContent = textoMensajeTool(mensaje.nombre_herramienta, mensaje.contenido);
            mensajesEl.appendChild(div);
          }
          mensajesEl.scrollTop = mensajesEl.scrollHeight;
        },
        onPendiente: function (pendiente) {
          quitarPensando();
          pintarPendiente(pendiente);
          if (liveActivo) {
            flushTts();
            hablar("¿Ejecuto " + pendiente.herramienta + "?");
          }
        },
        onError: function (mensaje) {
          quitarPensando();
          var div = document.createElement("div");
          div.className = "ia-msg ia-msg-error";
          div.textContent = "⚠️ " + (mensaje || "Ha ocurrido un error.");
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
        errorDiv.textContent = "⚠️ No se pudo contactar con el servidor.";
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

    if (vaciarEl) {
      vaciarEl.addEventListener("click", function () {
        if (!confirm("¿Borrar todo el historial de esta conversación?")) return;
        if (liveActivo) liveEl.click(); // apaga Live también, no se queda escuchando sobre un chat vacío
        fetch("/ia/vaciar", { method: "POST" }).then(function () {
          mensajesEl.innerHTML = "";
          pintarPendiente(null);
        });
      });
    }
  }

  document.querySelectorAll(".ia-chat").forEach(iniciarChat);

  var togglePanel = document.getElementById("ia-panel-toggle");
  var panel = document.getElementById("ia-panel-flotante");
  var cerrarPanel = document.getElementById("ia-panel-cerrar");
  if (togglePanel && panel) {
    togglePanel.addEventListener("click", function () { panel.hidden = !panel.hidden; });
  }
  if (cerrarPanel && panel) {
    cerrarPanel.addEventListener("click", function () { panel.hidden = true; });
  }
})();
