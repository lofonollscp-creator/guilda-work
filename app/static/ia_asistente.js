// Asistente IA: gobierna cualquier .ia-chat presente en la página (el chat
// de página completa en /ia, y/o el panel flotante de base.html). Sin SPA:
// fetch a /ia/mensaje y /ia/confirmar, actualiza el DOM con lo que devuelven.
(function () {
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
          div.textContent = m.contenido;
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
      mensajesEl.scrollTop = mensajesEl.scrollHeight;
      textareaEl.value = "";
      fetch("/ia/mensaje", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ texto: texto }),
      }).then(function (r) { return r.json(); }).then(manejarRespuesta);
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
