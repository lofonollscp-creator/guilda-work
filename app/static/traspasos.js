// La acción del formulario «asignar responsable» lleva el id del cliente elegido en la URL.
(function () {
  var f = document.getElementById("asignar-responsable");
  if (!f) return;
  var sel = document.getElementById("rs-cliente");
  function ajustar() { f.action = f.dataset.accion.replace(/\/0\/responsable$/, "/" + sel.value + "/responsable"); }
  sel.addEventListener("change", ajustar);
  ajustar();
})();
