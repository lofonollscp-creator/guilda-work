// Editor de correo enriquecido (al estilo New Outlook): una barra de
// herramientas mínima sobre un <div contenteditable>, usando execCommand
// (suficiente para negrita/cursiva/subrayado/listas/enlaces/imágenes sin
// añadir ninguna librería externa). Al enviar el formulario, se vuelca el
// HTML del editor a un campo oculto que es el que de verdad viaja al
// servidor. Se reutiliza tanto en redactar como en el editor de firma.
(function () {
  document.querySelectorAll(".correo-editor").forEach(inicializarEditor);

  function inicializarEditor(editor) {
    const campoOcultoId = editor.dataset.campoOculto || "correo-editor-campo-oculto";
    const campoOculto = document.getElementById(campoOcultoId);
    const form = editor.closest("form");
    const barra = editor.previousElementSibling;
    if (!barra || !barra.classList.contains("correo-editor-toolbar")) return;

    let inputArchivo = null;

    barra.querySelectorAll("[data-cmd]").forEach((boton) => {
      boton.addEventListener("click", () => {
        editor.focus();
        const cmd = boton.dataset.cmd;
        if (cmd === "createLink") {
          const url = window.prompt("URL del enlace:");
          if (url) document.execCommand(cmd, false, url);
        } else if (cmd === "insertImageFile") {
          if (!inputArchivo) {
            inputArchivo = document.createElement("input");
            inputArchivo.type = "file";
            inputArchivo.accept = "image/*";
            inputArchivo.style.display = "none";
            inputArchivo.addEventListener("change", () => {
              const archivo = inputArchivo.files[0];
              if (!archivo) return;
              const lector = new FileReader();
              lector.onload = () => {
                editor.focus();
                document.execCommand("insertImage", false, lector.result);
              };
              lector.readAsDataURL(archivo);
              inputArchivo.value = "";
            });
            document.body.appendChild(inputArchivo);
          }
          inputArchivo.click();
        } else {
          document.execCommand(cmd, false, null);
        }
      });
    });

    if (form && campoOculto) {
      form.addEventListener("submit", () => {
        campoOculto.value = editor.innerHTML;
      });
    }
  }
})();
