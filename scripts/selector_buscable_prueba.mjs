// Prueba de comportamiento de app/static/selector_buscable.js con jsdom (se ejecuta con scripts/comprobar_selector_buscable.sh).
import { JSDOM } from "jsdom";
import { readFileSync } from "node:fs";

const opciones = (n, prefijo = "Cliente") => Array.from({ length: n }, (_, i) => `<option value="${i}">${prefijo} ${i}</option>`).join("");
const html = `<!doctype html><body>
<form id="f"><select id="grande" name="c">${opciones(40)}<option value="x"><img src=x onerror=alert(1)> Ñandú Árbol</option></select></form>
<select id="pequeno">${opciones(3)}</select>
<select id="multiple" multiple>${opciones(20)}</select>
<select id="sin" data-sin-buscador>${opciones(20)}</select>
<select id="forzado" data-buscable>${opciones(2)}</select>
<select id="grupos">${"<optgroup label='Uno'>" + opciones(4) + "</optgroup><optgroup label='Dos'>" + opciones(4, "Otro") + "</optgroup>"}</select>
</body>`;
const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true });
const w = dom.window;
w.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {} });
w.Element.prototype.scrollIntoView = () => {};
w.eval(readFileSync(new URL("../app/static/selector_buscable.js", import.meta.url), "utf8"));
const doc = w.document;
await new Promise((r) => setTimeout(r, 50));   // DOMContentLoaded
let fallos = 0;
const ok = (cond, msg) => { if (!cond) { fallos++; console.error("FALLO:", msg); } else console.log("ok:", msg); };
const tecla = (el, key, extra = {}) => el.dispatchEvent(new w.KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...extra }));
const panel = () => doc.querySelector(".selbus-panel");
const visibles = () => [...doc.querySelectorAll(".selbus-opcion")].map((e) => e.textContent);

ok(doc.getElementById("grande").classList.contains("selbus-origen"), "un select con 41 opciones se mejora");
ok(doc.getElementById("pequeno").classList.contains("selbus-origen"), "uno con 3 opciones también usa la lista propia (sistema de diseño)");
{ const p = doc.getElementById("pequeno"); p.dispatchEvent(new w.MouseEvent("mousedown", { bubbles: true, cancelable: true, button: 0 }));
  ok(!!doc.querySelector(".selbus-panel.selbus-sin-buscador") && doc.querySelectorAll(".selbus-opcion").length === 3, "con pocas opciones el panel no muestra campo de búsqueda");
  doc.querySelector(".selbus-opcion:nth-child(2)").click();
  ok(p.value === "1" && !doc.querySelector(".selbus-panel"), "elegir en la lista pequeña cambia el valor y cierra"); }
{ const gr = doc.getElementById("grande"); gr.dispatchEvent(new w.MouseEvent("mousedown", { bubbles: true, cancelable: true, button: 0 }));
  ok(!doc.querySelector(".selbus-panel.selbus-sin-buscador"), "con muchas opciones el buscador sí se ve"); gr.dispatchEvent(new w.KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true })); }
ok(!doc.getElementById("multiple").classList.contains("selbus-origen"), "los multiple se quedan nativos");
ok(!doc.getElementById("sin").classList.contains("selbus-origen"), "data-sin-buscador se respeta");
ok(doc.getElementById("forzado").classList.contains("selbus-origen"), "data-buscable fuerza la mejora");

const g = doc.getElementById("grande");
ok(g.getAttribute("aria-haspopup") === "listbox" && g.getAttribute("aria-expanded") === "false", "aria en el select cerrado");
const md = new w.MouseEvent("mousedown", { bubbles: true, cancelable: true, button: 0 });
g.dispatchEvent(md);
ok(md.defaultPrevented, "mousedown no abre la lista nativa");
ok(panel() && g.getAttribute("aria-expanded") === "true", "se abre el panel");
ok(doc.querySelector(".selbus-buscar").getAttribute("role") === "combobox", "campo con role combobox");
ok(visibles().length === 41, "muestra todas las opciones sin filtro");

const campo = doc.querySelector(".selbus-buscar");
campo.value = "cliente 3"; campo.dispatchEvent(new w.Event("input", { bubbles: true }));
ok(visibles().length === 13 && visibles().every((t) => t.includes("3")) && visibles().includes("Cliente 3"), "filtra por varias palabras (todas deben aparecer)");
campo.value = "NANDU arbol"; campo.dispatchEvent(new w.Event("input", { bubbles: true }));
ok(visibles().length === 1 && visibles()[0].includes("Ñandú"), "ignora acentos y mayúsculas (ñ→n)");
ok(!doc.querySelector(".selbus-lista img"), "el texto de una opción nunca se interpreta como HTML");
campo.value = "zzz"; campo.dispatchEvent(new w.Event("input", { bubbles: true }));
ok(!!doc.querySelector(".selbus-vacio") && visibles().length === 0, "sin coincidencias muestra el aviso");

let cambios = 0; g.addEventListener("change", () => cambios++);
campo.value = "cliente 7"; campo.dispatchEvent(new w.Event("input", { bubbles: true }));
tecla(campo, "ArrowDown"); tecla(campo, "Enter");
ok(g.options[g.selectedIndex].textContent.includes("7"), "Enter elige la opción activa (" + g.options[g.selectedIndex].textContent + ")");
ok(!panel() && g.getAttribute("aria-expanded") === "false", "se cierra al elegir");
ok(cambios === 1, "lanza un solo change");
ok(new w.FormData(doc.getElementById("f")).get("c") === g.value, "el valor viaja en el formulario");

tecla(g, "ArrowDown");
ok(!!panel(), "ArrowDown sobre el select abre el panel");
tecla(doc.querySelector(".selbus-buscar"), "Escape");
ok(!panel(), "Escape cierra");
tecla(g, "c");
ok(!!panel() && doc.querySelector(".selbus-buscar").value === "c", "escribir sobre el select abre el panel con esa letra");
doc.querySelector(".selbus-buscar").dispatchEvent(new w.KeyboardEvent("keydown", { key: "Tab", bubbles: true }));
ok(!panel(), "Tab cierra");

const gr = doc.getElementById("grupos");
gr.dispatchEvent(new w.MouseEvent("mousedown", { bubbles: true, cancelable: true, button: 0 }));
ok(doc.querySelectorAll(".selbus-grupo").length === 2, "muestra las cabeceras de grupo");
tecla(doc.querySelector(".selbus-buscar"), "Escape");

// select añadido después y select al que se añaden opciones
const nuevo = doc.createElement("select"); nuevo.innerHTML = opciones(10); doc.body.append(nuevo);
const poco = doc.createElement("select"); poco.innerHTML = opciones(2); doc.body.append(poco);
await new Promise((r) => setTimeout(r, 30));
ok(nuevo.classList.contains("selbus-origen"), "mejora los select que aparecen después");
poco.insertAdjacentHTML("beforeend", opciones(8, "Más")); await new Promise((r) => setTimeout(r, 30));
ok(poco.classList.contains("selbus-origen"), "mejora un select cuando le llegan opciones");

const dis = doc.createElement("select"); dis.disabled = true; dis.innerHTML = opciones(10); doc.body.append(dis); await new Promise((r) => setTimeout(r, 30));
dis.dispatchEvent(new w.MouseEvent("mousedown", { bubbles: true, cancelable: true, button: 0 }));
ok(!panel(), "un select deshabilitado no abre el panel");

console.log(fallos ? `${fallos} fallos` : "todo correcto");
process.exit(fallos ? 1 : 0);
