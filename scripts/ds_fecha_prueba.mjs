// Prueba de comportamiento de app/static/ds_fecha.js (selector de fecha del sistema de diseño) con jsdom.
import { JSDOM } from "jsdom";
import { readFileSync } from "node:fs";

const html = `<!doctype html><html lang="es"><body>
<form id="f"><input type="date" id="d" name="desde" value="2026-10-12"><input type="date" id="h" name="hasta"></form>
<input type="date" id="rango" min="2026-10-10" max="2026-10-20" value="2026-10-15">
<input type="date" id="nat" data-nativo>
<input type="datetime-local" id="dt" value="2026-10-12T08:30">
<input type="time" id="t" value="09:15">
<input type="date" id="req" required value="2026-10-01">
</body></html>`;
const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true });
const w = dom.window;
w.GUILDA_I18N = { dsHoy: "Hoy", dsBorrar: "Borrar", dsAceptar: "Aceptar" };
w.eval(readFileSync(new URL("../app/static/ds_fecha.js", import.meta.url), "utf8"));
const doc = w.document;
let fallos = 0;
const ok = (c, m) => { if (!c) { fallos++; console.error("FALLO:", m); } else console.log("ok:", m); };
const abrir = (id) => doc.getElementById(id).dispatchEvent(new w.MouseEvent("mousedown", { bubbles: true, cancelable: true, button: 0 }));
const panel = () => doc.querySelector(".ds-cal");
const dia = (f) => doc.querySelector(`.ds-cal-dia[data-fecha="${f}"]`);
const cuenta = (id) => { const el = doc.getElementById(id); const n = { input: 0, change: 0 }; el.addEventListener("input", () => n.input++); el.addEventListener("change", () => n.change++); return n; };

// 1. abre con el mes del valor y marca el día elegido y hoy
abrir("d");
ok(panel() && panel().querySelector(".ds-cal-titulo").textContent.toLowerCase().includes("octubre"), "abre en el mes del valor actual");
ok(dia("2026-10-12").classList.contains("elegido") && dia("2026-10-12").getAttribute("aria-selected") === "true", "marca el día elegido");
ok(panel().querySelectorAll(".ds-cal-dia").length === 42 && panel().querySelectorAll("[role=columnheader]").length === 7, "42 días y 7 cabeceras de semana");
ok(panel().querySelector(".ds-cal-sem").textContent.toLowerCase().startsWith("lu"), "la semana empieza en lunes");

// 2. elegir un día rellena el campo, dispara input y change y cierra
const n = cuenta("d");
dia("2026-10-20").click();
ok(doc.getElementById("d").value === "2026-10-20" && n.input === 1 && n.change === 1 && !panel(), "elegir un día rellena, avisa y cierra");

// 3. navegación de meses
abrir("d"); panel().querySelectorAll(".ds-cal-nav")[1].click();
ok(panel().querySelector(".ds-cal-titulo").textContent.toLowerCase().includes("noviembre"), "el botón siguiente avanza un mes");
panel().querySelectorAll(".ds-cal-nav")[0].click(); panel().querySelectorAll(".ds-cal-nav")[0].click();
ok(panel().querySelector(".ds-cal-titulo").textContent.toLowerCase().includes("septiembre"), "el botón anterior retrocede");
w.GuildaFecha.cerrar();

// 4. min y max deshabilitan los días fuera de rango y no se pueden elegir
abrir("rango");
ok(dia("2026-10-09").disabled && dia("2026-10-21").disabled && !dia("2026-10-15").disabled, "min/max deshabilitan los días fuera de rango");
dia("2026-10-09").click();
ok(doc.getElementById("rango").value === "2026-10-15" && panel(), "un día deshabilitado no se elige");
w.GuildaFecha.cerrar();

// 5. teclado: Esc cierra y devuelve el foco; flechas mueven el día; AvPág cambia de mes
abrir("d");
const activo = () => doc.activeElement;
activo().dispatchEvent(new w.KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true, cancelable: true }));
ok(activo().classList.contains("ds-cal-dia") && activo().dataset.fecha === "2026-10-21", "→ mueve el foco al día siguiente");
activo().dispatchEvent(new w.KeyboardEvent("keydown", { key: "PageDown", bubbles: true, cancelable: true }));
ok(activo().dataset.fecha === "2026-11-21", "AvPág pasa al mes siguiente");
activo().dispatchEvent(new w.KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));
ok(!panel() && doc.activeElement === doc.getElementById("d"), "Esc cierra y devuelve el foco al campo");

// 6. atajos de periodo cuando hay desde/hasta en el mismo formulario
abrir("d");
const chips = [...panel().querySelectorAll(".ds-cal-periodo")];
ok(chips.length === 5, "hay 5 atajos de periodo con desde/hasta");
chips.find((c) => /mes/i.test(c.textContent) && !/pasado/i.test(c.textContent)).click();
const d1 = doc.getElementById("d").value, d2 = doc.getElementById("h").value;
ok(/^\d{4}-\d{2}-01$/.test(d1) && d2 > d1 && d2.slice(0, 7) === d1.slice(0, 7), "«Este mes» rellena desde y hasta con el primer y último día del mes");
abrir("rango"); ok(panel().querySelectorAll(".ds-cal-periodo").length === 0, "sin pareja desde/hasta no hay atajos");
w.GuildaFecha.cerrar();

// 7. fecha y hora: la hora se confirma con Aceptar
abrir("dt");
ok(panel().querySelectorAll(".ds-cal-num").length === 2 && panel().querySelector(".ds-cal-num").value === "08", "datetime-local muestra la hora actual");
dia("2026-10-14").click();
ok(doc.getElementById("dt").value === "2026-10-12T08:30", "elegir el día no escribe todavía");
const num = panel().querySelectorAll(".ds-cal-num"); num[0].value = "17"; num[0].dispatchEvent(new w.Event("input")); num[1].value = "45"; num[1].dispatchEvent(new w.Event("input"));
[...panel().querySelectorAll("button")].find((b) => b.textContent === "Aceptar").click();
ok(doc.getElementById("dt").value === "2026-10-14T17:45" && !panel(), "Aceptar escribe fecha y hora");

// 8. solo hora
abrir("t");
ok(!panel().querySelector(".ds-cal-rejilla") && panel().querySelectorAll(".ds-cal-num").length === 2, "time solo muestra la hora");
w.GuildaFecha.cerrar();

// 9. borrar (salvo si es obligatorio) y data-nativo
abrir("d"); [...panel().querySelectorAll("button")].find((b) => b.textContent === "Borrar").click();
ok(doc.getElementById("d").value === "", "Borrar vacía el campo");
abrir("req"); ok(![...panel().querySelectorAll("button")].some((b) => b.textContent === "Borrar"), "un campo obligatorio no se puede borrar");
w.GuildaFecha.cerrar();
abrir("nat"); ok(!panel(), "data-nativo no se mejora");

if (fallos) { console.error(fallos + " fallo(s)"); process.exit(1); }
console.log("ds_fecha.js: todo correcto");
