// Ficha de factura: sigue la lectura con IA que está en la cola de fondo y recarga la página al terminar (sin el parámetro ?leyendo).
(function () {
  var el = document.getElementById("leyendo-estado");
  if (!el) return;
  var lote = el.dataset.lote;
  var url = el.dataset.url.replace(/LOTE$/, encodeURIComponent(lote));
  var intentos = 0;
  function limpio() {
    var u = new URL(window.location.href);
    u.searchParams.delete("leyendo");
    return u.toString();
  }
  function seguir() {
    fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (p) {
        if (!p.terminado) {
          if (p.pausa_hasta) el.textContent = (el.dataset.txtPausa || "").replace("%(hora)s", p.pausa_hasta.slice(11, 16));
          intentos += 1; setTimeout(seguir, intentos < 10 ? 1500 : 4000); return; }
        if (p.errores && p.fallos && p.fallos.length) {
          el.textContent = (el.dataset.txtError || "%(error)s").replace("%(error)s", p.fallos[0].error || "");
          return;
        }
        window.location.replace(limpio());
      })
      .catch(function () { setTimeout(seguir, 4000); });
  }
  seguir();
})();
