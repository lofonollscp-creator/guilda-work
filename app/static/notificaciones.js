// Desplegable de la campana de notificaciones (centro de notificaciones
// unificado, ver app/notificaciones.py + app/rutas_notificaciones.py).
// Mismo patrón que el menú de ajustes de esta misma barra superior
// (sidebar.js): botón que muestra/oculta un panel absoluto, cerrado al
// hacer clic fuera.
(function () {
  const boton = document.getElementById("notificaciones-toggle");
  const panel = document.getElementById("notificaciones-panel");
  const lista = document.getElementById("notificaciones-lista");
  const vacio = document.getElementById("notificaciones-vacio");
  if (!boton || !panel) return;

  let cargado = false;

  function pintar(items) {
    lista.innerHTML = "";
    vacio.hidden = items.length > 0;
    items.forEach(function (n) {
      const nodo = document.createElement(n.url ? "a" : "div");
      nodo.className = "notificacion-item" + (n.leido ? "" : " es-no-leida");
      if (n.url) nodo.href = n.url;
      const titulo = document.createElement("div");
      titulo.className = "notificacion-item-titulo";
      titulo.textContent = n.titulo;
      const cuerpo = document.createElement("div");
      cuerpo.className = "notificacion-item-cuerpo";
      cuerpo.textContent = n.cuerpo || "";
      const fecha = document.createElement("div");
      fecha.className = "notificacion-item-fecha";
      fecha.textContent = (n.creado_en || "").slice(0, 16).replace("T", " ");
      nodo.appendChild(titulo);
      if (n.cuerpo) nodo.appendChild(cuerpo);
      nodo.appendChild(fecha);
      lista.appendChild(nodo);
    });
  }

  function cargar() {
    fetch("/notificaciones/recientes")
      .then(function (r) { return r.json(); })
      .then(pintar)
      .catch(function () {});
  }

  function quitarBadge() {
    const badge = boton.querySelector(".notificaciones-badge");
    if (badge) badge.remove();
  }

  boton.addEventListener("click", function () {
    const abrir = panel.hidden;
    panel.hidden = !abrir;
    if (abrir) {
      if (!cargado) {
        cargar();
        cargado = true;
      } else {
        cargar(); // refresca por si ha llegado algo nuevo desde la última vez
      }
      quitarBadge();
      fetch("/notificaciones/marcar-leidas", { method: "POST" }).catch(function () {});
    }
  });

  document.addEventListener("click", function (e) {
    if (!panel.hidden && !e.target.closest(".notificaciones-menu")) panel.hidden = true;
  });
})();
