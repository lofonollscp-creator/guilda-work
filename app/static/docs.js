// Guía para desarrolladores (/docs): copiar bloques de código + resaltar
// la sección activa en la tabla de contenidos al hacer scroll. Sin
// dependencias externas, a propósito (mismo criterio "autoalojado" del
// resto de la app).

document.querySelectorAll(".docs-code-copiar").forEach(function (boton) {
  boton.addEventListener("click", function () {
    var textoOriginal = boton.textContent;

    function marcarCopiado() {
      boton.textContent = "Copiado";
      boton.classList.add("is-copiado");
      setTimeout(function () {
        boton.textContent = textoOriginal;
        boton.classList.remove("is-copiado");
      }, 1500);
    }

    function copiaManual() {
      // Respaldo si el Clipboard API no está disponible/permitido
      // (contexto no seguro, permiso denegado...).
      var area = document.createElement("textarea");
      area.value = boton.dataset.code;
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      try {
        document.execCommand("copy");
        marcarCopiado();
      } catch (e) {
        boton.textContent = "Error al copiar";
        setTimeout(function () { boton.textContent = textoOriginal; }, 1500);
      }
      document.body.removeChild(area);
    }

    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(boton.dataset.code).then(marcarCopiado, copiaManual);
    } else {
      copiaManual();
    }
  });
});

(function () {
  var enlacesToc = document.querySelectorAll(".docs-toc a");
  if (!enlacesToc.length) return;
  var titulos = Array.from(enlacesToc).map(function (a) {
    return document.getElementById(a.getAttribute("href").slice(1));
  }).filter(Boolean);

  function actualizar() {
    var actual = null;
    titulos.forEach(function (h) {
      if (h.getBoundingClientRect().top < 100) actual = h;
    });
    enlacesToc.forEach(function (a) {
      a.classList.toggle("is-active", actual && a.getAttribute("href") === "#" + actual.id);
    });
  }

  document.addEventListener("scroll", actualizar, { passive: true });
  actualizar();
})();
