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
