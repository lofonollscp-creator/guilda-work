// Prueba de comportamiento de app/static/csp_compat.js con jsdom: lo que antes eran atributos on…= ahora son data-*.
import { JSDOM } from "jsdom";
import { readFileSync } from "node:fs";

const html = `<!doctype html><body>
<form id="f1" data-confirmar-envio="¿Seguro?"><button>enviar</button></form>
<form id="f5" data-confirmar-envio="¿Enviar?" data-confirmar-excepto="programar"><button name="programar" id="prog">programar</button><button name="enviar" id="env">enviar</button></form>
<button id="b1" data-confirmar-clic="¿Borrar?">borrar</button>
<form id="f2"><select id="s2" data-autoenviar><option>a</option></select></form>
<form id="f3"><select id="s3" data-autoenviar="submit"><option>a</option></select></form>
<form id="f4"><select id="s4" data-requerido-si-vacio="avisar_en"><option value="">-</option><option value="1">1</option></select><input name="avisar_en"></form>
<a id="a1" href="#cc" data-mostrar="cc">Cc/Cco</a><div id="cc" hidden>campos</div>
<a id="a2" data-accion="imprimir">imprimir</a>
<button id="b3" data-accion="cerrar-creacion-rapida">x</button>
</body>`;
const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true });
const w = dom.window;
let confirmaciones = [], respuestas = [], impresiones = 0, cierres = 0;
w.confirm = (m) => { confirmaciones.push(m); return respuestas.shift() ?? true; };
w.print = () => { impresiones++; };
w.cerrarCreacionRapidaTarea = () => { cierres++; };
w.eval(readFileSync(new URL("../app/static/csp_compat.js", import.meta.url), "utf8"));

let fallos = 0;
const ok = (cond, msg) => { if (!cond) { fallos++; console.error("FALLO:", msg); } else console.log("ok:", msg); };
const doc = w.document;
const esperar = () => new Promise((r) => setTimeout(r, 0));   // la confirmación es asíncrona (diálogo del sistema de diseño)
const enviado = (id) => { let n = 0; const f = doc.getElementById(id); f.addEventListener("submit", (e) => { e.preventDefault(); n++; }); return () => n; };

// 1. confirmar el envío: cancelar no deja pasar el submit a otros listeners; aceptar sí
const n1 = enviado("f1");
doc.getElementById("f1").requestSubmit = function (sub) { this.dispatchEvent(new w.Event("submit", { bubbles: true, cancelable: true })); };
respuestas = [false]; doc.getElementById("f1").dispatchEvent(new w.Event("submit", { bubbles: true, cancelable: true })); await esperar();
ok(confirmaciones.at(-1) === "¿Seguro?" && n1() === 0, "cancelar la confirmación impide el envío");
respuestas = [true]; doc.getElementById("f1").dispatchEvent(new w.Event("submit", { bubbles: true, cancelable: true })); await esperar();
ok(n1() === 1, "aceptar la confirmación deja enviar");

// 1b. data-confirmar-excepto: el botón «programar» no pregunta
const f5 = doc.getElementById("f5"); let n5 = 0, preguntas5 = confirmaciones.length;
f5.addEventListener("submit", (e) => { e.preventDefault(); n5++; });
const ev = new w.Event("submit", { bubbles: true, cancelable: true }); ev.submitter = doc.getElementById("prog"); f5.dispatchEvent(ev); await esperar();
ok(n5 === 1 && confirmaciones.length === preguntas5, "el botón exceptuado envía sin preguntar");

// 2. confirmar un clic
let seguido = 0; doc.getElementById("b1").addEventListener("click", () => seguido++);
respuestas = [false]; doc.getElementById("b1").click(); await esperar(); ok(seguido === 0, "clic cancelado no sigue");
respuestas = [true]; doc.getElementById("b1").click(); await esperar(); ok(seguido === 1, "clic confirmado sigue");

// 3. autoenviar con requestSubmit (jsdom: lo simulamos) y con submit
let rs = 0, sb = 0;
doc.getElementById("f2").requestSubmit = () => { rs++; };
doc.getElementById("f3").submit = () => { sb++; };
doc.getElementById("s2").dispatchEvent(new w.Event("change", { bubbles: true }));
doc.getElementById("s3").dispatchEvent(new w.Event("change", { bubbles: true }));
ok(rs === 1 && sb === 1, "data-autoenviar usa requestSubmit y data-autoenviar=submit usa submit");

// 4. obligatorio si vacío
const s4 = doc.getElementById("s4"), campo = doc.querySelector("#f4 input");
s4.value = ""; s4.dispatchEvent(new w.Event("change", { bubbles: true })); ok(campo.required === true, "vacío → obligatorio");
s4.value = "1"; s4.dispatchEvent(new w.Event("change", { bubbles: true })); ok(campo.required === false, "con valor → no obligatorio");

// 5. mostrar, imprimir y cerrar
doc.getElementById("a1").click();
ok(doc.getElementById("cc").hidden === false && doc.getElementById("a1").hidden === true, "data-mostrar muestra el destino y oculta el enlace");
doc.getElementById("a2").click(); ok(impresiones === 1, "data-accion=imprimir");
doc.getElementById("b3").click(); ok(cierres === 1, "data-accion=cerrar-creacion-rapida");

if (fallos) { console.error(fallos + " fallo(s)"); process.exit(1); }
console.log("csp_compat.js: todo correcto");
