// Constructor de reglas de automatización: muestra solo lo que corresponde al disparador y al tipo de cada acción.
// Sin JavaScript todo queda visible y el servidor ignora lo que no toca, así que el formulario sigue funcionando.
(function () {
  var formulario = document.getElementById("constructor-regla");
  if (!formulario) return;
  var disparador = formulario.querySelector("[name=disparador]");

  function mostrar(elemento, visible) {
    elemento.hidden = !visible;
    elemento.querySelectorAll("input, select, textarea").forEach(function (campo) { campo.disabled = !visible; });
  }

  function actualizarDisparador() {
    var actual = disparador.value;
    formulario.querySelectorAll("[data-solo-disparador]").forEach(function (bloque) {
      mostrar(bloque, bloque.getAttribute("data-solo-disparador") === actual);
    });
    var conTarea = ["tarea.vencida", "tarea.creada", "tarea.estado", "recurrencia.generada"].indexOf(actual) !== -1;
    formulario.querySelectorAll("[data-tipo-accion] option").forEach(function (opcion) {
      if (["comentar", "fijar_fecha", "asignar", "pedir_revision"].indexOf(opcion.value) !== -1) opcion.disabled = !conTarea;
    });
  }

  function actualizarFila(fila) {
    var tipo = fila.querySelector("[data-tipo-accion]").value;
    fila.querySelectorAll("[data-solo-tipo]").forEach(function (bloque) {
      mostrar(bloque, bloque.getAttribute("data-solo-tipo") === tipo);
    });
  }

  disparador.addEventListener("change", function () { actualizarDisparador(); formulario.querySelectorAll("[data-fila-accion]").forEach(actualizarFila); });
  formulario.querySelectorAll("[data-fila-accion]").forEach(function (fila) {
    fila.querySelector("[data-tipo-accion]").addEventListener("change", function () { actualizarFila(fila); });
  });
  actualizarDisparador();
  formulario.querySelectorAll("[data-fila-accion]").forEach(actualizarFila);
})();
