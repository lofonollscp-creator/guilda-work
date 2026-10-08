// Plan de carga: arrastrar una tarea a otra persona (reasignar) o a otro día (cambiar el vencimiento).
// Sin ratón: el enlace de cada tarea abre su ficha, donde se cambia lo mismo.
(function () {
  "use strict";
  var raiz = document.querySelector(".carga-envoltorio");
  if (!raiz) return;
  var arrastrada = null;

  function enviar(datos) {
    var cuerpo = new FormData();
    Object.keys(datos).forEach(function (k) { cuerpo.append(k, datos[k]); });
    return fetch(raiz.dataset.urlMover, {
      method: "POST", body: cuerpo, credentials: "same-origin", headers: { "X-Requested-With": "fetch", "Accept": "application/json" },
    }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok && j.ok !== false, mensaje: j.mensaje }; }, function () { return { ok: false }; }); })
      .catch(function () { return { ok: false }; });
  }

  raiz.addEventListener("dragstart", function (e) {
    var li = e.target.closest && e.target.closest(".carga-tarea");
    if (!li) return;
    arrastrada = li;
    li.classList.add("is-arrastrando");
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", li.dataset.tarea);
  });
  raiz.addEventListener("dragend", function () {
    if (arrastrada) arrastrada.classList.remove("is-arrastrando");
    arrastrada = null;
    raiz.querySelectorAll(".is-destino").forEach(function (c) { c.classList.remove("is-destino"); });
  });
  raiz.addEventListener("dragover", function (e) {
    var celda = e.target.closest && e.target.closest(".carga-celda");
    if (!celda || !arrastrada) return;
    e.preventDefault();
    raiz.querySelectorAll(".is-destino").forEach(function (c) { if (c !== celda) c.classList.remove("is-destino"); });
    celda.classList.add("is-destino");
  });
  raiz.addEventListener("drop", function (e) {
    var celda = e.target.closest && e.target.closest(".carga-celda");
    if (!celda || !arrastrada) return;
    e.preventDefault();
    var origen = arrastrada.closest(".carga-celda");
    var datos = { tarea_id: arrastrada.dataset.tarea };
    // Solo se manda lo que cambia: la persona si cambia de fila, el día si cambia de columna con fecha
    // (las columnas «Atrasadas» y «Sin fecha» no tienen día: no se toca el vencimiento).
    if (celda.dataset.persona !== origen.dataset.persona) datos.persona_id = celda.dataset.persona;
    if (celda.dataset.fecha && celda.dataset.fecha !== origen.dataset.fecha) datos.fecha = celda.dataset.fecha;
    if (!datos.persona_id && !datos.fecha) return;
    enviar(datos).then(function (r) {
      if (r.ok) { window.location.reload(); return; }
      if (window.mostrarToast) window.mostrarToast(r.mensaje || raiz.dataset.tError, "error");
    });
  });
})();
