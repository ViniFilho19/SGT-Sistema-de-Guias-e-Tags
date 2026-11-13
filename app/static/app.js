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
