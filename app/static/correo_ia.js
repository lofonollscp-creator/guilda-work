(function () {
  "use strict";
  var panel = document.getElementById("correo-ia-panel");
  if (!panel) return;
  var resultado = panel.querySelector(".correo-ia-resultado");
  var d = panel.dataset;

  function limpiar() { while (resultado.firstChild) resultado.removeChild(resultado.firstChild); }
  function mostrar(nodo) { limpiar(); resultado.appendChild(nodo); panel.hidden = false; }
  function parrafo(texto, clase) {
    var p = document.createElement("p");
    if (clase) p.className = clase;
    p.textContent = texto; // siempre textContent: la respuesta de la IA no es HTML de confianza
    return p;
  }
  function boton(texto, onclick, tipo) {
    var b = document.createElement("button");
    b.type = tipo || "button"; b.className = "boton-secundario"; b.textContent = texto;
    if (onclick) b.addEventListener("click", onclick);
    return b;
  }
  function cerrar() { return boton(d.tCerrar, function () { panel.hidden = true; limpiar(); }); }

  function formulario(url, campos, textoBoton) {
    var f = document.createElement("form");
    f.method = "post"; f.action = url;
    campos.forEach(function (c) {
      f.appendChild(c);
    });
    f.appendChild(boton(textoBoton, null, "submit"));
    return f;
  }

  function campo(tipo, nombre, valor, extra) {
    var i = document.createElement("input");
    i.type = tipo; i.name = nombre; if (valor !== undefined && valor !== null) i.value = valor;
    if (extra) Object.keys(extra).forEach(function (k) { i[k] = extra[k]; });
    return i;
  }
  function casilla(nombre, texto, marcada) {
    var l = document.createElement("label"); l.className = "correo-ia-tarea";
    var i = campo("checkbox", nombre, "on", { checked: marcada });
    l.appendChild(i); l.appendChild(document.createTextNode(" " + texto));
    return l;
  }

  // El plan completo («Sugerir acciones»): todo editable y marcado a mano; nada se aplica sin pulsar el botón.
  function pintarAcciones(cont, datos) {
    var campos = [];
    var hay = false;
    if (datos.cliente && (!datos.cliente_actual || datos.cliente_actual.id !== datos.cliente.id)) {
      hay = true;
      campos.push(campo("hidden", "cliente_id", datos.cliente.id));
      campos.push(casilla("vincular", d.tAccCliente.replace("%s", datos.cliente.nombre), true));
    } else if (datos.cliente_actual) {
      campos.push(campo("hidden", "cliente_id", datos.cliente_actual.id));
    }
    if (datos.tareas && datos.tareas.length) {
      hay = true;
      var t = document.createElement("strong"); t.textContent = d.tAccTareas; campos.push(t);
      datos.tareas.forEach(function (tarea, n) {
        var fila = document.createElement("div"); fila.className = "correo-ia-accion-tarea";
        fila.appendChild(casilla("tarea-" + n + "-on", "", true));
        fila.appendChild(campo("text", "tarea-" + n + "-asunto", tarea.asunto, { maxLength: 120, required: true }));
        var fecha = campo("date", "tarea-" + n + "-fecha", tarea.fecha || ""); fecha.title = d.tAccFecha; fila.appendChild(fecha);
        var prio = document.createElement("select"); prio.name = "tarea-" + n + "-prioridad";
        [["alta", d.tAccAlta], ["normal", d.tAccNormal], ["baja", d.tAccBaja]].forEach(function (p) {
          var o = document.createElement("option"); o.value = p[0]; o.textContent = p[1]; o.selected = p[0] === tarea.prioridad; prio.appendChild(o);
        });
        fila.appendChild(prio);
        var est = campo("text", "tarea-" + n + "-estimacion", tarea.estimacion || "", { maxLength: 12, size: 6, placeholder: "1h30" }); est.title = d.tAccEstimacion; fila.appendChild(est);
        campos.push(fila);
      });
    }
    var cliente = datos.cliente_actual || datos.cliente;
    if (datos.adjuntos && cliente) {
      hay = true;
      campos.push(casilla("archivar", d.tAccArchivar.replace("%s", datos.adjuntos), false));
    }
    if (datos.respuesta) {
      hay = true;
      campos.push(casilla("respuesta-on", d.tAccRespuesta, false));
      var area = document.createElement("textarea"); area.name = "respuesta"; area.rows = 6; area.value = datos.respuesta; campos.push(area);
    }
    if (!hay) { cont.appendChild(parrafo(d.tAccSin)); return; }
    cont.appendChild(formulario(d.urlAplicar, campos, d.tAccAplicar));
  }

  function pintar(accion, datos) {
    var cont = document.createElement("div");
    if (accion === "acciones") {
      pintarAcciones(cont, datos);
    } else if (accion === "tareas") {
      if (!datos.tareas || !datos.tareas.length) {
        cont.appendChild(parrafo(d.tSinTareas));
      } else {
        var campos = datos.tareas.map(function (t) {
          var l = document.createElement("label"); l.className = "correo-ia-tarea";
          var i = document.createElement("input");
          i.type = "checkbox"; i.name = "tarea"; i.value = t; i.checked = true;
          l.appendChild(i); l.appendChild(document.createTextNode(" " + t));
          return l;
        });
        cont.appendChild(formulario(d.urlTareas, campos, d.tCrear));
      }
    } else if (accion === "responder") {
      var area = document.createElement("textarea");
      area.name = "texto"; area.rows = 8; area.value = datos.texto || "";
      cont.appendChild(formulario(d.urlBorrador, [area], d.tUsar));
    } else {
      cont.appendChild(parrafo(datos.texto || "", "correo-ia-texto"));
    }
    cont.appendChild(cerrar());
    mostrar(cont);
  }

  document.querySelectorAll("[data-ia-accion]").forEach(function (b) {
    b.addEventListener("click", function () {
      var accion = b.dataset.iaAccion;
      mostrar(parrafo(d.tCargando));
      b.disabled = true;
      fetch(d.urlBase.replace("ACCION", accion), {
        method: "POST", headers: { "X-Requested-With": "fetch" }, credentials: "same-origin",
      }).then(function (r) { return r.json().catch(function () { return {}; }); })
        .then(function (datos) {
          if (datos.ok) { pintar(accion, datos); return; }
          var c = document.createElement("div");
          c.appendChild(parrafo(datos.error || d.tError, "correo-ia-error"));
          c.appendChild(cerrar());
          mostrar(c);
        })
        .catch(function () {
          var c = document.createElement("div");
          c.appendChild(parrafo(d.tError, "correo-ia-error")); c.appendChild(cerrar()); mostrar(c);
        })
        .finally(function () { b.disabled = false; });
    });
  });
})();
