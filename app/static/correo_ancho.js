// Divisor arrastrable entre la lista y el mensaje: cambia el ancho de la lista en vivo y lo guarda en las preferencias al soltar.
(function () {
  const divisor = document.getElementById("correo-divisor");
  const shell = document.querySelector(".correo-shell");
  if (!divisor || !shell) return;
  const MIN = 280, MAX = 720;
  let activo = false;

  function ancho() { const lista = shell.querySelector(".correo-lista-pane"); return lista ? lista.getBoundingClientRect().width : 0; }
  function poner(px) { shell.style.setProperty("--correo-ancho-lista", Math.max(MIN, Math.min(MAX, Math.round(px))) + "px"); }
  function guardar() {
    const cuerpo = new URLSearchParams({ ancho: String(Math.round(ancho())) });
    const csrf = document.querySelector('meta[name="csrf-token"]');
    fetch(shell.dataset.urlAncho, { method: "POST", body: cuerpo, credentials: "same-origin", headers: csrf ? { "X-CSRFToken": csrf.content } : {} });
  }
  divisor.addEventListener("pointerdown", function (e) { activo = true; divisor.setPointerCapture(e.pointerId); e.preventDefault(); });
  divisor.addEventListener("pointermove", function (e) {
    if (!activo) return;
    poner(e.clientX - shell.getBoundingClientRect().left - 220);
  });
  divisor.addEventListener("pointerup", function () { if (activo) { activo = false; guardar(); } });
  divisor.addEventListener("keydown", function (e) {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    poner(ancho() + (e.key === "ArrowRight" ? 20 : -20)); guardar(); e.preventDefault();
  });
})();
