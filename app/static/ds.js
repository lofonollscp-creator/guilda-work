// Sistema de diseño: diálogos propios que sustituyen a window.confirm / prompt / alert.
//
//   GuildaDS.confirmar(mensaje, { titulo, aceptar, cancelar, peligro })  -> Promise<boolean>
//   GuildaDS.pedirTexto(mensaje, valorInicial, { titulo, aceptar, tipo, marcador }) -> Promise<string|null>   (null = cancelado)
//   GuildaDS.avisar(mensaje, { titulo, aceptar })                         -> Promise<void>
//
// Usan <dialog>.showModal(): el navegador ya atrapa el foco, cierra con Esc y deja el resto de la página inerte. Todo el texto se pinta con
// textContent (nunca HTML). Si el navegador no soporta <dialog> se cae a los diálogos nativos, así que nada deja de funcionar.
(function () {
  function textos() { return window.GUILDA_I18N || {}; }
  function icono(nombre) {
    return '<svg aria-hidden="true" width="18" height="18"><use href="/static/iconos.svg#icono-' + nombre + '"></use></svg>';
  }

  function crear(mensaje, opciones, conCampo, valorInicial) {
    var t = textos();
    var dlg = document.createElement("dialog");
    dlg.className = "ds-dialogo" + (opciones.peligro ? " ds-dialogo-peligro" : "");
    var ident = "ds-dlg-" + Math.random().toString(36).slice(2, 8);
    dlg.setAttribute("aria-labelledby", ident + "-t");
    dlg.setAttribute("aria-describedby", ident + "-m");

    var form = document.createElement("form");
    form.method = "dialog";

    var cab = document.createElement("div");
    cab.className = "ds-dialogo-cabecera";
    var ico = document.createElement("span");
    ico.className = "ds-dialogo-icono";
    ico.innerHTML = icono(opciones.peligro ? "triangle-alert" : (conCampo ? "pencil" : "info"));
    var titulo = document.createElement("h2");
    titulo.id = ident + "-t";
    titulo.textContent = opciones.titulo || (opciones.peligro ? (t.dsConfirmarPeligro || "Confirma la acción") : (t.dsAtencion || "Atención"));
    cab.appendChild(ico);
    cab.appendChild(titulo);
    form.appendChild(cab);

    var p = document.createElement("p");
    p.id = ident + "-m";
    p.textContent = mensaje;
    form.appendChild(p);

    var campo = null;
    if (conCampo) {
      campo = document.createElement("input");
      campo.type = opciones.tipo || "text";
      campo.value = valorInicial || "";
      if (opciones.marcador) campo.placeholder = opciones.marcador;
      campo.setAttribute("aria-labelledby", ident + "-m");
      campo.autocomplete = "off";
      form.appendChild(campo);
    }

    var botones = document.createElement("div");
    botones.className = "ds-dialogo-botones";
    var cancelar = null;
    if (opciones.soloAceptar !== true) {
      cancelar = document.createElement("button");
      cancelar.type = "button";
      cancelar.className = "btn btn-ghost";
      cancelar.value = "cancelar";
      cancelar.textContent = opciones.cancelar || t.dsCancelar || "Cancelar";
      botones.appendChild(cancelar);
    }
    var aceptar = document.createElement("button");
    aceptar.type = "submit";
    aceptar.className = "btn " + (opciones.peligro ? "btn-peligro" : "btn-primary");
    aceptar.value = "aceptar";
    aceptar.textContent = opciones.aceptar || t.dsAceptar || "Aceptar";
    botones.appendChild(aceptar);
    form.appendChild(botones);

    dlg.appendChild(form);
    return { dlg: dlg, form: form, campo: campo, aceptar: aceptar, cancelar: cancelar };
  }

  function abrir(mensaje, opciones, conCampo, valorInicial) {
    opciones = opciones || {};
    return new Promise(function (resolver) {
      var antes = document.activeElement;
      var c = crear(mensaje, opciones, conCampo, valorInicial);
      var resultado = null;       // true / texto al aceptar; false / null al cancelar
      var cerrado = false;

      function terminar() {
        if (cerrado) return;
        cerrado = true;
        if (c.dlg.open) c.dlg.close();
        c.dlg.remove();
        if (antes && antes.focus && document.contains(antes)) { try { antes.focus(); } catch (e) { /* se quedó sin foco */ } }
        resolver(resultado);
      }

      c.form.addEventListener("submit", function (e) {
        e.preventDefault();
        resultado = conCampo ? c.campo.value : true;
        terminar();
      });
      if (c.cancelar) c.cancelar.addEventListener("click", function () { resultado = conCampo ? null : false; terminar(); });
      c.dlg.addEventListener("cancel", function (e) { e.preventDefault(); resultado = conCampo ? null : (opciones.soloAceptar === true); terminar(); });   // Esc
      c.dlg.addEventListener("click", function (e) {                                                                                  // clic en el fondo
        if (e.target === c.dlg && opciones.soloAceptar !== true) { resultado = conCampo ? null : false; terminar(); }
      });

      document.body.appendChild(c.dlg);
      c.dlg.showModal();
      // En una acción destructiva el foco empieza en «Cancelar»: Enter sin querer no borra nada.
      var inicial = conCampo ? c.campo : (opciones.peligro && c.cancelar ? c.cancelar : c.aceptar);
      inicial.focus();
      if (conCampo) c.campo.select();
    });
  }

  var soportado = typeof HTMLDialogElement === "function" && typeof HTMLDialogElement.prototype.showModal === "function";

  window.GuildaDS = {
    confirmar: function (mensaje, opciones) {
      if (!soportado) return Promise.resolve(window.confirm(mensaje));
      return abrir(mensaje, opciones, false);
    },
    pedirTexto: function (mensaje, valorInicial, opciones) {
      if (!soportado) return Promise.resolve(window.prompt(mensaje, valorInicial || ""));
      return abrir(mensaje, opciones, true, valorInicial);
    },
    avisar: function (mensaje, opciones) {
      opciones = Object.assign({ soloAceptar: true }, opciones || {});
      if (!soportado) { window.alert(mensaje); return Promise.resolve(); }
      return abrir(mensaje, opciones, false).then(function () { /* sin valor */ });
    },
  };
})();
