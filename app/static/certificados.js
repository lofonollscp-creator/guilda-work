// Alta rápida de certificados: ayudas que no son imprescindibles (el formulario funciona igual sin JavaScript).
//  - Al elegir tipo o fecha de emisión, propone la fecha de caducidad habitual del tipo (data-anios), sin pisar lo que la persona haya escrito.
//  - Al elegir un cliente, enseña su nombre y NIF como valor por defecto del titular.
(function () {
  "use strict";
  const form = document.getElementById("cert-alta");
  if (!form) return;
  const tipo = form.querySelector("#al-tipo"), emitido = form.querySelector("#al-emitido"), caduca = form.querySelector("#al-caduca");
  const cliente = form.querySelector("#al-cliente"), titular = form.querySelector("#al-titular"), nif = form.querySelector("#al-nif");
  let tocada = false;                                        // la persona ha escrito la caducidad a mano: no se pisa
  const pad = (n) => String(n).padStart(2, "0");

  function proponer() {
    if (tocada || !emitido.value) return;
    const anios = parseInt(tipo.options[tipo.selectedIndex].dataset.anios || "", 10);
    if (!anios) return;
    const [a, m, d] = emitido.value.split("-").map(Number);
    let fecha = new Date(a + anios, m - 1, d);
    if (fecha.getMonth() !== m - 1) fecha = new Date(a + anios, m - 1, 28);       // 29 de febrero
    caduca.value = fecha.getFullYear() + "-" + pad(fecha.getMonth() + 1) + "-" + pad(fecha.getDate());
    caduca.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function porDefecto() {
    const o = cliente.options[cliente.selectedIndex];
    titular.placeholder = (o && o.dataset.nombre) || titular.dataset.defecto || titular.placeholder;
    nif.placeholder = (o && o.dataset.nif) || nif.dataset.defecto || nif.placeholder;
  }

  titular.dataset.defecto = titular.placeholder;
  nif.dataset.defecto = nif.placeholder;
  caduca.addEventListener("input", () => { tocada = !!caduca.value; });
  tipo.addEventListener("change", proponer);
  emitido.addEventListener("change", () => { tocada = false; proponer(); });
  cliente.addEventListener("change", porDefecto);
  porDefecto();
})();
