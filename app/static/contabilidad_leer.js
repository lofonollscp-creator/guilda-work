// «Leerlas todas con IA»: pone la lectura en la cola del servidor (sigue aunque se cierre la página) y enseña el avance. Al terminar recarga la lista.
(function () {
  var boton = document.getElementById("leer-todas");
  if (!boton) return;
  var estado = document.getElementById("leer-todas-estado");
  var barra = document.getElementById("leer-todas-barra");
  var csrf = document.querySelector('meta[name="csrf-token"]');
  var cabeceras = Object.assign({ Accept: "application/json" }, csrf ? { "X-CSRFToken": csrf.content } : {});
  function texto(clave, valores) {
    var t = boton.getAttribute("data-txt-" + clave) || "";
    Object.keys(valores || {}).forEach(function (k) { t = t.replace("%(" + k + ")s", valores[k]); });
    return t;
  }
  function seguir(lote) {
    fetch(boton.dataset.urlEstado.replace(/\/0$/, "/" + encodeURIComponent(lote)), { credentials: "same-origin", headers: cabeceras })
      .then(function (r) { return r.json(); })
      .then(function (p) {
        barra.hidden = false; barra.max = Math.max(1, p.total); barra.value = p.hechas + p.errores;
        if (p.terminado) {
          estado.textContent = texto("fin", { hechas: p.hechas, errores: p.errores });
          setTimeout(function () { window.location.reload(); }, p.errores ? 3500 : 900);
        } else {
          estado.textContent = p.pausa_hasta ? texto("pausa", { hora: p.pausa_hasta.slice(11, 16) }) : texto("en-marcha", { hechas: p.hechas + p.errores, total: p.total });
          setTimeout(function () { seguir(lote); }, 2000);
        }
      })
      .catch(function () { setTimeout(function () { seguir(lote); }, 4000); });
  }
  boton.addEventListener("click", function () {
    boton.disabled = true;
    var datos = new FormData();
    if (boton.dataset.cliente) datos.set("cliente_id", boton.dataset.cliente);
    fetch(boton.dataset.urlCola, { method: "POST", body: datos, credentials: "same-origin", headers: cabeceras })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) { estado.textContent = d.error || texto("error"); boton.disabled = false; return; }
        if (!d.total) { window.location.reload(); return; }
        seguir(d.lote);
      })
      .catch(function () { estado.textContent = texto("error"); boton.disabled = false; });
  });
})();
