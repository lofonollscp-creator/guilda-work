// Página de proyecto: vista previa del alta rápida y arrastrar y soltar (lista, tablero, calendario).
// Todo lo que se arrastra tiene también una vía sin ratón (el selector de cada tarjeta, la ficha de la tarea,
// Alt + ↑/↓ en la lista), y sin JavaScript los formularios siguen funcionando.
(function () {
  "use strict";

  function enviar(url, datos) {
    var cuerpo = new FormData();
    Object.keys(datos).forEach(function (k) { if (datos[k] !== null && datos[k] !== undefined) cuerpo.append(k, datos[k]); });
    return fetch(url, {
      method: "POST", body: cuerpo, credentials: "same-origin",
      headers: { "X-Requested-With": "fetch", "Accept": "application/json" },
    }).then(function (r) {
      return r.json().then(function (j) { return { ok: r.ok && j.ok !== false, datos: j }; }, function () { return { ok: false, datos: {} }; });
    }).catch(function () { return { ok: false, datos: {} }; });
  }

  function url(plantilla, id) { return plantilla.replace("/tareas/0/", "/tareas/" + id + "/"); }

  function aviso(raiz, mensaje, deshacer) {
    if (!window.mostrarToast) return;
    var opciones = {};
    if (deshacer) { opciones.textoAccion = raiz.dataset.tDeshacer || "Undo"; opciones.accion = deshacer; opciones.duracion = 8000; }
    window.mostrarToast(mensaje, "exito", opciones);
  }
  function fallo(raiz, mensaje) {
    if (window.mostrarToast) window.mostrarToast(mensaje || raiz.dataset.tError || "Error", "error");
  }

  // --- Vista previa del alta rápida ---------------------------------------------------------------
  var campo = document.querySelector("input[data-interpretar]");
  var previa = document.getElementById("alta-previa");
  if (campo && previa) {
    var temporizador = null;
    var ultima = "";
    var pintar = function (d) {
      var trozos = [];
      if (d.vencimiento) trozos.push((d.fecha_texto || d.vencimiento.slice(0, 10)) + (d.hora ? " " + d.hora : ""));
      if (d.persona) trozos.push("@" + d.persona);
      if (d.seccion) trozos.push("#" + d.seccion);
      if (d.prioridad) trozos.push("!" + d.prioridad);
      if (d.estimacion) trozos.push("~" + d.estimacion);
      previa.textContent = trozos.length ? trozos.join(" · ") : "";
      if (d.sin_resolver && d.sin_resolver.length) previa.textContent += (trozos.length ? " · " : "") + d.sin_resolver.join(" ") + " ?";
      previa.hidden = !previa.textContent;
    };
    campo.addEventListener("input", function () {
      clearTimeout(temporizador);
      var texto = campo.value;
      if (!/[@#!]|\d|hoy|mañana|manana|lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo|today|tomorrow|avui|dem[aà]/i.test(texto)) { previa.hidden = true; return; }
      temporizador = setTimeout(function () {
        if (texto === ultima) return;
        ultima = texto;
        fetch(campo.dataset.interpretar + "?texto=" + encodeURIComponent(texto), { credentials: "same-origin", headers: { "Accept": "application/json" } })
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (d) { if (d && campo.value === texto) pintar(d); })
          .catch(function () { previa.hidden = true; });
      }, 250);
    });
  }

  var raiz = document.querySelector("[data-dnd]");
  if (!raiz) return;
  var modo = raiz.dataset.dnd;
  var arrastrada = null;

  function empezar(e, elemento) {
    arrastrada = elemento;
    elemento.classList.add("is-arrastrando");
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", elemento.dataset.tarea);
  }
  function terminar() {
    if (arrastrada) arrastrada.classList.remove("is-arrastrando");
    arrastrada = null;
    raiz.querySelectorAll(".is-destino").forEach(function (z) { z.classList.remove("is-destino"); });
  }
  function permitirSoltar(zona) {
    zona.addEventListener("dragover", function (e) { if (!arrastrada) return; e.preventDefault(); zona.classList.add("is-destino"); });
    zona.addEventListener("dragleave", function (e) { if (!zona.contains(e.relatedTarget)) zona.classList.remove("is-destino"); });
  }

  // --- Tablero: cambiar de estado --------------------------------------------------------------------
  if (modo === "tablero") {
    var cambiarEstado = function (tarjeta, destino, anterior) {
      var id = tarjeta.dataset.tarea;
      var origen = tarjeta.parentElement;
      var marcador = tarjeta.nextSibling;
      destino.insertBefore(tarjeta, destino.querySelector(".tareas-columna-vacia, .tareas-columna-mas"));
      var vacio = destino.querySelector(".tareas-columna-vacia"); if (vacio) vacio.remove();
      actualizarContador(origen, -1); actualizarContador(destino, 1);
      enviar(url(raiz.dataset.urlEstado, id), { estado: destino.dataset.estado }).then(function (r) {
        if (!r.ok) {
          origen.insertBefore(tarjeta, marcador); actualizarContador(destino, -1); actualizarContador(origen, 1);
          fallo(raiz, r.datos && r.datos.mensaje);
          return;
        }
        var selector = tarjeta.querySelector("select[name=estado]"); if (selector) selector.value = destino.dataset.estado;
        aviso(raiz, raiz.dataset.tMovida, function () {
          var columnaAnterior = raiz.querySelector('.tareas-columna[data-estado="' + (anterior || origen.dataset.estado) + '"]');
          if (columnaAnterior) cambiarEstado(tarjeta, columnaAnterior, null);
        });
      });
    };
    var actualizarContador = function (columna, delta) {
      var c = columna.querySelector("[data-contador]"); if (c) c.textContent = String(Math.max(0, (parseInt(c.textContent, 10) || 0) + delta));
    };
    raiz.querySelectorAll(".tareas-tarjeta[draggable]").forEach(function (t) {
      t.addEventListener("dragstart", function (e) { empezar(e, t); });
      t.addEventListener("dragend", terminar);
    });
    raiz.querySelectorAll(".tareas-columna").forEach(function (col) {
      permitirSoltar(col);
      col.addEventListener("drop", function (e) {
        e.preventDefault();
        if (!arrastrada || arrastrada.parentElement === col) { terminar(); return; }
        var tarjeta = arrastrada; terminar();
        cambiarEstado(tarjeta, col, tarjeta.parentElement.dataset.estado);
      });
    });
    raiz.querySelectorAll(".tareas-tarjeta-mover").forEach(function (f) {
      f.addEventListener("submit", function (e) {
        var tarjeta = f.closest(".tareas-tarjeta");
        var destino = raiz.querySelector('.tareas-columna[data-estado="' + f.querySelector("select").value + '"]');
        if (!tarjeta || !destino || destino === tarjeta.parentElement) return;
        e.preventDefault();
        cambiarEstado(tarjeta, destino, tarjeta.parentElement.dataset.estado);
      });
    });
  }

  // --- Calendario: cambiar el día de vencimiento ---------------------------------------------------------
  if (modo === "calendario") {
    var cambiarDia = function (chip, celda, fechaAnterior) {
      var id = chip.dataset.tarea;
      var origen = chip.parentElement;
      var marcador = chip.nextSibling;
      celda.querySelector(".cal-cell-chips").appendChild(chip);
      enviar(url(raiz.dataset.urlFecha, id), { fecha: celda.dataset.fecha }).then(function (r) {
        if (!r.ok) { origen.insertBefore(chip, marcador); fallo(raiz, r.datos && r.datos.mensaje); return; }
        var anterior = (r.datos && r.datos.anterior) || fechaAnterior;
        aviso(raiz, raiz.dataset.tMovida, anterior ? function () {
          var celdaAnterior = raiz.querySelector('.cal-cell[data-fecha="' + anterior + '"]');
          if (celdaAnterior) cambiarDia(chip, celdaAnterior, null);
        } : null);
      });
    };
    raiz.querySelectorAll(".cal-chip[draggable]").forEach(function (c) {
      c.addEventListener("dragstart", function (e) { empezar(e, c); });
      c.addEventListener("dragend", terminar);
    });
    raiz.querySelectorAll(".cal-cell").forEach(function (celda) {
      permitirSoltar(celda);
      celda.addEventListener("drop", function (e) {
        e.preventDefault();
        if (!arrastrada || arrastrada.closest(".cal-cell") === celda) { terminar(); return; }
        var chip = arrastrada; terminar();
        cambiarDia(chip, celda, chip.closest(".cal-cell").dataset.fecha);
      });
    });
  }

  // --- Lista: reordenar y pasar de sección --------------------------------------------------------------
  if (modo === "lista") {
    var colocar = function (fila, zona, antes, restaurar) {
      var origen = fila.parentElement;
      var marcador = fila.nextElementSibling;
      zona.insertBefore(fila, antes || null);
      var vacio = zona.parentElement.querySelector(".proyecto-vacio"); if (vacio) vacio.hidden = true;
      var siguiente = fila.nextElementSibling;
      enviar(url(raiz.dataset.urlOrden, fila.dataset.tarea), {
        seccion_id: zona.dataset.seccion || "", antes_de: siguiente && siguiente.dataset.tarea ? siguiente.dataset.tarea : "",
      }).then(function (r) {
        if (!r.ok) { origen.insertBefore(fila, marcador); fallo(raiz, r.datos && r.datos.mensaje); return; }
        if (!restaurar) aviso(raiz, raiz.dataset.tMovida, function () { colocar(fila, origen, marcador, true); });
      });
    };
    raiz.querySelectorAll("li[data-tarea][draggable]").forEach(function (fila) {
      fila.addEventListener("dragstart", function (e) { empezar(e, fila); });
      fila.addEventListener("dragend", terminar);
      fila.addEventListener("keydown", function (e) {
        if (!e.altKey || (e.key !== "ArrowUp" && e.key !== "ArrowDown") || e.target !== fila) return;
        e.preventDefault();
        var zona = fila.parentElement;
        var hermana = e.key === "ArrowUp" ? fila.previousElementSibling : fila.nextElementSibling;
        if (!hermana) return;
        colocar(fila, zona, e.key === "ArrowUp" ? hermana : hermana.nextElementSibling, false);
        fila.focus();
      });
    });
    raiz.querySelectorAll(".proyecto-zona").forEach(function (zona) {
      permitirSoltar(zona);
      zona.addEventListener("drop", function (e) {
        e.preventDefault();
        if (!arrastrada) return;
        var fila = arrastrada; terminar();
        var objetivo = e.target.closest("li[data-tarea]");
        var antes = null;
        if (objetivo && objetivo !== fila) {
          var caja = objetivo.getBoundingClientRect();
          antes = e.clientY < caja.top + caja.height / 2 ? objetivo : objetivo.nextElementSibling;
        }
        if (antes === fila) return;
        colocar(fila, zona, antes, false);
      });
    });
  }
})();
