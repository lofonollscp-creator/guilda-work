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

  function pintar(accion, datos) {
    var cont = document.createElement("div");
    if (accion === "tareas") {
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
