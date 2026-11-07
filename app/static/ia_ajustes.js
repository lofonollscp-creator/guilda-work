// Ajustes del Asistente IA: «Probar clave y modelo», lista de modelos de la cuenta y qué campos enseñar según el proveedor.
(function () {
  const csrf = document.querySelector('meta[name="csrf-token"]');
  const cabeceras = Object.assign({ Accept: "application/json" }, csrf ? { "X-CSRFToken": csrf.content } : {});

  document.querySelectorAll("[data-ia-proveedor-form]").forEach(function (form) {
    const esDespacho = form.dataset.ambito === "despacho";
    const selector = form.querySelector("[data-ia-proveedor]");
    const proveedor = function () { return esDespacho ? form.dataset.proveedor : (selector ? selector.value : "openrouter"); };
    const resultado = form.querySelector("[data-ia-resultado]");

    function ajustarPersonal() {
      if (!selector) return;
      const opcion = selector.options[selector.selectedIndex];
      const esOpenRouter = selector.value === "openrouter";
      form.querySelectorAll("[data-ia-solo-openrouter]").forEach(function (e) { e.hidden = !esOpenRouter; });
      const claves = parseInt(opcion.dataset.claves || "0", 10);
      const estado = form.querySelector("[data-ia-estado-claves]");
      if (estado) estado.textContent = claves ? (claves === 1 ? "Ya tienes 1 clave guardada de este proveedor." : "Ya tienes " + claves + " claves guardadas de este proveedor.") : "Todavía no tienes claves propias de este proveedor.";
      const borrar = form.querySelector("[data-ia-borrar]");
      if (borrar) borrar.hidden = !claves;
      const area = form.querySelector("#ia-claves");
      if (area && opcion.dataset.ejemplo) area.placeholder = opcion.dataset.ejemplo + " · deja en blanco para no cambiar las guardadas";
    }
    if (selector) { selector.addEventListener("change", ajustarPersonal); ajustarPersonal(); }

    const probar = form.querySelector("[data-ia-probar]");
    if (probar) probar.addEventListener("click", async function () {
      const datos = new FormData();
      datos.set("proveedor", proveedor());
      datos.set("ambito", form.dataset.ambito);
      const modelo = esDespacho ? (form.querySelector('[name="modelo_facturas"]').value || form.querySelector('[name="modelo_asistente"]').value) : form.querySelector('[name="modelo_personalizado"]').value || (form.querySelector('[name="modelo"]') || {}).value;
      datos.set("modelo", modelo || "");
      const clave = form.querySelector(esDespacho ? '[name="claves"]' : '[name="api_keys"]');
      datos.set("clave", clave ? clave.value : "");
      const url = form.querySelector('[name="url_base"]');
      if (url) datos.set("url_base", url.value);
      probar.disabled = true;
      resultado.textContent = "Probando…";
      try {
        const r = await fetch(form.dataset.urlProbar, { method: "POST", body: datos, credentials: "same-origin", headers: cabeceras });
        const d = await r.json();
        resultado.textContent = d.ok ? "✓ " + d.mensaje : "✗ " + (d.error || "No funcionó.");
      } catch (e) { resultado.textContent = "✗ No se pudo comprobar ahora mismo."; }
      probar.disabled = false;
    });

    const cargar = form.querySelector("[data-ia-cargar-modelos]");
    if (cargar) cargar.addEventListener("click", async function () {
      const lista = form.querySelector("#ia-modelos-lista");
      cargar.disabled = true;
      try {
        const r = await fetch(form.dataset.urlModelos + "?proveedor=" + encodeURIComponent(proveedor()), { credentials: "same-origin", headers: cabeceras });
        const d = await r.json();
        const ids = Array.isArray(d) ? d.map(function (m) { return m.id; }) : (d.modelos && d.modelos.length ? d.modelos : d.sugeridos || []);
        lista.innerHTML = "";
        ids.forEach(function (id) { const o = document.createElement("option"); o.value = id; lista.appendChild(o); });
        if (resultado) resultado.textContent = d.error ? "✗ " + d.error : ids.length + " modelos disponibles: empieza a escribir para elegir.";
      } catch (e) { if (resultado) resultado.textContent = "✗ No se pudieron cargar los modelos."; }
      cargar.disabled = false;
    });
  });
})();
