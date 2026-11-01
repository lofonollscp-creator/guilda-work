// Tema del centro de desarrolladores: sistema (por defecto) · claro · oscuro. Se aplica antes de pintar para evitar el parpadeo.
(function () {
  var raiz = document.documentElement, clave = "guilda-docs-tema";
  function leer() { try { var t = localStorage.getItem(clave); return t === "claro" || t === "oscuro" ? t : "sistema"; } catch (e) { return "sistema"; } }
  function aplicar(t) {
    if (t === "sistema") raiz.removeAttribute("data-theme"); else raiz.setAttribute("data-theme", t === "claro" ? "light" : "dark");
    raiz.setAttribute("data-docs-tema", t);
    var b = document.getElementById("docs-tema");
    if (b) { var tx = b.querySelector(".docs-tema-texto"), ic = b.querySelector(".docs-tema-icono"); if (tx) tx.textContent = t === "sistema" ? "Sistema" : (t === "claro" ? "Claro" : "Oscuro"); if (ic) ic.textContent = t === "sistema" ? "◐" : (t === "claro" ? "☀" : "☾"); b.title = "Tema: " + t; }
  }
  aplicar(leer());
  document.addEventListener("DOMContentLoaded", function () {
    aplicar(leer());
    var b = document.getElementById("docs-tema");
    if (b) b.addEventListener("click", function () {
      var sig = { sistema: "claro", claro: "oscuro", oscuro: "sistema" }[leer()];
      try { if (sig === "sistema") localStorage.removeItem(clave); else localStorage.setItem(clave, sig); } catch (e) { /* sin almacenamiento */ }
      aplicar(sig);
    });
  });
})();
