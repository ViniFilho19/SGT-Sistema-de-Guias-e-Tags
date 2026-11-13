/* Comportamentos globais (CSP proíbe JS inline como onsubmit/onclick). */
document.addEventListener("click", function (e) {
  if (e.target.closest("[data-print]")) window.print();
});
// <form data-confirm="Pergunta?"> pede confirmação antes de enviar
document.addEventListener("submit", function (e) {
  var msg = e.target.getAttribute && e.target.getAttribute("data-confirm");
  if (msg && !window.confirm(msg)) e.preventDefault();
});
