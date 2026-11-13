/* Comportamentos globais (CSP proíbe JS inline como onsubmit/onclick). */
document.addEventListener("click", function (e) {
  if (e.target.closest("[data-print]")) window.print();
});
// <form data-confirm="Pergunta?"> pede confirmação antes de enviar
document.addEventListener("submit", function (e) {
  var msg = e.target.getAttribute && e.target.getAttribute("data-confirm");
  if (msg && !window.confirm(msg)) e.preventDefault();
});
// "Registrar entrega" na lista de guias: abre a janela apontando para a guia clicada
document.addEventListener("click", function (e) {
  var botao = e.target.closest("[data-entrega]");
  var dlg = document.getElementById("dlg-entrega");
  if (!botao || !dlg) return;
  var form = dlg.querySelector("form");
  form.reset();
  form.action = botao.getAttribute("data-entrega");
  dlg.querySelector("[data-guia-num]").textContent = botao.getAttribute("data-guia");
  dlg.showModal();
  form.querySelector("[name=retirado_por]").focus();
});
// Botão "Copiar texto": copia o conteúdo do campo indicado em data-copiar
document.addEventListener("click", function (e) {
  var botao = e.target.closest("[data-copiar]");
  if (!botao) return;
  var campo = document.getElementById(botao.getAttribute("data-copiar"));
  if (!campo) return;
  var rotulo = botao.querySelector("span") || botao;
  var avisar = function () {
    var antes = rotulo.textContent;
    rotulo.textContent = "Copiado!";
    setTimeout(function () { rotulo.textContent = antes; }, 2000);
  };
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(campo.value).then(avisar);
  } else {  // http sem HTTPS (ex.: acesso pela rede interna): método antigo
    campo.select();
    document.execCommand("copy");
    avisar();
  }
});
