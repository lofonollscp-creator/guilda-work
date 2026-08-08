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

  function iniciarChat(contenedor) {
    var id = contenedor.id;
    var mensajesEl = document.getElementById(id + "-mensajes");
    var pendienteEl = document.getElementById(id + "-pendiente");
    var formEl = document.getElementById(id + "-form");
    var vaciarEl = document.getElementById(id + "-vaciar");
    var textareaEl = formEl.querySelector("textarea");
    if (!mensajesEl || !pendienteEl || !formEl) return;

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

    function agregarMensajes(mensajes) {
      mensajes.forEach(function (m) {
        var div = document.createElement("div");
        if (m.rol === "user") {
          div.className = "ia-msg ia-msg-user";
          div.textContent = m.contenido;
        } else if (m.rol === "assistant" && m.contenido) {
          div.className = "ia-msg ia-msg-assistant";
          div.innerHTML = renderizarMarkdown(m.contenido);
        } else if (m.rol === "tool") {
          div.className = "ia-msg ia-msg-tool";
          div.textContent = textoMensajeTool(m.nombre_herramienta, m.contenido);
        } else {
          return;
        }
        mensajesEl.appendChild(div);
      });
      mensajesEl.scrollTop = mensajesEl.scrollHeight;
    }

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

    function manejarRespuesta(datos) {
      if (!datos.ok) {
        var div = document.createElement("div");
        div.className = "ia-msg ia-msg-error";
        div.textContent = "⚠️ " + (datos.error || "Ha ocurrido un error.");
        mensajesEl.appendChild(div);
        mensajesEl.scrollTop = mensajesEl.scrollHeight;
        return;
      }
      agregarMensajes(datos.mensajes_nuevos || []);
      pintarPendiente(datos.pendiente);
    }

    function confirmar(aceptar) {
      fetch("/ia/confirmar", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ aceptar: aceptar }),
      }).then(function (r) { return r.json(); }).then(manejarRespuesta);
    }

    formEl.addEventListener("submit", function (e) {
      e.preventDefault();
      var texto = textareaEl.value.trim();
      if (!texto) return;
      var div = document.createElement("div");
      div.className = "ia-msg ia-msg-user";
      div.textContent = texto;
      mensajesEl.appendChild(div);
      var pensandoEl = document.createElement("div");
      pensandoEl.className = "ia-msg ia-msg-assistant chat-pensando";
      pensandoEl.textContent = "Pensando...";
      mensajesEl.appendChild(pensandoEl);
      mensajesEl.scrollTop = mensajesEl.scrollHeight;
      textareaEl.value = "";
      textareaEl.disabled = true;
      fetch("/ia/mensaje", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ texto: texto }),
      }).then(function (r) { return r.json(); }).then(function (datos) {
        pensandoEl.remove();
        manejarRespuesta(datos);
      }).catch(function () {
        pensandoEl.remove();
        var errorDiv = document.createElement("div");
        errorDiv.className = "ia-msg ia-msg-error";
        errorDiv.textContent = "⚠️ No se pudo contactar con el servidor.";
        mensajesEl.appendChild(errorDiv);
        mensajesEl.scrollTop = mensajesEl.scrollHeight;
      }).finally(function () {
        textareaEl.disabled = false;
        textareaEl.focus();
      });
    });

    if (vaciarEl) {
      vaciarEl.addEventListener("click", function () {
        if (!confirm("¿Borrar todo el historial de esta conversación?")) return;
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
