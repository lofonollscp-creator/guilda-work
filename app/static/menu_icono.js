document.querySelectorAll("[data-icono-selector]").forEach(function (selector) {
  var input = selector.querySelector("input[type=hidden]");
  selector.querySelectorAll(".menu-icono-opcion").forEach(function (boton) {
    boton.addEventListener("click", function () {
      selector.querySelectorAll(".menu-icono-opcion").forEach(function (b) {
        b.setAttribute("aria-pressed", "false");
      });
      boton.setAttribute("aria-pressed", "true");
      input.value = boton.dataset.icono;
    });
  });
});
