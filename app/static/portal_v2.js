// Navegación nueva del portal: tablas como tarjetas en el móvil, menús desplegables de la cabecera (novedades y perfil) y pestaña activa visible. Dos piezas independientes en un solo archivo para no sumar peticiones.
// Tablas del portal en el móvil: cada fila pasa a ser una tarjeta y cada celda lleva su título (el de su columna) delante. Solo pone el atributo data-label; la maqueta la hace portal_v2.css por debajo de 720 px, así que en pantallas grandes no cambia nada.
(function () {
  "use strict";
  function etiquetar(tabla) {
    var cabecera = tabla.querySelectorAll("thead th");
    if (!cabecera.length) return;
    var titulos = Array.prototype.map.call(cabecera, function (th) { return (th.textContent || "").trim(); });
    Array.prototype.forEach.call(tabla.querySelectorAll("tbody tr"), function (fila) {
      Array.prototype.forEach.call(fila.children, function (celda, i) {
        if (celda.tagName === "TD" && titulos[i] && !celda.hasAttribute("data-label")) celda.setAttribute("data-label", titulos[i]);
      });
    });
    tabla.classList.add("pv-tabla-tarjetas");
  }
  Array.prototype.forEach.call(document.querySelectorAll(".portal-v2 .table-wrap > table, .portal-v2 table.portal-tabla-situacion"), etiquetar);
})();
// Menús desplegables de la cabecera (novedades y perfil) y pestañas del portal nuevo: Esc o un clic fuera cierran el menú (y Esc devuelve el foco al botón), al salir del menú con el teclado se cierra solo, y la pestaña activa se ve aunque la fila haga scroll en el móvil.
(function () {
  "use strict";
  var menus = Array.prototype.slice.call(document.querySelectorAll("details.pv-desplegable"));
  menus.forEach(function (menu) {
    var resumen = menu.querySelector("summary");
    resumen.setAttribute("aria-haspopup", "true");
    resumen.setAttribute("aria-expanded", "false");
    menu.addEventListener("toggle", function () {
      resumen.setAttribute("aria-expanded", menu.open ? "true" : "false");
      if (menu.open) menus.forEach(function (otro) { if (otro !== menu) otro.open = false; });      // solo uno abierto a la vez
    });
    menu.addEventListener("focusout", function (e) { if (menu.open && e.relatedTarget && !menu.contains(e.relatedTarget)) menu.open = false; });
  });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    menus.forEach(function (menu) { if (menu.open) { menu.open = false; menu.querySelector("summary").focus(); } });
  });
  document.addEventListener("click", function (e) { menus.forEach(function (menu) { if (menu.open && !menu.contains(e.target)) menu.open = false; }); });
  function mostrarActiva() {
    var activa = document.querySelector(".pv-pestanas a[aria-current]");
    if (!activa) return;
    var fila = activa.parentElement;
    var izq = activa.getBoundingClientRect().left - fila.getBoundingClientRect().left + fila.scrollLeft;
    fila.scrollLeft = Math.max(0, izq - (fila.clientWidth - activa.offsetWidth) / 2);           // solo la fila: la página no se mueve
  }
  mostrarActiva();
  window.addEventListener("load", mostrarActiva);                                              // otra vez cuando ya están las fuentes y las medidas son las definitivas
})();
