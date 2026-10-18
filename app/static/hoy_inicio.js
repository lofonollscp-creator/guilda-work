// «Necesita tu atención» del inicio: se pide después de pintar la página para no sumar consultas al inicio. El servidor devuelve el panel ya escapado (204 si no hay nada que enseñar).
(function () {
  const panel = document.getElementById("dash-hoy");
  if (!panel) return;
  fetch(panel.dataset.url, { credentials: "same-origin", headers: { "X-Requested-With": "fetch" } })
    .then(function (r) { return r.status === 200 ? r.text() : ""; })
    .then(function (html) {
      if (!html) return;
      panel.innerHTML = html;
      panel.hidden = false;
    })
    .catch(function () {});
})();
