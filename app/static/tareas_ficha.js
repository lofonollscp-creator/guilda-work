// Lista de tareas con ficha: al tocar el título de una tarea (en pantallas anchas) su ficha se abre en el panel de la derecha sin salir de la lista.
// En pantallas estrechas, o con Ctrl/Cmd/clic central, el título sigue siendo un enlace normal a la tarea. La ficha es un fragmento del servidor
// (/tareas/<id>/ficha): el HTML ya viene escapado, aquí solo se coloca.
(function () {
  var panel = document.getElementById("tareas-ficha");
  if (!panel) return;
  var ancha = window.matchMedia("(min-width: 1400px)");
  var actual = null;

  function marcar(fila) {
    document.querySelectorAll(".tarea-fila.es-seleccionada").forEach(function (f) { f.classList.remove("es-seleccionada"); });
    if (fila) fila.classList.add("es-seleccionada");
  }

  function abrir(enlace, enfocar) {
    var fila = enlace.closest(".tarea-fila");
    var url = enlace.getAttribute("data-ficha");
    if (!url || url === actual) return;
    actual = url;
    marcar(fila);
    fetch(url, { headers: { "X-Requested-With": "fetch" }, credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(function (html) {
        if (actual !== url) return;
        panel.innerHTML = html;
        if (enfocar) panel.focus({ preventScroll: true });
      })
      .catch(function () { actual = null; window.location.href = enlace.href; });
  }

  document.addEventListener("click", function (e) {
    var enlace = e.target.closest("a[data-ficha]");
    if (!enlace || !ancha.matches || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    abrir(enlace, true);
  });

  panel.setAttribute("tabindex", "-1");
  var primera = document.querySelector("a[data-ficha]");
  if (primera && ancha.matches) abrir(primera, false);
})();
