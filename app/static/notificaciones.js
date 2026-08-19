// Desplegable de la campana de notificaciones (centro de notificaciones
// unificado, ver app/notificaciones.py + app/rutas_notificaciones.py).
// Mismo patrón que el menú de ajustes de esta misma barra superior
// (sidebar.js): botón que muestra/oculta un panel absoluto, cerrado al
// hacer clic fuera.
(function () {
  const URL_ICONOS = document.body.dataset.urlIconos;
  const boton = document.getElementById("notificaciones-toggle");
  const panel = document.getElementById("notificaciones-panel");
  const lista = document.getElementById("notificaciones-lista");
  const vacio = document.getElementById("notificaciones-vacio");
  const vaciarBtn = document.getElementById("notificaciones-vaciar");
  if (!boton || !panel) return;

  let cargado = false;

  function pintar(items) {
    lista.innerHTML = "";
    vacio.hidden = items.length > 0;
    if (vaciarBtn) vaciarBtn.hidden = items.length === 0;
    items.forEach(function (n) {
      const fila = document.createElement("div");
      fila.className = "notificacion-item" + (n.leido ? "" : " es-no-leida");
      fila.dataset.id = n.id;

      // Contenedor de contenido: <a> si hay URL a la que ir, <div> si no --
      // el botón de eliminar va HERMANO, nunca anidado dentro de un <a>
      // (un <button> dentro de un <a> es HTML inválido).
      const contenido = document.createElement(n.url ? "a" : "div");
      contenido.className = "notificacion-item-contenido";
      if (n.url) contenido.href = n.url;
      const titulo = document.createElement("div");
      titulo.className = "notificacion-item-titulo";
      titulo.textContent = n.titulo;
      const cuerpo = document.createElement("div");
      cuerpo.className = "notificacion-item-cuerpo";
      cuerpo.textContent = n.cuerpo || "";
      const fecha = document.createElement("div");
      fecha.className = "notificacion-item-fecha";
      fecha.textContent = (n.creado_en || "").slice(0, 16).replace("T", " ");
      contenido.appendChild(titulo);
      if (n.cuerpo) contenido.appendChild(cuerpo);
      contenido.appendChild(fecha);
      fila.appendChild(contenido);

      const eliminarBtn = document.createElement("button");
      eliminarBtn.type = "button";
      eliminarBtn.className = "notificacion-item-eliminar";
      eliminarBtn.title = "Eliminar";
      eliminarBtn.setAttribute("aria-label", "Eliminar notificación");
      eliminarBtn.innerHTML = '<svg aria-hidden="true"><use href="' + URL_ICONOS + '#icono-x"></use></svg>';
      eliminarBtn.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        fetch("/notificaciones/" + n.id + "/eliminar", { method: "POST" })
          .then(function () {
            fila.remove();
            if (!lista.children.length) {
              vacio.hidden = false;
              if (vaciarBtn) vaciarBtn.hidden = true;
            }
          })
          .catch(function () {});
      });
      fila.appendChild(eliminarBtn);

      lista.appendChild(fila);
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

  if (vaciarBtn) {
    vaciarBtn.addEventListener("click", function () {
      fetch("/notificaciones/vaciar", { method: "POST" })
        .then(function () {
          lista.innerHTML = "";
          vacio.hidden = false;
          vaciarBtn.hidden = true;
        })
        .catch(function () {});
    });
  }

  document.addEventListener("click", function (e) {
    if (!panel.hidden && !e.target.closest(".notificaciones-menu")) panel.hidden = true;
  });
})();
