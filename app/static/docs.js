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

// --- Buscador (Ctrl/Cmd+K) ------------------------------------------------

(function () {
  var boton = document.getElementById("docs-buscar-abrir");
  var overlay = document.getElementById("docs-buscar-overlay");
  var input = document.getElementById("docs-buscar-input");
  var lista = document.getElementById("docs-buscar-resultados");
  var vacio = document.getElementById("docs-buscar-vacio");
  var indiceEl = document.getElementById("docs-indice-busqueda");
  if (!boton || !overlay || !indiceEl) return;

  var indice = JSON.parse(indiceEl.textContent || "[]");
  var activo = -1;
  var resultadosActuales = [];

  function normaliza(s) {
    return s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
  }

  function buscar(consulta) {
    var q = normaliza(consulta.trim());
    if (!q) return [];
    var terminos = q.split(/\s+/);
    return indice
      .map(function (entrada) {
        var pajar = normaliza(entrada.titulo + " " + entrada.contexto + " " + entrada.texto);
        var puntos = 0;
        for (var i = 0; i < terminos.length; i++) {
          if (terminos[i] === "") continue;
          if (pajar.indexOf(terminos[i]) === -1) return null;
          puntos += normaliza(entrada.titulo).indexOf(terminos[i]) !== -1 ? 3 : 1;
        }
        return { entrada: entrada, puntos: puntos };
      })
      .filter(Boolean)
      .sort(function (a, b) { return b.puntos - a.puntos; })
      .slice(0, 30)
      .map(function (r) { return r.entrada; });
  }

  function pintar(resultados) {
    resultadosActuales = resultados;
    activo = resultados.length ? 0 : -1;
    lista.innerHTML = "";
    vacio.hidden = resultados.length !== 0 || !input.value.trim();
    resultados.forEach(function (r, i) {
      var li = document.createElement("li");
      var a = document.createElement("a");
      a.href = r.href;
      a.className = i === 0 ? "is-activo" : "";
      a.innerHTML =
        '<span class="r-contexto">' + r.contexto + '</span>' +
        '<span class="r-titulo">' + r.titulo + '</span>' +
        (r.texto ? '<span class="r-texto">' + r.texto + '</span>' : "");
      li.appendChild(a);
      lista.appendChild(li);
    });
  }

  function marcarActivo() {
    var enlaces = lista.querySelectorAll("a");
    enlaces.forEach(function (a, i) { a.classList.toggle("is-activo", i === activo); });
    if (enlaces[activo]) enlaces[activo].scrollIntoView({ block: "nearest" });
  }

  function abrir() {
    overlay.hidden = false;
    input.value = "";
    pintar(indice.slice(0, 8));
    setTimeout(function () { input.focus(); }, 0);
  }

  function cerrar() {
    overlay.hidden = true;
  }

  boton.addEventListener("click", abrir);

  document.addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      overlay.hidden ? abrir() : cerrar();
    } else if (e.key === "/" && overlay.hidden && document.activeElement.tagName !== "INPUT") {
      e.preventDefault();
      abrir();
    }
  });

  overlay.addEventListener("click", function (e) {
    if (e.target === overlay) cerrar();
  });

  input.addEventListener("input", function () {
    pintar(buscar(input.value));
  });

  input.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      cerrar();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      if (resultadosActuales.length) { activo = (activo + 1) % resultadosActuales.length; marcarActivo(); }
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (resultadosActuales.length) { activo = (activo - 1 + resultadosActuales.length) % resultadosActuales.length; marcarActivo(); }
    } else if (e.key === "Enter") {
      var enlaces = lista.querySelectorAll("a");
      if (enlaces[activo]) { window.location.href = enlaces[activo].getAttribute("href"); }
    }
  });
})();

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
