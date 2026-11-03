/* Consulta jurídica: al elegir un cliente se enseña, antes de enviar, el contexto exacto que recibirá el modelo (y se puede desmarcar). */
(function () {
  "use strict";
  var selector = document.getElementById("jur-cliente");
  var caja = document.getElementById("jur-contexto");
  var texto = document.getElementById("jur-contexto-texto");
  if (!selector || !caja || !texto) return;
  var peticion = 0;
  selector.addEventListener("change", function () {
    var id = selector.value;
    var esta = ++peticion;
    if (!id) { caja.hidden = true; texto.textContent = ""; return; }
    fetch(selector.dataset.contexto + "?cliente_id=" + encodeURIComponent(id), { credentials: "same-origin", headers: { "Accept": "application/json" } })
      .then(function (r) { return r.ok ? r.json() : { texto: "" }; })
      .then(function (d) {
        if (esta !== peticion) return;
        texto.textContent = d.texto || "";
        caja.hidden = !d.texto;
      })
      .catch(function () { if (esta === peticion) caja.hidden = true; });
  });
})();
