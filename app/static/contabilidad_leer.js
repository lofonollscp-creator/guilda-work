// «Leer con IA»: lee de una en una las facturas por leer (cada lectura es una consulta al modelo) y enseña el avance; al terminar recarga la lista.
(function () {
  const boton = document.getElementById("leer-todas");
  if (!boton) return;
  const estado = document.getElementById("leer-todas-estado");
  const ids = (boton.dataset.ids || "").split(",").filter(Boolean);
  const csrf = document.querySelector('meta[name="csrf-token"]');
  boton.addEventListener("click", async function () {
    boton.disabled = true;
    let bien = 0, mal = 0, ultimoError = "";
    for (let i = 0; i < ids.length; i++) {
      estado.textContent = (i + 1) + " / " + ids.length + "…";
      try {
        const r = await fetch(boton.dataset.url.replace("/0/", "/" + ids[i] + "/"), { method: "POST", credentials: "same-origin",
          headers: Object.assign({ Accept: "application/json" }, csrf ? { "X-CSRFToken": csrf.content } : {}) });
        const d = await r.json();
        if (d.ok) bien++; else { mal++; ultimoError = d.error || ""; }
      } catch (e) { mal++; ultimoError = ""; }
    }
    estado.textContent = bien + " ✓" + (mal ? " · " + mal + " ✗ " + ultimoError : "");
    setTimeout(function () { window.location.reload(); }, mal ? 3500 : 800);
  });
})();
