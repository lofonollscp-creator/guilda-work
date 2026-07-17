// Autocompletar de destinatarios recientes en Para/Cc/Cco de correo_redactar.html.
// Al escribir, pide sugerencias a /correo/destinatarios-recientes (debounce) y
// las lista debajo del campo; al hacer clic se añade la dirección al texto,
// separada por coma si ya había algo escrito.
(function () {
  document.querySelectorAll("[data-destinatarios-autocomplete]").forEach((input) => {
    const lista = input.parentElement.querySelector(".correo-autocomplete-lista");
    if (!lista) return;
    let temporizador = null;

    function cerrar() {
      lista.innerHTML = "";
      lista.hidden = true;
    }

    function fragmentoActual() {
      const partes = input.value.split(",");
      return partes[partes.length - 1].trim();
    }

    async function buscar() {
      const q = fragmentoActual();
      if (q.length < 2) {
        cerrar();
        return;
      }
      let respuesta;
      try {
        respuesta = await fetch(`/correo/destinatarios-recientes?q=${encodeURIComponent(q)}`);
      } catch (e) {
        return;
      }
      if (!respuesta.ok) return;
      const sugerencias = await respuesta.json();
      if (!sugerencias.length) {
        cerrar();
        return;
      }
      lista.innerHTML = "";
      sugerencias.forEach((s) => {
        const item = document.createElement("div");
        item.className = "correo-autocomplete-item";
        item.textContent = s.nombre_mostrado ? `${s.nombre_mostrado} <${s.direccion}>` : s.direccion;
        item.addEventListener("mousedown", (ev) => {
          ev.preventDefault();
          const partes = input.value.split(",");
          partes[partes.length - 1] = ` ${s.direccion}`;
          input.value = partes.map((p) => p.trim()).filter(Boolean).join(", ") + ", ";
          cerrar();
          input.focus();
        });
        lista.appendChild(item);
      });
      lista.hidden = false;
    }

    input.addEventListener("input", () => {
      clearTimeout(temporizador);
      temporizador = setTimeout(buscar, 200);
    });
    input.addEventListener("blur", () => setTimeout(cerrar, 150));
  });
})();
