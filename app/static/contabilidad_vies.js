// «Comprobar NIF en VIES»: pregunta al servidor si el NIF-IVA de la factura está dado de alta en la Comisión Europea. Solo consulta; no cambia la factura.
(function () {
  var boton = document.getElementById("vies-boton");
  if (!boton) return;
  var resultado = document.getElementById("vies-resultado");
  var csrf = document.querySelector('meta[name="csrf-token"]');
  var cabeceras = Object.assign({ Accept: "application/json" }, csrf ? { "X-CSRFToken": csrf.content } : {});
  boton.addEventListener("click", function () {
    boton.disabled = true;
    resultado.textContent = "…";
    fetch(boton.dataset.url, { method: "POST", credentials: "same-origin", headers: cabeceras })
      .then(function (r) { return r.json(); })
      .then(function (p) {
        if (p.valido === null) resultado.textContent = p.error;
        else resultado.textContent = (p.valido ? boton.dataset.leyendaOk : boton.dataset.leyendaNo) + (p.nombre ? " · " + p.nombre : "");
      })
      .catch(function () { resultado.textContent = boton.dataset.leyendaNo; })
      .then(function () { boton.disabled = false; });
  });
})();
