/* Lista de tareas: cambiar la prioridad o el vencimiento en la propia fila, sin abrir la ficha. Al pulsar la píldora aparece un selector (o el calendario del navegador); al elegir, se guarda y la
   fila se actualiza. Solo las píldoras con data-edita (el servidor las marca para quien puede editar la tarea). */
(function () {
  "use strict";
  var PRIORIDADES = [["alta", "Alta"], ["normal", "Normal"], ["baja", "Baja"]];
  var textos = window.GUILDA_I18N || {};
  var abierto = null;

  function cerrar() { if (abierto) { abierto.remove(); abierto = null; } }

  function guardar(pildora, campo, valor) {
    var datos = new FormData();
    datos.append("campo", campo);
    datos.append("valor", valor);
    return fetch(pildora.dataset.url, { method: "POST", body: datos, credentials: "same-origin", headers: { "Accept": "application/json" } })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok && j.ok, j: j }; }); });
  }

  function actualizar(pildora, campo, j) {
    if (campo === "prioridad") {
      pildora.textContent = j.prioridad_texto;
      pildora.className = "pildora-v2 " + ({ alta: "ambar", baja: "azul" }[j.prioridad] || "") + " prioridad-" + j.prioridad;
      pildora.dataset.valor = j.prioridad;
    } else {
      pildora.dataset.valor = j.vence.fecha;
      pildora.title = j.vence.fecha;
      pildora.textContent = j.vence.texto || ("+ " + (textos.tareaFecha || "Fecha"));
      pildora.className = "pildora-v2" + (j.vence.clase ? " " + j.vence.clase : "") + (j.vence.texto ? "" : " pildora-vacia");
    }
  }

  function abrir(pildora) {
    cerrar();
    var campo = pildora.dataset.edita;
    var control;
    if (campo === "prioridad") {
      control = document.createElement("select");
      PRIORIDADES.forEach(function (p) {
        var o = document.createElement("option");
        o.value = p[0]; o.textContent = p[1]; o.selected = p[0] === pildora.dataset.valor;
        control.appendChild(o);
      });
      control.setAttribute("aria-label", textos.tareaPrioridad || "Prioridad");
    } else {
      control = document.createElement("input");
      control.type = "date";
      control.value = pildora.dataset.valor || "";
      control.setAttribute("aria-label", textos.tareaVencimiento || "Vencimiento");
    }
    control.className = "tarea-en-fila-control";
    pildora.insertAdjacentElement("afterend", control);
    abierto = control;
    control.focus();
    if (control.showPicker) { try { control.showPicker(); } catch (e) { /* algunos navegadores solo lo permiten con un gesto directo */ } }
    control.addEventListener("change", function () {
      var valor = control.value;
      guardar(pildora, campo, valor).then(function (r) {
        if (r.ok) actualizar(pildora, campo, r.j);
        else if (window.mostrarToast) window.mostrarToast((r.j && r.j.error) || textos.correoAccionError || "No se pudo guardar.", "error");
        cerrar();
      }).catch(function () { if (window.mostrarToast) window.mostrarToast(textos.correoAccionError || "No se pudo guardar.", "error"); cerrar(); });
    });
    control.addEventListener("blur", function () { setTimeout(cerrar, 150); });
    control.addEventListener("keydown", function (e) { if (e.key === "Escape") { e.preventDefault(); cerrar(); pildora.focus(); } });
  }

  document.addEventListener("click", function (e) {
    var p = e.target.closest && e.target.closest("[data-edita]");
    if (!p) return;
    e.preventDefault(); e.stopPropagation();
    abrir(p);
  });
  document.addEventListener("keydown", function (e) {
    if ((e.key === "Enter" || e.key === " ") && e.target.matches && e.target.matches("[data-edita]")) { e.preventDefault(); abrir(e.target); }
  });
})();
