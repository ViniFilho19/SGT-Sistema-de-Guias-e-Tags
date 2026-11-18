/* Comportamentos globais (CSP proíbe JS inline como onsubmit/onclick). */
document.addEventListener("click", function (e) {
  if (e.target.closest("[data-print]")) window.print();
});
// <select data-auto-enviar> envia o formulário assim que a opção muda (ex.: ordenação da lista)
document.addEventListener("change", function (e) {
  if (e.target.matches && e.target.matches("select[data-auto-enviar]") && e.target.form) e.target.form.submit();
});
// <form data-confirm="Pergunta?"> pede confirmação antes de enviar
document.addEventListener("submit", function (e) {
  var msg = e.target.getAttribute && e.target.getAttribute("data-confirm");
  if (msg && !window.confirm(msg)) e.preventDefault();
});
// <button data-confirmar="Pergunta?"> pede confirmação só para esse botão
document.addEventListener("click", function (e) {
  var botao = e.target.closest("[data-confirmar]");
  if (botao && !window.confirm(botao.getAttribute("data-confirmar"))) e.preventDefault();
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
// Botão de tema claro/escuro
document.addEventListener("click", function (e) {
  if (!e.target.closest("[data-tema]")) return;
  var escuro = document.documentElement.classList.toggle("dark");
  try { localStorage.setItem("tema", escuro ? "escuro" : "claro"); } catch (err) {}
});
// Relatórios: mostra só os campos do período escolhido (mês, semestre, ano ou datas)
(function () {
  var form = document.querySelector("form[data-periodos]");
  if (!form) return;
  var sel = form.querySelector("[name=periodo]");
  function aplicar() {
    form.querySelectorAll("[data-periodo]").forEach(function (l) {
      var ativo = l.getAttribute("data-periodo") === sel.value;
      l.hidden = !ativo;
      l.querySelectorAll("input,select").forEach(function (c) { c.disabled = !ativo; });
    });
  }
  sel.addEventListener("change", aplicar);
  aplicar();
  // "Status da entrega" só vale para guias de saída: some quando o tipo é entrada ou etiquetas
  var tipo = form.querySelector("[name=tipo]"), st = form.querySelector("[data-status]");
  function status() {
    var usa = ["entrada", "etiquetas"].indexOf(tipo.value) < 0;
    st.hidden = !usa;
    st.querySelector("select").disabled = !usa;
  }
  if (tipo && st) { tipo.addEventListener("change", status); status(); }
})();
